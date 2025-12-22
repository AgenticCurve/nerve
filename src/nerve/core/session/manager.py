"""Managers for channels and sessions.

Two levels of management:
- ChannelManager: Manages individual channels directly
- SessionManager: Manages sessions (groups of channels)

Use ChannelManager when you just need channels without grouping.
Use SessionManager when you need logical groupings with metadata.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from nerve.core.channels import ChannelState
from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel
from nerve.core.channels.history import HistoryError, HistoryWriter
from nerve.core.channels.pty import PTYChannel
from nerve.core.channels.wezterm import WezTermChannel
from nerve.core.session.session import Session

if TYPE_CHECKING:
    from nerve.core.channels import Channel

logger = logging.getLogger(__name__)


@dataclass
class ChannelManager:
    """Manage individual channels.

    A simple registry for tracking channels without session grouping.
    Use this when you just need to manage channels directly.

    Example:
        >>> manager = ChannelManager()
        >>>
        >>> # Create channels (name is required)
        >>> claude = await manager.create_terminal("claude-main", command="claude")
        >>> shell = await manager.create_terminal("my-shell", command="bash")
        >>>
        >>> # Get a channel by name
        >>> channel = manager.get("claude-main")
        >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
        >>>
        >>> # Close all
        >>> await manager.close_all()
    """

    _channels: dict[str, Channel] = field(default_factory=dict)
    _server_name: str = field(default="default")
    _history_base_dir: Path | None = field(default=None)

    async def create_terminal(
        self,
        channel_id: str,
        command: list[str] | str | None = None,
        backend: str = "pty",
        cwd: str | None = None,
        pane_id: str | None = None,
        history: bool = True,
        **kwargs,
    ) -> PTYChannel | WezTermChannel | ClaudeOnWezTermChannel:
        """Create a new terminal channel.

        Args:
            channel_id: Unique channel identifier (required).
            command: Command to run (e.g., "claude" or ["bash"]).
            backend: Backend type ("pty", "wezterm", or "claude-wezterm").
            cwd: Working directory.
            pane_id: For WezTerm, attach to existing pane.
            history: Enable history logging (default: True).
            **kwargs: Additional args passed to channel create.

        Returns:
            The created channel.

        Raises:
            ValueError: If channel_id already exists.
        """
        if self._channels.get(channel_id):
            raise ValueError(f"Channel '{channel_id}' already exists")

        # Create history writer if enabled
        history_writer = None
        if history:
            try:
                history_writer = HistoryWriter.create(
                    channel_id=channel_id,
                    server_name=self._server_name,
                    base_dir=self._history_base_dir,
                    enabled=True,
                )
            except (HistoryError, ValueError) as e:
                # Log warning but continue without history
                logger.warning(f"Failed to create history writer for {channel_id}: {e}")
                history_writer = None

        channel: PTYChannel | WezTermChannel | ClaudeOnWezTermChannel

        try:
            if backend == "claude-wezterm":
                # ClaudeOnWezTerm - requires "claude" in command
                if not command:
                    raise ValueError("command is required for claude-wezterm backend")
                channel = await ClaudeOnWezTermChannel.create(
                    channel_id=channel_id,
                    command=command if isinstance(command, str) else " ".join(command),
                    cwd=cwd,
                    history_writer=history_writer,
                    **kwargs,
                )
            elif backend == "wezterm" or pane_id is not None:
                if pane_id:
                    # Attach to existing WezTerm pane
                    channel = await WezTermChannel.attach(
                        channel_id=channel_id,
                        pane_id=pane_id,
                        history_writer=history_writer,
                        **kwargs,
                    )
                else:
                    # Spawn new WezTerm pane
                    channel = await WezTermChannel.create(
                        channel_id=channel_id,
                        command=command,
                        cwd=cwd,
                        history_writer=history_writer,
                        **kwargs,
                    )
            else:
                # Use PTY
                channel = await PTYChannel.create(
                    channel_id=channel_id,
                    command=command,
                    cwd=cwd,
                    history_writer=history_writer,
                    **kwargs,
                )

            self._channels[channel.id] = channel
            return channel

        except Exception:
            # Clean up history writer on channel creation failure
            if history_writer is not None:
                history_writer.close()
            raise

    def add(self, channel: Channel) -> None:
        """Add an existing channel to the manager.

        Args:
            channel: The channel to add.
        """
        self._channels[channel.id] = channel

    def get(self, channel_id: str) -> Channel | None:
        """Get a channel by ID.

        Args:
            channel_id: The channel ID.

        Returns:
            The Channel, or None if not found.
        """
        return self._channels.get(channel_id)

    def list(self) -> list[str]:
        """List all channel IDs.

        Returns:
            List of channel IDs.
        """
        return list(self._channels.keys())

    def list_open(self) -> list[str]:
        """List IDs of open channels.

        Returns:
            List of open channel IDs.
        """
        return [
            cid
            for cid, channel in self._channels.items()
            if channel.state != ChannelState.CLOSED
        ]

    async def close(self, channel_id: str) -> bool:
        """Close a channel.

        Args:
            channel_id: The channel ID.

        Returns:
            True if closed, False if not found.
        """
        channel = self._channels.get(channel_id)
        if channel:
            await channel.close()
            del self._channels[channel_id]
            return True
        return False

    async def close_all(self) -> None:
        """Close all channels."""
        for channel in self._channels.values():
            await channel.close()
        self._channels.clear()


@dataclass
class SessionManager:
    """Manage sessions (groups of channels).

    Use this when you need logical groupings of channels with metadata.

    Example:
        >>> manager = SessionManager()
        >>>
        >>> # Create a session
        >>> session = manager.create_session(name="my-project")
        >>>
        >>> # Add channels to it
        >>> claude = await PTYChannel.create("claude", command="claude")
        >>> session.add("claude", claude)
        >>>
        >>> # Or use the channel manager
        >>> shell = await manager.channels.create_terminal("shell", command="bash")
        >>> session.add("shell", shell)
        >>>
        >>> # Close session (closes all its channels)
        >>> await manager.close_session(session.id)
    """

    _sessions: dict[str, Session] = field(default_factory=dict)
    channels: ChannelManager = field(default_factory=ChannelManager)

    def create_session(
        self,
        name: str | None = None,
        session_id: str | None = None,
        description: str = "",
        tags: list[str] | None = None,
    ) -> Session:
        """Create a new session.

        Args:
            name: Session name (defaults to ID).
            session_id: Optional session ID.
            description: Session description.
            tags: Optional tags.

        Returns:
            The created Session.
        """
        session = Session(
            id=session_id or "",
            name=name or "",
            description=description,
            tags=tags or [],
        )
        self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID.

        Args:
            session_id: The session ID.

        Returns:
            The Session, or None if not found.
        """
        return self._sessions.get(session_id)

    def find_by_name(self, name: str) -> Session | None:
        """Find a session by name.

        Args:
            name: Session name.

        Returns:
            The Session, or None if not found.
        """
        for session in self._sessions.values():
            if session.name == name:
                return session
        return None

    def list_sessions(self) -> list[str]:
        """List all session IDs.

        Returns:
            List of session IDs.
        """
        return list(self._sessions.keys())

    async def close_session(self, session_id: str) -> bool:
        """Close a session and all its channels.

        Args:
            session_id: The session ID.

        Returns:
            True if closed, False if not found.
        """
        session = self._sessions.get(session_id)
        if session:
            await session.close()
            del self._sessions[session_id]
            return True
        return False

    async def close_all(self) -> None:
        """Close all sessions and standalone channels."""
        for session in self._sessions.values():
            await session.close()
        self._sessions.clear()

        await self.channels.close_all()
