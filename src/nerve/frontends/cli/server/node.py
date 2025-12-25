"""Node subcommands for server."""

from __future__ import annotations

import asyncio
import sys

import rich_click as click

from nerve.frontends.cli.server import server
from nerve.frontends.cli.utils import create_client


@server.group()
def node() -> None:
    """Manage nodes.

    Nodes are persistent execution contexts that maintain state across
    interactions. They can run any process: AI CLIs (Claude, Gemini),
    shells (bash, zsh), interpreters (Python, Node), or other programs.

    **Commands:**

        nerve server node list      List nodes in a session

        nerve server node create    Create a new node

        nerve server node delete    Delete a node

        nerve server node send      Send input and get response
    """
    pass


@node.command("list")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
def node_list(server_name: str, session_id: str | None, json_output: bool) -> None:
    """List all nodes in a session.

    Shows nodes in the specified session (or default session).

    **Examples:**

        nerve server node list

        nerve server node list --server myproject

        nerve server node list --server myproject --session my-workspace

        nerve server node list --json
    """
    from nerve.server.protocols import Command, CommandType

    async def run() -> None:
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        params = {}
        if session_id:
            params["session_id"] = session_id

        result = await client.send_command(
            Command(
                type=CommandType.GET_SESSION,
                params=params,
            )
        )

        if result.success and result.data:
            nodes_info = result.data.get("nodes_info", [])

            if json_output:
                import json

                click.echo(json.dumps(nodes_info, indent=2))
            elif nodes_info:
                click.echo(f"{'NAME':<20} {'BACKEND':<18} {'STATE':<10} {'LAST INPUT'}")
                click.echo("-" * 70)
                for info in nodes_info:
                    name = info.get("id", "?")
                    backend = info.get("backend", info.get("type", "?"))
                    state = info.get("state", "?")
                    last_input = info.get("last_input", "")
                    if last_input:
                        last_input = last_input[:30]
                    click.echo(f"{name:<20} {backend:<18} {state:<10} {last_input}")
            else:
                session_name = result.data.get("name", "default")
                click.echo(f"No nodes in session '{session_name}'")
        else:
            click.echo(f"Error: {result.error}", err=True)
            sys.exit(1)

        await client.disconnect()

    asyncio.run(run())


@node.command("create")
@click.argument("name")
@click.option(
    "--server", "-s", "server_name", required=True, help="Server name to create the node on"
)
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
@click.option(
    "--command", "-c", default=None, help="Command to run (e.g., 'claude' or 'my-cli --flag')"
)
@click.option("--cwd", default=None, help="Working directory for the node")
@click.option(
    "--backend",
    "-b",
    type=click.Choice(["pty", "wezterm", "claude-wezterm"]),
    default="pty",
    help="Backend (pty, wezterm, or claude-wezterm)",
)
@click.option(
    "--pane-id", default=None, help="Attach to existing WezTerm pane (wezterm backend only)"
)
@click.option(
    "--history/--no-history",
    default=True,
    help="Enable/disable history logging (default: enabled)",
)
def node_create(
    name: str,
    server_name: str,
    session_id: str | None,
    command: str | None,
    cwd: str | None,
    backend: str,
    pane_id: str | None,
    history: bool,
) -> None:
    """Create a new node.

    NAME is the node name (required, must be unique).
    Names must be lowercase alphanumeric with dashes, 1-32 characters.

    **Examples:**

        nerve server node create my-claude --server myproject --command claude

        nerve server node create gemini-1 --server myproject --command gemini

        nerve server node create attached --server myproject --backend wezterm --pane-id 4

        nerve server node create claude --server myproject --session my-workspace
    """
    from nerve.core.validation import validate_name
    from nerve.server.protocols import Command, CommandType

    try:
        validate_name(name, "node")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    async def run() -> None:
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        params = {
            "node_id": name,
            "cwd": cwd,
            "backend": backend,
            "history": history,
        }
        if session_id:
            params["session_id"] = session_id
        if command:
            params["command"] = command
        if pane_id:
            params["pane_id"] = pane_id

        result = await client.send_command(
            Command(
                type=CommandType.CREATE_NODE,
                params=params,
            )
        )

        if result.success:
            click.echo(f"Created node: {name}")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@node.command("delete")
