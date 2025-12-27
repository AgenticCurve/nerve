"""Command registry and dispatch for REPL.

This module provides:
- CommandContext: All shared state needed by command handlers
- CommandResult: Result of command execution with control flow signals
- Graph resolution helper
- Error handling decorator for remote mode
- Command registry with handler functions
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import wraps
from typing import TYPE_CHECKING, Any

from nerve.frontends.cli.output import format_history_entry
from nerve.frontends.cli.repl.display import print_help, print_nodes
from nerve.frontends.cli.utils import REMOTE_ERRORS

if TYPE_CHECKING:
    from nerve.core.nodes import Graph
    from nerve.core.session import Session
    from nerve.frontends.cli.repl.adapters import SessionAdapter
    from nerve.frontends.cli.repl.state import REPLState


class CommandAction(Enum):
    """Control flow actions from command handlers."""

    CONTINUE = auto()  # Continue REPL loop
    BREAK = auto()  # Exit REPL loop (normal exit)
    DISCONNECT = auto()  # Server disconnected, exit REPL


@dataclass
class CommandContext:
    """All state needed by command handlers.

    This consolidates the scattered variables from the main REPL loop
    into a single object that can be passed to command handlers.

    Mode is determined via adapter.supports_local_execution.
    """

    adapter: SessionAdapter
    state: REPLState
    # Local mode only
    session: Session | None = None
    current_graph: Graph | None = None
    # Mutable state that commands can update
    mutable: dict[str, Any] = field(default_factory=dict)

    def update_graph(self, graph: Graph | None) -> None:
        """Update current graph reference."""
        self.current_graph = graph

    def update_session(self, session: Session) -> None:
        """Update session (used by reset command)."""
        self.session = session


@dataclass
class CommandResult:
    """Result from a command handler."""

    action: CommandAction = CommandAction.CONTINUE
    message: str | None = None  # Optional message to display


# Type alias for command handlers
CommandHandler = Callable[[CommandContext, list[str]], Coroutine[Any, Any, CommandResult]]


# =============================================================================
# Helper Functions
# =============================================================================


def handle_remote_errors(
    handler: CommandHandler,
) -> CommandHandler:
    """Decorator to handle remote connection errors consistently.

    Wraps a command handler to catch REMOTE_ERRORS and return
    DISCONNECT action instead of raising.
    """

    @wraps(handler)
    async def wrapper(ctx: CommandContext, args: list[str]) -> CommandResult:
        try:
            return await handler(ctx, args)
        except REMOTE_ERRORS:
            if not ctx.adapter.supports_local_execution:
                return CommandResult(action=CommandAction.DISCONNECT)
            raise

    return wrapper


# =============================================================================
# Command Handlers
# =============================================================================


async def cmd_help(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Show help."""
    print_help()
    return CommandResult()


@handle_remote_errors
async def cmd_nodes(ctx: CommandContext, args: list[str]) -> CommandResult:
    """List all nodes."""
    await print_nodes(ctx.adapter)
    return CommandResult()


@handle_remote_errors
async def cmd_graphs(ctx: CommandContext, args: list[str]) -> CommandResult:
    """List all graphs."""
    graph_ids = await ctx.adapter.list_graphs()
    if graph_ids:
        print("\nGraphs:")
        for gid in graph_ids:
            print(f"  {gid}")
    else:
        print("No graphs defined")
    return CommandResult()


