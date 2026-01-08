"""MCP error types.

Custom exceptions for MCP protocol errors and connection failures.
"""

from __future__ import annotations


class MCPError(Exception):
    """Base error for MCP operations.

    Raised when an MCP server returns an error response for a tool call
    or other operation.
    """


class MCPConnectionError(MCPError):
    """Error connecting to or communicating with MCP server.

    Raised when:
    - MCP server process fails to start
    - Connection to server is lost
    - Server doesn't respond within timeout
    - Protocol handshake fails
    """
