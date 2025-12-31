"""WorkflowRun - execution tracker for workflow runs.

Tracks execution state, manages gates, and emits events.
Each workflow execution creates a new WorkflowRun instance.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from nerve.core.workflow.context import WorkflowContext
from nerve.core.workflow.events import WorkflowEvent
from nerve.core.workflow.workflow import WorkflowState

if TYPE_CHECKING:
    from nerve.core.workflow.workflow import Workflow

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Return current UTC time (helper for default_factory)."""
    return datetime.now(UTC)


@dataclass
class GateInfo:
    """Metadata for a pending gate."""

    gate_id: str
    prompt: str
    choices: list[str] | None
    future: asyncio.Future[str]
    created_at: datetime = field(default_factory=_utc_now)


@dataclass
class WorkflowRunInfo:
    """Serializable run metadata."""

    run_id: str
    workflow_id: str
    state: WorkflowState
    started_at: datetime | None
    completed_at: datetime | None
    result: Any
    error: str | None
    pending_gate: dict[str, Any] | None
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "state": self.state.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "pending_gate": self.pending_gate,
            "events": self.events,
        }


# Type alias for event callback
EventCallback = Callable[[WorkflowEvent], Awaitable[None]]


class WorkflowRun:
    """A single execution of a workflow.

    Tracks execution state, manages gates, and emits events.
    Each workflow execution creates a new WorkflowRun instance.

    Lifecycle:
        1. Created with PENDING state
        2. start() transitions to RUNNING
        3. May transition to WAITING when gate() called
        4. answer_gate() transitions back to RUNNING
        5. Completes as COMPLETED, FAILED, or CANCELLED
    """

    def __init__(
        self,
        workflow: Workflow,
        input: Any,
        params: dict[str, Any] | None = None,
        event_callback: EventCallback | None = None,
    ) -> None:
        """Create a new workflow run.

        Args:
            workflow: The workflow to execute
            input: Input to pass to workflow function
            params: Additional parameters for WorkflowContext
            event_callback: Optional async callback for events
        """
        self._run_id = str(uuid4())
        self._workflow = workflow
        self._input = input
        self._params = params or {}
        self._event_callback = event_callback

        self._state = WorkflowState.PENDING
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._result: Any = None
        self._error: str | None = None
        self._exception: BaseException | None = None  # Original exception for re-raising

        # Gate management
        self._pending_gate: GateInfo | None = None
        self._task: asyncio.Task[Any] | None = None

        # Event history for TUI step tracking
        self._events: list[WorkflowEvent] = []

        logger.debug(
            "workflow_run_created: run_id=%s, workflow_id=%s",
            self._run_id,
            workflow.id,
        )

    @property
    def run_id(self) -> str:
        """Unique run identifier."""
        return self._run_id

    @property
    def workflow_id(self) -> str:
        """ID of the workflow being executed."""
        return self._workflow.id

    @property
    def state(self) -> WorkflowState:
        """Current execution state."""
        return self._state

    @property
    def result(self) -> Any:
        """Result value (if completed successfully)."""
        return self._result

    @property
    def error(self) -> str | None:
        """Error message (if failed)."""
        return self._error

    @property
    def is_complete(self) -> bool:
        """Whether execution has finished (success, failure, or cancelled)."""
        return self._state in (
            WorkflowState.COMPLETED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        )

    @property
    def pending_gate(self) -> GateInfo | None:
        """Currently pending gate, if any."""
        return self._pending_gate

    async def start(self) -> None:
        """Start workflow execution.

        Creates the WorkflowContext and begins executing the workflow
        function. Returns immediately; use wait() to block until complete.

        Raises:
            RuntimeError: If already started
        """
        if self._state != WorkflowState.PENDING:
            raise RuntimeError(f"Cannot start run in state {self._state}")

        self._state = WorkflowState.RUNNING
        self._started_at = datetime.now(UTC)

        logger.debug(
            "workflow_run_started: run_id=%s, workflow_id=%s",
            self._run_id,
            self._workflow.id,
        )

        # Emit started event
        self._emit_event(
            "workflow_started",
            {
                "run_id": self._run_id,
                "workflow_id": self._workflow.id,
            },
        )

        # Create context
        ctx = WorkflowContext(
            session=self._workflow.session,
            input=self._input,
            params=self._params,
        )
        ctx._run = self

        # Start execution in background task
        self._task = asyncio.create_task(self._execute(ctx))

    async def _execute(self, ctx: WorkflowContext) -> None:
        """Execute the workflow function."""
        try:
            result = await self._workflow.fn(ctx)
            self._result = result
            self._state = WorkflowState.COMPLETED
            self._completed_at = datetime.now(UTC)

            logger.debug(
                "workflow_run_completed: run_id=%s, workflow_id=%s",
                self._run_id,
                self._workflow.id,
            )

            self._emit_event(
                "workflow_completed",
                {
                    "run_id": self._run_id,
                    "result": result,
                },
            )

        except asyncio.CancelledError:
            self._state = WorkflowState.CANCELLED
            self._completed_at = datetime.now(UTC)

            logger.debug(
                "workflow_run_cancelled: run_id=%s, workflow_id=%s",
                self._run_id,
                self._workflow.id,
            )

            self._emit_event(
                "workflow_cancelled",
                {
                    "run_id": self._run_id,
                },
            )

        except Exception as e:
            self._error = str(e)
            self._exception = e  # Store original for re-raising with traceback
            self._state = WorkflowState.FAILED
            self._completed_at = datetime.now(UTC)

            logger.exception(
                "workflow_run_failed: run_id=%s, workflow_id=%s, error=%s",
                self._run_id,
                self._workflow.id,
                str(e),
            )

            self._emit_event(
                "workflow_failed",
                {
                    "run_id": self._run_id,
                    "error": str(e),
                },
            )

    async def wait(self) -> Any:
        """Wait for workflow to complete.

        Returns:
            Workflow result if completed successfully

        Raises:
            Exception: If workflow failed
            asyncio.CancelledError: If workflow was cancelled
            RuntimeError: If workflow not started
        """
        if self._task is None:
            raise RuntimeError("Workflow not started")

        await self._task

        if self._state == WorkflowState.FAILED:
            # Re-raise original exception to preserve type and traceback
            if self._exception is not None:
                raise self._exception
            raise Exception(self._error)
        elif self._state == WorkflowState.CANCELLED:
            raise asyncio.CancelledError()

        return self._result

    async def cancel(self) -> None:
        """Cancel workflow execution."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def answer_gate(self, answer: str) -> None:
        """Provide answer to pending gate.

        Args:
            answer: User's answer string

        Raises:
            RuntimeError: If no gate is pending
            ValueError: If answer not in allowed choices
        """
        if self._pending_gate is None:
            raise RuntimeError("No gate pending")

        gate = self._pending_gate

        # Validate against choices if specified
        if gate.choices and answer not in gate.choices:
            raise ValueError(f"Invalid choice '{answer}'. Must be one of: {gate.choices}")

        logger.debug(
            "workflow_gate_answered: run_id=%s, gate_id=%s, answer=%s",
            self._run_id,
            gate.gate_id,
            answer,
        )

        # Complete the future
        gate.future.set_result(answer)
        self._pending_gate = None
        self._state = WorkflowState.RUNNING

    def _register_gate(
        self,
        gate_id: str,
        future: asyncio.Future[str],
        prompt: str,
        choices: list[str] | None,
    ) -> None:
        """Register a new pending gate (internal use)."""
        self._pending_gate = GateInfo(
            gate_id=gate_id,
            prompt=prompt,
            choices=choices,
            future=future,
        )
        self._state = WorkflowState.WAITING

        logger.debug(
            "workflow_gate_registered: run_id=%s, gate_id=%s, prompt=%s",
            self._run_id,
            gate_id,
            prompt,
        )

    def _unregister_gate(self, gate_id: str) -> None:
        """Unregister a gate (on timeout, internal use)."""
        if self._pending_gate and self._pending_gate.gate_id == gate_id:
            self._pending_gate = None
            self._state = WorkflowState.RUNNING

            logger.debug(
                "workflow_gate_unregistered: run_id=%s, gate_id=%s",
                self._run_id,
                gate_id,
            )

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit event via callback and store in history."""
        event = WorkflowEvent(
            run_id=self._run_id,
            workflow_id=self._workflow.id,
            event_type=event_type,
            data=data,
            timestamp=datetime.now(UTC),
        )

        # Store event in history for TUI access
        self._events.append(event)

        # Fire and forget callback - don't block workflow
        if self._event_callback is not None:
            task: asyncio.Task[None] = asyncio.create_task(
                self._event_callback(event)  # type: ignore[arg-type]
            )

            # Add done callback to log exceptions (fire-and-forget shouldn't lose errors)
            def _handle_callback_error(t: asyncio.Task[None]) -> None:
                if t.cancelled():
                    return
                exc = t.exception()
                if exc is not None:
                    logger.error(
                        "Event callback failed: run_id=%s, workflow_id=%s, event_type=%s, error=%s",
                        self._run_id,
                        self._workflow.id,
                        event_type,
                        exc,
                    )

            task.add_done_callback(_handle_callback_error)

    def to_info(self) -> WorkflowRunInfo:
        """Get serializable run info."""
        pending_gate = None
        if self._pending_gate:
            pending_gate = {
                "gate_id": self._pending_gate.gate_id,
                "prompt": self._pending_gate.prompt,
                "choices": self._pending_gate.choices,
            }

        return WorkflowRunInfo(
            run_id=self._run_id,
            workflow_id=self._workflow.id,
            state=self._state,
            started_at=self._started_at,
            completed_at=self._completed_at,
            result=self._result,
            error=self._error,
            pending_gate=pending_gate,
            events=[e.to_dict() for e in self._events],
        )
