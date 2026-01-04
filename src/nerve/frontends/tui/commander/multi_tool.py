"""Multi-tool node handling for Commander TUI.

Provides detection, help rendering, and input parsing for nodes with multiple
tools (like MCPNode). Single-tool nodes use existing Commander behavior.

Help commands:
- @node ?          → List all tools from node
- @node tool ?     → Show specific tool details

Parsing for multi-tool nodes:
- @node tool_name {"arg": "value"}  → JSON arguments
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from rich.console import Console

if TYPE_CHECKING:
    from nerve.core.nodes.tools import ToolDefinition


def is_multi_tool_node_type(node_type: str) -> bool:
    """Check if a node type represents a multi-tool node.

    Args:
        node_type: The node type string (e.g., "MCPNode", "BashNode").

    Returns:
        True if the node type typically has multiple tools.
    """
    return "mcp" in node_type.lower()


def is_help_command(text: str) -> bool:
    """Check if text is a help command.

    Args:
        text: The input text after node ID.

    Returns:
        True if text is "?" (list all tools) or "tool ?" (tool help).
    """
    text = text.strip()
    return text == "?" or text.endswith(" ?")


def parse_help_command(text: str) -> tuple[bool, str | None]:
    """Parse a help command to determine if it's node-level or tool-level.

    Args:
        text: The input text after node ID.

    Returns:
        Tuple of (is_help, tool_name).
        - (True, None) for "@node ?" (list all tools)
        - (True, "tool") for "@node tool ?" (specific tool help)
        - (False, None) for non-help commands
    """
    text = text.strip()

    if text == "?":
        return (True, None)

    if text.endswith(" ?"):
        # Extract tool name: "tool_name ?" -> "tool_name"
        parts = text[:-2].strip().split()
        if len(parts) == 1:
            return (True, parts[0])

    return (False, None)


def render_node_tools_help(console: Console, node_id: str, tools: list[ToolDefinition]) -> None:
    """Render help listing all tools from a node.

    Args:
        console: Rich console for output.
        node_id: The node ID for display.
        tools: List of ToolDefinition objects.
    """
    console.print(f"\n[bold]{node_id}[/] tools:")
    console.print()

    if not tools:
        console.print("  [dim]No tools available[/]")
        console.print()
        return

    # Find max tool name length for alignment
    max_name_len = max(len(t.name) for t in tools)

    for tool in tools:
        # Truncate description to fit on one line
        desc = tool.description or "(no description)"
        if len(desc) > 60:
            desc = desc[:57] + "..."
        console.print(f"  [cyan]{tool.name:<{max_name_len}}[/]  {desc}")

    console.print()
    console.print(f'[dim]Usage: @{node_id} <tool> {{"arg": "value"}}[/]')
    console.print(f"[dim]Help:  @{node_id} <tool> ?[/]")
    console.print()


def render_tool_help(console: Console, node_id: str, tool: ToolDefinition) -> None:
    """Render help for a specific tool.

    Args:
        console: Rich console for output.
        node_id: The node ID for display.
        tool: The ToolDefinition to describe.
    """
    console.print(f"\n[bold cyan]{tool.name}[/] - {tool.description or '(no description)'}")
    console.print()

    # Extract parameters from JSON schema
    params = tool.parameters
    properties = params.get("properties", {})
    required = set(params.get("required", []))

    if properties:
        console.print("[bold]Parameters:[/]")
        for name, schema in properties.items():
            param_type = schema.get("type", "any")
            param_desc = schema.get("description", "")
            is_required = name in required

            req_marker = "[red]*[/]" if is_required else " "
            console.print(f"  {req_marker} [green]{name}[/] ({param_type})")
            if param_desc:
                console.print(f"      {param_desc}")
        console.print()
    else:
        console.print("[dim]No parameters[/]")
        console.print()

    # Show example
    example_args: dict[str, str | int | bool] = {}
    for name, schema in properties.items():
        param_type = schema.get("type", "string")
        if param_type == "string":
            example_args[name] = f"<{name}>"
        elif param_type == "number" or param_type == "integer":
            example_args[name] = 0
        elif param_type == "boolean":
            example_args[name] = True
        else:
            example_args[name] = f"<{name}>"

    example_json = json.dumps(example_args)
    console.print(f"[dim]Example: @{node_id} {tool.name} {example_json}[/]")
    console.print()


def parse_multi_tool_input(text: str) -> tuple[str, dict[str, Any]]:
    """Parse multi-tool node input into tool name and arguments.

    Expected format: tool_name {"arg": "value"}

    Args:
        text: The input text after node ID.

    Returns:
        Tuple of (tool_name, args_dict).

    Raises:
        ValueError: If format is invalid or JSON is malformed.
    """
    text = text.strip()

    if not text:
        raise ValueError("No tool specified. Use: @<node> ? to list tools")

    # Split on first whitespace
    parts = text.split(None, 1)
    tool_name = parts[0]

    if len(parts) == 1:
        # No arguments provided - use empty dict
        return (tool_name, {})

    args_str = parts[1].strip()

    # Parse JSON arguments
    try:
        args = json.loads(args_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON arguments: {e}") from e

    if not isinstance(args, dict):
        raise ValueError(f"Arguments must be a JSON object, got {type(args).__name__}")

    return (tool_name, args)
