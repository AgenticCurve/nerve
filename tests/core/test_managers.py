"""Tests for ChannelManager and SessionManager.

Tests the existing functionality of session and channel management
to ensure the new history feature doesn't break existing behavior.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nerve.core.channels.base import ChannelState, ChannelType
from nerve.core.session.manager import ChannelManager, SessionManager
from nerve.core.session.session import Session
from nerve.core.types import ParserType


class TestChannelManager:
    """Tests for ChannelManager."""

    def test_empty_manager(self):
        """Test empty channel manager."""
        manager = ChannelManager()
        assert manager.list() == []
        assert manager.list_open() == []
        assert manager.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_create_terminal_pty(self):
        """Test creating a PTY terminal channel."""
        manager = ChannelManager()

        try:
            channel = await manager.create_terminal(
                channel_id="test-pty",
                command="bash",
                backend="pty"
            )

            assert channel.id == "test-pty"
            assert channel.state == ChannelState.OPEN
            assert "test-pty" in manager.list()
            assert "test-pty" in manager.list_open()
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_create_terminal_duplicate_raises(self):
        """Test that creating duplicate channel raises ValueError."""
        manager = ChannelManager()

        try:
            await manager.create_terminal(channel_id="test-channel")

            with pytest.raises(ValueError, match="already exists"):
                await manager.create_terminal(channel_id="test-channel")
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_create_terminal_wezterm_mocked(self):
        """Test creating WezTerm channel (mocked)."""
        manager = ChannelManager()

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            MockBackend.return_value = mock_backend

            try:
                channel = await manager.create_terminal(
                    channel_id="test-wezterm",
                    command="bash",
                    backend="wezterm"
                )

                assert channel.id == "test-wezterm"
                assert channel.pane_id == "test-pane"
                assert "test-wezterm" in manager.list()
            finally:
                await manager.close_all()

    @pytest.mark.asyncio
    async def test_create_terminal_wezterm_attach_mocked(self):
        """Test attaching to WezTerm pane (mocked)."""
        manager = ChannelManager()

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "existing-pane"
            mock_backend.attach = AsyncMock()
            mock_backend.stop = AsyncMock()
            MockBackend.return_value = mock_backend

            try:
                channel = await manager.create_terminal(
                    channel_id="attached-channel",
                    pane_id="existing-pane"
                )

                assert channel.id == "attached-channel"
                assert channel.pane_id == "existing-pane"
            finally:
                await manager.close_all()

    @pytest.mark.asyncio
    async def test_create_terminal_claude_wezterm_requires_command(self):
        """Test that claude-wezterm backend requires command."""
        manager = ChannelManager()

        with pytest.raises(ValueError, match="command is required"):
            await manager.create_terminal(
                channel_id="test",
                backend="claude-wezterm"
            )

    @pytest.mark.asyncio
    async def test_create_terminal_claude_wezterm_mocked(self):
        """Test creating claude-wezterm channel (mocked)."""
        manager = ChannelManager()

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "claude-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            try:
                channel = await manager.create_terminal(
                    channel_id="test-claude",
                    command="claude --help",
                    backend="claude-wezterm"
                )

                assert channel.id == "test-claude"
                assert channel.backend_type == "claude-wezterm"
            finally:
                await manager.close_all()

    @pytest.mark.asyncio
    async def test_add_existing_channel(self):
        """Test adding an existing channel to manager."""
        manager = ChannelManager()

        from nerve.core.channels.pty import PTYChannel
        channel = await PTYChannel.create("external-channel")

        try:
            manager.add(channel)

            assert "external-channel" in manager.list()
            assert manager.get("external-channel") is channel
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_get_channel(self):
        """Test getting a channel by ID."""
        manager = ChannelManager()

        try:
            created = await manager.create_terminal(channel_id="test-get")

            retrieved = manager.get("test-get")
            assert retrieved is created

            assert manager.get("nonexistent") is None
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_list_channels(self):
        """Test listing channel IDs."""
        manager = ChannelManager()

        try:
            await manager.create_terminal(channel_id="channel-a")
            await manager.create_terminal(channel_id="channel-b")
            await manager.create_terminal(channel_id="channel-c")

            channels = manager.list()
            assert len(channels) == 3
            assert "channel-a" in channels
            assert "channel-b" in channels
            assert "channel-c" in channels
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_list_open_channels(self):
        """Test listing only open channels."""
        manager = ChannelManager()

        try:
            await manager.create_terminal(channel_id="open-1")
            await manager.create_terminal(channel_id="open-2")
            await manager.create_terminal(channel_id="to-close")

            # Close one channel
            await manager.close("to-close")

            open_channels = manager.list_open()
            assert len(open_channels) == 2
            assert "open-1" in open_channels
            assert "open-2" in open_channels
            assert "to-close" not in open_channels
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_close_channel(self):
        """Test closing a specific channel."""
        manager = ChannelManager()

        try:
            await manager.create_terminal(channel_id="to-close")
            assert "to-close" in manager.list()

            result = await manager.close("to-close")
            assert result is True
            assert "to-close" not in manager.list()

            # Closing again returns False
            result = await manager.close("to-close")
            assert result is False
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_close_nonexistent_channel(self):
        """Test closing a channel that doesn't exist."""
        manager = ChannelManager()

        result = await manager.close("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_all_channels(self):
        """Test closing all channels."""
        manager = ChannelManager()

        try:
            await manager.create_terminal(channel_id="ch-1")
            await manager.create_terminal(channel_id="ch-2")
            await manager.create_terminal(channel_id="ch-3")

            assert len(manager.list()) == 3

            await manager.close_all()

            assert len(manager.list()) == 0
        finally:
            pass  # Already closed


class TestSession:
    """Tests for Session."""

    def test_session_creation_with_defaults(self):
        """Test creating session with default values."""
        session = Session()

        assert session.id is not None
        assert len(session.id) == 8  # UUID[:8]
        assert session.name == session.id  # Name defaults to ID
        assert session.description == ""
        assert session.tags == []
        assert session.created_at is not None

    def test_session_creation_with_values(self):
        """Test creating session with specified values."""
        session = Session(
            id="my-session",
            name="Test Session",
            description="A test session",
            tags=["test", "example"]
        )

        assert session.id == "my-session"
        assert session.name == "Test Session"
        assert session.description == "A test session"
        assert session.tags == ["test", "example"]

    def test_add_channel(self):
        """Test adding a channel to session."""
        session = Session()
        mock_channel = MagicMock()
        mock_channel.id = "test-channel"

        session.add("test", mock_channel)

        assert "test" in session
        assert len(session) == 1
        assert session.get("test") is mock_channel

    def test_add_duplicate_raises(self):
        """Test that adding duplicate channel name raises."""
        session = Session()
        mock_channel = MagicMock()

        session.add("test", mock_channel)

        with pytest.raises(ValueError, match="already exists"):
            session.add("test", MagicMock())

    def test_get_channel(self):
        """Test getting a channel by name."""
        session = Session()
        mock_channel = MagicMock()

        session.add("my-channel", mock_channel)

        assert session.get("my-channel") is mock_channel
        assert session.get("nonexistent") is None

    def test_remove_channel(self):
        """Test removing a channel."""
        session = Session()
        mock_channel = MagicMock()

        session.add("to-remove", mock_channel)
        assert "to-remove" in session

        removed = session.remove("to-remove")
        assert removed is mock_channel
        assert "to-remove" not in session

    def test_remove_nonexistent(self):
        """Test removing nonexistent channel returns None."""
        session = Session()

        result = session.remove("nonexistent")
        assert result is None

    def test_list_channels(self):
        """Test listing channel names."""
        session = Session()

        session.add("ch-a", MagicMock())
        session.add("ch-b", MagicMock())
        session.add("ch-c", MagicMock())

        names = session.list_channels()
        assert len(names) == 3
        assert "ch-a" in names
        assert "ch-b" in names
        assert "ch-c" in names

    def test_get_channel_info(self):
        """Test getting info for all channels."""
        session = Session()

        mock_channel = MagicMock()
        mock_info = MagicMock()
        mock_channel.to_info.return_value = mock_info

        session.add("test", mock_channel)

        info = session.get_channel_info()
        assert "test" in info
        assert info["test"] is mock_info

    @pytest.mark.asyncio
    async def test_send_to_channel(self):
        """Test sending to a named channel."""
        session = Session()

        mock_channel = MagicMock()
        mock_response = MagicMock()
        mock_channel.send = AsyncMock(return_value=mock_response)

        session.add("test", mock_channel)

        result = await session.send("test", "hello", parser=ParserType.NONE)

        assert result is mock_response
        mock_channel.send.assert_called_once_with(
            "hello",
            parser=ParserType.NONE,
            timeout=None
        )

    @pytest.mark.asyncio
    async def test_send_to_nonexistent_raises(self):
        """Test sending to nonexistent channel raises KeyError."""
        session = Session()

        with pytest.raises(KeyError, match="not found"):
            await session.send("nonexistent", "hello")

    @pytest.mark.asyncio
    async def test_close_specific_channel(self):
        """Test closing a specific channel."""
        session = Session()

        mock_channel = MagicMock()
        mock_channel.close = AsyncMock()

        session.add("to-close", mock_channel)
        assert "to-close" in session

        await session.close("to-close")

        mock_channel.close.assert_called_once()
        assert "to-close" not in session

    @pytest.mark.asyncio
    async def test_close_all_channels(self):
        """Test closing all channels."""
        session = Session()

        channels = [MagicMock(), MagicMock(), MagicMock()]
        for i, ch in enumerate(channels):
            ch.close = AsyncMock()
            session.add(f"ch-{i}", ch)

        assert len(session) == 3

        await session.close()

        for ch in channels:
            ch.close.assert_called_once()
        assert len(session) == 0

    def test_to_dict(self):
        """Test converting session to dict."""
        session = Session(
            id="test-id",
            name="Test Name",
            description="Test desc",
            tags=["tag1", "tag2"]
        )

        mock_channel = MagicMock()
        mock_info = MagicMock()
        mock_info.to_dict.return_value = {"id": "ch-1", "state": "open"}
        mock_channel.to_info.return_value = mock_info

        session.add("channel1", mock_channel)

        result = session.to_dict()

        assert result["id"] == "test-id"
        assert result["name"] == "Test Name"
        assert result["description"] == "Test desc"
        assert result["tags"] == ["tag1", "tag2"]
        assert "created_at" in result
        assert "channels" in result

    def test_contains(self):
        """Test __contains__ for channel name lookup."""
        session = Session()
        session.add("exists", MagicMock())

        assert "exists" in session
        assert "missing" not in session

    def test_len(self):
        """Test __len__ returns channel count."""
        session = Session()

        assert len(session) == 0

        session.add("ch1", MagicMock())
        assert len(session) == 1

        session.add("ch2", MagicMock())
        assert len(session) == 2

    def test_repr(self):
        """Test __repr__ format."""
        session = Session(id="my-id", name="My Session")
        session.add("channel1", MagicMock())

        repr_str = repr(session)
        assert "Session" in repr_str
        assert "my-id" in repr_str
        assert "My Session" in repr_str


class TestSessionManager:
    """Tests for SessionManager."""

    def test_empty_manager(self):
        """Test empty session manager."""
        manager = SessionManager()

        assert manager.list_sessions() == []
        assert manager.get_session("nonexistent") is None
        assert manager.find_by_name("nonexistent") is None

    def test_create_session(self):
        """Test creating a session."""
        manager = SessionManager()

        session = manager.create_session(name="test-session")

        assert session.name == "test-session"
        assert session.id in manager.list_sessions()
        assert manager.get_session(session.id) is session

    def test_create_session_with_id(self):
        """Test creating session with specified ID."""
        manager = SessionManager()

        session = manager.create_session(
            session_id="my-id",
            name="My Session",
            description="A test session",
            tags=["test"]
        )

        assert session.id == "my-id"
        assert session.name == "My Session"
        assert session.description == "A test session"
        assert session.tags == ["test"]

    def test_get_session(self):
        """Test getting a session by ID."""
        manager = SessionManager()

        session = manager.create_session(session_id="find-me")

        found = manager.get_session("find-me")
        assert found is session

        not_found = manager.get_session("nonexistent")
        assert not_found is None

    def test_find_by_name(self):
        """Test finding session by name."""
        manager = SessionManager()

        manager.create_session(name="session-one")
        session2 = manager.create_session(name="session-two")

        found = manager.find_by_name("session-two")
        assert found is session2

        not_found = manager.find_by_name("nonexistent")
        assert not_found is None

    def test_list_sessions(self):
        """Test listing session IDs."""
        manager = SessionManager()

        s1 = manager.create_session(session_id="s1")
        s2 = manager.create_session(session_id="s2")
        s3 = manager.create_session(session_id="s3")

        sessions = manager.list_sessions()
        assert len(sessions) == 3
        assert "s1" in sessions
        assert "s2" in sessions
        assert "s3" in sessions

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Test closing a session."""
        manager = SessionManager()

        session = manager.create_session(session_id="to-close")

        mock_channel = MagicMock()
        mock_channel.close = AsyncMock()
        session.add("ch", mock_channel)

        result = await manager.close_session("to-close")

        assert result is True
        assert "to-close" not in manager.list_sessions()
        mock_channel.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_nonexistent_session(self):
        """Test closing nonexistent session returns False."""
        manager = SessionManager()

        result = await manager.close_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_all(self):
        """Test closing all sessions and channels."""
        manager = SessionManager()

        s1 = manager.create_session(session_id="s1")
        s2 = manager.create_session(session_id="s2")

        ch1 = MagicMock()
        ch1.close = AsyncMock()
        s1.add("ch1", ch1)

        ch2 = MagicMock()
        ch2.close = AsyncMock()
        s2.add("ch2", ch2)

        await manager.close_all()

        assert manager.list_sessions() == []
        ch1.close.assert_called_once()
        ch2.close.assert_called_once()

    def test_channels_property(self):
        """Test that channels property returns ChannelManager."""
        manager = SessionManager()

        assert isinstance(manager.channels, ChannelManager)

    @pytest.mark.asyncio
    async def test_channels_integration(self):
        """Test using channel manager through session manager."""
        manager = SessionManager()

        try:
            # Create channel through the channels property
            channel = await manager.channels.create_terminal(
                channel_id="standalone",
                command="bash"
            )

            assert channel.id == "standalone"
            assert "standalone" in manager.channels.list()
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_close_all_includes_standalone_channels(self):
        """Test that close_all closes standalone channels too."""
        manager = SessionManager()

        try:
            # Create session with channel
            session = manager.create_session()
            session_channel = MagicMock()
            session_channel.close = AsyncMock()
            session.add("session-ch", session_channel)

            # Create standalone channel
            standalone = await manager.channels.create_terminal(
                channel_id="standalone"
            )

            await manager.close_all()

            # Both should be closed
            session_channel.close.assert_called_once()
            assert manager.channels.list() == []
        finally:
            pass  # Already closed


class TestChannelManagerWithKwargs:
    """Test that ChannelManager passes kwargs to channel creation."""

    @pytest.mark.asyncio
    async def test_passes_ready_timeout(self):
        """Test that ready_timeout is passed to channel."""
        manager = ChannelManager()

        try:
            channel = await manager.create_terminal(
                channel_id="test",
                ready_timeout=120.0
            )

            assert channel._ready_timeout == 120.0
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_passes_response_timeout(self):
        """Test that response_timeout is passed to channel."""
        manager = ChannelManager()

        try:
            channel = await manager.create_terminal(
                channel_id="test",
                response_timeout=3600.0  # 1 hour
            )

            assert channel._response_timeout == 3600.0
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_passes_cwd(self):
        """Test that cwd is passed to channel."""
        manager = ChannelManager()

        try:
            channel = await manager.create_terminal(
                channel_id="test",
                cwd="/tmp"
            )

            # For PTY, cwd is in the config
            assert channel.backend.config.cwd == "/tmp"
        finally:
            await manager.close_all()
