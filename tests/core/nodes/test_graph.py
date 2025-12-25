"""Tests for nerve.core.nodes.graph module."""

import asyncio

import pytest

from nerve.core.nodes.base import FunctionNode
from nerve.core.nodes.cancellation import CancellationToken
from nerve.core.nodes.context import ExecutionContext
from nerve.core.nodes.graph import Graph, Step, StepEvent
from nerve.core.session.session import Session


class TestStep:
    """Tests for Step dataclass."""

    def test_requires_node_or_node_ref(self):
        """Test that Step requires either node or node_ref."""
        with pytest.raises(ValueError, match="must have either 'node' or 'node_ref'"):
            Step()

    def test_node_and_node_ref_mutually_exclusive(self):
        """Test that Step cannot have both node and node_ref."""
        session = Session(name="test")
        node = FunctionNode(id="test", session=session, fn=lambda ctx: ctx.input)
        with pytest.raises(ValueError, match="cannot have both 'node' and 'node_ref'"):
            Step(node=node, node_ref="other")

    def test_input_and_input_fn_mutually_exclusive(self):
        """Test that Step cannot have both input and input_fn."""
        session = Session(name="test")
        node = FunctionNode(id="test", session=session, fn=lambda ctx: ctx.input)
        with pytest.raises(ValueError, match="cannot have both 'input' and 'input_fn'"):
            Step(node=node, input="static", input_fn=lambda u: u)

    def test_with_node(self):
        """Test step with direct node reference."""
        session = Session(name="test")
        node = FunctionNode(id="test", session=session, fn=lambda ctx: ctx.input)
        step = Step(node=node, input="hello", depends_on=["prev"])

        assert step.node is node
        assert step.input == "hello"
        assert step.depends_on == ["prev"]

    def test_with_node_ref(self):
        """Test step with node reference by ID."""
        step = Step(node_ref="my-node", input="hello")

        assert step.node is None
        assert step.node_ref == "my-node"
        assert step.input == "hello"
        assert step.depends_on == []
        assert step.error_policy is None
        assert step.parser is None


