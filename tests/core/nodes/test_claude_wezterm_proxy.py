"""Tests for ClaudeWezTermNode proxy support."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nerve.core.nodes.terminal.claude_wezterm_node import ClaudeWezTermNode
from nerve.core.session import Session


class TestClaudeWezTermNodeProxyUrl:
    """Tests for ClaudeWezTermNode proxy_url parameter.

    All tests mock WezTermNode._create_internal to avoid creating real
    WezTerm panes.
    """

    @pytest.fixture
    def mock_session(self, tmp_path):
        """Create a mock session for testing."""
        session = Session(name="test", server_name="test-server")
        session.history_base_dir = tmp_path
        return session

    @pytest.fixture
    def mock_inner_node(self):
        """Create a mock inner WezTermNode."""
        mock_inner = MagicMock()
        mock_inner.backend = MagicMock()
        mock_inner.backend.write = AsyncMock()
        mock_inner.stop = AsyncMock()
        mock_inner.pane_id = "mock-pane-123"
        return mock_inner

    async def test_create_with_proxy_url(self, mock_session, mock_inner_node):
        """Node creation accepts proxy_url parameter.

        The ClaudeWezTermNode.create() method should accept a proxy_url
        parameter and store it on the node.
        """
        with patch(
            "nerve.core.nodes.terminal.claude_wezterm_node.WezTermNode._create_internal",
            return_value=mock_inner_node,
        ):
            node = await ClaudeWezTermNode.create(
                id="test-claude",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
                proxy_url="http://127.0.0.1:34567",
            )

            try:
                # Verify proxy_url is stored
                assert node._proxy_url == "http://127.0.0.1:34567"
            finally:
                # Cleanup - remove from session to avoid dangling references
                mock_session.nodes.pop("test-claude", None)

    async def test_proxy_url_exports_anthropic_base_url(self, mock_session, mock_inner_node):
        """Verify ANTHROPIC_BASE_URL env var is exported when proxy_url is set.

        When proxy_url is provided, the node should export ANTHROPIC_BASE_URL
        environment variable in the shell before running the claude command.
        """
        with patch(
            "nerve.core.nodes.terminal.claude_wezterm_node.WezTermNode._create_internal",
            return_value=mock_inner_node,
        ):
            await ClaudeWezTermNode.create(
                id="test-claude",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
                proxy_url="http://127.0.0.1:34567",
            )

            try:
                # Check that the export command was written
                write_calls = mock_inner_node.backend.write.call_args_list
                export_call_found = False
                for call in write_calls:
                    args = call[0]
                    if args and "export ANTHROPIC_BASE_URL=http://127.0.0.1:34567" in args[0]:
                        export_call_found = True
                        break

                assert export_call_found, (
                    "Expected 'export ANTHROPIC_BASE_URL=...' to be written. "
                    f"Actual writes: {[c[0] for c in write_calls]}"
                )
            finally:
                mock_session.nodes.pop("test-claude", None)

    async def test_to_info_includes_proxy_url(self, mock_session, mock_inner_node):
        """Verify to_info() includes proxy_url in metadata.

        When a node has a proxy_url, the to_info() method should include
        it in the metadata dictionary.
        """
        with patch(
            "nerve.core.nodes.terminal.claude_wezterm_node.WezTermNode._create_internal",
            return_value=mock_inner_node,
        ):
            node = await ClaudeWezTermNode.create(
                id="test-claude",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
                proxy_url="http://127.0.0.1:34567",
            )

            try:
                # Get node info
                info = node.to_info()

                # Verify proxy_url is in metadata
                assert "proxy_url" in info.metadata
                assert info.metadata["proxy_url"] == "http://127.0.0.1:34567"
            finally:
                mock_session.nodes.pop("test-claude", None)

    async def test_to_info_excludes_proxy_url_when_none(self, mock_session, mock_inner_node):
        """Verify to_info() excludes proxy_url when not set.

        When a node doesn't have a proxy_url, the to_info() method should
        not include proxy_url in the metadata dictionary.
        """
        with patch(
            "nerve.core.nodes.terminal.claude_wezterm_node.WezTermNode._create_internal",
            return_value=mock_inner_node,
        ):
            node = await ClaudeWezTermNode.create(
                id="test-claude",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
                # No proxy_url
            )

            try:
                # Get node info
                info = node.to_info()

                # Verify proxy_url is NOT in metadata
                assert "proxy_url" not in info.metadata
            finally:
                mock_session.nodes.pop("test-claude", None)

    async def test_no_export_when_proxy_url_not_set(self, mock_session, mock_inner_node):
        """Verify no export when proxy_url is not set.

        When proxy_url is not provided, no ANTHROPIC_BASE_URL export
        should be written.
        """
        with patch(
            "nerve.core.nodes.terminal.claude_wezterm_node.WezTermNode._create_internal",
            return_value=mock_inner_node,
        ):
            await ClaudeWezTermNode.create(
                id="test-claude",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
                # No proxy_url
            )

            try:
                # Check that no export command was written
                write_calls = mock_inner_node.backend.write.call_args_list
                for call in write_calls:
                    args = call[0]
                    if args:
                        assert "ANTHROPIC_BASE_URL" not in args[0], (
                            f"Unexpected ANTHROPIC_BASE_URL export: {args[0]}"
                        )
            finally:
                mock_session.nodes.pop("test-claude", None)
