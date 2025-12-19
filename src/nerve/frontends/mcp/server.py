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
        nerve_create_channel(name, command, cwd) -> channel_id
        nerve_send(channel_name, text, parser) -> response
        nerve_list_channels() -> [channel names]
        nerve_close_channel(channel_name) -> success
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
                    name="nerve_create_channel",
                    description="Create a new AI CLI channel",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Channel name (lowercase alphanumeric with dashes, 1-32 chars)",
                            },
                            "command": {
                                "type": "string",
                                "description": "Command to run (e.g., 'claude', 'gemini')",
                            },
                            "cwd": {
                                "type": "string",
                                "description": "Working directory (optional)",
                            },
                        },
                        "required": ["name"],
                    },
                ),
                Tool(
                    name="nerve_send",
                    description="Send input to an AI CLI channel and get response",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "channel_name": {
                                "type": "string",
                                "description": "Channel name",
                            },
                            "text": {
                                "type": "string",
                                "description": "Text to send",
                            },
                            "parser": {
                                "type": "string",
                                "enum": ["claude", "gemini", "none"],
                                "description": "Parser for output (claude, gemini, none)",
                            },
                        },
                        "required": ["channel_name", "text"],
                    },
                ),
                Tool(
                    name="nerve_list_channels",
                    description="List active AI CLI channels",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="nerve_close_channel",
                    description="Close an AI CLI channel",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "channel_name": {
                                "type": "string",
                                "description": "Channel name to close",
                            },
                        },
                        "required": ["channel_name"],
                    },
                ),
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict):
            """Handle tool calls."""
            from nerve.server.protocols import Command, CommandType

            if name == "nerve_create_channel":
                from nerve.core.validation import validate_name

                channel_name = arguments.get("name")
                try:
                    validate_name(channel_name, "channel")
                except ValueError as e:
                    return [TextContent(type="text", text=f"Error: {e}")]

                result = await self.engine.execute(
                    Command(
                        type=CommandType.CREATE_CHANNEL,
                        params={
                            "channel_id": channel_name,
                            "command": arguments.get("command"),
                            "cwd": arguments.get("cwd"),
                        },
                    )
                )
                if result.success:
                    return [
                        TextContent(
                            type="text",
                            text=f"Created channel: {channel_name}",
                        )
                    ]
                return [TextContent(type="text", text=f"Error: {result.error}")]

            elif name == "nerve_send":
                result = await self.engine.execute(
                    Command(
                        type=CommandType.SEND_INPUT,
                        params={
                            "channel_id": arguments["channel_name"],
                            "text": arguments["text"],
                            "parser": arguments.get("parser", "none"),
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

            elif name == "nerve_list_channels":
                result = await self.engine.execute(
                    Command(
                        type=CommandType.LIST_CHANNELS,
                        params={},
                    )
                )
                if result.success:
                    channels = result.data.get("channels", [])
                    return [
                        TextContent(
                            type="text",
                            text=f"Channels: {', '.join(channels) or 'none'}",
                        )
                    ]
                return [TextContent(type="text", text=f"Error: {result.error}")]

            elif name == "nerve_close_channel":
                result = await self.engine.execute(
                    Command(
                        type=CommandType.CLOSE_CHANNEL,
                        params={"channel_id": arguments["channel_name"]},
                    )
                )
                if result.success:
                    return [TextContent(type="text", text="Channel closed")]
                return [TextContent(type="text", text=f"Error: {result.error}")]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)
