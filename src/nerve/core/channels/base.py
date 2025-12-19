"""Channel abstraction - unified interface for interacting with things.

A Channel represents something you can send input to and get output from:
- Terminal pane (PTY, WezTerm)
- SQL connection (PostgreSQL, MySQL)
- HTTP endpoint (REST APIs)
- etc.

The key insight is that parsers are NOT attached to channels.
Parsing is done per-command when you send input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from nerve.core.types import ParsedResponse, ParserType


class ChannelState(Enum):
    """Channel lifecycle states."""

    CONNECTING = auto()  # Channel is being established
    OPEN = auto()  # Channel is ready for input
    BUSY = auto()  # Channel is processing
    CLOSED = auto()  # Channel is closed


class ChannelType(Enum):
    """Supported channel types."""

    TERMINAL = "terminal"  # Terminal-based (PTY, WezTerm)
    SQL = "sql"  # Database connections (future)
    HTTP = "http"  # HTTP endpoints (future)


@runtime_checkable
class Channel(Protocol):
    """Protocol for all channel types.

    A channel is something you can send input to and receive output from.
    This is the core abstraction that unifies terminal panes, SQL connections,
    HTTP endpoints, and any other interactive target.

    Main methods:
        run(command)         Start/execute something (fire and forget)
        send(input, parser)  Send input and wait for parsed response
        interrupt()          Cancel current operation
        write(data)          Low-level raw write

    Example:
        >>> channel = await TerminalChannel.create("my-channel")
        >>> await channel.run("claude")
        >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
        >>> print(response.raw)
        >>> await channel.close()
    """

    id: str
    channel_type: ChannelType
    state: ChannelState

    async def run(self, command: str) -> None:
        """Start/execute a command (fire and forget).

        For terminals: starts a program that takes over.
        For SQL: might execute a statement.
        For HTTP: might set up a connection.

        Args:
            command: Command to execute.
        """
        ...

    async def send(
        self,
        input: str,
        parser: ParserType | None = None,
        timeout: float | None = None,
    ) -> ParsedResponse:
        """Send input and wait for parsed response.

        Args:
            input: The input to send.
            parser: How to parse the response.
            timeout: Response timeout in seconds.

        Returns:
            Parsed response.
        """
        ...

    async def interrupt(self) -> None:
        """Cancel/interrupt the current operation."""
        ...

    async def write(self, data: str) -> None:
        """Write raw data (low-level, no waiting).

        Args:
            data: Raw data to write.
        """
        ...

    async def read(self) -> str:
        """Read current output buffer.

        Returns:
            Current buffer contents.
        """
        ...

    async def close(self) -> None:
        """Close the channel and release resources."""
        ...

    @property
    def is_open(self) -> bool:
        """Whether the channel is open and ready."""
        ...


@dataclass
class ChannelConfig:
    """Base configuration for channels.

    Subclasses can extend this with channel-specific options.
    """

    id: str | None = None  # Auto-generated if not provided
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelInfo:
    """Serializable channel information.

    Used for listing channels, persistence, etc.
    """

    id: str
    channel_type: ChannelType
    state: ChannelState
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "type": self.channel_type.value,
            "state": self.state.name,
            "metadata": self.metadata,
        }
