"""Session adapter abstraction for local vs remote sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from nerve.core.nodes import Graph


class SessionAdapter(Protocol):
    """Protocol for session operations in both local and remote modes."""

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

    async def execute_on_node(self, node_id: str, text: str) -> str:
        """Execute input on a node and return response."""
        ...

    async def stop(self) -> None:
        """Stop session and cleanup."""
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

    async def delete_node(self, node_id: str) -> bool:
        result: bool = await self.session.delete_node(node_id)
        return result

    async def execute_on_node(self, node_id: str, text: str) -> str:
        """Execute on a node (for send command)."""
        from nerve.core.nodes.context import ExecutionContext

        node = self.session.get_node(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        ctx = ExecutionContext(session=self.session, input=text)
        result = await node.execute(ctx)
        return result.raw if hasattr(result, "raw") else str(result)

    async def stop(self) -> None:
        await self.session.stop()


class RemoteSessionAdapter:
    """Adapter for remote server session."""

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
            nodes_info = result.data.get("nodes_info", [])
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
            graphs = result.data.get("graphs", [])
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

    async def execute_on_node(self, node_id: str, text: str) -> str:
        """Execute on a server node."""
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params=self._add_session_id({"node_id": node_id, "text": text, "stream": False}),
            )
        )
        if result.success:
            data = result.data or {}
            return str(data.get("response", ""))
        else:
            raise ValueError(result.error)

    async def stop(self) -> None:
        """Disconnect from server."""
        await self.client.disconnect()
