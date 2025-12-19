"""AI CLI output parsers.

Pure parsing logic - takes strings, returns structured data.
No PTY knowledge, no session awareness, no events.

Classes:
    Parser: Abstract base for parsers.
    ClaudeParser: Parser for Claude Code CLI output.
    GeminiParser: Parser for Gemini CLI output.

Functions:
    get_parser: Get parser instance for a CLI type.

Example:
    >>> from nerve.core.parsers import ClaudeParser
    >>>
    >>> parser = ClaudeParser()
    >>>
    >>> # Check if CLI is ready for input
    >>> if parser.is_ready(output_text):
    ...     print("Claude is waiting")
    >>>
    >>> # Parse a response
    >>> response = parser.parse(output_text)
    >>> for section in response.sections:
    ...     print(f"[{section.type}] {section.content}")
"""

from nerve.core.parsers.base import Parser
from nerve.core.parsers.claude import ClaudeParser
from nerve.core.parsers.gemini import GeminiParser
from nerve.core.types import CLIType


def get_parser(cli_type: CLIType) -> Parser:
    """Get parser instance for a CLI type.

    Args:
        cli_type: The CLI type to get a parser for.

    Returns:
        A parser instance.

    Raises:
        ValueError: If CLI type is not supported.
    """
    parsers = {
        CLIType.CLAUDE: ClaudeParser,
        CLIType.GEMINI: GeminiParser,
    }

    parser_class = parsers.get(cli_type)
    if parser_class is None:
        raise ValueError(f"No parser for CLI type: {cli_type}")

    return parser_class()


__all__ = ["Parser", "ClaudeParser", "GeminiParser", "get_parser"]
