"""Tests for Session factory methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nerve.core.session import Session


class TestSessionCreateNode:
    """Tests for Session.create_node()."""

    @pytest.mark.asyncio
    async def test_create_node_auto_registers(self):
        """Node is automatically registered in session.nodes."""
        session = Session()

        with patch("nerve.core.nodes.terminal.PTYNode") as mock_pty:
            mock_node = MagicMock()
            mock_node.id = "test-node"
            mock_pty._create = AsyncMock(return_value=mock_node)

            node = await session.create_node("test-node", command="bash")

            assert "test-node" in session.nodes
            assert session.nodes["test-node"] is node

    @pytest.mark.asyncio
    async def test_create_node_duplicate_id_raises(self):
        """Duplicate node_id raises ValueError."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "existing"
        session.nodes["existing"] = mock_node

        with pytest.raises(ValueError, match="already exists"):
            await session.create_node("existing", command="bash")

    @pytest.mark.asyncio
    async def test_create_node_empty_id_raises(self):
        """Empty node_id raises ValueError."""
        session = Session()

        with pytest.raises(ValueError, match="required"):
            await session.create_node("", command="bash")

    @pytest.mark.asyncio
    async def test_create_node_string_backend(self):
        """Backend can be string or BackendType enum."""
        session = Session()

        with patch("nerve.core.nodes.terminal.PTYNode") as mock_pty:
            mock_node = MagicMock()
            mock_node.id = "test"
            mock_pty._create = AsyncMock(return_value=mock_node)

            # String backend
            await session.create_node("test", command="bash", backend="pty")
            mock_pty._create.assert_called()

    @pytest.mark.asyncio
    async def test_create_node_history_disabled(self):
        """No history writer when history=False."""
        session = Session()

        with patch("nerve.core.nodes.terminal.PTYNode") as mock_pty:
            mock_node = MagicMock()
            mock_node.id = "test"
            mock_pty._create = AsyncMock(return_value=mock_node)

            await session.create_node("test", command="bash", history=False)

            # Verify history_writer is None in the call
            call_kwargs = mock_pty._create.call_args[1]
            assert call_kwargs.get("history_writer") is None

    @pytest.mark.asyncio
    async def test_create_node_inherits_session_history_setting(self):
        """Node inherits session.history_enabled when history=None."""
        session = Session(history_enabled=False)

        with patch("nerve.core.nodes.terminal.PTYNode") as mock_pty:
            mock_node = MagicMock()
            mock_node.id = "test"
            mock_pty._create = AsyncMock(return_value=mock_node)

            await session.create_node("test", command="bash")

            call_kwargs = mock_pty._create.call_args[1]
            assert call_kwargs.get("history_writer") is None


class TestSessionCreateFunction:
    """Tests for Session.create_function()."""

    def test_create_function_sync(self):
        """Create function node with sync callable."""
        session = Session()

        def my_fn(ctx):
            return ctx.input

        node = session.create_function("my-fn", fn=my_fn)

        assert node.id == "my-fn"
        assert "my-fn" in session.nodes

    def test_create_function_async(self):
        """Create function node with async callable."""
        session = Session()

        async def my_async_fn(ctx):
            return ctx.input

        node = session.create_function("my-fn", fn=my_async_fn)

        assert node.id == "my-fn"
        assert "my-fn" in session.nodes

    def test_create_function_auto_registers(self):
        """Function node is auto-registered."""
        session = Session()

        node = session.create_function("fn", fn=lambda ctx: ctx.input)

        assert session.nodes["fn"] is node

    def test_create_function_duplicate_id_raises(self):
        """Duplicate node_id raises ValueError."""
        session = Session()
        session.create_function("fn", fn=lambda ctx: ctx.input)

        with pytest.raises(ValueError, match="already exists"):
            session.create_function("fn", fn=lambda ctx: ctx.input)


class TestSessionCreateGraph:
    """Tests for Session.create_graph()."""

    def test_create_graph(self):
        """Create empty graph."""
        session = Session()

        graph = session.create_graph("my-graph")

        assert graph.id == "my-graph"

    def test_create_graph_auto_registers(self):
        """Graph is registered in session.graphs."""
        session = Session()

        graph = session.create_graph("my-graph")

        assert "my-graph" in session.graphs
        assert session.graphs["my-graph"] is graph

    def test_create_graph_duplicate_id_raises(self):
        """Duplicate graph_id raises ValueError."""
        session = Session()
        session.create_graph("my-graph")

        with pytest.raises(ValueError, match="already exists"):
            session.create_graph("my-graph")


class TestSessionDeleteNode:
    """Tests for Session.delete_node()."""

    @pytest.mark.asyncio
    async def test_delete_node_stops_and_removes(self):
        """Delete stops node and removes from registry."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "test"
        mock_node.stop = AsyncMock()
        session.nodes["test"] = mock_node

        deleted = await session.delete_node("test")

        assert deleted is True
        assert "test" not in session.nodes
        mock_node.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_node_not_found_returns_false(self):
        """Delete returns False if node not found."""
        session = Session()

        deleted = await session.delete_node("nonexistent")

        assert deleted is False


class TestSessionDeleteGraph:
    """Tests for Session.delete_graph()."""

    def test_delete_graph_removes(self):
        """Delete removes graph from registry."""
        session = Session()
        session.create_graph("my-graph")

        deleted = session.delete_graph("my-graph")

        assert deleted is True
        assert "my-graph" not in session.graphs

    def test_delete_graph_not_found_returns_false(self):
        """Delete returns False if graph not found."""
        session = Session()

        deleted = session.delete_graph("nonexistent")

        assert deleted is False


class TestSessionLifecycle:
    """Tests for Session lifecycle methods."""

    @pytest.mark.asyncio
    async def test_stop_stops_all_nodes(self):
        """Session.stop() stops all persistent nodes."""
        session = Session()

        nodes = []
        for i in range(3):
            node = MagicMock()
            node.id = f"node-{i}"
            node.persistent = True
            node.stop = AsyncMock()
            nodes.append(node)
            session.nodes[f"node-{i}"] = node

        await session.stop()

        for node in nodes:
            node.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_clears_registries(self):
        """Session.stop() clears nodes and graphs."""
        session = Session()
        mock_node = MagicMock()
        mock_node.id = "test"
        mock_node.persistent = True
        mock_node.stop = AsyncMock()
        session.nodes["test"] = mock_node
        session.create_graph("graph")

        await session.stop()

        assert len(session.nodes) == 0
        assert len(session.graphs) == 0
