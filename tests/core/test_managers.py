"""Tests for Session and SessionManager.

Tests the session and session management functionality with the new Node API.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nerve.core.session.manager import SessionManager
from nerve.core.session.session import Session


class TestSession:
    """Tests for Session.

    Session is the central workspace that creates, registers, and manages
    nodes and graphs.
    """

    def test_session_creation_with_defaults(self):
        """Test creating session with default values."""
        session = Session()

        assert session.id is not None
        assert session.id == "default"  # Default name
        assert session.name == session.id  # Name and ID are the same
        assert session.description == ""
        assert session.tags == []
        assert session.created_at is not None

    def test_session_creation_with_values(self):
        """Test creating session with specified values."""
        session = Session(
            name="Test Session", description="A test session", tags=["test", "example"]
        )

        assert session.id == "Test Session"
        assert session.name == "Test Session"
        assert session.description == "A test session"
        assert session.tags == ["test", "example"]

    def test_add_node_directly(self):
        """Test adding a node directly to session.nodes."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "test-node"

        # Direct assignment (used by create_node internally)
        session.nodes["test"] = mock_node

        # Session now has 2 nodes: auto-created identity + test
        assert "test" in session
        assert len(session) == 2  # identity + test
        assert session.get_node("test") is mock_node
        assert "identity" in session.nodes  # Auto-created

    def test_duplicate_node_raises(self):
        """Test that adding duplicate node ID raises."""
        from nerve.core.nodes.base import FunctionNode

        session = Session()

        # Create first node
        FunctionNode(id="fn1", session=session, fn=lambda ctx: None)

        # Creating another node with same ID should raise
        with pytest.raises(ValueError, match="already exists"):
            FunctionNode(id="fn1", session=session, fn=lambda ctx: None)

    def test_get_node(self):
        """Test getting a node by name."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "my-node"

        session.nodes["my-node"] = mock_node

        assert session.get_node("my-node") is mock_node
        assert session.get_node("nonexistent") is None

    @pytest.mark.asyncio
    async def test_delete_node(self):
        """Test deleting a node."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "to-remove"
        mock_node.stop = AsyncMock()

        session.nodes["to-remove"] = mock_node
        assert "to-remove" in session

        deleted = await session.delete_node("to-remove")
        assert deleted is True
        assert "to-remove" not in session
        mock_node.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_node(self):
        """Test deleting nonexistent node returns False."""
        session = Session()

        result = await session.delete_node("nonexistent")
        assert result is False

    def test_list_nodes(self):
        """Test listing node names."""
        session = Session()

        mock_node_a = MagicMock()
        mock_node_a.id = "node-a"
        mock_node_b = MagicMock()
        mock_node_b.id = "node-b"
        mock_node_c = MagicMock()
        mock_node_c.id = "node-c"

        session.nodes["node-a"] = mock_node_a
        session.nodes["node-b"] = mock_node_b
        session.nodes["node-c"] = mock_node_c

        names = session.list_nodes()
        assert len(names) == 4  # identity + node-a, node-b, node-c
        assert "identity" in names  # Auto-created
        assert "node-a" in names
        assert "node-b" in names
        assert "node-c" in names

    def test_get_node_info(self):
        """Test getting info for all nodes."""
        session = Session()

        mock_node = MagicMock()
        mock_node.id = "test-node"
        mock_info = MagicMock()
        mock_node.to_info.return_value = mock_info

        session.nodes["test"] = mock_node

        info = session.get_node_info()
        assert "test" in info
        assert info["test"] is mock_info

    @pytest.mark.asyncio
    async def test_stop_persistent_nodes(self):
        """Test stopping all stateful nodes."""
        session = Session()

        # Create mock stateful nodes
        nodes = []
        for i in range(3):
            node = MagicMock()
            node.id = f"node-{i}"
            node.persistent = True
            node.stop = AsyncMock()
            nodes.append(node)
            session.nodes[f"node-{i}"] = node

        assert len(session) == 4  # identity + 3 test nodes

        await session.stop()

        for node in nodes:
            node.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_non_persistent_nodes_skipped(self):
        """Test that stateless nodes are not stopped."""
        session = Session()

        # Create mock stateless node (no stop method)
        mock_node = MagicMock(spec=["id", "execute"])
        mock_node.id = "func-node"

        session.nodes["func"] = mock_node

        # Should not raise
        await session.stop()

    def test_to_dict(self):
        """Test converting session to dict."""
        session = Session(name="test-id", description="Test desc", tags=["tag1", "tag2"])

        mock_node = MagicMock()
        mock_node.id = "node-1"
        mock_info = MagicMock()
        mock_info.to_dict.return_value = {"id": "node-1", "state": "ready"}
        mock_node.to_info.return_value = mock_info

        session.nodes["node1"] = mock_node

        result = session.to_dict()

        assert result["id"] == "test-id"
        assert result["name"] == "test-id"
        assert result["description"] == "Test desc"
        assert result["tags"] == ["tag1", "tag2"]
        assert "created_at" in result
        assert "nodes" in result

    def test_contains(self):
        """Test __contains__ for node name lookup."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "exists"
        session.nodes["exists"] = mock_node

        assert "exists" in session
        assert "missing" not in session

    def test_len(self):
        """Test __len__ returns node count."""
        session = Session()

        assert len(session) == 1  # Auto-created identity node

        mock_node1 = MagicMock()
        mock_node1.id = "node1"
        session.nodes["node1"] = mock_node1
        assert len(session) == 2  # identity + node1

        mock_node2 = MagicMock()
        mock_node2.id = "node2"
        session.nodes["node2"] = mock_node2
        assert len(session) == 3  # identity + node1 + node2

    def test_repr(self):
        """Test __repr__ format."""
        session = Session(name="My Session")
        mock_node = MagicMock()
        mock_node.id = "node1"
        session.nodes["node1"] = mock_node

        repr_str = repr(session)
        assert "Session" in repr_str
        assert "My Session" in repr_str

    def test_create_function_node(self):
        """Test creating a function node with new API."""
        from nerve.core.nodes.base import FunctionNode

        session = Session()

        fn = FunctionNode(id="test-fn", session=session, fn=lambda ctx: ctx.input)

        assert fn.id == "test-fn"
        assert "test-fn" in session.nodes
        assert session.get_node("test-fn") is fn

    def test_create_graph(self):
        """Test creating a graph with new API."""
        from nerve.core.nodes.graph import Graph

        session = Session()

        graph = Graph(id="test-graph", session=session)

        assert graph.id == "test-graph"
        assert "test-graph" in session.graphs
        assert session.get_graph("test-graph") is graph

    def test_delete_graph(self):
        """Test deleting a graph."""
        from nerve.core.nodes.graph import Graph

        session = Session()

        Graph(id="to-delete", session=session)
        assert "to-delete" in session.graphs

        deleted = session.delete_graph("to-delete")
        assert deleted is True
        assert "to-delete" not in session.graphs

    def test_list_graphs(self):
        """Test listing graph IDs."""
        from nerve.core.nodes.graph import Graph

        session = Session()

        Graph(id="graph-a", session=session)
        Graph(id="graph-b", session=session)

        graphs = session.list_graphs()
        assert len(graphs) == 2
        assert "graph-a" in graphs
        assert "graph-b" in graphs


class TestSessionManager:
    """Tests for SessionManager."""

    def test_empty_manager(self):
        """Test empty session manager."""
        manager = SessionManager()

        assert manager.list_sessions() == []
        assert manager.get_session("nonexistent") is None
        assert manager.find_by_name("nonexistent") is None

    def test_create_session(self):
        """Test creating a session."""
        manager = SessionManager()

        session = manager.create_session(name="test-session")

        assert session.name == "test-session"
        assert session.id in manager.list_sessions()
        assert manager.get_session(session.id) is session

    def test_create_session_with_id(self):
        """Test creating session with specified ID."""
        manager = SessionManager()

        session = manager.create_session(
            session_id="my-id", description="A test session", tags=["test"]
        )

        assert session.id == "my-id"
        assert session.name == "my-id"
        assert session.description == "A test session"
        assert session.tags == ["test"]

    def test_get_session(self):
        """Test getting a session by ID."""
        manager = SessionManager()

        session = manager.create_session(session_id="find-me")

        found = manager.get_session("find-me")
        assert found is session

        not_found = manager.get_session("nonexistent")
        assert not_found is None

    def test_find_by_name(self):
        """Test finding session by name."""
        manager = SessionManager()

        manager.create_session(name="session-one")
        session2 = manager.create_session(name="session-two")

        found = manager.find_by_name("session-two")
        assert found is session2

        not_found = manager.find_by_name("nonexistent")
        assert not_found is None

    def test_list_sessions(self):
        """Test listing session IDs."""
        manager = SessionManager()

        manager.create_session(session_id="s1")
        manager.create_session(session_id="s2")
        manager.create_session(session_id="s3")

        sessions = manager.list_sessions()
        assert len(sessions) == 3
        assert "s1" in sessions
        assert "s2" in sessions
        assert "s3" in sessions

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Test closing a session."""
        manager = SessionManager()

        session = manager.create_session(session_id="to-close")

        mock_node = MagicMock()
        mock_node.id = "node"
        mock_node.persistent = True
        mock_node.stop = AsyncMock()
        session.nodes["node"] = mock_node

        result = await manager.close_session("to-close")

        assert result is True
        assert "to-close" not in manager.list_sessions()
        mock_node.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_nonexistent_session(self):
        """Test closing nonexistent session returns False."""
        manager = SessionManager()

        result = await manager.close_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_all(self):
        """Test closing all sessions and nodes."""
        manager = SessionManager()

        s1 = manager.create_session(session_id="s1")
        s2 = manager.create_session(session_id="s2")

        node1 = MagicMock()
        node1.id = "node1"
        node1.persistent = True
        node1.stop = AsyncMock()
        s1.nodes["node1"] = node1

        node2 = MagicMock()
        node2.id = "node2"
        node2.persistent = True
        node2.stop = AsyncMock()
        s2.nodes["node2"] = node2

        await manager.close_all()

        assert manager.list_sessions() == []
        node1.stop.assert_called_once()
        node2.stop.assert_called_once()
