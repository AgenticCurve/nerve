"""Command handlers and dispatch for Commander TUI.

Provides a registry-based command dispatch system for colon commands.
Each command handler is a separate async function that receives the
Commander instance and optional arguments.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from nerve.frontends.tui.commander import rendering

if TYPE_CHECKING:
    from nerve.frontends.tui.commander.commander import Commander

# Type alias for command handlers
CommandHandler = Callable[["Commander", str], Awaitable[None]]


async def cmd_exit(commander: Commander, args: str) -> None:
    """Handle :exit command - exit world or commander."""
    if commander._current_world:
        old_world = commander._current_world
        commander._current_world = None
        rendering.exit_world(commander.console, old_world)
    else:
        commander._running = False
        commander.console.print("[dim]Goodbye![/]")


async def cmd_back(commander: Commander, args: str) -> None:
    """Handle :back command - exit current world."""
    if commander._current_world:
        old_world = commander._current_world
        commander._current_world = None
        rendering.exit_world(commander.console, old_world)
    else:
        commander.console.print("[dim]Already at main timeline[/]")


async def cmd_help(commander: Commander, args: str) -> None:
    """Handle :help command - show help text."""
    rendering.print_help(commander.console)


async def cmd_nodes(commander: Commander, args: str) -> None:
    """Handle :nodes command - list available nodes (excludes graphs)."""
    await commander._sync_entities()
    # Filter to show only nodes (not graphs)
    nodes_only = {
        entity_id: entity.node_type
        for entity_id, entity in commander.entities.items()
        if entity.type == "node"
    }
    rendering.print_nodes(commander.console, nodes_only)


async def cmd_graphs(commander: Commander, args: str) -> None:
    """Handle :graphs command - list available graphs."""
    await commander._sync_entities()
    # Filter to show only graphs
    graphs = {
        entity_id: entity
        for entity_id, entity in commander.entities.items()
        if entity.type == "graph"
    }
    rendering.print_graphs(commander.console, graphs)


async def cmd_entities(commander: Commander, args: str) -> None:
    """Handle :entities command - list all entities (nodes and graphs)."""
    await commander._sync_entities()
    rendering.print_entities(commander.console, commander.entities)


async def cmd_info(commander: Commander, args: str) -> None:
    """Handle :info command - show detailed info about a block or entity.

    Usage:
        :info 3         # Show info about block 3
        :info pipeline  # Show info about entity 'pipeline'
    """
    if not args:
        commander.console.print("[error]Usage: :info <block-number | entity-name>[/]")
        return

    # Try as block number first
    try:
        block_num = int(args)
        if 0 <= block_num < len(commander.timeline.blocks):
            block = commander.timeline.blocks[block_num]
            rendering.print_block_info(commander.console, block)
            return
        else:
            commander.console.print(f"[error]Block {block_num} not found[/]")
            return
    except ValueError:
        pass

    # Try as entity name
    entity_id = args.strip()
    await commander._sync_entities()
    if entity_id in commander.entities:
        entity = commander.entities[entity_id]
        rendering.print_entity_info(commander.console, entity)
    else:
        commander.console.print(f"[error]Unknown block or entity: {args}[/]")


async def cmd_timeline(commander: Commander, args: str) -> None:
    """Handle :timeline command - show timeline."""
    limit = None
    if args:
        try:
            limit = int(args)
        except ValueError:
            commander.console.print(f"[warning]Invalid number: {args}[/]")
            return

    rendering.print_timeline(
        commander.console,
        commander.timeline,
        commander._current_world,
        commander.nodes,
        limit,
    )


async def cmd_clear(commander: Commander, args: str) -> None:
    """Handle :clear command - full viewport clear."""
    # Full viewport clear using ANSI escape codes
    # \033[2J clears entire screen, \033[H moves cursor to home (0,0)
    # \033[3J also clears scrollback buffer for a true fresh start
    print("\033[2J\033[3J\033[H", end="", flush=True)


async def cmd_clean(commander: Commander, args: str) -> None:
    """Handle :clean command - clear all blocks."""
    rendering.clean_blocks(
        commander.console,
        commander.timeline,
        commander.server_name,
        commander.session_name,
        commander.nodes,
    )


async def cmd_refresh(commander: Commander, args: str) -> None:
    """Handle :refresh command - sync nodes and re-render."""
    await commander._sync_entities()
    rendering.refresh_view(
        commander.console,
        commander.timeline,
        commander.nodes,
        commander._current_world,
        commander.server_name,
        commander.session_name,
    )


async def cmd_theme(commander: Commander, args: str) -> None:
    """Handle :theme command - switch theme."""
    new_console, new_theme = rendering.switch_theme(commander.console, args)
    if new_theme:
        commander.console = new_console
        commander.theme_name = new_theme


async def cmd_world(commander: Commander, args: str) -> None:
    """Handle :world command - enter/show world."""
    world_to_enter = rendering.show_world(
        commander.console,
        commander.nodes,
        commander._current_world,
        args,
    )
    if world_to_enter:
        commander._current_world = world_to_enter
        rendering.enter_world(
            commander.console,
            commander.timeline,
            commander.nodes,
            world_to_enter,
        )


async def cmd_loop(commander: Commander, args: str) -> None:
    """Handle :loop command - multi-node conversation."""
    from nerve.frontends.tui.commander.loop import handle_loop

    await handle_loop(commander, args)


# Command registry - maps command names to handlers
COMMANDS: dict[str, CommandHandler] = {
    "exit": cmd_exit,
    "back": cmd_back,
    "help": cmd_help,
    "nodes": cmd_nodes,
    "graphs": cmd_graphs,
    "entities": cmd_entities,
    "info": cmd_info,
    "timeline": cmd_timeline,
    "clear": cmd_clear,
    "clean": cmd_clean,
    "refresh": cmd_refresh,
    "theme": cmd_theme,
    "world": cmd_world,
    "loop": cmd_loop,
}


async def dispatch_command(commander: Commander, cmd_str: str) -> bool:
    """Dispatch a colon command.

    Args:
        commander: Commander instance.
        cmd_str: Command string (without leading colon).

    Returns:
        True if command was handled, False otherwise.
    """
    parts = cmd_str.strip().split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""

    handler = COMMANDS.get(command)
    if handler:
        await handler(commander, args)
        return True

    commander.console.print(f"[warning]Unknown command: {command}[/]")
    return False
