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
    nerve_create_session: Create a new AI CLI session
    nerve_send: Send input to a session
    nerve_list_sessions: List active sessions
    nerve_close_session: Close a session
"""

from nerve.frontends.mcp.server import NerveMCPServer

__all__ = ["NerveMCPServer"]
