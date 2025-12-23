"""NerveEngine - Wraps core with event emission.

The engine uses core primitives (Nodes, Graphs, etc.) and emits
events for state changes. It's the bridge between pure core
and the event-driven server world.

Node-based terminology (clean break from Channel/DAG):
- Nodes replace Channels
- Graphs replace DAGs
- Steps replace Tasks
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from nerve.core.nodes import (
    ExecutionContext,
    Graph,
    NodeFactory,
    NodeState,
    Step,
    TerminalNode,
)
from nerve.core.channels.history import HistoryReader
from nerve.core.parsers import get_parser
from nerve.core.session import Session
from nerve.core.types import ParserType
from nerve.server.protocols import (
    Command,
    CommandResult,
    CommandType,
    Event,
    EventSink,
    EventType,
)


@dataclass
class NerveEngine:
    """Main nerve engine - wraps core with event emission.

    The engine:
    - Uses core.NodeFactory, core.Graph, etc. for actual work
    - Emits events through EventSink for state changes
    - Handles commands from transport layer

    This layer knows about core, but not about:
    - Specific transports (that's the transport layer)
    - Frontends (that's the frontends layer)

    Example:
        >>> sink = MyEventSink()
        >>> engine = NerveEngine(event_sink=sink)
        >>>
        >>> result = await engine.execute(Command(
        ...     type=CommandType.CREATE_NODE,
        ...     params={"node_id": "my-claude", "command": "claude"},
        ... ))
        >>>
        >>> node_id = result.data["node_id"]  # "my-claude"
    """

    event_sink: EventSink
    _server_name: str = field(default="default")
    _node_factory: NodeFactory | None = field(default=None, repr=False)
    _nodes: dict[str, TerminalNode] = field(default_factory=dict, repr=False)
    _session: Session | None = field(default=None, repr=False)
    _running_graphs: dict[str, asyncio.Task] = field(default_factory=dict)
    _shutdown_requested: bool = field(default=False, repr=False)

    def __post_init__(self):
        """Initialize node factory and session."""
        if self._node_factory is None:
            self._node_factory = NodeFactory(server_name=self._server_name)
        if self._session is None:
            self._session = Session()

    @property
    def shutdown_requested(self) -> bool:
        """Whether shutdown has been requested."""
        return self._shutdown_requested

    async def execute(self, command: Command) -> CommandResult:
        """Execute a command.

        This is the single entry point for all operations.

        Args:
            command: The command to execute.

        Returns:
            CommandResult with success/failure and data.
        """
        handlers = {
            # Node management
            CommandType.CREATE_NODE: self._create_node,
            CommandType.STOP_NODE: self._stop_node,
            CommandType.LIST_NODES: self._list_nodes,
            CommandType.GET_NODE: self._get_node,
            # Interaction
            CommandType.RUN_COMMAND: self._run_command,
            CommandType.EXECUTE_INPUT: self._execute_input,
            CommandType.SEND_INTERRUPT: self._send_interrupt,
            CommandType.WRITE_DATA: self._write_data,
            CommandType.GET_BUFFER: self._get_buffer,
            CommandType.GET_HISTORY: self._get_history,
            # Graph execution
            CommandType.EXECUTE_GRAPH: self._execute_graph,
            CommandType.CANCEL_GRAPH: self._cancel_graph,
            # Server control
            CommandType.SHUTDOWN: self._shutdown,
            CommandType.PING: self._ping,
        }

        handler = handlers.get(command.type)
        if not handler:
            return CommandResult(
                success=False,
                error=f"Unknown command type: {command.type}",
                request_id=command.request_id,
            )

        try:
            data = await handler(command.params)
            return CommandResult(
                success=True,
                data=data,
                request_id=command.request_id,
            )
        except Exception as e:
            return CommandResult(
                success=False,
                error=str(e),
                request_id=command.request_id,
            )

    async def _emit(
        self,
        event_type: EventType,
        data: dict[str, Any] | None = None,
        node_id: str | None = None,
    ) -> None:
        """Emit an event through the sink.

        Args:
            event_type: The type of event.
            data: Event payload data.
            node_id: Associated node ID.
        """
        event = Event(
            type=event_type,
            data=data or {},
            node_id=node_id,
        )
        await self.event_sink.emit(event)

    # =========================================================================
    # Node Commands
    # =========================================================================

    async def _create_node(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new node.

        Requires node_id (name) in params. Names must be unique.
        """
        node_id = params.get("node_id")
        if not node_id:
            raise ValueError("Node ID is required")

        # Check for duplicate
        if node_id in self._nodes:
            raise ValueError(f"Node already exists: {node_id}")

        command = params.get("command")  # e.g., "claude" or ["claude", "--flag"]
        cwd = params.get("cwd")
        backend = params.get("backend", "pty")  # "pty" or "wezterm"
        pane_id = params.get("pane_id")  # For attaching to existing WezTerm pane
        history = params.get("history", True)  # Enable history by default

        node = await self._node_factory.create_terminal(
            node_id=node_id,
            command=command,
            backend=backend,
            cwd=cwd,
            pane_id=pane_id,
            history=history,
        )

        # Register with session and track locally
        self._session.register(node)
        self._nodes[node_id] = node

        await self._emit(
            EventType.NODE_CREATED,
            data={
                "command": command,
                "cwd": cwd,
                "backend": backend,
                "pane_id": getattr(node, "pane_id", None),
            },
            node_id=node.id,
        )

        # Start monitoring the node
        asyncio.create_task(self._monitor_node(node))

        return {"node_id": node.id}

    async def _stop_node(self, params: dict[str, Any]) -> dict[str, Any]:
        """Stop a node."""
        node_id = params.get("node_id")

        node = self._nodes.get(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        await node.stop()
        del self._nodes[node_id]

        await self._emit(EventType.NODE_STOPPED, node_id=node_id)

        return {"stopped": True}

    async def _list_nodes(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all nodes."""
        node_ids = list(self._nodes.keys())
        nodes_info = []

        for nid in node_ids:
            node = self._nodes.get(nid)
            if node:
                info = node.to_info()
                nodes_info.append({
                    "id": nid,
                    "type": info.node_type,
                    "state": info.state.name,
                    **info.metadata,
                })

        return {
            "nodes": node_ids,
            "nodes_info": nodes_info,
        }

    async def _get_node(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get node info."""
        node_id = params.get("node_id")
        node = self._nodes.get(node_id)

        if not node:
            raise ValueError(f"Node not found: {node_id}")

        info = node.to_info()
        result = {
            "node_id": node.id,
            "type": info.node_type,
            "state": info.state.name,
        }

        # Add optional metadata
        if "backend" in info.metadata:
            result["backend"] = info.metadata["backend"]
        if "pane_id" in info.metadata:
            result["pane_id"] = info.metadata["pane_id"]

        return result

    # =========================================================================
    # Interaction Commands
    # =========================================================================

    async def _run_command(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run a command in a node (fire and forget).

        This starts a program that takes over the terminal (like claude, python, etc.)
        without waiting for a response. Use EXECUTE_INPUT to interact with it after.
        """
        node_id = params.get("node_id")
        command = params["command"]

        node = self._nodes.get(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        await node.run(command)

        return {"started": True, "command": command}

    async def _execute_input(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute input on a node and wait for response."""
        node_id = params.get("node_id")
        text = params["text"]
        parser_str = params.get("parser")  # None means use node's default
        stream = params.get("stream", False)
        submit = params.get("submit")  # Custom submit sequence (optional)

        node = self._nodes.get(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        # Convert parser string to ParserType, or None to use node's default
        parser_type = ParserType(parser_str) if parser_str else None

        await self._emit(EventType.NODE_BUSY, node_id=node_id)

        # Create execution context
        context = ExecutionContext(
            session=self._session,
            input=text,
        )

        if stream:
            # Stream output chunks as events
            stream_context = ExecutionContext(
                session=self._session,
                input=text,
                parser=parser_type,
            )
            async for chunk in node.execute_stream(stream_context):
                await self._emit(
                    EventType.OUTPUT_CHUNK,
                    data={"chunk": chunk},
                    node_id=node_id,
                )

            # Parse final response
            actual_parser = parser_type or ParserType.NONE
            parser = get_parser(actual_parser)
            response = parser.parse(node.buffer)
        else:
            # Wait for complete response using ExecutionContext
            context.parser = parser_type
            response = await node.execute(context)

        await self._emit(
            EventType.OUTPUT_PARSED,
            data={
                "raw": response.raw,
                "sections": [
                    {"type": s.type, "content": s.content, "metadata": s.metadata}
                    for s in response.sections
                ],
                "tokens": response.tokens,
            },
            node_id=node_id,
        )

        await self._emit(EventType.NODE_READY, node_id=node_id)

        return {
            "response": {
                "raw": response.raw,
                "sections": [
                    {"type": s.type, "content": s.content, "metadata": s.metadata}
                    for s in response.sections
                ],
                "tokens": response.tokens,
                "is_complete": response.is_complete,
                "is_ready": response.is_ready,
            }
        }

    async def _send_interrupt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send interrupt to a node."""
        node_id = params.get("node_id")

        node = self._nodes.get(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        await node.interrupt()

        return {"interrupted": True}

    async def _write_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write raw data to a node (no waiting)."""
        node_id = params.get("node_id")
        data = params["data"]

        node = self._nodes.get(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        await node.write(data)

        return {"written": len(data)}

    async def _get_buffer(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get node buffer."""
        node_id = params.get("node_id")
        lines = params.get("lines")

        node = self._nodes.get(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        if lines:
            buffer = node.read_tail(lines)
        else:
            buffer = await node.read()

        return {"buffer": buffer}

    async def _get_history(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get node history.

        Reads the JSONL history file for a node.

        Parameters:
            node_id: The node ID (required)
            server_name: Server name (optional, defaults to engine's server name)
            last: Limit to last N entries (optional)
            op: Filter by operation type (optional)
            inputs_only: Filter to input operations only (optional)

        Returns:
            Dict with node_id, server_name, entries, and total count.
        """
        node_id = params.get("node_id")
        if not node_id:
            raise ValueError("node_id is required")

        server_name = params.get("server_name", self._server_name)
        last = params.get("last")
        op = params.get("op")
        inputs_only = params.get("inputs_only", False)

        try:
            reader = HistoryReader.create(
                channel_id=node_id,  # HistoryReader still uses channel_id internally
                server_name=server_name,
                base_dir=self._node_factory.history_base_dir,
            )

            # Apply filters
            if inputs_only:
                entries = reader.get_inputs_only()
            elif op:
                entries = reader.get_by_op(op)
            else:
                entries = reader.get_all()

            # Apply limit if specified
            if last is not None and last < len(entries):
                entries = entries[-last:]

            return {
                "node_id": node_id,
                "server_name": server_name,
                "entries": entries,
                "total": len(entries),
            }

        except FileNotFoundError:
            # Fail soft - return empty results with note
            return {
                "node_id": node_id,
                "server_name": server_name,
                "entries": [],
                "total": 0,
                "note": "No history found for this node",
            }

    # =========================================================================
    # Graph Commands
    # =========================================================================

    async def _execute_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a graph."""
        graph_id = params.get("graph_id", "graph_0")
        steps_data = params["steps"]

        # Build Graph from step definitions
        graph = self._node_factory.create_graph(graph_id)

        for step_data in steps_data:
            step_id = step_data["id"]
            node_id = step_data.get("node_id")
            text = step_data.get("text", "")
            parser_str = step_data.get("parser", "none")
            depends_on = step_data.get("depends_on", [])

            # Get the node for this step
            node = self._nodes.get(node_id)
            if not node:
                raise ValueError(f"Node not found: {node_id}")

            # Create step with input template
            graph.add_step(
                node=node,
                step_id=step_id,
                input=text,
                depends_on=depends_on,
            )

        await self._emit(EventType.GRAPH_STARTED, data={"graph_id": graph_id})

        # Create context with session
        context = ExecutionContext(session=self._session)

        # Execute graph with streaming
        results = {}
        async for event in graph.stream(context):
            if event.event == "step_started":
                await self._emit(
                    EventType.STEP_STARTED,
                    data={"step_id": event.step_id},
                )
            elif event.event == "step_completed":
                results[event.step_id] = event.output
                await self._emit(
                    EventType.STEP_COMPLETED,
                    data={"step_id": event.step_id, "output": str(event.output)[:500]},
                )
            elif event.event == "step_failed":
                await self._emit(
                    EventType.STEP_FAILED,
                    data={"step_id": event.step_id, "error": str(event.error)},
                )

        await self._emit(
            EventType.GRAPH_COMPLETED,
            data={"graph_id": graph_id, "step_count": len(results)},
        )

        return {
            "graph_id": graph_id,
            "results": {
                step_id: {"output": str(output)[:500]}
                for step_id, output in results.items()
            },
        }

    async def _cancel_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cancel a running graph."""
        graph_id = params["graph_id"]

        task = self._running_graphs.get(graph_id)
        if task:
            task.cancel()
            del self._running_graphs[graph_id]
            return {"cancelled": True}

        return {"cancelled": False, "error": "Graph not found"}

    # =========================================================================
    # Server Control Commands
    # =========================================================================

    async def _shutdown(self, params: dict[str, Any]) -> dict[str, Any]:
        """Shutdown the server.

        Returns immediately after initiating shutdown. Cleanup happens async.
        """
        # Set shutdown flag first so serve loop will exit
        self._shutdown_requested = True

        # Emit shutdown event
        await self._emit(EventType.SERVER_SHUTDOWN)

        # Schedule cleanup in background (don't await)
        asyncio.create_task(self._cleanup_on_shutdown())

        return {"shutdown": True}

    async def _cleanup_on_shutdown(self) -> None:
        """Background cleanup during shutdown."""
        # Cancel all running graphs
        for _graph_id, task in self._running_graphs.items():
            task.cancel()
        self._running_graphs.clear()

        # Stop all nodes
        for node_id, node in list(self._nodes.items()):
            try:
                await node.stop()
            except Exception:
                pass  # Best effort cleanup
        self._nodes.clear()

    async def _ping(self, params: dict[str, Any]) -> dict[str, Any]:
        """Ping the server to check if it's alive."""
        return {
            "pong": True,
            "nodes": len(self._nodes),
            "graphs": len(self._running_graphs),
        }

    # =========================================================================
    # Internal
    # =========================================================================

    async def _monitor_node(self, node: TerminalNode) -> None:
        """Monitor node for state changes.

        This runs in the background and emits events when
        the node state changes.
        """
        last_state = node.state

        while node.state != NodeState.STOPPED:
            await asyncio.sleep(0.5)

            if node.state != last_state:
                if node.state == NodeState.READY:
                    await self._emit(EventType.NODE_READY, node_id=node.id)
                elif node.state == NodeState.BUSY:
                    await self._emit(EventType.NODE_BUSY, node_id=node.id)

                last_state = node.state
