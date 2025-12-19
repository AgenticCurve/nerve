"""Python SDK client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nerve.core.types import ParsedResponse
    from nerve.server.protocols import Event


@dataclass
class RemoteChannel:
    """Proxy for a remote channel.

    Provides a high-level interface to a channel running on the server.
    """

    id: str
    command: str
    _client: NerveClient

    async def send(
        self, text: str, parser: str = "none", stream: bool = False
    ) -> ParsedResponse:
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
                type=CommandType.SEND_INPUT,
                params={
                    "channel_id": self.id,
                    "text": text,
                    "parser": parser,
                    "stream": stream,
                },
            )
        )

        if not result.success:
            raise RuntimeError(result.error)

        # Convert to ParsedResponse
        return ParsedResponse(
            raw=result.data.get("response", ""),
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

        # Subscribe to events for this channel
        async def get_chunks():
            async for event in self._client.events():
                if event.channel_id == self.id:
                    if event.type.name == "OUTPUT_CHUNK":
                        yield event.data.get("chunk", "")
                    elif event.type.name == "CHANNEL_READY":
                        break

        # Send the command
        await self._client._send_command(
            Command(
                type=CommandType.SEND_INPUT,
                params={
                    "channel_id": self.id,
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
                params={"channel_id": self.id},
            )
        )

    async def close(self) -> None:
        """Close the channel."""
        from nerve.server.protocols import Command, CommandType

        await self._client._send_command(
            Command(
                type=CommandType.CLOSE_CHANNEL,
                params={"channel_id": self.id},
            )
        )


@dataclass
class NerveClient:
    """High-level client for nerve.

    Can connect to a remote server or run standalone (using core directly).

    Example (remote):
        >>> async with NerveClient.connect("/tmp/nerve-myproject.sock") as client:
        ...     channel = await client.create_channel("my-claude", command="claude")
        ...     response = await channel.send("Hello!", parser="claude")

    Example (standalone):
        >>> async with NerveClient.standalone() as client:
        ...     channel = await client.create_channel("my-claude", command="claude")
        ...     response = await channel.send("Hello!", parser="claude")
    """

    _transport: object = None
    _standalone_manager: object = None
    _channels: dict[str, RemoteChannel] = field(default_factory=dict)

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

        No server required - uses core.ChannelManager directly.

        Returns:
            Standalone client.
        """
        from nerve.core import ChannelManager

        client = cls(_standalone_manager=ChannelManager())
        return client

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        if self._transport:
            await self._transport.disconnect()

        if self._standalone_manager:
            await self._standalone_manager.close_all()

    async def __aenter__(self) -> NerveClient:
        return self

    async def __aexit__(self, *args) -> None:
        await self.disconnect()

    async def create_channel(
        self,
        name: str,
        command: str | list[str] | None = None,
        cwd: str | None = None,
    ) -> RemoteChannel:
        """Create a new channel.

        Args:
            name: Channel name (required, must be unique).
            command: Command to run (e.g., "claude" or ["claude", "--flag"]).
            cwd: Working directory.

        Returns:
            Channel proxy.

        Raises:
            ValueError: If name is invalid.
            RuntimeError: If channel already exists.
        """
        from nerve.core.validation import validate_name

        validate_name(name, "channel")

        if self._standalone_manager:
            # Use core directly
            channel = await self._standalone_manager.create_terminal(
                channel_id=name,
                command=command,
                cwd=cwd,
            )
            cmd_str = command if isinstance(command, str) else " ".join(command or [])
            remote = RemoteChannel(
                id=channel.id,
                command=cmd_str,
                _client=self,
            )
            self._channels[channel.id] = remote
            return remote

        # Use transport
        from nerve.server.protocols import Command, CommandType

        result = await self._send_command(
            Command(
                type=CommandType.CREATE_CHANNEL,
                params={"channel_id": name, "command": command, "cwd": cwd},
            )
        )

        if not result.success:
            raise RuntimeError(result.error)

        cmd_str = command if isinstance(command, str) else " ".join(command or [])
        remote = RemoteChannel(
            id=name,
            command=cmd_str,
            _client=self,
        )
        self._channels[name] = remote
        return remote

    async def get_channel(self, channel_id: str) -> RemoteChannel | None:
        """Get a channel by ID.

        Args:
            channel_id: Channel ID.

        Returns:
            Channel proxy, or None if not found.
        """
        return self._channels.get(channel_id)

    async def list_channels(self) -> list[str]:
        """List channel IDs.

        Returns:
            List of channel IDs.
        """
        if self._standalone_manager:
            return self._standalone_manager.list()

        from nerve.server.protocols import Command, CommandType

        result = await self._send_command(
            Command(
                type=CommandType.LIST_CHANNELS,
                params={},
            )
        )

        if result.success:
            return result.data.get("channels", [])
        return []

    async def events(self) -> AsyncIterator[Event]:
        """Subscribe to events.

        Yields:
            Events from the server.
        """
        if self._transport:
            async for event in self._transport.events():
                yield event

    async def _send_command(self, command) -> object:
        """Send a command via transport."""
        if self._transport:
            return await self._transport.send_command(command)
        raise RuntimeError("No transport available")
