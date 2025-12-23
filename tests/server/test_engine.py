"""Tests for NerveEngine, specifically the GET_HISTORY handler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nerve.server.engine import NerveEngine
from nerve.server.protocols import Command, CommandType


class MockEventSink:
    """Mock event sink for testing."""

    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


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
        engine._node_factory.history_base_dir = tmp_path
        return engine

    @pytest.mark.asyncio
    async def test_get_history_returns_entries(self, engine, tmp_path):
        """Test that GET_HISTORY returns history entries for a node."""
        try:
            # Create a node with history
            await engine.execute(Command(
                type=CommandType.CREATE_NODE,
                params={
                    "node_id": "test-node",
                    "command": "bash",
                    "history": True,
                },
            ))

            # Send some input to create history entries
            node = engine._nodes.get("test-node")
            # Write directly to create history entry
            await node.write("echo hello\n")

            # Get history
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={"node_id": "test-node"},
            ))

            assert result.success is True
            assert result.data["node_id"] == "test-node"
            assert result.data["server_name"] == "test-server"
            assert isinstance(result.data["entries"], list)
            assert result.data["total"] >= 1  # At least the write entry
        finally:
            # Stop all nodes
            for node in list(engine._nodes.values()):
                await node.stop()
            engine._nodes.clear()

    @pytest.mark.asyncio
    async def test_get_history_with_last_limit(self, engine, tmp_path):
        """Test that 'last' parameter limits results."""
        try:
            # Create a node
            await engine.execute(Command(
                type=CommandType.CREATE_NODE,
                params={
                    "node_id": "test-limit",
                    "command": "bash",
                },
            ))

            node = engine._nodes.get("test-limit")
            # Create multiple history entries
            for i in range(5):
                await node.write(f"cmd{i}\n")

            # Get only last 2 entries
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={
                    "node_id": "test-limit",
                    "last": 2,
                },
            ))

            assert result.success is True
            assert result.data["total"] == 2
            assert len(result.data["entries"]) == 2
        finally:
            for node in list(engine._nodes.values()):
                await node.stop()
            engine._nodes.clear()

    @pytest.mark.asyncio
    async def test_get_history_with_op_filter(self, engine, tmp_path):
        """Test that 'op' parameter filters by operation type."""
        try:
            # Create a node
            await engine.execute(Command(
                type=CommandType.CREATE_NODE,
                params={
                    "node_id": "test-op",
                    "command": "bash",
                },
            ))

            node = engine._nodes.get("test-op")
            # Create different types of entries (all writes)
            await node.write("some data\n")
            await node.write("ls\n")

            # Filter by 'write' operation
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={
                    "node_id": "test-op",
                    "op": "write",
                },
            ))

            assert result.success is True
            # All entries should be 'write' operations
            for entry in result.data["entries"]:
                assert entry["op"] == "write"
        finally:
            for node in list(engine._nodes.values()):
                await node.stop()
            engine._nodes.clear()

    @pytest.mark.asyncio
    async def test_get_history_with_inputs_only(self, engine, tmp_path):
        """Test that 'inputs_only' filters to input operations."""
        try:
            # Create a node
            await engine.execute(Command(
                type=CommandType.CREATE_NODE,
                params={
                    "node_id": "test-inputs",
                    "command": "bash",
                },
            ))

            node = engine._nodes.get("test-inputs")
            # Create entries
            await node.write("data\n")
            await node.write("ls\n")

            # Get inputs only
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={
                    "node_id": "test-inputs",
                    "inputs_only": True,
                },
            ))

            assert result.success is True
            # All entries should be input operations
            input_ops = {"send", "write"}
            for entry in result.data["entries"]:
                assert entry["op"] in input_ops
        finally:
            for node in list(engine._nodes.values()):
                await node.stop()
            engine._nodes.clear()

    @pytest.mark.asyncio
    async def test_get_history_missing_node(self, engine, tmp_path):
        """Test graceful handling when node doesn't exist."""
        # Get history for non-existent node
        result = await engine.execute(Command(
            type=CommandType.GET_HISTORY,
            params={"node_id": "nonexistent"},
        ))

        # Should succeed with empty results, not error
        assert result.success is True
        assert result.data["node_id"] == "nonexistent"
        assert result.data["entries"] == []
        assert result.data["total"] == 0
        assert "note" in result.data

    @pytest.mark.asyncio
    async def test_get_history_no_history_node(self, engine, tmp_path):
        """Test node created with history=False."""
        try:
            # Create a node without history
            await engine.execute(Command(
                type=CommandType.CREATE_NODE,
                params={
                    "node_id": "no-history",
                    "command": "bash",
                    "history": False,
                },
            ))

            # Get history for node with disabled history
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={"node_id": "no-history"},
            ))

            # Should succeed with empty results
            assert result.success is True
            assert result.data["entries"] == []
            assert result.data["total"] == 0
            assert "note" in result.data
        finally:
            for node in list(engine._nodes.values()):
                await node.stop()
            engine._nodes.clear()

    @pytest.mark.asyncio
    async def test_get_history_requires_node_id(self, engine):
        """Test that node_id is required."""
        result = await engine.execute(Command(
            type=CommandType.GET_HISTORY,
            params={},  # Missing node_id
        ))

        assert result.success is False
        assert "node_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_get_history_uses_engine_server_name(self, engine, tmp_path):
        """Test that server_name defaults to engine's server name."""
        try:
            # Create a node
            await engine.execute(Command(
                type=CommandType.CREATE_NODE,
                params={
                    "node_id": "test-default-server",
                    "command": "bash",
                },
            ))

            # Get history without specifying server_name
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={"node_id": "test-default-server"},
            ))

            assert result.success is True
            # Server name should default to engine's server name
            assert result.data["server_name"] == "test-server"
        finally:
            for node in list(engine._nodes.values()):
                await node.stop()
            engine._nodes.clear()
