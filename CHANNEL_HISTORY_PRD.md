# Channel History Feature - Technical PRD

## Document Status
- **Version**: 0.4 (Final)
- **Author**: Development Team
- **Last Updated**: 2025-12-22
- **Status**: Ready for Implementation
- **Revision Notes**: v0.4 adds send_stream/interrupt handling, validation, CLI code, constants

---

## 1. Executive Summary

### 1.1 Problem Statement

Nerve currently provides no persistent record of what happened during a channel session. When debugging issues, understanding AI behavior, or auditing interactions, users have no way to review:
- What inputs were sent to the AI CLI
- What outputs were received
- The sequence and timing of operations
- The state of the terminal buffer at key moments

### 1.2 Proposed Solution

Implement a JSONL-based history system that:
- Records all channel operations (send, send_stream, write, run, interrupt, read, close)
- Persists to disk for post-session analysis
- Provides CLI and API access to history data
- Can be enabled/disabled per channel
- Does not affect existing channel functionality

### 1.3 Key Benefits

1. **Debugging**: Replay exact sequences that led to issues
2. **Auditing**: Complete record of AI interactions
3. **Shareability**: Export history files for collaboration
4. **Transparency**: Human-readable JSONL format

---

## 2. Goals and Non-Goals

### 2.1 Goals

| ID | Goal | Priority |
|----|------|----------|
| G1 | Record all channel operations with timestamps | P0 |
| G2 | Persist history to JSONL files per channel | P0 |
| G3 | Provide CLI commands to view/query history | P0 |
| G4 | Provide API endpoints for history access | P1 |
| G5 | Support enable/disable per channel | P1 |
| G6 | Auto-capture buffer state after write/run | P1 |
| G7 | Zero performance impact on existing workflows | P0 |

### 2.2 Non-Goals

| ID | Non-Goal | Rationale |
|----|----------|-----------|
| NG1 | Capture individual streaming chunks | Adds noise; final response after stream completes IS captured |
| NG2 | History compression/encryption | Over-engineering for v1 |
| NG3 | History search across channels | Can use grep/jq on JSONL files |
| NG4 | Automatic history rotation | Future enhancement if needed |
| NG5 | Real-time history streaming | Not required for debugging use case |
| NG6 | History modification/editing | Audit trail should be immutable |

---

## 3. Technical Architecture

### 3.1 System Overview

```
                                    ┌─────────────────────────────┐
                                    │   .nerve/history/           │
                                    │   └── {server}/             │
                                    │       └── {channel_id}.jsonl│
                                    └─────────────────────────────┘
                                              ▲
                                              │ write
                                              │
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│  Engine  │────▶│ ChannelMgr   │────▶│HistoryWriter │
│          │     │              │     │              │
└──────────┘     └──────────────┘     └──────────────┘
                        │
                        │ creates
                        ▼
                 ┌──────────────┐
                 │   Channel    │
                 │(PTY/WezTerm/ │
                 │ClaudeWezTerm)│
                 └──────────────┘
```

### 3.2 Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| `HistoryWriter` | Write entries to JSONL file, manage sequence numbers, handle errors gracefully |
| `HistoryReader` | Read and filter history entries from JSONL files |
| `ChannelManager` | Create HistoryWriter and pass to channel constructors |
| `PTYChannel` | Call history writer after operations |
| `WezTermChannel` | Call history writer after operations |
| `ClaudeOnWezTermChannel` | **Own history writer (not delegate)**, intercept ops before delegation |
| `NerveEngine` | Pass server_name to ChannelManager for history paths |
| `CLI` | `channel history` subcommand |
| `API` | `/channels/{id}/history` endpoint |

### 3.3 History Ownership for Wrapper Channels

**Decision: ClaudeOnWezTermChannel owns the history writer, NOT the inner WezTermChannel.**

Rationale:
- `ClaudeOnWezTermChannel` is the logical unit the user interacts with
- It has its own `_last_input` tracking
- It applies default parser logic in `send()`
- The inner channel is an implementation detail

```
ClaudeOnWezTermChannel (owns history_writer)
    │
    │ intercepts send/write/run/close
    │ logs to history_writer
    │
    └──▶ _inner: WezTermChannel (no history_writer)
              │
              └──▶ backend operations
```

### 3.4 Data Flow

```
User calls channel.send("Hello")
         │
         ▼
  ┌──────────────────────────────────────┐
  │ PTYChannel.send()                    │
  │   1. Capture pre-state buffer        │
  │   2. Log 'read' for pre-state        │
  │   3. Record ts_start                 │
  │   4. Write to backend                │
  │   5. Wait for response               │
  │   6. Log 'send' with response        │
  │   7. Return parsed response          │
  │   (NO post-send auto-read for send)  │
  └──────────────────────────────────────┘
```

**Auto-Read Rules (Revised)**:

| Operation | Auto-read BEFORE? | Auto-read AFTER? | Rationale |
|-----------|-------------------|------------------|-----------|
| `send()` | Yes (for `preceding_buffer_seq`) | **No** | Response captures output |
| `send_stream()` | Yes (for `preceding_buffer_seq`) | **No** | Final response logged after stream completes |
| `write()` | No | Yes | Capture effect of write |
| `run()` | No | Yes | Capture command output |
| `interrupt()` | No | Yes | Capture terminal state after Ctrl+C |
| `close()` | Yes (final state) | N/A | Capture before teardown |

---

## 4. Data Models

### 4.1 History Entry Types

#### Base Fields (Not Inherited)
All entries share these fields but define them directly (no inheritance):
```python
seq: int      # Sequence number (monotonic, unique within file)
op: str       # Operation type
```

#### Send Entry
```python
@dataclass
class SendEntry:
    """Entry for channel.send() operations."""
    seq: int
    op: str = "send"
    ts_start: str              # When send was initiated (ISO 8601)
    ts_end: str                # When response was complete (ISO 8601)
    input: str                 # User input text
    preceding_buffer_seq: int  # Reference to read entry captured BEFORE send
    response: ResponseData     # Parsed response data

@dataclass
class ResponseData:
    """Structured response information."""
    sections: list[dict]       # Parsed sections
    tokens: dict | None        # Token counts if available
    is_complete: bool
    is_ready: bool
```

**Note**: `SendEntry` uses `ts_start`/`ts_end` instead of a single `ts` because send operations have duration.

#### Send Stream Entry
```python
@dataclass
class SendStreamEntry:
    """Entry for channel.send_stream() operations.

    Logs the final response after streaming completes, NOT individual chunks.
    Individual chunks are excluded per NG1 (too noisy for debugging).
    """
    seq: int
    op: str = "send_stream"
    ts_start: str              # When streaming started (ISO 8601)
    ts_end: str                # When streaming completed (ISO 8601)
    input: str                 # User input text
    preceding_buffer_seq: int  # Reference to read entry captured BEFORE streaming
    final_buffer: str          # Final buffer state after streaming (last N lines)
    parser: str                # Parser type used ("claude", "gemini", "none")
```

**Note**: Unlike `send()`, `send_stream()` doesn't parse the response into sections. We capture the final buffer state instead.

