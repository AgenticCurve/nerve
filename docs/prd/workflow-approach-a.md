# PRD: Python Workflow Functions (Approach A)

## Document Info

- **Author**: System
- **Created**: 2025-01-01
- **Status**: Draft
- **Related**: `docs/prd/workflow-system.md` (overview), `examples/agents/dev_coach_review/`

---

## 1. Problem Statement

### 1.1 Current State

Nerve's graph system executes DAGs (Directed Acyclic Graphs) - nodes run in topological order with data flowing through dependencies. This works well for simple pipelines but cannot express:

- **Loops**: "Keep refining until approved"
- **Conditionals**: "If error, retry with different approach"
- **Human Gates**: "Pause and wait for user input"
- **Dynamic Branching**: "Based on result, choose next action"

### 1.2 The Workaround

Users write Python orchestration scripts (see `examples/agents/dev_coach_review/main.py` - 400+ lines) that manually:

1. Create sessions and nodes
2. Execute nodes in loops with `while` statements
3. Parse outputs to determine next actions
4. Handle user input via `input()` calls

This works but:
- Cannot be triggered from Commander
- No visibility into execution state
- No pause/resume capability
- Duplicates session/node management logic

### 1.3 Goal

Enable users to write Python async functions that orchestrate nodes, and execute them from Commander with full visibility and interactivity.

---

## 2. Solution Overview

### 2.1 Core Concept

A **Workflow** is an async Python function registered with a Session. It receives a `WorkflowContext` that provides:

- `run(node_id, input)` - Execute any node
- `gate(prompt)` - Pause and wait for human input
- `emit(event_type, data)` - Stream events to Commander
- `state` - Persistent dict for workflow state

### 2.2 User Experience

```python
# Define workflow
async def code_review(ctx: WorkflowContext) -> str:
    """Review code until approved."""
    code = ctx.input

    while True:
        # Get review from Claude
        review = await ctx.run("reviewer", f"Review this:\n{code}")
        ctx.emit("review_complete", {"review": review["output"]})

        # Wait for human decision
        decision = await ctx.gate("Accept, reject, or provide feedback:")

        if decision.lower() == "accept":
            return review["output"]
        elif decision.lower() == "reject":
            return "Review rejected"
        else:
            # Incorporate feedback and loop
            code = await ctx.run("editor", f"Apply feedback: {decision}\n\nCode:\n{code}")
            code = code["output"]

# Register with session
Workflow(id="code_review", session=session, fn=code_review)
```

```
# Execute from Commander
%code_review Here is my code...

# Commander shows:
[workflow] code_review started
[reviewer] Reviewing code...
[review_complete] Found 3 issues...
[gate] Accept, reject, or provide feedback: _
```

---

## 3. Detailed Design

### 3.1 Workflow Class

```python
# src/nerve/core/workflow/workflow.py

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable
from uuid import uuid4

if TYPE_CHECKING:
    from nerve.core.session import Session


class WorkflowState(Enum):
    """Workflow execution states."""
    PENDING = "pending"      # Created but not started
    RUNNING = "running"      # Currently executing
    WAITING = "waiting"      # Blocked on gate() call
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"        # Finished with error
    CANCELLED = "cancelled"  # User cancelled


@dataclass
class WorkflowInfo:
    """Serializable workflow metadata."""
    id: str
    description: str
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
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
        self._created_at = datetime.now()

        # Register with session
        session.workflows[id] = self

    @property
    def id(self) -> str:
        return self._id

    @property
    def session(self) -> Session:
        return self._session

    @property
    def fn(self) -> Callable[[WorkflowContext], Awaitable[Any]]:
        return self._fn

    @property
    def description(self) -> str:
        return self._description

    def to_info(self) -> WorkflowInfo:
        """Get serializable workflow info."""
        return WorkflowInfo(
            id=self._id,
            description=self._description,
            created_at=self._created_at,
        )

    def __repr__(self) -> str:
        return f"Workflow(id='{self._id}')"
```

### 3.2 WorkflowContext Class

