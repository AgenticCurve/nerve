"""History persistence for nodes.

This module provides JSONL-based history recording for node operations.

Note: The old Channel protocol has been replaced by the Node protocol.
See nerve.core.nodes for the new abstractions.

Classes:
    HistoryWriter: Writes node history to JSONL file.
    HistoryReader: Reads node history from JSONL file.
    HistoryError: Error during history operations.
    HISTORY_BUFFER_LINES: Number of lines to capture for buffer state.
"""

from nerve.core.channels.history import (
    HISTORY_BUFFER_LINES,
    HistoryError,
    HistoryReader,
    HistoryWriter,
)

__all__ = [
    "HistoryWriter",
    "HistoryReader",
    "HistoryError",
    "HISTORY_BUFFER_LINES",
]
