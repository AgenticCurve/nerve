"""Tests for nerve.core.nodes.terminal module.

These tests use mocked backends to verify terminal node behavior
without requiring actual PTY or WezTerm instances.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nerve.core.nodes.base import NodeState
from nerve.core.nodes.context import ExecutionContext
from nerve.core.nodes.terminal import ClaudeWezTermNode, PTYNode, WezTermNode
from nerve.core.session.session import Session
from nerve.core.types import ParsedResponse, ParserType, Section


def create_mock_pty_backend():
    """Create a mock PTYBackend that doesn't block."""
    backend = MagicMock()
    backend.buffer = "$ hello\nHELLO\n$ "
    backend.start = AsyncMock()
    backend.stop = AsyncMock()
    backend.write = AsyncMock()
    backend.read_tail = MagicMock(return_value="HELLO\n$ ")

    # clear_buffer should actually clear the buffer attribute
    def _clear_buffer():
        backend.buffer = ""

    backend.clear_buffer = MagicMock(side_effect=_clear_buffer)

    # Create a proper async generator for read_stream
    async def mock_read_stream():
        yield "HELLO"
        yield "\n$ "

    backend.read_stream = mock_read_stream
    return backend


def create_mock_wezterm_backend():
    """Create a mock WezTermBackend."""
    backend = MagicMock()
    backend.buffer = "$ hello\nHELLO\n$ "
    backend.pane_id = "42"
    backend.start = AsyncMock()
    backend.stop = AsyncMock()
    backend.write = AsyncMock()
    backend.attach = AsyncMock()
    backend.focus = AsyncMock()
    backend.get_pane_info = AsyncMock(return_value={"pane_id": "42"})
    backend.read_tail = MagicMock(return_value="HELLO\n$ ")

    # clear_buffer should actually clear the buffer attribute
    def _clear_buffer():
        backend.buffer = ""

    backend.clear_buffer = MagicMock(side_effect=_clear_buffer)

    async def mock_read_stream():
        yield "HELLO"
        yield "\n$ "

    backend.read_stream = mock_read_stream
    return backend


