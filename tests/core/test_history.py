"""Tests for node history."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nerve.core.nodes.history import (
    HISTORY_BUFFER_LINES,
    HistoryError,
    HistoryReader,
    HistoryWriter,
)


class TestHistoryWriter:
    """Tests for HistoryWriter."""

    def test_create_writer(self, tmp_path: Path):
        """Test creating a history writer."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        assert writer.node_id == "test-node"
        assert writer.server_name == "test-server"
        assert writer.enabled is True
        assert writer.file_path.exists()

        writer.close()

    def test_disabled_writer_no_file(self, tmp_path: Path):
        """Test disabled writer doesn't create file."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
            enabled=False,
        )

        writer.log_run("echo hello")

        assert not writer.file_path.exists()
        writer.close()

    def test_log_run(self, tmp_path: Path):
        """Test logging a run operation."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        seq = writer.log_run("claude")
        writer.close()

        assert seq == 1

        # Verify file contents
        with open(writer.file_path) as f:
            entry = json.loads(f.readline())
            assert entry["seq"] == 1
            assert entry["op"] == "run"
            assert entry["input"] == "claude"
            assert "ts" in entry

    def test_log_write(self, tmp_path: Path):
        """Test logging a write operation."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        seq = writer.log_write("hello\n")
        writer.close()

        assert seq == 1

        with open(writer.file_path) as f:
            entry = json.loads(f.readline())
            assert entry["op"] == "write"
            assert entry["input"] == "hello\n"

    def test_log_read(self, tmp_path: Path):
        """Test logging a read/buffer capture."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        seq = writer.log_read("buffer content here", lines=50)
        writer.close()

        assert seq == 1

        with open(writer.file_path) as f:
            entry = json.loads(f.readline())
            assert entry["op"] == "read"
            assert entry["buffer"] == "buffer content here"
            assert entry["lines"] == 50

    def test_log_send(self, tmp_path: Path):
        """Test logging a send operation."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        response = {
            "sections": [{"type": "text", "content": "Hello!", "metadata": {}}],
            "tokens": {"input": 10, "output": 5},
            "is_complete": True,
            "is_ready": True,
        }

        seq = writer.log_send(
            input="Hello",
            response=response,
            preceding_buffer_seq=1,
            ts_start="2025-12-22T10:00:00Z",
            ts_end="2025-12-22T10:00:05Z",
        )
        writer.close()

        assert seq == 1

        with open(writer.file_path) as f:
            entry = json.loads(f.readline())
            assert entry["op"] == "send"
            assert entry["input"] == "Hello"
            assert entry["ts_start"] == "2025-12-22T10:00:00Z"
            assert entry["ts_end"] == "2025-12-22T10:00:05Z"
            assert entry["preceding_buffer_seq"] == 1
            assert entry["response"]["sections"][0]["content"] == "Hello!"

    def test_log_send_stream(self, tmp_path: Path):
        """Test logging a send_stream operation."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        seq = writer.log_send_stream(
            input="Write code",
            final_buffer="def hello():\n    pass\n",
            parser="claude",
            preceding_buffer_seq=1,
            ts_start="2025-12-22T10:00:00Z",
            ts_end="2025-12-22T10:00:10Z",
        )
        writer.close()

        assert seq == 1

        with open(writer.file_path) as f:
            entry = json.loads(f.readline())
            assert entry["op"] == "send_stream"
            assert entry["input"] == "Write code"
            assert entry["final_buffer"] == "def hello():\n    pass\n"
            assert entry["parser"] == "claude"

    def test_log_interrupt(self, tmp_path: Path):
        """Test logging an interrupt operation."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        seq = writer.log_interrupt()
        writer.close()

        assert seq == 1

        with open(writer.file_path) as f:
            entry = json.loads(f.readline())
            assert entry["op"] == "interrupt"
            assert "ts" in entry

    def test_log_delete(self, tmp_path: Path):
        """Test logging a delete event."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        seq = writer.log_delete(reason="user requested")
        writer.close()

        assert seq == 1

        with open(writer.file_path) as f:
            entry = json.loads(f.readline())
            assert entry["op"] == "delete"
            assert entry["reason"] == "user requested"

    def test_sequence_numbers_increment(self, tmp_path: Path):
        """Test that sequence numbers increment correctly."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        seq1 = writer.log_run("cmd1")
        seq2 = writer.log_read("buffer", 50)
        seq3 = writer.log_write("data")
        writer.close()

        assert seq1 == 1
        assert seq2 == 2
        assert seq3 == 3

    def test_sequence_recovery_on_append(self, tmp_path: Path):
        """Test sequence numbers continue from existing file."""
        # First writer
        writer1 = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )
        writer1.log_run("cmd1")  # seq 1
        writer1.log_run("cmd2")  # seq 2
        writer1.close()

        # Second writer (simulates server restart)
        writer2 = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )
        seq = writer2.log_run("cmd3")  # Should be seq 3
        writer2.close()

        assert seq == 3

    def test_error_handling_non_serializable(self, tmp_path: Path):
        """Test graceful handling of non-serializable objects."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        # This should not raise - uses default=str fallback
        seq = writer.log_send(
            input="test",
            response={"obj": object()},  # Non-serializable
            preceding_buffer_seq=1,
            ts_start="2025-01-01T00:00:00Z",
        )

        writer.close()
        # Should have written something (with str representation)
        assert seq > 0

    def test_create_failure_raises_history_error(self, tmp_path: Path):
        """Test that unwritable directory raises HistoryError."""
        # Create a file where directory should be
        blocker = tmp_path / "test-server"
        blocker.touch()  # File, not directory

        with pytest.raises(HistoryError):
            HistoryWriter.create(
                node_id="test-node",
                server_name="test-server",
                base_dir=tmp_path,
            )

    def test_invalid_node_id_raises_value_error(self, tmp_path: Path):
        """Test that invalid node_id raises ValueError."""
        with pytest.raises(ValueError, match="(?i)node"):
            HistoryWriter.create(
                node_id="INVALID_NAME",  # Uppercase not allowed
                server_name="test-server",
                base_dir=tmp_path,
            )

    def test_invalid_server_name_raises_value_error(self, tmp_path: Path):
        """Test that invalid server_name raises ValueError."""
        with pytest.raises(ValueError, match="(?i)server"):
            HistoryWriter.create(
                node_id="test-node",
                server_name="../escape",  # Path traversal attempt
                base_dir=tmp_path,
            )

    def test_disabled_writer_returns_zero(self, tmp_path: Path):
        """Test that disabled writer returns 0 for all log methods."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
            enabled=False,
        )

        assert writer.log_run("cmd") == 0
        assert writer.log_write("data") == 0
        assert writer.log_read("buffer", 50) == 0
        assert writer.log_interrupt() == 0
        assert writer.log_delete() == 0
        writer.close()

    def test_closed_writer_returns_zero(self, tmp_path: Path):
        """Test that closed writer returns 0 for all log methods."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )
        writer.close()

        assert writer.log_run("cmd") == 0
        assert writer.enabled is False


