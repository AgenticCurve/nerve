"""Node history persistence.

Provides JSONL-based history recording for node operations.
All operations (send, send_stream, write, run, interrupt, read, delete)
are logged with timestamps and sequence numbers for debugging and auditing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nerve.core.validation import validate_name

logger = logging.getLogger(__name__)

# Buffer capture configuration
HISTORY_BUFFER_LINES = 50
"""Number of lines to capture for buffer state.

Rationale:
- 50 lines typically captures 1-2 Claude Code responses with context
- Matches read_tail() default in existing node implementations
- Balances debugging utility vs file size (avg ~5KB per buffer capture)
- Configurable per-node would add complexity without clear benefit for v1

Tradeoff: Very long single-line outputs may be truncated. For v1, this is
acceptable as the full buffer is still available in the terminal.
"""


class HistoryError(Exception):
    """Error during history operations."""

    pass


@dataclass
class HistoryWriter:
    """Writes node history to JSONL file.

    Append-only writer for node operations. All write operations are
    synchronous and atomic within the async context (no yielding during
    writes), so no explicit locking is required.

    Error Handling Policy: FAIL-SOFT
    - Errors are logged as warnings
    - Operations continue without history
    - Never raises exceptions to caller (except in create())

    Example:
        >>> writer = HistoryWriter.create("my-node", server_name="test")
        >>> writer.log_run("claude")
        >>> writer.log_read("Claude started...")
        >>> writer.log_send("Hello", response_data, preceding_buffer_seq=2)
        >>> writer.close()
    """

    node_id: str
    server_name: str
    file_path: Path
    _seq: int = field(default=0, repr=False)
    _file: Any = field(default=None, repr=False)
    _enabled: bool = field(default=True, repr=False)
    _closed: bool = field(default=False, repr=False)
    _last_op: str | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        node_id: str,
        server_name: str,
        base_dir: Path | None = None,
        enabled: bool = True,
    ) -> HistoryWriter:
        """Create a new history writer.

        If appending to existing file, recovers sequence number from last entry.

        Args:
            node_id: Unique node identifier.
            server_name: Server this node belongs to.
            base_dir: Base directory for history files (default: .nerve/history).
            enabled: Whether history logging is enabled.

        Returns:
            HistoryWriter instance.

        Raises:
            HistoryError: If directory creation or file access fails.
            ValueError: If node_id or server_name is invalid.
        """
        # Validate names to prevent path traversal (raises ValueError)
        validate_name(node_id, "node")
        validate_name(server_name, "server")

        if base_dir is None:
            base_dir = Path.cwd() / ".nerve" / "history"

        server_dir = base_dir / server_name
        file_path = server_dir / f"{node_id}.jsonl"

        # Create instance first (before any file ops)
        writer = cls(
            node_id=node_id,
            server_name=server_name,
            file_path=file_path,
            _enabled=enabled,
        )

        if not enabled:
            return writer

        try:
            # Create directory
            server_dir.mkdir(parents=True, exist_ok=True)

            # Recover sequence number from existing file
            if file_path.exists():
                writer._seq = writer._recover_last_seq()

            # Open file in append mode
            writer._file = open(file_path, "a", encoding="utf-8")

        except (OSError, PermissionError, json.JSONDecodeError) as e:
            raise HistoryError(f"Failed to initialize history writer: {e}") from e

        return writer

    def _recover_last_seq(self) -> int:
        """Recover last sequence number from existing file.

        Returns:
            Last sequence number found, or 0 if file empty/invalid.
        """
        last_seq = 0
        try:
            with open(self.file_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            last_seq = max(last_seq, entry.get("seq", 0))
                        except json.JSONDecodeError:
                            continue  # Skip malformed lines
        except (OSError, IOError):
            pass
        return last_seq

    @property
    def enabled(self) -> bool:
        """Whether history logging is enabled."""
        return self._enabled and not self._closed

    @property
    def seq(self) -> int:
        """Current sequence number."""
        return self._seq

    @property
    def last_op(self) -> str | None:
        """Last operation type logged."""
        return self._last_op

    def needs_buffer_capture(self) -> bool:
        """Check if buffer capture is needed from previous run/write.

        Returns True if the last logged operation was 'run' or 'write',
        which are fire-and-forget operations that don't capture responses.
        """
        return self._last_op in ("run", "write")

    def _next_seq(self) -> int:
        """Get next sequence number."""
        self._seq += 1
        return self._seq

    def _now(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def _write_entry(self, entry: dict) -> bool:
        """Write entry to file.

        Args:
            entry: Entry dict to write.

        Returns:
            True if written successfully, False otherwise.
        """
        if not self._enabled or self._file is None or self._closed:
            return False

        try:
            # Ensure entry is JSON-serializable
            json_str = json.dumps(
                entry, default=str
            )  # default=str handles non-serializable
            self._file.write(json_str + "\n")
            self._file.flush()  # Ensure immediate write
            return True
        except (OSError, IOError, TypeError) as e:
            logger.warning(f"History write failed for {self.node_id}: {e}")
            return False

    def log_run(self, command: str) -> int:
        """Log a run operation.

        Args:
            command: Command that was executed.

        Returns:
            Sequence number of this entry (0 if failed/disabled).
        """
        if not self.enabled:
            return 0

        seq = self._next_seq()
        success = self._write_entry(
            {
                "seq": seq,
                "op": "run",
                "ts": self._now(),
                "input": command,
            }
        )
        if success:
            self._last_op = "run"
        return seq if success else 0

    def log_write(self, data: str) -> int:
        """Log a write operation (raw data).

        Args:
            data: Raw data that was written.

        Returns:
            Sequence number of this entry (0 if failed/disabled).
        """
        if not self.enabled:
            return 0

        seq = self._next_seq()
        success = self._write_entry(
            {
                "seq": seq,
                "op": "write",
                "ts": self._now(),
                "input": data,
            }
        )
        if success:
            self._last_op = "write"
        return seq if success else 0

    def log_read(self, buffer: str, lines: int = 50) -> int:
        """Log a read/buffer capture.

        Args:
            buffer: Buffer contents.
            lines: Number of lines captured.

        Returns:
            Sequence number of this entry (0 if failed/disabled).
        """
        if not self.enabled:
            return 0

        seq = self._next_seq()
        success = self._write_entry(
            {
                "seq": seq,
                "op": "read",
                "ts": self._now(),
                "buffer": buffer,
                "lines": lines,
            }
        )
        if success:
            self._last_op = "read"
        return seq if success else 0

    def log_send(
        self,
        input: str,
        response: dict,
        preceding_buffer_seq: int | None,
        ts_start: str,
        ts_end: str | None = None,
    ) -> int:
        """Log a send operation with response.

        Args:
            input: Input text that was sent.
            response: Parsed response data (sections, tokens, etc.).
            preceding_buffer_seq: Sequence number of read entry captured BEFORE send.
            ts_start: Timestamp when send was initiated.
            ts_end: Timestamp when response was complete.

        Returns:
            Sequence number of this entry (0 if failed/disabled).
        """
        if not self.enabled:
            return 0

        seq = self._next_seq()
        success = self._write_entry(
            {
                "seq": seq,
                "op": "send",
                "ts_start": ts_start,
                "ts_end": ts_end or self._now(),
                "input": input,
                "preceding_buffer_seq": preceding_buffer_seq,
                "response": response,
            }
        )
        if success:
            self._last_op = "send"
        return seq if success else 0

    def log_send_stream(
        self,
        input: str,
        final_buffer: str,
        parser: str,
        preceding_buffer_seq: int | None,
        ts_start: str,
        ts_end: str | None = None,
    ) -> int:
        """Log a send_stream operation with final buffer state.

        Unlike log_send(), this captures the final buffer state rather than
        parsed sections, since streaming doesn't parse incrementally.

        Args:
            input: Input text that was sent.
            final_buffer: Final buffer state after streaming (last N lines).
            parser: Parser type used ("claude", "gemini", "none").
            preceding_buffer_seq: Sequence number of read entry captured BEFORE streaming.
            ts_start: Timestamp when streaming started.
            ts_end: Timestamp when streaming completed.

        Returns:
            Sequence number of this entry (0 if failed/disabled).
        """
        if not self.enabled:
            return 0

        seq = self._next_seq()
        success = self._write_entry(
            {
                "seq": seq,
                "op": "send_stream",
                "ts_start": ts_start,
                "ts_end": ts_end or self._now(),
                "input": input,
                "preceding_buffer_seq": preceding_buffer_seq,
                "final_buffer": final_buffer,
                "parser": parser,
            }
        )
        if success:
            self._last_op = "send_stream"
        return seq if success else 0

    def log_interrupt(self) -> int:
        """Log an interrupt operation (Ctrl+C).

        Interrupts are logged as a dedicated entry type rather than a write
        because they are significant user actions that affect debugging context.

        Returns:
            Sequence number of this entry (0 if failed/disabled).
        """
        if not self.enabled:
            return 0

        seq = self._next_seq()
        success = self._write_entry(
            {
                "seq": seq,
                "op": "interrupt",
                "ts": self._now(),
            }
        )
        if success:
            self._last_op = "interrupt"
        return seq if success else 0

    def log_delete(self, reason: str | None = None) -> int:
        """Log a delete event.

        Args:
            reason: Optional reason for deleting.

        Returns:
            Sequence number of this entry (0 if failed/disabled).
        """
        if not self.enabled:
            return 0

        seq = self._next_seq()
        success = self._write_entry(
            {
                "seq": seq,
                "op": "delete",
                "ts": self._now(),
                "reason": reason,
            }
        )
        if success:
            self._last_op = "delete"
        return seq if success else 0

    def close(self) -> None:
        """Close the history writer and file handle."""
        self._closed = True
        if self._file is not None:
            try:
                self._file.close()
            except (OSError, IOError):
                pass  # Best effort
            self._file = None


@dataclass
class HistoryReader:
    """Reads node history from JSONL file.

    Note: This implementation loads the entire file into memory.
    For v1 this is acceptable as history files are typically small.
    Consider streaming reads for v2 if files grow large.

    Example:
        >>> reader = HistoryReader.create("my-node", server_name="test")
        >>> entries = reader.get_all()
        >>> sends = reader.get_by_op("send")
        >>> last_5 = reader.get_last(5)
    """

    node_id: str
    server_name: str
    file_path: Path

    @classmethod
    def create(
        cls,
        node_id: str,
        server_name: str,
        base_dir: Path | None = None,
    ) -> HistoryReader:
        """Create a history reader.

        Args:
            node_id: Node identifier.
            server_name: Server name.
            base_dir: Base directory for history files.

        Returns:
            HistoryReader instance.

        Raises:
            FileNotFoundError: If history file doesn't exist.
        """
        if base_dir is None:
            base_dir = Path.cwd() / ".nerve" / "history"

        file_path = base_dir / server_name / f"{node_id}.jsonl"

        if not file_path.exists():
            raise FileNotFoundError(
                f"No history for node '{node_id}' on server '{server_name}'"
            )

        return cls(
            node_id=node_id,
            server_name=server_name,
            file_path=file_path,
        )

    def _load_entries(self) -> list[dict]:
        """Load all entries from file.

        Skips malformed lines with a warning.
        """
        entries = []
        with open(self.file_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Malformed JSON at {self.file_path}:{line_num}, skipping"
                        )
        return entries

    def get_all(self) -> list[dict]:
        """Get all history entries."""
        return self._load_entries()

    def get_last(self, n: int) -> list[dict]:
        """Get last N entries."""
        entries = self._load_entries()
        return entries[-n:] if n < len(entries) else entries

    def get_by_op(self, op: str) -> list[dict]:
        """Get entries filtered by operation type.

        Args:
            op: Operation type (send, write, run, read, delete).

        Returns:
            Filtered entries.
        """
        return [e for e in self._load_entries() if e.get("op") == op]

    def get_by_seq(self, seq: int) -> dict | None:
        """Get entry by sequence number.

        Args:
            seq: Sequence number.

        Returns:
            Entry or None if not found.
        """
        for entry in self._load_entries():
            if entry.get("seq") == seq:
                return entry
        return None

    def get_inputs_only(self) -> list[dict]:
        """Get only input operations (send, write, run)."""
        input_ops = {"send", "write", "run"}
        return [e for e in self._load_entries() if e.get("op") in input_ops]
