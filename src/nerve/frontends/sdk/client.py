"""Python SDK client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nerve.core.types import ParsedResponse
    from nerve.server.protocols import Event


@dataclass
class RemoteSession:
    """Proxy for a remote session.

    Provides a high-level interface to a session running on the server.
    """

    id: str
    cli_type: str
    _client: NerveClient

    async def send(self, text: str, stream: bool = False) -> ParsedResponse:
        """Send input and get response.

        Args:
            text: Text to send.
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
                    "session_id": self.id,
                    "text": text,
                    "stream": stream,
                },
            )
        )

        if not result.success:
            raise RuntimeError(result.error)

        # Convert to ParsedResponse
        # For now, return a simple response
        return ParsedResponse(
            raw=result.data.get("response", ""),
            sections=(),
            is_complete=True,
            is_ready=True,
        )

    async def send_stream(self, text: str) -> AsyncIterator[str]:
        """Send input and stream output chunks.

        Args:
            text: Text to send.

        Yields:
            Output chunks.
        """
        from nerve.server.protocols import Command, CommandType

        # Subscribe to events for this session
        async def get_chunks():
            async for event in self._client.events():
                if event.session_id == self.id:
                    if event.type.name == "OUTPUT_CHUNK":
                        yield event.data.get("chunk", "")
                    elif event.type.name == "SESSION_READY":
                        break

        # Send the command
        await self._client._send_command(
            Command(
                type=CommandType.SEND_INPUT,
                params={
                    "session_id": self.id,
                    "text": text,
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
                params={"session_id": self.id},
            )
        )

    async def close(self) -> None:
        """Close the session."""
        from nerve.server.protocols import Command, CommandType

        await self._client._send_command(
            Command(
                type=CommandType.CLOSE_SESSION,
                params={"session_id": self.id},
            )
        )


@dataclass
class NerveClient:
    """High-level client for nerve.

    Can connect to a remote server or run standalone (using core directly).

    Example (remote):
        >>> async with NerveClient.connect("/tmp/nerve.sock") as client:
        ...     session = await client.create_session("claude")
        ...     response = await session.send("Hello!")

    Example (standalone):
        >>> async with NerveClient.standalone() as client:
        ...     session = await client.create_session("claude")
        ...     response = await session.send("Hello!")
    """

    _transport: object = None
    _standalone_manager: object = None
    _sessions: dict[str, RemoteSession] = field(default_factory=dict)

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

        No server required - uses core.SessionManager directly.

        Returns:
            Standalone client.
        """
        from nerve.core import SessionManager

        client = cls(_standalone_manager=SessionManager())
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

    async def create_session(
        self,
        cli_type: str = "claude",
        cwd: str | None = None,
    ) -> RemoteSession:
        """Create a new session.

        Args:
            cli_type: Type of CLI ("claude", "gemini").
            cwd: Working directory.

        Returns:
            Session proxy.
        """
        if self._standalone_manager:
            # Use core directly
            from nerve.core import CLIType

            session = await self._standalone_manager.create(
                cli_type=CLIType(cli_type),
                cwd=cwd,
            )
            remote = RemoteSession(
                id=session.id,
                cli_type=cli_type,
                _client=self,
            )
            self._sessions[session.id] = remote
            return remote

        # Use transport
        from nerve.server.protocols import Command, CommandType

        result = await self._send_command(
            Command(
                type=CommandType.CREATE_SESSION,
                params={"cli_type": cli_type, "cwd": cwd},
            )
        )

        if not result.success:
            raise RuntimeError(result.error)

        session_id = result.data["session_id"]
        remote = RemoteSession(
            id=session_id,
            cli_type=cli_type,
            _client=self,
        )
        self._sessions[session_id] = remote
        return remote

    async def get_session(self, session_id: str) -> RemoteSession | None:
        """Get a session by ID.

        Args:
            session_id: Session ID.

        Returns:
            Session proxy, or None if not found.
        """
        return self._sessions.get(session_id)

    async def list_sessions(self) -> list[str]:
        """List session IDs.

        Returns:
            List of session IDs.
        """
        if self._standalone_manager:
            return self._standalone_manager.list()

        from nerve.server.protocols import Command, CommandType

        result = await self._send_command(
            Command(
                type=CommandType.LIST_SESSIONS,
                params={},
            )
        )

        if result.success:
            return result.data.get("sessions", [])
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
