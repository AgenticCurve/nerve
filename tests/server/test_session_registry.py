"""Unit tests for SessionRegistry.

Tests the central registry for session state with dynamic lookup.
"""

from __future__ import annotations

import pytest

from nerve.core.session import Session
from nerve.server.session_registry import SessionRegistry


class TestSessionRegistry:
    """Tests for SessionRegistry functionality."""

    @pytest.fixture
    def registry(self) -> SessionRegistry:
        """Create a fresh SessionRegistry for each test."""
        return SessionRegistry()

    @pytest.fixture
    def session(self) -> Session:
        """Create a test session."""
        return Session(name="test-session", server_name="test-server")

    @pytest.fixture
    def default_session(self) -> Session:
        """Create a default session."""
        return Session(name="default", server_name="test-server")

    def test_empty_registry(self, registry: SessionRegistry) -> None:
        """Empty registry has no sessions or default."""
        assert registry.default_session is None
        assert registry.default_session_name is None
        assert registry.session_count() == 0
        assert registry.list_session_names() == []
        assert registry.get_all_sessions() == []

    def test_add_session(self, registry: SessionRegistry, session: Session) -> None:
        """add_session registers a new session."""
        registry.add_session("test-session", session)

        assert registry.has_session("test-session")
        assert registry.session_count() == 1
        assert "test-session" in registry.list_session_names()

    def test_add_multiple_sessions(self, registry: SessionRegistry) -> None:
        """Multiple sessions can be added."""
        session1 = Session(name="session-1", server_name="test")
        session2 = Session(name="session-2", server_name="test")

        registry.add_session("session-1", session1)
        registry.add_session("session-2", session2)

        assert registry.session_count() == 2
        assert registry.has_session("session-1")
        assert registry.has_session("session-2")

    def test_has_session_false_for_nonexistent(self, registry: SessionRegistry) -> None:
        """has_session returns False for nonexistent session."""
        assert not registry.has_session("nonexistent")

    def test_remove_session(self, registry: SessionRegistry, session: Session) -> None:
        """remove_session unregisters a session and returns it."""
        registry.add_session("test-session", session)

        removed = registry.remove_session("test-session")

        assert removed is session
        assert not registry.has_session("test-session")
        assert registry.session_count() == 0

    def test_remove_session_returns_none_for_nonexistent(self, registry: SessionRegistry) -> None:
        """remove_session returns None for nonexistent session."""
        removed = registry.remove_session("nonexistent")
        assert removed is None

    def test_set_default(self, registry: SessionRegistry, default_session: Session) -> None:
        """set_default sets the default session."""
        registry.add_session("default", default_session)
        registry.set_default("default")

        assert registry.default_session is default_session
        assert registry.default_session_name == "default"

    def test_set_default_raises_for_nonexistent(self, registry: SessionRegistry) -> None:
        """set_default raises ValueError for nonexistent session."""
        with pytest.raises(ValueError, match="not found"):
            registry.set_default("nonexistent")

    def test_get_session_returns_by_name(self, registry: SessionRegistry, session: Session) -> None:
        """get_session returns session by name."""
        registry.add_session("test-session", session)

        result = registry.get_session("test-session")

        assert result is session

    def test_get_session_returns_default_when_none(
        self, registry: SessionRegistry, default_session: Session
    ) -> None:
        """get_session returns default session when session_id is None."""
        registry.add_session("default", default_session)
        registry.set_default("default")

        result = registry.get_session(None)

        assert result is default_session

    def test_get_session_raises_when_not_found(self, registry: SessionRegistry) -> None:
        """get_session raises ValueError for nonexistent session."""
        with pytest.raises(ValueError, match="Session not found"):
            registry.get_session("nonexistent")

    def test_get_session_raises_when_no_default(self, registry: SessionRegistry) -> None:
        """get_session raises ValueError when no default and None passed."""
        with pytest.raises(ValueError, match="No default session"):
            registry.get_session(None)

    def test_get_all_sessions(self, registry: SessionRegistry) -> None:
        """get_all_sessions returns list of all Session objects."""
        session1 = Session(name="session-1", server_name="test")
        session2 = Session(name="session-2", server_name="test")

        registry.add_session("session-1", session1)
        registry.add_session("session-2", session2)

        all_sessions = registry.get_all_sessions()

        assert len(all_sessions) == 2
        assert session1 in all_sessions
        assert session2 in all_sessions

    def test_list_session_names(self, registry: SessionRegistry) -> None:
        """list_session_names returns list of session names."""
        session1 = Session(name="alpha", server_name="test")
        session2 = Session(name="beta", server_name="test")

        registry.add_session("alpha", session1)
        registry.add_session("beta", session2)

        names = registry.list_session_names()

        assert len(names) == 2
        assert "alpha" in names
        assert "beta" in names

    def test_default_session_dynamic_lookup(self, registry: SessionRegistry) -> None:
        """default_session uses dynamic lookup (not cached reference)."""
        session1 = Session(name="session-1", server_name="test")
        session2 = Session(name="session-2", server_name="test")

        registry.add_session("session-1", session1)
        registry.add_session("session-2", session2)

        # Set first default
        registry.set_default("session-1")
        assert registry.default_session is session1

        # Change default - should update dynamically
        registry.set_default("session-2")
        assert registry.default_session is session2

    def test_get_session_with_empty_session(self, registry: SessionRegistry) -> None:
        """get_session works with empty sessions (no nodes/graphs).

        This tests the fix for the Session.__bool__ bug where empty sessions
        evaluated to False.
        """
        empty_session = Session(name="empty", server_name="test")
        # Session has no nodes or graphs, so bool(empty_session) would be False
        assert len(empty_session.nodes) == 0
        assert len(empty_session.graphs) == 0

        registry.add_session("empty", empty_session)

        # Should still find the session even though it's "empty"
        result = registry.get_session("empty")
        assert result is empty_session

    def test_default_session_with_empty_session(self, registry: SessionRegistry) -> None:
        """default_session works with empty sessions.

        This tests the fix for the Session.__bool__ bug.
        """
        empty_session = Session(name="default", server_name="test")

        registry.add_session("default", empty_session)
        registry.set_default("default")

        # Should return empty session, not None
        result = registry.get_session(None)
        assert result is empty_session