#### Interrupt Entry
```python
@dataclass
class InterruptEntry:
    """Entry for channel.interrupt() operations (Ctrl+C).

    Dedicated entry type (not just a write) because interrupts are significant
    user actions that affect debugging context.
    """
    seq: int
    op: str = "interrupt"
    ts: str                    # ISO 8601 timestamp
```

**Note**: The actual `\x03` byte is not stored since it's always the same. The buffer auto-read after captures the terminal state.

#### Write Entry
```python
@dataclass
class WriteEntry:
    """Entry for channel.write() operations (raw data)."""
    seq: int
    op: str = "write"
    ts: str                    # ISO 8601 timestamp
    input: str                 # Raw data written
```

#### Run Entry
```python
@dataclass
class RunEntry:
    """Entry for channel.run() operations (fire and forget)."""
    seq: int
    op: str = "run"
    ts: str                    # ISO 8601 timestamp
    input: str                 # Command executed
```

#### Read Entry
```python
@dataclass
class ReadEntry:
    """Entry for buffer captures."""
    seq: int
    op: str = "read"
    ts: str                    # ISO 8601 timestamp
    buffer: str                # Buffer contents (last N lines)
    lines: int                 # Number of lines captured
```

#### Close Entry
```python
@dataclass
class CloseEntry:
    """Entry for channel close events."""
    seq: int
    op: str = "close"
    ts: str                    # ISO 8601 timestamp
    reason: str | None = None  # Optional close reason
```

### 4.2 JSONL File Format

Each line is a self-contained JSON object:

```json
{"seq": 1, "op": "run", "ts": "2025-12-22T10:30:00.000Z", "input": "claude"}
{"seq": 2, "op": "read", "ts": "2025-12-22T10:30:01.500Z", "buffer": "Claude started...", "lines": 50}
{"seq": 3, "op": "send", "ts_start": "2025-12-22T10:30:05.000Z", "ts_end": "2025-12-22T10:30:10.000Z", "input": "Hello!", "preceding_buffer_seq": 2, "response": {"sections": [{"type": "text", "content": "Hi!"}], "tokens": {"input": 10, "output": 5}, "is_complete": true, "is_ready": true}}
{"seq": 4, "op": "read", "ts": "2025-12-22T10:30:10.100Z", "buffer": "...", "lines": 50}
{"seq": 5, "op": "send_stream", "ts_start": "2025-12-22T10:30:15.000Z", "ts_end": "2025-12-22T10:30:25.000Z", "input": "Write code", "preceding_buffer_seq": 4, "final_buffer": "def hello()...", "parser": "claude"}
{"seq": 6, "op": "read", "ts": "2025-12-22T10:30:25.100Z", "buffer": "...", "lines": 50}
{"seq": 7, "op": "interrupt", "ts": "2025-12-22T10:30:30.000Z"}
{"seq": 8, "op": "read", "ts": "2025-12-22T10:30:30.200Z", "buffer": "^C...", "lines": 50}
{"seq": 9, "op": "close", "ts": "2025-12-22T10:35:00.000Z", "reason": null}
```

### 4.3 Storage Location

```
.nerve/
├── history/
│   └── {server_name}/
│       ├── {channel_id_1}.jsonl
│       ├── {channel_id_2}.jsonl
│       └── ...
└── sessions.json  (existing)
```

---

## 5. Implementation Design

### 5.1 Constants and Configuration

```python
# src/nerve/core/channels/history.py

# Buffer capture configuration
HISTORY_BUFFER_LINES = 50
"""Number of lines to capture for buffer state.

Rationale:
- 50 lines typically captures 1-2 Claude Code responses with context
- Matches read_tail() default in existing channel implementations
- Balances debugging utility vs file size (avg ~5KB per buffer capture)
- Configurable per-channel would add complexity without clear benefit for v1

Tradeoff: Very long single-line outputs may be truncated. For v1, this is
acceptable as the full buffer is still available in the terminal.
"""
```

### 5.2 Name Validation

History file paths are constructed from `channel_id` and `server_name`. To prevent path traversal attacks and ensure valid filenames, these MUST be validated using the existing validation module.

**Security Requirement**: Use `nerve.core.validation.validate_name()` before constructing paths.

```python
from nerve.core.validation import validate_name

# In HistoryWriter.create():
validate_name(channel_id, "channel")    # Raises ValueError if invalid
validate_name(server_name, "server")    # Raises ValueError if invalid

# Rules enforced (from validation.py):
# - 1-32 characters
# - Lowercase alphanumeric and dashes only
# - Cannot start or end with dash
# - Pattern: ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$
```

**Why existing validation is sufficient:**
- `my/channel` → REJECTED (contains `/`)
- `../escape` → REJECTED (contains `.` and `/`)
- `test-channel` → ALLOWED
- `claude-1` → ALLOWED

### 5.3 HistoryWriter Class

Location: `src/nerve/core/channels/history.py`

**Key design decisions:**
- Synchronous writes (no async I/O) - atomic within async context
- Fail-soft error handling - never breaks channel operations
- Sequence number recovery on file append (server restart safe)
- Name validation prevents path traversal

