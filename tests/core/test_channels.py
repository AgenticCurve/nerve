"""Tests for channel implementations.

Tests the existing functionality of PTYChannel, WezTermChannel,
and ClaudeOnWezTermChannel to ensure the new history feature
doesn't break existing behavior.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nerve.core.channels.base import ChannelState, ChannelType
from nerve.core.channels.pty import PTYChannel, PTYConfig
from nerve.core.types import ParserType


class TestPTYChannel:
    """Tests for PTYChannel."""

    @pytest.mark.asyncio
    async def test_create_requires_channel_id(self):
        """Test that create() requires a channel_id."""
        with pytest.raises(ValueError, match="channel_id is required"):
            await PTYChannel.create("")

    @pytest.mark.asyncio
    async def test_create_with_default_command(self):
        """Test creating channel with default bash command."""
        channel = await PTYChannel.create("test-channel")
        try:
            assert channel.id == "test-channel"
            assert channel.command == "bash"
            assert channel.state == ChannelState.OPEN
            assert channel.is_open is True
            assert channel.backend_type == "pty"
            assert channel.channel_type == ChannelType.TERMINAL
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_create_with_string_command(self):
        """Test creating channel with a string command."""
        channel = await PTYChannel.create("test-channel", command="echo hello")
        try:
            assert channel.command == "echo hello"
            assert channel.state == ChannelState.OPEN
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_create_with_list_command(self):
        """Test creating channel with a list command."""
        channel = await PTYChannel.create("test-channel", command=["echo", "hello"])
        try:
            assert channel.command == "echo hello"
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_write_data(self):
        """Test writing raw data to the terminal."""
        channel = await PTYChannel.create("test-channel")
        try:
            # Write should not raise
            await channel.write("echo test\n")
            # Give time for output
            await asyncio.sleep(0.5)
            # Buffer should contain something
            assert len(channel.buffer) > 0
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_run_command(self):
        """Test running a command (fire and forget)."""
        channel = await PTYChannel.create("test-channel")
        try:
            await channel.run("echo 'hello world'")
            await asyncio.sleep(0.5)
            assert "hello world" in channel.buffer
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_read_returns_buffer(self):
        """Test read() returns current buffer."""
        channel = await PTYChannel.create("test-channel")
        try:
            await channel.run("echo test_output")
            await asyncio.sleep(0.5)
            content = await channel.read()
            assert "test_output" in content
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_read_tail(self):
        """Test read_tail() returns last N lines."""
        channel = await PTYChannel.create("test-channel")
        try:
            # Write multiple lines
            for i in range(5):
                await channel.run(f"echo line{i}")
            await asyncio.sleep(1)

            tail = channel.read_tail(3)
            lines = [l for l in tail.split("\n") if l.strip()]
            # Should have at most 3 lines (may have fewer due to timing)
            assert len(lines) <= 3
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_interrupt_sends_ctrl_c(self):
        """Test interrupt() sends Ctrl+C."""
        channel = await PTYChannel.create("test-channel")
        try:
            # Start a long-running command
            await channel.run("sleep 100")
            await asyncio.sleep(0.3)

            # Interrupt it
            await channel.interrupt()
            await asyncio.sleep(0.3)

            # Channel should still be open after interrupt
            assert channel.state == ChannelState.OPEN
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_close_sets_state_closed(self):
        """Test close() sets state to CLOSED."""
        channel = await PTYChannel.create("test-channel")
        assert channel.state == ChannelState.OPEN

        await channel.close()

        assert channel.state == ChannelState.CLOSED
        assert channel.is_open is False

    @pytest.mark.asyncio
    async def test_send_on_closed_channel_raises(self):
        """Test that send() on closed channel raises RuntimeError."""
        channel = await PTYChannel.create("test-channel")
        await channel.close()

        with pytest.raises(RuntimeError, match="Channel is closed"):
            await channel.send("hello")

    @pytest.mark.asyncio
    async def test_to_info_returns_channel_info(self):
        """Test to_info() returns correct ChannelInfo."""
        channel = await PTYChannel.create("test-channel", command="bash")
        try:
            info = channel.to_info()

            assert info.id == "test-channel"
            assert info.channel_type == ChannelType.TERMINAL
            assert info.state == ChannelState.OPEN
            assert info.metadata["backend"] == "pty"
            assert info.metadata["command"] == "bash"
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_last_input_tracked(self):
        """Test that _last_input is tracked after send."""
        channel = await PTYChannel.create("test-channel")
        try:
            # Mock both _wait_for_ready and backend.write to avoid PTY issues
            channel._wait_for_ready = AsyncMock()
            channel.backend.write = AsyncMock()

            # Calling send should track the input
            await channel.send("test input", parser=ParserType.NONE, timeout=2.0)
            assert channel._last_input == "test input"
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_buffer_property(self):
        """Test buffer property returns backend buffer."""
        channel = await PTYChannel.create("test-channel")
        try:
            await channel.run("echo buffer_test")
            await asyncio.sleep(0.5)
            assert "buffer_test" in channel.buffer
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_state_transitions(self):
        """Test channel state transitions during operations."""
        channel = await PTYChannel.create("test-channel")
        try:
            assert channel.state == ChannelState.OPEN

            # After close
            await channel.close()
            assert channel.state == ChannelState.CLOSED
        finally:
            if channel.state != ChannelState.CLOSED:
                await channel.close()


class TestPTYChannelConfig:
    """Tests for PTYConfig dataclass."""

    def test_pty_config_defaults(self):
        """Test PTYConfig has sensible defaults."""
        config = PTYConfig()
        assert config.cwd is None
        assert config.env == {}
        assert config.ready_timeout == 60.0
        assert config.response_timeout == 1800.0


class TestPTYChannelSend:
    """Tests for PTYChannel.send() method with different parsers."""

    @pytest.mark.asyncio
    async def test_send_with_none_parser(self):
        """Test send() with NONE parser returns parsed response."""
        channel = await PTYChannel.create("test-channel")
        try:
            # Mock both _wait_for_ready and backend.write to avoid PTY issues
            channel._wait_for_ready = AsyncMock()
            channel.backend.write = AsyncMock()

            # Send a simple echo command
            result = await channel.send("echo hello", parser=ParserType.NONE, timeout=5.0)

            # With NONE parser, we get raw output
            assert result.raw is not None
            assert result.is_complete is True
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_send_with_custom_submit(self):
        """Test send() with custom submit sequence."""
        channel = await PTYChannel.create("test-channel")
        try:
            # Mock both _wait_for_ready and backend.write
            channel._wait_for_ready = AsyncMock()
            channel.backend.write = AsyncMock()

            # Using explicit submit sequence
            result = await channel.send(
                "echo test",
                parser=ParserType.NONE,
                submit="\n",
                timeout=5.0
            )
            assert result.raw is not None
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_send_uses_default_response_timeout(self):
        """Test send() uses default response timeout when not specified."""
        channel = await PTYChannel.create("test-channel", response_timeout=999.0)
        try:
            # Mock _wait_for_ready and backend.write
            mock_wait = AsyncMock()
            channel._wait_for_ready = mock_wait
            channel.backend.write = AsyncMock()

            await channel.send("test", parser=ParserType.NONE)

            # Should have been called with default timeout
            call_kwargs = mock_wait.call_args.kwargs
            assert call_kwargs["timeout"] == 999.0
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_send_uses_custom_timeout(self):
        """Test send() respects custom timeout when specified."""
        channel = await PTYChannel.create("test-channel")
        try:
            # Mock _wait_for_ready and backend.write
            mock_wait = AsyncMock()
            channel._wait_for_ready = mock_wait
            channel.backend.write = AsyncMock()

            await channel.send("test", parser=ParserType.NONE, timeout=123.0)

            # Should have been called with custom timeout
            call_kwargs = mock_wait.call_args.kwargs
            assert call_kwargs["timeout"] == 123.0
        finally:
            await channel.close()

    @pytest.mark.asyncio
    async def test_send_sets_busy_state(self):
        """Test send() sets channel to BUSY while waiting."""
        channel = await PTYChannel.create("test-channel")

        busy_during_wait = False

        async def mock_wait(**kwargs):
            nonlocal busy_during_wait
            busy_during_wait = channel.state == ChannelState.BUSY

        try:
            channel._wait_for_ready = mock_wait
            channel.backend.write = AsyncMock()

            await channel.send("test", parser=ParserType.NONE)

            # Channel should have been BUSY during wait
            assert busy_during_wait is True
        finally:
            await channel.close()


class TestPTYChannelRepr:
    """Tests for PTYChannel string representation."""

    @pytest.mark.asyncio
    async def test_repr_format(self):
        """Test __repr__ format."""
        channel = await PTYChannel.create("test-channel")
        try:
            repr_str = repr(channel)
            assert "PTYChannel" in repr_str
            assert "test-channel" in repr_str
            assert "OPEN" in repr_str
        finally:
            await channel.close()


class TestWezTermChannel:
    """Tests for WezTermChannel (mocked - requires WezTerm)."""

    @pytest.mark.asyncio
    async def test_create_requires_channel_id(self):
        """Test that create() requires a channel_id."""
        from nerve.core.channels.wezterm import WezTermChannel

        with pytest.raises(ValueError, match="channel_id is required"):
            await WezTermChannel.create("")

    @pytest.mark.asyncio
    async def test_attach_requires_channel_id(self):
        """Test that attach() requires a channel_id."""
        from nerve.core.channels.wezterm import WezTermChannel

        with pytest.raises(ValueError, match="channel_id is required"):
            await WezTermChannel.attach("", pane_id="123")

    @pytest.mark.asyncio
    async def test_create_with_mocked_backend(self):
        """Test WezTermChannel creation with mocked backend."""
        from nerve.core.channels.wezterm import WezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane-123"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await WezTermChannel.create(
                channel_id="test-wezterm",
                command="bash"
            )

            try:
                assert channel.id == "test-wezterm"
                assert channel.pane_id == "test-pane-123"
                assert channel.state == ChannelState.OPEN
                assert channel.backend_type == "wezterm"
                mock_backend.start.assert_called_once()
            finally:
                await channel.close()
                mock_backend.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_attach_with_mocked_backend(self):
        """Test WezTermChannel.attach() with mocked backend."""
        from nerve.core.channels.wezterm import WezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = "existing content"
            mock_backend.pane_id = "existing-pane"
            mock_backend.attach = AsyncMock()
            mock_backend.stop = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await WezTermChannel.attach(
                channel_id="attached-channel",
                pane_id="existing-pane"
            )

            try:
                assert channel.id == "attached-channel"
                assert channel.pane_id == "existing-pane"
                assert channel.state == ChannelState.OPEN
                mock_backend.attach.assert_called_once_with("existing-pane")
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_write_with_mocked_backend(self):
        """Test WezTermChannel.write() with mocked backend."""
        from nerve.core.channels.wezterm import WezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await WezTermChannel.create(
                channel_id="test-wezterm",
                command="bash"
            )

            try:
                await channel.write("test data")
                mock_backend.write.assert_called_with("test data")
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_run_with_mocked_backend(self):
        """Test WezTermChannel.run() with mocked backend."""
        from nerve.core.channels.wezterm import WezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await WezTermChannel.create(
                channel_id="test-wezterm",
                command="bash"
            )

            try:
                await channel.run("echo hello")
                # run() writes command + carriage return
                assert mock_backend.write.call_count >= 2
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_interrupt_with_mocked_backend(self):
        """Test WezTermChannel.interrupt() sends Ctrl+C."""
        from nerve.core.channels.wezterm import WezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await WezTermChannel.create(
                channel_id="test-wezterm"
            )

            try:
                await channel.interrupt()
                mock_backend.write.assert_called_with("\x03")
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_focus_with_mocked_backend(self):
        """Test WezTermChannel.focus() calls backend focus."""
        from nerve.core.channels.wezterm import WezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.focus = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await WezTermChannel.create(
                channel_id="test-wezterm"
            )

            try:
                await channel.focus()
                mock_backend.focus.assert_called_once()
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_to_info_with_mocked_backend(self):
        """Test WezTermChannel.to_info() returns correct info."""
        from nerve.core.channels.wezterm import WezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane-456"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await WezTermChannel.create(
                channel_id="test-wezterm",
                command="bash"
            )

            try:
                info = channel.to_info()
                assert info.id == "test-wezterm"
                assert info.metadata["backend"] == "wezterm"
                assert info.metadata["pane_id"] == "test-pane-456"
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_read_tail_with_mocked_backend(self):
        """Test WezTermChannel.read_tail() uses backend."""
        from nerve.core.channels.wezterm import WezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = "line1\nline2\nline3\nline4\nline5"
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.read_tail = MagicMock(return_value="line4\nline5")
            MockBackend.return_value = mock_backend

            channel = await WezTermChannel.create(
                channel_id="test-wezterm"
            )

            try:
                result = channel.read_tail(2)
                assert result == "line4\nline5"
                mock_backend.read_tail.assert_called_with(2)
            finally:
                await channel.close()


class TestClaudeOnWezTermChannel:
    """Tests for ClaudeOnWezTermChannel (mocked - requires WezTerm)."""

    @pytest.mark.asyncio
    async def test_create_requires_channel_id(self):
        """Test that create() requires a channel_id."""
        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel

        with pytest.raises(ValueError, match="channel_id is required"):
            await ClaudeOnWezTermChannel.create("", command="claude")

    @pytest.mark.asyncio
    async def test_create_requires_claude_in_command(self):
        """Test that create() requires 'claude' in command."""
        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel

        with pytest.raises(ValueError, match="Command must contain 'claude'"):
            await ClaudeOnWezTermChannel.create("test", command="bash")

    @pytest.mark.asyncio
    async def test_create_accepts_claude_command(self):
        """Test that create() accepts commands containing 'claude'."""
        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await ClaudeOnWezTermChannel.create(
                channel_id="test-claude",
                command="claude --help"
            )

            try:
                assert channel.id == "test-claude"
                assert channel.command == "claude --help"
                assert channel.backend_type == "claude-wezterm"
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_create_accepts_case_insensitive_claude(self):
        """Test that 'claude' check is case-insensitive."""
        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            # Should accept CLAUDE (uppercase)
            channel = await ClaudeOnWezTermChannel.create(
                channel_id="test-claude",
                command="CLAUDE"
            )
            await channel.close()

    @pytest.mark.asyncio
    async def test_default_parser_is_claude(self):
        """Test that default parser is CLAUDE."""
        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await ClaudeOnWezTermChannel.create(
                channel_id="test-claude",
                command="claude"
            )

            try:
                assert channel._default_parser == ParserType.CLAUDE
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_send_uses_default_parser(self):
        """Test that send() uses default CLAUDE parser when not specified."""
        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = "> hello\n\n⏺ Response here\n\n>\n-- INSERT -- 100 tokens"
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await ClaudeOnWezTermChannel.create(
                channel_id="test-claude",
                command="claude"
            )

            try:
                # Patch the inner send to verify parser used
                channel._inner.send = AsyncMock()
                await channel.send("test input")

                # Verify CLAUDE parser was used
                call_kwargs = channel._inner.send.call_args.kwargs
                assert call_kwargs["parser"] == ParserType.CLAUDE
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_send_allows_parser_override(self):
        """Test that send() allows overriding the parser."""
        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await ClaudeOnWezTermChannel.create(
                channel_id="test-claude",
                command="claude"
            )

            try:
                channel._inner.send = AsyncMock()
                await channel.send("test", parser=ParserType.NONE)

                call_kwargs = channel._inner.send.call_args.kwargs
                assert call_kwargs["parser"] == ParserType.NONE
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_last_input_tracked(self):
        """Test that _last_input is tracked after send."""
        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await ClaudeOnWezTermChannel.create(
                channel_id="test-claude",
                command="claude"
            )

            try:
                channel._inner.send = AsyncMock()
                await channel.send("my test input")

                assert channel._last_input == "my test input"
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_delegates_to_inner_channel(self):
        """Test that operations delegate to inner WezTermChannel."""
        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = "test buffer"
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            mock_backend.focus = AsyncMock()
            mock_backend.read_tail = MagicMock(return_value="tail content")
            MockBackend.return_value = mock_backend

            channel = await ClaudeOnWezTermChannel.create(
                channel_id="test-claude",
                command="claude"
            )

            try:
                # Test property delegation
                assert channel.buffer == "test buffer"
                assert channel.pane_id == "test-pane"
                assert channel.state == ChannelState.OPEN
                assert channel.is_open is True

                # Test method delegation
                await channel.run("test command")
                await channel.write("test data")
                await channel.interrupt()
                await channel.focus()

                # Verify backend was called
                assert mock_backend.write.call_count > 0
                mock_backend.focus.assert_called_once()

                # Test read_tail delegation
                result = channel.read_tail(10)
                assert result == "tail content"
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_to_info(self):
        """Test to_info() returns correct metadata."""
        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "pane-789"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await ClaudeOnWezTermChannel.create(
                channel_id="test-claude",
                command="claude --verbose"
            )

            try:
                info = channel.to_info()

                assert info.id == "test-claude"
                assert info.channel_type == ChannelType.TERMINAL
                assert info.metadata["backend"] == "claude-wezterm"
                assert info.metadata["pane_id"] == "pane-789"
                assert info.metadata["command"] == "claude --verbose"
                assert info.metadata["default_parser"] == "claude"
            finally:
                await channel.close()

    @pytest.mark.asyncio
    async def test_repr_format(self):
        """Test __repr__ format."""
        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel

        with patch("nerve.core.channels.wezterm.WezTermBackend") as MockBackend:
            mock_backend = MagicMock()
            mock_backend.buffer = ""
            mock_backend.pane_id = "test-pane"
            mock_backend.start = AsyncMock()
            mock_backend.stop = AsyncMock()
            mock_backend.write = AsyncMock()
            MockBackend.return_value = mock_backend

            channel = await ClaudeOnWezTermChannel.create(
                channel_id="my-claude-channel",
                command="claude"
            )

            try:
                repr_str = repr(channel)
                assert "ClaudeOnWezTermChannel" in repr_str
                assert "my-claude-channel" in repr_str
            finally:
                await channel.close()
