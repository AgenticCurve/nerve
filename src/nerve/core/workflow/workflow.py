"""Workflow - async Python functions registered with a Session.

A Workflow wraps an async function that orchestrates nodes with control flow
(loops, conditionals, gates). Workflows are registered with a Session and can
be executed from Commander.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.session import Session
    from nerve.core.workflow.context import WorkflowContext


class WorkflowState(Enum):
    """Workflow execution states."""

    PENDING = "pending"  # Created but not started
    RUNNING = "running"  # Currently executing
    WAITING = "waiting"  # Blocked on gate() call
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"  # Finished with error
    CANCELLED = "cancelled"  # User cancelled


@dataclass
class WorkflowInfo:
    """Serializable workflow metadata."""

    id: str
    description: str
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
        }


class Workflow:
    """A registered workflow function.

    Workflows are async Python functions that orchestrate nodes with
    control flow (loops, conditionals, gates). They are registered with
    a Session and can be executed from Commander.

    Example:
        async def my_workflow(ctx: WorkflowContext) -> str:
            result = await ctx.run("node1", "input")
            decision = await ctx.gate("Continue?")
            if decision == "yes":
                return await ctx.run("node2", result["output"])
            return "Cancelled"

        Workflow(id="my_workflow", session=session, fn=my_workflow)
    """

    def __init__(
        self,
        id: str,
        session: Session,
        fn: Callable[[WorkflowContext], Awaitable[Any]],
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Create and register a workflow.

        Args:
            id: Unique workflow identifier (validated same as node IDs)
            session: Session to register with
            fn: Async function that receives WorkflowContext
            description: Human-readable description
            metadata: Optional metadata dict

        Raises:
            ValueError: If ID conflicts with existing workflow, node, or graph
        """
        # Validate ID uniqueness across workflows, nodes, and graphs
        session.validate_unique_id(id, entity_type="workflow")

        self._id = id
        self._session = session
        self._fn = fn
        self._description = description or fn.__doc__ or ""
        self._metadata = metadata or {}
        self._created_at = datetime.now(UTC)

        # Register with session
        session.workflows[id] = self

    @property
    def id(self) -> str:
        """Workflow ID."""
        return self._id

    @property
    def session(self) -> Session:
        """Session this workflow belongs to."""
        return self._session

    @property
    def fn(self) -> Callable[[WorkflowContext], Awaitable[Any]]:
        """The workflow function."""
        return self._fn

    @property
    def description(self) -> str:
        """Human-readable description."""
        return self._description

    @property
    def metadata(self) -> dict[str, Any]:
        """Optional metadata."""
        return self._metadata

    def to_info(self) -> WorkflowInfo:
        """Get serializable workflow info."""
        return WorkflowInfo(
            id=self._id,
            description=self._description,
            created_at=self._created_at,
        )

    def __repr__(self) -> str:
        return f"Workflow(id='{self._id}')"
