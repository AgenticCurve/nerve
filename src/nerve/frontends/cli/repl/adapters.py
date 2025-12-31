"""Session adapter abstraction for local vs remote sessions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from nerve.core.nodes import Graph

logger = logging.getLogger(__name__)


class SessionAdapter(Protocol):
    """Protocol for session operations in both local and remote modes.

    This protocol fully abstracts local vs remote mode differences.
    Command handlers should use these methods without checking mode.
    """

    @property
    def name(self) -> str:
        """Session name."""
        ...

    @property
    def id(self) -> str:
        """Session ID."""
        ...

    @property
    def node_count(self) -> int:
        """Number of nodes in session."""
        ...

    @property
    def graph_count(self) -> int:
        """Number of graphs in session."""
        ...

    @property
    def supports_local_execution(self) -> bool:
        """True if this adapter supports local-only operations (stop, run, reset)."""
        ...

    async def list_nodes(self) -> list[tuple[str, str]]:
        """List nodes as (name, info) tuples."""
        ...

    async def list_graphs(self) -> list[str]:
        """List graph IDs."""
        ...

    async def get_graph(self, graph_id: str) -> Graph | None:
        """Get graph by ID (returns Graph object or None)."""
        ...

    async def delete_node(self, node_id: str) -> bool:
        """Delete a node."""
        ...

    async def execute_on_node(self, node_id: str, text: str) -> dict[str, Any]:
        """Execute input on a node and return response dict.

        Returns dict with keys:
            success (bool): True if execution succeeded
            error (str | None): Error message if failed
            error_type (str | None): Error type if failed
            ... node-specific output fields (raw, stdout, content, output, etc.)
        """
        ...

    async def stop(self) -> None:
        """Stop session and cleanup."""
        ...

    # =========================================================================
    # Unified command methods - abstract local/remote differences
    # =========================================================================

    async def read_node_buffer(self, node_id: str) -> str:
        """Read a node's output buffer.

        Raises:
            ValueError: If node not found or doesn't support read.
        """
        ...

    async def stop_node(self, node_id: str) -> None:
        """Stop a running node.

        Raises:
            ValueError: If node not found or doesn't support stop.
            NotImplementedError: If not supported in remote mode.
        """
        ...

    async def show_graph(
        self, graph_id: str | None = None, fallback_graph: Graph | None = None
    ) -> str:
        """Get formatted graph structure for display.

        Args:
            graph_id: Explicit graph ID to show.
            fallback_graph: Fallback graph if graph_id not provided (local mode only).

        Returns:
            Formatted string ready for display.

        Raises:
            ValueError: If no graph found/specified.
        """
        ...

    async def validate_graph(
        self, graph_id: str | None = None, fallback_graph: Graph | None = None
    ) -> str:
        """Validate a graph and return formatted result.

        Args:
            graph_id: Explicit graph ID to validate.
            fallback_graph: Fallback graph if graph_id not provided (local mode only).

        Returns:
            Formatted validation result string.

        Raises:
            ValueError: If no graph found/specified.
        """
        ...

    async def dry_run_graph(
        self, graph_id: str | None = None, fallback_graph: Graph | None = None
    ) -> str:
        """Get formatted execution order for a graph.

        Args:
            graph_id: Explicit graph ID for dry run.
            fallback_graph: Fallback graph if graph_id not provided (local mode only).

        Returns:
            Formatted execution order string.

        Raises:
            ValueError: If no graph found/specified.
        """
        ...

    @property
    def server_name(self) -> str:
        """Server name for history file lookups."""
        ...


class LocalSessionAdapter:
    """Adapter for local in-memory session."""

    def __init__(self, session: Any):  # Session type
        self.session = session

    @property
    def name(self) -> str:
        return str(self.session.name)

    @property
    def id(self) -> str:
        return str(self.session.id)

    @property
    def node_count(self) -> int:
        return len(self.session.nodes)

    @property
    def graph_count(self) -> int:
        return len(self.session.graphs)

    @property
    def supports_local_execution(self) -> bool:
        return True

    async def list_nodes(self) -> list[tuple[str, str]]:
        """Return list of (name, info_string) tuples."""
        result = []
        for name, node in self.session.nodes.items():
            if hasattr(node, "state"):
                info = node.state.name
            else:
                info = type(node).__name__
            result.append((name, info))
        return result

    async def list_graphs(self) -> list[str]:
        result: list[str] = self.session.list_graphs()
        return result

    async def get_graph(self, graph_id: str) -> Graph | None:
        result: Graph | None = self.session.get_graph(graph_id)
        return result

    async def execute_graph(self, graph_id: str, input: Any = None) -> dict[str, Any]:
        """Execute a registered graph in local session.

        Args:
            graph_id: ID of the graph to execute.
            input: Optional input data for the graph.

        Returns:
            Dict with success, output, error, error_type, attributes fields
            (matches node execution format for seamless transparency).
        """
        from nerve.core.nodes.context import ExecutionContext

        graph = self.session.get_graph(graph_id)
        if not graph:
            return {
                "success": False,
                "error": f"Graph not found: {graph_id}",
                "error_type": "not_found",
                "node_type": "graph",
                "node_id": graph_id,
                "input": input,
                "output": None,
            }

        ctx = ExecutionContext(session=self.session, input=input)

        try:
            result = await graph.execute(ctx)
            # Graph.execute() already returns standardized dict
            return cast(dict[str, Any], result)
        except Exception as e:
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "error_type": "execution_error",
                "node_type": "graph",
                "node_id": graph_id,
                "input": input,
                "output": None,
            }

    async def delete_node(self, node_id: str) -> bool:
        result: bool = await self.session.delete_node(node_id)
        return result

    async def execute_on_node(self, node_id: str, text: str) -> dict[str, Any]:
        """Execute on a node (for send command)."""
        from nerve.core.nodes.context import ExecutionContext
        from nerve.core.nodes.terminal.claude_wezterm_node import ClaudeWezTermNode

        node = self.session.get_node(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        # Defensive: Log node details for debugging concurrent execution
        pane_id = getattr(node, "pane_id", "N/A")
        logger.debug(
            f"execute_on_node: node_id={node_id}, pane_id={pane_id}, "
            f"type={type(node).__name__}, input_len={len(text)}"
        )

        ctx = ExecutionContext(session=self.session, input=text)

        # Use execute_when_ready() for ClaudeWezTermNode to prevent concurrent execution
        if isinstance(node, ClaudeWezTermNode):
            result = await node.execute_when_ready(ctx)
        else:
            result = await node.execute(ctx)

        # All nodes now return dicts with success/error/error_type fields
        if not isinstance(result, dict):
            raise TypeError(
                f"Node {node_id} returned {type(result).__name__} instead of dict. "
                f"All nodes must return dict with success/error/error_type fields."
            )

        # Defensive: Add node_id to result for verification
        result["_executed_on_node_id"] = node_id
        result["_executed_on_pane_id"] = pane_id

        return result

    async def stop(self) -> None:
        await self.session.stop()

    # =========================================================================
    # Unified command methods
    # =========================================================================

    async def read_node_buffer(self, node_id: str) -> str:
        """Read a node's output buffer."""
        node = self.session.get_node(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")
        if not hasattr(node, "read"):
            raise ValueError(f"Node '{node_id}' does not support read")
        result = await node.read()
        return str(result) if result is not None else ""

    async def stop_node(self, node_id: str) -> None:
        """Stop a running node."""
        node = self.session.get_node(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")
        if not hasattr(node, "stop"):
            raise ValueError(f"Node '{node_id}' does not support stop")
        await node.stop()

    def _resolve_graph(self, graph_id: str | None, fallback_graph: Any | None) -> Any:
        """Resolve graph from ID or fallback."""
        if graph_id:
            graph = self.session.get_graph(graph_id)
            if not graph:
                raise ValueError(f"Graph not found: {graph_id}")
            return graph
        if fallback_graph:
            return fallback_graph
        raise ValueError("No graph specified")

    async def show_graph(
        self, graph_id: str | None = None, fallback_graph: Any | None = None
    ) -> str:
        """Get formatted graph structure for display."""
        graph = self._resolve_graph(graph_id, fallback_graph)

        if not graph.list_steps():
            return "No steps defined"

        lines = ["\nGraph Structure:", "-" * 40]
        for step_id in graph.list_steps():
            step = graph.get_step(step_id)
            deps = step.depends_on if step else []
            lines.append(f"  {step_id}")
            if deps:
                lines.append(f"    depends on: {', '.join(deps)}")
        lines.append("-" * 40)
        return "\n".join(lines)

    async def validate_graph(
        self, graph_id: str | None = None, fallback_graph: Any | None = None
    ) -> str:
        """Validate a graph and return formatted result."""
        graph = self._resolve_graph(graph_id, fallback_graph)

        errors = graph.validate()
        if errors:
            lines = ["Validation FAILED:"]
            for err in errors:
                lines.append(f"  - {err}")
            return "\n".join(lines)
        return "Validation PASSED"

    async def dry_run_graph(
        self, graph_id: str | None = None, fallback_graph: Any | None = None
    ) -> str:
        """Get formatted execution order for a graph."""
        graph = self._resolve_graph(graph_id, fallback_graph)

        order = graph.execution_order()
        lines = ["\nExecution order:"]
        for i, step_id in enumerate(order, 1):
            lines.append(f"  [{i}] {step_id}")
        return "\n".join(lines)

    @property
    def server_name(self) -> str:
        """Server name for history file lookups."""
        return str(self.session.server_name) if self.session.server_name else "repl"


class RemoteSessionAdapter:
    """Adapter for remote server session."""

    # Execution timeout constants (in seconds)
    DEFAULT_TIMEOUT = 300.0  # 5 minutes for standard nodes
    CLAUDE_NODE_TIMEOUT = 2400.0  # 40 minutes for long-running Claude tasks
    CLAUDE_NODE_TYPES = {"claude-wezterm"}  # Node types with extended timeout

    def __init__(
        self, client: Any, server_name: str, session_name: str | None = None
    ):  # UnixSocketClient type
        self.client = client
        self.server_name = server_name
        self._name = session_name or "default"  # Use provided or default
        self.session_id = session_name  # None means use server's default
        self._cached_nodes_info: list[dict[str, Any]] = []
        self._cached_graphs: list[dict[str, Any]] = []

    def _add_session_id(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add session_id to params if specified."""
        if self.session_id:
            params["session_id"] = self.session_id
        return params

    @property
    def name(self) -> str:
        return self._name

    @property
    def id(self) -> str:
        """Session ID (actual name on server)."""
        return self._name

    @property
    def node_count(self) -> int:
        """Get node count from cached data."""
        return len(self._cached_nodes_info)

    @property
    def graph_count(self) -> int:
        """Get graph count from cached data."""
        return len(self._cached_graphs)

    async def list_nodes(self) -> list[tuple[str, str]]:
        """List nodes from server with actual backend types."""
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(type=CommandType.LIST_NODES, params=self._add_session_id({}))
        )
        if result.success:
            nodes_info = (result.data or {}).get("nodes_info", [])
            self._cached_nodes_info = nodes_info  # Cache for node_count

            # Return (name, backend_type) tuples
            return [(info["id"], info.get("type", "UNKNOWN")) for info in nodes_info]
        return []

    async def list_graphs(self) -> list[str]:
        """List graphs from server."""
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(type=CommandType.LIST_GRAPHS, params=self._add_session_id({}))
        )
        if result.success:
            graphs = (result.data or {}).get("graphs", [])
            self._cached_graphs = graphs  # Cache for graph_count
            return [g["id"] for g in graphs]
        return []

    async def get_graph(self, graph_id: str) -> Graph | None:
        """Get graph - not supported in remote mode.

        In remote mode, REPL commands (show, dry, validate) are executed
        entirely on the server via EXECUTE_REPL_COMMAND. This method is
        only used by local mode.

        Returns None to indicate graphs are not accessible client-side.
        """
        return None

    async def execute_graph(self, graph_id: str, input: Any = None) -> dict[str, Any]:
        """Execute a registered graph on the server.

        Args:
            graph_id: ID of the graph to execute.
            input: Optional input data for the graph.

        Returns:
            Dict with success, output, error, error_type, attributes fields
            (matches node execution format for seamless transparency).
        """
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(
                type=CommandType.RUN_GRAPH,
                params=self._add_session_id({"graph_id": graph_id, "input": input}),
            ),
            timeout=3600.0,  # Graphs can be long-running (1 hour timeout)
        )

        if result.success:
            # Server returns {"response": {...}} with Graph.execute() standardized dict
            return cast(dict[str, Any], (result.data or {}).get("response", {}))
        else:
            return {
                "success": False,
                "error": result.error or "Graph execution failed",
                "error_type": "execution_error",
                "node_type": "graph",
                "node_id": graph_id,
                "input": input,
                "output": None,
            }

    async def delete_node(self, node_id: str) -> bool:
        """Delete node on server."""
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(
                type=CommandType.DELETE_NODE,
                params=self._add_session_id({"node_id": node_id}),
            )
        )
        return bool(result.success)

    async def execute_on_node(self, node_id: str, text: str) -> dict[str, Any]:
        """Execute on a server node."""
        from nerve.server.protocols import Command, CommandType

        # Determine timeout based on node type
        # ClaudeWezTermNode gets extended timeout for long-running tasks
        timeout = self.DEFAULT_TIMEOUT
        for node_info in self._cached_nodes_info:
            if node_info.get("id") == node_id:
                node_type = node_info.get("type", "")
                if node_type in self.CLAUDE_NODE_TYPES:
                    timeout = self.CLAUDE_NODE_TIMEOUT
                break

        result = await self.client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params=self._add_session_id({"node_id": node_id, "text": text, "stream": False}),
            ),
            timeout=timeout,
        )
        if result.success:
            data = result.data or {}
            response = data.get("response", {})

            # CRITICAL: Validate response came from the requested node
            # This prevents request/response correlation bugs in the transport layer
            returned_node_id = data.get("node_id")
            if returned_node_id and returned_node_id != node_id:
                return {
                    "success": False,
                    "error": (
                        f"Response mismatch! Requested execution on '{node_id}' "
                        f"but got response from '{returned_node_id}'. "
                        f"This indicates a bug in request/response correlation."
                    ),
                    "error_type": "internal_error",
                }

            # The response should already be a dict from the node
            if isinstance(response, dict):
                return response
            else:
                # Unexpected format - wrap in error dict
                return {
                    "success": False,
                    "error": f"Unexpected response type: {type(response).__name__}",
                    "error_type": "internal_error",
                }
        else:
            # Server command failed
            return {
                "success": False,
                "error": result.error or "Unknown server error",
                "error_type": "api_error",
            }

    async def stop(self) -> None:
        """Disconnect from server."""
        await self.client.disconnect()

    @property
    def supports_local_execution(self) -> bool:
        return False

    # =========================================================================
    # Unified command methods
    # =========================================================================

    async def _send_repl_command(
        self, command: str, args: list[str]
    ) -> tuple[str | None, str | None]:
        """Send a REPL command to the server and return (output, error)."""
        from nerve.server.protocols import Command, CommandType

        params: dict[str, Any] = {"command": command, "args": args}
        if self.session_id:
            params["session_id"] = self.session_id

        result = await self.client.send_command(
            Command(type=CommandType.EXECUTE_REPL_COMMAND, params=params)
        )

        if result.success and result.data:
            return result.data.get("output"), result.data.get("error")
        return None, result.error

    async def read_node_buffer(self, node_id: str) -> str:
        """Read a node's output buffer via server."""
        output, error = await self._send_repl_command("read", [node_id])
        if error:
            raise ValueError(error)
        return output or ""

    async def stop_node(self, node_id: str) -> None:
        """Stop a node - not supported in remote mode."""
        raise NotImplementedError("stop_node not available in server mode")

    async def show_graph(
        self, graph_id: str | None = None, fallback_graph: Any | None = None
    ) -> str:
        """Get formatted graph structure from server."""
        if not graph_id:
            raise ValueError("Graph name required in server mode")
        output, error = await self._send_repl_command("show", [graph_id])
        if error:
            raise ValueError(error)
        return output or ""

    async def validate_graph(
        self, graph_id: str | None = None, fallback_graph: Any | None = None
    ) -> str:
        """Validate a graph on the server."""
        if not graph_id:
            raise ValueError("Graph name required in server mode")
        output, error = await self._send_repl_command("validate", [graph_id])
        if error:
            raise ValueError(error)
        return output or ""

    async def dry_run_graph(
        self, graph_id: str | None = None, fallback_graph: Any | None = None
    ) -> str:
        """Get execution order from server."""
        if not graph_id:
            raise ValueError("Graph name required in server mode")
        output, error = await self._send_repl_command("dry", [graph_id])
        if error:
            raise ValueError(error)
        return output or ""

    async def execute_python(self, code: str, namespace: dict[str, Any]) -> tuple[str, str | None]:
        """Execute Python code on the server.

        In remote mode, code is sent to the server for execution.
        The namespace parameter is ignored (server maintains its own state).

        Args:
            code: Python code to execute.
            namespace: Ignored in remote mode.

        Returns:
            Tuple of (output_string, error_string_or_none).
        """
        from nerve.server.protocols import Command, CommandType

        params: dict[str, Any] = {"code": code}
        if self.session_id:
            params["session_id"] = self.session_id

        result = await self.client.send_command(
            Command(type=CommandType.EXECUTE_PYTHON, params=params)
        )

        if result.success and result.data:
            output = result.data.get("output", "")
            error = result.data.get("error")
            return output, error
        return "", result.error

    # =========================================================================
    # Workflow methods
    # =========================================================================

    async def list_workflows(self) -> list[dict[str, Any]]:
        """List workflows from server.

        Returns:
            List of workflow info dicts with 'id', 'description' keys.
        """
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(type=CommandType.LIST_WORKFLOWS, params=self._add_session_id({}))
        )
        if result.success:
            return cast(list[dict[str, Any]], (result.data or {}).get("workflows", []))
        return []

    async def execute_workflow(
        self, workflow_id: str, input: Any = None, wait: bool = False
    ) -> dict[str, Any]:
        """Execute a workflow on the server.

        Args:
            workflow_id: ID of the workflow to execute.
            input: Optional input for the workflow.
            wait: If True, wait for completion (blocking).

        Returns:
            Dict with run_id, state, and optionally result/error.
        """
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(
                type=CommandType.EXECUTE_WORKFLOW,
                params=self._add_session_id(
                    {
                        "workflow_id": workflow_id,
                        "input": input,
                        "wait": wait,
                    }
                ),
            ),
            timeout=3600.0,  # Workflows can be long-running
        )

        if result.success:
            return cast(dict[str, Any], result.data or {})
        else:
            return {
                "success": False,
                "error": result.error or "Workflow execution failed",
            }

    async def get_workflow_run(self, run_id: str) -> dict[str, Any]:
        """Get workflow run status.

        Args:
            run_id: The workflow run ID.

        Returns:
            Dict with run info including state, result, pending_gate, etc.
        """
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(
                type=CommandType.GET_WORKFLOW_RUN,
                params=self._add_session_id({"run_id": run_id}),
            )
        )

        if result.success:
            return cast(dict[str, Any], (result.data or {}).get("run", {}))
        else:
            return {
                "success": False,
                "error": result.error or "Failed to get workflow run",
            }

    async def answer_gate(self, run_id: str, answer: str) -> dict[str, Any]:
        """Answer a pending workflow gate.

        Args:
            run_id: The workflow run ID with a pending gate.
            answer: The user's answer to the gate prompt.

        Returns:
            Dict with success status.
        """
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(
                type=CommandType.ANSWER_GATE,
                params=self._add_session_id({"run_id": run_id, "answer": answer}),
            )
        )

        if result.success:
            return {"success": True}
        else:
            return {
                "success": False,
                "error": result.error or "Failed to answer gate",
            }

    async def cancel_workflow(self, run_id: str) -> dict[str, Any]:
        """Cancel a running workflow.

        Args:
            run_id: The workflow run ID to cancel.

        Returns:
            Dict with success status.
        """
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(
                type=CommandType.CANCEL_WORKFLOW,
                params=self._add_session_id({"run_id": run_id}),
            )
        )

        if result.success:
            return {"success": True}
        else:
            return {
                "success": False,
                "error": result.error or "Failed to cancel workflow",
            }