```python
# src/nerve/core/workflow/context.py

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from nerve.core.nodes import ExecutionContext

if TYPE_CHECKING:
    from nerve.core.session import Session
    from nerve.core.workflow.run import WorkflowRun


@dataclass
class WorkflowContext:
    """Context passed to workflow functions.

    Provides helpers for executing nodes, waiting for human input,
    and emitting events to Commander.

    Attributes:
        session: The session containing nodes
        input: Initial input passed when workflow started
        params: Additional parameters passed at execution time
        state: Mutable dict for storing workflow state across iterations

    Example:
        async def my_workflow(ctx: WorkflowContext) -> str:
            # Execute a node
            result = await ctx.run("analyzer", ctx.input)

            # Store state for later iterations
            ctx.state["analysis"] = result["output"]

            # Wait for human decision
            decision = await ctx.gate("Approve analysis?")

            # Emit custom event
            ctx.emit("decision_made", {"decision": decision})

            return result["output"]
    """

    session: Session
    input: Any
    params: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)

    # Internal: set by WorkflowRun
    _run: WorkflowRun | None = field(default=None, repr=False)

    async def run(
        self,
        node_id: str,
        input: Any,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a node and return its result.

        Args:
            node_id: ID of node to execute
            input: Input to pass to node
            timeout: Optional timeout in seconds
            **kwargs: Additional args passed to ExecutionContext

        Returns:
            Node execution result dict with keys:
            - success: bool
            - output: Any (if success)
            - error: str (if not success)
            - attributes: dict

        Raises:
            ValueError: If node_id not found in session
            asyncio.TimeoutError: If timeout exceeded

        Example:
            result = await ctx.run("summarizer", "Long text here...")
            if result["success"]:
                summary = result["output"]
        """
        node = self.session.get_node(node_id)
        if node is None:
            raise ValueError(f"Node '{node_id}' not found in session")

        # Emit node_started event
        self.emit("node_started", {"node_id": node_id})

        # Create execution context
        exec_ctx = ExecutionContext(
            session=self.session,
            input=input,
            **kwargs,
        )

        # Execute with optional timeout
        try:
            if timeout:
                result = await asyncio.wait_for(
                    node.execute(exec_ctx),
                    timeout=timeout,
                )
            else:
                result = await node.execute(exec_ctx)
        except asyncio.TimeoutError:
            self.emit("node_timeout", {"node_id": node_id, "timeout": timeout})
            raise
        except Exception as e:
            self.emit("node_error", {"node_id": node_id, "error": str(e)})
            raise

        # Emit node_completed event
        self.emit("node_completed", {
            "node_id": node_id,
            "success": result.get("success", False),
        })

        return result

    async def gate(
        self,
        prompt: str,
        timeout: float | None = None,
        choices: list[str] | None = None,
    ) -> str:
        """Pause execution and wait for human input.

        Args:
            prompt: Message to display to user
            timeout: Optional timeout in seconds (None = wait forever)
            choices: Optional list of valid choices (for validation)

        Returns:
            User's input string

        Raises:
            asyncio.TimeoutError: If timeout exceeded
            asyncio.CancelledError: If workflow cancelled while waiting

        Example:
            # Simple gate
            answer = await ctx.gate("Continue? (yes/no)")

            # Gate with timeout
            answer = await ctx.gate("Approve?", timeout=300)

            # Gate with choices
            answer = await ctx.gate(
                "Select action:",
                choices=["approve", "reject", "revise"]
            )
        """
        if self._run is None:
            raise RuntimeError("WorkflowContext not attached to a WorkflowRun")

        # Create future for receiving input
        future: asyncio.Future[str] = asyncio.Future()

        # Register gate with run
        gate_id = str(uuid4())[:8]
        self._run._register_gate(gate_id, future, prompt, choices)

        # Emit gate_waiting event
        self.emit("gate_waiting", {
            "gate_id": gate_id,
            "prompt": prompt,
            "choices": choices,
        })

        try:
            if timeout:
                result = await asyncio.wait_for(future, timeout=timeout)
            else:
                result = await future

            self.emit("gate_answered", {
                "gate_id": gate_id,
                "answer": result,
            })

            return result

        except asyncio.TimeoutError:
            self._run._unregister_gate(gate_id)
            self.emit("gate_timeout", {"gate_id": gate_id, "timeout": timeout})
            raise

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Emit an event to Commander.

        Events are streamed to the Commander TUI in real-time, allowing
        visibility into workflow progress.

        Args:
            event_type: Event type identifier (e.g., "step_complete")
            data: Optional event payload

        Example:
            ctx.emit("analysis_started", {"file": "main.py"})
            ctx.emit("progress", {"percent": 50})
            ctx.emit("warning", {"message": "Rate limited, retrying..."})
        """
        if self._run is None:
            return  # Silently ignore if not attached to run

        self._run._emit_event(event_type, data or {})
```

### 3.3 WorkflowRun Class

