"""Shared data models for proxy log parsing."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileOperation:
    """Tracks read/write operations on a file."""

    path: str
    was_read: bool = False
    was_written: bool = False


@dataclass
class ToolCall:
    """Represents a tool invocation with its arguments and result."""

    name: str
    args: dict
    result: str = ""
    success: bool = True
    index: int = 0
    tool_use_id: str = ""

    def summary(self) -> str:
        """Generate a brief summary of the tool call."""

        def _get_path(key: str) -> str:
            val = self.args.get(key)
            return Path(val).name if val else "?"

        extractors = {
            "Edit": lambda: f"Edit -> {_get_path('file_path')}",
            "Read": lambda: f"Read -> {_get_path('file_path')}",
            "Write": lambda: f"Write -> {_get_path('file_path')}",
            "Bash": lambda: f"Bash -> {(self.args.get('command') or '?')[:40]}",
            "Grep": lambda: f'Grep -> "{(self.args.get("pattern") or "?")[:20]}"',
            "Glob": lambda: f"Glob -> {(self.args.get('pattern') or '?')[:30]}",
            "Task": lambda: f"Task -> {(self.args.get('description') or '?')[:30]}",
            "TodoWrite": lambda: "TodoWrite -> updated todos",
        }
        return extractors.get(self.name, lambda: self.name)()

    def matches_search(self, query: str, nested: bool = True) -> bool:
        """Check if this tool call matches a search query.

        Args:
            query: Search query string.
            nested: If True, also search in args and result.

        Returns:
            True if the tool call matches the query.
        """
        q = query.lower()
        # Current level: name and summary only
        if q in self.name.lower() or q in self.summary().lower():
            return True
        # Nested: also search in args and result
        if nested:
            if q in self.result.lower():
                return True
            for v in self.args.values():
                if isinstance(v, str) and q in v.lower():
                    return True
        return False
