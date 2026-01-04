"""MCP node implementation.

Provides MCPNode which wraps MCP server connections as nerve nodes.
Each MCPNode connects to one MCP server and exposes all its tools.

Example:
    >>> from nerve.core.nodes.mcp import MCPNode
    >>>
    >>> node = await MCPNode.create(
    ...     id="fs-mcp",
    ...     session=session,
    ...     command="npx",
    ...     args=["@modelcontextprotocol/server-filesystem", "/tmp"],
    ... )
    >>> tools = node.list_tools()
    >>> result = await node.call_tool("read_file", {"path": "/tmp/foo.txt"})
"""

from nerve.core.nodes.mcp.mcp_node import MCPNode

__all__ = ["MCPNode"]
