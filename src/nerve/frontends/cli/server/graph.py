"""Graph subcommands and server REPL for server."""

from __future__ import annotations

import asyncio

import rich_click as click

from nerve.frontends.cli.server import server


@server.group()
def graph():
    """Execute graphs on the server.

    Run graph definition files on the server, using server-managed nodes.

    **Commands:**

        nerve server graph run       Run a graph file
    """
    pass


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
