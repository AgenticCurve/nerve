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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with complete data (no truncation).

        Returns:
            Dict with all section data, suitable for JSON serialization.
        """
        return {
            "type": self.type,
            "content": self.content,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        """Compact representation for REPL display."""
        # Truncate content for readability
        max_len = 60
        content_preview = self.content[:max_len]
        if len(self.content) > max_len:
            content_preview += "..."

        # Show metadata if present
        meta_str = ""
        if self.metadata:
            meta_keys = list(self.metadata.keys())
            if len(meta_keys) <= 2:
                meta_str = f", metadata={dict(self.metadata)}"
            else:
                meta_str = f", metadata={{{', '.join(meta_keys[:2])}, ...}}"

        return f"Section(type={self.type!r}, content={content_preview!r}{meta_str})"

    def __str__(self) -> str:
        """Human-readable representation."""
        return f"[{self.type}] {self.content[:100]}{'...' if len(self.content) > 100 else ''}"


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

    @property
    def text(self) -> str:
        """Get text content only (excludes thinking, tool calls).

        Returns:
            Combined text from all text sections, or empty string if none.
        """
        text_sections = [s.content for s in self.sections if s.type == "text"]
        return " ".join(text_sections).strip()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with complete data (no truncation).

        Returns:
            Dict with all response data, suitable for JSON serialization.
            Includes the computed 'text' property for convenience.
        """
        return {
            "raw": self.raw,
            "sections": [s.to_dict() for s in self.sections],
            "is_complete": self.is_complete,
            "is_ready": self.is_ready,
            "tokens": self.tokens,
            "text": self.text,  # Include computed property
        }

    def __repr__(self) -> str:
        """Compact representation for REPL display."""
        # Summarize sections
        section_summary = {}
        for s in self.sections:
            section_summary[s.type] = section_summary.get(s.type, 0) + 1

        sections_str = ", ".join(f"{count}×{stype}" for stype, count in section_summary.items())

        # Truncate text preview
        text_preview = self.text[:80]
        if len(self.text) > 80:
            text_preview += "..."

        # Token info
        token_str = f", tokens={self.tokens}" if self.tokens else ""

        return f"ParsedResponse(text={text_preview!r}, sections=[{sections_str}]{token_str})"

    def __str__(self) -> str:
        """Human-readable representation."""
        lines = [
            "ParsedResponse:",
            f"  Text: {self.text[:150]}{'...' if len(self.text) > 150 else ''}",
            f"  Sections: {len(self.sections)} ({', '.join(s.type for s in self.sections)})",
            f"  Complete: {self.is_complete}, Ready: {self.is_ready}",
        ]
        if self.tokens:
            lines.append(f"  Tokens: {self.tokens}")
        return "\n".join(lines)
