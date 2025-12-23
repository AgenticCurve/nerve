"""Tests for nerve.core.nodes.graph module."""

import pytest

from nerve.core.nodes.base import FunctionNode
from nerve.core.nodes.context import ExecutionContext
from nerve.core.nodes.graph import Graph, Step, StepEvent
from nerve.core.nodes.policies import ErrorPolicy
from nerve.core.session.session import Session


class TestStep:
    """Tests for Step dataclass."""

    def test_default_values(self):
        """Test default values."""
        step = Step()
        assert step.node is None
        assert step.node_ref is None
        assert step.input is None
        assert step.input_fn is None
        assert step.depends_on == []
        assert step.error_policy is None
        assert step.parser is None

    def test_with_node(self):
        """Test step with direct node reference."""
        node = FunctionNode(id="test", fn=lambda ctx: ctx.input)
        step = Step(node=node, input="hello", depends_on=["prev"])

        assert step.node is node
        assert step.input == "hello"
        assert step.depends_on == ["prev"]


class TestGraph:
    """Tests for Graph class."""

    def test_init(self):
        """Test graph initialization."""
        graph = Graph(id="test-graph")
        assert graph.id == "test-graph"
        assert graph.persistent is False
        assert len(graph) == 0

    def test_add_step(self):
        """Test adding steps."""
        graph = Graph(id="test")
        node = FunctionNode(id="fn", fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="step1", input="hello")

        assert len(graph) == 1
        assert "step1" in graph.list_steps()
        step = graph.get_step("step1")
        assert step is not None
        assert step.node is node

    def test_add_step_duplicate_error(self):
        """Test duplicate step_id raises error."""
        graph = Graph(id="test")
        node = FunctionNode(id="fn", fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="step1")

        with pytest.raises(ValueError, match="already exists"):
            graph.add_step(node, step_id="step1")

    def test_add_step_empty_id_error(self):
        """Test empty step_id raises error."""
        graph = Graph(id="test")
        node = FunctionNode(id="fn", fn=lambda ctx: ctx.input)

        with pytest.raises(ValueError, match="cannot be empty"):
            graph.add_step(node, step_id="")

    def test_add_step_ref(self):
        """Test adding step with node_ref."""
        graph = Graph(id="test")

        graph.add_step_ref(node_id="registered-node", step_id="step1")

        step = graph.get_step("step1")
        assert step is not None
        assert step.node_ref == "registered-node"

    def test_chain(self):
        """Test chain method sets dependencies."""
        graph = Graph(id="test")
        node = FunctionNode(id="fn", fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="a")
        graph.add_step(node, step_id="b")
        graph.add_step(node, step_id="c")

        graph.chain("a", "b", "c")

        assert "a" in graph.get_step("b").depends_on
        assert "b" in graph.get_step("c").depends_on

    def test_validate_valid_graph(self):
        """Test validate with valid graph."""
        graph = Graph(id="test")
        node = FunctionNode(id="fn", fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="a")
        graph.add_step(node, step_id="b", depends_on=["a"])

        errors = graph.validate()
        assert errors == []

    def test_validate_self_dependency(self):
        """Test validate catches self-dependency."""
        graph = Graph(id="test")
        node = FunctionNode(id="fn", fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="a", depends_on=["a"])

        errors = graph.validate()
        assert len(errors) == 1
        assert "depends on itself" in errors[0]

    def test_validate_missing_dependency(self):
        """Test validate catches missing dependency."""
        graph = Graph(id="test")
        node = FunctionNode(id="fn", fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="a", depends_on=["nonexistent"])

        errors = graph.validate()
        assert len(errors) == 1
        assert "unknown step" in errors[0]

    def test_validate_missing_node(self):
        """Test validate catches step without node or node_ref."""
        graph = Graph(id="test")
        graph._steps["a"] = Step()  # No node or node_ref

        errors = graph.validate()
        assert len(errors) == 1
        assert "node or node_ref" in errors[0]

    def test_validate_mutually_exclusive_input(self):
        """Test validate catches input and input_fn together."""
        graph = Graph(id="test")
        node = FunctionNode(id="fn", fn=lambda ctx: ctx.input)

        graph._steps["a"] = Step(
            node=node, input="static", input_fn=lambda u: u
        )

        errors = graph.validate()
        assert len(errors) == 1
        assert "mutually exclusive" in errors[0]

    def test_execution_order(self):
        """Test execution order respects dependencies."""
        graph = Graph(id="test")
        node = FunctionNode(id="fn", fn=lambda ctx: ctx.input)

        graph.add_step(node, step_id="c", depends_on=["b"])
        graph.add_step(node, step_id="b", depends_on=["a"])
        graph.add_step(node, step_id="a")

        order = graph.execution_order()
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    @pytest.mark.asyncio
    async def test_execute_simple(self):
        """Test simple graph execution."""
        graph = Graph(id="test")

        graph.add_step(
            FunctionNode(id="fn1", fn=lambda ctx: "result_a"),
            step_id="a",
        )
        graph.add_step(
            FunctionNode(id="fn2", fn=lambda ctx: f"got_{ctx.upstream['a']}"),
            step_id="b",
            depends_on=["a"],
        )

        session = Session()
        context = ExecutionContext(session=session)
        results = await graph.execute(context)

        assert results["a"] == "result_a"
        assert results["b"] == "got_result_a"

    @pytest.mark.asyncio
    async def test_execute_with_static_input(self):
        """Test execution with static input."""
        graph = Graph(id="test")

        graph.add_step(
            FunctionNode(id="fn", fn=lambda ctx: ctx.input.upper()),
            step_id="a",
            input="hello",
        )

        session = Session()
        context = ExecutionContext(session=session)
        results = await graph.execute(context)

        assert results["a"] == "HELLO"

    @pytest.mark.asyncio
    async def test_execute_with_input_fn(self):
        """Test execution with dynamic input_fn."""
        graph = Graph(id="test")

        graph.add_step(
            FunctionNode(id="fn1", fn=lambda ctx: {"data": "value"}),
            step_id="a",
        )
        graph.add_step(
            FunctionNode(id="fn2", fn=lambda ctx: ctx.input),
            step_id="b",
            depends_on=["a"],
            input_fn=lambda u: u["a"]["data"].upper(),
        )

        session = Session()
        context = ExecutionContext(session=session)
        results = await graph.execute(context)

        assert results["a"] == {"data": "value"}
        assert results["b"] == "VALUE"

    @pytest.mark.asyncio
    async def test_execute_with_node_ref(self):
        """Test execution with node_ref resolved from session."""
        session = Session()
        registered_node = FunctionNode(id="registered", fn=lambda ctx: "from_session")
        session.register(registered_node)

        graph = Graph(id="test")
        graph.add_step_ref(node_id="registered", step_id="a")

        context = ExecutionContext(session=session)
        results = await graph.execute(context)

        assert results["a"] == "from_session"

    @pytest.mark.asyncio
    async def test_nested_graphs(self):
        """Test graphs containing graphs."""
        inner = Graph(id="inner")
        inner.add_step(
            FunctionNode(id="fn", fn=lambda ctx: "inner_result"),
            step_id="inner_step",
        )

        outer = Graph(id="outer")
        outer.add_step(inner, step_id="nested")
        outer.add_step(
            FunctionNode(
                id="fn", fn=lambda ctx: f"got_{ctx.upstream['nested']['inner_step']}"
            ),
            step_id="after",
            depends_on=["nested"],
        )

        session = Session()
        context = ExecutionContext(session=session)
        results = await outer.execute(context)

        assert results["nested"]["inner_step"] == "inner_result"
        assert results["after"] == "got_inner_result"

    @pytest.mark.asyncio
    async def test_execute_stream(self):
        """Test streaming execution."""
        graph = Graph(id="test")

        graph.add_step(
            FunctionNode(id="fn1", fn=lambda ctx: "a"),
            step_id="a",
        )
        graph.add_step(
            FunctionNode(id="fn2", fn=lambda ctx: "b"),
            step_id="b",
            depends_on=["a"],
        )

        session = Session()
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
        graph = Graph(id="test")
        node = FunctionNode(id="fn", fn=lambda ctx: ctx.input)
        graph.add_step(node, step_id="a")
        graph.add_step(node, step_id="b")

        info = graph.to_info()
        assert info.id == "test"
        assert info.node_type == "graph"
        assert info.persistent is False
        assert info.metadata["steps"] == 2

    def test_repr(self):
        """Test repr."""
        graph = Graph(id="test")
        node = FunctionNode(id="fn", fn=lambda ctx: ctx.input)
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

        graph = Graph(id="test")
        persistent = MockPersistentNode()
        ephemeral = FunctionNode(id="fn", fn=lambda ctx: ctx.input)

        graph.add_step(persistent, step_id="a")
        graph.add_step(ephemeral, step_id="b")

        persistent_nodes = graph.collect_persistent_nodes()
        assert len(persistent_nodes) == 1
        assert persistent_nodes[0] is persistent


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
