"""Frontends - User interfaces for nerve.

Frontends provide different ways to interact with nerve:
- CLI: Command-line interface
- SDK: Python SDK for programmatic use
- MCP: Model Context Protocol server for AI agents

Each frontend uses the transport layer to communicate,
and knows nothing about the core or server internals.

Submodules:
    cli/    Command-line interface
    sdk/    Python SDK
    mcp/    MCP server for AI agents
"""
