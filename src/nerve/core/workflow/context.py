"""WorkflowContext - context passed to workflow functions.

WorkflowContext provides helpers for executing nodes, waiting for human input,
and emitting events to Commander.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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

            # Execute a graph (DAG pipeline)
            pipeline_result = await ctx.run_graph("my_pipeline", result["output"])

            # Execute another workflow (composition)
            final = await ctx.run_workflow("post_process", pipeline_result["output"])

            # Store state for later iterations
            ctx.state["analysis"] = final

            # Wait for human decision
            decision = await ctx.gate("Approve analysis?")

            # Emit custom event
            ctx.emit("decision_made", {"decision": decision})

            return pipeline_result["output"]
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

        # Emit node_started event with input for TUI step tracking
        self.emit("node_started", {"node_id": node_id, "input": str(input) if input else ""})

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
        except TimeoutError:
            self.emit("node_timeout", {"node_id": node_id, "timeout": timeout})
            raise
        except Exception as e:
            self.emit("node_error", {"node_id": node_id, "error": str(e)})
            raise

        # Emit node_completed event with output for TUI step tracking
        output = result.get("output", result.get("stdout", ""))
        self.emit(
            "node_completed",
            {
                "node_id": node_id,
                "success": result.get("success", False),
                "output": str(output) if output else "",
            },
        )

        return dict(result)

    async def run_graph(
        self,
        graph_id: str,
        input: Any = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute a graph (DAG) and return its result.

        Args:
            graph_id: ID of graph to execute
            input: Input to pass to graph (optional)
            timeout: Optional timeout in seconds

        Returns:
            Graph execution result dict with keys:
            - success: bool
            - output: Any (from the final step)
            - error: str (if not success)
            - attributes: dict (including step results)

        Raises:
            ValueError: If graph_id not found in session
            asyncio.TimeoutError: If timeout exceeded

        Example:
            # Execute a pipeline as a single step
            result = await ctx.run_graph("analysis_pipeline", document)
            if result["success"]:
                analysis = result["output"]

            # Chain with other operations
            step1 = await ctx.run("preprocessor", ctx.input)
            step2 = await ctx.run_graph("main_pipeline", step1["output"])
            step3 = await ctx.run("postprocessor", step2["output"])
        """
        graph = self.session.get_graph(graph_id)
        if graph is None:
            raise ValueError(f"Graph '{graph_id}' not found in session")

        # Emit graph_started event for TUI step tracking
        self.emit("graph_started", {"graph_id": graph_id, "input": str(input) if input else ""})

        # Create execution context
        exec_ctx = ExecutionContext(
            session=self.session,
            input=input,
        )

        # Execute with optional timeout
        try:
            if timeout:
                result = await asyncio.wait_for(
                    graph.execute(exec_ctx),
                    timeout=timeout,
                )
            else:
                result = await graph.execute(exec_ctx)
        except TimeoutError:
            self.emit("graph_timeout", {"graph_id": graph_id, "timeout": timeout})
            raise
        except Exception as e:
            self.emit("graph_error", {"graph_id": graph_id, "error": str(e)})
            raise

        # Emit graph_completed event for TUI step tracking
        output = result.get("output", "")
        self.emit(
            "graph_completed",
            {
                "graph_id": graph_id,
                "success": result.get("success", False),
                "output": str(output) if output else "",
            },
        )

        return dict(result)

    async def run_workflow(
        self,
        workflow_id: str,
        input: Any = None,
        timeout: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute another workflow and return its result.

        Enables workflow composition - building complex workflows from simpler ones.
        The nested workflow runs to completion before returning.

        Args:
            workflow_id: ID of workflow to execute
            input: Input to pass to workflow (optional)
            timeout: Optional timeout in seconds
            params: Additional parameters for the nested workflow's context

        Returns:
            The return value of the nested workflow function.

        Raises:
            ValueError: If workflow_id not found in session
            asyncio.TimeoutError: If timeout exceeded
            Exception: If nested workflow fails

        Example:
            # Compose workflows
            async def pipeline(ctx: WorkflowContext) -> str:
                # Run summarization workflow
                summary = await ctx.run_workflow("summarize", ctx.input)

                # Run translation workflow on the summary
                translated = await ctx.run_workflow("translate", summary)

                return translated

            # Chain with gates
            async def review_pipeline(ctx: WorkflowContext) -> str:
                result = await ctx.run_workflow("analyze", ctx.input)

                decision = await ctx.gate("Approve analysis?")
                if decision == "yes":
                    return await ctx.run_workflow("publish", result)
                return "Rejected"
        """
        # Import here to avoid circular dependency
        from nerve.core.workflow.run import WorkflowRun

        workflow = self.session.get_workflow(workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow '{workflow_id}' not found in session")

        # Emit nested workflow started event for TUI step tracking
        self.emit(
            "nested_workflow_started",
            {"workflow_id": workflow_id, "input": str(input) if input else ""},
        )

        # Create child run with parent's event forwarding
        # Events from child will be emitted to parent's event stream
        from nerve.core.workflow.events import WorkflowEvent
        from nerve.core.workflow.run import EventCallback

        event_callback: EventCallback | None = None
        if self._run is not None:
            parent_run = self._run  # Capture for closure

            async def forward_event(event: WorkflowEvent) -> None:
                # Forward child events to parent's event stream
                parent_run._emit_event(
                    f"nested:{event.event_type}",
                    {
                        "nested_workflow_id": workflow_id,
                        "nested_run_id": event.run_id,
                        **event.data,
                    },
                )

            event_callback = forward_event

        child_run = WorkflowRun(
            workflow=workflow,
            input=input,
            params=params or {},
            event_callback=event_callback,
        )

        # Register child run with session so gates can be answered
        self.session.register_workflow_run(child_run)

        try:
            # Start and wait for completion
            await child_run.start()

            if timeout:
                result = await asyncio.wait_for(child_run.wait(), timeout=timeout)
            else:
                result = await child_run.wait()

            # Emit success event
            self.emit(
                "nested_workflow_completed",
                {
                    "workflow_id": workflow_id,
                    "run_id": child_run.run_id,
                    "success": True,
                },
            )

            return result

        except TimeoutError:
            await child_run.cancel()
            self.emit(
                "nested_workflow_timeout",
                {"workflow_id": workflow_id, "timeout": timeout},
            )
            raise

        except asyncio.CancelledError:
            await child_run.cancel()
            self.emit(
                "nested_workflow_cancelled",
                {"workflow_id": workflow_id},
            )
            raise

        except Exception as e:
            self.emit(
                "nested_workflow_error",
                {"workflow_id": workflow_id, "error": str(e)},
            )
            raise

        finally:
            # Unregister child run to prevent memory leak
            self.session.unregister_workflow_run(child_run.run_id)

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
            RuntimeError: If not attached to a WorkflowRun

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
        self.emit(
            "gate_waiting",
            {
                "gate_id": gate_id,
                "prompt": prompt,
                "choices": choices,
            },
        )

        try:
            if timeout:
                result = await asyncio.wait_for(future, timeout=timeout)
            else:
                result = await future

            self.emit(
                "gate_answered",
                {
                    "gate_id": gate_id,
                    "answer": result,
                },
            )

            return result

        except TimeoutError:
            self._run._unregister_gate(gate_id)
            self.emit("gate_timeout", {"gate_id": gate_id, "timeout": timeout})
            raise

        except asyncio.CancelledError:
            self._run._unregister_gate(gate_id)
            self.emit("gate_cancelled", {"gate_id": gate_id})
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
