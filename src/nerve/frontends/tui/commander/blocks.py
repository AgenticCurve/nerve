"""Block rendering for Commander TUI.

Each interaction (node execution, python code, etc.) is rendered as a block.
Blocks are rendered without borders, separated by light dashed lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.text import Text


@dataclass
class Block:
    """A single interaction block in the timeline.

    Blocks represent one request/response cycle and are
    rendered as borderless text with a header line.
    """

    # Block identity
    block_type: str  # "bash", "llm", "python", "error"
    node_id: str | None  # None for python blocks
    timestamp: datetime = field(default_factory=datetime.now)

    # Content
    input_text: str = ""
    output_text: str = ""
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)  # Raw result from node

    # Metadata
    number: int = 0  # Block number (set by Timeline)
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Execution status: "pending", "completed", "error", "waiting"
    status: str = "pending"
    # Track if this block was executed asynchronously (exceeded threshold)
    was_async: bool = False
    # Track which blocks this one depends on (for dependency-aware execution)
    depends_on: set[int] = field(default_factory=set)

    def render(self, console: Console, show_separator: bool = True) -> RenderableType:
        """Render this block as borderless text.

        Args:
            console: Console with theme for styling.
            show_separator: Whether to show separator line before block.

        Returns:
            A Rich renderable (Group of Text objects).
        """
        parts: list[RenderableType] = []

        # Pending blocks use theme's "pending" style throughout
        is_pending = self.status == "pending"

        # Separator line (light dashed, matches terminal width)
        if show_separator:
            width = console.width or 80
            parts.append(Text("─" * width, style="pending" if is_pending else "dim"))

        # Header line: [003] @bash (12:34:56, 42ms)
        header = self._build_header()
        parts.append(header)

        # Input line
        if self.input_text:
            input_line = Text()
            input_line.append("› ", style="pending" if is_pending else "dim")
            input_line.append(self.input_text, style="pending" if is_pending else "input")
            parts.append(input_line)

        # Blank line between input and output for visual separation
        if self.input_text and (self.output_text or self.error) and not is_pending:
            parts.append(Text(""))

        # Output (if any) - not shown for pending blocks
        if self.output_text and not is_pending:
            for line in self.output_text.split("\n"):
                parts.append(Text(line, style="output"))

        # Error (if any) - not shown for pending blocks
        if self.error and not is_pending:
            error_line = Text()
            error_line.append("ERROR: ", style="bold red")
            error_line.append(self.error, style="error")
            parts.append(error_line)

        # Empty line after block
        parts.append(Text(""))

        return Group(*parts)

    def _build_header(self) -> Text:
        """Build the header line with block number, node, and timing."""
        header = Text()

        # Pending blocks use theme's "pending" style throughout
        is_pending = self.status == "pending"

        # Block number :::1
        header.append(f":::{self.number} ", style="pending" if is_pending else "dim")

        # Node/type indicator
        if self.block_type == "python":
            header.append(">>> ", style="pending" if is_pending else "node.python")
        elif self.node_id:
            if is_pending:
                style = "pending"
            else:
                style = f"node.{self.block_type}" if self.block_type in ("bash", "llm") else "bold"
            header.append(f"@{self.node_id} ", style=style)
        else:
            header.append(f"{self.block_type} ", style="pending" if is_pending else "bold")

        # Status indicator for pending/waiting/async-completed
        if self.status == "pending":
            header.append("⏳ ", style="pending")
        elif self.status == "waiting":
            header.append("⏸️ ", style="dim")
        elif self.status == "completed" and self.was_async:
            # Show ⚡ for blocks that completed asynchronously
            header.append("⚡ ", style="success")

        # Timestamp and duration
        time_str = self.timestamp.strftime("%H:%M:%S")
        if self.status in ("pending", "waiting"):
            header.append(f"({time_str})", style="pending" if self.status == "pending" else "dim")
        elif self.duration_ms is not None:
            if self.duration_ms < 1000:
                duration_str = f"{self.duration_ms:.0f}ms"
            else:
                duration_str = f"{self.duration_ms / 1000:.1f}s"
            header.append(f"({time_str}, {duration_str})", style="timestamp")
        else:
            header.append(f"({time_str})", style="timestamp")

        return header

    # Dict-like access for :::N['input'] / :::N['output'] / :::N['raw']
    def __getitem__(self, key: str) -> str | dict[str, Any]:
        """Allow dict-like access: block['input'], block['output'], block['raw'], etc."""
        if key == "input":
            return self.input_text
        elif key == "output":
            # Prefer stdout/stderr for bash-like nodes
            if self.raw:
                stdout = str(self.raw.get("stdout") or "")
                stderr = str(self.raw.get("stderr") or "")
                if stdout or stderr:
                    return stdout if stdout else stderr
            # Fall back to output_text (for identity, LLM, and other nodes)
            return self.output_text
        elif key == "error":
            return self.error or ""
        elif key == "type":
            return self.block_type
        elif key == "node":
            return self.node_id or ""
        elif key == "raw":
            return self.raw
        else:
            raise KeyError(f"Unknown key: {key}. Valid keys: input, output, error, type, node, raw")

    def keys(self) -> list[str]:
        """Return available keys for dict-like access."""
        return ["input", "output", "error", "type", "node", "raw"]

    def to_dict(self) -> dict[str, Any]:
        """Convert block to dictionary."""
        return {
            "number": self.number,
            "type": self.block_type,
            "node": self.node_id,
            "input": self.input_text,
            "output": self.output_text,
            "error": self.error,
            "raw": self.raw,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
        }


@dataclass
class Timeline:
    """Collection of blocks representing a session's activity.

    The timeline maintains chronological order and provides
    methods for filtering, display, and programmatic access.

    Blocks are numbered starting from 0 (Pythonic) and can be accessed via:
    - timeline[0] - get first block
    - timeline.blocks - list of all blocks
    """

    blocks: list[Block] = field(default_factory=list)
    _next_number: int = field(default=0, init=False)

    def add(self, block: Block) -> None:
        """Add a block to the timeline, assigning it a number."""
        block.number = self._next_number
        self._next_number += 1
        self.blocks.append(block)

    def reserve_number(self) -> int:
        """Reserve the next block number without adding a block yet.

        Returns:
            The reserved block number.
        """
        number = self._next_number
        self._next_number += 1
        return number

    def add_with_number(self, block: Block, number: int) -> None:
        """Add a block with a pre-assigned number (from reserve_number).

        Args:
            block: The block to add.
            number: The pre-reserved block number.
        """
        block.number = number
        self.blocks.append(block)

    def render_last(self, console: Console) -> None:
        """Render only the last block."""
        if self.blocks:
            console.print(self.blocks[-1].render(console))

    def render_all(self, console: Console, limit: int | None = None) -> None:
        """Render all blocks (or last N if limit specified)."""
        blocks_to_render = self.blocks[-limit:] if limit else self.blocks
        for i, block in enumerate(blocks_to_render):
            # Show separator for all except first
            console.print(block.render(console, show_separator=(i > 0)))

    def filter_by_node(self, node_id: str) -> list[Block]:
        """Get blocks for a specific node."""
        return [b for b in self.blocks if b.node_id == node_id]

    def filter_by_type(self, block_type: str) -> list[Block]:
        """Get blocks of a specific type."""
        return [b for b in self.blocks if b.block_type == block_type]

    def clear(self) -> None:
        """Clear all blocks and reset numbering."""
        self.blocks.clear()
        self._next_number = 0

    def get(self, number: int) -> Block | None:
        """Get block by number (0-indexed)."""
        for block in self.blocks:
            if block.number == number:
                return block
        return None

    def last(self) -> Block | None:
        """Get the last block."""
        return self.blocks[-1] if self.blocks else None

    def __len__(self) -> int:
        return len(self.blocks)

    def __getitem__(self, number: int) -> Block:
        """Get block by number (0-indexed): timeline[0], timeline[1], etc."""
        block = self.get(number)
        if block is None:
            raise IndexError(f"No block with number {number}")
        return block

    def __contains__(self, number: int) -> bool:
        """Check if block number exists: 1 in timeline."""
        return self.get(number) is not None