```python
# src/nerve/core/workflow/run.py

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from nerve.core.workflow.workflow import WorkflowState
from nerve.core.workflow.context import WorkflowContext
from nerve.core.workflow.events import WorkflowEvent, WorkflowEventType

if TYPE_CHECKING:
    from nerve.core.workflow.workflow import Workflow
    from nerve.server.events import EventSink


@dataclass
class GateInfo:
    """Metadata for a pending gate."""
    gate_id: str
    prompt: str
    choices: list[str] | None
    future: asyncio.Future[str]
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class WorkflowRunInfo:
    """Serializable run metadata."""
    run_id: str
    workflow_id: str
    state: WorkflowState
    started_at: datetime
    completed_at: datetime | None
    result: Any
    error: str | None
    pending_gate: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "state": self.state.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "pending_gate": self.pending_gate,
        }


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
        event_sink: EventSink | None = None,
    ) -> None:
        """Create a new workflow run.

        Args:
            workflow: The workflow to execute
            input: Input to pass to workflow function
            params: Additional parameters for WorkflowContext
            event_sink: Optional sink for streaming events
        """
        self._run_id = str(uuid4())
        self._workflow = workflow
        self._input = input
        self._params = params or {}
        self._event_sink = event_sink

        self._state = WorkflowState.PENDING
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._result: Any = None
        self._error: str | None = None

        # Gate management
        self._pending_gate: GateInfo | None = None
        self._task: asyncio.Task | None = None

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def workflow_id(self) -> str:
        return self._workflow.id

    @property
    def state(self) -> WorkflowState:
        return self._state

    @property
    def is_complete(self) -> bool:
        return self._state in (
            WorkflowState.COMPLETED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        )

    @property
    def pending_gate(self) -> GateInfo | None:
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
        self._started_at = datetime.now()

        # Emit started event
        self._emit_event("workflow_started", {
            "run_id": self._run_id,
            "workflow_id": self._workflow.id,
        })

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
            self._completed_at = datetime.now()

            self._emit_event("workflow_completed", {
                "run_id": self._run_id,
                "result": result,
            })

        except asyncio.CancelledError:
            self._state = WorkflowState.CANCELLED
            self._completed_at = datetime.now()

            self._emit_event("workflow_cancelled", {
                "run_id": self._run_id,
            })

        except Exception as e:
            self._error = str(e)
            self._state = WorkflowState.FAILED
            self._completed_at = datetime.now()

            self._emit_event("workflow_failed", {
                "run_id": self._run_id,
                "error": str(e),
            })

    async def wait(self) -> Any:
        """Wait for workflow to complete.

        Returns:
            Workflow result if completed successfully

        Raises:
            Exception: If workflow failed
            asyncio.CancelledError: If workflow was cancelled
        """
        if self._task is None:
            raise RuntimeError("Workflow not started")

        await self._task

        if self._state == WorkflowState.FAILED:
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
            raise ValueError(
                f"Invalid choice '{answer}'. Must be one of: {gate.choices}"
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

    def _unregister_gate(self, gate_id: str) -> None:
        """Unregister a gate (on timeout, internal use)."""
        if self._pending_gate and self._pending_gate.gate_id == gate_id:
            self._pending_gate = None
            self._state = WorkflowState.RUNNING

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit event to sink (internal use)."""
        if self._event_sink is None:
            return

        event = WorkflowEvent(
            run_id=self._run_id,
            workflow_id=self._workflow.id,
            event_type=event_type,
            data=data,
            timestamp=datetime.now(),
        )

        # Fire and forget - don't block workflow
        asyncio.create_task(self._event_sink.emit(event))

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
            started_at=self._started_at or datetime.now(),
            completed_at=self._completed_at,
            result=self._result,
            error=self._error,
            pending_gate=pending_gate,
        )
```

### 3.4 Workflow Events

```python
# src/nerve/core/workflow/events.py

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class WorkflowEvent:
    """Event emitted during workflow execution.

    Events are streamed to Commander for real-time visibility.

    Standard event types:
        - workflow_started: Workflow began execution
        - workflow_completed: Workflow finished successfully
        - workflow_failed: Workflow finished with error
        - workflow_cancelled: Workflow was cancelled
        - node_started: Node execution began
        - node_completed: Node execution finished
        - node_error: Node execution failed
        - node_timeout: Node execution timed out
        - gate_waiting: Workflow paused for human input
        - gate_answered: Human provided input
        - gate_timeout: Gate timed out waiting for input

    Custom event types can be emitted via ctx.emit().
    """
    run_id: str
    workflow_id: str
    event_type: str
    data: dict[str, Any]
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }
```

