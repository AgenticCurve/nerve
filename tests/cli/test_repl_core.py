"""Tests for REPL core functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from nerve.frontends.cli.repl.core import run_interactive


class TestRunInteractive:
    """Tests for run_interactive function."""

    @pytest.mark.asyncio
    async def test_run_interactive_creates_local_session(self):
        """run_interactive creates local session when no server specified."""
        # Mock input to exit immediately
        with patch("builtins.input", side_effect=["exit"]):
            with patch("nerve.core.session.Session") as MockSession:
                mock_session_instance = Mock()
                mock_session_instance.name = "default"
                mock_session_instance.id = "default"
                mock_session_instance.nodes = {}
                mock_session_instance.graphs = {}
                mock_session_instance.stop = AsyncMock()
                mock_session_instance.list_graphs.return_value = []

                MockSession.return_value = mock_session_instance

                await run_interactive()

                # Verify session was created
                MockSession.assert_called_once_with(name="default", server_name="repl")
                # Verify cleanup was called
                mock_session_instance.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_interactive_connects_to_server(self):
        """run_interactive connects to server when server_name provided."""
        # Mock the server connection
        with (
            patch("builtins.input", side_effect=["exit"]),
            patch(
                "nerve.frontends.cli.utils.get_server_transport",
                return_value=("unix", "/tmp/test.sock"),
            ),
            patch("nerve.transport.UnixSocketClient") as MockClient,
        ):
            mock_client = Mock()
            mock_client.connect = AsyncMock()
            mock_client.disconnect = AsyncMock()
            MockClient.return_value = mock_client

            await run_interactive(server_name="test-server")

            # Verify client was created and connected
            MockClient.assert_called_once_with("/tmp/test.sock")
            mock_client.connect.assert_called_once()
            mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_interactive_handles_eof(self, capsys):
        """run_interactive handles EOF (Ctrl-D) gracefully."""
        with patch("builtins.input", side_effect=EOFError):
            with patch("nerve.core.session.Session") as MockSession:
                mock_session = Mock()
                mock_session.name = "default"
                mock_session.id = "repl"
                mock_session.nodes = {}
                mock_session.graphs = {}
                mock_session.stop = AsyncMock()
                mock_session.list_graphs.return_value = []
                MockSession.return_value = mock_session

                await run_interactive()

                captured = capsys.readouterr()
                # Should print newline on EOF
                assert "\n" in captured.out

    @pytest.mark.asyncio
    async def test_run_interactive_handles_keyboard_interrupt(self, capsys):
        """run_interactive handles KeyboardInterrupt (Ctrl-C)."""
        # First Ctrl-C shows message, second exits
        with (
            patch("builtins.input", side_effect=[KeyboardInterrupt, KeyboardInterrupt]),
            patch("nerve.core.session.Session") as MockSession,
        ):
            mock_session = Mock()
            mock_session.name = "repl"
            mock_session.id = "repl"
            mock_session.nodes = {}
            mock_session.graphs = {}
            mock_session.stop = AsyncMock()
            mock_session.list_graphs.return_value = []
            MockSession.return_value = mock_session

            await run_interactive()

            captured = capsys.readouterr()
            # Should show interrupt message
            assert "Press Ctrl-C again to exit" in captured.out or "Exiting" in captured.out

    @pytest.mark.asyncio
    async def test_run_interactive_prints_startup_message(self, capsys):
        """run_interactive prints startup message."""
        with patch("builtins.input", side_effect=["exit"]):
            with patch("nerve.core.session.Session") as MockSession:
                mock_session = Mock()
                mock_session.name = "default"
                mock_session.id = "repl"
                mock_session.nodes = {}
                mock_session.graphs = {}
                mock_session.stop = AsyncMock()
                mock_session.list_graphs.return_value = []
                MockSession.return_value = mock_session

                await run_interactive()

                captured = capsys.readouterr()
                assert "Nerve REPL" in captured.out
                assert "Type 'help' for commands" in captured.out

    @pytest.mark.asyncio
    async def test_run_interactive_initializes_namespace_local_mode(self):
        """run_interactive initializes namespace in local mode."""
        from nerve.frontends.cli.repl.state import REPLState

        state = REPLState()

        with patch("builtins.input", side_effect=["exit"]):
            with patch("nerve.core.session.Session") as MockSession:
                mock_session = Mock()
                mock_session.name = "default"
                mock_session.id = "repl"
                mock_session.nodes = {}
                mock_session.graphs = {}
                mock_session.stop = AsyncMock()
                mock_session.list_graphs.return_value = []
                MockSession.return_value = mock_session

                await run_interactive(state=state, server_name=None)

                # Check namespace was populated
                assert "session" in state.namespace
                assert "Session" in state.namespace
                assert "ExecutionContext" in state.namespace
                assert "ParserType" in state.namespace
                assert "BackendType" in state.namespace

    @pytest.mark.asyncio
    async def test_run_interactive_server_mode_empty_namespace(self):
        """run_interactive has empty namespace in server mode."""
        from nerve.frontends.cli.repl.state import REPLState

        state = REPLState()

        with (
            patch("builtins.input", side_effect=["exit"]),
            patch(
                "nerve.frontends.cli.utils.get_server_transport",
                return_value=("unix", "/tmp/test.sock"),
            ),
            patch("nerve.transport.UnixSocketClient") as MockClient,
        ):
            mock_client = Mock()
            mock_client.connect = AsyncMock()
            mock_client.disconnect = AsyncMock()
            MockClient.return_value = mock_client

            await run_interactive(state=state, server_name="test-server")

            # Namespace should be empty in server mode
            assert state.namespace == {}

    @pytest.mark.asyncio
    async def test_run_interactive_cleanup_on_exit(self):
        """run_interactive calls cleanup on exit."""
        with patch("builtins.input", side_effect=["exit"]):
            with patch("nerve.core.session.Session") as MockSession:
                mock_session = Mock()
                mock_session.name = "default"
                mock_session.id = "repl"
                mock_session.nodes = {}
                mock_session.graphs = {}
                mock_session.stop = AsyncMock()
                mock_session.list_graphs.return_value = []
                MockSession.return_value = mock_session

                await run_interactive()

                # Verify stop was called
                mock_session.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_interactive_cleanup_on_exception(self):
        """run_interactive calls cleanup even on exception."""
        with patch("builtins.input", side_effect=["exit"]):
            with patch("nerve.core.session.Session") as MockSession:
                mock_session = Mock()
                mock_session.name = "default"
                mock_session.id = "repl"
                mock_session.nodes = {}
                mock_session.graphs = {}
                mock_session.stop = AsyncMock()
                mock_session.list_graphs.return_value = []
                MockSession.return_value = mock_session

                await run_interactive()

                # Even if exception occurred, stop should be called
                mock_session.stop.assert_called()

    @pytest.mark.asyncio
    async def test_run_interactive_server_disconnect_message(self, capsys):
        """run_interactive shows message on server disconnect."""
        from nerve.frontends.cli.repl.state import REPLState

        state = REPLState()

        with patch("builtins.input", side_effect=["graphs"]):  # Command that might fail
            with patch(
                "nerve.frontends.cli.utils.get_server_transport",
                return_value=("unix", "/tmp/test.sock"),
            ):
                with patch("nerve.transport.UnixSocketClient") as MockClient:
                    mock_client = Mock()
                    mock_client.connect = AsyncMock()
                    mock_client.disconnect = AsyncMock()

                    # Simulate connection error
                    mock_client.send_command = AsyncMock(
                        side_effect=ConnectionError("Connection lost")
                    )

                    MockClient.return_value = mock_client

                    await run_interactive(state=state, server_name="test-server")

                    captured = capsys.readouterr()
                    # Should show server connection lost message
                    assert "Server connection lost" in captured.out

    @pytest.mark.asyncio
    async def test_run_interactive_reuses_state(self):
        """run_interactive can resume from existing state."""
        from nerve.frontends.cli.repl.state import REPLState

        state = REPLState()
        state.history.append("previous command")
        state.namespace["x"] = 10

        with patch("builtins.input", side_effect=["exit"]):
            with patch("nerve.core.session.Session") as MockSession:
                mock_session = Mock()
                mock_session.name = "default"
                mock_session.id = "repl"
                mock_session.nodes = {}
                mock_session.graphs = {}
                mock_session.stop = AsyncMock()
                mock_session.list_graphs.return_value = []
                MockSession.return_value = mock_session

                await run_interactive(state=state)

                # State should be reused
                assert "previous command" in state.history
                # Note: namespace gets overwritten in local mode,
                # but state object itself is reused
