"""REPL command handlers for local and remote modes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nerve.frontends.cli.output import format_history_entry

if TYPE_CHECKING:
    from nerve.core.nodes import Graph
    from nerve.core.session import Session
    from nerve.frontends.cli.repl.adapters import SessionAdapter
    from nerve.frontends.cli.repl.state import REPLState
    from nerve.transport import UnixSocketClient


async def send_repl_command(
    client: UnixSocketClient,
    command: str,
    args: list[str],
    session_id: str | None = None,
) -> tuple[str | None, str | None]:
    """Send a REPL command to the server and return (output, error).

    Args:
        client: Connected UnixSocketClient
        command: Command name (e.g., "show", "validate", "dry", "read")
        args: Command arguments
        session_id: Optional session ID

    Returns:
        Tuple of (output, error). One will be None.
    """
    from nerve.server.protocols import Command, CommandType

    params: dict[str, Any] = {"command": command, "args": args}
    if session_id:
        params["session_id"] = session_id

    result = await client.send_command(
        Command(type=CommandType.EXECUTE_REPL_COMMAND, params=params)
    )

    if result.success and result.data:
        return result.data.get("output"), result.data.get("error")
    return None, result.error


def print_repl_result(output: str | None, error: str | None) -> None:
    """Print REPL command result."""
    if output:
        print(output, end="")
    if error:
        print(f"Error: {error}")


async def handle_show_local(
    adapter: SessionAdapter,
    state: REPLState,
    current_graph: Graph | None,
    graph_name: str | None,
) -> None:
    """Handle 'show' command in local mode."""
    from nerve.frontends.cli.repl.display import print_graph

    graph = None
    if graph_name:
        graph = await adapter.get_graph(graph_name)
        if not graph:
            print(f"Graph not found: {graph_name}")
            return
    else:
        graph = state.namespace.get("graph") or current_graph
    print_graph(graph)


async def handle_show_remote(
    client: UnixSocketClient,
    session_id: str | None,
    graph_name: str,
) -> None:
    """Handle 'show' command in remote mode."""
    output, error = await send_repl_command(client, "show", [graph_name], session_id)
    print_repl_result(output, error)


async def handle_validate_local(
    adapter: SessionAdapter,
    state: REPLState,
    current_graph: Graph | None,
    graph_name: str | None,
) -> None:
    """Handle 'validate' command in local mode."""
    graph = None
    if graph_name:
        graph = await adapter.get_graph(graph_name)
        if not graph:
            print(f"Graph not found: {graph_name}")
            return
    else:
        graph = state.namespace.get("graph") or current_graph

    if graph:
        errors = graph.validate()
        if errors:
            print("Validation FAILED:")
            for err in errors:
                print(f"  - {err}")
        else:
            print("Validation PASSED")
    else:
        print("No Graph defined")


async def handle_validate_remote(
    client: UnixSocketClient,
    session_id: str | None,
    graph_name: str,
) -> None:
    """Handle 'validate' command in remote mode."""
    output, error = await send_repl_command(client, "validate", [graph_name], session_id)
    print_repl_result(output, error)


async def handle_dry_local(
    adapter: SessionAdapter,
    state: REPLState,
    current_graph: Graph | None,
    graph_name: str | None,
) -> None:
    """Handle 'dry' command in local mode."""
    graph = None
    if graph_name:
        graph = await adapter.get_graph(graph_name)
        if not graph:
            print(f"Graph not found: {graph_name}")
            return
    else:
        graph = state.namespace.get("graph") or current_graph

    if graph:
        try:
            order = graph.execution_order()
            print("\nExecution order:")
            for i, step_id in enumerate(order, 1):
                print(f"  [{i}] {step_id}")
        except ValueError as e:
            print(f"Error: {e}")
    else:
        print("No Graph defined")


async def handle_dry_remote(
    client: UnixSocketClient,
    session_id: str | None,
    graph_name: str,
) -> None:
    """Handle 'dry' command in remote mode."""
    output, error = await send_repl_command(client, "dry", [graph_name], session_id)
    print_repl_result(output, error)


async def handle_read_local(
    session: Session | None,
    node_name: str,
) -> None:
    """Handle 'read' command in local mode."""
    node = session.get_node(node_name) if session else None
    if not node:
        print(f"Node not found: {node_name}")
        return
    if hasattr(node, "read"):
        try:
            buffer_content = await node.read()
            print(buffer_content)
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Node does not support read")


async def handle_read_remote(
    client: UnixSocketClient,
    session_id: str | None,
    node_name: str,
) -> None:
    """Handle 'read' command in remote mode."""
    output, error = await send_repl_command(client, "read", [node_name], session_id)
    print_repl_result(output, error)


def format_history_entry_repl(entry: dict[str, Any]) -> str:
    """Format a single history entry for REPL display (40 char truncation)."""
    return format_history_entry(entry, truncate=40)


def print_history_repl(
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
            print(format_history_entry_repl(entry))
