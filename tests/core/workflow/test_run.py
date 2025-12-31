"""Tests for WorkflowRun class."""

from __future__ import annotations

import asyncio

import pytest

from nerve.core.nodes.base import FunctionNode
from nerve.core.session import Session
from nerve.core.workflow import (
    Workflow,
    WorkflowContext,
    WorkflowRun,
    WorkflowState,
)


class TestWorkflowRunBasic:
    """Basic WorkflowRun tests."""

    @pytest.mark.asyncio
    async def test_simple_workflow_completes(self):
        """Simple workflow completes successfully."""
        session = Session(name="test")

        async def simple(ctx: WorkflowContext) -> str:
            return "done"

        workflow = Workflow(id="simple", session=session, fn=simple)
        run = WorkflowRun(workflow=workflow, input="test")

        await run.start()
        result = await run.wait()

        assert result == "done"
        assert run.state == WorkflowState.COMPLETED
        assert run.error is None

    @pytest.mark.asyncio
    async def test_workflow_with_input(self):
        """Workflow receives input correctly."""
        session = Session(name="test")

        async def echo(ctx: WorkflowContext) -> str:
            return f"got: {ctx.input}"

        workflow = Workflow(id="echo", session=session, fn=echo)
        run = WorkflowRun(workflow=workflow, input="hello")

        await run.start()
        result = await run.wait()

        assert result == "got: hello"

    @pytest.mark.asyncio
    async def test_workflow_with_params(self):
        """Workflow receives params correctly."""
        session = Session(name="test")

        async def use_params(ctx: WorkflowContext) -> str:
            return f"prefix={ctx.params.get('prefix')}"

        workflow = Workflow(id="params", session=session, fn=use_params)
        run = WorkflowRun(workflow=workflow, input="test", params={"prefix": ">>>"})

        await run.start()
        result = await run.wait()

        assert result == "prefix=>>>"

    @pytest.mark.asyncio
    async def test_workflow_with_state(self):
        """Workflow can use state dict."""
        session = Session(name="test")

        async def use_state(ctx: WorkflowContext) -> int:
            ctx.state["count"] = 0
            for _ in range(5):
                ctx.state["count"] += 1
            return ctx.state["count"]

        workflow = Workflow(id="state", session=session, fn=use_state)
        run = WorkflowRun(workflow=workflow, input=None)

        await run.start()
        result = await run.wait()

        assert result == 5


class TestWorkflowRunContextRun:
    """Tests for WorkflowContext.run() method."""

    @pytest.mark.asyncio
    async def test_run_executes_node(self):
        """ctx.run() executes a node."""
        session = Session(name="test")

        # FunctionNode returns a dict with output being what the function returns
        FunctionNode(
            id="echo",
            session=session,
            fn=lambda ctx: ctx.input.upper(),
        )

        async def use_node(ctx: WorkflowContext) -> str:
            result = await ctx.run("echo", "hello")
            return result["output"]

        workflow = Workflow(id="test", session=session, fn=use_node)
        run = WorkflowRun(workflow=workflow, input=None)

        await run.start()
        result = await run.wait()

        assert result == "HELLO"

    @pytest.mark.asyncio
    async def test_run_unknown_node_raises(self):
        """ctx.run() raises for unknown node."""
        session = Session(name="test")

        async def use_missing(ctx: WorkflowContext) -> str:
            await ctx.run("nonexistent", "input")
            return "never reached"

        workflow = Workflow(id="test", session=session, fn=use_missing)
        run = WorkflowRun(workflow=workflow, input=None)

        await run.start()

        with pytest.raises(Exception, match="not found"):
            await run.wait()

        assert run.state == WorkflowState.FAILED

    @pytest.mark.asyncio
    async def test_run_multiple_nodes(self):
        """ctx.run() can execute multiple nodes in sequence."""
        session = Session(name="test")

        # FunctionNode returns a dict with output being what the function returns
        FunctionNode(
            id="double",
            session=session,
            fn=lambda ctx: ctx.input * 2,
        )
        FunctionNode(
            id="add10",
            session=session,
            fn=lambda ctx: ctx.input + 10,
        )

        async def pipeline(ctx: WorkflowContext) -> int:
            r1 = await ctx.run("double", ctx.input)
            r2 = await ctx.run("add10", r1["output"])
            return r2["output"]

        workflow = Workflow(id="test", session=session, fn=pipeline)
        run = WorkflowRun(workflow=workflow, input=5)

        await run.start()
        result = await run.wait()

        assert result == 20  # (5 * 2) + 10


