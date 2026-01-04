"""MCP (Model Context Protocol) client implementation.

Provides low-level MCP protocol client for stdio transport.
Used by MCPNode to communicate with MCP servers.

Example:
    >>> from nerve.core.mcp import MCPClient, MCPError, MCPConnectionError
    >>>
    >>> client = await MCPClient.connect(
    ...     command="npx",
    ...     args=["@modelcontextprotocol/server-filesystem", "/tmp"],
    ... )
    >>> tools = await client.list_tools()
    >>> result = await client.call_tool("read_file", {"path": "/tmp/foo.txt"})
    >>> await client.close()
"""

from nerve.core.mcp.client import MCPClient, MCPToolInfo
from nerve.core.mcp.errors import MCPConnectionError, MCPError

__all__ = [
    "MCPClient",
    "MCPToolInfo",
    "MCPError",
    "MCPConnectionError",
]
