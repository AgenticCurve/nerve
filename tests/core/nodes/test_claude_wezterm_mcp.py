"""Tests for ClaudeWezTermNode MCP passthrough support."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nerve.core.nodes.terminal.claude_wezterm_node import ClaudeWezTermNode
from nerve.core.session import Session


class TestClaudeWezTermNodeMCPConfig:
    """Tests for ClaudeWezTermNode MCP config passthrough.

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

    @pytest.fixture
    def sample_mcp_config(self):
        """Sample MCP config for testing."""
        return {
            "filesystem": {
                "command": "npx",
                "args": ["@modelcontextprotocol/server-filesystem", "/tmp"],
            },
            "github": {
                "command": "npx",
                "args": ["@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": "test-token"},
            },
        }

    @pytest.fixture
    async def mcp_node(
        self,
        mock_session,
        mock_inner_node,
        sample_mcp_config,
        request,
    ):
        """Create a ClaudeWezTermNode with MCP config and auto-cleanup.

        Test can customize via indirect params:
        - node_id: Node ID (default: "test-claude")
        - mcp_config: MCP config dict (default: sample_mcp_config)
        - strict_mcp_config: Whether to use strict mode (default: False)
        - use_mcp_config: Whether to use MCP config at all (default: True)
        """
        params: dict[str, Any] = getattr(request, "param", {})
        node_id = params.get("node_id", "test-claude")
        mcp_config = params.get("mcp_config", sample_mcp_config)
        strict_mcp_config = params.get("strict_mcp_config", False)
        use_mcp_config = params.get("use_mcp_config", True)

        with patch(
            "nerve.core.nodes.terminal.claude_wezterm_node.WezTermNode._create_internal",
            return_value=mock_inner_node,
        ):
            node = await ClaudeWezTermNode.create(
                id=node_id,
                session=mock_session,
                command="claude --dangerously-skip-permissions",
                mcp_config=mcp_config if use_mcp_config else None,
                strict_mcp_config=strict_mcp_config,
            )

            yield node

            # Cleanup
            mock_session.nodes.pop(node_id, None)
            if node._mcp_config_path and node._mcp_config_path.exists():
                node._mcp_config_path.unlink()

    async def test_create_with_mcp_config(self, mcp_node, sample_mcp_config):
        """Node creation accepts mcp_config parameter."""
        assert mcp_node._mcp_config == sample_mcp_config
        assert mcp_node._mcp_config_path is not None

    async def test_mcp_config_creates_temp_file(self, mcp_node, sample_mcp_config):
        """MCP config creates a temp file with correct content."""
        assert mcp_node._mcp_config_path is not None
        assert mcp_node._mcp_config_path.exists()

        # Verify file content
        content = json.loads(mcp_node._mcp_config_path.read_text())
        assert "mcpServers" in content
        assert content["mcpServers"] == sample_mcp_config

    async def test_command_includes_mcp_config_flag(self, mcp_node, mock_inner_node):
        """Command includes --mcp-config flag with temp file path."""
        write_calls = mock_inner_node.backend.write.call_args_list
        mcp_config_found = False
        for call in write_calls:
            args = call[0]
            if args and "--mcp-config" in args[0]:
                mcp_config_found = True
                # Verify the path is in the command
                assert str(mcp_node._mcp_config_path) in args[0]
                break

        assert mcp_config_found, (
            f"Expected '--mcp-config' flag in command. Actual writes: {[c[0] for c in write_calls]}"
        )

    @pytest.mark.parametrize("mcp_node", [{"strict_mcp_config": True}], indirect=True)
    async def test_strict_mcp_config_flag(self, mcp_node, mock_inner_node):
        """Command includes --strict-mcp-config flag when enabled."""
        write_calls = mock_inner_node.backend.write.call_args_list
        strict_flag_found = False
        for call in write_calls:
            args = call[0]
            if args and "--strict-mcp-config" in args[0]:
                strict_flag_found = True
                break

        assert strict_flag_found, (
            "Expected '--strict-mcp-config' flag in command. "
            f"Actual writes: {[c[0] for c in write_calls]}"
        )

    async def test_stop_deletes_mcp_config_file(self, mcp_node):
        """Stopping node deletes the MCP config temp file."""
        config_path = mcp_node._mcp_config_path
        assert config_path is not None
        assert config_path.exists()

        # Stop the node
        await mcp_node.stop()

        # File should be deleted
        assert not config_path.exists()

    async def test_to_info_includes_mcp_servers(self, mcp_node):
        """to_info() includes mcp_servers in metadata."""
        info = mcp_node.to_info()
        assert "mcp_servers" in info.metadata
        assert set(info.metadata["mcp_servers"]) == {"filesystem", "github"}

    @pytest.mark.parametrize("mcp_node", [{"use_mcp_config": False}], indirect=True)
    async def test_no_mcp_config_no_file(self, mcp_node):
        """Without mcp_config, no temp file is created."""
        assert mcp_node._mcp_config is None
        assert mcp_node._mcp_config_path is None

        # to_info should not include mcp_servers
        info = mcp_node.to_info()
        assert "mcp_servers" not in info.metadata

    @pytest.mark.parametrize("mcp_node", [{"node_id": "my-special-node"}], indirect=True)
    async def test_mcp_config_file_name_includes_node_id(self, mcp_node):
        """MCP config file name includes node ID for debugging."""
        assert mcp_node._mcp_config_path is not None
        assert "my-special-node" in mcp_node._mcp_config_path.name
