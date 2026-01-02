"""Suggestion history JSONL utilities for ML training data.

Provides async file I/O for appending suggestion records to JSONL files.
Each session has its own history file at:
    ~/.nerve/session_history/<server-name>/<session-name>/suggestion_history.jsonl

Key features:
- Async append to avoid blocking the TUI event loop
- Creates directories as needed
- Each line is a complete, self-contained training record
- Opt-in via NERVE_SUGGESTION_HISTORY=1 environment variable

Example:
    >>> from suggestion_history import append_to_history_async, is_history_enabled
    >>> if is_history_enabled():
    ...     asyncio.create_task(append_to_history_async(record, "local", "my-session"))
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nerve.frontends.tui.commander.suggestion_record import SuggestionRecord

logger = logging.getLogger(__name__)

# Environment variable to enable suggestion history logging
SUGGESTION_HISTORY_ENV = "NERVE_SUGGESTION_HISTORY"

# Base directory for session history
HISTORY_BASE_DIR = Path.home() / ".nerve" / "session_history"


def is_history_enabled() -> bool:
    """Check if suggestion history logging is enabled.

    Returns:
        True if NERVE_SUGGESTION_HISTORY=1 is set.
    """
    return os.environ.get(SUGGESTION_HISTORY_ENV, "").strip() == "1"


def get_history_path(server_name: str, session_name: str) -> Path:
    """Get the JSONL file path for a session.

    Args:
        server_name: Server name (e.g., "local", "prod-server").
        session_name: Session name (e.g., "my-project").

    Returns:
        Path to the suggestion_history.jsonl file.
    """
    # Sanitize names to be filesystem-safe
    safe_server = _sanitize_name(server_name or "local")
    safe_session = _sanitize_name(session_name or "default")

    return HISTORY_BASE_DIR / safe_server / safe_session / "suggestion_history.jsonl"


def _sanitize_name(name: str) -> str:
    """Sanitize a name for use in filesystem paths.

    Replaces problematic characters with underscores.

    Args:
        name: Original name.

    Returns:
        Filesystem-safe name.
    """
    # Replace path separators and other problematic chars
    for char in '/\\:*?"<>|':
        name = name.replace(char, "_")
    return name or "default"


async def append_to_history_async(
    record: SuggestionRecord,
    server_name: str,
    session_name: str,
) -> None:
    """Append a suggestion record to the session's JSONL history file.

    This is a fire-and-forget async operation - errors are logged but not raised.
    The function creates the directory structure if it doesn't exist.

    Args:
        record: The suggestion record to append.
        server_name: Server name for the path.
        session_name: Session name for the path.
    """
    try:
        path = get_history_path(server_name, session_name)

        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize to JSON
        data = record.to_full_dict()
        line = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"

        # Write async using thread pool to avoid blocking
        await asyncio.get_running_loop().run_in_executor(None, _append_line, path, line)

        logger.debug("Appended suggestion record to %s", path)

    except Exception as e:
        # Fire-and-forget - log but don't raise
        logger.warning("Failed to append suggestion history: %s", e)


def _append_line(path: Path, line: str) -> None:
    """Synchronous helper to append a line to a file.

    Args:
        path: File path.
        line: Line to append (should end with newline).
    """
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