```python
"""Channel history persistence."""

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


class HistoryError(Exception):
    """Error during history operations."""
    pass


@dataclass
class HistoryWriter:
    """Writes channel history to JSONL file.

    Append-only writer for channel operations. All write operations are
    synchronous and atomic within the async context (no yielding during
    writes), so no explicit locking is required.

    Error Handling Policy: FAIL-SOFT
    - Errors are logged as warnings
    - Operations continue without history
    - Never raises exceptions to caller (except in create())

    Example:
        >>> writer = HistoryWriter.create("my-channel", server_name="test")
        >>> writer.log_run("claude")
        >>> writer.log_read("Claude started...")
        >>> writer.log_send("Hello", response_data, preceding_buffer_seq=2)
        >>> writer.close()
    """

    channel_id: str
    server_name: str
    file_path: Path
    _seq: int = field(default=0, repr=False)
    _file: Any = field(default=None, repr=False)
    _enabled: bool = field(default=True, repr=False)
    _closed: bool = field(default=False, repr=False)

    @classmethod
    def create(
        cls,
        channel_id: str,
        server_name: str,
        base_dir: Path | None = None,
        enabled: bool = True,
    ) -> HistoryWriter:
        """Create a new history writer.

        If appending to existing file, recovers sequence number from last entry.

        Args:
            channel_id: Unique channel identifier.
            server_name: Server this channel belongs to.
            base_dir: Base directory for history files (default: .nerve/history).
            enabled: Whether history logging is enabled.

        Returns:
            HistoryWriter instance.

        Raises:
            HistoryError: If directory creation or file access fails.
            ValueError: If channel_id or server_name is invalid.
        """
        # Validate names to prevent path traversal (raises ValueError)
        validate_name(channel_id, "channel")
        validate_name(server_name, "server")

        if base_dir is None:
            base_dir = Path.cwd() / ".nerve" / "history"

        server_dir = base_dir / server_name
        file_path = server_dir / f"{channel_id}.jsonl"

        # Create instance first (before any file ops)
        writer = cls(
            channel_id=channel_id,
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
            with open(self.file_path, "r", encoding="utf-8") as f:
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
            json_str = json.dumps(entry, default=str)  # default=str handles non-serializable
            self._file.write(json_str + "\n")
            self._file.flush()  # Ensure immediate write
            return True
        except (OSError, IOError, TypeError) as e:
            logger.warning(f"History write failed for {self.channel_id}: {e}")
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
        success = self._write_entry({
            "seq": seq,
            "op": "run",
            "ts": self._now(),
            "input": command,
        })
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
        success = self._write_entry({
            "seq": seq,
            "op": "write",
            "ts": self._now(),
            "input": data,
        })
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
        success = self._write_entry({
            "seq": seq,
            "op": "read",
            "ts": self._now(),
            "buffer": buffer,
            "lines": lines,
        })
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
        success = self._write_entry({
            "seq": seq,
            "op": "send",
            "ts_start": ts_start,
            "ts_end": ts_end or self._now(),
            "input": input,
            "preceding_buffer_seq": preceding_buffer_seq,
            "response": response,
        })
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
        success = self._write_entry({
            "seq": seq,
            "op": "send_stream",
            "ts_start": ts_start,
            "ts_end": ts_end or self._now(),
            "input": input,
            "preceding_buffer_seq": preceding_buffer_seq,
            "final_buffer": final_buffer,
            "parser": parser,
        })
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
        success = self._write_entry({
            "seq": seq,
            "op": "interrupt",
            "ts": self._now(),
        })
        return seq if success else 0

    def log_close(self, reason: str | None = None) -> int:
        """Log a close event.

        Args:
            reason: Optional reason for closing.

        Returns:
            Sequence number of this entry (0 if failed/disabled).
        """
        if not self.enabled:
            return 0

        seq = self._next_seq()
        success = self._write_entry({
            "seq": seq,
            "op": "close",
            "ts": self._now(),
            "reason": reason,
        })
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
    """Reads channel history from JSONL file.

    Note: This implementation loads the entire file into memory.
    For v1 this is acceptable as history files are typically small.
    Consider streaming reads for v2 if files grow large.

    Example:
        >>> reader = HistoryReader.create("my-channel", server_name="test")
        >>> entries = reader.get_all()
        >>> sends = reader.get_by_op("send")
        >>> last_5 = reader.get_last(5)
    """

    channel_id: str
    server_name: str
    file_path: Path

    @classmethod
    def create(
        cls,
        channel_id: str,
        server_name: str,
        base_dir: Path | None = None,
    ) -> HistoryReader:
        """Create a history reader.

        Args:
            channel_id: Channel identifier.
            server_name: Server name.
            base_dir: Base directory for history files.

        Returns:
            HistoryReader instance.

        Raises:
            FileNotFoundError: If history file doesn't exist.
        """
        if base_dir is None:
            base_dir = Path.cwd() / ".nerve" / "history"

        file_path = base_dir / server_name / f"{channel_id}.jsonl"

        if not file_path.exists():
            raise FileNotFoundError(
                f"No history for channel '{channel_id}' on server '{server_name}'"
            )

        return cls(
            channel_id=channel_id,
            server_name=server_name,
            file_path=file_path,
        )

    def _load_entries(self) -> list[dict]:
        """Load all entries from file.

        Skips malformed lines with a warning.
        """
        entries = []
        with open(self.file_path, "r", encoding="utf-8") as f:
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
            op: Operation type (send, write, run, read, close).

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
```

### 5.4 ChannelManager Integration

Location: `src/nerve/core/session/manager.py`

The `ChannelManager` is the integration point where history writers are created and passed to channels.

```python
@dataclass
class ChannelManager:
    """Manage individual channels."""

    _channels: dict[str, Channel] = field(default_factory=dict)
    _server_name: str = field(default="default")  # NEW: For history paths
    _history_base_dir: Path | None = field(default=None)  # NEW: Override for testing

    async def create_terminal(
        self,
        channel_id: str,
        command: list[str] | str | None = None,
        backend: str = "pty",
        cwd: str | None = None,
        pane_id: str | None = None,
        history: bool = True,  # NEW: Enable/disable history
        **kwargs,
    ) -> PTYChannel | WezTermChannel | ClaudeOnWezTermChannel:
        """Create a new terminal channel.

        Args:
            channel_id: Unique channel identifier (required).
            command: Command to run.
            backend: Backend type ("pty", "wezterm", or "claude-wezterm").
            cwd: Working directory.
            pane_id: For WezTerm, attach to existing pane.
            history: Enable history logging (default: True).
            **kwargs: Additional args passed to channel create.

        Returns:
            The created channel.

        Raises:
            ValueError: If channel_id already exists.
        """
        if self._channels.get(channel_id):
            raise ValueError(f"Channel '{channel_id}' already exists")

        # Create history writer if enabled
        history_writer = None
        if history:
            try:
                from nerve.core.channels.history import HistoryWriter
                history_writer = HistoryWriter.create(
                    channel_id=channel_id,
                    server_name=self._server_name,
                    base_dir=self._history_base_dir,
                    enabled=True,
                )
            except Exception as e:
                # Log warning but continue without history
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to create history writer for {channel_id}: {e}"
                )
                history_writer = None

        channel: PTYChannel | WezTermChannel | ClaudeOnWezTermChannel

        try:
            if backend == "claude-wezterm":
                if not command:
                    raise ValueError("command is required for claude-wezterm backend")
                channel = await ClaudeOnWezTermChannel.create(
                    channel_id=channel_id,
                    command=command if isinstance(command, str) else " ".join(command),
                    cwd=cwd,
                    history_writer=history_writer,  # Pass to wrapper, NOT inner
                    **kwargs,
                )
            elif backend == "wezterm" or pane_id is not None:
                if pane_id:
                    channel = await WezTermChannel.attach(
                        channel_id=channel_id,
                        pane_id=pane_id,
                        history_writer=history_writer,
                        **kwargs,
                    )
                else:
                    channel = await WezTermChannel.create(
                        channel_id=channel_id,
                        command=command,
                        cwd=cwd,
                        history_writer=history_writer,
                        **kwargs,
                    )
            else:
                channel = await PTYChannel.create(
                    channel_id=channel_id,
                    command=command,
                    cwd=cwd,
                    history_writer=history_writer,
                    **kwargs,
                )

            self._channels[channel.id] = channel
            return channel

        except Exception:
            # Clean up history writer on channel creation failure
            if history_writer is not None:
                history_writer.close()
            raise
```

### 5.5 PTYChannel Integration

Location: `src/nerve/core/channels/pty.py`

Key changes (additions only):