### 3.5 Session Integration

The Session class needs additions to support workflows:

```python
# Additions to src/nerve/core/session/session.py

class Session:
    def __init__(self, ...):
        ...
        self.workflows: dict[str, Workflow] = {}
        self._workflow_runs: dict[str, WorkflowRun] = {}

    def validate_unique_id(self, id: str, entity_type: str) -> None:
        """Validate ID is unique across nodes, graphs, and workflows.

        Args:
            id: ID to validate
            entity_type: Type being created ("node", "graph", "workflow")

        Raises:
            ValueError: If ID already exists
        """
        # Validate format
        if not id or not re.match(r'^[a-z][a-z0-9_-]*$', id, re.IGNORECASE):
            raise ValueError(
                f"Invalid {entity_type} ID '{id}'. "
                "Must start with letter and contain only letters, numbers, underscores, hyphens."
            )

        # Check collisions
        if id in self.nodes:
            raise ValueError(f"ID '{id}' conflicts with existing node")
        if id in self.graphs:
            raise ValueError(f"ID '{id}' conflicts with existing graph")
        if id in self.workflows:
            raise ValueError(f"ID '{id}' conflicts with existing workflow")

    def get_workflow(self, id: str) -> Workflow | None:
        """Get workflow by ID."""
        return self.workflows.get(id)

    def list_workflows(self) -> list[str]:
        """List all workflow IDs."""
        return list(self.workflows.keys())

    def delete_workflow(self, id: str) -> bool:
        """Delete a workflow."""
        if id in self.workflows:
            del self.workflows[id]
            return True
        return False

    def get_workflow_run(self, run_id: str) -> WorkflowRun | None:
        """Get workflow run by ID."""
        return self._workflow_runs.get(run_id)

    def list_workflow_runs(
        self,
        workflow_id: str | None = None,
        state: WorkflowState | None = None,
    ) -> list[WorkflowRunInfo]:
        """List workflow runs with optional filters."""
        runs = []
        for run in self._workflow_runs.values():
            if workflow_id and run.workflow_id != workflow_id:
                continue
            if state and run.state != state:
                continue
            runs.append(run.to_info())
        return runs

    def _register_run(self, run: WorkflowRun) -> None:
        """Register a workflow run (internal use)."""
        self._workflow_runs[run.run_id] = run
```

---

## 4. Server Integration

### 4.1 Workflow Handler

```python
# src/nerve/server/handlers/workflow_handler.py

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nerve.core.workflow import Workflow, WorkflowRun, WorkflowState
from nerve.server.handlers.base import BaseHandler

if TYPE_CHECKING:
    from nerve.server.events import EventSink
    from nerve.server.session_registry import SessionRegistry


class WorkflowHandler(BaseHandler):
    """Handler for workflow-related commands.

    Commands:
        - EXECUTE_WORKFLOW: Start a workflow
        - LIST_WORKFLOWS: List registered workflows
        - GET_WORKFLOW_RUN: Get run status
        - LIST_WORKFLOW_RUNS: List runs
        - ANSWER_GATE: Provide input to pending gate
        - CANCEL_WORKFLOW: Cancel a running workflow
    """

    def __init__(
        self,
        session_registry: SessionRegistry,
        event_sink: EventSink,
    ) -> None:
        super().__init__(session_registry, event_sink)

    async def execute_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a workflow.

        Params:
            session_id: Session containing the workflow
            workflow_id: ID of workflow to execute
            input: Input to pass to workflow
            params: Optional additional parameters
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
            raise ValueError(f"Workflow '{workflow_id}' not found")

        # Create run
        run = WorkflowRun(
            workflow=workflow,
            input=params.get("input"),
            params=params.get("params", {}),
            event_sink=self.event_sink,
        )

        # Register with session
        session._register_run(run)

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

        Params:
            session_id: Session to query

        Returns:
            workflows: List of workflow info dicts
        """
        session = self.session_registry.get_session(params.get("session_id"))

        workflows = [
            workflow.to_info().to_dict()
            for workflow in session.workflows.values()
        ]

        return {"workflows": workflows}

    async def get_workflow_run(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get workflow run status.

        Params:
            session_id: Session containing the run
            run_id: Run identifier

        Returns:
            run: Run info dict
        """
        session = self.session_registry.get_session(params.get("session_id"))
        run_id = self.validation.require_param(params, "run_id")

        run = session.get_workflow_run(run_id)
        if run is None:
            raise ValueError(f"Workflow run '{run_id}' not found")

        return {"run": run.to_info().to_dict()}

    async def list_workflow_runs(self, params: dict[str, Any]) -> dict[str, Any]:
        """List workflow runs.

        Params:
            session_id: Session to query
            workflow_id: Optional filter by workflow
            state: Optional filter by state

        Returns:
            runs: List of run info dicts
        """
        session = self.session_registry.get_session(params.get("session_id"))

        state = None
        if state_str := params.get("state"):
            state = WorkflowState(state_str)

        runs = session.list_workflow_runs(
            workflow_id=params.get("workflow_id"),
            state=state,
        )

        return {"runs": [r.to_dict() for r in runs]}

    async def answer_gate(self, params: dict[str, Any]) -> dict[str, Any]:
        """Answer a pending gate.

        Params:
            session_id: Session containing the run
            run_id: Run with pending gate
            answer: User's answer

        Returns:
            success: True if answered
        """
        session = self.session_registry.get_session(params.get("session_id"))
        run_id = self.validation.require_param(params, "run_id")
        answer = self.validation.require_param(params, "answer")

        run = session.get_workflow_run(run_id)
        if run is None:
            raise ValueError(f"Workflow run '{run_id}' not found")

        if run.state != WorkflowState.WAITING:
            raise ValueError(f"Run is not waiting for input (state: {run.state})")

        run.answer_gate(answer)

        return {"success": True}

    async def cancel_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cancel a running workflow.

        Params:
            session_id: Session containing the run
            run_id: Run to cancel

        Returns:
            success: True if cancelled
        """
        session = self.session_registry.get_session(params.get("session_id"))
        run_id = self.validation.require_param(params, "run_id")

        run = session.get_workflow_run(run_id)
        if run is None:
            raise ValueError(f"Workflow run '{run_id}' not found")

        await run.cancel()

        return {"success": True}
```

