"""Workflow events for streaming execution status.

Events are emitted during workflow execution and can be streamed
to Commander for real-time visibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> datetime:
    """Return current UTC time (helper for default_factory)."""
    return datetime.now(UTC)


@dataclass
class WorkflowEvent:
    """Event emitted during workflow execution.

    Events are streamed to Commander for real-time visibility.

    Standard event types:
        Workflow lifecycle:
        - workflow_started: Workflow began execution
        - workflow_completed: Workflow finished successfully
        - workflow_failed: Workflow finished with error
        - workflow_cancelled: Workflow was cancelled

        Node execution (via ctx.run()):
        - node_started: Node execution began
        - node_completed: Node execution finished
        - node_error: Node execution failed
        - node_timeout: Node execution timed out

        Graph execution (via ctx.run_graph()):
        - graph_started: Graph execution began
        - graph_completed: Graph execution finished
        - graph_error: Graph execution failed
        - graph_timeout: Graph execution timed out

        Nested workflow execution (via ctx.run_workflow()):
        - nested_workflow_started: Nested workflow began
        - nested_workflow_completed: Nested workflow finished
        - nested_workflow_error: Nested workflow failed
        - nested_workflow_timeout: Nested workflow timed out
        - nested_workflow_cancelled: Nested workflow was cancelled

        Gate (human input):
        - gate_waiting: Workflow paused for human input
        - gate_answered: Human provided input
        - gate_timeout: Gate timed out waiting for input
        - gate_cancelled: Gate was cancelled (workflow cancelled while waiting)

    Custom event types can be emitted via ctx.emit().
    """

    run_id: str
    workflow_id: str
    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }
