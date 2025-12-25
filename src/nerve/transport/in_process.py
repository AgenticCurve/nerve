"""In-process transport - direct communication without IPC.

Useful for:
- Testing
- Embedding nerve in an application
- Single-process use cases
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nerve.server import NerveEngine
    from nerve.server.protocols import Command, CommandResult, Event


@dataclass
class InProcessTransport:
    """In-process transport - no IPC, direct communication.

    Both server and client in the same process.
    Events are queued and can be consumed by the client.

    Example:
        >>> transport = InProcessTransport()
        >>> engine = build_nerve_engine(event_sink=transport)
        >>>
        >>> # Send command directly through transport
        >>> result = await transport.send_command(Command(
        ...     type=CommandType.CREATE_NODE,
        ...     params={"command": "claude"},
        ... ))
        >>>
        >>> # Consume events
        >>> async for event in transport.events():
        ...     print(event.type)
    """

    _engine: NerveEngine | None = None
    _event_queue: asyncio.Queue[Event] = field(default_factory=asyncio.Queue)
    _subscribers: list[asyncio.Queue[Event]] = field(default_factory=list)

    def bind(self, engine: NerveEngine) -> None:
        """Bind to an engine.

        Args:
            engine: The NerveEngine to communicate with.
        """
        self._engine = engine

    async def emit(self, event: Event) -> None:
        """Receive event from engine and broadcast to subscribers.

        Called by the engine when events occur.
        """
        # Put in main queue
        await self._event_queue.put(event)

        # Broadcast to all subscribers
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop if subscriber is slow

    async def send_command(self, command: Command) -> CommandResult:
        """Send a command to the engine.

        Args:
            command: The command to execute.

        Returns:
            The command result.

        Raises:
            RuntimeError: If not bound to an engine.
        """
        if not self._engine:
            raise RuntimeError("Transport not bound to engine")

        return await self._engine.execute(command)

    async def events(self) -> AsyncIterator[Event]:
        """Subscribe to events.

        Yields:
            Events as they occur.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)

        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscribers.remove(queue)

    async def next_event(self, timeout: float | None = None) -> Event | None:
        """Get the next event.

        Args:
            timeout: Timeout in seconds.

        Returns:
            The next event, or None if timeout.
        """
        try:
            if timeout:
                return await asyncio.wait_for(self._event_queue.get(), timeout=timeout)
            return await self._event_queue.get()
        except TimeoutError:
            return None

    def clear_events(self) -> None:
        """Clear pending events."""
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
