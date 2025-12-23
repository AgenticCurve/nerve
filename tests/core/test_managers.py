"""Tests for Session and SessionManager.

Tests the session and session management functionality with the new Node API.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nerve.core.session.manager import SessionManager
from nerve.core.session.session import Session


class TestSession:
    """Tests for Session (Node API).

    Session is a clean Node-only registry and lifecycle manager.
    It uses register/unregister/list_nodes/stop for node management.
    """

    def test_session_creation_with_defaults(self):
        """Test creating session with default values."""
        session = Session()

        assert session.id is not None
        assert len(session.id) == 8  # UUID[:8]
        assert session.name == session.id  # Name defaults to ID
        assert session.description == ""
        assert session.tags == []
        assert session.created_at is not None

    def test_session_creation_with_values(self):
        """Test creating session with specified values."""
        session = Session(
            id="my-session",
            name="Test Session",
            description="A test session",
            tags=["test", "example"]
        )

        assert session.id == "my-session"
        assert session.name == "Test Session"
        assert session.description == "A test session"
        assert session.tags == ["test", "example"]

    def test_register_node(self):
        """Test registering a node to session."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "test-node"

        session.register(mock_node, name="test")

        assert "test" in session
        assert len(session) == 1
        assert session.get("test") is mock_node

    def test_register_node_uses_id_by_default(self):
        """Test that register uses node.id when name not specified."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "node-123"

        session.register(mock_node)

        assert "node-123" in session
        assert session.get("node-123") is mock_node

    def test_register_duplicate_raises(self):
        """Test that registering duplicate name raises."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "node-1"

        session.register(mock_node, name="test")

        mock_node2 = MagicMock()
        mock_node2.id = "node-2"
        with pytest.raises(ValueError, match="already exists"):
            session.register(mock_node2, name="test")

    def test_get_node(self):
        """Test getting a node by name."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "my-node"

        session.register(mock_node, name="my-node")

        assert session.get("my-node") is mock_node
        assert session.get("nonexistent") is None

    def test_unregister_node(self):
        """Test unregistering a node."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "to-remove"

        session.register(mock_node, name="to-remove")
        assert "to-remove" in session

        removed = session.unregister("to-remove")
        assert removed is mock_node
        assert "to-remove" not in session

    def test_unregister_nonexistent(self):
        """Test unregistering nonexistent node returns None."""
        session = Session()

        result = session.unregister("nonexistent")
        assert result is None

    def test_list_nodes(self):
        """Test listing node names."""
        session = Session()

        mock_node_a = MagicMock()
        mock_node_a.id = "node-a"
        mock_node_b = MagicMock()
        mock_node_b.id = "node-b"
        mock_node_c = MagicMock()
        mock_node_c.id = "node-c"

        session.register(mock_node_a, name="node-a")
        session.register(mock_node_b, name="node-b")
        session.register(mock_node_c, name="node-c")

        names = session.list_nodes()
        assert len(names) == 3
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

        session.register(mock_node, name="test")

        info = session.get_node_info()
        assert "test" in info
        assert info["test"] is mock_info

    @pytest.mark.asyncio
    async def test_stop_persistent_nodes(self):
        """Test stopping all persistent nodes."""
        session = Session()

        # Create mock persistent nodes
        nodes = []
        for i in range(3):
            node = MagicMock()
            node.id = f"node-{i}"
            node.persistent = True
            node.stop = AsyncMock()
            nodes.append(node)
            session.register(node, name=f"node-{i}")

        assert len(session) == 3

        await session.stop()

        for node in nodes:
            node.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_non_persistent_nodes_skipped(self):
        """Test that non-persistent nodes are not stopped."""
        session = Session()

        # Create mock non-persistent node (no stop method)
        mock_node = MagicMock(spec=["id", "execute"])
        mock_node.id = "func-node"

        session.register(mock_node, name="func")

        # Should not raise
        await session.stop()

    def test_to_dict(self):
        """Test converting session to dict."""
        session = Session(
            id="test-id",
            name="Test Name",
            description="Test desc",
            tags=["tag1", "tag2"]
        )

        mock_node = MagicMock()
        mock_node.id = "node-1"
        mock_info = MagicMock()
        mock_info.to_dict.return_value = {"id": "node-1", "state": "ready"}
        mock_node.to_info.return_value = mock_info

        session.register(mock_node, name="node1")

        result = session.to_dict()

        assert result["id"] == "test-id"
        assert result["name"] == "Test Name"
        assert result["description"] == "Test desc"
        assert result["tags"] == ["tag1", "tag2"]
        assert "created_at" in result
        assert "nodes" in result

    def test_contains(self):
        """Test __contains__ for node name lookup."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "exists"
        session.register(mock_node, name="exists")

        assert "exists" in session
        assert "missing" not in session

    def test_len(self):
        """Test __len__ returns node count."""
        session = Session()

        assert len(session) == 0

        mock_node1 = MagicMock()
        mock_node1.id = "node1"
        session.register(mock_node1, name="node1")
        assert len(session) == 1

        mock_node2 = MagicMock()
        mock_node2.id = "node2"
        session.register(mock_node2, name="node2")
        assert len(session) == 2

    def test_repr(self):
        """Test __repr__ format."""
        session = Session(id="my-id", name="My Session")
        mock_node = MagicMock()
        mock_node.id = "node1"
        session.register(mock_node, name="node1")

        repr_str = repr(session)
        assert "Session" in repr_str
        assert "my-id" in repr_str
        assert "My Session" in repr_str


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
            session_id="my-id",
            name="My Session",
            description="A test session",
            tags=["test"]
        )

        assert session.id == "my-id"
        assert session.name == "My Session"
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
        session.register(mock_node, name="node")

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
        s1.register(node1, name="node1")

        node2 = MagicMock()
        node2.id = "node2"
        node2.persistent = True
        node2.stop = AsyncMock()
        s2.register(node2, name="node2")

        await manager.close_all()

        assert manager.list_sessions() == []
        node1.stop.assert_called_once()
        node2.stop.assert_called_once()