```python
from nerve.core.channels.history import (
    HistoryWriter,
    HISTORY_BUFFER_LINES,
)  # At top with TYPE_CHECKING

@dataclass
class PTYChannel:
    # ... existing fields ...

    # New field for history
    _history_writer: HistoryWriter | None = field(default=None, repr=False)

    @classmethod
    async def create(
        cls,
        channel_id: str,
        command: list[str] | str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        history_writer: HistoryWriter | None = None,  # NEW
    ) -> PTYChannel:
        """Create a new PTY channel."""
        # ... existing validation and setup ...

        channel = cls(
            id=channel_id,
            backend=backend,
            command=command_str,
            state=ChannelState.OPEN,
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
            _history_writer=history_writer,  # NEW
        )

        # ... existing reader start and sleep ...

        return channel

    async def send(
        self,
        input: str,
        parser: ParserType | None = None,
        timeout: float | None = None,
        submit: str | None = None,
    ) -> ParsedResponse:
        """Send input and wait for a parsed response."""
        if self.state == ChannelState.CLOSED:
            raise RuntimeError("Channel is closed")

        # Track last input (existing)
        self._last_input = input

        # History: capture pre-state and timestamps
        preceding_buffer_seq = None
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()
            # Log current buffer state BEFORE send
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            preceding_buffer_seq = self._history_writer.log_read(
                buffer_content, lines=HISTORY_BUFFER_LINES
            )

        # ... existing send logic (unchanged) ...

        actual_parser = parser if parser is not None else ParserType.NONE
        is_claude = actual_parser == ParserType.CLAUDE and submit is None
        # ... input handling ...

        # Wait for response
        await self._wait_for_ready(...)

        # Parse response
        new_output = self.backend.buffer[buffer_start:]
        result = parser_instance.parse(new_output)

        # History: log send with response (NO auto-read after send)
        if self._history_writer and self._history_writer.enabled:
            response_data = {
                "sections": [
                    {"type": s.type, "content": s.content, "metadata": s.metadata}
                    for s in result.sections
                ],
                "tokens": result.tokens,
                "is_complete": result.is_complete,
                "is_ready": result.is_ready,
            }
            self._history_writer.log_send(
                input=input,
                response=response_data,
                preceding_buffer_seq=preceding_buffer_seq,
                ts_start=ts_start,
            )

        return result

    async def write(self, data: str) -> None:
        """Write raw data to the terminal (low-level)."""
        await self.backend.write(data)

        # History: log write then auto-read
        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_write(data)
            # Brief delay for data to settle (documented tradeoff)
            await asyncio.sleep(0.1)
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def run(self, command: str) -> None:
        """Start a program in the terminal (fire and forget)."""
        await self.backend.write(command + "\n")

        # History: log run then auto-read
        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_run(command)
            # Brief delay for command to start (documented tradeoff)
            await asyncio.sleep(0.5)
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def send_stream(
        self,
        input: str,
        parser: ParserType = ParserType.NONE,
    ) -> AsyncIterator[str]:
        """Send input and stream output chunks.

        History logs the final buffer state after streaming completes,
        NOT individual chunks (per NG1).
        """
        if self.state == ChannelState.CLOSED:
            raise RuntimeError("Channel is closed")

        # History: capture pre-state
        preceding_buffer_seq = None
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            preceding_buffer_seq = self._history_writer.log_read(
                buffer_content, lines=HISTORY_BUFFER_LINES
            )

        parser_instance = get_parser(parser)
        await self.backend.write(input + "\n")
        self.state = ChannelState.BUSY

        async for chunk in self.backend.read_stream():
            yield chunk

            if parser_instance.is_ready(self.backend.buffer):
                self.state = ChannelState.OPEN
                break

        # History: log final state after streaming completes
        if self._history_writer and self._history_writer.enabled:
            final_buffer = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_send_stream(
                input=input,
                final_buffer=final_buffer,
                parser=parser.value,
                preceding_buffer_seq=preceding_buffer_seq,
                ts_start=ts_start,
            )

    async def interrupt(self) -> None:
        """Send interrupt signal (Ctrl+C)."""
        await self.backend.write("\x03")

        # History: log interrupt then auto-read
        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_interrupt()
            await asyncio.sleep(0.1)
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def close(self) -> None:
        """Close the channel and stop the backend."""
        # History: capture final state before close
        if self._history_writer and self._history_writer.enabled:
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)
            self._history_writer.log_close()
            self._history_writer.close()

        # ... existing close logic ...
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        await self.backend.stop()
        self.state = ChannelState.CLOSED
```

### 5.6 WezTermChannel Integration

Location: `src/nerve/core/channels/wezterm.py`

Similar changes as PTYChannel. Key differences:
- Buffer is always fresh (no `buffer_start` tracking)
- `attach()` also accepts `history_writer` parameter

```python
from nerve.core.channels.history import (
    HistoryWriter,
    HISTORY_BUFFER_LINES,
)  # At top with TYPE_CHECKING

@dataclass
class WezTermChannel:
    # ... existing fields ...

    # New field for history
    _history_writer: HistoryWriter | None = field(default=None, repr=False)

    @classmethod
    async def create(
        cls,
        channel_id: str,
        command: list[str] | str | None = None,
        cwd: str | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        history_writer: HistoryWriter | None = None,  # NEW
    ) -> WezTermChannel:
        """Create a new WezTerm channel by spawning a pane."""
        # ... existing validation and setup ...

        channel = cls(
            id=channel_id,
            backend=backend,
            pane_id=backend.pane_id,
            command=command_str,
            state=ChannelState.OPEN,
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
            _history_writer=history_writer,  # NEW
        )

        await asyncio.sleep(0.5)
        return channel

    @classmethod
    async def attach(
        cls,
        channel_id: str,
        pane_id: str,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        history_writer: HistoryWriter | None = None,  # NEW
    ) -> WezTermChannel:
        """Attach to an existing WezTerm pane."""
        if not channel_id:
            raise ValueError("channel_id is required")

        config = BackendConfig()
        backend = WezTermBackend([], config, pane_id=pane_id)
        await backend.attach(pane_id)

        return cls(
            id=channel_id,
            backend=backend,
            pane_id=pane_id,
            state=ChannelState.OPEN,
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
            _history_writer=history_writer,  # NEW
        )

    async def send(
        self,
        input: str,
        parser: ParserType | None = None,
        timeout: float | None = None,
        submit: str | None = None,
    ) -> ParsedResponse:
        """Send input and wait for a parsed response."""
        if self.state == ChannelState.CLOSED:
            raise RuntimeError("Channel is closed")

        self._last_input = input

        # History: capture pre-state
        # WezTerm buffer is always fresh - no buffer_start tracking needed
        preceding_buffer_seq = None
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            preceding_buffer_seq = self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

        # ... existing send logic ...

        actual_parser = parser if parser is not None else ParserType.NONE
        is_claude = actual_parser == ParserType.CLAUDE and submit is None
        # ... rest of existing logic ...

        # Wait for response
        await self._wait_for_ready(timeout=timeout, parser_type=actual_parser)
        await asyncio.sleep(0.5)

        buffer = self.backend.buffer
        result = parser_instance.parse(buffer)

        # History: log send (NO auto-read after send)
        if self._history_writer and self._history_writer.enabled:
            response_data = {
                "sections": [
                    {"type": s.type, "content": s.content, "metadata": s.metadata}
                    for s in result.sections
                ],
                "tokens": result.tokens,
                "is_complete": result.is_complete,
                "is_ready": result.is_ready,
            }
            self._history_writer.log_send(
                input=input,
                response=response_data,
                preceding_buffer_seq=preceding_buffer_seq,
                ts_start=ts_start,
            )

        return result

    async def write(self, data: str) -> None:
        """Write raw data to the terminal."""
        await self.backend.write(data)

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_write(data)
            await asyncio.sleep(0.1)
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def run(self, command: str) -> None:
        """Start a program in the terminal."""
        await self.backend.write(command)
        await asyncio.sleep(0.1)
        await self.backend.write("\r")

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_run(command)
            await asyncio.sleep(0.5)
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def close(self) -> None:
        """Close the channel and stop the backend."""
        if self._history_writer and self._history_writer.enabled:
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)
            self._history_writer.log_close()
            self._history_writer.close()

        await self.backend.stop()
        self.state = ChannelState.CLOSED
```

