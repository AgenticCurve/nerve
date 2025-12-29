"""Rendering and display functions for Commander TUI.

Handles welcome messages, help text, timeline display, world management,
and block printing coordination with prompt_toolkit.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from rich.console import Console

from nerve.frontends.tui.commander.themes import get_theme

if TYPE_CHECKING:
    from nerve.frontends.tui.commander.blocks import Block, Timeline


def print_welcome(
    console: Console,
    server_name: str,
    session_name: str,
    nodes: dict[str, str],
) -> None:
    """Print welcome message.

    Args:
        console: Rich console for output.
        server_name: Name of connected server.
        session_name: Name of active session.
        nodes: Dict of node_id -> node_type.
    """
    console.print()
    console.print("[bold]Commander[/] - Nerve Command Center", style="prompt")
    console.print(f"[dim]Server: {server_name} | Session: {session_name} | Nodes: {len(nodes)}[/]")
    if nodes:
        console.print("[dim]Use @<node> <message> to interact. :help for commands.[/]")
    else:
        console.print(
            "[dim]No nodes in session. Create nodes first with: nerve server node create[/]"
        )
    console.print()


def print_help(console: Console) -> None:
    """Print help message.

    Args:
        console: Rich console for output.
    """
    console.print()
    console.print("[bold]Commands:[/]")
    console.print("  [bold]@node message[/]  Send message to a node")
    console.print("  [bold]>>> code[/]       Execute Python code")
    console.print("  [bold]Ctrl+C[/]         Interrupt running command")
    console.print()
    console.print("[bold]Block References:[/] (0-indexed)")
    console.print("  [bold]:::0[/]                   First block's output")
    console.print("  [bold]:::N[/]                   Block N's output")
    console.print("  [bold]:::N['input'][/]          Block N's input text")
    console.print("  [bold]:::-1[/]                  Last block (negative indexing)")
    console.print("  [bold]:::-2[/]                  Second to last block")
    console.print()
    console.print("[bold]Node References:[/] (per-node indexing)")
    console.print("  [bold]:::claude[/]              Last block from node 'claude'")
    console.print("  [bold]:::claude[0][/]           First block from 'claude'")
    console.print("  [bold]:::claude[-2][/]          Second to last from 'claude'")
    console.print("  [bold]:::bash[0]['input'][/]    First bash block's input")
    console.print()
    console.print("[bold]Colon Commands:[/]")
    console.print("  [bold]:world bash[/]    Enter bash world (no @ prefix needed)")
    console.print("  [bold]:world python[/]  Enter python world (no >>> needed)")
    console.print("  [bold]:back[/]          Exit current world")
    console.print("  [bold]:timeline[/]      Show timeline (filtered in world)")
    console.print("  [bold]:refresh[/]       Clear screen and re-render view")
    console.print("  [bold]:clean[/]         Clear all blocks, start from :::0")
    console.print("  [bold]:nodes[/]         List available nodes")
    console.print("  [bold]:theme name[/]    Switch theme")
    console.print("  [bold]:exit[/]          Exit world or commander")
    console.print()
    console.print("[bold]Loop Command:[/]")
    console.print('  [bold]:loop @n1 @n2 "prompt" [options][/]')
    console.print("    Round-robin conversation between nodes")
    console.print('    [dim]--until "phrase"[/]  Stop when output contains phrase')
    console.print("    [dim]--max N[/]           Maximum rounds (default: 10)")
    console.print('    [dim]--node "template"[/] Per-node prompt template')
    console.print("    Template variables:")
    console.print("      [dim]{prev}[/]    Previous step's output")
    console.print("      [dim]{node}[/]    That node's last output (e.g., {claude}, {bash})")
    console.print('  [dim]Example: :loop @claude @gemini "discuss AI" --until "AGREED" --max 5[/]')
    console.print()


def print_nodes(console: Console, nodes: dict[str, str]) -> None:
    """Print available nodes.

    Args:
        console: Rich console for output.
        nodes: Dict of node_id -> node_type.
    """
    console.print()
    console.print("[bold]Available Nodes:[/]")
    if not nodes:
        console.print("  [dim]No nodes in session[/]")
    else:
        for node_id, node_type in nodes.items():
            console.print(f"  [bold]{node_id}[/] ({node_type})")
    console.print()


def print_timeline(
    console: Console,
    timeline: Timeline,
    current_world: str | None,
    nodes: dict[str, str],
    limit: int | None = None,
) -> None:
    """Print timeline (optionally limited to last N).

    Args:
        console: Rich console for output.
        timeline: The timeline to display.
        current_world: Current world filter (node_id, "python", or None).
        nodes: Dict of node_id -> node_type (unused but kept for consistency).
        limit: Optional limit on number of blocks to show.
    """
    # Filter by current world if in one
    if current_world:
        if current_world == "python":
            blocks = timeline.filter_by_type("python")
        else:
            blocks = timeline.filter_by_node(current_world)
    else:
        blocks = timeline.blocks

    if not blocks:
        console.print("[dim]No blocks in timeline yet[/]")
        return

    console.print()
    blocks_to_render = blocks[-limit:] if limit else blocks
    for i, block in enumerate(blocks_to_render):
        console.print(block.render(console, show_separator=(i > 0)))


def print_block(console: Console, block: Block) -> None:
    """Print a block ensuring output goes through patch_stdout.

    Uses Rich's capture to render to string, then print() to output.
    This ensures coordination with prompt_toolkit when printing from
    background tasks.

    Args:
        console: Rich console for rendering.
        block: The block to print.
    """
    # Render block to string using Rich
    with console.capture() as capture:
        console.print(block.render(console, show_separator=True))
    output = capture.get()

    # Use print() which goes through patch_stdout's proxy
    # This properly coordinates with prompt_toolkit's input line
    print(output, end="", file=sys.stdout, flush=True)


def switch_theme(console: Console, theme_name: str) -> tuple[Console, str]:
    """Switch to a different theme.

    Args:
        console: Current console instance.
        theme_name: Name of theme to switch to.

    Returns:
        Tuple of (new_console, theme_name) if theme was changed,
        or (original_console, original_theme_name) if no change.
    """
    if not theme_name:
        console.print("[dim]Available themes: default, nord, dracula, mono[/]")
        return console, ""

    theme = get_theme(theme_name)
    new_console = Console(theme=theme, force_terminal=True)
    new_console.print(f"[success]Switched to theme: {theme_name}[/]")
    return new_console, theme_name


def show_world(
    console: Console,
    nodes: dict[str, str],
    current_world: str | None,
    node_id: str,
) -> str | None:
    """Show world info or enter a world.

    Args:
        console: Rich console for output.
        nodes: Dict of node_id -> node_type.
        current_world: Currently active world (if any).
        node_id: World to enter (empty to show current/available).

    Returns:
        Node ID to enter world for, or None if no change.
    """
    # Handle "python" as a special world
    if node_id == "python":
        return "python"

    if not node_id:
        # No argument - show current world or list available
        if current_world:
            console.print(f"[dim]Currently in world: {current_world}[/]")
        else:
            console.print("[dim]Available worlds:[/]")
            for nid in nodes:
                console.print(f"  [bold]{nid}[/]")
            console.print("  [bold]python[/]")
        return None

    if node_id not in nodes:
        console.print(f"[error]Node not found: {node_id}[/]")
        return None

    return node_id


def enter_world(
    console: Console,
    timeline: Timeline,
    nodes: dict[str, str],
    world_id: str,
) -> None:
    """Display world entry and history.

    Args:
        console: Rich console for output.
        timeline: Timeline to get history from.
        nodes: Dict of node_id -> node_type.
        world_id: The world being entered.
    """
    console.print()
    if world_id == "python":
        console.print("[bold]World: python[/]")
        console.print("[dim]Type Python code directly. :exit or :back to leave.[/]")
        blocks = timeline.filter_by_type("python")
        if blocks:
            console.print(f"[dim]History: {len(blocks)} blocks[/]")
            console.print()
            for i, block in enumerate(blocks):
                console.print(block.render(console, show_separator=(i > 0)))
        else:
            console.print()
    else:
        node_type = nodes.get(world_id, "?")
        console.print(f"[bold]World: @{world_id}[/] ({node_type})")
        console.print("[dim]Type commands directly. :exit or :back to leave.[/]")
        blocks = timeline.filter_by_node(world_id)
        if blocks:
            console.print(f"[dim]History: {len(blocks)} blocks[/]")
            console.print()
            for i, block in enumerate(blocks):
                console.print(block.render(console, show_separator=(i > 0)))
        else:
            console.print()


def exit_world(console: Console, old_world: str) -> None:
    """Display world exit message.

    Args:
        console: Rich console for output.
        old_world: The world being exited.
    """
    console.print(f"[dim]Left world: {old_world}[/]")
    console.print()


def clean_blocks(
    console: Console,
    timeline: Timeline,
    server_name: str,
    session_name: str,
    nodes: dict[str, str],
) -> None:
    """Clear all blocks and reset numbering.

    Args:
        console: Rich console for output.
        timeline: Timeline to clear.
        server_name: Name of connected server.
        session_name: Name of active session.
        nodes: Dict of node_id -> node_type.
    """
    count = len(timeline)
    timeline.clear()
    console.clear()
    print_welcome(console, server_name, session_name, nodes)
    console.print(f"[dim]Cleared {count} blocks. Starting fresh from :::0[/]")
    console.print()


def refresh_view(
    console: Console,
    timeline: Timeline,
    nodes: dict[str, str],
    current_world: str | None,
    server_name: str,
    session_name: str,
) -> None:
    """Clear screen and re-render current view.

    Args:
        console: Rich console for output.
        timeline: Timeline to render.
        nodes: Dict of node_id -> node_type.
        current_world: Current world filter (node_id, "python", or None).
        server_name: Name of connected server.
        session_name: Name of active session.
    """
    console.clear()

    # Re-render based on current context
    if current_world:
        # In a world - show world header and filtered blocks
        if current_world == "python":
            console.print("[bold]World: python[/]")
            blocks = timeline.filter_by_type("python")
        else:
            node_type = nodes.get(current_world, "?")
            console.print(f"[bold]World: @{current_world}[/] ({node_type})")
            blocks = timeline.filter_by_node(current_world)

        if blocks:
            console.print(f"[dim]History: {len(blocks)} blocks[/]")
            console.print()
            for i, block in enumerate(blocks):
                console.print(block.render(console, show_separator=(i > 0)))
        else:
            console.print()
    else:
        # Main view - show welcome and all blocks
        print_welcome(console, server_name, session_name, nodes)
        if timeline.blocks:
            for i, block in enumerate(timeline.blocks):
                console.print(block.render(console, show_separator=(i > 0)))