@handle_remote_errors
async def cmd_session(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Show session info."""
    # Refresh cached data before displaying
    await ctx.adapter.list_nodes()
    await ctx.adapter.list_graphs()

    print(f"\nSession: {ctx.adapter.name}")
    print(f"  ID: {ctx.adapter.id}")
    if hasattr(ctx.adapter, "server_name"):
        print(f"  Server: {ctx.adapter.server_name}")
    print(f"  Nodes: {ctx.adapter.node_count}")
    print(f"  Graphs: {ctx.adapter.graph_count}")
    return CommandResult()


@handle_remote_errors
async def cmd_send(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Send input to a node."""
    if len(args) < 2:
        print("Usage: send <node> <text>")
        return CommandResult()

    node_name = args[0]
    text = args[1]

    try:
        response = await ctx.adapter.execute_on_node(node_name, text)
        # Pretty print the response
        if isinstance(response, (dict, list)):
            print(json.dumps(response, indent=2))
        elif isinstance(response, str):
            # Try to parse as JSON/dict string
            try:
                parsed = json.loads(response)
                print(json.dumps(parsed, indent=2))
            except (json.JSONDecodeError, ValueError):
                import ast

                try:
                    parsed = ast.literal_eval(response)
                    print(json.dumps(parsed, indent=2))
                except (ValueError, SyntaxError):
                    print(response)
        else:
            print(response)
    except Exception as e:
        print(f"Error: {e}")
    return CommandResult()


@handle_remote_errors
async def cmd_read(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Read node's output buffer."""
    if len(args) < 1:
        print("Usage: read <node>")
        return CommandResult()

    node_name = args[0]
    try:
        buffer_content = await ctx.adapter.read_node_buffer(node_name)
        print(buffer_content)
    except ValueError as e:
        print(f"Error: {e}")
    return CommandResult()


@handle_remote_errors
async def cmd_stop(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Stop a node."""
    if len(args) < 1:
        print("Usage: stop <node>")
        return CommandResult()

    node_name = args[0]
    try:
        await ctx.adapter.stop_node(node_name)
        print(f"Stopped: {node_name}")
    except NotImplementedError:
        print("Command not available in server mode")
    except ValueError as e:
        print(f"Error: {e}")
    return CommandResult()


@handle_remote_errors
async def cmd_delete(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Delete a node."""
    if len(args) < 1:
        print("Usage: delete <node>")
        return CommandResult()

    node_name = args[0]
    try:
        success = await ctx.adapter.delete_node(node_name)
        if success:
            print(f"Deleted: {node_name}")
        else:
            print(f"Node not found: {node_name}")
    except Exception as e:
        print(f"Error: {e}")
    return CommandResult()


async def cmd_history(ctx: CommandContext, args: list[str]) -> CommandResult:
    """View node's history."""
    if len(args) < 1:
        print("Usage: history <node> [--last N] [--op TYPE] [--summary]")
        return CommandResult()

    node_name = args[0]

    # Parse optional flags from remaining args
    remaining = args[1:]
    last = None
    op = None
    summary = False

    i = 0
    while i < len(remaining):
        if remaining[i] == "--last" and i + 1 < len(remaining):
            try:
                last = int(remaining[i + 1])
                i += 2
            except ValueError:
                print(f"Invalid --last value: {remaining[i + 1]}")
                return CommandResult()
        elif remaining[i] == "--op" and i + 1 < len(remaining):
            op = remaining[i + 1]
            i += 2
        elif remaining[i] == "--summary":
            summary = True
            i += 1
        else:
            i += 1

    from nerve.core.nodes.history import HistoryReader

    try:
        # Determine server and session names for history file lookup
        server = ctx.adapter.server_name
        sess = ctx.adapter.name

        reader = HistoryReader.create(
            node_id=node_name,
            server_name=server,
            session_name=sess,
        )

        # Get entries
        if op:
            entries = reader.get_by_op(op)
        else:
            entries = reader.get_all()

        # Apply limit
        if last is not None and last < len(entries):
            entries = entries[-last:]

        if not entries:
            print("No history entries found")
            return CommandResult()

        # Display
        _print_history_repl(entries, summary, node_name, server, sess)

    except FileNotFoundError:
        print(f"No history found for node '{node_name}'")
    except Exception as e:
        print(f"Error reading history: {e}")
    return CommandResult()


def _print_history_repl(
    entries: list[dict[str, Any]],
    summary: bool,
    node_name: str,
    server_name: str,
    session_name: str,
) -> None:
    """Print history entries for REPL."""
    from collections import Counter

    if summary:
        ops_count = Counter(e.get("op", "unknown") for e in entries)
        print(f"Node: {node_name}")
        print(f"Server: {server_name}")
        print(f"Session: {session_name}")
        print(f"Total entries: {len(entries)}")
        print("\nOperations:")
        for op_type, count in sorted(ops_count.items()):
            print(f"  {op_type}: {count}")
    else:
        for entry in entries:
            print(format_history_entry(entry, truncate=40))


async def cmd_reset(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Reset session (local mode only)."""
    if not ctx.adapter.supports_local_execution:
        print("Command not available in server mode")
        return CommandResult()

    from nerve.core.nodes import ExecutionContext
    from nerve.core.session import Session

    if ctx.session:
        await ctx.session.stop()
    ctx.state.nodes.clear()

    # Recreate session
    session = Session(name="default", server_name="repl")
    ctx.state.namespace["session"] = session
    ctx.state.namespace["context"] = ExecutionContext(session=session)
    ctx.state.namespace["nodes"] = ctx.state.nodes

    # Update context
    ctx.update_session(session)
    ctx.update_graph(None)

    # Signal that adapter needs update - store in mutable dict
    ctx.mutable["new_session"] = session

    print("Session reset")
    return CommandResult()


@handle_remote_errors
async def cmd_show(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Show graph structure."""
    graph_name = args[0] if args else None
    fallback = ctx.state.namespace.get("graph") or ctx.current_graph

    try:
        output = await ctx.adapter.show_graph(graph_name, fallback)
        print(output)
    except ValueError as e:
        print(f"Error: {e}")
    return CommandResult()


@handle_remote_errors
async def cmd_validate(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Validate graph."""
    graph_name = args[0] if args else None
    fallback = ctx.state.namespace.get("graph") or ctx.current_graph

    try:
        output = await ctx.adapter.validate_graph(graph_name, fallback)
        print(output)
    except ValueError as e:
        print(f"Error: {e}")
    return CommandResult()


@handle_remote_errors
async def cmd_dry(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Dry run - show execution order."""
    graph_name = args[0] if args else None
    fallback = ctx.state.namespace.get("graph") or ctx.current_graph

    try:
        output = await ctx.adapter.dry_run_graph(graph_name, fallback)
        print(output)
    except ValueError as e:
        print(f"Error: {e}")
    return CommandResult()


async def cmd_run(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Execute graph (local mode only)."""
    if not ctx.adapter.supports_local_execution:
        print("Graph execution not available in server mode")
        print("Use server REPL commands instead")
        return CommandResult()

    from nerve.core.nodes import ExecutionContext

    # Resolve graph: explicit name, or fallback to namespace/current
    graph_name = args[0] if args else None
    if graph_name:
        graph = await ctx.adapter.get_graph(graph_name)
        if not graph:
            print(f"Graph not found: {graph_name}")
            return CommandResult()
    else:
        graph = ctx.state.namespace.get("graph") or ctx.current_graph

    if graph:
        try:
            print("\nExecuting Graph...")
            context = ExecutionContext(session=ctx.session)
            results = await graph.execute(context)
            ctx.state.namespace["_results"] = results
            print("\nResults stored in '_results'")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("No Graph defined")
    return CommandResult()


async def cmd_exit(ctx: CommandContext, args: list[str]) -> CommandResult:
    """Exit the REPL."""
    print("Exiting...")
    return CommandResult(action=CommandAction.BREAK)


# =============================================================================
# Command Registry
# =============================================================================

# Map command names to handler functions
COMMANDS: dict[str, CommandHandler] = {
    "help": cmd_help,
    "nodes": cmd_nodes,
    "graphs": cmd_graphs,
    "session": cmd_session,
    "send": cmd_send,
    "read": cmd_read,
    "stop": cmd_stop,
    "delete": cmd_delete,
    "history": cmd_history,
    "reset": cmd_reset,
    "show": cmd_show,
    "validate": cmd_validate,
    "dry": cmd_dry,
    "run": cmd_run,
    "exit": cmd_exit,
    "quit": cmd_exit,  # Alias
}


async def dispatch_command(
    ctx: CommandContext,
    command: str,
    args: list[str],
) -> CommandResult | None:
    """Dispatch a command to its handler.

    Args:
        ctx: Command context
        command: Command name (lowercase)
        args: Command arguments

    Returns:
        CommandResult if command was handled, None if not a recognized command.
    """
    handler = COMMANDS.get(command)
    if handler:
        return await handler(ctx, args)
    return None
