"""Base parser protocol."""

import logging
from abc import ABC, abstractmethod

from nerve.core.types import ParsedResponse

logger = logging.getLogger(__name__)


class Parser(ABC):
    """Abstract base class for AI CLI output parsers.

    Parsers are pure - they take strings and return structured data.
    They know nothing about PTY, sessions, or events.

    Subclasses must implement:
        - is_ready(): Check if CLI is ready for input
        - parse(): Parse output into structured response
    """

    @abstractmethod
    def is_ready(self, content: str) -> bool:
        """Check if the CLI is ready for input.

        Args:
            content: The terminal output to check.

        Returns:
            True if the CLI is waiting for input.
        """
        ...

    @abstractmethod
    def parse(self, content: str) -> ParsedResponse:
        """Parse CLI output into structured response.

        Args:
            content: The terminal output to parse.

        Returns:
            Parsed response with sections.
        """
        ...

    def parse_incremental(self, chunk: str, buffer: str) -> ParsedResponse:
        """Parse incremental output.

        Default implementation just calls parse() on the full buffer.
        Subclasses can override for more efficient incremental parsing.

        Args:
            chunk: New output chunk.
            buffer: Full accumulated buffer.

        Returns:
            Parsed response (may be incomplete).
        """
        return self.parse(buffer)
