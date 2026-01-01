"""Rendering and display functions for Commander TUI.

Handles welcome messages, help text, timeline display, world management,
and block printing coordination with prompt_toolkit.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

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
    console.print("  [bold]@entity message[/]  Send message to node or graph")
    console.print("  [bold]%workflow input[/]  Execute a workflow (with gate support)")
    console.print("  [bold]>>> code[/]         Execute Python code")
    console.print("  [bold]Ctrl+C[/]           Interrupt running command")
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
    console.print("  [bold]:world[/]         Show worlds + backgrounded workflows")
    console.print("  [bold]:world bash[/]    Enter bash world (no @ prefix needed)")
    console.print("  [bold]:world python[/]  Enter python world (no >>> needed)")
    console.print("  [bold]:world <id>[/]    Resume backgrounded workflow by run_id")
    console.print("  [bold]:back[/]          Exit current world")
    console.print("  [bold]:timeline[/]      Show timeline (filtered in world)")
    console.print("  [bold]:refresh[/]       Clear screen and re-render view")
    console.print("  [bold]:clean[/]         Clear all blocks, start from :::0")
    console.print()
    console.print("[bold]Entity Discovery:[/]")
    console.print("  [bold]:nodes[/]         List nodes only")
    console.print("  [bold]:graphs[/]        List graphs only")
    console.print("  [bold]:workflows[/]     List workflows only")
    console.print("  [bold]:entities[/]      List all (nodes + graphs + workflows)")
    console.print("  [bold]:info <name>[/]   Show entity or block details")
    console.print()
    console.print("[bold]Workflow Loading:[/]")
    console.print("  [bold]:load file.py[/]        Load workflow(s) from Python file")
    console.print("  [bold]:load *.py[/]           Load multiple files (glob)")
    console.print("  [bold]:load f1.py f2.py[/]    Load multiple files")
    console.print("  [bold]Tab[/] (in workflow)    Background workflow, return later")
    console.print()
    console.print("[bold]Session Persistence:[/]")
    console.print("  [bold]:export file.json[/]    Export session state to file")
    console.print("  [bold]:import file.json[/]    Import session state from file")
    console.print("  [dim]Note: Workflows need :load to restore[/]")
    console.print()
    console.print("[bold]Other:[/]")
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
    from rich.table import Table

    console.print()
    console.print("[bold]Available Nodes:[/]")
    if not nodes:
        console.print("  [dim]No nodes in session[/]")
    else:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="dim")

        for node_id, node_type in nodes.items():
            table.add_row(node_id, node_type)

        console.print(table)
    console.print()


def print_graphs(console: Console, graphs: dict[str, Any]) -> None:
    """Print available graphs.

    Args:
        console: Rich console for output.
        graphs: Dict of graph_id -> EntityInfo.
    """
    from rich.table import Table

    console.print()
    console.print("[bold]Available Graphs:[/]")
    if not graphs:
        console.print("  [dim]No graphs in session[/]")
    else:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="dim")

        for graph_id, entity in graphs.items():
            table.add_row(graph_id, entity.node_type)

        console.print(table)
    console.print()


def print_entities(console: Console, entities: dict[str, Any]) -> None:
    """Print all entities (nodes, graphs, and workflows).

    Args:
        console: Rich console for output.
        entities: Dict of entity_id -> EntityInfo.
    """
    from rich.table import Table

    console.print()
    console.print("[bold]Available Entities:[/]")
    if not entities:
        console.print("  [dim]No entities in session[/]")
    else:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Kind", style="dim")

        for entity_id, entity in entities.items():
            if entity.type == "graph":
                type_badge = "📊"
            elif entity.type == "workflow":
                type_badge = "🔄"
            else:
                type_badge = "⚙️"
            table.add_row(entity_id, f"{type_badge} {entity.type}", entity.node_type)

        console.print(table)
    console.print()


def print_workflows(console: Console, workflows: dict[str, Any]) -> None:
    """Print available workflows.

    Args:
        console: Rich console for output.
        workflows: Dict of workflow_id -> EntityInfo.
    """
    from rich.table import Table

    console.print()
    console.print("[bold]Available Workflows:[/]")
    if not workflows:
        console.print("  [dim]No workflows registered[/]")
    else:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="cyan")
        table.add_column("Description", style="dim")

        for wf_id, entity in workflows.items():
            desc = entity.metadata.get("description", "") if entity.metadata else ""
            table.add_row(wf_id, desc[:60] + "..." if len(desc) > 60 else desc)

        console.print(table)
    console.print()


def print_block_info(console: Console, block: Any) -> None:
    """Print detailed information about a block.

    Args:
        console: Rich console for output.
        block: The block to display info for.
    """
    console.print()
    console.print(f"[bold]Block {block.number}[/]")
    console.print(f"  Type: {block.block_type}")
    console.print(f"  Entity: {block.node_id}")
    console.print(f"  Status: {block.status}")

    if block.duration_ms is not None:
        console.print(f"  Duration: {block.duration_ms:.1f}ms")

    if block.error:
        console.print(f"  [red]Error: {block.error}[/]")

    # Show graph-specific details if available
    if block.block_type == "graph" and block.raw and isinstance(block.raw, dict):
        attrs = block.raw.get("attributes", {})
        if attrs:
            console.print("\n  [dim]Graph Details:[/]")
            execution_order = attrs.get("execution_order", [])
            if execution_order:
                console.print(f"    Steps: {', '.join(execution_order)}")
            final_step = attrs.get("final_step_id")
            if final_step:
                console.print(f"    Final step: {final_step}")

    console.print()


def print_entity_info(console: Console, entity: Any) -> None:
    """Print detailed information about an entity.

    Args:
        console: Rich console for output.
        entity: The EntityInfo to display.
    """
    console.print()
    console.print(f"[bold]{entity.id}[/]")
    console.print(f"  Type: {entity.type}")
    console.print(f"  Kind: {entity.node_type}")

    if entity.type == "graph" and entity.metadata:
        console.print("\n  [dim]Graph Metadata:[/]")
        for key, value in entity.metadata.items():
            console.print(f"    {key}: {value}")

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

    # Clear async flag after first render (one-time indicator)
    if block.status == "completed" and block.was_async:
        block.was_async = False


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
    active_workflows: dict[str, Any] | None = None,
) -> str | None:
    """Show world info or enter a world.

    Args:
        console: Rich console for output.
        nodes: Dict of node_id -> node_type.
        current_world: Currently active world (if any).
        node_id: World to enter (empty to show current/available).
        active_workflows: Dict of run_id -> workflow info (for backgrounded workflows).

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

        # Show backgrounded workflows if any
        if active_workflows:
            console.print()
            console.print("[dim]Backgrounded workflows:[/]")
            for run_id, wf_info in active_workflows.items():
                workflow_id = wf_info.get("workflow_id", "?")
                block_num = wf_info.get("block_number", "?")
                has_gate = wf_info.get("pending_gate") is not None
                gate_indicator = " [yellow]⏸ gate[/]" if has_gate else ""
                console.print(
                    f"  [cyan]{run_id[:8]}[/] │ {workflow_id} │ block #{block_num}{gate_indicator}"
                )
            console.print("[dim]  Use :world <run_id> to resume[/]")
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
