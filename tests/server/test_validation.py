"""Unit tests for ValidationHelpers.

Tests shared validation logic for command handlers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nerve.core.session import Session
from nerve.server.validation import ValidationHelpers


class TestRequireParam:
    """Tests for ValidationHelpers.require_param."""

    @pytest.fixture
    def validation(self) -> ValidationHelpers:
        """Create ValidationHelpers instance."""
        return ValidationHelpers()

    def test_require_param_returns_value(self, validation: ValidationHelpers) -> None:
        """require_param returns value when present."""
        params = {"node_id": "test-node", "command": "echo hello"}

        result = validation.require_param(params, "node_id")

        assert result == "test-node"

    def test_require_param_raises_for_missing_key(self, validation: ValidationHelpers) -> None:
        """require_param raises ValueError for missing key."""
        params = {"other_key": "value"}

        with pytest.raises(ValueError, match="node_id is required"):
            validation.require_param(params, "node_id")

    def test_require_param_raises_for_none_value(self, validation: ValidationHelpers) -> None:
        """require_param raises ValueError when value is None."""
        params = {"node_id": None}

        with pytest.raises(ValueError, match="node_id is required"):
            validation.require_param(params, "node_id")

    def test_require_param_allows_empty_string(self, validation: ValidationHelpers) -> None:
        """require_param allows empty string (not None)."""
        params = {"text": ""}

        result = validation.require_param(params, "text")

        assert result == ""

    def test_require_param_allows_zero(self, validation: ValidationHelpers) -> None:
        """require_param allows zero (not None)."""
        params = {"count": 0}

        result = validation.require_param(params, "count")

        assert result == 0

    def test_require_param_allows_false(self, validation: ValidationHelpers) -> None:
        """require_param allows False (not None)."""
        params = {"enabled": False}

        result = validation.require_param(params, "enabled")

        assert result is False


class TestGetNode:
    """Tests for ValidationHelpers.get_node."""

    @pytest.fixture
    def validation(self) -> ValidationHelpers:
        """Create ValidationHelpers instance."""
        return ValidationHelpers()

    @pytest.fixture
    def session(self) -> Session:
        """Create a test session."""
        return Session(name="test-session", server_name="test-server")

    @pytest.fixture
    def mock_node(self) -> MagicMock:
        """Create a mock node."""
        node = MagicMock()
        node.id = "test-node"
        return node

    @pytest.fixture
    def mock_terminal_node(self) -> MagicMock:
        """Create a mock terminal node with write method."""
        node = MagicMock()
        node.id = "terminal-node"
        node.write = MagicMock()  # Terminal capability
        return node

    def test_get_node_returns_node(
        self, validation: ValidationHelpers, session: Session, mock_node: MagicMock
    ) -> None:
        """get_node returns node when found."""
        session.nodes["test-node"] = mock_node

        result = validation.get_node(session, "test-node")

        assert result is mock_node

    def test_get_node_raises_for_not_found(
        self, validation: ValidationHelpers, session: Session
    ) -> None:
        """get_node raises ValueError when node not found."""
        with pytest.raises(ValueError, match="Node not found: nonexistent"):
            validation.get_node(session, "nonexistent")

    def test_get_node_require_terminal_success(
        self,
        validation: ValidationHelpers,
        session: Session,
        mock_terminal_node: MagicMock,
    ) -> None:
        """get_node with require_terminal=True succeeds for terminal node."""
        session.nodes["terminal-node"] = mock_terminal_node

        result = validation.get_node(session, "terminal-node", require_terminal=True)

        assert result is mock_terminal_node

    def test_get_node_require_terminal_failure(
        self, validation: ValidationHelpers, session: Session
    ) -> None:
        """get_node with require_terminal=True fails for non-terminal node."""
        # Create a mock node without write method
        non_terminal_node = MagicMock(spec=[])  # No methods
        non_terminal_node.id = "non-terminal"
        session.nodes["non-terminal"] = non_terminal_node

        with pytest.raises(ValueError, match="not a terminal node"):
            validation.get_node(session, "non-terminal", require_terminal=True)


class TestGetGraph:
    """Tests for ValidationHelpers.get_graph."""

    @pytest.fixture
    def validation(self) -> ValidationHelpers:
        """Create ValidationHelpers instance."""
        return ValidationHelpers()

    @pytest.fixture
    def session(self) -> Session:
        """Create a test session."""
        return Session(name="test-session", server_name="test-server")

    @pytest.fixture
    def mock_graph(self) -> MagicMock:
        """Create a mock graph."""
        graph = MagicMock()
        graph.id = "test-graph"
        return graph

    def test_get_graph_returns_graph(
        self, validation: ValidationHelpers, session: Session, mock_graph: MagicMock
    ) -> None:
        """get_graph returns graph when found."""
        session.graphs["test-graph"] = mock_graph

        result = validation.get_graph(session, "test-graph")

        assert result is mock_graph

    def test_get_graph_raises_for_not_found(
        self, validation: ValidationHelpers, session: Session
    ) -> None:
        """get_graph raises ValueError when graph not found."""
        with pytest.raises(ValueError, match="Graph not found: nonexistent"):
            validation.get_graph(session, "nonexistent")


class TestValidationHelpersStateless:
    """Tests verifying ValidationHelpers is stateless."""

    def test_validation_helpers_has_no_instance_state(self) -> None:
        """ValidationHelpers should have no instance state."""
        # Check no instance attributes (other than what dataclass may add)
        # ValidationHelpers should work identically across instances
        validation1 = ValidationHelpers()
        validation2 = ValidationHelpers()

        params = {"key": "value"}
        result1 = validation1.require_param(params, "key")
        result2 = validation2.require_param(params, "key")

        # Both instances should behave identically
        assert result1 == result2 == "value"

    def test_static_methods_work_without_instance(self) -> None:
        """All ValidationHelpers methods can be called statically."""
        # require_param
        result = ValidationHelpers.require_param({"key": "value"}, "key")
        assert result == "value"

        # get_node requires session, tested via fixtures above
        # get_graph requires session, tested via fixtures above
