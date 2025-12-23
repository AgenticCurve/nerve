"""MCP server implementation for nerve.

Node-based terminology (clean break from Channel):
- nerve_create_node (was nerve_create_channel)
- nerve_list_nodes (was nerve_list_channels)
- nerve_stop_node (was nerve_close_channel)
"""

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
        nerve_create_node(name, command, cwd) -> node_id
        nerve_send(node_name, text, parser) -> response
        nerve_list_nodes() -> [node names]
        nerve_stop_node(node_name) -> success
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
                    name="nerve_create_node",
                    description="Create a new AI CLI node",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Node name (lowercase alphanumeric with dashes, 1-32 chars)",
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
                    description="Send input to an AI CLI node and get response",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "node_name": {
                                "type": "string",
                                "description": "Node name",
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
                        "required": ["node_name", "text"],
                    },
                ),
                Tool(
                    name="nerve_list_nodes",
                    description="List active AI CLI nodes",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="nerve_stop_node",
                    description="Stop an AI CLI node",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "node_name": {
                                "type": "string",
                                "description": "Node name to stop",
                            },
                        },
                        "required": ["node_name"],
                    },
                ),
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict):
            """Handle tool calls."""
            from nerve.server.protocols import Command, CommandType

            if name == "nerve_create_node":
                from nerve.core.validation import validate_name

                node_name = arguments.get("name")
                try:
                    validate_name(node_name, "node")
                except ValueError as e:
                    return [TextContent(type="text", text=f"Error: {e}")]

                result = await self.engine.execute(
                    Command(
                        type=CommandType.CREATE_NODE,
                        params={
                            "node_id": node_name,
                            "command": arguments.get("command"),
                            "cwd": arguments.get("cwd"),
                        },
                    )
                )
                if result.success:
                    return [
                        TextContent(
                            type="text",
                            text=f"Created node: {node_name}",
                        )
                    ]
                return [TextContent(type="text", text=f"Error: {result.error}")]

            elif name == "nerve_send":
                result = await self.engine.execute(
                    Command(
                        type=CommandType.EXECUTE_INPUT,
                        params={
                            "node_id": arguments["node_name"],
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

            elif name == "nerve_list_nodes":
                result = await self.engine.execute(
                    Command(
                        type=CommandType.LIST_NODES,
                        params={},
                    )
                )
                if result.success:
                    nodes = result.data.get("nodes", [])
                    return [
                        TextContent(
                            type="text",
                            text=f"Nodes: {', '.join(nodes) or 'none'}",
                        )
                    ]
                return [TextContent(type="text", text=f"Error: {result.error}")]

            elif name == "nerve_stop_node":
                result = await self.engine.execute(
                    Command(
                        type=CommandType.STOP_NODE,
                        params={"node_id": arguments["node_name"]},
                    )
                )
                if result.success:
                    return [TextContent(type="text", text="Node stopped")]
                return [TextContent(type="text", text=f"Error: {result.error}")]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)
