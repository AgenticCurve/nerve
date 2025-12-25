"""Tests for NerveEngine session management."""

from __future__ import annotations

import pytest

from nerve.server.engine import build_nerve_engine
from nerve.server.protocols import Command, CommandType


class MockEventSink:
    """Mock event sink for testing."""

    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


def get_default_session(engine):
    """Helper to get the default session from the engine's session registry."""
    return engine.session_handler.session_registry.default_session


def get_session_registry(engine):
    """Helper to get the session registry from the engine."""
    return engine.session_handler.session_registry


class TestEngineSessionCommands:
    """Tests for session management commands."""

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

    @pytest.mark.asyncio
    async def test_create_session(self, engine):
        """CREATE_SESSION creates new session."""
        result = await engine.execute(
            Command(
                type=CommandType.CREATE_SESSION,
                params={"name": "test-session", "description": "A test session"},
            )
        )

        assert result.success is True
        assert "session_id" in result.data

        # Verify session exists
        session_id = result.data["session_id"]
        registry = get_session_registry(engine)
        assert registry.has_session(session_id)

    @pytest.mark.asyncio
    async def test_delete_session(self, engine):
        """DELETE_SESSION removes session."""
        # Create a session first
        create_result = await engine.execute(
            Command(
                type=CommandType.CREATE_SESSION,
                params={"name": "to-delete"},
            )
        )
        session_id = create_result.data["session_id"]

        # Delete it
        result = await engine.execute(
            Command(
                type=CommandType.DELETE_SESSION,
                params={"session_id": session_id},
            )
        )

        assert result.success is True
        registry = get_session_registry(engine)
        assert not registry.has_session(session_id)

    @pytest.mark.asyncio
    async def test_delete_default_session_raises(self, engine):
        """Cannot delete default session."""
        default_session = get_default_session(engine)
        result = await engine.execute(
            Command(
                type=CommandType.DELETE_SESSION,
                params={"session_id": default_session.name},
            )
        )

        assert result.success is False
        assert "default" in result.error.lower()

    @pytest.mark.asyncio
    async def test_list_sessions(self, engine):
        """LIST_SESSIONS returns all sessions."""
        # Create additional sessions
        await engine.execute(
            Command(
                type=CommandType.CREATE_SESSION,
                params={"name": "session-1"},
            )
        )
        await engine.execute(
            Command(
                type=CommandType.CREATE_SESSION,
                params={"name": "session-2"},
            )
        )

        result = await engine.execute(
            Command(
                type=CommandType.LIST_SESSIONS,
                params={},
            )
        )

        assert result.success is True
        sessions = result.data["sessions"]
        assert len(sessions) >= 3  # default + 2 created

    @pytest.mark.asyncio
    async def test_get_session(self, engine):
        """GET_SESSION returns session info."""
        default_session = get_default_session(engine)
        # Use default session (no session_id param means default)
        result = await engine.execute(
            Command(
                type=CommandType.GET_SESSION,
                params={},
            )
        )

        assert result.success is True
        assert result.data["session_id"] == default_session.name
        assert "nodes" in result.data
        assert "graphs" in result.data


class TestEngineGraphCommands:
    """Tests for graph management commands."""

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

    @pytest.mark.asyncio
    async def test_create_graph(self, engine):
        """CREATE_GRAPH creates new graph."""
        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={"graph_id": "test-graph"},
            )
        )

        assert result.success is True
        assert result.data["graph_id"] == "test-graph"
        default_session = get_default_session(engine)
        assert "test-graph" in default_session.graphs

    @pytest.mark.asyncio
    async def test_delete_graph(self, engine):
        """DELETE_GRAPH removes graph."""
        # Create a graph first
        await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={"graph_id": "to-delete"},
            )
        )

        # Delete it
        result = await engine.execute(
            Command(
                type=CommandType.DELETE_GRAPH,
                params={"graph_id": "to-delete"},
            )
        )

        assert result.success is True
        default_session = get_default_session(engine)
        assert "to-delete" not in default_session.graphs

    @pytest.mark.asyncio
    async def test_list_graphs(self, engine):
        """LIST_GRAPHS returns graphs in session."""
        # Create some graphs
        await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={"graph_id": "graph-1"},
            )
        )
        await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={"graph_id": "graph-2"},
            )
        )

        result = await engine.execute(
            Command(
                type=CommandType.LIST_GRAPHS,
                params={},
            )
        )

        assert result.success is True
        graph_ids = [g["id"] for g in result.data["graphs"]]
        assert "graph-1" in graph_ids
        assert "graph-2" in graph_ids


class TestEngineSessionRouting:
    """Tests for session_id parameter routing."""

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

    @pytest.mark.asyncio
    async def test_create_graph_in_specific_session(self, engine):
        """CREATE_GRAPH with session_id creates in that session."""
        # Create a new session
        create_result = await engine.execute(
            Command(
                type=CommandType.CREATE_SESSION,
                params={"name": "other-session"},
            )
        )
        assert create_result.success is True
        session_id = create_result.data["session_id"]

        # Create graph in that session
        graph_result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={"graph_id": "specific-graph", "session_id": session_id},
            )
        )
        assert graph_result.success is True, f"Graph creation failed: {graph_result.error}"

        # Verify it's in the specific session, not default
        registry = get_session_registry(engine)
        other_session = registry.get_session(session_id)
        default_session = get_default_session(engine)
        assert "specific-graph" in other_session.graphs
        assert "specific-graph" not in default_session.graphs

    @pytest.mark.asyncio
    async def test_create_graph_default_session(self, engine):
        """CREATE_GRAPH without session_id uses default."""
        await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={"graph_id": "default-graph"},
            )
        )

        default_session = get_default_session(engine)
        assert "default-graph" in default_session.graphs

    @pytest.mark.asyncio
    async def test_invalid_session_id_raises(self, engine):
        """Invalid session_id raises error."""
        result = await engine.execute(
            Command(
                type=CommandType.CREATE_GRAPH,
                params={"graph_id": "test", "session_id": "nonexistent"},
            )
        )

        assert result.success is False
        assert "not found" in result.error.lower()
