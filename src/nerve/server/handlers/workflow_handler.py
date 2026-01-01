"""WorkflowHandler - Manages workflow execution.

Commands: EXECUTE_WORKFLOW, LIST_WORKFLOWS, GET_WORKFLOW_RUN,
          LIST_WORKFLOW_RUNS, ANSWER_GATE, CANCEL_WORKFLOW

State: Manages workflow execution through Session's workflow registry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nerve.core.workflow import WorkflowEvent, WorkflowRun, WorkflowState
from nerve.server.protocols import Event, EventType

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nerve.server.protocols import EventSink
    from nerve.server.session_registry import SessionRegistry
    from nerve.server.validation import ValidationHelpers


@dataclass
class WorkflowHandler:
    """Manages workflow execution.

    Commands: EXECUTE_WORKFLOW, LIST_WORKFLOWS, GET_WORKFLOW_RUN,
              LIST_WORKFLOW_RUNS, ANSWER_GATE, CANCEL_WORKFLOW

    State: Manages workflow execution through Session's workflow registry.
    """

    event_sink: EventSink
    validation: ValidationHelpers
    session_registry: SessionRegistry

    async def execute_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a workflow.

        Parameters:
            session_id: Session containing the workflow (optional, uses default)
            workflow_id: ID of workflow to execute (required)
            input: Input to pass to workflow (optional)
            params: Additional parameters for WorkflowContext (optional)
            wait: If True, wait for completion (default: False)

        Returns:
            run_id: Unique run identifier
            state: Current run state
            result: Result if wait=True and completed
        """
        session = self.session_registry.get_session(params.get("session_id"))
        workflow_id = self.validation.require_param(params, "workflow_id")

        workflow = session.get_workflow(workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow '{workflow_id}' not found in session '{session.name}'")

        # Create event callback that converts to server events
        async def event_callback(event: WorkflowEvent) -> None:
            event_type = self._map_workflow_event_type(event.event_type)
            if event_type:
                await self.event_sink.emit(
                    Event(
                        type=event_type,
                        data={
                            "run_id": event.run_id,
                            "workflow_id": event.workflow_id,
                            "event_type": event.event_type,
                            **event.data,
                        },
                    )
                )

        # Create run
        run = WorkflowRun(
            workflow=workflow,
            input=params.get("input"),
            params=params.get("params", {}),
            event_callback=event_callback,
        )

        # Register with session
        session.register_workflow_run(run)

        logger.debug(
            "workflow_execute: session=%s, workflow_id=%s, run_id=%s",
            session.name,
            workflow_id,
            run.run_id,
        )

        # Start execution
        await run.start()

        # Optionally wait for completion
        if params.get("wait", False):
            try:
                result = await run.wait()
                return {
                    "run_id": run.run_id,
                    "state": run.state.value,
                    "result": result,
                }
            except Exception as e:
                return {
                    "run_id": run.run_id,
                    "state": run.state.value,
                    "error": str(e),
                }

        return {
            "run_id": run.run_id,
            "state": run.state.value,
        }

    async def list_workflows(self, params: dict[str, Any]) -> dict[str, Any]:
        """List registered workflows.

        Parameters:
            session_id: Session to query (optional, uses default)

        Returns:
            workflows: List of workflow info dicts
        """
        session = self.session_registry.get_session(params.get("session_id"))

        workflows = []
        for workflow in session.workflows.values():
            info = workflow.to_info()
            workflows.append(info.to_dict())

        logger.debug(
            "workflow_list: session=%s, count=%d",
            session.name,
            len(workflows),
        )

        return {"workflows": workflows}

    async def get_workflow_run(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get workflow run status.

        Parameters:
            session_id: Session containing the run (optional, uses default)
            run_id: Run identifier (required)

        Returns:
            run: Run info dict
        """
        session = self.session_registry.get_session(params.get("session_id"))
        run_id = self.validation.require_param(params, "run_id")

        run = session.get_workflow_run(run_id)
        if run is None:
            raise ValueError(f"Workflow run '{run_id}' not found in session '{session.name}'")

        logger.debug(
            "workflow_run_get: session=%s, run_id=%s, state=%s",
            session.name,
            run_id,
            run.state.value,
        )

        return {"run": run.to_info().to_dict()}

    async def list_workflow_runs(self, params: dict[str, Any]) -> dict[str, Any]:
        """List workflow runs.

        Parameters:
            session_id: Session to query (optional, uses default)
            workflow_id: Optional filter by workflow
            state: Optional filter by state

        Returns:
            runs: List of run info dicts
        """
        session = self.session_registry.get_session(params.get("session_id"))

        state = None
        if state_str := params.get("state"):
            try:
                state = WorkflowState(state_str)
            except ValueError as e:
                raise ValueError(f"Invalid state: {state_str}") from e

        runs = session.list_workflow_runs(
            workflow_id=params.get("workflow_id"),
            state=state,
        )

        logger.debug(
            "workflow_runs_list: session=%s, count=%d",
            session.name,
            len(runs),
        )

        return {"runs": [r.to_dict() for r in runs]}

    async def answer_gate(self, params: dict[str, Any]) -> dict[str, Any]:
        """Answer a pending gate.

        Parameters:
            session_id: Session containing the run (optional, uses default)
            run_id: Run with pending gate (required)
            answer: User's answer (required)

        Returns:
            success: True if answered
        """
        session = self.session_registry.get_session(params.get("session_id"))
        run_id = self.validation.require_param(params, "run_id")
        answer = self.validation.require_param(params, "answer")

        run = session.get_workflow_run(run_id)
        if run is None:
            raise ValueError(f"Workflow run '{run_id}' not found in session '{session.name}'")

        if run.state != WorkflowState.WAITING:
            raise ValueError(f"Run is not waiting for input (state: {run.state.value})")

        # Handle race condition: gate may timeout between state check and answer
        try:
            run.answer_gate(answer)
        except RuntimeError as e:
            if "No gate pending" in str(e):
                raise ValueError(f"No pending gate for run '{run_id}' (may have timed out)") from e
            raise

        logger.debug(
            "workflow_gate_answered: session=%s, run_id=%s",
            session.name,
            run_id,
        )

        await self.event_sink.emit(
            Event(
                type=EventType.WORKFLOW_GATE_ANSWERED,
                data={
                    "run_id": run_id,
                    "answer": answer,
                },
            )
        )

        return {"success": True}

    async def cancel_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cancel a running workflow.

        Parameters:
            session_id: Session containing the run (optional, uses default)
            run_id: Run to cancel (required)

        Returns:
            success: True if cancelled
        """
        session = self.session_registry.get_session(params.get("session_id"))
        run_id = self.validation.require_param(params, "run_id")

        run = session.get_workflow_run(run_id)
        if run is None:
            raise ValueError(f"Workflow run '{run_id}' not found in session '{session.name}'")

        await run.cancel()

        logger.debug(
            "workflow_cancelled: session=%s, run_id=%s",
            session.name,
            run_id,
        )

        # Note: WORKFLOW_CANCELLED event is already emitted by run.cancel()
        # via the event callback when CancelledError is caught in _execute()

        return {"success": True}

    def _map_workflow_event_type(self, event_type: str) -> EventType | None:
        """Map workflow event type string to EventType enum."""
        mapping = {
            "workflow_started": EventType.WORKFLOW_STARTED,
            "workflow_completed": EventType.WORKFLOW_COMPLETED,
            "workflow_failed": EventType.WORKFLOW_FAILED,
            "workflow_cancelled": EventType.WORKFLOW_CANCELLED,
            "gate_waiting": EventType.WORKFLOW_GATE_WAITING,
            "gate_answered": EventType.WORKFLOW_GATE_ANSWERED,
            "gate_timeout": EventType.WORKFLOW_GATE_TIMEOUT,
            "gate_cancelled": EventType.WORKFLOW_GATE_CANCELLED,
            "node_started": EventType.WORKFLOW_NODE_STARTED,
            "node_completed": EventType.WORKFLOW_NODE_COMPLETED,
            "node_error": EventType.WORKFLOW_NODE_ERROR,
            "node_timeout": EventType.WORKFLOW_NODE_TIMEOUT,
            "graph_started": EventType.WORKFLOW_GRAPH_STARTED,
            "graph_completed": EventType.WORKFLOW_GRAPH_COMPLETED,
            "graph_error": EventType.WORKFLOW_GRAPH_ERROR,
            "graph_timeout": EventType.WORKFLOW_GRAPH_TIMEOUT,
            "nested_workflow_started": EventType.WORKFLOW_NESTED_STARTED,
            "nested_workflow_completed": EventType.WORKFLOW_NESTED_COMPLETED,
            "nested_workflow_error": EventType.WORKFLOW_NESTED_ERROR,
            "nested_workflow_timeout": EventType.WORKFLOW_NESTED_TIMEOUT,
            "nested_workflow_cancelled": EventType.WORKFLOW_NESTED_CANCELLED,
        }
        return mapping.get(event_type)