@click.argument("node_name")
@click.option("--server", "-s", "server_name", required=True, help="Server name the node is on")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
def node_delete(node_name: str, server_name: str, session_id: str | None) -> None:
    """Delete a node.

    Stops the node, closes its terminal/pane, and removes it from the server.

    **Arguments:**

        NODE_NAME     The node to delete

    **Examples:**

        nerve server node delete my-claude --server local

        nerve server node delete my-shell -s myproject

        nerve server node delete claude --server myproject --session my-workspace
    """
    from nerve.server.protocols import Command, CommandType

    async def run() -> None:
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        params = {"node_id": node_name}
        if session_id:
            params["session_id"] = session_id

        result = await client.send_command(
            Command(
                type=CommandType.DELETE_NODE,
                params=params,
            )
        )

        if result.success:
            click.echo(f"Deleted node: {node_name}")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@node.command("run")
@click.argument("node_name")
@click.argument("command")
@click.option("--server", "-s", "server_name", required=True, help="Server name the node is on")
def node_run(node_name: str, command: str, server_name: str) -> None:
    """Start a program in a node (fire and forget).

    Use this to launch programs that take over the terminal,
    like claude, python, vim, etc. This does NOT wait for the
    program to be ready - use 'send' to interact with it after.

    **Arguments:**

        NODE_NAME     The node to run in

        COMMAND       The program/command to start

    **Examples:**

        nerve server node run my-shell claude --server myproject

        nerve server node run my-shell python --server myproject

        nerve server node run my-shell "gemini --flag" --server myproject
    """
    from nerve.server.protocols import Command, CommandType

    async def run() -> None:
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        result = await client.send_command(
            Command(
                type=CommandType.RUN_COMMAND,
                params={
                    "node_id": node_name,
                    "command": command,
                },
            )
        )

        if result.success:
            click.echo(f"Started: {command}")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@node.command("read")
@click.argument("node_name")
@click.option("--server", "-s", "server_name", required=True, help="Server name the node is on")
@click.option("--lines", "-n", default=None, type=int, help="Only show last N lines")
def node_read(node_name: str, server_name: str, lines: int | None) -> None:
    """Read the output buffer of a node.

    Shows all output from the node since it was created.

    **Arguments:**

        NODE_NAME     The node to read from

    **Examples:**

        nerve server node read my-shell --server local

        nerve server node read my-shell --server local --lines 50
    """
    from nerve.server.protocols import Command, CommandType

    async def run() -> None:
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        params: dict[str, str | int] = {"node_id": node_name}
        if lines:
            params["lines"] = lines

        result = await client.send_command(
            Command(
                type=CommandType.GET_BUFFER,
                params=params,
            )
        )

        if result.success and result.data:
            click.echo(result.data.get("buffer", ""))
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@node.command("send")
@click.argument("node_name")
@click.argument("text")
@click.option("--server", "-s", "server_name", required=True, help="Server name the node is on")
@click.option(
    "--parser",
    "-p",
    type=click.Choice(["claude", "gemini", "none"]),
    default=None,
    help="Parser for output. Default: auto-detect from node type.",
)
@click.option(
    "--submit",
    default=None,
    help="Submit sequence (e.g., '\\n', '\\r', '\\x1b\\r'). Default: auto based on parser.",
)
def node_send(
    node_name: str, text: str, server_name: str, parser: str | None, submit: str | None
) -> None:
    """Send input to a node and get JSON response.

    **Arguments:**

        NODE_NAME     The node to send to

        TEXT          The text/prompt to send

    **Examples:**

        nerve server node send my-claude "Explain this code" --server myproject

        nerve server node send my-shell "ls" --server myproject --parser none
    """
    import json

    from nerve.server.protocols import Command, CommandType

    async def run() -> None:
        client = create_client(server_name)
        await client.connect()

        params = {
            "node_id": node_name,
            "text": text,
        }
        # Only include parser if explicitly set (let node use its default)
        if parser is not None:
            params["parser"] = parser
        # Decode escape sequences in submit string (e.g., "\\x1b" -> actual escape)
        if submit:
            params["submit"] = submit.encode().decode("unicode_escape")

        result = await client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params=params,
            )
        )

        if not result.success:
            # Output error as JSON
            click.echo(json.dumps({"error": result.error}, indent=2))
        elif result.data:
            # Output response as JSON
            response = result.data.get("response", {})
            click.echo(json.dumps(response, indent=2))

        await client.disconnect()

    asyncio.run(run())