### 4.2 Command Types

Add to `src/nerve/server/protocol.py`:

```python
class CommandType(str, Enum):
    ...
    # Workflow commands
    EXECUTE_WORKFLOW = "EXECUTE_WORKFLOW"
    LIST_WORKFLOWS = "LIST_WORKFLOWS"
    GET_WORKFLOW_RUN = "GET_WORKFLOW_RUN"
    LIST_WORKFLOW_RUNS = "LIST_WORKFLOW_RUNS"
    ANSWER_GATE = "ANSWER_GATE"
    CANCEL_WORKFLOW = "CANCEL_WORKFLOW"
```

### 4.3 Server Router

Add to `src/nerve/server/server.py`:

```python
class Server:
    def __init__(self, ...):
        ...
        self._workflow_handler = WorkflowHandler(
            session_registry=self._session_registry,
            event_sink=self._event_sink,
        )

    async def _handle_command(self, command: Command) -> Response:
        ...
        match command.type:
            ...
            # Workflow commands
            case CommandType.EXECUTE_WORKFLOW:
                result = await self._workflow_handler.execute_workflow(params)
            case CommandType.LIST_WORKFLOWS:
                result = await self._workflow_handler.list_workflows(params)
            case CommandType.GET_WORKFLOW_RUN:
                result = await self._workflow_handler.get_workflow_run(params)
            case CommandType.LIST_WORKFLOW_RUNS:
                result = await self._workflow_handler.list_workflow_runs(params)
            case CommandType.ANSWER_GATE:
                result = await self._workflow_handler.answer_gate(params)
            case CommandType.CANCEL_WORKFLOW:
                result = await self._workflow_handler.cancel_workflow(params)
```

---

## 5. Commander Integration

### 5.1 Workflow Execution Syntax

In Commander, workflows are invoked with `%` prefix:

```
%workflow_id input text here...
```

Example:
```
%code_review Here is my Python function...
```

### 5.2 Commander Parser Changes

Add to `src/nerve/commander/parser.py`:

```python
def parse_input(text: str) -> ParsedInput:
    """Parse Commander input line.

    Patterns:
        @node_id text     -> Execute node
        #graph_id text    -> Execute graph
        %workflow_id text -> Execute workflow (NEW)
        ::ref             -> History reference
        /command          -> Internal command
        other             -> Direct input to current target
    """
    text = text.strip()

    if text.startswith("%"):
        # Workflow execution
        parts = text[1:].split(None, 1)
        workflow_id = parts[0]
        input_text = parts[1] if len(parts) > 1 else ""
        return ParsedInput(
            type=InputType.WORKFLOW,
            target=workflow_id,
            text=input_text,
        )

    # ... existing parsing ...
```

