"""Tests for NerveEngine, specifically the GET_HISTORY handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nerve.core.nodes.history import HistoryWriter
from nerve.server.engine import build_nerve_engine
from nerve.server.protocols import Command, CommandType


class MockEventSink:
    """Mock event sink for testing."""

    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


def create_mock_node(node_id: str, history_writer: HistoryWriter | None = None):
    """Create a mock node that doesn't spawn real processes."""
    mock_node = MagicMock()
    mock_node.id = node_id
    mock_node.stop = AsyncMock()
    mock_node.history_writer = history_writer

    async def mock_write(data: str):
        """Mock write that records to history."""
        if history_writer:
            history_writer.log_write(data)

    mock_node.write = mock_write
    return mock_node


def get_default_session(engine):
    """Helper to get the default session from the engine's session registry."""
    return engine.session_handler.session_registry.default_session


class TestGetHistory:
    """Tests for _get_history handler."""

    @pytest.fixture
    def event_sink(self):
        """Create mock event sink."""
        return MockEventSink()

    @pytest.fixture
    def engine(self, event_sink, tmp_path):
        """Create engine with test configuration."""
        engine = build_nerve_engine(
            event_sink=event_sink,
            server_name="test-server",
        )
        # Override history base dir for testing
        session = get_default_session(engine)
        session.history_base_dir = tmp_path
        return engine

    def _create_node_with_history(self, engine, node_id: str, tmp_path):
        """Helper to create a mock node with real history writer."""
        history_writer = HistoryWriter.create(
            node_id=node_id,
            server_name="test-server",
            session_name="default",
            base_dir=tmp_path,
            enabled=True,
        )
        mock_node = create_mock_node(node_id, history_writer)
        session = get_default_session(engine)
        session.nodes[node_id] = mock_node
        return mock_node, history_writer

    def _create_node_without_history(self, engine, node_id: str):
        """Helper to create a mock node without history."""
        mock_node = create_mock_node(node_id, history_writer=None)
        session = get_default_session(engine)
        session.nodes[node_id] = mock_node
        return mock_node

    @pytest.mark.asyncio
    async def test_get_history_returns_entries(self, engine, tmp_path):
        """Test that GET_HISTORY returns history entries for a node."""
        mock_node, history_writer = self._create_node_with_history(engine, "test-node", tmp_path)
        try:
            # Write directly to create history entry
            await mock_node.write("echo hello\n")

            # Get history
            result = await engine.execute(
                Command(
                    type=CommandType.GET_HISTORY,
                    params={"node_id": "test-node"},
                )
            )

            assert result.success is True
            assert result.data["node_id"] == "test-node"
            assert result.data["server_name"] == "test-server"
            assert isinstance(result.data["entries"], list)
            assert result.data["total"] >= 1  # At least the write entry
        finally:
            history_writer.close()
            get_default_session(engine).nodes.clear()

    @pytest.mark.asyncio
    async def test_get_history_with_last_limit(self, engine, tmp_path):
        """Test that 'last' parameter limits results."""
        mock_node, history_writer = self._create_node_with_history(engine, "test-limit", tmp_path)
        try:
            # Create multiple history entries
            for i in range(5):
                await mock_node.write(f"cmd{i}\n")

            # Get only last 2 entries
            result = await engine.execute(
                Command(
                    type=CommandType.GET_HISTORY,
                    params={
                        "node_id": "test-limit",
                        "last": 2,
                    },
                )
            )

            assert result.success is True
            assert result.data["total"] == 2
            assert len(result.data["entries"]) == 2
        finally:
            history_writer.close()
            get_default_session(engine).nodes.clear()

    @pytest.mark.asyncio
    async def test_get_history_with_op_filter(self, engine, tmp_path):
        """Test that 'op' parameter filters by operation type."""
        mock_node, history_writer = self._create_node_with_history(engine, "test-op", tmp_path)
        try:
            # Create different types of entries (all writes)
            await mock_node.write("some data\n")
            await mock_node.write("ls\n")

            # Filter by 'write' operation
            result = await engine.execute(
                Command(
                    type=CommandType.GET_HISTORY,
                    params={
                        "node_id": "test-op",
                        "op": "write",
                    },
                )
            )

            assert result.success is True
            # All entries should be 'write' operations
            for entry in result.data["entries"]:
                assert entry["op"] == "write"
        finally:
            history_writer.close()
            get_default_session(engine).nodes.clear()

    @pytest.mark.asyncio
    async def test_get_history_with_inputs_only(self, engine, tmp_path):
        """Test that 'inputs_only' filters to input operations."""
        mock_node, history_writer = self._create_node_with_history(engine, "test-inputs", tmp_path)
        try:
            # Create entries
            await mock_node.write("data\n")
            await mock_node.write("ls\n")

            # Get inputs only
            result = await engine.execute(
                Command(
                    type=CommandType.GET_HISTORY,
                    params={
                        "node_id": "test-inputs",
                        "inputs_only": True,
                    },
                )
            )

            assert result.success is True
            # All entries should be input operations
            input_ops = {"send", "write"}
            for entry in result.data["entries"]:
                assert entry["op"] in input_ops
        finally:
            history_writer.close()
            get_default_session(engine).nodes.clear()

    @pytest.mark.asyncio
    async def test_get_history_missing_node(self, engine, tmp_path):
        """Test graceful handling when node doesn't exist."""
        # Get history for non-existent node
        result = await engine.execute(
            Command(
                type=CommandType.GET_HISTORY,
                params={"node_id": "nonexistent"},
            )
        )

        # Should succeed with empty results, not error
        assert result.success is True
        assert result.data["node_id"] == "nonexistent"
        assert result.data["entries"] == []
        assert result.data["total"] == 0
        assert "note" in result.data

    @pytest.mark.asyncio
    async def test_get_history_no_history_node(self, engine, tmp_path):
        """Test node created with history=False."""
        self._create_node_without_history(engine, "no-history")
        try:
            # Get history for node with disabled history
            result = await engine.execute(
                Command(
                    type=CommandType.GET_HISTORY,
                    params={"node_id": "no-history"},
                )
            )

            # Should succeed with empty results
            assert result.success is True
            assert result.data["entries"] == []
            assert result.data["total"] == 0
            assert "note" in result.data
        finally:
            get_default_session(engine).nodes.clear()

    @pytest.mark.asyncio
    async def test_get_history_requires_node_id(self, engine, tmp_path):
        """Test that node_id is required."""
        result = await engine.execute(
            Command(
                type=CommandType.GET_HISTORY,
                params={},  # Missing node_id
            )
        )

        assert result.success is False
        assert "node_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_get_history_uses_engine_server_name(self, engine, tmp_path):
        """Test that server_name defaults to engine's server name."""
        mock_node, history_writer = self._create_node_with_history(
            engine, "test-default-server", tmp_path
        )
        try:
            # Get history without specifying server_name
            result = await engine.execute(
                Command(
                    type=CommandType.GET_HISTORY,
                    params={"node_id": "test-default-server"},
                )
            )

            assert result.success is True
            # Server name should default to engine's server name
            assert result.data["server_name"] == "test-server"
        finally:
            history_writer.close()
            get_default_session(engine).nodes.clear()


