"""Tests for REPL display functions."""

from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock, Mock

import pytest

from nerve.frontends.cli.repl.display import print_graph, print_help, print_nodes


class TestPrintHelp:
    """Tests for print_help function."""

    def test_print_help_output(self, capsys):
        """print_help displays help text."""
        print_help()
        captured = capsys.readouterr()

        # Check for key sections
        assert "Nerve REPL" in captured.out
        assert "Pre-loaded:" in captured.out
        assert "Python Examples:" in captured.out
        assert "Commands:" in captured.out
        assert "session" in captured.out
        assert "nodes" in captured.out
        assert "graphs" in captured.out
        assert "help" in captured.out
        assert "exit" in captured.out

    def test_print_help_shows_commands(self, capsys):
        """print_help displays all command categories."""
        print_help()
        captured = capsys.readouterr()

        # Check for command categories
        assert "Session:" in captured.out
        assert "Nodes:" in captured.out
        assert "Graphs:" in captured.out
        assert "Other:" in captured.out


class TestPrintNodes:
    """Tests for print_nodes function."""

    @pytest.mark.asyncio
    async def test_print_nodes_empty(self, capsys):
        """print_nodes handles empty node list."""
        adapter = AsyncMock()
        adapter.list_nodes.return_value = []

        await print_nodes(adapter)
        captured = capsys.readouterr()

        assert "No active nodes" in captured.out

    @pytest.mark.asyncio
    async def test_print_nodes_with_nodes(self, capsys):
        """print_nodes displays nodes correctly."""
        adapter = AsyncMock()
        adapter.list_nodes.return_value = [
            ("node1", "READY"),
            ("node2", "BUSY"),
            ("node3", "PTYNode"),
        ]

        await print_nodes(adapter)
        captured = capsys.readouterr()

        assert "Active Nodes:" in captured.out
        assert "node1: READY" in captured.out
        assert "node2: BUSY" in captured.out
        assert "node3: PTYNode" in captured.out
        assert "-" * 40 in captured.out

    @pytest.mark.asyncio
    async def test_print_nodes_calls_adapter(self):
        """print_nodes calls adapter.list_nodes()."""
        adapter = AsyncMock()
        adapter.list_nodes.return_value = []

        await print_nodes(adapter)

        adapter.list_nodes.assert_called_once()


class TestPrintGraph:
    """Tests for print_graph function."""

    def test_print_graph_none(self, capsys):
        """print_graph handles None graph."""
        print_graph(None)
        captured = capsys.readouterr()

        assert "No steps defined" in captured.out

    def test_print_graph_empty_steps(self, capsys):
        """print_graph handles graph with no steps."""
        graph = Mock()
        graph.list_steps.return_value = []

        print_graph(graph)
        captured = capsys.readouterr()

        assert "No steps defined" in captured.out

    def test_print_graph_with_steps(self, capsys):
        """print_graph displays graph structure."""
        # Create mock graph with steps
        step1 = Mock()
        step1.depends_on = []

        step2 = Mock()
        step2.depends_on = ["step1"]

        step3 = Mock()
        step3.depends_on = ["step1", "step2"]

        graph = Mock()
        graph.list_steps.return_value = ["step1", "step2", "step3"]
        graph.get_step.side_effect = lambda step_id: {
            "step1": step1,
            "step2": step2,
            "step3": step3,
        }[step_id]

        print_graph(graph)
        captured = capsys.readouterr()

        assert "Graph Structure:" in captured.out
        assert "step1" in captured.out
        assert "step2" in captured.out
        assert "step3" in captured.out
        assert "depends on: step1" in captured.out
        assert "depends on: step1, step2" in captured.out
        assert "-" * 40 in captured.out

    def test_print_graph_no_dependencies(self, capsys):
        """print_graph handles steps with no dependencies."""
        step1 = Mock()
        step1.depends_on = []

        graph = Mock()
        graph.list_steps.return_value = ["step1"]
        graph.get_step.return_value = step1

        print_graph(graph)
        captured = capsys.readouterr()

        assert "Graph Structure:" in captured.out
        assert "step1" in captured.out
        # Should not print "depends on" for steps with no dependencies
        output_lines = captured.out.split("\n")
        step1_lines = [line for line in output_lines if "step1" in line]
        assert len(step1_lines) == 1  # Only the step name line
