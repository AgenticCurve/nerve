"""MCP server frontend for nerve.

Exposes nerve as an MCP (Model Context Protocol) server,
allowing AI agents to control other AI CLI instances.

This enables patterns like:
- Claude controlling Gemini
- Multi-agent orchestration
- AI-driven automation

Example:
    >>> from nerve.frontends.mcp import NerveMCPServer
    >>> from nerve.server import build_nerve_engine
    >>> from nerve.transport import InProcessTransport
    >>>
    >>> transport = InProcessTransport()
    >>> engine = build_nerve_engine(event_sink=transport)
    >>> mcp = NerveMCPServer(engine)
    >>> await mcp.run()

Tools exposed:
    nerve_create_node: Create a new AI CLI node
    nerve_send: Send input to a node
    nerve_list_nodes: List active nodes
    nerve_delete_node: Delete a node
"""

from nerve.frontends.mcp.server import NerveMCPServer

__all__ = ["NerveMCPServer"]
