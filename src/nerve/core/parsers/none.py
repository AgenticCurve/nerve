"""No-op parser for raw output.

Use when you don't need structured parsing of CLI output.
"""

from nerve.core.parsers.base import Parser
from nerve.core.types import ParsedResponse, Section


class NoneParser(Parser):
    """No-op parser that returns raw output without parsing.

    Useful for:
    - Custom CLIs without known output format
    - Shell sessions
    - Debugging/testing

    Example:
        >>> parser = NoneParser()
        >>> response = parser.parse("some output\\n> ")
        >>> print(response.raw)
        some output
        >
    """

    def is_ready(self, content: str) -> bool:
        """Check if ready for input.

        For NoneParser, we consider it ready if:
        - Content ends with a common prompt pattern (>, $, %, #)
        - Handles prompts with or without trailing space

        Args:
            content: Terminal output to check.

        Returns:
            True if appears ready for input.
        """
        if not content:
            return False

        lines = content.strip().split("\n")
        if not lines:
            return False

        # Strip ANSI escape codes from last line
        last_line = self._strip_ansi(lines[-1]).strip()

        # Common prompt patterns (with or without trailing space)
        prompt_patterns = [">", ">>>", "$", "%", "#", "❯"]
        for pattern in prompt_patterns:
            # Exact match
            if last_line == pattern:
                return True
            # Ends with pattern (with or without trailing space)
            if last_line.endswith(pattern) or last_line.endswith(pattern + " "):
                return True

        return False

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Strip ANSI escape codes from text."""
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def parse(self, content: str) -> ParsedResponse:
        """Return content as-is in a single text section.

        Args:
            content: The raw output.

        Returns:
            ParsedResponse with raw content.
        """
        return ParsedResponse(
            raw=content,
            sections=(Section(type="text", content=content),),
            is_complete=True,
            is_ready=self.is_ready(content),
            tokens=None,
        )