@node.command("write")
@click.argument("node_name")
@click.argument("data")
@click.option("--server", "-s", "server_name", required=True, help="Server name the node is on")
def node_write(node_name: str, data: str, server_name: str) -> None:
    """Write raw data to a node (no waiting).

    Low-level write for testing and debugging. Does not wait for response.
    Use escape sequences like \\x1b for Escape, \\r for CR, \\n for LF.

    **Arguments:**

        NODE_NAME     The node to write to

        DATA          Raw data to write (escape sequences supported)

    **Examples:**

        nerve server node write my-shell "Hello" --server local

        nerve server node write my-shell "\\x1b" --server local  # Send Escape

        nerve server node write my-shell "\\r" --server local    # Send CR
    """
    from nerve.server.protocols import Command, CommandType

    # Decode escape sequences
    decoded_data = data.encode().decode("unicode_escape")

    async def run() -> None:
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        result = await client.send_command(
            Command(
                type=CommandType.WRITE_DATA,
                params={
                    "node_id": node_name,
                    "data": decoded_data,
                },
            )
        )

        if result.success:
            click.echo(f"Wrote {len(decoded_data)} bytes")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@node.command("interrupt")
@click.argument("node_name")
@click.option("--server", "-s", "server_name", required=True, help="Server name the node is on")
def node_interrupt(node_name: str, server_name: str) -> None:
    """Send interrupt (Ctrl+C) to a node.

    Cancels the current operation in the node.

    **Arguments:**

        NODE_NAME     The node to interrupt

    **Examples:**

        nerve server node interrupt my-claude --server local
    """
    from nerve.server.protocols import Command, CommandType

    async def run() -> None:
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        result = await client.send_command(
            Command(
                type=CommandType.SEND_INTERRUPT,
                params={"node_id": node_name},
            )
        )

        if result.success:
            click.echo("Interrupt sent")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@node.command("history")
