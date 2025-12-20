"""Channels - unified interface for interacting with things.

A Channel represents something you can send input to and get output from.
This abstraction unifies different backends:

- PTYChannel: Direct pseudo-terminal process management
- WezTermChannel: WezTerm pane interaction via CLI
- SQL channels: Database connections (future)
- HTTP channels: REST endpoints (future)

The key design principle: parsers are NOT attached to channels.
You specify how to parse output per-command, allowing flexible
interaction with the same channel.

Example:
    >>> from nerve.core.channels import PTYChannel, WezTermChannel
    >>> from nerve.core.types import ParserType
    >>>
    >>> # Create a PTY channel (you own the process)
    >>> channel = await PTYChannel.create("my-shell", command="claude")
    >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    >>>
    >>> # Or attach to WezTerm pane (WezTerm owns the pane)
    >>> channel = await WezTermChannel.attach("claude-pane", pane_id="4")
    >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    >>>
    >>> await channel.close()

Classes:
    Channel: Protocol for all channel types.
    ChannelState: Channel lifecycle states.
    ChannelType: Supported channel types.
    ChannelConfig: Base configuration.
    ChannelInfo: Serializable channel info.
    PTYChannel: PTY-based terminal channel.
    WezTermChannel: WezTerm-based terminal channel.
"""

from nerve.core.channels.base import (
    Channel,
    ChannelConfig,
    ChannelInfo,
    ChannelState,
    ChannelType,
)
from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel
from nerve.core.channels.pty import PTYChannel, PTYConfig
from nerve.core.channels.wezterm import WezTermChannel, WezTermConfig

__all__ = [
    # Protocol and types
    "Channel",
    "ChannelState",
    "ChannelType",
    "ChannelConfig",
    "ChannelInfo",
    # Implementations
    "PTYChannel",
    "PTYConfig",
    "WezTermChannel",
    "WezTermConfig",
    "ClaudeOnWezTermChannel",
]