### 5.7 ClaudeOnWezTermChannel Integration

Location: `src/nerve/core/channels/claude_wezterm.py`

**Key Design Decision**: The wrapper owns the history writer and intercepts all operations BEFORE delegating to the inner channel. The inner `WezTermChannel` has NO history writer.

```python
from nerve.core.channels.history import (
    HistoryWriter,
    HISTORY_BUFFER_LINES,
)  # At top with TYPE_CHECKING

@dataclass
class ClaudeOnWezTermChannel:
    """WezTerm channel optimized for Claude CLI.

    HISTORY OWNERSHIP: This wrapper owns the history writer, NOT the inner
    WezTermChannel. All history logging happens at this level.
    """

    id: str
    _inner: WezTermChannel
    _command: str = ""
    _default_parser: ParserType = ParserType.CLAUDE
    _last_input: str = ""
    channel_type: ChannelType = field(default=ChannelType.TERMINAL, init=False)
    _history_writer: HistoryWriter | None = field(default=None, repr=False)  # NEW

    @classmethod
    async def create(
        cls,
        channel_id: str,
        command: str,
        cwd: str | None = None,
        parser: ParserType = ParserType.CLAUDE,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        history_writer: HistoryWriter | None = None,  # NEW
    ) -> ClaudeOnWezTermChannel:
        """Create a new ClaudeOnWezTerm channel."""
        if not channel_id:
            raise ValueError("channel_id is required")

        if "claude" not in command.lower():
            raise ValueError(f"Command must contain 'claude'. Got: {command}")

        # Create inner channel WITHOUT history writer
        inner = await WezTermChannel.create(
            channel_id=channel_id,
            command=None,
            cwd=cwd,
            ready_timeout=ready_timeout,
            response_timeout=response_timeout,
            history_writer=None,  # Inner has NO history
        )

        await asyncio.sleep(0.5)

        # Run the claude command (this will be logged by wrapper)
        # Don't call inner.run() directly - we'll log it ourselves
        await inner.backend.write(command)
        await asyncio.sleep(0.1)
        await inner.backend.write("\r")

        wrapper = cls(
            id=channel_id,
            _inner=inner,
            _command=command,
            _default_parser=parser,
            _history_writer=history_writer,  # Wrapper owns history
        )

        # History: log the initial run command
        if history_writer and history_writer.enabled:
            history_writer.log_run(command)
            await asyncio.sleep(2)  # Wait for Claude to start
            buffer_content = inner.read_tail(HISTORY_BUFFER_LINES)
            history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)
        else:
            await asyncio.sleep(2)

        return wrapper

    async def send(
        self,
        input: str,
        parser: ParserType | None = None,
        timeout: float | None = None,
        submit: str | None = None,
    ) -> ParsedResponse:
        """Send input and wait for parsed response."""
        self._last_input = input

        # History: capture pre-state
        preceding_buffer_seq = None
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()
            buffer_content = self._inner.read_tail(HISTORY_BUFFER_LINES)
            preceding_buffer_seq = self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

        # Delegate to inner (which has no history writer)
        actual_parser = parser if parser is not None else self._default_parser
        result = await self._inner.send(
            input=input,
            parser=actual_parser,
            timeout=timeout,
            submit=submit,
        )

        # History: log send
        if self._history_writer and self._history_writer.enabled:
            response_data = {
                "sections": [
                    {"type": s.type, "content": s.content, "metadata": s.metadata}
                    for s in result.sections
                ],
                "tokens": result.tokens,
                "is_complete": result.is_complete,
                "is_ready": result.is_ready,
            }
            self._history_writer.log_send(
                input=input,
                response=response_data,
                preceding_buffer_seq=preceding_buffer_seq,
                ts_start=ts_start,
            )

        return result

    async def run(self, command: str) -> None:
        """Run a command (fire and forget)."""
        await self._inner.run(command)

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_run(command)
            await asyncio.sleep(0.5)
            buffer_content = self._inner.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def write(self, data: str) -> None:
        """Write raw data."""
        await self._inner.write(data)

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_write(data)
            await asyncio.sleep(0.1)
            buffer_content = self._inner.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def close(self) -> None:
        """Close the channel."""
        if self._history_writer and self._history_writer.enabled:
            buffer_content = self._inner.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)
            self._history_writer.log_close()
            self._history_writer.close()

        await self._inner.close()

    # ... existing pass-through properties unchanged ...
```

### 5.8 NerveEngine Integration

Location: `src/nerve/server/engine.py`

The engine needs to know the server name to pass to ChannelManager, and must pass the `history` parameter from API requests through to channel creation.

**Full Parameter Flow:**

```
API Request                  NerveEngine                   ChannelManager                Channel
    │                             │                              │                          │
    │ {"channel_id": "x",         │                              │                          │
    │  "history": false}          │                              │                          │
    │ ──────────────────────────▶ │                              │                          │
    │                             │ _create_channel(params)      │                          │
    │                             │ ────────────────────────────▶│                          │
    │                             │                              │ create_terminal(         │
    │                             │                              │   channel_id="x",        │
    │                             │                              │   history=False          │
    │                             │                              │ ) ─────────────────────▶ │
    │                             │                              │                          │
```

```python
@dataclass
class NerveEngine:
    """Main nerve engine - wraps core with event emission."""

    event_sink: EventSink
    _server_name: str = field(default="default")  # Extracted from socket path
    _channel_manager: ChannelManager = field(init=False)  # Delayed init
    _running_dags: dict[str, asyncio.Task] = field(default_factory=dict)
    _shutdown_requested: bool = field(default=False, repr=False)

    def __post_init__(self):
        """Initialize channel manager with server name."""
        self._channel_manager = ChannelManager(_server_name=self._server_name)

    async def _create_channel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new channel.

        Passes history parameter from API to ChannelManager.
        """
        channel_id = params.get("channel_id")
        if not channel_id:
            raise ValueError("Channel name is required")

        command = params.get("command")
        cwd = params.get("cwd")
        backend = params.get("backend", "pty")
        pane_id = params.get("pane_id")

        # Extract history parameter from API request (default: True)
        history_enabled = params.get("history", True)

        channel = await self._channel_manager.create_terminal(
            channel_id=channel_id,
            command=command,
            backend=backend,
            cwd=cwd,
            pane_id=pane_id,
            history=history_enabled,  # Pass through to ChannelManager
        )

        await self._emit(Event(
            type=EventType.CHANNEL_CREATED,
            channel_id=channel.id,
        ))

        return {"channel_id": channel.id, "status": "created"}

    # ... existing methods unchanged ...
```

