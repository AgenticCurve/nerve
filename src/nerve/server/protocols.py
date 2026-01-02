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

    # Session lifecycle
    SESSION_CREATED = auto()
    SESSION_DELETED = auto()

    # Graph lifecycle
    GRAPH_CREATED = auto()
    GRAPH_DELETED = auto()

    # Workflow execution
    WORKFLOW_STARTED = auto()
    WORKFLOW_COMPLETED = auto()
    WORKFLOW_FAILED = auto()
    WORKFLOW_CANCELLED = auto()
    WORKFLOW_GATE_WAITING = auto()
    WORKFLOW_GATE_ANSWERED = auto()
    WORKFLOW_GATE_TIMEOUT = auto()
    WORKFLOW_GATE_CANCELLED = auto()
    WORKFLOW_NODE_STARTED = auto()
    WORKFLOW_NODE_COMPLETED = auto()
    WORKFLOW_NODE_ERROR = auto()
    WORKFLOW_NODE_TIMEOUT = auto()
    WORKFLOW_GRAPH_STARTED = auto()
    WORKFLOW_GRAPH_COMPLETED = auto()
    WORKFLOW_GRAPH_ERROR = auto()
    WORKFLOW_GRAPH_TIMEOUT = auto()
    WORKFLOW_NESTED_STARTED = auto()
    WORKFLOW_NESTED_COMPLETED = auto()
    WORKFLOW_NESTED_ERROR = auto()
    WORKFLOW_NESTED_TIMEOUT = auto()
    WORKFLOW_NESTED_CANCELLED = auto()

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
    FORK_NODE = auto()

    # Interaction
    RUN_COMMAND = auto()  # Fire and forget - start a program
    EXECUTE_INPUT = auto()  # Send and wait for response
    EXECUTE_PYTHON = auto()  # Execute Python code in server's interpreter
    EXECUTE_REPL_COMMAND = auto()  # Execute REPL command (show, dry, validate, etc.)
    SEND_INTERRUPT = auto()
    WRITE_DATA = auto()  # Raw write (no waiting)

    # Graph execution
    EXECUTE_GRAPH = auto()
    CANCEL_GRAPH = auto()

    # Session management
    CREATE_SESSION = auto()
    DELETE_SESSION = auto()
    LIST_SESSIONS = auto()
    GET_SESSION = auto()

    # Graph management
    CREATE_GRAPH = auto()
    DELETE_GRAPH = auto()
    LIST_GRAPHS = auto()
    GET_GRAPH = auto()
    RUN_GRAPH = auto()  # Execute a registered graph

    # Workflow management
    EXECUTE_WORKFLOW = auto()
    LIST_WORKFLOWS = auto()
    GET_WORKFLOW_RUN = auto()
    LIST_WORKFLOW_RUNS = auto()
    ANSWER_GATE = auto()
    CANCEL_WORKFLOW = auto()

    # Query
    GET_BUFFER = auto()
    GET_HISTORY = auto()

    # Server control
    STOP = auto()
    PING = auto()


# Node type to backend name mapping (protocol-level constant)
NODE_TYPE_TO_BACKEND: dict[str, str] = {
    "PTYNode": "pty",
    "WezTermNode": "wezterm",
    "ClaudeWezTermNode": "claude-wezterm",
    "BashNode": "bash",
    "IdentityNode": "identity",
    "OpenRouterNode": "openrouter",
    "GLMNode": "glm",
    "StatefulLLMNode": "llm-chat",
    "SuggestionNode": "suggestion",
}


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