### 5.3 Workflow Controller

```python
# src/nerve/commander/workflow_controller.py

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

if TYPE_CHECKING:
    from nerve.client import Client


class WorkflowController:
    """Controls workflow execution and rendering in Commander.

    Handles:
        - Starting workflow execution
        - Rendering events in real-time
        - Collecting gate input
        - Displaying results
    """

    def __init__(self, client: Client, console: Console) -> None:
        self._client = client
        self._console = console
        self._current_run_id: str | None = None
        self._events: list[dict] = []

    async def execute(
        self,
        session_id: str,
        workflow_id: str,
        input: str,
    ) -> None:
        """Execute a workflow with live rendering."""

        # Start workflow
        result = await self._client.send_command(
            Command(
                type=CommandType.EXECUTE_WORKFLOW,
                params={
                    "session_id": session_id,
                    "workflow_id": workflow_id,
                    "input": input,
                    "wait": False,  # Don't block - we'll poll
                },
            )
        )

        if not result.success:
            self._console.print(f"[red]Error: {result.error}[/red]")
            return

        self._current_run_id = result.data["run_id"]
        self._console.print(f"[dim]Started workflow run: {self._current_run_id}[/dim]")

        # Event loop - poll for updates and handle gates
        await self._run_event_loop()

    async def _run_event_loop(self) -> None:
        """Main event loop for workflow execution."""
        while True:
            # Get current run status
            result = await self._client.send_command(
                Command(
                    type=CommandType.GET_WORKFLOW_RUN,
                    params={
                        "session_id": self._client.current_session,
                        "run_id": self._current_run_id,
                    },
                )
            )

            if not result.success:
                self._console.print(f"[red]Error: {result.error}[/red]")
                return

            run_info = result.data["run"]
            state = run_info["state"]

            # Handle different states
            if state == "completed":
                self._console.print(f"[green]Workflow completed[/green]")
                self._console.print(f"Result: {run_info['result']}")
                return

            elif state == "failed":
                self._console.print(f"[red]Workflow failed: {run_info['error']}[/red]")
                return

            elif state == "cancelled":
                self._console.print(f"[yellow]Workflow cancelled[/yellow]")
                return

            elif state == "waiting":
                # Handle gate
                gate = run_info["pending_gate"]
                await self._handle_gate(gate)

            else:
                # Still running - poll again
                await asyncio.sleep(0.1)

    async def _handle_gate(self, gate: dict) -> None:
        """Handle a pending gate."""
        prompt = gate["prompt"]
        choices = gate.get("choices")

        # Display prompt
        if choices:
            self._console.print(f"\n[bold]{prompt}[/bold]")
            for i, choice in enumerate(choices, 1):
                self._console.print(f"  {i}. {choice}")
            answer = input("> ").strip()

            # Convert number to choice if needed
            if answer.isdigit():
                idx = int(answer) - 1
                if 0 <= idx < len(choices):
                    answer = choices[idx]
        else:
            self._console.print(f"\n[bold]{prompt}[/bold]")
            answer = input("> ").strip()

        # Send answer
        result = await self._client.send_command(
            Command(
                type=CommandType.ANSWER_GATE,
                params={
                    "session_id": self._client.current_session,
                    "run_id": self._current_run_id,
                    "answer": answer,
                },
            )
        )

        if not result.success:
            self._console.print(f"[red]Error: {result.error}[/red]")
```

### 5.4 Event Streaming (Future Enhancement)

For real-time event streaming, the server can push events via WebSocket or SSE. This is optional for MVP - the polling approach above works for initial implementation.

```python
# Future: src/nerve/server/events/stream.py

class EventStream:
    """Server-sent event stream for workflow events.

    Clients can subscribe to events for specific runs:
        GET /events/workflow/{run_id}

    Events are pushed as SSE:
        event: node_started
        data: {"node_id": "reviewer", "timestamp": "..."}

        event: gate_waiting
        data: {"prompt": "Approve?", "choices": ["yes", "no"]}
    """
    pass
```

---

## 6. File Structure