@click.argument("node_name")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option(
    "--session", "session_name", default="default", help="Session name (default: default)"
)
@click.option("--last", "-n", "limit", type=int, default=None, help="Show only last N entries")
@click.option(
    "--op",
    type=click.Choice(["send", "send_stream", "write", "run", "read", "interrupt", "delete"]),
    help="Filter by operation type",
)
@click.option("--seq", type=int, default=None, help="Get entry by sequence number")
@click.option("--inputs-only", is_flag=True, help="Show only input operations (send, write, run)")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
@click.option("--summary", is_flag=True, help="Show summary statistics")
def node_history(
    node_name: str,
    server_name: str,
    session_name: str,
    limit: int | None,
    op: str | None,
    seq: int | None,
    inputs_only: bool,
    json_output: bool,
    summary: bool,
) -> None:
    """View history for a node.

    Reads the JSONL history file for the specified node.
    History is stored in .nerve/history/<server>/<session>/<node>.jsonl

    **Arguments:**

        NODE_NAME     The node to view history for

    **Examples:**

        nerve server node history my-claude

        nerve server node history my-claude --last 10

        nerve server node history my-claude --server prod --session my-session

        nerve server node history my-claude --op send

        nerve server node history my-claude --inputs-only --json

        nerve server node history my-claude --summary
    """
    import json
    from pathlib import Path

    from nerve.core.nodes.history import HistoryReader

    try:
        # Default base directory
        base_dir = Path.cwd() / ".nerve" / "history"

        reader = HistoryReader.create(
            node_id=node_name,
            server_name=server_name,
            session_name=session_name,
            base_dir=base_dir,
        )

        # Get entries based on filters
        if seq is not None:
            entry = reader.get_by_seq(seq)
            if entry is None:
                click.echo(f"No entry with sequence number {seq}", err=True)
                sys.exit(1)
            entries = [entry]
        elif inputs_only:
            entries = reader.get_inputs_only()
        elif op:
            entries = reader.get_by_op(op)
        else:
            entries = reader.get_all()

        # Apply limit if specified
        if limit is not None:
            entries = entries[-limit:] if limit < len(entries) else entries

        if not entries:
            click.echo("No history entries found")
            return

        # Summary mode
        if summary:
            ops_count: dict[str, int] = {}
            for e in entries:
                op_type = e.get("op", "unknown")
                ops_count[op_type] = ops_count.get(op_type, 0) + 1
            click.echo(f"Node: {node_name}")
            click.echo(f"Server: {server_name}")
            click.echo(f"Session: {session_name}")
            click.echo(f"Total entries: {len(entries)}")
            click.echo("\nOperations:")
            for op_name, count in sorted(ops_count.items()):
                click.echo(f"  {op_name}: {count}")
            return

        if json_output:
            click.echo(json.dumps(entries, indent=2, default=str))
        else:
            # Pretty print history
            for entry in entries:
                seq_num = entry.get("seq", "?")
                op_type = entry.get("op", "unknown")
                ts = entry.get("ts", entry.get("ts_start", ""))

                # Format timestamp for display (just time portion)
                if ts:
                    ts_display = ts.split("T")[1][:8] if "T" in ts else ts[:8]
                else:
                    ts_display = ""

                if op_type == "send":
                    input_text = entry.get("input", "")[:50]
                    response = entry.get("response", {})
                    sections = response.get("sections", [])
                    section_count = len(sections)
                    click.echo(
                        f"[{seq_num:3}] {ts_display} SEND    {input_text!r} -> {section_count} sections"
                    )
                elif op_type == "send_stream":
                    input_text = entry.get("input", "")[:50]
                    click.echo(f"[{seq_num:3}] {ts_display} STREAM  {input_text!r}")
                elif op_type == "run":
                    cmd = entry.get("input", "")[:50]
                    click.echo(f"[{seq_num:3}] {ts_display} RUN     {cmd!r}")
                elif op_type == "write":
                    data_str = entry.get("input", "")[:30].replace("\n", "\\n")
                    click.echo(f"[{seq_num:3}] {ts_display} WRITE   {data_str!r}")
                elif op_type == "read":
                    lines_count = entry.get("lines", 0)
                    buffer_len = len(entry.get("buffer", ""))
                    click.echo(
                        f"[{seq_num:3}] {ts_display} READ    {lines_count} lines, {buffer_len} chars"
                    )
                elif op_type == "interrupt":
                    click.echo(f"[{seq_num:3}] {ts_display} INTERRUPT")
                elif op_type == "delete":
                    reason = entry.get("reason", "")
                    click.echo(f"[{seq_num:3}] {ts_display} DELETE  {reason or ''}")
                else:
                    click.echo(f"[{seq_num:3}] {ts_display} {op_type.upper()}")

    except FileNotFoundError:
        click.echo(
            f"No history found for node '{node_name}' in session '{session_name}' on server '{server_name}'",
            err=True,
        )
        sys.exit(1)
