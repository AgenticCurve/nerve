"""MCP server implementation for nerve."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nerve.server import NerveEngine


@dataclass
class NerveMCPServer:
    """MCP server that exposes nerve to AI agents.

    Allows AI models to control other AI CLI instances through
    the Model Context Protocol.

    Example:
        >>> engine = NerveEngine(event_sink=transport)
        >>> mcp = NerveMCPServer(engine)
        >>> await mcp.run()  # Start MCP server

    Tools:
        nerve_create_session(cli_type, cwd) -> session_id
        nerve_send(session_id, text) -> response
        nerve_list_sessions() -> [session_ids]
        nerve_close_session(session_id) -> success
    """

    engine: NerveEngine

    async def run(self) -> None:
        """Run the MCP server.

        Listens for MCP tool calls and routes them to the engine.
        """
        try:
            from mcp.server import Server
            from mcp.server.stdio import stdio_server
            from mcp.types import TextContent, Tool
        except ImportError as err:
            raise ImportError(
                "MCP package is required. Install with: pip install nerve[mcp]"
            ) from err

        server = Server("nerve")

        @server.list_tools()
        async def list_tools():
            """List available tools."""
            return [
                Tool(
                    name="nerve_create_session",
                    description="Create a new AI CLI session (Claude, Gemini)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "cli_type": {
                                "type": "string",
                                "enum": ["claude", "gemini"],
                                "description": "Type of AI CLI",
                            },
                            "cwd": {
                                "type": "string",
                                "description": "Working directory (optional)",
                            },
                        },
                        "required": ["cli_type"],
                    },
                ),
                Tool(
                    name="nerve_send",
                    description="Send input to an AI CLI session and get response",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session ID",
                            },
                            "text": {
                                "type": "string",
                                "description": "Text to send",
                            },
                        },
                        "required": ["session_id", "text"],
                    },
                ),
                Tool(
                    name="nerve_list_sessions",
                    description="List active AI CLI sessions",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="nerve_close_session",
                    description="Close an AI CLI session",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session ID to close",
                            },
                        },
                        "required": ["session_id"],
                    },
                ),
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict):
            """Handle tool calls."""
            from nerve.server.protocols import Command, CommandType

            if name == "nerve_create_session":
                result = await self.engine.execute(
                    Command(
                        type=CommandType.CREATE_SESSION,
                        params={
                            "cli_type": arguments.get("cli_type", "claude"),
                            "cwd": arguments.get("cwd"),
                        },
                    )
                )
                if result.success:
                    return [
                        TextContent(
                            type="text",
                            text=f"Created session: {result.data['session_id']}",
                        )
                    ]
                return [TextContent(type="text", text=f"Error: {result.error}")]

            elif name == "nerve_send":
                result = await self.engine.execute(
                    Command(
                        type=CommandType.SEND_INPUT,
                        params={
                            "session_id": arguments["session_id"],
                            "text": arguments["text"],
                        },
                    )
                )
                if result.success:
                    return [
                        TextContent(
                            type="text",
                            text=result.data.get("response", ""),
                        )
                    ]
                return [TextContent(type="text", text=f"Error: {result.error}")]

            elif name == "nerve_list_sessions":
                result = await self.engine.execute(
                    Command(
                        type=CommandType.LIST_SESSIONS,
                        params={},
                    )
                )
                if result.success:
                    sessions = result.data.get("sessions", [])
                    return [
                        TextContent(
                            type="text",
                            text=f"Sessions: {', '.join(sessions) or 'none'}",
                        )
                    ]
                return [TextContent(type="text", text=f"Error: {result.error}")]

            elif name == "nerve_close_session":
                result = await self.engine.execute(
                    Command(
                        type=CommandType.CLOSE_SESSION,
                        params={"session_id": arguments["session_id"]},
                    )
                )
                if result.success:
                    return [TextContent(type="text", text="Session closed")]
                return [TextContent(type="text", text=f"Error: {result.error}")]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)
