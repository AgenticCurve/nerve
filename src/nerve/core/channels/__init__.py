"""Channels - unified interface for interacting with things.

A Channel represents something you can send input to and get output from.
This abstraction unifies different backends:

- Terminal channels: PTY processes, WezTerm panes
- SQL channels: Database connections (future)
- HTTP channels: REST endpoints (future)

The key design principle: parsers are NOT attached to channels.
You specify how to parse output per-command, allowing flexible
interaction with the same channel.

Example:
    >>> from nerve.core.channels import TerminalChannel
    >>> from nerve.core.types import ParserType
    >>>
    >>> # Create a terminal channel
    >>> channel = await TerminalChannel.create(command="claude")
    >>>
    >>> # Send with Claude parsing
    >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    >>>
    >>> # Same channel, different parsing
    >>> await channel.send("exit")
    >>> response = await channel.send("echo hi", parser=ParserType.NONE)
    >>>
    >>> await channel.close()

Classes:
    Channel: Protocol for all channel types.
    ChannelState: Channel lifecycle states.
    ChannelType: Supported channel types.
    ChannelConfig: Base configuration.
    ChannelInfo: Serializable channel info.
    TerminalChannel: Terminal-based channel (PTY, WezTerm).
"""

from nerve.core.channels.base import (
    Channel,
    ChannelConfig,
    ChannelInfo,
    ChannelState,
    ChannelType,
)
from nerve.core.channels.terminal import TerminalChannel, TerminalConfig

__all__ = [
    # Protocol and types
    "Channel",
    "ChannelState",
    "ChannelType",
    "ChannelConfig",
    "ChannelInfo",
    # Implementations
    "TerminalChannel",
    "TerminalConfig",
]
