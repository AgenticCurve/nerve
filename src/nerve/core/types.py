"""Pure data types for nerve.core.

These are simple dataclasses with no behavior coupling.
They can be serialized, passed around, and used anywhere.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class ParserType(Enum):
    """Supported parser types for CLI output."""

    CLAUDE = "claude"
    GEMINI = "gemini"
    NONE = "none"  # No parsing, raw output only


class SessionState(Enum):
    """Session lifecycle states."""

    STARTING = auto()  # CLI is starting up
    READY = auto()  # Waiting for input
    BUSY = auto()  # Processing a request
    STOPPED = auto()  # Session terminated


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
        """Get tool result for tool_call sections.

        For tool_call sections, the result is stored in content.
        """
        if self.type == "tool_call":
            return self.content if self.content else None
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
