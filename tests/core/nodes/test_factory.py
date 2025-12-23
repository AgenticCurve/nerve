"""Tests for nerve.core.nodes.factory module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nerve.core.nodes.base import FunctionNode
from nerve.core.nodes.factory import BackendType, NodeFactory
from nerve.core.nodes.graph import Graph
from nerve.core.nodes.terminal import ClaudeWezTermNode, PTYNode, WezTermNode


def create_mock_pty_backend():
    """Create a mock PTY backend for testing."""
    mock = MagicMock()
    mock.buffer = ""
    mock.start = AsyncMock()
    mock.stop = AsyncMock()
    mock.write = AsyncMock()
    mock.read_stream = MagicMock(return_value=AsyncMock(__anext__=AsyncMock(side_effect=StopAsyncIteration)))
    return mock


def create_mock_wezterm_backend():
    """Create a mock WezTerm backend for testing."""
    mock = MagicMock()
    mock.buffer = ""
    mock.pane_id = "42"
    mock.start = AsyncMock()
    mock.stop = AsyncMock()
    mock.attach = AsyncMock()
    mock.write = AsyncMock()
    mock.focus = AsyncMock()
    mock.get_pane_info = AsyncMock(return_value={"pane_id": "42"})
    mock.clear_buffer = MagicMock()
    return mock


class TestNodeFactory:
    """Tests for NodeFactory."""

    def test_factory_creation_defaults(self):
        """Test factory creation with defaults."""
        factory = NodeFactory()

        assert factory.server_name == "default"
        assert factory.history_base_dir is None

    def test_factory_creation_with_args(self, tmp_path):
        """Test factory creation with arguments."""
        factory = NodeFactory(
            server_name="test-server",
            history_base_dir=tmp_path,
        )

        assert factory.server_name == "test-server"
        assert factory.history_base_dir == tmp_path

    @pytest.mark.asyncio
    async def test_create_terminal_pty(self):
        """Test creating PTY terminal node."""
        mock_backend = create_mock_pty_backend()
        factory = NodeFactory()

        with patch(
            "nerve.core.nodes.terminal.PTYBackend", return_value=mock_backend
        ), patch("asyncio.sleep", new_callable=AsyncMock):
            node = await factory.create_terminal(
                node_id="test-pty",
                command="bash",
                backend=BackendType.PTY,
                history=False,
            )

            assert isinstance(node, PTYNode)
            assert node.id == "test-pty"
            await node.stop()

    @pytest.mark.asyncio
    async def test_create_terminal_pty_string_backend(self):
        """Test creating PTY terminal node with string backend."""
        mock_backend = create_mock_pty_backend()
        factory = NodeFactory()

        with patch(
            "nerve.core.nodes.terminal.PTYBackend", return_value=mock_backend
        ), patch("asyncio.sleep", new_callable=AsyncMock):
            node = await factory.create_terminal(
                node_id="test-pty",
                command="bash",
                backend="pty",
                history=False,
            )

            assert isinstance(node, PTYNode)
            await node.stop()

    @pytest.mark.asyncio
    async def test_create_terminal_wezterm(self):
        """Test creating WezTerm terminal node."""
        mock_backend = create_mock_wezterm_backend()
        factory = NodeFactory()

        with patch(
            "nerve.core.nodes.terminal.WezTermBackend", return_value=mock_backend
        ), patch("asyncio.sleep", new_callable=AsyncMock):
            node = await factory.create_terminal(
                node_id="test-wezterm",
                command="bash",
                backend=BackendType.WEZTERM,
                history=False,
            )

            assert isinstance(node, WezTermNode)
            assert node.id == "test-wezterm"
            await node.stop()

    @pytest.mark.asyncio
    async def test_create_terminal_wezterm_attach(self):
        """Test attaching to existing WezTerm pane."""
        mock_backend = create_mock_wezterm_backend()
        factory = NodeFactory()

        with patch(
            "nerve.core.nodes.terminal.WezTermBackend", return_value=mock_backend
        ), patch("asyncio.sleep", new_callable=AsyncMock):
            node = await factory.create_terminal(
                node_id="test-attach",
                pane_id="existing-pane",
                history=False,
            )

            assert isinstance(node, WezTermNode)
            assert node.id == "test-attach"
            await node.stop()

    @pytest.mark.asyncio
    async def test_create_terminal_claude_wezterm(self):
        """Test creating ClaudeWezTerm terminal node."""
        mock_backend = create_mock_wezterm_backend()
        factory = NodeFactory()

        with patch(
            "nerve.core.nodes.terminal.WezTermBackend", return_value=mock_backend
        ), patch("asyncio.sleep", new_callable=AsyncMock):
            node = await factory.create_terminal(
                node_id="test-claude",
                command="claude",
                backend=BackendType.CLAUDE_WEZTERM,
                history=False,
            )

            assert isinstance(node, ClaudeWezTermNode)
            assert node.id == "test-claude"
            await node.stop()

    @pytest.mark.asyncio
    async def test_create_terminal_claude_requires_command(self):
        """Test that claude-wezterm backend requires command."""
        factory = NodeFactory()

        with pytest.raises(ValueError, match="command is required"):
            await factory.create_terminal(
                node_id="test",
                backend=BackendType.CLAUDE_WEZTERM,
                history=False,
            )

    @pytest.mark.asyncio
    async def test_create_terminal_requires_node_id(self):
        """Test that create_terminal requires node_id."""
        factory = NodeFactory()

        with pytest.raises(ValueError, match="node_id is required"):
            await factory.create_terminal(node_id="", history=False)

    @pytest.mark.asyncio
    async def test_create_terminal_with_history(self, tmp_path):
        """Test creating terminal node with history enabled."""
        mock_backend = create_mock_pty_backend()
        factory = NodeFactory(
            server_name="test-server",
            history_base_dir=tmp_path,
        )

        with patch(
            "nerve.core.nodes.terminal.PTYBackend", return_value=mock_backend
        ), patch("asyncio.sleep", new_callable=AsyncMock):
            node = await factory.create_terminal(
                node_id="test-history",
                command="bash",
                history=True,
            )

            assert isinstance(node, PTYNode)
            # History file should be created
            history_path = tmp_path / "test-server" / "test-history.jsonl"
            assert history_path.exists()
            await node.stop()

    def test_create_function(self):
        """Test creating function node."""
        factory = NodeFactory()

        def my_fn(ctx):
            return ctx.input.upper()

        node = factory.create_function(
            node_id="upper",
            fn=my_fn,
        )

        assert isinstance(node, FunctionNode)
        assert node.id == "upper"

    def test_create_function_async(self):
        """Test creating function node with async function."""
        factory = NodeFactory()

        async def async_fn(ctx):
            return ctx.input.upper()

        node = factory.create_function(
            node_id="async-upper",
            fn=async_fn,
        )

        assert isinstance(node, FunctionNode)
        assert node.id == "async-upper"

    def test_create_graph(self):
        """Test creating graph node."""
        factory = NodeFactory()

        graph = factory.create_graph("my-pipeline")

        assert isinstance(graph, Graph)
        assert graph.id == "my-pipeline"
        assert len(graph) == 0  # Empty graph

    @pytest.mark.asyncio
    async def test_stop_node(self):
        """Test stopping a terminal node."""
        mock_backend = create_mock_pty_backend()
        factory = NodeFactory()

        with patch(
            "nerve.core.nodes.terminal.PTYBackend", return_value=mock_backend
        ), patch("asyncio.sleep", new_callable=AsyncMock):
            node = await factory.create_terminal(
                node_id="test-stop",
                command="bash",
                history=False,
            )

            await factory.stop_node(node)

            mock_backend.stop.assert_called()


class TestBackendType:
    """Tests for BackendType enum."""

    def test_backend_values(self):
        """Test BackendType enum values."""
        assert BackendType.PTY.value == "pty"
        assert BackendType.WEZTERM.value == "wezterm"
        assert BackendType.CLAUDE_WEZTERM.value == "claude-wezterm"

    def test_backend_from_string(self):
        """Test creating BackendType from string."""
        assert BackendType("pty") == BackendType.PTY
        assert BackendType("wezterm") == BackendType.WEZTERM
        assert BackendType("claude-wezterm") == BackendType.CLAUDE_WEZTERM
