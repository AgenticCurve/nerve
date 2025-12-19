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
        - Or content ends with a newline (simple heuristic)

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

        last_line = lines[-1].strip()

        # Common prompt patterns
        prompt_patterns = [">", ">>>", "$", "%", "#", "❯"]
        for pattern in prompt_patterns:
            if last_line == pattern or last_line.endswith(pattern + " "):
                return True

        return False

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
