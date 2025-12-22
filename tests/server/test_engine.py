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
        engine._channel_manager._history_base_dir = tmp_path
        return engine

    @pytest.mark.asyncio
    async def test_get_history_returns_entries(self, engine, tmp_path):
        """Test that GET_HISTORY returns history entries for a channel."""
        try:
            # Create a channel with history
            await engine.execute(Command(
                type=CommandType.CREATE_CHANNEL,
                params={
                    "channel_id": "test-channel",
                    "command": "bash",
                    "history": True,
                },
            ))

            # Send some input to create history entries
            channel = engine._channel_manager.get("test-channel")
            # Write directly to create history entry
            await channel.write("echo hello\n")

            # Get history
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={"channel_id": "test-channel"},
            ))

            assert result.success is True
            assert result.data["channel_id"] == "test-channel"
            assert result.data["server_name"] == "test-server"
            assert isinstance(result.data["entries"], list)
            assert result.data["total"] >= 1  # At least the write entry
        finally:
            await engine._channel_manager.close_all()

    @pytest.mark.asyncio
    async def test_get_history_with_last_limit(self, engine, tmp_path):
        """Test that 'last' parameter limits results."""
        try:
            # Create a channel
            await engine.execute(Command(
                type=CommandType.CREATE_CHANNEL,
                params={
                    "channel_id": "test-limit",
                    "command": "bash",
                },
            ))

            channel = engine._channel_manager.get("test-limit")
            # Create multiple history entries
            for i in range(5):
                await channel.write(f"cmd{i}\n")

            # Get only last 2 entries
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={
                    "channel_id": "test-limit",
                    "last": 2,
                },
            ))

            assert result.success is True
            assert result.data["total"] == 2
            assert len(result.data["entries"]) == 2
        finally:
            await engine._channel_manager.close_all()

    @pytest.mark.asyncio
    async def test_get_history_with_op_filter(self, engine, tmp_path):
        """Test that 'op' parameter filters by operation type."""
        try:
            # Create a channel
            await engine.execute(Command(
                type=CommandType.CREATE_CHANNEL,
                params={
                    "channel_id": "test-op",
                    "command": "bash",
                },
            ))

            channel = engine._channel_manager.get("test-op")
            # Create different types of entries
            await channel.write("some data\n")
            await channel.run("ls")

            # Filter by 'write' operation
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={
                    "channel_id": "test-op",
                    "op": "write",
                },
            ))

            assert result.success is True
            # All entries should be 'write' operations
            for entry in result.data["entries"]:
                assert entry["op"] == "write"
        finally:
            await engine._channel_manager.close_all()

    @pytest.mark.asyncio
    async def test_get_history_with_inputs_only(self, engine, tmp_path):
        """Test that 'inputs_only' filters to input operations."""
        try:
            # Create a channel
            await engine.execute(Command(
                type=CommandType.CREATE_CHANNEL,
                params={
                    "channel_id": "test-inputs",
                    "command": "bash",
                },
            ))

            channel = engine._channel_manager.get("test-inputs")
            # Create different types of entries
            await channel.write("data\n")
            await channel.run("ls")

            # Get inputs only
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={
                    "channel_id": "test-inputs",
                    "inputs_only": True,
                },
            ))

            assert result.success is True
            # All entries should be input operations
            input_ops = {"send", "write", "run"}
            for entry in result.data["entries"]:
                assert entry["op"] in input_ops
        finally:
            await engine._channel_manager.close_all()

    @pytest.mark.asyncio
    async def test_get_history_missing_channel(self, engine, tmp_path):
        """Test graceful handling when channel doesn't exist."""
        # Get history for non-existent channel
        result = await engine.execute(Command(
            type=CommandType.GET_HISTORY,
            params={"channel_id": "nonexistent"},
        ))

        # Should succeed with empty results, not error
        assert result.success is True
        assert result.data["channel_id"] == "nonexistent"
        assert result.data["entries"] == []
        assert result.data["total"] == 0
        assert "note" in result.data

    @pytest.mark.asyncio
    async def test_get_history_no_history_channel(self, engine, tmp_path):
        """Test channel created with history=False."""
        try:
            # Create a channel without history
            await engine.execute(Command(
                type=CommandType.CREATE_CHANNEL,
                params={
                    "channel_id": "no-history",
                    "command": "bash",
                    "history": False,
                },
            ))

            # Get history for channel with disabled history
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={"channel_id": "no-history"},
            ))

            # Should succeed with empty results
            assert result.success is True
            assert result.data["entries"] == []
            assert result.data["total"] == 0
            assert "note" in result.data
        finally:
            await engine._channel_manager.close_all()

    @pytest.mark.asyncio
    async def test_get_history_requires_channel_id(self, engine):
        """Test that channel_id is required."""
        result = await engine.execute(Command(
            type=CommandType.GET_HISTORY,
            params={},  # Missing channel_id
        ))

        assert result.success is False
        assert "channel_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_get_history_uses_engine_server_name(self, engine, tmp_path):
        """Test that server_name defaults to engine's server name."""
        try:
            # Create a channel
            await engine.execute(Command(
                type=CommandType.CREATE_CHANNEL,
                params={
                    "channel_id": "test-default-server",
                    "command": "bash",
                },
            ))

            # Get history without specifying server_name
            result = await engine.execute(Command(
                type=CommandType.GET_HISTORY,
                params={"channel_id": "test-default-server"},
            ))

            assert result.success is True
            # Server name should default to engine's server name
            assert result.data["server_name"] == "test-server"
        finally:
            await engine._channel_manager.close_all()
