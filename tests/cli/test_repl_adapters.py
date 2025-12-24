"""Tests for REPL session adapters."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from nerve.frontends.cli.repl.adapters import (
    LocalSessionAdapter,
    RemoteSessionAdapter,
    SessionAdapter,
)


class TestSessionAdapterProtocol:
    """Tests for SessionAdapter Protocol."""

    def test_session_adapter_is_protocol(self):
        """SessionAdapter is a Protocol (structural typing)."""
        # SessionAdapter should be a Protocol with required methods
        assert hasattr(SessionAdapter, "__annotations__")

    def test_local_adapter_implements_protocol(self):
        """LocalSessionAdapter implements SessionAdapter protocol."""
        session = Mock()
        session.name = "test"
        session.id = "test-id"
        session.nodes = {}
        session.graphs = {}

        adapter = LocalSessionAdapter(session)

        # Check protocol methods exist
        assert hasattr(adapter, "name")
        assert hasattr(adapter, "id")
        assert hasattr(adapter, "node_count")
        assert hasattr(adapter, "graph_count")
        assert hasattr(adapter, "list_nodes")
        assert hasattr(adapter, "list_graphs")
        assert hasattr(adapter, "get_graph")
        assert hasattr(adapter, "delete_node")
        assert hasattr(adapter, "execute_on_node")
        assert hasattr(adapter, "stop")

    def test_remote_adapter_implements_protocol(self):
        """RemoteSessionAdapter implements SessionAdapter protocol."""
        client = Mock()
        adapter = RemoteSessionAdapter(client, "test-server", "test-session")

        # Check protocol methods exist
        assert hasattr(adapter, "name")
        assert hasattr(adapter, "id")
        assert hasattr(adapter, "node_count")
        assert hasattr(adapter, "graph_count")
        assert hasattr(adapter, "list_nodes")
        assert hasattr(adapter, "list_graphs")
        assert hasattr(adapter, "get_graph")
        assert hasattr(adapter, "delete_node")
        assert hasattr(adapter, "execute_on_node")
        assert hasattr(adapter, "stop")


class TestLocalSessionAdapter:
    """Tests for LocalSessionAdapter."""

    def test_local_adapter_creation(self):
        """LocalSessionAdapter can be created with a session."""
        session = Mock()
        session.name = "test-session"
        session.id = "test-id"

        adapter = LocalSessionAdapter(session)

        assert adapter.session == session
        assert adapter.name == "test-session"
        assert adapter.id == "test-id"

    def test_local_adapter_node_count(self):
        """LocalSessionAdapter returns correct node count."""
        session = Mock()
        session.nodes = {"node1": Mock(), "node2": Mock(), "node3": Mock()}

        adapter = LocalSessionAdapter(session)

        assert adapter.node_count == 3

    def test_local_adapter_graph_count(self):
        """LocalSessionAdapter returns correct graph count."""
        session = Mock()
        session.graphs = {"graph1": Mock(), "graph2": Mock()}

        adapter = LocalSessionAdapter(session)

        assert adapter.graph_count == 2

    @pytest.mark.asyncio
    async def test_local_adapter_list_nodes_with_state(self):
        """LocalSessionAdapter lists nodes with state."""
        node1 = Mock()
        node1.state.name = "READY"

        node2 = Mock()
        node2.state.name = "BUSY"

        session = Mock()
        session.nodes = {"node1": node1, "node2": node2}

        adapter = LocalSessionAdapter(session)
        nodes = await adapter.list_nodes()

        assert len(nodes) == 2
        assert ("node1", "READY") in nodes
        assert ("node2", "BUSY") in nodes

    @pytest.mark.asyncio
    async def test_local_adapter_list_nodes_without_state(self):
        """LocalSessionAdapter handles nodes without state attribute."""
        node1 = Mock(spec=[])  # No state attribute
        node1.__class__.__name__ = "FunctionNode"

        session = Mock()
        session.nodes = {"func1": node1}

        adapter = LocalSessionAdapter(session)
        nodes = await adapter.list_nodes()

        assert len(nodes) == 1
        assert ("func1", "FunctionNode") in nodes

    @pytest.mark.asyncio
    async def test_local_adapter_list_graphs(self):
        """LocalSessionAdapter lists graphs."""
        session = Mock()
        session.list_graphs.return_value = ["graph1", "graph2"]

        adapter = LocalSessionAdapter(session)
        graphs = await adapter.list_graphs()

        assert graphs == ["graph1", "graph2"]

    @pytest.mark.asyncio
    async def test_local_adapter_get_graph(self):
        """LocalSessionAdapter gets graph by ID."""
        mock_graph = Mock()
        session = Mock()
        session.get_graph.return_value = mock_graph

        adapter = LocalSessionAdapter(session)
        graph = await adapter.get_graph("graph1")

        assert graph == mock_graph
        session.get_graph.assert_called_once_with("graph1")

    @pytest.mark.asyncio
    async def test_local_adapter_delete_node(self):
        """LocalSessionAdapter deletes node."""
        session = Mock()
        session.delete_node = AsyncMock(return_value=True)

        adapter = LocalSessionAdapter(session)
        result = await adapter.delete_node("node1")

        assert result is True
        session.delete_node.assert_called_once_with("node1")

    @pytest.mark.asyncio
    async def test_local_adapter_execute_on_node(self):
        """LocalSessionAdapter executes on node."""
        from nerve.core.nodes.context import ExecutionContext

        # Mock node with execute method
        mock_result = Mock()
        mock_result.raw = "test response"

        mock_node = Mock()
        mock_node.execute = AsyncMock(return_value=mock_result)

        session = Mock()
        session.get_node.return_value = mock_node

        adapter = LocalSessionAdapter(session)
        response = await adapter.execute_on_node("node1", "test input")

        assert response == "test response"
        session.get_node.assert_called_once_with("node1")
        mock_node.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_local_adapter_execute_on_nonexistent_node(self):
        """LocalSessionAdapter raises error for nonexistent node."""
        session = Mock()
        session.get_node.return_value = None

        adapter = LocalSessionAdapter(session)

        with pytest.raises(ValueError, match="Node not found: node1"):
            await adapter.execute_on_node("node1", "test input")

    @pytest.mark.asyncio
    async def test_local_adapter_stop(self):
        """LocalSessionAdapter stops session."""
        session = Mock()
        session.stop = AsyncMock()

        adapter = LocalSessionAdapter(session)
        await adapter.stop()

        session.stop.assert_called_once()


class TestRemoteSessionAdapter:
    """Tests for RemoteSessionAdapter."""

    def test_remote_adapter_creation_with_session_name(self):
        """RemoteSessionAdapter can be created with session name."""
        client = Mock()
        adapter = RemoteSessionAdapter(client, "test-server", "my-session")

        assert adapter.client == client
        assert adapter.server_name == "test-server"
        assert adapter.name == "my-session"
        assert adapter.id == "my-session"
        assert adapter.session_id == "my-session"

    def test_remote_adapter_creation_without_session_name(self):
        """RemoteSessionAdapter defaults to 'default' session."""
        client = Mock()
        adapter = RemoteSessionAdapter(client, "test-server", None)

        assert adapter.name == "default"
        assert adapter.id == "default"
        assert adapter.session_id is None  # None means use server default

    def test_remote_adapter_node_count_from_cache(self):
        """RemoteSessionAdapter returns node count from cache."""
        client = Mock()
        adapter = RemoteSessionAdapter(client, "test-server", "test-session")

        adapter._cached_nodes_info = [
            {"id": "node1", "type": "PTYNode"},
            {"id": "node2", "type": "WezTermNode"},
        ]

        assert adapter.node_count == 2

    def test_remote_adapter_graph_count_from_cache(self):
        """RemoteSessionAdapter returns graph count from cache."""
        client = Mock()
        adapter = RemoteSessionAdapter(client, "test-server", "test-session")

        adapter._cached_graphs = [{"id": "graph1"}, {"id": "graph2"}]

        assert adapter.graph_count == 2

    @pytest.mark.asyncio
    async def test_remote_adapter_list_nodes(self):
        """RemoteSessionAdapter lists nodes from server."""
        from nerve.server.protocols import CommandResult

        client = Mock()
        client.send_command = AsyncMock(
            return_value=CommandResult(
                success=True,
                data={
                    "nodes_info": [
                        {"id": "node1", "type": "PTYNode"},
                        {"id": "node2", "type": "WezTermNode"},
                    ]
                },
            )
        )

        adapter = RemoteSessionAdapter(client, "test-server", "test-session")
        nodes = await adapter.list_nodes()

        assert len(nodes) == 2
        assert ("node1", "PTYNode") in nodes
        assert ("node2", "WezTermNode") in nodes
        # Check cache was updated
        assert len(adapter._cached_nodes_info) == 2

    @pytest.mark.asyncio
    async def test_remote_adapter_list_nodes_adds_session_id(self):
        """RemoteSessionAdapter adds session_id to params."""
        from nerve.server.protocols import Command, CommandType, CommandResult

        client = Mock()
        client.send_command = AsyncMock(
            return_value=CommandResult(success=True, data={"nodes_info": []})
        )

        adapter = RemoteSessionAdapter(client, "test-server", "my-session")
        await adapter.list_nodes()

        # Check that send_command was called with session_id in params
        call_args = client.send_command.call_args
        command = call_args[0][0]
        assert isinstance(command, Command)
        assert command.params.get("session_id") == "my-session"

    @pytest.mark.asyncio
    async def test_remote_adapter_list_graphs(self):
        """RemoteSessionAdapter lists graphs from server."""
        from nerve.server.protocols import CommandResult

        client = Mock()
        client.send_command = AsyncMock(
            return_value=CommandResult(
                success=True,
                data={"graphs": [{"id": "graph1"}, {"id": "graph2"}]},
            )
        )

        adapter = RemoteSessionAdapter(client, "test-server", "test-session")
        graphs = await adapter.list_graphs()

        assert len(graphs) == 2
        assert "graph1" in graphs
        assert "graph2" in graphs

    @pytest.mark.asyncio
    async def test_remote_adapter_get_graph_returns_none(self):
        """RemoteSessionAdapter.get_graph always returns None."""
        client = Mock()
        adapter = RemoteSessionAdapter(client, "test-server", "test-session")

        graph = await adapter.get_graph("graph1")

        assert graph is None

    @pytest.mark.asyncio
    async def test_remote_adapter_delete_node(self):
        """RemoteSessionAdapter deletes node on server."""
        from nerve.server.protocols import CommandResult

        client = Mock()
        client.send_command = AsyncMock(
            return_value=CommandResult(success=True, data={})
        )

        adapter = RemoteSessionAdapter(client, "test-server", "test-session")
        result = await adapter.delete_node("node1")

        assert result is True

    @pytest.mark.asyncio
    async def test_remote_adapter_delete_node_failure(self):
        """RemoteSessionAdapter handles delete failure."""
        from nerve.server.protocols import CommandResult

        client = Mock()
        client.send_command = AsyncMock(
            return_value=CommandResult(success=False, error="Node not found")
        )

        adapter = RemoteSessionAdapter(client, "test-server", "test-session")
        result = await adapter.delete_node("node1")

        assert result is False

    @pytest.mark.asyncio
    async def test_remote_adapter_execute_on_node(self):
        """RemoteSessionAdapter executes on server node."""
        from nerve.server.protocols import CommandResult

        client = Mock()
        client.send_command = AsyncMock(
            return_value=CommandResult(success=True, data={"response": "test output"})
        )

        adapter = RemoteSessionAdapter(client, "test-server", "test-session")
        response = await adapter.execute_on_node("node1", "test input")

        assert response == "test output"

    @pytest.mark.asyncio
    async def test_remote_adapter_execute_on_node_failure(self):
        """RemoteSessionAdapter raises error on execution failure."""
        from nerve.server.protocols import CommandResult

        client = Mock()
        client.send_command = AsyncMock(
            return_value=CommandResult(success=False, error="Execution failed")
        )

        adapter = RemoteSessionAdapter(client, "test-server", "test-session")

        with pytest.raises(ValueError, match="Execution failed"):
            await adapter.execute_on_node("node1", "test input")

    @pytest.mark.asyncio
    async def test_remote_adapter_stop(self):
        """RemoteSessionAdapter disconnects from server."""
        client = Mock()
        client.disconnect = AsyncMock()

        adapter = RemoteSessionAdapter(client, "test-server", "test-session")
        await adapter.stop()

        client.disconnect.assert_called_once()
