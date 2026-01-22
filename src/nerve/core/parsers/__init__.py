"""AI CLI output parsers.

Pure parsing logic - takes strings, returns structured data.
No PTY knowledge, no session awareness, no events.

Classes:
    Parser: Abstract base for parsers.
    ClaudeCodeParser: Parser for Claude Code CLI output.
    GeminiParser: Parser for Gemini CLI output.
    NoneParser: No-op parser for raw output.

Functions:
    get_parser: Get parser instance for a parser type.

Example:
    >>> from nerve.core.parsers import ClaudeCodeParser
    >>>
    >>> parser = ClaudeCodeParser()
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
from nerve.core.parsers.claude_code import ClaudeCodeParser
from nerve.core.parsers.gemini import GeminiParser
from nerve.core.parsers.none import NoneParser
from nerve.core.types import ParserType


def get_parser(parser_type: ParserType) -> Parser:
    """Get parser instance for a parser type.

    Args:
        parser_type: The parser type to use.

    Returns:
        A parser instance.

    Raises:
        ValueError: If parser type is not supported.
    """
    parsers: dict[ParserType, type[Parser]] = {
        ParserType.CLAUDE_CODE: ClaudeCodeParser,
        ParserType.GEMINI: GeminiParser,
        ParserType.NONE: NoneParser,
    }

    parser_class = parsers.get(parser_type)
    if parser_class is None:
        raise ValueError(f"No parser for type: {parser_type}")

    return parser_class()


__all__ = ["Parser", "ClaudeCodeParser", "GeminiParser", "NoneParser", "get_parser"]
