"""StepEvent - events emitted during streaming graph execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class StepEvent:
    """Event emitted during streaming graph execution.

    Used by Graph.execute_stream() to provide real-time
    feedback on execution progress.

    Attributes:
        event_type: Type of event.
        step_id: The step this event relates to.
        node_id: The node being executed.
        data: Event-specific data (chunk content, result, or error).
        timestamp: When the event occurred.
    """

    event_type: Literal["step_start", "step_chunk", "step_complete", "step_error"]
    step_id: str
    node_id: str
    data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
