"""Python SDK client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.server.protocols import CommandResult, Event


@dataclass
class RemoteNode:
    """Proxy for a remote node.

    Provides a high-level interface to a node running on the server.
    """

    id: str
    command: str
    _client: NerveClient

    async def send(
        self,
        text: str,
        parser: str = "none",
        stream: bool = False,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send input and get response.

        Args:
            text: Text to send.
            parser: Parser type ("claude", "gemini", "none").
            stream: Whether to stream output (events emitted).
            timeout: Override node's response_timeout for this execution (optional).

        Returns:
            Response dict with success/error/output fields.
        """
        from nerve.server.protocols import Command, CommandType

        params: dict[str, Any] = {
            "node_id": self.id,
            "text": text,
            "parser": parser,
            "stream": stream,
        }
        if timeout is not None:
            params["timeout"] = timeout

        result = await self._client._send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params=params,
            )
        )

        if not result.success:
            raise RuntimeError(result.error)

        # Return response dict directly
        return result.data or {}

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

        if self._standalone_session is not None:
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
        response_timeout: float = 1800.0,
        ready_timeout: float = 60.0,
        backend: str = "pty",
        provider: dict[str, Any] | None = None,
    ) -> RemoteNode:
        """Create a new node.

        Args:
            name: Node name (required, must be unique).
            command: Command to run (e.g., "claude" or ["claude", "--flag"]).
            cwd: Working directory.
            response_timeout: Max wait for terminal response in seconds (default: 1800.0).
            ready_timeout: Max wait for terminal ready state in seconds (default: 60.0).
            backend: Node backend type ("pty", "wezterm", "claude-wezterm").
            provider: Provider configuration for proxy (claude-wezterm only).
                Dict with keys: api_format, base_url, api_key, model (optional).

        Returns:
            Node proxy.

        Raises:
            ValueError: If name is invalid.
            RuntimeError: If node already exists.

        Example with OpenAI provider:
            >>> node = await client.create_node(
            ...     name="claude-openai",
            ...     command="claude --dangerously-skip-permissions",
            ...     backend="claude-wezterm",
            ...     provider={
            ...         "api_format": "openai",
            ...         "base_url": "https://api.openai.com/v1",
            ...         "api_key": "sk-...",
            ...         "model": "gpt-4.1",
            ...     },
            ... )
        """
        from nerve.core.validation import validate_name

        validate_name(name, "node")

        if self._standalone_session is not None:
            # Use PTYNode.create() directly (node is auto-registered)
            from nerve.core.nodes.terminal import PTYNode

            node = await PTYNode.create(
                id=name,
                session=self._standalone_session,
                command=command,
                cwd=cwd,
                response_timeout=response_timeout,
                ready_timeout=ready_timeout,
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

        params: dict[str, Any] = {
            "node_id": name,
            "command": command,
            "cwd": cwd,
            "response_timeout": response_timeout,
            "ready_timeout": ready_timeout,
            "backend": backend,
        }
        if provider is not None:
            params["provider"] = provider

        result = await self._send_command(
            Command(
                type=CommandType.CREATE_NODE,
                params=params,
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
        if self._standalone_session is not None:
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
