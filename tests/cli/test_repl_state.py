"""Tests for REPL state management."""

from __future__ import annotations

from nerve.frontends.cli.repl.state import REPLState


class TestREPLState:
    """Tests for REPLState dataclass."""

    def test_repl_state_creation_default(self):
        """REPLState can be created with default values."""
        state = REPLState()
        assert state.namespace == {}
        assert state.history == []
        assert state.nodes == {}

    def test_repl_state_creation_with_data(self):
        """REPLState can be created with initial data."""
        namespace = {"x": 1, "y": 2}
        history = ["print('hello')", "x = 10"]
        nodes = {"node1": "mock_node"}

        state = REPLState(namespace=namespace, history=history, nodes=nodes)

        assert state.namespace == namespace
        assert state.history == history
        assert state.nodes == nodes

    def test_repl_state_namespace_modification(self):
        """REPLState namespace can be modified."""
        state = REPLState()
        state.namespace["test"] = "value"
        assert state.namespace["test"] == "value"
        assert len(state.namespace) == 1

    def test_repl_state_history_append(self):
        """REPLState history can be appended."""
        state = REPLState()
        state.history.append("command1")
        state.history.append("command2")
        assert len(state.history) == 2
        assert state.history[0] == "command1"
        assert state.history[1] == "command2"

    def test_repl_state_nodes_tracking(self):
        """REPLState can track nodes."""
        state = REPLState()
        state.nodes["node1"] = "mock_node_1"
        state.nodes["node2"] = "mock_node_2"
        assert len(state.nodes) == 2
        assert "node1" in state.nodes
        assert "node2" in state.nodes

    def test_repl_state_independent_instances(self):
        """Multiple REPLState instances are independent."""
        state1 = REPLState()
        state2 = REPLState()

        state1.namespace["x"] = 1
        state2.namespace["y"] = 2

        assert "x" in state1.namespace
        assert "x" not in state2.namespace
        assert "y" in state2.namespace
        assert "y" not in state1.namespace
