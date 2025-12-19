"""Session - logical grouping of channels.

A Session is a high-level concept that groups related channels
together with metadata. For example, a "project" session might include:

- A Claude channel for AI assistance
- A shell channel for running commands
- A database channel for queries

This is optional - you can use channels directly without sessions.

Example:
    >>> session = Session(name="my-project")
    >>>
    >>> # Add channels
    >>> claude = await TerminalChannel.create(command="claude")
    >>> shell = await TerminalChannel.create(command="bash")
    >>>
    >>> session.add("claude", claude)
    >>> session.add("shell", shell)
    >>>
    >>> # Use channels through session
    >>> response = await session.send("claude", "Hello!", parser=ParserType.CLAUDE)
    >>>
    >>> # Or access directly
    >>> channel = session.get("shell")
    >>> await channel.send("ls -la")
    >>>
    >>> # Close all
    >>> await session.close()
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.channels import Channel, ChannelInfo
    from nerve.core.types import ParsedResponse, ParserType


@dataclass
class Session:
    """A logical grouping of channels with metadata.

    Sessions provide:
    - Named access to multiple channels
    - Shared metadata and tags
    - Convenience methods for common operations
    - Lifecycle management (close all channels at once)

    Sessions are optional - you can use channels directly
    if you don't need grouping.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    _channels: dict[str, Channel] = field(default_factory=dict)

    def __post_init__(self):
        if not self.name:
            self.name = self.id

    def add(self, name: str, channel: Channel) -> None:
        """Add a channel to the session.

        Args:
            name: Name to reference the channel by.
            channel: The channel to add.

        Raises:
            ValueError: If name already exists.
        """
        if name in self._channels:
            raise ValueError(f"Channel '{name}' already exists in session")
        self._channels[name] = channel

    def get(self, name: str) -> Channel | None:
        """Get a channel by name.

        Args:
            name: Channel name.

        Returns:
            The channel, or None if not found.
        """
        return self._channels.get(name)

    def remove(self, name: str) -> Channel | None:
        """Remove a channel from the session.

        Note: This does NOT close the channel.

        Args:
            name: Channel name.

        Returns:
            The removed channel, or None if not found.
        """
        return self._channels.pop(name, None)

    def list_channels(self) -> list[str]:
        """List all channel names.

        Returns:
            List of channel names.
        """
        return list(self._channels.keys())

    def get_channel_info(self) -> dict[str, ChannelInfo]:
        """Get info for all channels.

        Returns:
            Dict of channel name -> ChannelInfo.
        """
        return {
            name: channel.to_info()
            for name, channel in self._channels.items()
            if hasattr(channel, "to_info")
        }

    async def send(
        self,
        channel_name: str,
        input: str,
        parser: ParserType | None = None,
        timeout: float | None = None,
    ) -> ParsedResponse:
        """Send input to a named channel.

        Convenience method that combines get() and send().

        Args:
            channel_name: Name of the channel.
            input: Input to send.
            parser: How to parse the response.
            timeout: Response timeout.

        Returns:
            Parsed response.

        Raises:
            KeyError: If channel not found.
        """
        channel = self._channels.get(channel_name)
        if not channel:
            raise KeyError(f"Channel '{channel_name}' not found in session")

        return await channel.send(input, parser=parser, timeout=timeout)

    async def close(self, channel_name: str | None = None) -> None:
        """Close channel(s).

        Args:
            channel_name: Specific channel to close, or None for all.
        """
        if channel_name:
            channel = self._channels.get(channel_name)
            if channel:
                await channel.close()
                del self._channels[channel_name]
        else:
            # Close all
            for channel in self._channels.values():
                await channel.close()
            self._channels.clear()

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict.

        Returns:
            Dict representation of session.
        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
            "channels": {
                name: channel.to_info().to_dict()
                for name, channel in self._channels.items()
                if hasattr(channel, "to_info")
            },
        }

    def __len__(self) -> int:
        return len(self._channels)

    def __contains__(self, name: str) -> bool:
        return name in self._channels

    def __repr__(self) -> str:
        channels = ", ".join(self._channels.keys())
        return f"Session(id={self.id!r}, name={self.name!r}, channels=[{channels}])"
