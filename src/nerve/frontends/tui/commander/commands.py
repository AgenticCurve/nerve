"""Command handlers and dispatch for Commander TUI.

Provides a registry-based command dispatch system for colon commands.
Each command handler is a separate async function that receives the
Commander instance and optional arguments.
"""

from __future__ import annotations

import glob
from collections.abc import Awaitable, Callable
from pathlib import Path
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
    """Handle :entities command - list all entities (nodes, graphs, workflows)."""
    await commander._sync_entities()
    rendering.print_entities(commander.console, commander.entities)


async def cmd_workflows(commander: Commander, args: str) -> None:
    """Handle :workflows command - list available workflows."""
    await commander._sync_entities()
    # Filter to show only workflows
    workflows = {
        entity_id: entity
        for entity_id, entity in commander.entities.items()
        if entity.type == "workflow"
    }
    rendering.print_workflows(commander.console, workflows)


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
    """Handle :world command - enter/show world or resume workflow.

    Usage:
        :world              # Show current world + backgrounded workflows
        :world <node>       # Enter node world
        :world python       # Enter python world
        :world <run_id>     # Resume backgrounded workflow (prefix match)
    """
    from nerve.frontends.tui.commander.workflow_runner import resume_workflow_tui

    # Check if arg matches a backgrounded workflow run_id
    if args and commander._active_workflows:
        run_id_prefix = args.strip()
        matching_run_ids = [
            run_id for run_id in commander._active_workflows if run_id.startswith(run_id_prefix)
        ]

        # Handle ambiguous matches
        if len(matching_run_ids) > 1:
            commander.console.print(
                f"[yellow]Ambiguous prefix '{run_id_prefix}' matches {len(matching_run_ids)} workflows:[/]"
            )
            for run_id in matching_run_ids:
                wf_info = commander._active_workflows[run_id]
                workflow_id = wf_info.get("workflow_id", "?")
                commander.console.print(f"  [dim]{run_id[:12]}[/] ({workflow_id})")
            commander.console.print("[dim]Use a longer prefix to disambiguate.[/]")
            return

        if matching_run_ids:
            matching_run_id = matching_run_ids[0]
            # Resume the workflow
            wf_info = commander._active_workflows[matching_run_id]
            workflow_id = wf_info.get("workflow_id", "")
            block_number = wf_info.get("block_number")

            commander.console.print(f"[dim]Resuming workflow {workflow_id}...[/]")

            result = await resume_workflow_tui(
                commander._adapter,  # type: ignore[arg-type]
                wf_info,
            )

            # Update the original block
            if block_number is not None and 0 <= block_number < len(commander.timeline.blocks):
                block = commander.timeline.blocks[block_number]
                block.duration_ms = result.get("duration_ms", 0)

                if result.get("backgrounded"):
                    block.status = "pending"
                    block.output_text = "(backgrounded - use :world to resume)"
                    commander._active_workflows[matching_run_id] = {
                        **wf_info,
                        "events": result.get("events", []),
                        "pending_gate": result.get("pending_gate"),
                    }
                    commander.console.print(
                        f"[dim]Workflow backgrounded. Use :world {matching_run_id[:8]} to resume[/]"
                    )
                elif result.get("state") == "completed":
                    block.status = "completed"
                    block.output_text = str(result.get("result", ""))
                    block.raw = result
                    commander._active_workflows.pop(matching_run_id, None)
                    rendering.print_block(commander.console, block)
                elif result.get("state") == "cancelled":
                    block.status = "error"
                    block.error = "Workflow cancelled"
                    block.raw = result
                    commander._active_workflows.pop(matching_run_id, None)
                    rendering.print_block(commander.console, block)
                else:
                    block.status = "error"
                    block.error = result.get("error", "Workflow failed")
                    block.raw = result
                    commander._active_workflows.pop(matching_run_id, None)
                    rendering.print_block(commander.console, block)
            return

    # Show world info or enter a world (with backgrounded workflows)
    world_to_enter = rendering.show_world(
        commander.console,
        commander.nodes,
        commander._current_world,
        args,
        commander._active_workflows,  # Pass active workflows for display
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


async def cmd_export(commander: Commander, args: str) -> None:
    """Handle :export command - export session state to JSON file.

    Usage:
        :export session.json       # Export to session.json
        :export                    # Error - filename required

    Exports:
        - Timeline blocks (completed only)
        - Entity definitions (nodes, graphs, workflows)

    Limitations:
        - Workflows can't be serialized (Python functions)
        - Graph input_fn lambdas can't be serialized
        - Node conversation history is not preserved
    """
    import json

    from nerve.frontends.tui.commander.persistence import save_session_state

    if not args:
        commander.console.print("[error]Usage: :export <filename.json>[/]")
        return

    filename = args.strip()
    if not filename.endswith(".json"):
        filename += ".json"

    try:
        state = await save_session_state(commander)
        Path(filename).write_text(json.dumps(state, indent=2), encoding="utf-8")

        # Count items
        node_count = len(state.get("entities", {}).get("nodes", []))
        graph_count = len(state.get("entities", {}).get("graphs", []))
        workflow_count = len(state.get("entities", {}).get("workflows", []))
        block_count = len(state.get("blocks", []))

        commander.console.print(f"[green]✓[/] Exported to [bold]{filename}[/]")
        commander.console.print(
            f"[dim]  {block_count} blocks, {node_count} nodes, "
            f"{graph_count} graphs, {workflow_count} workflows[/]"
        )
    except Exception as e:
        commander.console.print(f"[error]Export failed: {e}[/]")


async def cmd_import(commander: Commander, args: str) -> None:
    """Handle :import command - import session state from JSON file.

    Usage:
        :import session.json       # Import from session.json
        :import                    # Error - filename required

    Restores:
        - Timeline blocks (as completed blocks for display)
        - Entity definitions (nodes, graphs recreated)

    Limitations:
        - Workflows must be reloaded with :load
        - Node state is not preserved (fresh instances)
    """
    import json

    from nerve.frontends.tui.commander.persistence import restore_session_state

    if not args:
        commander.console.print("[error]Usage: :import <filename.json>[/]")
        return

    filename = args.strip()
    path = Path(filename)

    if not path.exists():
        commander.console.print(f"[error]File not found: {filename}[/]")
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stats = await restore_session_state(commander, data)

        commander.console.print(f"[green]✓[/] Imported from [bold]{filename}[/]")
        commander.console.print(
            f"[dim]  {stats['blocks_restored']} blocks restored, "
            f"{stats['nodes_created']} nodes created, "
            f"{stats['graphs_created']} graphs created[/]"
        )

        if stats["workflows_skipped"]:
            commander.console.print(
                f"[yellow]  {stats['workflows_skipped']} workflows skipped "
                f"(use :load to reload workflow files)[/]"
            )

        if stats["errors"]:
            for error in stats["errors"]:
                commander.console.print(f"[error]  {error}[/]")

    except json.JSONDecodeError as e:
        commander.console.print(f"[error]Invalid JSON: {e}[/]")
    except Exception as e:
        commander.console.print(f"[error]Import failed: {e}[/]")


async def cmd_load(commander: Commander, args: str) -> None:
    """Handle :load command - load workflow(s) from Python file(s).

    Usage:
        :load workflow.py              # Load single file
        :load file1.py file2.py        # Load multiple files
        :load workflows/*.py           # Load with glob pattern

    The file should define workflow functions and register them using
    the Workflow class. The `session` variable is available in scope.

    Example workflow file:
        from nerve.core.workflow import Workflow, WorkflowContext

        async def my_workflow(ctx: WorkflowContext) -> str:
            return f"Hello, {ctx.input}!"

        Workflow(id="my-workflow", session=session, fn=my_workflow)
    """
    if not args:
        commander.console.print("[error]Usage: :load <file.py> [file2.py ...][/]")
        commander.console.print("[dim]Supports glob patterns: :load workflows/*.py[/]")
        return

    # Expand glob patterns and collect all files
    file_patterns = args.split()
    files_to_load: list[Path] = []

    for pattern in file_patterns:
        # Expand glob patterns
        matches = glob.glob(pattern)
        if matches:
            for match in matches:
                path = Path(match)
                if path.is_file() and path.suffix == ".py":
                    files_to_load.append(path)
        else:
            # Try as literal path
            path = Path(pattern)
            if path.is_file():
                files_to_load.append(path)
            else:
                commander.console.print(f"[warning]File not found: {pattern}[/]")

    if not files_to_load:
        commander.console.print("[error]No Python files found to load[/]")
        return

    # Load each file
    loaded_count = 0
    for file_path in files_to_load:
        try:
            code = file_path.read_text()
            output, error = await commander._adapter.execute_python(code, {})  # type: ignore[union-attr]

            if error:
                commander.console.print(f"[error]Error loading {file_path.name}: {error}[/]")
            else:
                loaded_count += 1
                commander.console.print(f"[green]✓[/] Loaded [bold]{file_path.name}[/]")
                if output and output.strip():
                    commander.console.print(f"[dim]{output.strip()}[/]")

        except Exception as e:
            commander.console.print(f"[error]Failed to load {file_path.name}: {e}[/]")

    # Refresh entities to pick up new workflows
    if loaded_count > 0:
        await commander._sync_entities()
        # Count workflows
        workflow_count = sum(1 for e in commander.entities.values() if e.type == "workflow")
        commander.console.print(
            f"[dim]Loaded {loaded_count} file(s). {workflow_count} workflow(s) registered.[/]"
        )


# Command registry - maps command names to handlers
COMMANDS: dict[str, CommandHandler] = {
    "exit": cmd_exit,
    "back": cmd_back,
    "help": cmd_help,
    "nodes": cmd_nodes,
    "graphs": cmd_graphs,
    "workflows": cmd_workflows,
    "entities": cmd_entities,
    "info": cmd_info,
    "timeline": cmd_timeline,
    "clear": cmd_clear,
    "clean": cmd_clean,
    "refresh": cmd_refresh,
    "theme": cmd_theme,
    "world": cmd_world,
    "loop": cmd_loop,
    "load": cmd_load,
    "export": cmd_export,
    "import": cmd_import,
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