class TestPTYNode:
    """Tests for PTYNode."""

    @pytest.mark.asyncio
    async def test_pty_node_properties(self):
        """Test PTYNode properties."""
        mock_backend = create_mock_pty_backend()

        with (
            patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await PTYNode.create(id="test-node", session=session, command="bash")

            assert node.id == "test-node"
            assert node.persistent is True
            assert node.state == NodeState.READY
            assert node.command == "bash"

            await node.stop()

    @pytest.mark.asyncio
    async def test_pty_node_execute(self):
        """Test PTYNode.execute() method."""
        mock_backend = create_mock_pty_backend()
        mock_backend.buffer = ""

        with (
            patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("nerve.core.nodes.terminal.pty_node.get_parser") as mock_parser,
        ):
            # Setup parser mock
            parser_instance = MagicMock()
            parser_instance.is_ready = MagicMock(return_value=True)
            parser_instance.parse = MagicMock(
                return_value=ParsedResponse(
                    raw="HELLO",
                    sections=(Section(type="text", content="HELLO"),),
                    is_complete=True,
                    is_ready=True,
                )
            )
            mock_parser.return_value = parser_instance

            session = Session(history_enabled=False)
            node = await PTYNode.create(id="test-node", session=session, command="bash")

            # Update buffer to simulate response
            mock_backend.buffer = "hello\nHELLO\n$ "

            context = ExecutionContext(session=session, input="echo hello", parser=ParserType.NONE)

            result = await node.execute(context)

            assert isinstance(result, ParsedResponse)
            mock_backend.write.assert_called()
            await node.stop()

    @pytest.mark.asyncio
    async def test_pty_node_execute_stream(self):
        """Test PTYNode.execute_stream() method."""
        mock_backend = create_mock_pty_backend()

        with (
            patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("nerve.core.nodes.terminal.pty_node.get_parser") as mock_parser,
        ):
            parser_instance = MagicMock()
            parser_instance.is_ready = MagicMock(return_value=True)
            mock_parser.return_value = parser_instance

            session = Session(history_enabled=False)
            node = await PTYNode.create(id="test-node", session=session, command="bash")

            context = ExecutionContext(session=session, input="ls")

            chunks = []
            async for chunk in node.execute_stream(context):
                chunks.append(chunk)

            assert len(chunks) > 0
            assert "HELLO" in chunks
            await node.stop()

    @pytest.mark.asyncio
    async def test_pty_node_write(self):
        """Test PTYNode.write() method."""
        mock_backend = create_mock_pty_backend()

        with (
            patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await PTYNode.create(id="test-node", session=session, command="bash")

            await node.write("test data")

            mock_backend.write.assert_called_with("test data")
            await node.stop()

    @pytest.mark.asyncio
    async def test_pty_node_run(self):
        """Test PTYNode.run() fire-and-forget execution."""
        mock_backend = create_mock_pty_backend()

        with (
            patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await PTYNode.create(id="test-node", session=session, command="bash")

            await node.run("python script.py")

            # run() should write command with newline
            mock_backend.write.assert_called_with("python script.py\n")
            await node.stop()

    @pytest.mark.asyncio
    async def test_pty_node_read(self):
        """Test PTYNode.read() method."""
        mock_backend = create_mock_pty_backend()
        mock_backend.buffer = "test output"

        with (
            patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await PTYNode.create(id="test-node", session=session, command="bash")

            result = await node.read()

            assert result == "test output"
            await node.stop()

    @pytest.mark.asyncio
    async def test_pty_node_read_tail(self):
        """Test PTYNode.read_tail() method."""
        mock_backend = create_mock_pty_backend()

        with (
            patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await PTYNode.create(id="test-node", session=session, command="bash")

            result = node.read_tail(10)

            mock_backend.read_tail.assert_called_with(10)
            assert result == "HELLO\n$ "
            await node.stop()

    @pytest.mark.asyncio
    async def test_pty_node_interrupt(self):
        """Test PTYNode.interrupt() method."""
        mock_backend = create_mock_pty_backend()

        with (
            patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await PTYNode.create(id="test-node", session=session, command="bash")

            await node.interrupt()

            # Should write Ctrl+C
            mock_backend.write.assert_called_with("\x03")
            await node.stop()

    @pytest.mark.asyncio
    async def test_pty_node_stop(self):
        """Test PTYNode.stop() method."""
        mock_backend = create_mock_pty_backend()

        with (
            patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await PTYNode.create(id="test-node", session=session, command="bash")

            await node.stop()

            assert node.state == NodeState.STOPPED
            mock_backend.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_pty_node_to_info(self):
        """Test PTYNode.to_info() method."""
        mock_backend = create_mock_pty_backend()

        with (
            patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await PTYNode.create(id="test-node", session=session, command="bash")

            info = node.to_info()

            assert info.id == "test-node"
            assert info.node_type == "pty"
            assert info.persistent is True
            assert info.metadata["command"] == "bash"
            await node.stop()

    @pytest.mark.asyncio
    async def test_pty_node_requires_id(self):
        """Test PTYNode.create() requires node_id."""
        session = Session(history_enabled=False)
        with pytest.raises(ValueError):
            await PTYNode.create(id="", session=session, command="bash")

    @pytest.mark.asyncio
    async def test_pty_node_reset(self):
        """Test PTYNode.reset() clears buffer and state."""
        mock_backend = create_mock_pty_backend()

        with (
            patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await PTYNode.create(id="test-node", session=session, command="bash")

            # Set some state
            node.backend.buffer = "some output"
            node._last_input = "echo hello"

            # Reset
            await node.reset()

            # Buffer and state should be cleared
            assert node.backend.buffer == ""
            assert node._last_input == ""

            await node.stop()


class TestWezTermNode:
    """Tests for WezTermNode."""

    @pytest.mark.asyncio
    async def test_wezterm_node_properties(self):
        """Test WezTermNode properties."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            assert node.id == "test-node"
            assert node.persistent is True
            assert node.state == NodeState.READY
            assert node.pane_id == "42"

            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_execute(self):
        """Test WezTermNode.execute() method."""
        mock_backend = create_mock_wezterm_backend()
        mock_backend.buffer = "hello\nHELLO\n$ "

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("nerve.core.nodes.terminal.wezterm_node.get_parser") as mock_parser,
        ):
            parser_instance = MagicMock()
            parser_instance.is_ready = MagicMock(return_value=True)
            parser_instance.parse = MagicMock(
                return_value=ParsedResponse(
                    raw="HELLO",
                    sections=(Section(type="text", content="HELLO"),),
                    is_complete=True,
                    is_ready=True,
                )
            )
            mock_parser.return_value = parser_instance

            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            context = ExecutionContext(session=session, input="echo hello", parser=ParserType.NONE)

            result = await node.execute(context)

            assert isinstance(result, ParsedResponse)
            mock_backend.write.assert_called()
            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_execute_stream(self):
        """Test WezTermNode.execute_stream() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("nerve.core.nodes.terminal.wezterm_node.get_parser") as mock_parser,
        ):
            parser_instance = MagicMock()
            parser_instance.is_ready = MagicMock(return_value=True)
            mock_parser.return_value = parser_instance

            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            context = ExecutionContext(session=session, input="ls")

            chunks = []
            async for chunk in node.execute_stream(context):
                chunks.append(chunk)

            assert len(chunks) > 0
            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_attach(self):
        """Test WezTermNode.attach() method."""
        mock_backend = create_mock_wezterm_backend()

        with patch(
            "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.attach(id="test-node", session=session, pane_id="42")

            assert node.id == "test-node"
            assert node.pane_id == "42"
            mock_backend.attach.assert_called_with("42")
            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_focus(self):
        """Test WezTermNode.focus() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            await node.focus()

            mock_backend.focus.assert_called_once()
            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_get_pane_info(self):
        """Test WezTermNode.get_pane_info() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            info = await node.get_pane_info()

            assert info["pane_id"] == "42"
            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_write(self):
        """Test WezTermNode.write() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            await node.write("test data")

            mock_backend.write.assert_called_with("test data")
            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_run(self):
        """Test WezTermNode.run() fire-and-forget execution."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            await node.run("claude")

            # run() should write command, then \r separately (WezTerm pattern)
            calls = mock_backend.write.call_args_list
            assert len(calls) >= 2
            # Find the command and \r calls (may have other writes before)
            call_values = [c[0][0] for c in calls]
            assert "claude" in call_values
            assert "\r" in call_values
            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_read(self):
        """Test WezTermNode.read() method."""
        mock_backend = create_mock_wezterm_backend()
        mock_backend.buffer = "test output"

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            result = await node.read()

            assert result == "test output"
            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_read_tail(self):
        """Test WezTermNode.read_tail() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            node.read_tail(10)

            mock_backend.read_tail.assert_called_with(10)
            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_interrupt(self):
        """Test WezTermNode.interrupt() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            await node.interrupt()

            mock_backend.write.assert_called_with("\x03")
            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_stop(self):
        """Test WezTermNode.stop() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            await node.stop()

            assert node.state == NodeState.STOPPED
            mock_backend.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_wezterm_node_to_info(self):
        """Test WezTermNode.to_info() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            info = node.to_info()

            assert info.id == "test-node"
            assert info.node_type == "wezterm"
            assert info.persistent is True
            assert info.metadata["pane_id"] == "42"
            await node.stop()

    @pytest.mark.asyncio
    async def test_wezterm_node_requires_id(self):
        """Test WezTermNode.create() requires node_id."""
        session = Session(history_enabled=False)
        with pytest.raises(ValueError):
            await WezTermNode.create(id="", session=session, command="bash")

    @pytest.mark.asyncio
    async def test_wezterm_node_reset(self):
        """Test WezTermNode.reset() clears buffer and state."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await WezTermNode.create(id="test-node", session=session, command="bash")

            # Set some state
            node._last_input = "echo hello"

            # Reset
            await node.reset()

            # State should be cleared
            mock_backend.clear_buffer.assert_called()
            assert node._last_input == ""

            await node.stop()


class TestClaudeWezTermNode:
    """Tests for ClaudeWezTermNode."""

    @pytest.mark.asyncio
    async def test_claude_node_properties(self):
        """Test ClaudeWezTermNode properties."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(
                id="test-node", session=session, command="claude --dangerously-skip-permissions"
            )

            assert node.id == "test-node"
            assert node.persistent is True
            assert node.pane_id == "42"
            assert "claude" in node.command.lower()

            await node.stop()

    @pytest.mark.asyncio
    async def test_claude_node_requires_claude_in_command(self):
        """Test ClaudeWezTermNode requires 'claude' in command."""
        session = Session(history_enabled=False)
        with pytest.raises(ValueError, match="must contain 'claude'"):
            await ClaudeWezTermNode.create(id="test", session=session, command="bash")

    @pytest.mark.asyncio
    async def test_claude_node_execute(self):
        """Test ClaudeWezTermNode.execute() uses Claude parser by default."""
        mock_backend = create_mock_wezterm_backend()
        mock_backend.buffer = "Claude> Hello\n"

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("nerve.core.nodes.terminal.wezterm_node.get_parser") as mock_parser,
        ):
            parser_instance = MagicMock()
            parser_instance.is_ready = MagicMock(return_value=True)
            parser_instance.parse = MagicMock(
                return_value=ParsedResponse(
                    raw="Hello World",
                    sections=(Section(type="text", content="Hello World"),),
                    is_complete=True,
                    is_ready=True,
                )
            )
            mock_parser.return_value = parser_instance

            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(id="test-node", session=session, command="claude")

            context = ExecutionContext(session=session, input="Hello")

            result = await node.execute(context)

            assert isinstance(result, ParsedResponse)
            await node.stop()

    @pytest.mark.asyncio
    async def test_claude_node_execute_stream(self):
        """Test ClaudeWezTermNode.execute_stream() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("nerve.core.nodes.terminal.wezterm_node.get_parser") as mock_parser,
        ):
            parser_instance = MagicMock()
            parser_instance.is_ready = MagicMock(return_value=True)
            mock_parser.return_value = parser_instance

            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(id="test-node", session=session, command="claude")

            context = ExecutionContext(session=session, input="Hello")

            chunks = []
            async for chunk in node.execute_stream(context):
                chunks.append(chunk)

            assert len(chunks) > 0
            await node.stop()

    @pytest.mark.asyncio
    async def test_claude_node_write(self):
        """Test ClaudeWezTermNode.write() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(id="test-node", session=session, command="claude")

            await node.write("test data")

            mock_backend.write.assert_called_with("test data")
            await node.stop()

    @pytest.mark.asyncio
    async def test_claude_node_run(self):
        """Test ClaudeWezTermNode.run() fire-and-forget execution."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(id="test-node", session=session, command="claude")

            await node.run("python -m mymodule")

            # run() should write command, then \r separately (WezTerm pattern)
            calls = mock_backend.write.call_args_list
            assert len(calls) >= 2
            # Find the command and \r calls (may have other writes before)
            call_values = [c[0][0] for c in calls]
            assert "python -m mymodule" in call_values
            assert "\r" in call_values
            await node.stop()

    @pytest.mark.asyncio
    async def test_claude_node_read(self):
        """Test ClaudeWezTermNode.read() method."""
        mock_backend = create_mock_wezterm_backend()
        mock_backend.buffer = "Claude response"

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(id="test-node", session=session, command="claude")

            result = await node.read()

            assert result == "Claude response"
            await node.stop()

    @pytest.mark.asyncio
    async def test_claude_node_read_tail(self):
        """Test ClaudeWezTermNode.read_tail() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(id="test-node", session=session, command="claude")

            node.read_tail(10)

            mock_backend.read_tail.assert_called_with(10)
            await node.stop()

    @pytest.mark.asyncio
    async def test_claude_node_interrupt(self):
        """Test ClaudeWezTermNode.interrupt() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(id="test-node", session=session, command="claude")

            await node.interrupt()

            mock_backend.write.assert_called_with("\x03")
            await node.stop()

    @pytest.mark.asyncio
    async def test_claude_node_focus(self):
        """Test ClaudeWezTermNode.focus() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(id="test-node", session=session, command="claude")

            await node.focus()

            mock_backend.focus.assert_called_once()
            await node.stop()

    @pytest.mark.asyncio
    async def test_claude_node_stop(self):
        """Test ClaudeWezTermNode.stop() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(id="test-node", session=session, command="claude")

            await node.stop()

            assert node.state == NodeState.STOPPED

    @pytest.mark.asyncio
    async def test_claude_node_to_info(self):
        """Test ClaudeWezTermNode.to_info() method."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(
                id="test-node", session=session, command="claude --skip"
            )

            info = node.to_info()

            assert info.id == "test-node"
            assert info.node_type == "claude-wezterm"
            assert info.persistent is True
            assert info.metadata["default_parser"] == "claude"
            await node.stop()

    @pytest.mark.asyncio
    async def test_claude_node_requires_id(self):
        """Test ClaudeWezTermNode.create() requires node_id."""
        session = Session(history_enabled=False)
        with pytest.raises(ValueError):
            await ClaudeWezTermNode.create(id="", session=session, command="claude")

    @pytest.mark.asyncio
    async def test_claude_node_reset(self):
        """Test ClaudeWezTermNode.reset() clears buffer and state."""
        mock_backend = create_mock_wezterm_backend()

        with (
            patch(
                "nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session = Session(history_enabled=False)
            node = await ClaudeWezTermNode.create(id="test-node", session=session, command="claude")

            # Set some state
            node._last_input = "echo hello"

            # Reset - should delegate to inner node
            await node.reset()

            # State should be cleared
            mock_backend.clear_buffer.assert_called()
            assert node._last_input == ""

            await node.stop()
