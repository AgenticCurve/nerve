"""Server protocols - Command/Event types and EventSink interface.

These protocols define the contract between server and transport layers.

Node-based terminology (clean break from Channel/DAG):
- CREATE_NODE, DELETE_NODE, LIST_NODES, GET_NODE (was CREATE_CHANNEL, etc.)
- EXECUTE_GRAPH, CANCEL_GRAPH (was EXECUTE_DAG, CANCEL_DAG)
- NODE_CREATED, NODE_DELETED (was CHANNEL_CREATED, CHANNEL_CLOSED)
- STEP_STARTED, STEP_COMPLETED (was TASK_STARTED, TASK_COMPLETED)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Protocol


class EventType(Enum):
    """Types of events emitted by the server."""

    # Node lifecycle
    NODE_CREATED = auto()
    NODE_READY = auto()
    NODE_BUSY = auto()
    NODE_DELETED = auto()

    # Output
    OUTPUT_CHUNK = auto()  # Raw output chunk
    OUTPUT_PARSED = auto()  # Parsed response

    # Graph execution
    GRAPH_STARTED = auto()
    STEP_STARTED = auto()
    STEP_COMPLETED = auto()
    STEP_FAILED = auto()
    GRAPH_COMPLETED = auto()

    # Errors
    ERROR = auto()

    # Server lifecycle
    SERVER_STOPPED = auto()


class CommandType(Enum):
    """Types of commands accepted by the server."""

    # Node management
    CREATE_NODE = auto()
    DELETE_NODE = auto()
    LIST_NODES = auto()
    GET_NODE = auto()

    # Interaction
    RUN_COMMAND = auto()  # Fire and forget - start a program
    EXECUTE_INPUT = auto()  # Send and wait for response
    SEND_INTERRUPT = auto()
    WRITE_DATA = auto()  # Raw write (no waiting)

    # Graph execution
    EXECUTE_GRAPH = auto()
    CANCEL_GRAPH = auto()

    # Query
    GET_BUFFER = auto()
    GET_HISTORY = auto()

    # Server control
    STOP = auto()
    PING = auto()


@dataclass(frozen=True)
class Event:
    """Event emitted by the server.

    Attributes:
        type: The event type.
        node_id: Associated node ID (if applicable).
        data: Event payload.
        timestamp: When the event occurred.
    """

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    node_id: str | None = None
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