class TestWorkflowRunGate:
    """Tests for WorkflowContext.gate() method."""

    @pytest.mark.asyncio
    async def test_gate_pauses_execution(self):
        """ctx.gate() pauses execution until answered."""
        session = Session(name="test")
        gate_reached = asyncio.Event()

        async def with_gate(ctx: WorkflowContext) -> str:
            gate_reached.set()
            answer = await ctx.gate("Continue?")
            return f"answered: {answer}"

        workflow = Workflow(id="gated", session=session, fn=with_gate)
        run = WorkflowRun(workflow=workflow, input=None)
        session.register_workflow_run(run)

        await run.start()

        # Wait for gate to be reached
        await asyncio.wait_for(gate_reached.wait(), timeout=1.0)

        # Should be in WAITING state
        assert run.state == WorkflowState.WAITING
        assert run.pending_gate is not None
        assert run.pending_gate.prompt == "Continue?"

        # Answer the gate
        run.answer_gate("yes")

        # Wait for completion
        result = await asyncio.wait_for(run.wait(), timeout=1.0)

        assert result == "answered: yes"
        assert run.state == WorkflowState.COMPLETED

    @pytest.mark.asyncio
    async def test_gate_with_choices(self):
        """ctx.gate() can specify valid choices."""
        session = Session(name="test")
        gate_reached = asyncio.Event()

        async def with_choices(ctx: WorkflowContext) -> str:
            gate_reached.set()
            answer = await ctx.gate("Pick one:", choices=["a", "b", "c"])
            return f"picked: {answer}"

        workflow = Workflow(id="choices", session=session, fn=with_choices)
        run = WorkflowRun(workflow=workflow, input=None)
        session.register_workflow_run(run)

        await run.start()
        await asyncio.wait_for(gate_reached.wait(), timeout=1.0)

        assert run.pending_gate is not None
        assert run.pending_gate.choices == ["a", "b", "c"]

        # Invalid choice raises
        with pytest.raises(ValueError, match="Invalid choice"):
            run.answer_gate("d")

        # Valid choice works
        run.answer_gate("b")
        result = await asyncio.wait_for(run.wait(), timeout=1.0)
        assert result == "picked: b"

    @pytest.mark.asyncio
    async def test_answer_gate_no_pending_raises(self):
        """answer_gate() raises if no gate pending."""
        session = Session(name="test")

        async def no_gate(ctx: WorkflowContext) -> str:
            return "done"

        workflow = Workflow(id="test", session=session, fn=no_gate)
        run = WorkflowRun(workflow=workflow, input=None)

        with pytest.raises(RuntimeError, match="No gate pending"):
            run.answer_gate("answer")