class TestTimeoutParameters:
    """Tests for timeout parameters in CREATE_NODE and EXECUTE_INPUT."""

    @pytest.fixture
    def event_sink(self):
        """Create mock event sink."""
        return MockEventSink()

    @pytest.fixture
    def engine(self, event_sink, tmp_path):
        """Create engine with test configuration."""
        engine = build_nerve_engine(
            event_sink=event_sink,
            server_name="test-server",
        )
        session = get_default_session(engine)
        session.history_base_dir = tmp_path
        return engine

    @pytest.mark.asyncio
    async def test_create_node_with_default_timeouts(self, engine):
        """Test CREATE_NODE uses default timeout values when not specified."""
        with patch("nerve.core.nodes.terminal.PTYNode.create") as mock_create:
            mock_node = MagicMock()
            mock_node.id = "test-node"
            mock_node.state = MagicMock()
            mock_create.return_value = mock_node

            result = await engine.execute(
                Command(
                    type=CommandType.CREATE_NODE,
                    params={
                        "node_id": "test-node",
                        "command": "echo",
                        "backend": "pty",
                    },
                )
            )

            assert result.success is True
            # Verify default timeout values were passed
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["response_timeout"] == 1800.0
            assert call_kwargs["ready_timeout"] == 60.0

    @pytest.mark.asyncio
    async def test_create_node_with_custom_timeouts(self, engine):
        """Test CREATE_NODE accepts custom timeout values."""
        with patch("nerve.core.nodes.terminal.PTYNode.create") as mock_create:
            mock_node = MagicMock()
            mock_node.id = "test-node"
            mock_node.state = MagicMock()
            mock_create.return_value = mock_node

            result = await engine.execute(
                Command(
                    type=CommandType.CREATE_NODE,
                    params={
                        "node_id": "test-node",
                        "command": "echo",
                        "backend": "pty",
                        "response_timeout": 3600.0,
                        "ready_timeout": 120.0,
                    },
                )
            )

            assert result.success is True
            # Verify custom timeout values were passed
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["response_timeout"] == 3600.0
            assert call_kwargs["ready_timeout"] == 120.0

    @pytest.mark.asyncio
    async def test_create_wezterm_node_with_timeouts(self, engine):
        """Test CREATE_NODE with wezterm backend passes timeout values."""
        with patch("nerve.core.nodes.terminal.WezTermNode.create") as mock_create:
            mock_node = MagicMock()
            mock_node.id = "test-node"
            mock_node.state = MagicMock()
            mock_create.return_value = mock_node

            result = await engine.execute(
                Command(
                    type=CommandType.CREATE_NODE,
                    params={
                        "node_id": "test-node",
                        "command": "echo",
                        "backend": "wezterm",
                        "response_timeout": 2400.0,
                        "ready_timeout": 90.0,
                    },
                )
            )

            assert result.success is True
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["response_timeout"] == 2400.0
            assert call_kwargs["ready_timeout"] == 90.0

    @pytest.mark.asyncio
    async def test_create_wezterm_attach_with_timeouts(self, engine):
        """Test CREATE_NODE with wezterm attach passes timeout values."""
        with patch("nerve.core.nodes.terminal.WezTermNode.attach") as mock_attach:
            mock_node = MagicMock()
            mock_node.id = "test-node"
            mock_node.state = MagicMock()
            mock_attach.return_value = mock_node

            result = await engine.execute(
                Command(
                    type=CommandType.CREATE_NODE,
                    params={
                        "node_id": "test-node",
                        "backend": "wezterm",
                        "pane_id": "123",
                        "response_timeout": 2400.0,
                        "ready_timeout": 90.0,
                    },
                )
            )

            assert result.success is True
            call_kwargs = mock_attach.call_args.kwargs
            assert call_kwargs["response_timeout"] == 2400.0
            assert call_kwargs["ready_timeout"] == 90.0

    @pytest.mark.asyncio
    async def test_create_claude_wezterm_node_with_timeouts(self, engine):
        """Test CREATE_NODE with claude-wezterm backend passes timeout values."""
        with patch("nerve.core.nodes.terminal.ClaudeWezTermNode.create") as mock_create:
            mock_node = MagicMock()
            mock_node.id = "test-node"
            mock_node.state = MagicMock()
            mock_create.return_value = mock_node

            result = await engine.execute(
                Command(
                    type=CommandType.CREATE_NODE,
                    params={
                        "node_id": "test-node",
                        "command": "claude",
                        "backend": "claude-wezterm",
                        "response_timeout": 3600.0,
                        "ready_timeout": 120.0,
                    },
                )
            )

            assert result.success is True
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["response_timeout"] == 3600.0
            assert call_kwargs["ready_timeout"] == 120.0

    @pytest.mark.asyncio
    async def test_execute_input_with_timeout(self, engine):
        """Test EXECUTE_INPUT passes timeout to ExecutionContext."""
        from nerve.core import ExecutionContext
        from nerve.core.types import ParsedResponse

        # Create a mock node
        mock_node = MagicMock()
        mock_node.id = "test-node"
        mock_node.state = MagicMock()

        # Capture the context passed to execute
        captured_context = None

        async def mock_execute(context: ExecutionContext):
            nonlocal captured_context
            captured_context = context
            return ParsedResponse(
                raw="test output",
                sections=(),
                is_complete=True,
                is_ready=True,
            )

        mock_node.execute = mock_execute
        session = get_default_session(engine)
        session.nodes["test-node"] = mock_node

        try:
            result = await engine.execute(
                Command(
                    type=CommandType.EXECUTE_INPUT,
                    params={
                        "node_id": "test-node",
                        "text": "hello",
                        "timeout": 2400.0,
                    },
                )
            )

            assert result.success is True
            assert captured_context is not None
            assert captured_context.timeout == 2400.0
        finally:
            session.nodes.clear()

    @pytest.mark.asyncio
    async def test_execute_input_without_timeout(self, engine):
        """Test EXECUTE_INPUT uses None timeout when not specified."""
        from nerve.core import ExecutionContext
        from nerve.core.types import ParsedResponse

        # Create a mock node
        mock_node = MagicMock()
        mock_node.id = "test-node"
        mock_node.state = MagicMock()

        # Capture the context passed to execute
        captured_context = None

        async def mock_execute(context: ExecutionContext):
            nonlocal captured_context
            captured_context = context
            return ParsedResponse(
                raw="test output",
                sections=(),
                is_complete=True,
                is_ready=True,
            )

        mock_node.execute = mock_execute
        session = get_default_session(engine)
        session.nodes["test-node"] = mock_node

        try:
            result = await engine.execute(
                Command(
                    type=CommandType.EXECUTE_INPUT,
                    params={
                        "node_id": "test-node",
                        "text": "hello",
                        # No timeout specified
                    },
                )
            )

            assert result.success is True
            assert captured_context is not None
            assert captured_context.timeout is None
        finally:
            session.nodes.clear()
