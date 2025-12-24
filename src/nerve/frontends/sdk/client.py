"""Python SDK client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.types import ParsedResponse
    from nerve.server.protocols import CommandResult, Event


@dataclass
class RemoteNode:
    """Proxy for a remote node.

    Provides a high-level interface to a node running on the server.
    """

    id: str
    command: str
    _client: NerveClient

    async def send(self, text: str, parser: str = "none", stream: bool = False) -> ParsedResponse:
        """Send input and get response.

        Args:
            text: Text to send.
            parser: Parser type ("claude", "gemini", "none").
            stream: Whether to stream output (events emitted).

        Returns:
            Parsed response.
        """
        from nerve.core.types import ParsedResponse
        from nerve.server.protocols import Command, CommandType

        result = await self._client._send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params={
                    "node_id": self.id,
                    "text": text,
                    "parser": parser,
                    "stream": stream,
                },
            )
        )

        if not result.success:
            raise RuntimeError(result.error)

        # Convert to ParsedResponse
        data = result.data or {}
        return ParsedResponse(
            raw=data.get("response", ""),
            sections=(),
            is_complete=True,
            is_ready=True,
        )

    async def send_stream(self, text: str, parser: str = "none") -> AsyncIterator[str]:
        """Send input and stream output chunks.

        Args:
            text: Text to send.
            parser: Parser type ("claude", "gemini", "none").

        Yields:
            Output chunks.
        """
        from nerve.server.protocols import Command, CommandType

        # Subscribe to events for this node
        async def get_chunks() -> AsyncIterator[str]:
            async for event in self._client.events():
                if event.node_id == self.id:
                    if event.type.name == "OUTPUT_CHUNK":
                        yield event.data.get("chunk", "")
                    elif event.type.name == "NODE_READY":
                        break

        # Send the command
        await self._client._send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params={
                    "node_id": self.id,
                    "text": text,
                    "parser": parser,
                    "stream": True,
                },
            )
        )

        async for chunk in get_chunks():
            yield chunk

    async def interrupt(self) -> None:
        """Send interrupt signal."""
        from nerve.server.protocols import Command, CommandType

        await self._client._send_command(
            Command(
                type=CommandType.SEND_INTERRUPT,
                params={"node_id": self.id},
            )
        )

    async def delete(self) -> None:
        """Delete the node."""
        from nerve.server.protocols import Command, CommandType

        await self._client._send_command(
            Command(
                type=CommandType.DELETE_NODE,
                params={"node_id": self.id},
            )
        )


@dataclass
class NerveClient:
    """High-level client for nerve.

    Can connect to a remote server or run standalone (using core directly).

    Example (remote):
        >>> async with NerveClient.connect("/tmp/nerve-myproject.sock") as client:
        ...     node = await client.create_node("my-claude", command="claude")
        ...     response = await node.send("Hello!", parser="claude")

    Example (standalone):
        >>> async with NerveClient.standalone() as client:
        ...     node = await client.create_node("my-claude", command="claude")
        ...     response = await node.send("Hello!", parser="claude")
    """

    _transport: Any = None
    _standalone_session: Any = None
    _nodes: dict[str, RemoteNode] = field(default_factory=dict)

    @classmethod
    async def connect(cls, socket_path: str) -> NerveClient:
        """Connect to a nerve server via Unix socket.

        Args:
            socket_path: Path to the Unix socket.

        Returns:
            Connected client.
        """
        from nerve.transport import UnixSocketClient

        transport = UnixSocketClient(socket_path)
        await transport.connect()

        client = cls(_transport=transport)
        return client

    @classmethod
    async def connect_http(cls, url: str) -> NerveClient:
        """Connect to a nerve server via HTTP.

        Args:
            url: Server URL (e.g., "http://localhost:8080").

        Returns:
            Connected client.
        """
        from nerve.transport import HTTPClient

        transport = HTTPClient(url)
        await transport.connect()

        client = cls(_transport=transport)
        return client

    @classmethod
    async def standalone(cls) -> NerveClient:
        """Create a standalone client using core directly.

        No server required - uses Session directly.

        Returns:
            Standalone client.
        """
        from nerve.core.session import Session

        session = Session()
        client = cls(_standalone_session=session)
        return client

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        if self._transport:
            await self._transport.disconnect()

        if self._standalone_session:
            # Stop all nodes tracked in the session
            await self._standalone_session.stop()

    async def __aenter__(self) -> NerveClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.disconnect()

    async def create_node(
        self,
        name: str,
        command: str | list[str] | None = None,
        cwd: str | None = None,
    ) -> RemoteNode:
        """Create a new node.

        Args:
            name: Node name (required, must be unique).
            command: Command to run (e.g., "claude" or ["claude", "--flag"]).
            cwd: Working directory.

        Returns:
            Node proxy.

        Raises:
            ValueError: If name is invalid.
            RuntimeError: If node already exists.
        """
        from nerve.core.validation import validate_name

        validate_name(name, "node")

        if self._standalone_session:
            # Use Session directly (node is auto-registered)
            node = await self._standalone_session.create_node(
                node_id=name,
                command=command,
                cwd=cwd,
            )
            cmd_str = command if isinstance(command, str) else " ".join(command or [])
            remote = RemoteNode(
                id=node.id,
                command=cmd_str,
                _client=self,
            )
            self._nodes[node.id] = remote
            return remote

        # Use transport
        from nerve.server.protocols import Command, CommandType

        result = await self._send_command(
            Command(
                type=CommandType.CREATE_NODE,
                params={"node_id": name, "command": command, "cwd": cwd},
            )
        )

        if not result.success:
            raise RuntimeError(result.error)

        cmd_str = command if isinstance(command, str) else " ".join(command or [])
        remote = RemoteNode(
            id=name,
            command=cmd_str,
            _client=self,
        )
        self._nodes[name] = remote
        return remote

    async def get_node(self, node_id: str) -> RemoteNode | None:
        """Get a node by ID.

        Args:
            node_id: Node ID.

        Returns:
            Node proxy, or None if not found.
        """
        return self._nodes.get(node_id)

    async def list_nodes(self) -> list[str]:
        """List node IDs.

        Returns:
            List of node IDs.
        """
        if self._standalone_session:
            return list(self._nodes.keys())

        from nerve.server.protocols import Command, CommandType

        result = await self._send_command(
            Command(
                type=CommandType.LIST_NODES,
                params={},
            )
        )

        if result.success:
            data = result.data or {}
            nodes: list[str] = data.get("nodes", [])
            return nodes
        return []

    async def events(self) -> AsyncIterator[Event]:
        """Subscribe to events.

        Yields:
            Events from the server.
        """
        if self._transport:
            async for event in self._transport.events():
                yield event

    async def _send_command(self, command: Any) -> CommandResult:
        """Send a command via transport."""

        if self._transport:
            result: CommandResult = await self._transport.send_command(command)
            return result
        raise RuntimeError("No transport available")