**CLI Update** (`main.py`):

```python
# In server start command, extract server name from argument
@click.option("--name", "-n", default="default", help="Server name")
def start(name: str, ...):
    socket_path = f"/tmp/nerve-{name}.sock"
    # ...
    engine = NerveEngine(event_sink=transport, _server_name=name)
```

---

## 6. Error Handling Policy

### 6.1 Philosophy: Fail-Soft

History is a debugging aid, not a critical path. Errors should NEVER break channel operations.

### 6.2 Error Handling by Component

| Component | Error Type | Handling |
|-----------|-----------|----------|
| `HistoryWriter.create()` | Dir/file creation failure | **Raises `HistoryError`** (caller can catch and continue without history) |
| `HistoryWriter.log_*()` | Write failure | Log warning, return 0, continue |
| `HistoryWriter.log_*()` | JSON serialization failure | Use `default=str`, log warning, continue |
| `HistoryWriter.close()` | File close failure | Ignore (best effort) |
| `HistoryReader.create()` | File not found | **Raises `FileNotFoundError`** |
| `HistoryReader._load_entries()` | Malformed JSON line | Log warning, skip line, continue |
| `ChannelManager` | History writer creation fails | Log warning, create channel without history |

### 6.3 Example Error Flow

```python
# In ChannelManager.create_terminal()
history_writer = None
if history:
    try:
        history_writer = HistoryWriter.create(...)
    except HistoryError as e:
        logger.warning(f"History disabled for {channel_id}: {e}")
        history_writer = None  # Continue without history

# Channel creation proceeds regardless
channel = await PTYChannel.create(..., history_writer=history_writer)
```

---

## 7. Performance Considerations

### 7.1 Added Latency

The following intentional delays are added:

| Location | Delay | Purpose |
|----------|-------|---------|
| `write()` after logging | 0.1s | Allow terminal to process data before capture |
| `run()` after logging | 0.5s | Allow command to start before capture |

**Tradeoff**: These delays ensure accurate buffer captures. Without them, the auto-read might capture pre-operation state. The delays are short enough to be imperceptible in interactive use.

**Alternative considered**: Callback-based capture (rejected for complexity).

### 7.2 File I/O

- **Synchronous writes**: `_file.write()` is blocking but typically <1ms
- **Immediate flush**: Ensures durability at cost of extra syscall
- **Acceptable for v1**: History writes are infrequent relative to overall operation time

**Future improvement**: Consider `aiofiles` or write queue for high-throughput scenarios.

### 7.3 Memory Usage

- `HistoryReader` loads entire file into memory
- Acceptable for typical file sizes (<10MB)
- Consider streaming reads if files grow large

---

## 8. CLI Design

### 8.1 New Commands

```bash
# View full history
nerve server channel history <channel_name> --server <server>

# Last N entries
nerve server channel history <channel_name> --server <server> --last 10

# Filter by operation type
nerve server channel history <channel_name> --server <server> --op send

# Get specific entry by sequence number
nerve server channel history <channel_name> --server <server> --seq 3

# Inputs only (send, write, run)
nerve server channel history <channel_name> --server <server> --inputs-only

# JSON output
nerve server channel history <channel_name> --server <server> --json

# Summary mode
nerve server channel history <channel_name> --server <server> --summary
```

### 8.2 Channel Create Flag

```bash
nerve server channel create my-claude --server test --history        # enabled (default)
nerve server channel create my-claude --server test --no-history     # disabled
```

### 8.3 API Response for --no-history Channels

When requesting history for a channel created with `--no-history`:

```json
{
  "channel_id": "my-claude",
  "server_name": "test",
  "entries": [],
  "total": 0,
  "note": "History was disabled for this channel"
}
```

The API returns an empty array (not 404) because the channel exists, just without history.

### 8.4 CLI Implementation

Location: `src/nerve/frontends/cli/main.py`

```python
@channel.command("history")
@click.argument("channel_name")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
@click.option("--last", "-n", "last_n", type=int, default=None, help="Show last N entries")
@click.option(
    "--op",
    "operation",
    type=click.Choice(["send", "send_stream", "write", "run", "interrupt", "read", "close"]),
    help="Filter by operation",
)
@click.option("--seq", type=int, default=None, help="Get entry by sequence number")
@click.option("--inputs-only", is_flag=True, help="Show only input operations")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
@click.option("--summary", is_flag=True, help="Show summary statistics")
def channel_history(
    channel_name: str,
    server_name: str,
    last_n: int | None,
    operation: str | None,
    seq: int | None,
    inputs_only: bool,
    json_output: bool,
    summary: bool,
):
    """View channel operation history.

    Shows the history of all operations performed on a channel,
    including inputs sent, responses received, and buffer captures.

    Examples:

        nerve server channel history my-claude --server myproject

        nerve server channel history my-claude --server myproject --last 10

        nerve server channel history my-claude --server myproject --op send

        nerve server channel history my-claude --server myproject --json
    """
    import json as json_module
    import sys

    from nerve.core.channels.history import HistoryReader

    try:
        reader = HistoryReader.create(channel_name, server_name)
    except FileNotFoundError:
        click.echo(
            f"No history found for channel '{channel_name}' on server '{server_name}'",
            err=True,
        )
        sys.exit(1)

    # Get entries based on filters
    if seq is not None:
        entry = reader.get_by_seq(seq)
        if entry is None:
            click.echo(f"No entry with sequence number {seq}", err=True)
            sys.exit(1)
        entries = [entry]
    elif inputs_only:
        entries = reader.get_inputs_only()
    elif operation:
        entries = reader.get_by_op(operation)
    elif last_n:
        entries = reader.get_last(last_n)
    else:
        entries = reader.get_all()

    if summary:
        # Show summary statistics
        ops_count: dict[str, int] = {}
        for e in entries:
            op = e.get("op", "unknown")
            ops_count[op] = ops_count.get(op, 0) + 1

        click.echo(f"Channel: {channel_name}")
        click.echo(f"Server: {server_name}")
        click.echo(f"Total entries: {len(entries)}")
        click.echo("\nOperations:")
        for op, count in sorted(ops_count.items()):
            click.echo(f"  {op}: {count}")
        return

    if json_output:
        click.echo(json_module.dumps(entries, indent=2))
    else:
        # Human-readable output
        for entry in entries:
            seq_num = entry.get("seq", "?")
            op = entry.get("op", "?")
            ts = entry.get("ts") or entry.get("ts_start", "?")

            # Format based on operation type
            if op == "send":
                input_text = entry.get("input", "")[:50]
                click.echo(f"[{seq_num}] {op.upper()} @ {ts}")
                click.echo(f"    Input: {input_text}...")
                response = entry.get("response", {})
                sections = response.get("sections", [])
                if sections:
                    first_section = sections[0]
                    content_preview = first_section.get("content", "")[:100]
                    click.echo(f"    Response ({len(sections)} sections): {content_preview}...")
            elif op == "send_stream":
                input_text = entry.get("input", "")[:50]
                click.echo(f"[{seq_num}] {op.upper()} @ {ts}")
                click.echo(f"    Input: {input_text}...")
                final_buffer = entry.get("final_buffer", "")[:100]
                click.echo(f"    Final buffer: {final_buffer}...")
            elif op == "read":
                lines = entry.get("lines", "?")
                click.echo(f"[{seq_num}] {op.upper()} @ {ts} ({lines} lines)")
            elif op == "interrupt":
                click.echo(f"[{seq_num}] {op.upper()} @ {ts} (Ctrl+C)")
            elif op in ("write", "run"):
                input_text = entry.get("input", "")[:80]
                click.echo(f"[{seq_num}] {op.upper()} @ {ts}")
                click.echo(f"    {input_text}")
            elif op == "close":
                reason = entry.get("reason") or "normal"
                click.echo(f"[{seq_num}] {op.upper()} @ {ts} (reason: {reason})")
            else:
                click.echo(f"[{seq_num}] {op.upper()} @ {ts}")

            click.echo()  # Blank line between entries


# Modify existing channel create command to add history flag
@channel.command("create")
@click.argument("name")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
@click.option("--command", "-c", default=None, help="Command to run")
@click.option("--cwd", default=None, help="Working directory")
@click.option(
    "--backend",
    "-b",
    type=click.Choice(["pty", "wezterm", "claude-wezterm"]),
    default="pty",
)
@click.option("--pane-id", default=None, help="Attach to existing WezTerm pane")
@click.option(
    "--history/--no-history",
    default=True,
    help="Enable/disable history logging (default: enabled)",
)
def channel_create(
    name: str,
    server_name: str,
    command: str | None,
    cwd: str | None,
    backend: str,
    pane_id: str | None,
    history: bool,
):
    """Create a new AI CLI channel."""
    # ... existing implementation ...

    params = {
        "channel_id": name,
        "cwd": cwd,
        "backend": backend,
        "history": history,  # NEW: Pass history flag
    }

    if command:
        params["command"] = command
    if pane_id:
        params["pane_id"] = pane_id

    # ... send command to server ...
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

Location: `tests/core/test_history.py`

```python
"""Tests for channel history."""