class TestHistoryReader:
    """Tests for HistoryReader."""

    @pytest.fixture
    def history_file(self, tmp_path: Path) -> Path:
        """Create a sample history file."""
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        writer.log_run("claude")
        writer.log_read("Claude started", lines=50)
        writer.log_send(
            input="Hello",
            response={
                "sections": [],
                "tokens": None,
                "is_complete": True,
                "is_ready": True,
            },
            preceding_buffer_seq=2,
            ts_start="2025-12-22T10:00:00Z",
        )
        writer.log_delete()
        writer.close()

        return tmp_path

    def test_get_all(self, history_file: Path):
        """Test getting all entries."""
        reader = HistoryReader.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=history_file,
        )

        entries = reader.get_all()

        assert len(entries) == 4
        assert entries[0]["op"] == "run"
        assert entries[-1]["op"] == "delete"

    def test_get_last(self, history_file: Path):
        """Test getting last N entries."""
        reader = HistoryReader.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=history_file,
        )

        entries = reader.get_last(2)

        assert len(entries) == 2
        assert entries[0]["op"] == "send"
        assert entries[1]["op"] == "delete"

    def test_get_by_op(self, history_file: Path):
        """Test filtering by operation type."""
        reader = HistoryReader.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=history_file,
        )

        sends = reader.get_by_op("send")

        assert len(sends) == 1
        assert sends[0]["input"] == "Hello"

    def test_get_by_seq(self, history_file: Path):
        """Test getting entry by sequence number."""
        reader = HistoryReader.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=history_file,
        )

        entry = reader.get_by_seq(1)

        assert entry is not None
        assert entry["op"] == "run"
        assert entry["input"] == "claude"

    def test_get_by_seq_not_found(self, history_file: Path):
        """Test get_by_seq returns None for missing seq."""
        reader = HistoryReader.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=history_file,
        )

        entry = reader.get_by_seq(999)

        assert entry is None

    def test_get_inputs_only(self, history_file: Path):
        """Test getting only input operations."""
        reader = HistoryReader.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=history_file,
        )

        inputs = reader.get_inputs_only()

        assert len(inputs) == 2  # run and send
        assert all(e["op"] in {"send", "write", "run"} for e in inputs)

    def test_reader_not_found_raises(self, tmp_path: Path):
        """Test reader raises FileNotFoundError for missing node."""
        with pytest.raises(FileNotFoundError):
            HistoryReader.create(
                node_id="nonexistent",
                server_name="test-server",
                base_dir=tmp_path,
            )

    def test_malformed_json_skipped(self, tmp_path: Path):
        """Test malformed lines are skipped."""
        # Create file with bad line
        server_dir = tmp_path / "test-server"
        server_dir.mkdir(parents=True)
        file_path = server_dir / "test-node.jsonl"

        with open(file_path, "w") as f:
            f.write('{"seq": 1, "op": "run", "ts": "2025-01-01T00:00:00Z", "input": "cmd"}\n')
            f.write("this is not json\n")  # Bad line
            f.write('{"seq": 2, "op": "delete", "ts": "2025-01-01T00:00:00Z", "reason": null}\n')

        reader = HistoryReader.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        entries = reader.get_all()
        assert len(entries) == 2  # Bad line skipped


