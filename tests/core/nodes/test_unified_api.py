"""Tests for unified node creation API.

These tests verify the new unified API where all nodes take explicit session
parameter and auto-register on creation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nerve.core.nodes.base import FunctionNode
from nerve.core.nodes.bash import BashNode
from nerve.core.nodes.graph import Graph
from nerve.core.session import Session


class TestBashNodeUnifiedAPI:
    """Tests for BashNode with session parameter."""

    def test_bash_node_requires_session(self):
        """BashNode requires session parameter."""
        with pytest.raises(TypeError):
            BashNode(id="bash")  # Missing session

    def test_bash_node_auto_registers(self):
        """BashNode auto-registers in session.nodes on creation."""
        session = Session(name="test")

        bash = BashNode(id="bash", session=session, cwd="/tmp")

        assert "bash" in session.nodes
        assert session.nodes["bash"] is bash

    def test_bash_node_duplicate_id_raises(self):
        """Duplicate node_id raises ValueError."""
        session = Session(name="test")
        BashNode(id="bash", session=session)

        with pytest.raises(ValueError, match="conflicts with existing"):
            BashNode(id="bash", session=session)

    def test_bash_node_invalid_id_raises(self):
        """Invalid node_id raises ValueError."""
        session = Session(name="test")

        with pytest.raises(ValueError):
            BashNode(id="Invalid Name!", session=session)

    def test_bash_node_same_id_different_sessions(self):
        """Same node_id allowed in different sessions."""
        session1 = Session(name="session1")
        session2 = Session(name="session2")

        bash1 = BashNode(id="bash", session=session1)
        bash2 = BashNode(id="bash", session=session2)

        assert bash1 in session1.nodes.values()
        assert bash2 in session2.nodes.values()
        assert bash1 is not bash2


class TestFunctionNodeUnifiedAPI:
    """Tests for FunctionNode with session parameter."""

    def test_function_node_requires_session(self):
        """FunctionNode requires session parameter."""
        with pytest.raises(TypeError):
            FunctionNode(id="fn", fn=lambda ctx: ctx.input)  # Missing session

    def test_function_node_auto_registers(self):
        """FunctionNode auto-registers in session.nodes on creation."""
        session = Session(name="test")

        fn = FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

        assert "fn" in session.nodes
        assert session.nodes["fn"] is fn

    def test_function_node_duplicate_id_raises(self):
        """Duplicate node_id raises ValueError."""
        session = Session(name="test")
        FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

        with pytest.raises(ValueError, match="conflicts with existing"):
            FunctionNode(id="fn", session=session, fn=lambda ctx: ctx.input)

    def test_function_node_sync_callable(self):
        """FunctionNode works with sync callable."""
        session = Session(name="test")

        def my_fn(ctx):
            return ctx.input.upper()

        node = FunctionNode(id="fn", session=session, fn=my_fn)
        assert node.fn is my_fn

    def test_function_node_async_callable(self):
        """FunctionNode works with async callable."""
        session = Session(name="test")

        async def my_async_fn(ctx):
            return ctx.input.upper()

        node = FunctionNode(id="fn", session=session, fn=my_async_fn)
        assert node.fn is my_async_fn


class TestPTYNodeUnifiedAPI:
    """Tests for PTYNode.create() method."""

    def test_pty_node_direct_instantiation_raises(self):
        """Direct PTYNode instantiation raises TypeError."""
        from nerve.core.nodes.terminal import PTYNode

        session = Session(name="test")
        mock_backend = MagicMock()

        with pytest.raises(TypeError, match="Cannot instantiate PTYNode directly"):
            PTYNode(id="pty", session=session, backend=mock_backend)

    @pytest.mark.asyncio
    async def test_pty_node_create_auto_registers(self):
        """PTYNode.create() auto-registers in session.nodes."""
        from nerve.core.nodes.terminal import PTYNode

        session = Session(name="test", history_enabled=False)

        with patch("nerve.core.nodes.terminal.pty_node.PTYBackend") as mock_backend_cls:
            mock_backend = MagicMock()
            mock_backend.start = AsyncMock()
            mock_backend.buffer = ""
            mock_backend.read_stream = MagicMock(return_value=AsyncMock())
            mock_backend_cls.return_value = mock_backend

            node = await PTYNode.create(
                id="pty",
                session=session,
                command="bash",
            )

            assert "pty" in session.nodes
            assert session.nodes["pty"] is node

    @pytest.mark.asyncio
    async def test_pty_node_create_duplicate_raises(self):
        """Duplicate node_id raises ValueError."""
        from nerve.core.nodes.terminal import PTYNode

        session = Session(name="test", history_enabled=False)

        # Add existing node
        mock_existing = MagicMock()
        session.nodes["pty"] = mock_existing

        with pytest.raises(ValueError, match="conflicts with existing"):
            await PTYNode.create(id="pty", session=session, command="bash")


class TestWezTermNodeUnifiedAPI:
    """Tests for WezTermNode.create() method."""

    def test_wezterm_node_direct_instantiation_raises(self):
        """Direct WezTermNode instantiation raises TypeError."""
        from nerve.core.nodes.terminal import WezTermNode

        session = Session(name="test")
        mock_backend = MagicMock()

        with pytest.raises(TypeError, match="Cannot instantiate WezTermNode directly"):
            WezTermNode(id="wez", session=session, backend=mock_backend)

    @pytest.mark.asyncio
    async def test_wezterm_node_create_auto_registers(self):
        """WezTermNode.create() auto-registers in session.nodes."""
        from nerve.core.nodes.terminal import WezTermNode

        session = Session(name="test", history_enabled=False)

        with patch("nerve.core.nodes.terminal.wezterm_node.WezTermBackend") as mock_backend_cls:
            mock_backend = MagicMock()
            mock_backend.start = AsyncMock()
            mock_backend.pane_id = "12345"
            mock_backend_cls.return_value = mock_backend

            node = await WezTermNode.create(
                id="wez",
                session=session,
                command="bash",
            )

            assert "wez" in session.nodes
            assert session.nodes["wez"] is node

    @pytest.mark.asyncio
    async def test_wezterm_node_attach_auto_registers(self):
        """WezTermNode.attach() auto-registers in session.nodes."""
        from nerve.core.nodes.terminal import WezTermNode

        session = Session(name="test", history_enabled=False)

        with patch("nerve.core.nodes.terminal.wezterm_node.WezTermBackend") as mock_backend_cls:
            mock_backend = MagicMock()
            mock_backend.attach = AsyncMock()
            mock_backend_cls.return_value = mock_backend

            node = await WezTermNode.attach(
                id="wez",
                session=session,
                pane_id="12345",
            )

            assert "wez" in session.nodes
            assert session.nodes["wez"] is node


class TestClaudeWezTermNodeUnifiedAPI:
    """Tests for ClaudeWezTermNode.create() method."""

    def test_claude_node_direct_instantiation_raises(self):
        """Direct ClaudeWezTermNode instantiation raises TypeError."""
        from nerve.core.nodes.terminal import ClaudeWezTermNode, WezTermNode

        session = Session(name="test")
        # Create a mock inner node using object.__new__ to bypass check
        mock_inner = object.__new__(WezTermNode)
        mock_inner._created_via_create = True

        with pytest.raises(TypeError, match="Cannot instantiate ClaudeWezTermNode directly"):
            ClaudeWezTermNode(id="claude", session=session, _inner=mock_inner)

    @pytest.mark.asyncio
    async def test_claude_node_create_auto_registers(self):
        """ClaudeWezTermNode.create() auto-registers in session.nodes."""
        from nerve.core.nodes.terminal import ClaudeWezTermNode

        session = Session(name="test", history_enabled=False)

        with patch("nerve.core.nodes.terminal.wezterm_node.WezTermBackend") as mock_backend_cls:
            mock_backend = MagicMock()
            mock_backend.start = AsyncMock()
            mock_backend.pane_id = "12345"
            mock_backend.write = AsyncMock()
            mock_backend_cls.return_value = mock_backend

            node = await ClaudeWezTermNode.create(
                id="claude",
                session=session,
                command="claude --dangerously-skip-permissions",
            )

            assert "claude" in session.nodes
            assert session.nodes["claude"] is node

    @pytest.mark.asyncio
    async def test_claude_node_command_must_contain_claude(self):
        """Command must contain 'claude'."""
        from nerve.core.nodes.terminal import ClaudeWezTermNode

        session = Session(name="test", history_enabled=False)

        with pytest.raises(ValueError, match="must contain 'claude'"):
            await ClaudeWezTermNode.create(
                id="claude",
                session=session,
                command="bash",  # No 'claude' in command
            )


class TestGraphUnifiedAPI:
    """Tests for Graph with session parameter."""

    def test_graph_auto_registers(self):
        """Graph auto-registers in session.graphs on creation."""
        session = Session(name="test")

        graph = Graph(id="pipeline", session=session)

        assert "pipeline" in session.graphs
        assert session.graphs["pipeline"] is graph

    def test_graph_duplicate_id_raises(self):
        """Duplicate graph_id raises ValueError."""
        session = Session(name="test")
        Graph(id="pipeline", session=session)

        with pytest.raises(ValueError, match="conflicts with existing"):
            Graph(id="pipeline", session=session)

    def test_graph_has_session_property(self):
        """Graph exposes session as property."""
        session = Session(name="test")

        graph = Graph(id="pipeline", session=session)

        assert graph.session is session

    def test_graph_empty_id_raises(self):
        """Empty graph_id raises ValueError."""
        session = Session(name="test")

        with pytest.raises(ValueError, match="cannot be empty"):
            Graph(id="", session=session)


class TestCrossNodeIntegration:
    """Integration tests for unified node API."""

    def test_nodes_and_graphs_same_session(self):
        """Multiple node types can be created in same session."""
        session = Session(name="test")

        # Create various nodes (auto-registered in session)
        BashNode(id="bash", session=session)
        FunctionNode(id="func", session=session, fn=lambda ctx: ctx.input)
        Graph(id="pipeline", session=session)

        # All should be registered
        assert "bash" in session.nodes
        assert "func" in session.nodes
        assert "pipeline" in session.graphs

    def test_node_id_uniqueness_across_types(self):
        """Same ID cannot be used for different node types."""
        session = Session(name="test")

        BashNode(id="node", session=session)

        # Cannot create FunctionNode with same ID
        with pytest.raises(ValueError, match="conflicts with existing"):
            FunctionNode(id="node", session=session, fn=lambda ctx: ctx.input)

    def test_node_graph_cross_type_collision(self):
        """Same ID cannot be used for both node and graph."""
        session = Session(name="test")

        # Create a node first
        BashNode(id="pipeline", session=session)

        # Cannot create Graph with same ID as existing node
        with pytest.raises(ValueError, match="conflicts with existing node"):
            Graph(id="pipeline", session=session)

    def test_graph_node_cross_type_collision(self):
        """Same ID cannot be used for both graph and node."""
        session = Session(name="test")

        # Create a graph first
        Graph(id="runner", session=session)

        # Cannot create BashNode with same ID as existing graph
        with pytest.raises(ValueError, match="conflicts with existing graph"):
            BashNode(id="runner", session=session)
