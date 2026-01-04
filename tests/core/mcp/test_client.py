"""Tests for MCPClient."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nerve.core.mcp import MCPClient, MCPConnectionError, MCPError

# Path to mock MCP server
MOCK_SERVER = str(Path(__file__).parent / "mock_mcp_server.py")


class TestMCPClientConnection:
    """Test MCPClient connection and initialization."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Connect to mock MCP server successfully."""
        client = await MCPClient.connect(
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            assert client is not None
            assert client._process is not None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_connect_command_not_found(self):
        """Connection fails with non-existent command."""
        with pytest.raises(MCPConnectionError, match="Command not found"):
            await MCPClient.connect(command="nonexistent-command-12345")

    @pytest.mark.asyncio
    async def test_connect_init_failure(self):
        """Connection fails when server returns init error."""
        with pytest.raises(MCPConnectionError, match="initialization failed"):
            await MCPClient.connect(
                command=sys.executable,
                args=[MOCK_SERVER, "--fail-init"],
            )


class TestMCPClientListTools:
    """Test MCPClient.list_tools()."""

    @pytest.mark.asyncio
    async def test_list_tools(self):
        """List tools from mock server."""
        client = await MCPClient.connect(
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            tools = await client.list_tools()

            assert len(tools) == 3
            tool_names = {t.name for t in tools}
            assert tool_names == {"echo", "add", "fail"}

            # Check echo tool
            echo_tool = next(t for t in tools if t.name == "echo")
            assert "echo" in echo_tool.description.lower()
            assert "message" in echo_tool.input_schema.get("properties", {})

            # Check add tool
            add_tool = next(t for t in tools if t.name == "add")
            assert "add" in add_tool.description.lower()
            assert "a" in add_tool.input_schema.get("properties", {})
            assert "b" in add_tool.input_schema.get("properties", {})

        finally:
            await client.close()


class TestMCPClientCallTool:
    """Test MCPClient.call_tool()."""

    @pytest.mark.asyncio
    async def test_call_echo_tool(self):
        """Call echo tool successfully."""
        client = await MCPClient.connect(
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            result = await client.call_tool("echo", {"message": "hello world"})
            assert "hello world" in result

        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_call_add_tool(self):
        """Call add tool successfully."""
        client = await MCPClient.connect(
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            result = await client.call_tool("add", {"a": 5, "b": 3})
            assert result == "8"

        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_call_failing_tool(self):
        """Call tool that returns error."""
        client = await MCPClient.connect(
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            with pytest.raises(MCPError, match="always fails"):
                await client.call_tool("fail", {})

        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self):
        """Call non-existent tool."""
        client = await MCPClient.connect(
            command=sys.executable,
            args=[MOCK_SERVER],
        )
        try:
            with pytest.raises(MCPError, match="Unknown tool"):
                await client.call_tool("nonexistent", {})

        finally:
            await client.close()


class TestMCPClientClose:
    """Test MCPClient.close()."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Close connection cleanly."""
        client = await MCPClient.connect(
            command=sys.executable,
            args=[MOCK_SERVER],
        )

        await client.close()

        # Process should be terminated
        assert client._process.returncode is not None

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """Close can be called multiple times."""
        client = await MCPClient.connect(
            command=sys.executable,
            args=[MOCK_SERVER],
        )

        await client.close()
        await client.close()  # Should not raise
