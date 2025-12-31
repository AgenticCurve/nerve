"""Tests for GraphHandler with step registration support."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nerve.server.engine import build_nerve_engine
from nerve.server.protocols import Command, CommandType


class MockEventSink:
    """Mock event sink for testing."""

    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


def create_mock_node(node_id: str):
    """Create a mock node for testing."""
    mock_node = MagicMock()
    mock_node.id = node_id
    mock_node.stop = AsyncMock()

    async def mock_send(text: str):
        """Mock send that returns the input."""
        return f"Response to: {text}"

    mock_node.send = mock_send
    return mock_node


def get_default_session(engine):
    """Helper to get the default session from the engine's session registry."""
    return engine.session_handler.session_registry.default_session


class TestCreateGraphWithSteps:
    """Tests for create_graph with step registration."""

    @pytest.fixture
    def event_sink(self):
        """Create mock event sink."""
        return MockEventSink()

    @pytest.fixture
    def engine(self, event_sink):
        """Create engine with test configuration."""
        return build_nerve_engine(
            event_sink=event_sink,
            server_name="test-server",
        )

    def _add_mock_nodes(self, engine, *node_ids):
        """Helper to add mock nodes to default session."""
        session = get_default_session(engine)
        for node_id in node_ids:
            session.nodes[node_id] = create_mock_node(node_id)

    @pytest.mark.asyncio
    async def test_create_empty_graph_backward_compatibility(self, engine):
        """Test that create_graph without steps still creates empty graph."""
        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={"graph_id": "empty_graph"},
            )
        )

        assert result.success
        assert result.data["graph_id"] == "empty_graph"
        assert result.data["step_count"] == 0

        # Verify graph exists in session
        session = get_default_session(engine)
        assert "empty_graph" in session.graphs

    @pytest.mark.asyncio
    async def test_create_graph_with_single_step(self, engine):
        """Test creating graph with one step."""
        self._add_mock_nodes(engine, "node1")

        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "single_step",
                    "steps": [
                        {
                            "step_id": "step1",
                            "node_id": "node1",
                            "input": "Hello world",
                        }
                    ],
                },
            )
        )

        assert result.success
        assert result.data["graph_id"] == "single_step"
        assert result.data["step_count"] == 1

        # Verify graph structure
        session = get_default_session(engine)
        graph = session.get_graph("single_step")
        assert graph is not None
        assert "step1" in graph.list_steps()

    @pytest.mark.asyncio
    async def test_create_graph_with_multiple_steps_and_dependencies(self, engine):
        """Test creating graph with linear chain of dependencies."""
        self._add_mock_nodes(engine, "node1", "node2", "node3")

        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "chain_graph",
                    "steps": [
                        {
                            "step_id": "step1",
                            "node_id": "node1",
                            "input": "Start",
                        },
                        {
                            "step_id": "step2",
                            "node_id": "node2",
                            "input": "Process {step1}",
                            "depends_on": ["step1"],
                        },
                        {
                            "step_id": "step3",
                            "node_id": "node3",
                            "input": "Finalize {step2}",
                            "depends_on": ["step2"],
                        },
                    ],
                },
            )
        )

        assert result.success
        assert result.data["step_count"] == 3

        # Verify graph structure
        session = get_default_session(engine)
        graph = session.get_graph("chain_graph")
        assert graph is not None
        assert set(graph.list_steps()) == {"step1", "step2", "step3"}

        # Verify template conversion
        step2 = graph.get_step("step2")
        assert step2 is not None
        assert step2.input_fn is not None  # Template converted to lambda
        assert step2.depends_on == ["step1"]

    @pytest.mark.asyncio
    async def test_create_graph_with_template_variables(self, engine):
        """Test that template variables {step_id} are detected and converted."""
        self._add_mock_nodes(engine, "node1", "node2")

        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "template_graph",
                    "steps": [
                        {
                            "step_id": "pick",
                            "node_id": "node1",
                            "input": "Pick a number",
                        },
                        {
                            "step_id": "double",
                            "node_id": "node2",
                            "input": "Double this: {pick}",
                            "depends_on": ["pick"],
                        },
                    ],
                },
            )
        )

        assert result.success
        assert result.data["step_count"] == 2

        # Verify template step has input_fn
        session = get_default_session(engine)
        graph = session.get_graph("template_graph")
        double_step = graph.get_step("double")
        assert double_step.input_fn is not None
        assert double_step.input is None  # Static input should be None when using template

    @pytest.mark.asyncio
    async def test_create_graph_missing_node_fails(self, engine):
        """Test that referencing non-existent node fails with clear error."""
        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "bad_graph",
                    "steps": [
                        {
                            "step_id": "step1",
                            "node_id": "nonexistent",
                            "input": "Test",
                        }
                    ],
                },
            )
        )

        assert not result.success
        assert "nonexistent" in result.error
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_graph_with_cycle_fails(self, engine):
        """Test that circular dependencies are detected during validation."""
        self._add_mock_nodes(engine, "node1", "node2")

        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "cycle_graph",
                    "steps": [
                        {
                            "step_id": "a",
                            "node_id": "node1",
                            "input": "A",
                            "depends_on": ["b"],
                        },
                        {
                            "step_id": "b",
                            "node_id": "node2",
                            "input": "B",
                            "depends_on": ["a"],
                        },
                    ],
                },
            )
        )

        assert not result.success
        assert "cycle" in result.error.lower() or "validation failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_graph_with_missing_dependency_fails(self, engine):
        """Test that referencing non-existent dependency fails validation."""
        self._add_mock_nodes(engine, "node1")

        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "bad_dep",
                    "steps": [
                        {
                            "step_id": "step1",
                            "node_id": "node1",
                            "input": "Test",
                            "depends_on": ["nonexistent_step"],
                        }
                    ],
                },
            )
        )

        assert not result.success
        assert "validation failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_graph_missing_step_id_fails(self, engine):
        """Test that step without step_id fails with clear error."""
        self._add_mock_nodes(engine, "node1")

        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "bad_step",
                    "steps": [
                        {
                            "node_id": "node1",
                            "input": "Test",
                            # Missing step_id
                        }
                    ],
                },
            )
        )

        assert not result.success
        assert "step_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_graph_missing_node_id_fails(self, engine):
        """Test that step without node_id fails with clear error."""
        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "bad_step",
                    "steps": [
                        {
                            "step_id": "step1",
                            "input": "Test",
                            # Missing node_id
                        }
                    ],
                },
            )
        )

        assert not result.success
        assert "node_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_graph_empty_steps_list(self, engine):
        """Test that empty steps list creates empty graph."""
        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "empty_steps",
                    "steps": [],
                },
            )
        )

        assert result.success
        assert result.data["step_count"] == 0

    @pytest.mark.asyncio
    async def test_create_graph_invalid_depends_on_type(self, engine):
        """Test that non-list depends_on fails with clear error."""
        self._add_mock_nodes(engine, "node1")

        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "bad_deps",
                    "steps": [
                        {
                            "step_id": "step1",
                            "node_id": "node1",
                            "input": "Test",
                            "depends_on": "not_a_list",  # Should be list
                        }
                    ],
                },
            )
        )

        assert not result.success
        assert "depends_on" in result.error.lower()
        assert "list" in result.error.lower()


