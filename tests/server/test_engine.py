"""Tests for NerveEngine, specifically the GET_HISTORY handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nerve.core.nodes.history import HistoryWriter
from nerve.server.engine import NerveEngine
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


class TestGetHistory:
    """Tests for _get_history handler."""

    @pytest.fixture
    def event_sink(self):
        """Create mock event sink."""
        return MockEventSink()

    @pytest.fixture
    def engine(self, event_sink, tmp_path):
        """Create engine with test configuration."""
        engine = NerveEngine(
            event_sink=event_sink,
            _server_name="test-server",
        )
        # Override history base dir for testing
        engine._default_session.history_base_dir = tmp_path
        return engine

    def _create_node_with_history(self, engine, node_id: str, tmp_path):
        """Helper to create a mock node with real history writer."""
        history_writer = HistoryWriter.create(
            node_id=node_id,
            server_name="test-server",
            base_dir=tmp_path,
            enabled=True,
        )
        mock_node = create_mock_node(node_id, history_writer)
        engine._default_session.nodes[node_id] = mock_node
        return mock_node, history_writer

    def _create_node_without_history(self, engine, node_id: str):
        """Helper to create a mock node without history."""
        mock_node = create_mock_node(node_id, history_writer=None)
        engine._default_session.nodes[node_id] = mock_node
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
            engine._default_session.nodes.clear()

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
            engine._default_session.nodes.clear()

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
            engine._default_session.nodes.clear()

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
            engine._default_session.nodes.clear()

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
            engine._default_session.nodes.clear()

    @pytest.mark.asyncio
    async def test_get_history_requires_node_id(self, engine):
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
            engine._default_session.nodes.clear()
