"""Server - Stateful wrapper over core with event emission.

The server layer wraps core primitives with:
- Event emission for state changes
- Command/response protocol
- Connection management

This layer knows about core, but not about:
- Specific transports (socket, HTTP)
- Frontends (CLI, SDK, MCP)

Classes:
    NerveEngine: Main engine that wraps core with events.
    EventSink: Protocol for event consumers.
    Command: Command message type.
    Event: Event message type.

Example:
    >>> from nerve.server import NerveEngine
    >>> from nerve.server.protocols import EventSink, Event
    >>>
    >>> class MySink(EventSink):
    ...     async def emit(self, event: Event) -> None:
    ...         print(f"Event: {event.type}")
    >>>
    >>> engine = NerveEngine(event_sink=MySink())
    >>> result = await engine.execute(Command(
    ...     type=CommandType.CREATE_NODE,
    ...     params={"command": "claude"},
    ... ))
"""

from nerve.server.engine import NerveEngine
from nerve.server.protocols import (
    Command,
    CommandResult,
    CommandType,
    Event,
    EventSink,
    EventType,
)

__all__ = [
    "NerveEngine",
    "EventSink",
    "Event",
    "EventType",
    "Command",
    "CommandType",
    "CommandResult",
]