class TestInterleavedAccess:
    """Tests for interleaved history access.

    Note: These tests verify interleaved (not truly concurrent) writes work
    correctly. Since log_*() methods are synchronous, Python's GIL ensures
    each write completes atomically. The await points between writes allow
    task switching, creating interleaved but not concurrent execution.
    """

    @pytest.mark.asyncio
    async def test_interleaved_writes(self, tmp_path: Path):
        """Test interleaved async writes don't corrupt file.

        This tests that multiple async tasks writing to the same history
        file produce valid output. Writes are interleaved (not concurrent)
        because log_write() is synchronous - task switching only occurs
        at await points between writes.
        """
        writer = HistoryWriter.create(
            node_id="test-node",
            server_name="test-server",
            base_dir=tmp_path,
        )

        async def write_entries(start: int, count: int):
            for i in range(count):
                writer.log_write(f"data_{start}_{i}")
                await asyncio.sleep(0.001)  # Yield point for task switching

        # Run interleaved writes from multiple tasks
        await asyncio.gather(
            write_entries(0, 10),
            write_entries(100, 10),
            write_entries(200, 10),
        )

        writer.close()

        # Verify all entries are valid JSON
        with open(writer.file_path) as f:
            lines = f.readlines()

        assert len(lines) == 30
        for line in lines:
            json.loads(line)  # Should not raise


class TestHistoryBufferLines:
    """Tests for HISTORY_BUFFER_LINES constant."""

    def test_constant_value(self):
        """Verify HISTORY_BUFFER_LINES has expected value."""
        assert HISTORY_BUFFER_LINES == 50