import json
import tempfile
from pathlib import Path

import pytest

from nerve.core.channels.history import HistoryWriter, HistoryReader, HistoryError


class TestHistoryWriter:
    """Tests for HistoryWriter."""

    def test_create_writer(self, tmp_path):
        """Test creating a history writer."""
        writer = HistoryWriter.create(
            channel_id="test-channel",
            server_name="test-server",
            base_dir=tmp_path,
        )

        assert writer.channel_id == "test-channel"
        assert writer.server_name == "test-server"
        assert writer.enabled is True
        assert writer.file_path.exists()

        writer.close()

    def test_disabled_writer_no_file(self, tmp_path):
        """Test disabled writer doesn't create file."""
        writer = HistoryWriter.create(
            channel_id="test-channel",
            server_name="test-server",
            base_dir=tmp_path,
            enabled=False,
        )

        writer.log_run("echo hello")

        assert not writer.file_path.exists()
        writer.close()

    def test_sequence_recovery_on_append(self, tmp_path):
        """Test sequence numbers continue from existing file."""
        # First writer
        writer1 = HistoryWriter.create(
            channel_id="test-channel",
            server_name="test-server",
            base_dir=tmp_path,
        )
        writer1.log_run("cmd1")  # seq 1
        writer1.log_run("cmd2")  # seq 2
        writer1.close()

        # Second writer (simulates server restart)
        writer2 = HistoryWriter.create(
            channel_id="test-channel",
            server_name="test-server",
            base_dir=tmp_path,
        )
        seq = writer2.log_run("cmd3")  # Should be seq 3
        writer2.close()

        assert seq == 3

    def test_error_handling_non_serializable(self, tmp_path):
        """Test graceful handling of non-serializable objects."""
        writer = HistoryWriter.create(
            channel_id="test-channel",
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

    def test_create_failure_raises_history_error(self, tmp_path):
        """Test that unwritable directory raises HistoryError."""
        # Create a file where directory should be
        blocker = tmp_path / "history" / "test-server"
        blocker.parent.mkdir(parents=True)
        blocker.touch()  # File, not directory

        with pytest.raises(HistoryError):
            HistoryWriter.create(
                channel_id="test-channel",
                server_name="test-server",
                base_dir=tmp_path / "history",
            )


class TestHistoryReader:
    """Tests for HistoryReader."""

    @pytest.fixture
    def history_file(self, tmp_path):
        """Create a sample history file."""
        writer = HistoryWriter.create(
            channel_id="test-channel",
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
        writer.log_close()
        writer.close()

        return tmp_path

    def test_get_all(self, history_file):
        """Test getting all entries."""
        reader = HistoryReader.create(
            channel_id="test-channel",
            server_name="test-server",
            base_dir=history_file,
        )

        entries = reader.get_all()

        assert len(entries) == 4
        assert entries[0]["op"] == "run"
        assert entries[-1]["op"] == "close"

    def test_reader_not_found_raises(self, tmp_path):
        """Test reader raises FileNotFoundError for missing channel."""
        with pytest.raises(FileNotFoundError):
            HistoryReader.create(
                channel_id="nonexistent",
                server_name="test-server",
                base_dir=tmp_path,
            )

    def test_malformed_json_skipped(self, tmp_path):
        """Test malformed lines are skipped."""
        # Create file with bad line
        server_dir = tmp_path / "test-server"
        server_dir.mkdir(parents=True)
        file_path = server_dir / "test-channel.jsonl"

        with open(file_path, "w") as f:
            f.write('{"seq": 1, "op": "run"}\n')
            f.write('this is not json\n')  # Bad line
            f.write('{"seq": 2, "op": "close"}\n')

        reader = HistoryReader.create(
            channel_id="test-channel",
            server_name="test-server",
            base_dir=tmp_path,
        )

        entries = reader.get_all()
        assert len(entries) == 2  # Bad line skipped


class TestWezTermChannelHistory:
    """Integration tests for WezTermChannel with history."""

    @pytest.mark.asyncio
    async def test_attach_with_history(self, tmp_path, mocker):
        """Test WezTermChannel.attach() accepts history_writer."""
        # Mock WezTermBackend to avoid real WezTerm dependency
        mock_backend = mocker.MagicMock()
        mock_backend.buffer = "test buffer"
        mock_backend.pane_id = "123"
        mocker.patch(
            'nerve.core.channels.wezterm.WezTermBackend',
            return_value=mock_backend
        )
        mock_backend.attach = mocker.AsyncMock()

        from nerve.core.channels.wezterm import WezTermChannel
        from nerve.core.channels.history import HistoryWriter

        history_writer = HistoryWriter.create(
            channel_id="test",
            server_name="test",
            base_dir=tmp_path,
        )

        channel = await WezTermChannel.attach(
            channel_id="test",
            pane_id="123",
            history_writer=history_writer,
        )

        assert channel._history_writer is history_writer
        history_writer.close()


class TestClaudeOnWezTermChannelHistory:
    """Tests for ClaudeOnWezTermChannel history ownership."""

    @pytest.mark.asyncio
    async def test_wrapper_owns_history(self, tmp_path, mocker):
        """Test that wrapper owns history, not inner channel."""
        # Complex mock setup for ClaudeOnWezTermChannel
        mock_backend = mocker.MagicMock()
        mock_backend.buffer = "Claude started"
        mock_backend.pane_id = "123"
        mock_backend.write = mocker.AsyncMock()
        mock_backend.stop = mocker.AsyncMock()

        mocker.patch(
            'nerve.core.channels.wezterm.WezTermBackend',
            return_value=mock_backend
        )
        mock_backend.start = mocker.AsyncMock()

        from nerve.core.channels.claude_wezterm import ClaudeOnWezTermChannel
        from nerve.core.channels.history import HistoryWriter

        history_writer = HistoryWriter.create(
            channel_id="test-claude",
            server_name="test",
            base_dir=tmp_path,
        )

        channel = await ClaudeOnWezTermChannel.create(
            channel_id="test-claude",
            command="claude",
            history_writer=history_writer,
        )

        # Wrapper has history writer
        assert channel._history_writer is history_writer
        # Inner does NOT have history writer
        assert channel._inner._history_writer is None

        await channel.close()


class TestInterleavedAccess:
    """Tests for interleaved history access.

    Note: These tests verify interleaved (not truly concurrent) writes work
    correctly. Since log_*() methods are synchronous, Python's GIL ensures
    each write completes atomically. The await points between writes allow
    task switching, creating interleaved but not concurrent execution.
    """

    @pytest.mark.asyncio
    async def test_interleaved_writes(self, tmp_path):
        """Test interleaved async writes don't corrupt file.

        This tests that multiple async tasks writing to the same history
        file produce valid output. Writes are interleaved (not concurrent)
        because log_write() is synchronous - task switching only occurs
        at await points between writes.
        """
        import asyncio
        from nerve.core.channels.history import HistoryWriter

        writer = HistoryWriter.create(
            channel_id="test",
            server_name="test",
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
```

---

## 10. Backwards Compatibility

### 10.1 Guarantees

| Aspect | Guarantee |
|--------|-----------|
| Existing channel creation | Works unchanged (history enabled by default) |
| Existing channel methods | Same signatures, same behavior |
| Existing CLI commands | No changes required |
| Existing API endpoints | No changes required |
| Performance | Negligible impact (<1ms per operation) |

### 10.2 Opt-out Mechanism

```python
# Programmatic
channel = await PTYChannel.create("test", history_writer=None)

# Via ChannelManager
await manager.create_terminal("test", history=False)

# CLI
nerve server channel create my-claude --server test --no-history

# API
{"channel_id": "my-claude", "history": false}
```

---

## 11. Implementation Phases

### Phase 1: Core (P0)
- [ ] Implement `HistoryWriter` class with error handling
- [ ] Implement `HistoryReader` class
- [ ] Add sequence recovery on file append
- [ ] Unit tests for writer/reader

### Phase 2: Channel Integration (P0)
- [ ] Add `_history_writer` to `PTYChannel`
- [ ] Add `_history_writer` to `WezTermChannel`
- [ ] Add `_history_writer` to `ClaudeOnWezTermChannel` (wrapper owns)
- [ ] Update `WezTermChannel.attach()` to accept history_writer
- [ ] Integration tests for all channel types

### Phase 3: ChannelManager Integration (P0)
- [ ] Add `_server_name` to `ChannelManager`
- [ ] Add `history` parameter to `create_terminal()`
- [ ] Handle history writer lifecycle (cleanup on failure)
- [ ] Integration tests

### Phase 4: Engine/CLI (P1)
- [ ] Add `_server_name` to `NerveEngine`
- [ ] Pass server name from CLI to engine
- [ ] Add `channel history` subcommand
- [ ] Add `--history/--no-history` to `channel create`
- [ ] CLI tests

### Phase 5: API (P2)
- [ ] Add `GET_HISTORY` command type
- [ ] Implement `_get_history` handler
- [ ] Add `/channels/{id}/history` endpoint
- [ ] API tests

---

## 12. Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2025-12-22 | Initial draft |
| 0.2 | 2025-12-22 | Addressed coach feedback: ChannelManager integration, WezTermChannel code, ClaudeOnWezTermChannel ownership, removed double reads in send(), added error handling policy, fixed sequence recovery, added performance tradeoff docs, renamed to preceding_buffer_seq |
| 0.3 | 2025-12-22 | Fixed asyncio.Lock inconsistency: removed unused lock, updated docstring to accurately describe synchronous operations, renamed test class to TestInterleavedAccess with clarifying comments |
| 0.4 | 2025-12-22 | Final review: added send_stream() handling with SendStreamEntry data model, added interrupt() handling with InterruptEntry data model, added name validation requirements (Section 5.2), defined HISTORY_BUFFER_LINES constant with rationale (Section 5.1), restored complete CLI implementation (Section 8.4), fixed test response structure to include is_complete/is_ready, completed NerveEngine parameter flow diagram (Section 5.8), replaced all hardcoded read_tail(50) with HISTORY_BUFFER_LINES |

---

## Appendix A: Coach Feedback Resolution

| Issue | Resolution |
|-------|------------|
| **#1 ChannelManager Missing** | Added Section 5.2 with complete ChannelManager changes |
| **#2 WezTermChannel Code Missing** | Added Section 5.4 with explicit code |
| **#3 ClaudeOnWezTermChannel Ignored** | Added Section 5.5; wrapper owns history, inner has none |
| **#4 Double Reads in send()** | Fixed: Only one pre-send read, no post-send auto-read (see Section 3.4 table) |
| **#5 False Thread-Safety Claim** | Removed unused lock, docstring now accurately describes synchronous atomic operations |
| **#6 File Handle Leak Risk** | Added try/except/finally in ChannelManager (Section 5.2) |
| **#7 Sequence Restart on Server Restart** | Added `_recover_last_seq()` method (Section 5.1) |
| **#8 Added Sleeps Performance** | Documented in Section 7.1 with rationale |
| **#9 Error Handling Not Defined** | Added Section 6 with fail-soft policy |
| **#10 _server_name Source** | Section 5.6 shows CLI passing name to engine |
| **#11 HistoryReader Efficiency** | Documented in Section 5.1 as acceptable for v1 |
| **#12 Test Coverage Gaps** | Added tests for concurrent access, attach(), wrapper ownership, error conditions |
| **#13 API for --no-history** | Section 8.3 specifies empty array response |
| **#14 buffer_after_seq Naming** | Renamed to `preceding_buffer_seq` throughout |
| **#15 SendEntry Inheritance Confusion** | Clarified in Section 4.1 that entries don't inherit |
| **#16 Synchronous File I/O** | Documented in Section 7.2 as acceptable for v1 |
