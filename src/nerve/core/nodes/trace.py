"""Execution tracing for graph execution observability.

Traces provide visibility into what happened during graph execution:
- Which steps ran and in what order
- Timing information per step
- Input/output for each step
- Errors that occurred

Tracing is opt-in via context parameter to avoid overhead
when not needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class StepTrace:
    """Trace record for a single step execution.

    Captures everything about one step's execution for debugging
    and monitoring purposes.

    Attributes:
        step_id: The step identifier in the graph.
        node_id: The node that was executed.
        node_type: Type of node (function, pty, wezterm, graph).
        input: Input provided to the step.
        output: Output produced by the step (None if error).
        error: Error message if step failed (None if success).
        start_time: When step execution started.
        end_time: When step execution completed.
        duration_ms: Execution time in milliseconds.
        tokens_used: Token count if applicable (for LLM nodes).
        metadata: Additional step-specific data.
    """

    step_id: str
    node_id: str
    node_type: str
    input: Any
    output: Any
    error: str | None
    start_time: datetime
    end_time: datetime
    duration_ms: float
    tokens_used: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict.

        Returns:
            Dict representation of the trace.
        """
        return {
            "step_id": self.step_id,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "input": _safe_repr(self.input),
            "output": _safe_repr(self.output),
            "error": self.error,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
            "metadata": self.metadata,
        }


@dataclass
class ExecutionTrace:
    """Trace record for an entire graph execution.

    Aggregates step traces and provides summary information
    for the complete execution.

    Attributes:
        graph_id: The graph identifier.
        start_time: When graph execution started.
        end_time: When graph execution completed (None if still running).
        status: Execution status.
        steps: List of step traces in execution order.
        total_tokens: Sum of tokens across all steps.
        total_cost: Sum of costs across all steps.
        error: Error message if execution failed.

    Example:
        >>> trace = ExecutionTrace(graph_id="main", start_time=datetime.now())
        >>> results = await graph.execute(ExecutionContext(session=s, trace=trace))
        >>> print(trace.explain())
    """

    graph_id: str
    start_time: datetime
    end_time: datetime | None = None
    status: Literal["running", "completed", "failed", "cancelled"] = "running"
    steps: list[StepTrace] = field(default_factory=list)
    total_tokens: int = 0
    total_cost: float = 0.0
    error: str | None = None

    def add_step(self, step: StepTrace) -> None:
        """Add a step trace to the execution.

        Args:
            step: The step trace to add.
        """
        self.steps.append(step)
        self.total_tokens += step.tokens_used

    def complete(self, error: str | None = None) -> None:
        """Mark execution as complete.

        Args:
            error: Error message if execution failed.
        """
        self.end_time = datetime.now()
        if error:
            self.status = "failed"
            self.error = error
        else:
            self.status = "completed"

    def cancel(self) -> None:
        """Mark execution as cancelled."""
        self.end_time = datetime.now()
        self.status = "cancelled"

    @property
    def duration_ms(self) -> float | None:
        """Total execution duration in milliseconds.

        Returns:
            Duration if execution is complete, None otherwise.
        """
        if self.end_time is None:
            return None
        delta = self.end_time - self.start_time
        return delta.total_seconds() * 1000

    def explain(self) -> str:
        """Generate human-readable execution summary.

        Returns:
            Multi-line string describing the execution.
        """
        lines = [
            f"Graph: {self.graph_id}",
            f"Status: {self.status}",
        ]

        if self.duration_ms is not None:
            lines.append(f"Duration: {self.duration_ms:.0f}ms")

        if self.total_tokens > 0:
            lines.append(f"Tokens: {self.total_tokens}")

        lines.append(f"Steps: {len(self.steps)}")

        for step in self.steps:
            status_indicator = "x" if step.error else "+"
            lines.append(
                f"  [{status_indicator}] {step.step_id} ({step.node_type}): "
                f"{step.duration_ms:.0f}ms"
            )
            if step.error:
                lines.append(f"      Error: {step.error}")

        if self.error:
            lines.append(f"Error: {self.error}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict.

        Returns:
            Dict representation of the trace.
        """
        return {
            "graph_id": self.graph_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "steps": [step.to_dict() for step in self.steps],
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "error": self.error,
        }


def _safe_repr(value: Any) -> Any:
    """Convert value to JSON-safe representation.

    Args:
        value: Any value to convert.

    Returns:
        JSON-serializable representation.
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_repr(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_repr(v) for k, v in value.items()}
    # For other types, convert to string
    return str(value)