class TestGraph:
    """Tests for Graph class."""

    def test_init(self):
        """Test graph initialization."""
        session = Session(name="test")
        graph = Graph(id="test-graph", session=session)
        assert graph.id == "test-graph"
        assert graph.persistent is False
        assert len(graph) == 0
        # Verify auto-registration
        assert "test-graph" in session.graphs

    def test_add_step(self):
        """Test adding steps."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)
        node = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="step1", input="hello")

        assert len(graph) == 1
        assert "step1" in graph.list_steps()
        step = graph.get_step("step1")
        assert step is not None
        assert step.node is node

    def test_add_step_duplicate_error(self):
        """Test duplicate step_id raises error."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)
        node = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="step1")

        with pytest.raises(ValueError, match="already exists"):
            graph.add_step(node, step_id="step1")

    def test_add_step_empty_id_error(self):
        """Test empty step_id raises error."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)
        node = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

        with pytest.raises(ValueError, match="cannot be empty"):
            graph.add_step(node, step_id="")

    def test_add_step_ref(self):
        """Test adding step with node_ref."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)

        graph.add_step_ref(node_id="registered-node", step_id="step1")

        step = graph.get_step("step1")
        assert step is not None
        assert step.node_ref == "registered-node"

    def test_chain(self):
        """Test chain method sets dependencies."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)
        node = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="a")
        graph.add_step(node, step_id="b")
        graph.add_step(node, step_id="c")

        graph.chain("a", "b", "c")

        assert "a" in graph.get_step("b").depends_on
        assert "b" in graph.get_step("c").depends_on

    def test_validate_valid_graph(self):
        """Test validate with valid graph."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)
        node = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="a")
        graph.add_step(node, step_id="b", depends_on=["a"])

        errors = graph.validate()
        assert errors == []

    def test_validate_self_dependency(self):
        """Test validate catches self-dependency."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)
        node = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="a", depends_on=["a"])

        errors = graph.validate()
        assert len(errors) == 1
        assert "depends on itself" in errors[0]

    def test_validate_missing_dependency(self):
        """Test validate catches missing dependency."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)
        node = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="a", depends_on=["nonexistent"])

        errors = graph.validate()
        assert len(errors) == 1
        assert "unknown step" in errors[0]

    # Note: Step validation for missing node/node_ref and mutually exclusive
    # input/input_fn is now done in Step.__post_init__ - see TestStep tests

    def test_execution_order(self):
        """Test execution order respects dependencies."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)
        node = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="c", depends_on=["b"])
        graph.add_step(node, step_id="b", depends_on=["a"])
        graph.add_step(node, step_id="a")

        order = graph.execution_order()
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    @pytest.mark.asyncio
    async def test_execute_simple(self):
        """Test simple graph execution."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)

        graph.add_step(
            FunctionNode(id="fn1", session=session, fn=lambda ctx: "result_a"),
            step_id="a",
        )
        graph.add_step(
            FunctionNode(id="fn2", session=session, fn=lambda ctx: f"got_{ctx.upstream['a']}"),
            step_id="b",
            depends_on=["a"],
        )

        context = ExecutionContext(session=session)
        results = await graph.execute(context)

        assert results["a"] == "result_a"
        assert results["b"] == "got_result_a"

    @pytest.mark.asyncio
    async def test_execute_with_static_input(self):
        """Test execution with static input."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)

        graph.add_step(
            FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input.upper()),
            step_id="a",
            input="hello",
        )

        context = ExecutionContext(session=session)
        results = await graph.execute(context)

        assert results["a"] == "HELLO"

    @pytest.mark.asyncio
    async def test_execute_with_input_fn(self):
        """Test execution with dynamic input_fn."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)

        graph.add_step(
            FunctionNode(id="fn1", session=session, fn=lambda ctx: {"data": "value"}),
            step_id="a",
        )
        graph.add_step(
            FunctionNode(id="fn2", session=session, fn=lambda ctx: ctx.input),
            step_id="b",
            depends_on=["a"],
            input_fn=lambda u: u["a"]["data"].upper(),
        )

        context = ExecutionContext(session=session)
        results = await graph.execute(context)

        assert results["a"] == {"data": "value"}
        assert results["b"] == "VALUE"

    @pytest.mark.asyncio
    async def test_execute_with_node_ref(self):
        """Test execution with node_ref resolved from session."""
        session = Session(name="test")
        FunctionNode(id="registered", session=session, fn=lambda ctx: "from_session")

        graph = Graph(id="test", session=session)
        graph.add_step_ref(node_id="registered", step_id="a")

        context = ExecutionContext(session=session)
        results = await graph.execute(context)

        assert results["a"] == "from_session"

    @pytest.mark.asyncio
    async def test_nested_graphs(self):
        """Test graphs containing graphs."""
        session = Session(name="test")
        inner = Graph(id="inner", session=session)
        inner.add_step(
            FunctionNode(id="inner-fn", session=session, fn=lambda ctx: "inner_result"),
            step_id="inner_step",
        )

        # Create outer graph in separate session to avoid ID conflict
        session2 = Session(name="test2")
        outer = Graph(id="outer", session=session2)
        outer.add_step(inner, step_id="nested")
        outer.add_step(
            FunctionNode(
                id="outer-fn",
                session=session2,
                fn=lambda ctx: f"got_{ctx.upstream['nested']['inner_step']}",
            ),
            step_id="after",
            depends_on=["nested"],
        )

        context = ExecutionContext(session=session2)
        results = await outer.execute(context)

        assert results["nested"]["inner_step"] == "inner_result"
        assert results["after"] == "got_inner_result"

    @pytest.mark.asyncio
    async def test_execute_stream(self):
        """Test streaming execution."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)

        graph.add_step(
            FunctionNode(id="fn1", session=session, fn=lambda ctx: "a"),
            step_id="a",
        )
        graph.add_step(
            FunctionNode(id="fn2", session=session, fn=lambda ctx: "b"),
            step_id="b",
            depends_on=["a"],
        )

        context = ExecutionContext(session=session)

        events = []
        async for event in graph.execute_stream(context):
            events.append(event)

        # Should have start and complete for each step
        start_events = [e for e in events if e.event_type == "step_start"]
        complete_events = [e for e in events if e.event_type == "step_complete"]

        assert len(start_events) == 2
        assert len(complete_events) == 2

    def test_to_info(self):
        """Test to_info method."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)
        node = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)
        graph.add_step(node, step_id="a")
        graph.add_step(node, step_id="b")

        info = graph.to_info()
        assert info.id == "test"
        assert info.node_type == "graph"
        assert info.persistent is False
        assert info.metadata["steps"] == 2

    def test_repr(self):
        """Test repr."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)
        node = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)
        graph.add_step(node, step_id="a")

        assert "test" in repr(graph)
        assert "a" in repr(graph)

    def test_collect_persistent_nodes(self):
        """Test collecting persistent nodes from graph."""

        # Create a mock persistent node
        class MockPersistentNode:
            id = "persistent"
            persistent = True

            async def execute(self, ctx):
                return "result"

        session = Session(name="test")
        graph = Graph(id="test", session=session)
        persistent = MockPersistentNode()
        ephemeral = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

        graph.add_step(persistent, step_id="a")
        graph.add_step(ephemeral, step_id="b")

        persistent_nodes = graph.collect_persistent_nodes()
        assert len(persistent_nodes) == 1
        assert persistent_nodes[0] is persistent

    @pytest.mark.asyncio
    async def test_interrupt_sets_cancellation_token(self):
        """Test interrupt() sets the cancellation token."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)

        step_started = asyncio.Event()

        async def slow_step(ctx: ExecutionContext):
            step_started.set()
            await asyncio.sleep(10)
            return "done"

        graph.add_step(FunctionNode(id="slow", session=session, fn=slow_step), step_id="slow")

        token = CancellationToken()
        context = ExecutionContext(session=session, cancellation=token)

        # Start graph execution in background
        task = asyncio.create_task(graph.execute(context))

        # Wait for step to start
        await step_started.wait()

        # Interrupt the graph
        await graph.interrupt()

        # Token should be cancelled
        assert token.is_cancelled

        # Task should raise CancelledError
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_interrupt_stops_current_node(self):
        """Test interrupt() interrupts the currently executing node."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)

        node_interrupted = False
        step_started = asyncio.Event()

        class InterruptableNode:
            id = "interruptable"
            persistent = False

            async def execute(self, ctx):
                step_started.set()
                await asyncio.sleep(10)
                return "done"

            async def interrupt(self):
                nonlocal node_interrupted
                node_interrupted = True

        graph.add_step(InterruptableNode(), step_id="step")

        token = CancellationToken()
        context = ExecutionContext(session=session, cancellation=token)

        task = asyncio.create_task(graph.execute(context))

        await step_started.wait()

        # Interrupt should call node's interrupt()
        await graph.interrupt()

        assert node_interrupted

        # Clean up
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_interrupt_when_not_executing(self):
        """Test interrupt() is safe when graph is not executing."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)

        # Should not raise
        await graph.interrupt()

    @pytest.mark.asyncio
    async def test_interrupt_prevents_next_steps(self):
        """Test interrupt() prevents subsequent steps from executing."""
        session = Session(name="test")
        graph = Graph(id="test", session=session)

        steps_executed = []
        step1_started = asyncio.Event()

        async def step1(ctx):
            steps_executed.append("step1")
            step1_started.set()
            await asyncio.sleep(0.5)
            return "step1"

        def step2(ctx):
            steps_executed.append("step2")
            return "step2"

        graph.add_step(FunctionNode(id="fn1", session=session, fn=step1), step_id="step1")
        graph.add_step(
            FunctionNode(id="fn2", session=session, fn=step2), step_id="step2", depends_on=["step1"]
        )

        token = CancellationToken()
        context = ExecutionContext(session=session, cancellation=token)

        task = asyncio.create_task(graph.execute(context))

        # Wait for step1 to start
        await step1_started.wait()

        # Interrupt before step2
        await graph.interrupt()

        # Wait for task to complete/fail
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Only step1 should have started
        assert "step1" in steps_executed
        assert "step2" not in steps_executed


class TestStepEvent:
    """Tests for StepEvent dataclass."""

    def test_creation(self):
        """Test creating StepEvent."""
        event = StepEvent(
            event_type="step_start",
            step_id="test",
            node_id="node1",
        )

        assert event.event_type == "step_start"
        assert event.step_id == "test"
        assert event.node_id == "node1"
        assert event.data is None
        assert event.timestamp is not None

    def test_with_data(self):
        """Test StepEvent with data."""
        event = StepEvent(
            event_type="step_complete",
            step_id="test",
            node_id="node1",
            data={"result": "value"},
        )

        assert event.data == {"result": "value"}
