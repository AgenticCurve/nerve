"""FormattedText builder utilities for Commander TUI.

Provides a fluent API for building prompt_toolkit FormattedText objects,
reducing boilerplate for common patterns like section headers, separators,
and content blocks.
"""

from __future__ import annotations

from typing import Self

from prompt_toolkit.formatted_text import FormattedText


class FormattedTextBuilder:
    """Builder for constructing FormattedText with common patterns.

    Example:
        text = (
            FormattedTextBuilder()
            .add_line("Header", style="bold")
            .add_separator(40)
            .add_line("Content here")
            .build()
        )
    """

    def __init__(self) -> None:
        self._lines: list[tuple[str, str]] = []

    def add_line(self, text: str, style: str = "", newline: bool = True) -> Self:
        """Add a single line with optional styling.

        Args:
            text: The text content.
            style: Rich style string (e.g., "bold", "dim", "ansired").
            newline: Whether to append newline (default True).

        Returns:
            Self for chaining.
        """
        content = text + "\n" if newline else text
        self._lines.append((style, content))
        return self

    def add_separator(self, width: int = 40, char: str = "─", style: str = "dim") -> Self:
        """Add a separator line.

        Args:
            width: Width of the separator in characters.
            char: Character to repeat (default "─").
            style: Style for the separator (default "dim").

        Returns:
            Self for chaining.
        """
        self._lines.append((style, char * width + "\n"))
        return self

    def add_section(
        self,
        title: str,
        content: str,
        *,
        title_style: str = "bold",
        content_style: str = "",
        separator_width: int = 40,
        indent: str = "",
        max_chars: int | None = None,
    ) -> Self:
        """Add a titled section with content.

        Args:
            title: Section title.
            content: Section content.
            title_style: Style for the title (default "bold").
            content_style: Style for content (default "").
            separator_width: Width of separator under title.
            indent: Prefix for each content line.
            max_chars: If set, truncate content with "..." suffix.

        Returns:
            Self for chaining.
        """
        self.add_line(title, style=title_style)
        self.add_separator(separator_width)

        display_content = content
        if max_chars and len(content) > max_chars:
            display_content = content[:max_chars] + "..."

        for line in display_content.split("\n"):
            self._lines.append((content_style, f"{indent}{line}\n"))

        return self

    def add_spacing(self, lines: int = 1) -> Self:
        """Add blank lines for spacing.

        Args:
            lines: Number of blank lines to add.

        Returns:
            Self for chaining.
        """
        for _ in range(lines):
            self._lines.append(("", "\n"))
        return self

    def add_raw(self, style: str, text: str) -> Self:
        """Add raw (style, text) tuple directly.

        Use when you need precise control over formatting.

        Args:
            style: Rich style string.
            text: Text content (include newline if needed).

        Returns:
            Self for chaining.
        """
        self._lines.append((style, text))
        return self

    def extend(self, lines: list[tuple[str, str]]) -> Self:
        """Extend with existing list of (style, text) tuples.

        Args:
            lines: List of (style, text) tuples to add.

        Returns:
            Self for chaining.
        """
        self._lines.extend(lines)
        return self

    def build(self) -> FormattedText:
        """Build and return the FormattedText.

        Returns:
            FormattedText ready for use with prompt_toolkit.
        """
        return FormattedText(self._lines)

    def to_list(self) -> list[tuple[str, str]]:
        """Return the raw list of (style, text) tuples.

        Useful when you need to extend another list rather than
        build a FormattedText directly.

        Returns:
            List of (style, text) tuples.
        """
        return self._lines.copy()