```
src/nerve/core/workflow/
├── __init__.py           # Exports: Workflow, WorkflowContext, WorkflowRun, WorkflowState
├── workflow.py           # Workflow class
├── context.py            # WorkflowContext class
├── run.py                # WorkflowRun class
└── events.py             # WorkflowEvent dataclass

src/nerve/server/handlers/
├── workflow_handler.py   # WorkflowHandler (NEW)
└── ...

src/nerve/commander/
├── workflow_controller.py # WorkflowController (NEW)
└── ...

tests/core/workflow/
├── test_workflow.py      # Workflow class tests
├── test_context.py       # WorkflowContext tests
├── test_run.py           # WorkflowRun tests
└── test_integration.py   # End-to-end tests
```

---

## 7. Implementation Phases

### Phase 1: Core Workflow Classes (Week 1)

**Files to create:**
- `src/nerve/core/workflow/__init__.py`
- `src/nerve/core/workflow/workflow.py`
- `src/nerve/core/workflow/context.py`
- `src/nerve/core/workflow/run.py`
- `src/nerve/core/workflow/events.py`

**Tasks:**
1. Implement `Workflow` class with registration
2. Implement `WorkflowContext` with `run()`, `gate()`, `emit()`
3. Implement `WorkflowRun` with state machine
4. Add `WorkflowEvent` dataclass
5. Unit tests for all classes

**Acceptance Criteria:**
- Can create and register workflow with session
- Can execute workflow function with context
- Gate pauses execution and resumes on answer
- Events are emitted during execution

### Phase 2: Session Integration (Week 1)

**Files to modify:**
- `src/nerve/core/session/session.py`

**Tasks:**
1. Add `workflows` dict to Session
2. Add `_workflow_runs` dict to Session
3. Implement `validate_unique_id()` method
4. Add workflow-related methods: `get_workflow()`, `list_workflows()`, etc.
5. Update tests

**Acceptance Criteria:**
- Workflows register with session on creation
- IDs validated across nodes, graphs, workflows
- Can query workflows and runs from session

### Phase 3: Server Handler (Week 2)

**Files to create:**
- `src/nerve/server/handlers/workflow_handler.py`

**Files to modify:**
- `src/nerve/server/protocol.py` (add command types)
- `src/nerve/server/server.py` (add routing)

**Tasks:**
1. Implement `WorkflowHandler` with all methods
2. Add command types to protocol
3. Wire up routing in server
4. Integration tests

**Acceptance Criteria:**
- Can execute workflow via command
- Can query workflow status
- Can answer gates via command
- Can cancel running workflows

### Phase 4: Commander Integration (Week 2)

**Files to create:**
- `src/nerve/commander/workflow_controller.py`

**Files to modify:**
- `src/nerve/commander/parser.py` (add `%` prefix)
- `src/nerve/commander/repl.py` (integrate controller)

**Tasks:**
1. Add workflow parsing (`%workflow_id`)
2. Implement `WorkflowController`
3. Handle gate input in REPL
4. Display workflow events

**Acceptance Criteria:**
- Can execute workflow with `%workflow_id input`
- Gates prompt for input in Commander
- Events display in real-time
- Results shown on completion

### Phase 5: Documentation & Examples (Week 3)

**Files to create:**
- `examples/workflows/basic_workflow.py`
- `examples/workflows/code_review_workflow.py`

**Tasks:**
1. Create example workflows
2. Update README with workflow documentation
3. Add docstrings to all public APIs

---

## 8. Testing Strategy

### Unit Tests

