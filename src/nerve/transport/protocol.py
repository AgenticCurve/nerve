"""Transport protocol definitions.

Defines the interfaces that transport adapters must implement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from nerve.server.engine import NerveEngine
    from nerve.server.protocols import Command, CommandResult, Event


class Transport(Protocol):
    """Base transport protocol.

    All transports must be usable as an EventSink (to receive
    events from the engine) and provide command sending.
    """

    async def emit(self, event: Event) -> None:
        """Receive and handle an event from the engine.

        Called by the engine when events occur.
        Implementations should broadcast to connected clients.
        """
        ...


class ClientTransport(Protocol):
    """Client-side transport protocol.

    Used by frontends to communicate with the server.
    """

    async def connect(self) -> None:
        """Connect to the server."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        ...

    async def send_command(self, command: Command) -> CommandResult:
        """Send a command and wait for result."""
        ...

    async def events(self) -> AsyncIterator[Event]:
        """Subscribe to the event stream."""
        ...


class ServerTransport(Protocol):
    """Server-side transport protocol.

    Used to serve the engine to multiple clients.
    """

    async def serve(self, engine: NerveEngine) -> None:
        """Start serving. Blocks until stopped."""
        ...

    async def stop(self) -> None:
        """Stop serving."""
        ...
