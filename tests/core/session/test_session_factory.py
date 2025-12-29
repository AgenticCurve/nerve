"""Tests for Session lifecycle and registry operations.

Note: Factory method tests have moved to test_unified_api.py as part of the
unified node creation API. This file tests session lifecycle operations.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nerve.core.nodes.graph import Graph
from nerve.core.session import Session


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
        Graph(id="my-graph", session=session)

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
        """Session.stop() stops all stateful nodes."""
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
        Graph(id="graph", session=session)

        await session.stop()

        assert len(session.nodes) == 0
        assert len(session.graphs) == 0
