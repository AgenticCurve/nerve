"""Tests for node CLI commands."""

from __future__ import annotations

import pytest

from nerve.frontends.cli.server.node import (
    node,
    node_create,
    node_delete,
    node_list,
)


class TestNodeCLI:
    """Tests for nerve node commands."""

    def test_node_group_exists(self):
        """Node command group is defined."""
        assert node is not None
        assert callable(node)

    def test_node_create_command_exists(self):
        """Node create command is defined."""
        assert node_create is not None
        assert callable(node_create)

    def test_node_list_command_exists(self):
        """Node list command is defined."""
        assert node_list is not None
        assert callable(node_list)

    def test_node_delete_command_exists(self):
        """Node delete command is defined."""
        assert node_delete is not None
        assert callable(node_delete)

    def test_node_create_has_session_option(self):
        """Node create has --session option."""
        params = node_create.params
        param_names = [p.name for p in params]
        assert "session_id" in param_names

    def test_node_list_has_session_option(self):
        """Node list has --session option."""
        params = node_list.params
        param_names = [p.name for p in params]
        assert "session_id" in param_names

    def test_node_delete_has_session_option(self):
        """Node delete has --session option."""
        params = node_delete.params
        param_names = [p.name for p in params]
        assert "session_id" in param_names

    def test_node_create_has_server_option(self):
        """Node create has --server option."""
        params = node_create.params
        param_names = [p.name for p in params]
        assert "server_name" in param_names

    def test_node_list_has_server_option(self):
        """Node list has --server option."""
        params = node_list.params
        param_names = [p.name for p in params]
        assert "server_name" in param_names

    def test_node_delete_has_server_option(self):
        """Node delete has --server option."""
        params = node_delete.params
        param_names = [p.name for p in params]
        assert "server_name" in param_names
