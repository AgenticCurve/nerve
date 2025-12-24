"""Tests for session CLI commands."""

from __future__ import annotations

from nerve.frontends.cli.server.session import (
    session,
    session_create,
    session_delete,
    session_info,
    session_list,
    session_switch,
)


class TestSessionCLI:
    """Tests for nerve session commands."""

    def test_session_group_exists(self):
        """Session command group is defined."""
        assert session is not None
        assert callable(session)

    def test_session_list_command_exists(self):
        """Session list command is defined."""
        assert session_list is not None
        assert callable(session_list)

    def test_session_create_command_exists(self):
        """Session create command is defined."""
        assert session_create is not None
        assert callable(session_create)

    def test_session_delete_command_exists(self):
        """Session delete command is defined."""
        assert session_delete is not None
        assert callable(session_delete)

    def test_session_info_command_exists(self):
        """Session info command is defined."""
        assert session_info is not None
        assert callable(session_info)

    def test_session_switch_command_exists(self):
        """Session switch command is defined."""
        assert session_switch is not None
        assert callable(session_switch)

    def test_session_list_has_server_option(self):
        """Session list has --server option."""
        params = session_list.params
        param_names = [p.name for p in params]
        assert "server_name" in param_names

    def test_session_create_has_server_option(self):
        """Session create has --server option."""
        params = session_create.params
        param_names = [p.name for p in params]
        assert "server_name" in param_names

    def test_session_delete_has_server_option(self):
        """Session delete has --server option."""
        params = session_delete.params
        param_names = [p.name for p in params]
        assert "server_name" in param_names

    def test_session_switch_has_server_option(self):
        """Session switch has --server option."""
        params = session_switch.params
        param_names = [p.name for p in params]
        assert "server_name" in param_names
