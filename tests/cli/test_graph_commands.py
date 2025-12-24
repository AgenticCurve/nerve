"""Tests for graph CLI commands."""

from __future__ import annotations

from nerve.frontends.cli.server.graph import (
    graph,
    graph_create,
    graph_delete,
    graph_info,
    graph_list,
    graph_run,
)


class TestGraphCLI:
    """Tests for nerve graph commands."""

    def test_graph_group_exists(self):
        """Graph command group is defined."""
        assert graph is not None
        assert callable(graph)

    def test_graph_list_command_exists(self):
        """Graph list command is defined."""
        assert graph_list is not None
        assert callable(graph_list)

    def test_graph_create_command_exists(self):
        """Graph create command is defined."""
        assert graph_create is not None
        assert callable(graph_create)

    def test_graph_delete_command_exists(self):
        """Graph delete command is defined."""
        assert graph_delete is not None
        assert callable(graph_delete)

    def test_graph_info_command_exists(self):
        """Graph info command is defined."""
        assert graph_info is not None
        assert callable(graph_info)

    def test_graph_run_command_exists(self):
        """Graph run command is defined."""
        assert graph_run is not None
        assert callable(graph_run)

    def test_graph_list_has_server_option(self):
        """Graph list has --server option."""
        params = graph_list.params
        param_names = [p.name for p in params]
        assert "server_name" in param_names

    def test_graph_create_has_server_option(self):
        """Graph create has --server option."""
        params = graph_create.params
        param_names = [p.name for p in params]
        assert "server_name" in param_names

    def test_graph_delete_has_server_option(self):
        """Graph delete has --server option."""
        params = graph_delete.params
        param_names = [p.name for p in params]
        assert "server_name" in param_names

    def test_graph_list_has_session_option(self):
        """Graph list has --session option."""
        params = graph_list.params
        param_names = [p.name for p in params]
        assert "session_id" in param_names

    def test_graph_create_has_session_option(self):
        """Graph create has --session option."""
        params = graph_create.params
        param_names = [p.name for p in params]
        assert "session_id" in param_names
