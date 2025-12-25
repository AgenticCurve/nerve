"""Tests for nerve.frontends.sdk.client module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nerve.frontends.sdk.client import NerveClient, RemoteNode


class TestRemoteNode:
    """Tests for RemoteNode."""

    def test_remote_node_properties(self):
        """Test RemoteNode properties."""
        mock_client = MagicMock()
        node = RemoteNode(id="test-node", command="claude", _client=mock_client)

        assert node.id == "test-node"
        assert node.command == "claude"

    @pytest.mark.asyncio
    async def test_remote_node_send(self):
        """Test RemoteNode.send() method."""
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"response": "Hello back!"}
        mock_client._send_command = AsyncMock(return_value=mock_result)

        node = RemoteNode(id="test-node", command="claude", _client=mock_client)

        await node.send("Hello", parser="claude")

        assert mock_client._send_command.called
        call_args = mock_client._send_command.call_args[0][0]
        assert call_args.params["node_id"] == "test-node"
        assert call_args.params["text"] == "Hello"
        assert call_args.params["parser"] == "claude"

    @pytest.mark.asyncio
    async def test_remote_node_send_error(self):
        """Test RemoteNode.send() handles errors."""
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Node not found"
        mock_client._send_command = AsyncMock(return_value=mock_result)

        node = RemoteNode(id="test-node", command="claude", _client=mock_client)

        with pytest.raises(RuntimeError, match="Node not found"):
            await node.send("Hello")

    @pytest.mark.asyncio
    async def test_remote_node_interrupt(self):
        """Test RemoteNode.interrupt() method."""
        mock_client = MagicMock()
        mock_client._send_command = AsyncMock()

        node = RemoteNode(id="test-node", command="claude", _client=mock_client)

        await node.interrupt()

        assert mock_client._send_command.called
        call_args = mock_client._send_command.call_args[0][0]
        assert call_args.type.name == "SEND_INTERRUPT"
        assert call_args.params["node_id"] == "test-node"

    @pytest.mark.asyncio
    async def test_remote_node_delete(self):
        """Test RemoteNode.delete() method."""
        mock_client = MagicMock()
        mock_client._send_command = AsyncMock()

        node = RemoteNode(id="test-node", command="claude", _client=mock_client)

        await node.delete()

        assert mock_client._send_command.called
        call_args = mock_client._send_command.call_args[0][0]
        assert call_args.type.name == "DELETE_NODE"
        assert call_args.params["node_id"] == "test-node"


class TestNerveClientStandalone:
    """Tests for NerveClient in standalone mode.

    Note: These tests use real Session/PTYNode.create() to test actual behavior.
    """

    @pytest.mark.asyncio
    async def test_standalone_create_node(self, tmp_path):
        """Test creating node in standalone mode."""
        from unittest.mock import patch

        from nerve.core.session import Session

        session = Session(name="test-session")
        client = NerveClient(_standalone_session=session)

        # Mock PTYNode.create to avoid actually spawning a process
        mock_node = MagicMock()
        mock_node.id = "my-node"

        with patch("nerve.core.nodes.terminal.PTYNode.create", new=AsyncMock(return_value=mock_node)):
            node = await client.create_node("my-node", command="claude")

            assert isinstance(node, RemoteNode)
            assert node.id == "my-node"

    @pytest.mark.asyncio
    async def test_standalone_list_nodes(self, tmp_path):
        """Test listing nodes in standalone mode."""
        from unittest.mock import patch

        from nerve.core.session import Session

        session = Session(name="test-session")
        client = NerveClient(_standalone_session=session)

        mock_node = MagicMock()
        mock_node.id = "node-1"

        with patch("nerve.core.nodes.terminal.PTYNode.create", new=AsyncMock(return_value=mock_node)):
            # Create a node
            await client.create_node("node-1", command="bash")

            nodes = await client.list_nodes()

            assert "node-1" in nodes

    @pytest.mark.asyncio
    async def test_standalone_get_node(self, tmp_path):
        """Test getting node in standalone mode."""
        from unittest.mock import patch

        from nerve.core.session import Session

        session = Session(name="test-session")
        client = NerveClient(_standalone_session=session)

        mock_node = MagicMock()
        mock_node.id = "my-node"

        with patch("nerve.core.nodes.terminal.PTYNode.create", new=AsyncMock(return_value=mock_node)):
            # Create a node first
            await client.create_node("my-node", command="claude")

            # Get the node
            node = await client.get_node("my-node")

            assert node is not None
            assert node.id == "my-node"

    @pytest.mark.asyncio
    async def test_standalone_get_node_not_found(self):
        """Test getting non-existent node returns None."""
        from nerve.core.session import Session

        session = Session(name="test-session")
        client = NerveClient(_standalone_session=session)

        node = await client.get_node("nonexistent")

        assert node is None

    @pytest.mark.asyncio
    async def test_create_node_validates_name(self):
        """Test that create_node validates node name."""
        from nerve.core.session import Session

        session = Session(name="test-session")
        client = NerveClient(_standalone_session=session)

        # Invalid name should raise ValueError
        with pytest.raises(ValueError):
            await client.create_node("INVALID_NAME", command="bash")


class TestNerveClientFactory:
    """Tests for NerveClient factory methods."""

    @pytest.mark.asyncio
    async def test_standalone_factory(self):
        """Test NerveClient.standalone() factory."""
        client = await NerveClient.standalone()

        assert client._standalone_session is not None
        assert client._transport is None

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test NerveClient as async context manager."""
        async with await NerveClient.standalone() as client:
            assert client._standalone_session is not None

        # After context, client should be disconnected
        # (no explicit check needed, just verify no exceptions)