class TestWorkflowRunCancel:
    """Tests for workflow cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_running_workflow(self):
        """cancel() stops a running workflow."""
        session = Session(name="test")
        started = asyncio.Event()

        async def long_running(ctx: WorkflowContext) -> str:
            started.set()
            await asyncio.sleep(10)  # Would take forever without cancel
            return "done"

        workflow = Workflow(id="long", session=session, fn=long_running)
        run = WorkflowRun(workflow=workflow, input=None)

        await run.start()
        await asyncio.wait_for(started.wait(), timeout=1.0)

        # Cancel
        await run.cancel()

        assert run.state == WorkflowState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_waiting_workflow(self):
        """cancel() stops a workflow waiting on gate."""
        session = Session(name="test")
        gate_reached = asyncio.Event()

        async def with_gate(ctx: WorkflowContext) -> str:
            gate_reached.set()
            answer = await ctx.gate("Continue?")
            return answer

        workflow = Workflow(id="gated", session=session, fn=with_gate)
        run = WorkflowRun(workflow=workflow, input=None)
        session.register_workflow_run(run)

        await run.start()
        await asyncio.wait_for(gate_reached.wait(), timeout=1.0)

        assert run.state == WorkflowState.WAITING

        # Cancel
        await run.cancel()

        assert run.state == WorkflowState.CANCELLED


class TestWorkflowRunEvents:
    """Tests for workflow event emission."""

    @pytest.mark.asyncio
    async def test_events_emitted(self):
        """Events are emitted during workflow execution."""
        session = Session(name="test")
        events = []

        async def capture_event(event):
            events.append(event)

        async def simple(ctx: WorkflowContext) -> str:
            ctx.emit("custom_event", {"key": "value"})
            return "done"

        workflow = Workflow(id="test", session=session, fn=simple)
        run = WorkflowRun(workflow=workflow, input=None, event_callback=capture_event)

        await run.start()
        await run.wait()

        # Should have workflow_started, custom_event, workflow_completed
        event_types = [e.event_type for e in events]
        assert "workflow_started" in event_types
        assert "custom_event" in event_types
        assert "workflow_completed" in event_types


class TestWorkflowRunInfo:
    """Tests for WorkflowRun info methods."""

    @pytest.mark.asyncio
    async def test_to_info(self):
        """to_info returns serializable WorkflowRunInfo."""
        session = Session(name="test")

        async def simple(ctx: WorkflowContext) -> str:
            return "done"

        workflow = Workflow(id="test", session=session, fn=simple)
        run = WorkflowRun(workflow=workflow, input="test")

        # Before start
        info = run.to_info()
        assert info.run_id == run.run_id
        assert info.workflow_id == "test"
        assert info.state == WorkflowState.PENDING

        # After completion
        await run.start()
        await run.wait()

        info = run.to_info()
        assert info.state == WorkflowState.COMPLETED
        assert info.result == "done"

        # to_dict should be JSON-serializable
        d = info.to_dict()
        assert d["run_id"] == run.run_id
        assert d["state"] == "completed"


class TestWorkflowRunContextRunGraph:
    """Tests for WorkflowContext.run_graph() method."""

    @pytest.mark.asyncio
    async def test_run_graph_executes_graph(self):
        """ctx.run_graph() executes a graph."""
        from nerve.core.nodes.graph import Graph

        session = Session(name="test")

        # Create nodes for the graph
        FunctionNode(
            id="step1",
            session=session,
            fn=lambda ctx: f"processed_{ctx.input}",
        )

        # Create a graph with a single step
        graph = Graph(id="my_pipeline", session=session)
        graph.add_step_ref(node_id="step1", step_id="process", input="data")

        async def use_graph(ctx: WorkflowContext) -> str:
            result = await ctx.run_graph("my_pipeline")
            return result["attributes"]["steps"]["process"]["output"]

        workflow = Workflow(id="test", session=session, fn=use_graph)
        run = WorkflowRun(workflow=workflow, input=None)

        await run.start()
        result = await run.wait()

        assert result == "processed_data"

    @pytest.mark.asyncio
    async def test_run_graph_unknown_graph_raises(self):
        """ctx.run_graph() raises for unknown graph."""
        session = Session(name="test")

        async def use_missing_graph(ctx: WorkflowContext) -> str:
            await ctx.run_graph("nonexistent")
            return "never reached"

        workflow = Workflow(id="test", session=session, fn=use_missing_graph)
        run = WorkflowRun(workflow=workflow, input=None)

        await run.start()

        with pytest.raises(Exception, match="not found"):
            await run.wait()

        assert run.state == WorkflowState.FAILED

    @pytest.mark.asyncio
    async def test_run_graph_with_input(self):
        """ctx.run_graph() passes input to graph."""
        from nerve.core.nodes.graph import Graph

        session = Session(name="test")

        # Create node that uses input
        FunctionNode(
            id="upper",
            session=session,
            fn=lambda ctx: ctx.input.upper() if ctx.input else "NO_INPUT",
        )

        # Create graph that uses context input
        # Graph input is passed under "input" key in input_fn's upstream dict
        graph = Graph(id="upper_pipeline", session=session)
        graph.add_step_ref(
            node_id="upper",
            step_id="process",
            input_fn=lambda upstream: upstream.get("input", ""),
        )

        async def use_graph(ctx: WorkflowContext) -> str:
            result = await ctx.run_graph("upper_pipeline", "hello world")
            return result["attributes"]["steps"]["process"]["output"]

        workflow = Workflow(id="test", session=session, fn=use_graph)
        run = WorkflowRun(workflow=workflow, input=None)

        await run.start()
        result = await run.wait()

        assert result == "HELLO WORLD"

    @pytest.mark.asyncio
    async def test_run_graph_multi_step(self):
        """ctx.run_graph() executes multi-step graph."""
        from nerve.core.nodes.graph import Graph

        session = Session(name="test")

        # Create nodes
        FunctionNode(
            id="double",
            session=session,
            fn=lambda ctx: ctx.input * 2,
        )
        FunctionNode(
            id="add10",
            session=session,
            fn=lambda ctx: ctx.input + 10,
        )

        # Create graph with two chained steps
        graph = Graph(id="math_pipeline", session=session)
        graph.add_step_ref(node_id="double", step_id="step1", input=5)
        graph.add_step_ref(
            node_id="add10",
            step_id="step2",
            input_fn=lambda upstream: upstream["step1"]["output"],
            depends_on=["step1"],
        )

        async def use_graph(ctx: WorkflowContext) -> int:
            result = await ctx.run_graph("math_pipeline")
            return result["attributes"]["steps"]["step2"]["output"]

        workflow = Workflow(id="test", session=session, fn=use_graph)
        run = WorkflowRun(workflow=workflow, input=None)

        await run.start()
        result = await run.wait()

        assert result == 20  # (5 * 2) + 10

    @pytest.mark.asyncio
    async def test_run_graph_emits_events(self):
        """ctx.run_graph() emits graph_started and graph_completed events."""
        from nerve.core.nodes.graph import Graph

        session = Session(name="test")
        events = []

        async def capture_event(event) -> None:
            events.append(event)

        # Create node and graph
        FunctionNode(
            id="echo",
            session=session,
            fn=lambda _: "done",
        )
        graph = Graph(id="test_graph", session=session)
        graph.add_step_ref(node_id="echo", step_id="step1")

        async def use_graph(ctx: WorkflowContext) -> str:
            result = await ctx.run_graph("test_graph")
            return result["attributes"]["steps"]["step1"]["output"]

        workflow = Workflow(id="test", session=session, fn=use_graph)
        run = WorkflowRun(workflow=workflow, input=None, event_callback=capture_event)

        await run.start()
        await run.wait()

        # Check events
        event_types = [e.event_type for e in events]
        assert "graph_started" in event_types
        assert "graph_completed" in event_types

        # Verify graph_started event data
        graph_started = next(e for e in events if e.event_type == "graph_started")
        assert graph_started.data["graph_id"] == "test_graph"

        # Verify graph_completed event data
        graph_completed = next(e for e in events if e.event_type == "graph_completed")
        assert graph_completed.data["graph_id"] == "test_graph"
        assert graph_completed.data["success"] is True


class TestWorkflowRunContextRunWorkflow:
    """Tests for WorkflowContext.run_workflow() method."""

    @pytest.mark.asyncio
    async def test_run_workflow_executes_nested(self):
        """ctx.run_workflow() executes a nested workflow."""
        session = Session(name="test")

        # Create a simple child workflow
        async def child_workflow(ctx: WorkflowContext) -> str:
            return f"processed: {ctx.input}"

        Workflow(id="child", session=session, fn=child_workflow)

        # Create parent workflow that calls child
        async def parent_workflow(ctx: WorkflowContext) -> str:
            result = await ctx.run_workflow("child", ctx.input)
            return f"parent got: {result}"

        workflow = Workflow(id="parent", session=session, fn=parent_workflow)
        run = WorkflowRun(workflow=workflow, input="hello")

        await run.start()
        result = await run.wait()

        assert result == "parent got: processed: hello"

    @pytest.mark.asyncio
    async def test_run_workflow_unknown_workflow_raises(self):
        """ctx.run_workflow() raises for unknown workflow."""
        session = Session(name="test")

        async def use_missing_workflow(ctx: WorkflowContext) -> str:
            await ctx.run_workflow("nonexistent")
            return "never reached"

        workflow = Workflow(id="test", session=session, fn=use_missing_workflow)
        run = WorkflowRun(workflow=workflow, input=None)

        await run.start()

        with pytest.raises(Exception, match="not found"):
            await run.wait()

        assert run.state == WorkflowState.FAILED

    @pytest.mark.asyncio
    async def test_run_workflow_chain(self):
        """ctx.run_workflow() can chain multiple workflows."""
        session = Session(name="test")

        # Step 1: Double
        async def double_workflow(ctx: WorkflowContext) -> int:
            return ctx.input * 2

        Workflow(id="double", session=session, fn=double_workflow)

        # Step 2: Add 10
        async def add10_workflow(ctx: WorkflowContext) -> int:
            return ctx.input + 10

        Workflow(id="add10", session=session, fn=add10_workflow)

        # Parent chains them together
        async def pipeline(ctx: WorkflowContext) -> int:
            doubled = await ctx.run_workflow("double", ctx.input)
            result = await ctx.run_workflow("add10", doubled)
            return result

        workflow = Workflow(id="pipeline", session=session, fn=pipeline)
        run = WorkflowRun(workflow=workflow, input=5)

        await run.start()
        result = await run.wait()

        assert result == 20  # (5 * 2) + 10

    @pytest.mark.asyncio
    async def test_run_workflow_with_params(self):
        """ctx.run_workflow() passes params to nested workflow."""
        session = Session(name="test")

        async def child_with_params(ctx: WorkflowContext) -> str:
            prefix = ctx.params.get("prefix", "")
            return f"{prefix}{ctx.input}"

        Workflow(id="child", session=session, fn=child_with_params)

        async def parent(ctx: WorkflowContext) -> str:
            return await ctx.run_workflow(
                "child",
                ctx.input,
                params={"prefix": ">>>"},
            )

        workflow = Workflow(id="parent", session=session, fn=parent)
        run = WorkflowRun(workflow=workflow, input="test")

        await run.start()
        result = await run.wait()

        assert result == ">>>test"

    @pytest.mark.asyncio
    async def test_run_workflow_emits_events(self):
        """ctx.run_workflow() emits nested_workflow events."""
        session = Session(name="test")
        events = []

        async def capture_event(event) -> None:
            events.append(event)

        async def child(ctx: WorkflowContext) -> str:
            return "done"

        Workflow(id="child", session=session, fn=child)

        async def parent(ctx: WorkflowContext) -> str:
            return await ctx.run_workflow("child", "input")

        workflow = Workflow(id="parent", session=session, fn=parent)
        run = WorkflowRun(workflow=workflow, input=None, event_callback=capture_event)

        await run.start()
        await run.wait()

        # Check events
        event_types = [e.event_type for e in events]
        assert "nested_workflow_started" in event_types
        assert "nested_workflow_completed" in event_types

        # Verify nested_workflow_started event data
        started = next(e for e in events if e.event_type == "nested_workflow_started")
        assert started.data["workflow_id"] == "child"

    @pytest.mark.asyncio
    async def test_run_workflow_nested_error_propagates(self):
        """Errors in nested workflow propagate to parent."""
        session = Session(name="test")

        async def failing_child(ctx: WorkflowContext) -> str:
            raise ValueError("Child failed!")

        Workflow(id="failing", session=session, fn=failing_child)

        async def parent(ctx: WorkflowContext) -> str:
            return await ctx.run_workflow("failing", None)

        workflow = Workflow(id="parent", session=session, fn=parent)
        run = WorkflowRun(workflow=workflow, input=None)

        await run.start()

        with pytest.raises(Exception, match="Child failed"):
            await run.wait()

        assert run.state == WorkflowState.FAILED

    @pytest.mark.asyncio
    async def test_run_workflow_composition_with_nodes(self):
        """Workflows can combine run_workflow with run (nodes)."""
        session = Session(name="test")

        # Create a node
        FunctionNode(
            id="uppercase",
            session=session,
            fn=lambda ctx: ctx.input.upper(),
        )

        # Create a child workflow
        async def child(ctx: WorkflowContext) -> str:
            return f"[{ctx.input}]"

        Workflow(id="child", session=session, fn=child)

        # Parent uses both
        async def parent(ctx: WorkflowContext) -> str:
            # First call a node
            node_result = await ctx.run("uppercase", ctx.input)
            # Then call a workflow
            workflow_result = await ctx.run_workflow("child", node_result["output"])
            return workflow_result

        workflow = Workflow(id="parent", session=session, fn=parent)
        run = WorkflowRun(workflow=workflow, input="hello")

        await run.start()
        result = await run.wait()

        assert result == "[HELLO]"
