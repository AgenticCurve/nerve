"""Server protocols - Command/Event types and EventSink interface.

These protocols define the contract between server and transport layers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Protocol


class EventType(Enum):
    """Types of events emitted by the server."""

    # Channel lifecycle
    CHANNEL_CREATED = auto()
    CHANNEL_READY = auto()
    CHANNEL_BUSY = auto()
    CHANNEL_CLOSED = auto()

    # Output
    OUTPUT_CHUNK = auto()  # Raw output chunk
    OUTPUT_PARSED = auto()  # Parsed response

    # DAG execution
    DAG_STARTED = auto()
    TASK_STARTED = auto()
    TASK_COMPLETED = auto()
    TASK_FAILED = auto()
    DAG_COMPLETED = auto()

    # Errors
    ERROR = auto()

    # Server lifecycle
    SERVER_SHUTDOWN = auto()


class CommandType(Enum):
    """Types of commands accepted by the server."""

    # Channel management
    CREATE_CHANNEL = auto()
    CLOSE_CHANNEL = auto()
    LIST_CHANNELS = auto()
    GET_CHANNEL = auto()

    # Interaction
    RUN_COMMAND = auto()  # Fire and forget - start a program
    SEND_INPUT = auto()  # Send and wait for response
    SEND_INTERRUPT = auto()
    WRITE_DATA = auto()  # Raw write (no waiting)

    # DAG
    EXECUTE_DAG = auto()
    CANCEL_DAG = auto()

    # Query
    GET_BUFFER = auto()
    GET_HISTORY = auto()

    # Server control
    SHUTDOWN = auto()
    PING = auto()


@dataclass(frozen=True)
class Event:
    """Event emitted by the server.

    Attributes:
        type: The event type.
        channel_id: Associated channel ID (if applicable).
        data: Event payload.
        timestamp: When the event occurred.
    """

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    channel_id: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Command:
    """Command sent to the server.

    Attributes:
        type: The command type.
        params: Command parameters.
        request_id: Optional ID for request-response correlation.
    """

    type: CommandType
    params: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None


@dataclass
class CommandResult:
    """Result of command execution.

    Attributes:
        success: Whether the command succeeded.
        data: Result data (if successful).
        error: Error message (if failed).
        request_id: Correlation ID from the command.
    """

    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    request_id: str | None = None


class EventSink(Protocol):
    """Protocol for event consumers.

    The server emits events through this interface.
    Transport layers implement this to receive events.
    """

    async def emit(self, event: Event) -> None:
        """Emit an event.

        Args:
            event: The event to emit.
        """
        ...