class TestTemplateSubstitution:
    """Tests for template variable substitution logic."""

    @pytest.fixture
    def event_sink(self):
        """Create mock event sink."""
        return MockEventSink()

    @pytest.fixture
    def engine(self, event_sink):
        """Create engine with test configuration."""
        return build_nerve_engine(
            event_sink=event_sink,
            server_name="test-server",
        )

    def _add_mock_nodes(self, engine, *node_ids):
        """Helper to add mock nodes to default session."""
        session = get_default_session(engine)
        for node_id in node_ids:
            session.nodes[node_id] = create_mock_node(node_id)

    @pytest.mark.asyncio
    async def test_static_input_without_templates(self, engine):
        """Test that static input without templates remains static."""
        self._add_mock_nodes(engine, "node1")

        await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "static_input",
                    "steps": [
                        {
                            "step_id": "step1",
                            "node_id": "node1",
                            "input": "Plain text without templates",
                        }
                    ],
                },
            )
        )

        session = get_default_session(engine)
        graph = session.get_graph("static_input")
        step = graph.get_step("step1")

        assert step.input == "Plain text without templates"
        assert step.input_fn is None  # No template function

    @pytest.mark.asyncio
    async def test_multiple_template_variables_in_one_input(self, engine):
        """Test input with multiple template variables."""
        self._add_mock_nodes(engine, "node1", "node2", "node3")

        await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={
                    "graph_id": "multi_template",
                    "steps": [
                        {"step_id": "a", "node_id": "node1", "input": "A"},
                        {"step_id": "b", "node_id": "node2", "input": "B"},
                        {
                            "step_id": "c",
                            "node_id": "node3",
                            "input": "Combine {a} and {b}",
                            "depends_on": ["a", "b"],
                        },
                    ],
                },
            )
        )

        session = get_default_session(engine)
        graph = session.get_graph("multi_template")
        step_c = graph.get_step("c")

        assert step_c.input_fn is not None
        assert step_c.input is None
