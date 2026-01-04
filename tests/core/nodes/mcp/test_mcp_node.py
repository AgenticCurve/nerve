"""Tests for MCPNode."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nerve.core.mcp import MCPConnectionError
from nerve.core.nodes import ExecutionContext, NodeState
from nerve.core.nodes.mcp import MCPNode
from nerve.core.nodes.tools import ToolCapable, is_multi_tool_node, is_tool_capable
from nerve.core.session import Session

# Path to mock MCP server
MOCK_SERVER = str(Path(__file__).parents[2] / "mcp" / "mock_mcp_server.py")


@pytest.fixture
def session():
    """Create a test session."""
    return Session(name="test-session")


class TestMCPNodeCreation:
    """Test MCPNode creation and initialization."""

    @pytest.mark.asyncio
    async def test_create_success(self, session):
        """Create MCPNode successfully."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            assert node.id == "test-mcp"
            assert node.state == NodeState.READY
            assert node.persistent is True
            assert "test-mcp" in session.nodes
        finally:
            await node.stop()

    @pytest.mark.asyncio
    async def test_create_discovers_tools(self, session):
        """MCPNode discovers tools on creation."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            tools = node.list_tools()
            assert len(tools) == 3
            tool_names = {t.name for t in tools}
            assert tool_names == {"echo", "add", "fail"}
        finally:
            await node.stop()

    @pytest.mark.asyncio
    async def test_create_connection_failure(self, session):
        """MCPNode creation fails on connection error."""
        with pytest.raises(MCPConnectionError):
            await MCPNode.create(
                id="bad-mcp",
                session=session,
                command="nonexistent-command-12345",
            )

        # Node should not be registered on failure
        assert "bad-mcp" not in session.nodes

    def test_direct_instantiation_raises(self, session):
        """Direct instantiation raises TypeError."""
        with pytest.raises(TypeError, match="Cannot instantiate"):
            MCPNode(id="test", session=session)

    @pytest.mark.asyncio
    async def test_duplicate_id_raises(self, session):
        """Creating node with duplicate ID raises."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            with pytest.raises(ValueError, match="conflicts with existing node"):
                await MCPNode.create(
                    id="test-mcp",
                    session=session,
                    command=sys.executable,
                    args=[MOCK_SERVER],
                )
        finally:
            await node.stop()


class TestMCPNodeToolCapable:
    """Test MCPNode implements ToolCapable protocol."""

    @pytest.mark.asyncio
    async def test_is_tool_capable(self, session):
        """MCPNode implements ToolCapable."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            assert is_tool_capable(node)
            assert isinstance(node, ToolCapable)
        finally:
            await node.stop()

    @pytest.mark.asyncio
    async def test_is_multi_tool_node(self, session):
        """MCPNode is a multi-tool node."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            assert is_multi_tool_node(node)
        finally:
            await node.stop()

    @pytest.mark.asyncio
    async def test_list_tools_returns_definitions(self, session):
        """list_tools returns ToolDefinition objects."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            tools = node.list_tools()
            for tool in tools:
                assert tool.node_id == "test-mcp"
                assert tool.name
                assert isinstance(tool.parameters, dict)
        finally:
            await node.stop()


class TestMCPNodeCallTool:
    """Test MCPNode.call_tool()."""

    @pytest.mark.asyncio
    async def test_call_tool_success(self, session):
        """Call tool successfully."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            result = await node.call_tool("echo", {"message": "hello"})
            assert "hello" in result
        finally:
            await node.stop()

    @pytest.mark.asyncio
    async def test_call_tool_unknown(self, session):
        """Call unknown tool raises ValueError."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            with pytest.raises(ValueError, match="not found"):
                await node.call_tool("nonexistent", {})
        finally:
            await node.stop()

    @pytest.mark.asyncio
    async def test_call_tool_not_ready(self, session):
        """Call tool when not ready raises RuntimeError."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            await node.stop()
            with pytest.raises(RuntimeError, match="not ready"):
                await node.call_tool("echo", {"message": "hello"})
        finally:
            pass  # Already stopped

    @pytest.mark.asyncio
    async def test_call_tool_error_state(self, session):
        """Call tool when in ERROR state raises RuntimeError."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            # Manually transition to ERROR state (simulates connection loss)
            node.state = NodeState.ERROR
            node._error_message = "Simulated connection loss"

            with pytest.raises(RuntimeError, match="ERROR state"):
                await node.call_tool("echo", {"message": "hello"})
        finally:
            await node.stop()


class TestMCPNodeExecute:
    """Test MCPNode.execute() for Commander."""

    @pytest.mark.asyncio
    async def test_execute_success(self, session):
        """Execute with valid input succeeds."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            ctx = ExecutionContext(
                session=session,
                input={"tool": "add", "args": {"a": 10, "b": 20}},
            )
            result = await node.execute(ctx)

            assert result["success"] is True
            assert result["output"] == "30"
            assert result["node_type"] == "mcp"
            assert result["node_id"] == "test-mcp"
        finally:
            await node.stop()

    @pytest.mark.asyncio
    async def test_execute_invalid_input(self, session):
        """Execute with non-dict input fails."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            ctx = ExecutionContext(
                session=session,
                input="not a dict",
            )
            result = await node.execute(ctx)

            assert result["success"] is False
            assert result["error_type"] == "invalid_input"
        finally:
            await node.stop()

    @pytest.mark.asyncio
    async def test_execute_missing_tool(self, session):
        """Execute without tool key fails."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            ctx = ExecutionContext(
                session=session,
                input={"args": {"a": 1}},
            )
            result = await node.execute(ctx)

            assert result["success"] is False
            assert "Missing 'tool'" in result["error"]
        finally:
            await node.stop()


class TestMCPNodeLifecycle:
    """Test MCPNode lifecycle (start, stop)."""

    @pytest.mark.asyncio
    async def test_stop(self, session):
        """Stop node transitions to STOPPED."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        await node.stop()

        assert node.state == NodeState.STOPPED

    @pytest.mark.asyncio
    async def test_start_after_stop(self, session):
        """Start after stop reconnects."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        await node.stop()
        assert node.state == NodeState.STOPPED

        await node.start()
        assert node.state == NodeState.READY

        # Should work again
        result = await node.call_tool("echo", {"message": "reconnected"})
        assert "reconnected" in result

        await node.stop()

    @pytest.mark.asyncio
    async def test_start_when_ready_is_noop(self, session):
        """Start when already ready does nothing."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            await node.start()  # Should not raise
            assert node.state == NodeState.READY
        finally:
            await node.stop()


class TestMCPNodeInfo:
    """Test MCPNode.to_info()."""

    @pytest.mark.asyncio
    async def test_to_info(self, session):
        """to_info returns correct information."""
        node = await MCPNode.create(
            id="test-mcp",
            session=session,
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            info = node.to_info()

            assert info.id == "test-mcp"
            assert info.node_type == "mcp"
            assert info.state == NodeState.READY
            assert info.persistent is True
            assert info.metadata["tool_count"] == 3
            assert "echo" in info.metadata["tools"]
        finally:
            await node.stop()
