"""NerveEngine - Command dispatcher and event emitter.

NerveEngine is a thin wrapper that:
- Dispatches commands to Session methods
- Emits events for state changes
- Manages multiple sessions (multi-workspace)

Session is the single source of truth for nodes and graphs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from nerve.core.nodes import (
    ExecutionContext,
    NodeState,
)
from nerve.core.nodes.history import HistoryReader
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
    """Command dispatcher and event emitter.

    NerveEngine is the server-layer adapter that:
    - Dispatches commands to Session methods
    - Emits events for state changes
    - Manages multiple sessions (multi-workspace)

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
    _default_session: Session | None = field(default=None, repr=False)
    _sessions: dict[str, Session] = field(default_factory=dict, repr=False)
    _python_namespaces: dict[str, dict[str, Any]] = field(
        default_factory=dict, repr=False
    )  # session_id -> namespace
    _running_graphs: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    _shutdown_requested: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize default session."""
        if self._default_session is None:
            self._default_session = Session(
                name="default",
                server_name=self._server_name,
            )
        self._sessions[self._default_session.name] = self._default_session

    @property
    def shutdown_requested(self) -> bool:
        """Whether shutdown has been requested."""
        return self._shutdown_requested

    def _get_session(self, params: dict[str, Any]) -> Session:
        """Get session from params or return default.

        Args:
            params: Command parameters (may contain session_id which is actually the session name).

        Returns:
            The requested session or default session.

        Raises:
            ValueError: If session_id is provided but not found.
        """
        session_name = params.get("session_id")  # session_id param is actually the name
        if session_name:
            session = self._sessions.get(session_name)
            if session is None:
                raise ValueError(f"Session not found: {session_name}")
            return session
        assert self._default_session is not None
        return self._default_session

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
            CommandType.DELETE_NODE: self._delete_node,
            CommandType.LIST_NODES: self._list_nodes,
            CommandType.GET_NODE: self._get_node,
            # Interaction
            CommandType.RUN_COMMAND: self._run_command,
            CommandType.EXECUTE_INPUT: self._execute_input,
            CommandType.EXECUTE_PYTHON: self._execute_python,
            CommandType.EXECUTE_REPL_COMMAND: self._execute_repl_command,
            CommandType.SEND_INTERRUPT: self._send_interrupt,
            CommandType.WRITE_DATA: self._write_data,
            CommandType.GET_BUFFER: self._get_buffer,
            CommandType.GET_HISTORY: self._get_history,
            # Graph execution (ad-hoc)
            CommandType.EXECUTE_GRAPH: self._execute_graph,
            CommandType.CANCEL_GRAPH: self._cancel_graph,
            # Session management
            CommandType.CREATE_SESSION: self._create_session,
            CommandType.DELETE_SESSION: self._delete_session,
            CommandType.LIST_SESSIONS: self._list_sessions,
            CommandType.GET_SESSION: self._get_session_info,
            # Graph management
            CommandType.CREATE_GRAPH: self._create_graph,
            CommandType.DELETE_GRAPH: self._delete_graph,
            CommandType.LIST_GRAPHS: self._list_graphs,
            CommandType.GET_GRAPH: self._get_graph_info,
            CommandType.RUN_GRAPH: self._run_graph,
            # Server control
            CommandType.STOP: self._stop,
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
        Uses direct node class instantiation with session parameter.

        Parameters:
            node_id: Node identifier (required)
            command: Command to run (e.g., "claude" or ["claude", "--flag"])
            cwd: Working directory
            backend: Node backend ("pty", "wezterm", "claude-wezterm")
            pane_id: For attaching to existing WezTerm pane
            history: Enable history logging (default: True)
            response_timeout: Max wait for terminal response in seconds (default: 1800.0)
            ready_timeout: Max wait for terminal ready state in seconds (default: 60.0)
        """
        from nerve.core.nodes.terminal import (
            ClaudeWezTermNode,
            PTYNode,
            WezTermNode,
        )

        session = self._get_session(params)

        node_id = params.get("node_id")
        if not node_id:
            raise ValueError("node_id is required")
        command = params.get("command")  # e.g., "claude" or ["claude", "--flag"]
        cwd = params.get("cwd")
        backend = params.get("backend", "pty")  # "pty" or "wezterm"
        pane_id = params.get("pane_id")  # For attaching to existing WezTerm pane
        history = params.get("history", True)  # Enable history by default
        response_timeout = params.get("response_timeout", 1800.0)
        ready_timeout = params.get("ready_timeout", 60.0)

        # Dispatch to appropriate node class based on backend
        node: PTYNode | WezTermNode | ClaudeWezTermNode
        if backend == "pty":
            node = await PTYNode.create(
                id=str(node_id),
                session=session,
                command=command,
                cwd=cwd,
                history=history,
                response_timeout=response_timeout,
                ready_timeout=ready_timeout,
            )
        elif backend == "wezterm":
            if pane_id:
                # Attach to existing pane
                node = await WezTermNode.attach(
                    id=str(node_id),
                    session=session,
                    pane_id=pane_id,
                    history=history,
                    response_timeout=response_timeout,
                    ready_timeout=ready_timeout,
                )
            else:
                # Create new pane
                node = await WezTermNode.create(
                    id=str(node_id),
                    session=session,
                    command=command,
                    cwd=cwd,
                    history=history,
                    response_timeout=response_timeout,
                    ready_timeout=ready_timeout,
                )
        elif backend == "claude-wezterm":
            if not command:
                raise ValueError("command is required for claude-wezterm backend")
            node = await ClaudeWezTermNode.create(
                id=str(node_id),
                session=session,
                command=command,
                cwd=cwd,
                history=history,
                response_timeout=response_timeout,
                ready_timeout=ready_timeout,
            )
        else:
            raise ValueError(f"Unknown backend: {backend}")

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

    async def _delete_node(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete a node."""
        session = self._get_session(params)
        node_id = params.get("node_id")
        if not node_id:
            raise ValueError("node_id is required")

        deleted = await session.delete_node(str(node_id))
        if not deleted:
            raise ValueError(f"Node not found: {node_id}")

        await self._emit(EventType.NODE_DELETED, node_id=node_id)

        return {"deleted": True}

    async def _list_nodes(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all nodes."""
        session = self._get_session(params)

        node_ids = session.list_nodes()
        nodes_info = []

        for nid in node_ids:
            node = session.get_node(nid)
            if node and hasattr(node, "to_info"):
                info = node.to_info()
                nodes_info.append(
                    {
                        "id": nid,
                        "type": info.node_type,
                        "state": info.state.name,
                        **info.metadata,
                    }
                )

        return {
            "nodes": node_ids,
            "nodes_info": nodes_info,
        }

    async def _get_node(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get node info."""
        session = self._get_session(params)
        node_id = params.get("node_id")
        if not node_id:
            raise ValueError("node_id is required")

        node = session.get_node(str(node_id))
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        info = node.to_info()  # type: ignore[attr-defined]
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
        session = self._get_session(params)
        node_id = params.get("node_id")
        if not node_id:
            raise ValueError("node_id is required")
        command = params["command"]

        node = session.get_node(str(node_id))
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        await node.run(command)  # type: ignore[attr-defined]

        return {"started": True, "command": command}

    async def _execute_input(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute input on a node and wait for response.

        Parameters:
            node_id: Node identifier (required)
            text: Input text to send (required)
            parser: Parser type ("claude", "gemini", "none")
            stream: Stream output as events (default: False)
            timeout: Override node's response_timeout for this execution (optional)
        """
        session = self._get_session(params)
        node_id = params.get("node_id")
        if not node_id:
            raise ValueError("node_id is required")
        text = params["text"]
        parser_str = params.get("parser")  # None means use node's default
        stream = params.get("stream", False)
        timeout = params.get("timeout")  # Optional per-execution timeout override

        node = session.get_node(str(node_id))
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        # Convert parser string to ParserType, or None to use node's default
        parser_type = ParserType(parser_str) if parser_str else None

        await self._emit(EventType.NODE_BUSY, node_id=node_id)

        # Create execution context with optional timeout
        context = ExecutionContext(
            session=session,
            input=text,
            timeout=timeout,
        )

        if stream:
            # Stream output chunks as events
            stream_context = ExecutionContext(
                session=session,
                input=text,
                parser=parser_type,
                timeout=timeout,
            )
            async for chunk in node.execute_stream(stream_context):  # type: ignore[attr-defined]
                await self._emit(
                    EventType.OUTPUT_CHUNK,
                    data={"chunk": chunk},
                    node_id=node_id,
                )

            # Parse final response
            actual_parser = parser_type or ParserType.NONE
            parser = get_parser(actual_parser)
            response = parser.parse(node.buffer)  # type: ignore[attr-defined]
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

    def _pretty_print_value(self, value: Any) -> str:
        """Pretty-print a value for REPL display.

        Handles special cases like ParsedResponse objects and converts them to JSON.
        """
        import json
        from dataclasses import asdict, is_dataclass

        # Convert dataclasses to dicts for JSON serialization
        def convert_to_serializable(obj: Any) -> Any:
            if is_dataclass(obj) and not isinstance(obj, type):
                return asdict(obj)
            elif isinstance(obj, dict):
                return {k: convert_to_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [convert_to_serializable(item) for item in obj]
            else:
                return obj

        try:
            serializable = convert_to_serializable(value)
            return json.dumps(serializable, indent=2)
        except (TypeError, ValueError):
            # Fall back to repr if JSON serialization fails
            return repr(value)

    async def _execute_python(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute Python code in server's interpreter.

        The code executes in a namespace associated with the session.
        This allows REPL clients to maintain Python state across commands.

        Args:
            params: Must contain "code" (Python code string).
                    May contain "session_id" (uses default if not provided).

        Returns:
            dict with "output" (captured stdout/result) and "error" (if any).
        """
        import io
        from code import compile_command
        from contextlib import redirect_stderr, redirect_stdout

        session = self._get_session(params)
        code_str = params.get("code", "")

        if not code_str.strip():
            return {"output": "", "error": None}

        # Get or create namespace for this session
        session_id = session.name
        if session_id not in self._python_namespaces:
            # Initialize namespace with nerve imports and session
            from nerve.core import ParserType
            from nerve.core.nodes import (
                ExecutionContext,
                FunctionNode,
            )
            from nerve.core.nodes.bash import BashNode
            from nerve.core.nodes.graph import Graph
            from nerve.core.nodes.terminal import (
                ClaudeWezTermNode,
                PTYNode,
                WezTermNode,
            )

            self._python_namespaces[session_id] = {
                "asyncio": asyncio,
                # Node classes (use with session parameter)
                "BashNode": BashNode,
                "FunctionNode": FunctionNode,
                "Graph": Graph,
                "PTYNode": PTYNode,
                "WezTermNode": WezTermNode,
                "ClaudeWezTermNode": ClaudeWezTermNode,
                # Other useful classes
                "ExecutionContext": ExecutionContext,
                "Session": Session,
                "ParserType": ParserType,
                # Pre-configured instances
                "session": session,  # The actual session
                "context": ExecutionContext(session=session),  # Pre-configured context
            }

        namespace = self._python_namespaces[session_id]

        # Capture output
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                # Handle async code (contains await)
                if "await " in code_str:
                    # Wrap in async function that returns local variables
                    async_code = "async def __repl_async__():\n"
                    for line in code_str.split("\n"):
                        async_code += f"    {line}\n"
                    async_code += "    return locals()\n"

                    # Compile and execute the function definition
                    exec(compile(async_code, "<repl>", "exec"), namespace)

                    # Call the async function and get its local variables
                    func_locals = await namespace["__repl_async__"]()

                    # Update namespace with variables from the function
                    # (skip private variables and built-in names)
                    for key, value in func_locals.items():
                        if not key.startswith("_"):
                            namespace[key] = value
                            # Print value if it's a standalone expression result
                            if key == "result" and value is not None:
                                print(self._pretty_print_value(value))
                else:
                    # Try to compile as a complete statement
                    code_obj = compile_command(code_str, "<repl>", "single")

                    if code_obj is None:
                        # Incomplete code
                        return {
                            "output": "",
                            "error": "SyntaxError: unexpected EOF while parsing (incomplete code)",
                        }

                    # Execute synchronous code
                    exec(code_obj, namespace)

            # Get captured output
            output = stdout_capture.getvalue()
            error_output = stderr_capture.getvalue()

            if error_output:
                output = error_output if not output else output + "\n" + error_output

            return {
                "output": output,
                "error": None,
            }

        except SyntaxError as e:
            return {
                "output": "",
                "error": f"SyntaxError: {e}",
            }
        except Exception as e:
            import traceback

            return {
                "output": "",
                "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            }

    async def _execute_repl_command(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute REPL command (show, dry, validate, etc.) on server.

        Args:
            params: Must contain "command" (command name like "show", "dry").
                    May contain "args" (list of command arguments).
                    May contain "session_id" (uses default if not provided).

        Returns:
            dict with "output" (formatted command output) and "error" (if any).
        """
        import io

        session = self._get_session(params)
        command = params.get("command", "")
        args = params.get("args", [])

        try:
            output_buffer = io.StringIO()

            if command == "show":
                # show [graph-name]
                graph_id = args[0] if args else None
                graph = session.get_graph(graph_id) if graph_id else None

                if not graph:
                    return {"output": "", "error": f"Graph not found: {graph_id}"}

                if not graph.list_steps():
                    output_buffer.write("No steps defined\n")
                else:
                    output_buffer.write("\nGraph Structure:\n")
                    output_buffer.write("-" * 40 + "\n")
                    for step_id in graph.list_steps():
                        step = graph.get_step(step_id)
                        deps = step.depends_on if step else []
                        output_buffer.write(f"  {step_id}\n")
                        if deps:
                            output_buffer.write(f"    depends on: {', '.join(deps)}\n")
                    output_buffer.write("-" * 40 + "\n")

            elif command == "dry":
                # dry [graph-name]
                graph_id = args[0] if args else None
                graph = session.get_graph(graph_id) if graph_id else None

                if not graph:
                    return {"output": "", "error": f"Graph not found: {graph_id}"}

                try:
                    order = graph.execution_order()
                    output_buffer.write("\nExecution order:\n")
                    for i, step_id in enumerate(order, 1):
                        output_buffer.write(f"  [{i}] {step_id}\n")
                except ValueError as e:
                    return {"output": "", "error": str(e)}

            elif command == "validate":
                # validate [graph-name]
                graph_id = args[0] if args else None
                graph = session.get_graph(graph_id) if graph_id else None

                if not graph:
                    return {"output": "", "error": f"Graph not found: {graph_id}"}

                errors = graph.validate()
                if errors:
                    output_buffer.write("Validation FAILED:\n")
                    for err in errors:
                        output_buffer.write(f"  - {err}\n")
                else:
                    output_buffer.write("Validation PASSED\n")

            elif command == "list":
                # list [nodes|graphs]
                what = args[0] if args else "nodes"

                if what == "graphs":
                    graphs = session.list_graphs()
                    if graphs:
                        output_buffer.write("\nGraphs:\n")
                        for g in graphs:
                            output_buffer.write(f"  - {g}\n")
                    else:
                        output_buffer.write("No graphs defined\n")
                else:  # nodes
                    if session.nodes:
                        output_buffer.write("\nNodes:\n")
                        for name, node in session.nodes.items():
                            if hasattr(node, "state"):
                                info = node.state.name
                            else:
                                info = type(node).__name__
                            output_buffer.write(f"  {name}: {info}\n")
                    else:
                        output_buffer.write("No nodes defined\n")

            elif command == "read":
                # read <node-name>
                if not args:
                    return {"output": "", "error": "Usage: read <node>"}

                node_name = args[0]
                read_node = session.get_node(node_name)
                if not read_node:
                    return {"output": "", "error": f"Node not found: {node_name}"}

                if hasattr(read_node, "read"):
                    buffer_content = await read_node.read()
                    output_buffer.write(buffer_content)
                else:
                    return {"output": "", "error": "Node does not support read"}

            else:
                return {"output": "", "error": f"Unknown REPL command: {command}"}

            return {
                "output": output_buffer.getvalue(),
                "error": None,
            }

        except Exception as e:
            import traceback

            return {
                "output": "",
                "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            }

    async def _send_interrupt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send interrupt to a node."""
        session = self._get_session(params)
        node_id = params.get("node_id")
        if not node_id:
            raise ValueError("node_id is required")

        node = session.get_node(str(node_id))
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        await node.interrupt()

        return {"interrupted": True}

    async def _write_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write raw data to a node (no waiting)."""
        session = self._get_session(params)
        node_id = params.get("node_id")
        if not node_id:
            raise ValueError("node_id is required")
        data = params["data"]

        node = session.get_node(str(node_id))
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        await node.write(data)  # type: ignore[attr-defined]

        return {"written": len(data)}

    async def _get_buffer(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get node buffer."""
        session = self._get_session(params)
        node_id = params.get("node_id")
        if not node_id:
            raise ValueError("node_id is required")
        lines = params.get("lines")

        node = session.get_node(str(node_id))
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        if lines:
            buffer = node.read_tail(lines)  # type: ignore[attr-defined]
        else:
            buffer = await node.read()  # type: ignore[attr-defined]

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
        session = self._get_session(params)
        node_id = params.get("node_id")
        if not node_id:
            raise ValueError("node_id is required")

        server_name = params.get("server_name", self._server_name)
        last = params.get("last")
        op = params.get("op")
        inputs_only = params.get("inputs_only", False)

        try:
            reader = HistoryReader.create(
                node_id=node_id,
                server_name=server_name,
                session_name=session.name,
                base_dir=session.history_base_dir,
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
        from nerve.core.nodes.graph import Graph

        session = self._get_session(params)
        graph_id = params.get("graph_id", "graph_0")
        steps_data = params["steps"]

        # Build Graph from step definitions
        graph = Graph(id=graph_id, session=session)

        for step_data in steps_data:
            step_id = step_data["id"]
            node_id = step_data.get("node_id")
            text = step_data.get("text", "")
            depends_on = step_data.get("depends_on", [])

            # Get the node for this step
            node = session.get_node(node_id)
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
        context = ExecutionContext(session=session)

        # Execute graph with streaming
        results = {}
        async for event in graph.stream(context):  # type: ignore[attr-defined]
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
                step_id: {"output": str(output)[:500]} for step_id, output in results.items()
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
    # Session Management Commands
    # =========================================================================

    async def _create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new session.

        Parameters:
            name: Session name (required)
            description: Session description (optional)
            tags: Session tags (optional)

        Returns:
            Dict with session_id (which is the name).
        """
        name = params.get("name")
        if not name:
            raise ValueError("Session name is required")

        description = params.get("description", "")
        tags = params.get("tags", [])

        # Check for duplicate session name
        if name in self._sessions:
            raise ValueError(f"Session with name '{name}' already exists")

        session = Session(
            name=name,
            description=description,
            tags=tags,
            server_name=self._server_name,
        )
        self._sessions[session.name] = session

        await self._emit(
            EventType.SESSION_CREATED,
            data={
                "session_id": session.name,
                "name": session.name,
            },
        )

        return {
            "session_id": session.name,
            "name": session.name,
        }

    async def _delete_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete a session.

        Parameters:
            session_id: Session ID to delete (required)

        Returns:
            Dict with deleted status.
        """
        session_id = params.get("session_id")
        if not session_id:
            raise ValueError("session_id is required")

        assert self._default_session is not None
        if session_id == self._default_session.name:
            raise ValueError("Cannot delete the default session")

        session = self._sessions.pop(session_id, None)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        await session.stop()

        await self._emit(
            EventType.SESSION_DELETED,
            data={"session_id": session_id},
        )

        return {"deleted": True}

    async def _list_sessions(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all sessions.

        Returns:
            Dict with sessions list.
        """
        assert self._default_session is not None
        sessions = []
        for session in self._sessions.values():
            sessions.append(
                {
                    "id": session.name,  # id is the name
                    "name": session.name,
                    "description": session.description,
                    "tags": session.tags,
                    "node_count": len(session.nodes),
                    "graph_count": len(session.graphs),
                    "is_default": session.name == self._default_session.name,
                }
            )

        return {
            "sessions": sessions,
            "default_session_id": self._default_session.name,
        }

    async def _get_session_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get session info.

        Parameters:
            session_id: Session ID (optional, defaults to default session)

        Returns:
            Dict with session info including detailed node info.
        """
        assert self._default_session is not None
        session = self._get_session(params)

        # Get detailed node info
        node_ids = session.list_nodes()
        nodes_info = []
        for nid in node_ids:
            node = session.get_node(nid)
            if node and hasattr(node, "to_info"):
                info = node.to_info()
                nodes_info.append(
                    {
                        "id": nid,
                        "type": info.node_type,
                        "state": info.state.name,
                        **info.metadata,
                    }
                )

        return {
            "session_id": session.name,  # session_id is the name
            "name": session.name,
            "description": session.description,
            "tags": session.tags,
            "nodes": node_ids,
            "nodes_info": nodes_info,
            "graphs": session.list_graphs(),
            "is_default": session.name == self._default_session.name,
        }

    # =========================================================================
    # Graph Management Commands
    # =========================================================================

    async def _create_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create and register a graph in a session.

        Parameters:
            graph_id: Graph ID (required)
            session_id: Session ID (optional, defaults to default session)

        Returns:
            Dict with graph_id.
        """
        from nerve.core.nodes.graph import Graph

        session = self._get_session(params)
        graph_id = params.get("graph_id")

        if not graph_id:
            raise ValueError("graph_id is required")

        graph = Graph(id=graph_id, session=session)

        await self._emit(
            EventType.GRAPH_CREATED,
            data={"graph_id": graph_id},
        )

        return {"graph_id": graph.id}

    async def _delete_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete a graph from a session.

        Parameters:
            graph_id: Graph ID (required)
            session_id: Session ID (optional, defaults to default session)

        Returns:
            Dict with deleted status.
        """
        session = self._get_session(params)
        graph_id = params.get("graph_id")

        if not graph_id:
            raise ValueError("graph_id is required")

        deleted = session.delete_graph(graph_id)
        if not deleted:
            raise ValueError(f"Graph not found: {graph_id}")

        await self._emit(
            EventType.GRAPH_DELETED,
            data={"graph_id": graph_id},
        )

        return {"deleted": True}

    async def _list_graphs(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all graphs in a session.

        Parameters:
            session_id: Session ID (optional, defaults to default session)

        Returns:
            Dict with graphs list.
        """
        session = self._get_session(params)
        graph_ids = session.list_graphs()

        graphs = []
        for gid in graph_ids:
            graph = session.get_graph(gid)
            if graph is not None:
                graphs.append(
                    {
                        "id": gid,
                        "step_count": len(graph.list_steps()),
                    }
                )

        return {"graphs": graphs}

    async def _get_graph_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get graph info.

        Parameters:
            graph_id: Graph ID (required)
            session_id: Session ID (optional, defaults to default session)

        Returns:
            Dict with graph info.
        """
        session = self._get_session(params)
        graph_id = params.get("graph_id")

        if not graph_id:
            raise ValueError("graph_id is required")

        graph = session.get_graph(graph_id)
        if graph is None:
            raise ValueError(f"Graph not found: {graph_id}")

        steps = []
        for step_id in graph.list_steps():
            step = graph.get_step(step_id)
            if step is not None:
                # Get node ID (from node_ref or from node.id)
                node_id = None
                if step.node_ref:
                    node_id = step.node_ref
                elif step.node:
                    node_id = step.node.id

                steps.append(
                    {
                        "id": step_id,
                        "node_id": node_id,
                        "input": step.input,
                        "depends_on": step.depends_on,
                        # Note: input_fn, error_policy, parser are not serializable
                    }
                )

        return {
            "graph_id": graph_id,
            "steps": steps,
        }

    async def _run_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run a registered graph.

        Parameters:
            graph_id: Graph ID (required)
            session_id: Session ID (optional, defaults to default session)
            input: Initial input for the graph (optional)

        Returns:
            Dict with results.
        """
        session = self._get_session(params)
        graph_id = params.get("graph_id")
        initial_input = params.get("input")

        if not graph_id:
            raise ValueError("graph_id is required")

        graph = session.get_graph(graph_id)
        if graph is None:
            raise ValueError(f"Graph not found: {graph_id}")

        await self._emit(EventType.GRAPH_STARTED, data={"graph_id": graph_id})

        # Create context with session
        context = ExecutionContext(session=session, input=initial_input)

        # Execute graph with streaming
        results = {}
        async for event in graph.stream(context):  # type: ignore[attr-defined]
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
                step_id: {"output": str(output)[:500]} for step_id, output in results.items()
            },
        }

    # =========================================================================
    # Server Control Commands
    # =========================================================================

    async def _stop(self, params: dict[str, Any]) -> dict[str, Any]:
        """Stop the server.

        Returns immediately after initiating stop. Cleanup happens async.
        """
        # Set shutdown flag first so serve loop will exit
        self._shutdown_requested = True

        # Emit stop event
        await self._emit(EventType.SERVER_STOPPED)

        # Schedule cleanup in background (don't await)
        asyncio.create_task(self._cleanup_on_stop())

        return {"stopped": True}

    async def _cleanup_on_stop(self) -> None:
        """Background cleanup during stop."""
        # Cancel all running graphs
        for _graph_id, task in self._running_graphs.items():
            task.cancel()
        self._running_graphs.clear()

        # Stop all sessions
        for session in self._sessions.values():
            try:
                await session.stop()
            except Exception:
                pass  # Best effort cleanup

    async def _ping(self, params: dict[str, Any]) -> dict[str, Any]:
        """Ping the server to check if it's alive."""
        total_nodes = sum(len(s.nodes) for s in self._sessions.values())
        return {
            "pong": True,
            "nodes": total_nodes,
            "graphs": len(self._running_graphs),
            "sessions": len(self._sessions),
        }

    # =========================================================================
    # Internal
    # =========================================================================

    async def _monitor_node(self, node: Any) -> None:
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