```python
# tests/core/workflow/test_workflow.py

class TestWorkflow:
    def test_creates_and_registers(self):
        session = Session(name="test")

        async def my_fn(ctx):
            return "done"

        workflow = Workflow(id="test", session=session, fn=my_fn)

        assert "test" in session.workflows
        assert session.workflows["test"] is workflow

    def test_duplicate_id_raises(self):
        session = Session(name="test")
        Workflow(id="test", session=session, fn=lambda ctx: None)

        with pytest.raises(ValueError, match="conflicts"):
            Workflow(id="test", session=session, fn=lambda ctx: None)

    def test_id_collision_with_node(self):
        session = Session(name="test")
        BashNode(id="runner", session=session)

        with pytest.raises(ValueError, match="conflicts with existing node"):
            Workflow(id="runner", session=session, fn=lambda ctx: None)


# tests/core/workflow/test_context.py

class TestWorkflowContext:
    @pytest.mark.asyncio
    async def test_run_executes_node(self):
        session = Session(name="test")
        FunctionNode(
            id="echo",
            session=session,
            fn=lambda ctx: {"output": ctx.input.upper()},
        )

        ctx = WorkflowContext(session=session, input="test")
        result = await ctx.run("echo", "hello")

        assert result["output"] == "HELLO"

    @pytest.mark.asyncio
    async def test_run_unknown_node_raises(self):
        session = Session(name="test")
        ctx = WorkflowContext(session=session, input="test")

        with pytest.raises(ValueError, match="not found"):
            await ctx.run("nonexistent", "input")


# tests/core/workflow/test_run.py

class TestWorkflowRun:
    @pytest.mark.asyncio
    async def test_simple_workflow_completes(self):
        session = Session(name="test")

        async def simple(ctx):
            return "done"

        workflow = Workflow(id="simple", session=session, fn=simple)
        run = WorkflowRun(workflow=workflow, input="test")

        await run.start()
        result = await run.wait()

        assert result == "done"
        assert run.state == WorkflowState.COMPLETED

    @pytest.mark.asyncio
    async def test_gate_pauses_execution(self):
        session = Session(name="test")
        gate_reached = asyncio.Event()

        async def with_gate(ctx):
            gate_reached.set()
            answer = await ctx.gate("Continue?")
            return f"answered: {answer}"

        workflow = Workflow(id="gated", session=session, fn=with_gate)
        run = WorkflowRun(workflow=workflow, input="test")

        await run.start()
        await gate_reached.wait()

        assert run.state == WorkflowState.WAITING
        assert run.pending_gate is not None

        run.answer_gate("yes")
        result = await run.wait()

        assert result == "answered: yes"
```

### Integration Tests

```python
# tests/core/workflow/test_integration.py

class TestWorkflowIntegration:
    @pytest.mark.asyncio
    async def test_workflow_with_multiple_nodes(self):
        session = Session(name="test")

        # Create nodes
        FunctionNode(
            id="step1",
            session=session,
            fn=lambda ctx: {"output": f"step1({ctx.input})"},
        )
        FunctionNode(
            id="step2",
            session=session,
            fn=lambda ctx: {"output": f"step2({ctx.input})"},
        )

        # Create workflow
        async def pipeline(ctx):
            r1 = await ctx.run("step1", ctx.input)
            r2 = await ctx.run("step2", r1["output"])
            return r2["output"]

        Workflow(id="pipeline", session=session, fn=pipeline)

        # Execute
        run = WorkflowRun(
            workflow=session.get_workflow("pipeline"),
            input="hello",
        )
        await run.start()
        result = await run.wait()

        assert result == "step2(step1(hello))"

    @pytest.mark.asyncio
    async def test_workflow_with_loop(self):
        session = Session(name="test")

        counter = {"value": 0}

        FunctionNode(
            id="increment",
            session=session,
            fn=lambda ctx: {"output": counter.__setitem__("value", counter["value"] + 1) or counter["value"]},
        )

        async def loop_workflow(ctx):
            target = ctx.input
            while counter["value"] < target:
                await ctx.run("increment", None)
            return counter["value"]

        Workflow(id="loop", session=session, fn=loop_workflow)

        run = WorkflowRun(
            workflow=session.get_workflow("loop"),
            input=5,
        )
        await run.start()
        result = await run.wait()

        assert result == 5
```

---

## 9. Success Criteria

### MVP (Phases 1-4)

1. **Workflow Registration**: Users can define async functions and register them as workflows
2. **Workflow Execution**: Workflows execute nodes via `ctx.run()`
3. **Gate Support**: `ctx.gate()` pauses execution and waits for input
4. **Event Emission**: `ctx.emit()` sends events (logged, not yet streamed)
5. **Server Commands**: All workflow commands implemented
6. **Commander Integration**: `%workflow_id` syntax works, gates prompt for input

### Full Release

1. **Event Streaming**: Real-time events via WebSocket/SSE
2. **Rich TUI**: Live workflow visualization in Commander
3. **Persistence**: Workflow runs survive server restart
4. **Timeout Handling**: Graceful timeout for gates and node execution

---

## 10. Open Questions

1. **Workflow Persistence**: Should workflow definitions be serializable for remote registration?
   - Currently: Python functions only, must be registered in server process
   - Future: Could add DSL or serializable workflow definitions

2. **Nested Workflows**: Should workflows be able to call other workflows?
   - Recommendation: Yes, via `ctx.run_workflow(workflow_id, input)`
   - Deferred to post-MVP

3. **Parallel Execution**: Should workflows support parallel node execution?
   - Could add `ctx.run_parallel([("node1", input1), ("node2", input2)])`
   - Deferred to post-MVP

4. **State Persistence**: Should `ctx.state` persist across server restarts?
   - MVP: No, in-memory only
   - Future: Could add optional state persistence
