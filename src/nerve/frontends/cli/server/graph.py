"""Graph subcommands and server REPL for server."""

from __future__ import annotations

import asyncio
import sys

import rich_click as click

from nerve.frontends.cli.server import server
from nerve.frontends.cli.utils import create_client


@server.group()
def graph():
    """Manage and execute graphs on the server.

    Graphs are multi-step workflows that orchestrate node execution.
    They can be registered in a session and executed later.

    **Commands:**

        nerve server graph list      List registered graphs

        nerve server graph create    Create an empty graph

        nerve server graph delete    Delete a graph

        nerve server graph info      Get graph details

        nerve server graph run       Run a graph file
    """
    pass


@graph.command("list")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
def graph_list(server_name: str, session_id: str | None, json_output: bool):
    """List registered graphs in a session.

    **Examples:**

        nerve server graph list --server myproject

        nerve server graph list --server myproject --session my-workspace
    """
    from nerve.server.protocols import Command, CommandType

    async def run():
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
                type=CommandType.LIST_GRAPHS,
                params=params,
            )
        )

        if result.success:
            graphs = result.data.get("graphs", [])

            if json_output:
                import json

                click.echo(json.dumps(result.data, indent=2))
            elif graphs:
                click.echo(f"{'ID':<20} {'STEPS'}")
                click.echo("-" * 30)
                for g in graphs:
                    click.echo(f"{g['id']:<20} {g.get('step_count', 0)}")
            else:
                click.echo("No graphs registered")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@graph.command("create")
@click.argument("graph_id")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
def graph_create(graph_id: str, server_name: str, session_id: str | None):
    """Create an empty graph.

    Creates a graph that can have steps added later.

    **Arguments:**

        GRAPH_ID      Unique identifier for the graph

    **Examples:**

        nerve server graph create my-workflow --server myproject

        nerve server graph create pipeline --server myproject --session my-workspace
    """
    from nerve.server.protocols import Command, CommandType

    async def run():
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        params = {"graph_id": graph_id}
        if session_id:
            params["session_id"] = session_id

        result = await client.send_command(
            Command(
                type=CommandType.CREATE_GRAPH,
                params=params,
            )
        )

        if result.success:
            click.echo(f"Created graph: {graph_id}")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@graph.command("delete")
@click.argument("graph_id")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
def graph_delete(graph_id: str, server_name: str, session_id: str | None):
    """Delete a graph.

    **Arguments:**

        GRAPH_ID      The graph to delete

    **Examples:**

        nerve server graph delete my-workflow --server myproject
    """
    from nerve.server.protocols import Command, CommandType

    async def run():
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        params = {"graph_id": graph_id}
        if session_id:
            params["session_id"] = session_id

        result = await client.send_command(
            Command(
                type=CommandType.DELETE_GRAPH,
                params=params,
            )
        )

        if result.success:
            click.echo(f"Deleted graph: {graph_id}")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@graph.command("info")
@click.argument("graph_id")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
def graph_info(graph_id: str, server_name: str, session_id: str | None, json_output: bool):
    """Get graph info.

    **Arguments:**

        GRAPH_ID      The graph to get info for

    **Examples:**

        nerve server graph info my-workflow --server myproject
    """
    from nerve.server.protocols import Command, CommandType

    async def run():
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        params = {"graph_id": graph_id}
        if session_id:
            params["session_id"] = session_id

        result = await client.send_command(
            Command(
                type=CommandType.GET_GRAPH,
                params=params,
            )
        )

        if result.success:
            if json_output:
                import json

                click.echo(json.dumps(result.data, indent=2))
            else:
                data = result.data
                click.echo(f"Graph: {data.get('graph_id')}")
                steps = data.get("steps", [])
                if steps:
                    click.echo("Steps:")
                    for step in steps:
                        deps = ", ".join(step.get("depends_on", [])) or "none"
                        click.echo(f"  {step['id']} <- {deps}")
                else:
                    click.echo("Steps: None")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@graph.command("run")
@click.argument("file")
@click.option("--server", "-s", "server_name", required=True, help="Server name to run the graph on")
@click.option("--dry-run", "-d", is_flag=True, help="Show execution order without running")
def graph_run(file: str, server_name: str, dry_run: bool):
    """Run a graph definition file on the server.

    The file should define a `graph` dict or Graph object with steps.
    Nodes are created automatically if needed.

    **Examples:**

        nerve server graph run workflow.py --server myproject

        nerve server graph run workflow.py --server myproject --dry-run
    """
    from nerve.frontends.cli.server.repl import run_graph_file

    socket = f"/tmp/nerve-{server_name}.sock"
    asyncio.run(run_graph_file(file, socket_path=socket, dry_run=dry_run))


@server.command("repl")
@click.argument("name")
def server_repl_cmd(name: str):
    """Interactive REPL connected to the server.

    Unlike the standalone `nerve repl`, this REPL connects to a running
    nerve server and operates on server-managed nodes.

    **Examples:**

        nerve server repl myproject
    """
    from nerve.frontends.cli.server.repl import run_server_repl

    socket = f"/tmp/nerve-{name}.sock"
    asyncio.run(run_server_repl(socket_path=socket))
