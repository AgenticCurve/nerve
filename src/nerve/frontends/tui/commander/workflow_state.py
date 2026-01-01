"""State classes for workflow runner TUI.

Contains data structures for tracking workflow execution state,
step information, and view modes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ViewMode(Enum):
    """Current view mode of the TUI."""

    MAIN = "main"
    FULL_SCREEN = "full_screen"
    EVENTS = "events"


@dataclass
class StepInfo:
    """Information about a workflow step (node execution)."""

    node_id: str
    input_text: str = ""
    output_text: str = ""
    status: str = "running"  # running, completed, error
    error: str | None = None


@dataclass
class TUIWorkflowEvent:
    """A local workflow event for TUI display (not the core WorkflowEvent).

    Uses monotonic timestamp for elapsed time display in the TUI.
    """

    timestamp: float  # time.monotonic() value
    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
