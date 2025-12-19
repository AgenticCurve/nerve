"""Pure data types for nerve.core.

These are simple dataclasses with no behavior coupling.
They can be serialized, passed around, and used anywhere.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class CLIType(Enum):
    """Supported AI CLI types."""

    CLAUDE = "claude"
    GEMINI = "gemini"
    CUSTOM = "custom"


class SessionState(Enum):
    """Session lifecycle states."""

    STARTING = auto()  # CLI is starting up
    READY = auto()  # Waiting for input
    BUSY = auto()  # Processing a request
    STOPPED = auto()  # Session terminated


class TaskStatus(Enum):
    """DAG task execution status."""

    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass(frozen=True)
class Section:
    """A section of an AI response.

    Attributes:
        type: Section type - "thinking", "tool_call", "text", etc.
        content: The text content of this section.
        metadata: Additional data (e.g., tool name, args for tool_call).
    """

    type: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tool(self) -> str | None:
        """Get tool name for tool_call sections."""
        return self.metadata.get("tool")

    @property
    def args(self) -> str | None:
        """Get tool arguments for tool_call sections."""
        return self.metadata.get("args")

    @property
    def result(self) -> str | None:
        """Get tool result for tool_call sections."""
        return self.metadata.get("result")


@dataclass(frozen=True)
class ParsedResponse:
    """Parsed AI CLI response.

    Attributes:
        raw: The raw text output.
        sections: Parsed sections (thinking, tool calls, text).
        is_complete: Whether the response is complete.
        is_ready: Whether the CLI is ready for next input.
        tokens: Token count if available.
    """

    raw: str
    sections: tuple[Section, ...]
    is_complete: bool
    is_ready: bool
    tokens: int | None = None


@dataclass(frozen=True)
class TaskResult:
    """Result of a DAG task execution.

    Attributes:
        task_id: The task identifier.
        status: Execution status.
        output: The task output (if successful).
        error: Error message (if failed).
        duration_ms: Execution duration in milliseconds.
    """

    task_id: str
    status: TaskStatus
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
