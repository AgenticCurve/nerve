"""Tests for graph CLI commands."""

from __future__ import annotations

from nerve.frontends.cli.server.graph import (
    graph,
    graph_run,
)


class TestGraphCLI:
    """Tests for nerve graph commands."""

    def test_graph_group_exists(self):
        """Graph command group is defined."""
        assert graph is not None
        assert callable(graph)

    def test_graph_run_command_exists(self):
        """Graph run command is defined."""
        assert graph_run is not None
        assert callable(graph_run)

    def test_graph_run_has_server_option(self):
        """Graph run has --server option."""
        params = graph_run.params
        param_names = [p.name for p in params]
        assert "server_name" in param_names

    def test_graph_run_has_dry_run_option(self):
        """Graph run has --dry-run option."""
        params = graph_run.params
        param_names = [p.name for p in params]
        assert "dry_run" in param_names
