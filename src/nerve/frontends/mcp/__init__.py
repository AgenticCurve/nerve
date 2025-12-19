"""MCP server frontend for nerve.

Exposes nerve as an MCP (Model Context Protocol) server,
allowing AI agents to control other AI CLI instances.

This enables patterns like:
- Claude controlling Gemini
- Multi-agent orchestration
- AI-driven automation

Example:
    >>> from nerve.frontends.mcp import NerveMCPServer
    >>> from nerve.server import NerveEngine
    >>> from nerve.transport import InProcessTransport
    >>>
    >>> transport = InProcessTransport()
    >>> engine = NerveEngine(event_sink=transport)
    >>> mcp = NerveMCPServer(engine)
    >>> await mcp.run()

Tools exposed:
    nerve_create_channel: Create a new AI CLI channel
    nerve_send: Send input to a channel
    nerve_list_channels: List active channels
    nerve_close_channel: Close a channel
"""

from nerve.frontends.mcp.server import NerveMCPServer

__all__ = ["NerveMCPServer"]
