"""Unified status indicators for Commander TUI.

Centralizes status emoji and style mappings to ensure consistency
across blocks, workflow runner, and monitor components.
"""

from __future__ import annotations

from typing import NamedTuple


class StatusIndicator(NamedTuple):
    """A status indicator with emoji and Rich style."""

    emoji: str
    style: str


# Block/step status indicators (standard)
STATUS_PENDING = StatusIndicator("⏳", "pending")
STATUS_WAITING = StatusIndicator("⏸️", "dim")
STATUS_RUNNING = StatusIndicator("⏳", "bold cyan")
STATUS_COMPLETED = StatusIndicator("✅", "success")
STATUS_COMPLETED_ASYNC = StatusIndicator("⚡", "success")
STATUS_ERROR = StatusIndicator("❌", "error")
STATUS_FAILED = StatusIndicator("❌", "error")  # Alias for error
STATUS_CANCELLED = StatusIndicator("🚫", "dim")

# Compact indicators for dense UIs (monitor cards)
STATUS_PENDING_COMPACT = StatusIndicator("⏳", "pending")
STATUS_WAITING_COMPACT = StatusIndicator("⏸️", "dim")
STATUS_RUNNING_COMPACT = StatusIndicator("⏳", "bold cyan")
STATUS_COMPLETED_COMPACT = StatusIndicator("✓", "success")
STATUS_ERROR_COMPACT = StatusIndicator("✗", "error")
STATUS_FAILED_COMPACT = StatusIndicator("✗", "error")
STATUS_CANCELLED_COMPACT = StatusIndicator("⊘", "dim")


# Mapping from status string to indicator (standard)
_STATUS_MAP: dict[str, StatusIndicator] = {
    "pending": STATUS_PENDING,
    "waiting": STATUS_WAITING,
    "running": STATUS_RUNNING,
    "completed": STATUS_COMPLETED,
    "error": STATUS_ERROR,
    "failed": STATUS_FAILED,
    "cancelled": STATUS_CANCELLED,
}

# Mapping from status string to indicator (compact)
_STATUS_MAP_COMPACT: dict[str, StatusIndicator] = {
    "pending": STATUS_PENDING_COMPACT,
    "waiting": STATUS_WAITING_COMPACT,
    "running": STATUS_RUNNING_COMPACT,
    "completed": STATUS_COMPLETED_COMPACT,
    "error": STATUS_ERROR_COMPACT,
    "failed": STATUS_FAILED_COMPACT,
    "cancelled": STATUS_CANCELLED_COMPACT,
}

# Default indicator for unknown statuses
_DEFAULT_INDICATOR = StatusIndicator("○", "dim")
_DEFAULT_INDICATOR_COMPACT = StatusIndicator("?", "dim")


def get_status_indicator(
    status: str,
    *,
    was_async: bool = False,
    compact: bool = False,
) -> StatusIndicator:
    """Get the status indicator for a given status string.

    Args:
        status: Status string (pending, waiting, running, completed, error, failed).
        was_async: If True and status is "completed", returns async completion indicator.
        compact: If True, use compact single-char indicators for dense UIs.

    Returns:
        StatusIndicator with emoji and style.
    """
    if status == "completed" and was_async:
        return STATUS_COMPLETED_ASYNC
    status_map = _STATUS_MAP_COMPACT if compact else _STATUS_MAP
    default = _DEFAULT_INDICATOR_COMPACT if compact else _DEFAULT_INDICATOR
    return status_map.get(status, default)


def get_status_emoji(
    status: str,
    *,
    was_async: bool = False,
    compact: bool = False,
) -> str:
    """Get just the emoji for a status.

    Convenience function for cases where only the emoji is needed.

    Args:
        status: Status string.
        was_async: If True and status is "completed", returns async emoji.
        compact: If True, use compact single-char indicators for dense UIs.

    Returns:
        Status emoji string.
    """
    return get_status_indicator(status, was_async=was_async, compact=compact).emoji


def get_status_style(
    status: str,
    *,
    was_async: bool = False,
    compact: bool = False,
) -> str:
    """Get just the Rich style for a status.

    Convenience function for cases where only the style is needed.

    Args:
        status: Status string.
        was_async: If True and status is "completed", returns async style.
        compact: If True, use compact single-char indicators for dense UIs.

    Returns:
        Rich style string.
    """
    return get_status_indicator(status, was_async=was_async, compact=compact).style
