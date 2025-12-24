"""Session subcommands for server."""

from __future__ import annotations

import asyncio
import sys

import rich_click as click

from nerve.frontends.cli.server import server
from nerve.frontends.cli.utils import create_client


@server.group()
def session():
    """Manage sessions (workspaces).

    Sessions are isolated workspaces that contain nodes and graphs.
    Each server has a default session, and you can create additional
    sessions for different projects or workflows.

    **Commands:**

        nerve server session list      List sessions

        nerve server session create    Create a new session

        nerve server session delete    Delete a session

        nerve server session info      Get session details
    """
    pass


@session.command("list")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
def session_list(server_name: str, json_output: bool):
    """List all sessions on a server.

    **Examples:**

        nerve server session list --server myproject

        nerve server session list --server myproject --json
    """
    from nerve.server.protocols import Command, CommandType

    async def run():
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        result = await client.send_command(
            Command(
                type=CommandType.LIST_SESSIONS,
                params={},
            )
        )

        if result.success:
            sessions = result.data.get("sessions", [])

            if json_output:
                import json

                click.echo(json.dumps(result.data, indent=2))
            elif sessions:
                click.echo(f"{'NAME':<20} {'NODES':<8} {'GRAPHS':<8} {'DEFAULT'}")
                click.echo("-" * 60)
                for s in sessions:
                    default_marker = "*" if s.get("is_default") else ""
                    click.echo(
                        f"{s['name'][:20]:<20} "
                        f"{s.get('node_count', 0):<8} {s.get('graph_count', 0):<8} "
                        f"{default_marker}"
                    )
            else:
                click.echo("No sessions found")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@session.command("create")
@click.argument("name")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
@click.option("--description", "-d", default="", help="Session description")
@click.option("--tags", "-t", multiple=True, help="Session tags")
def session_create(name: str, server_name: str, description: str, tags: tuple):
    """Create a new session.

    NAME is required and serves as the unique session identifier.

    **Examples:**

        nerve server session create my-workspace --server myproject

        nerve server session create dev --server myproject -d "Development" -t dev -t testing
    """
    from nerve.server.protocols import Command, CommandType

    async def run():
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        params = {"name": name}
        if description:
            params["description"] = description
        if tags:
            params["tags"] = list(tags)

        result = await client.send_command(
            Command(
                type=CommandType.CREATE_SESSION,
                params=params,
            )
        )

        if result.success:
            session_name = result.data.get("name")
            click.echo(f"Created session: {session_name}")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@session.command("delete")
@click.argument("session_id")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
def session_delete(session_id: str, server_name: str):
    """Delete a session.

    Stops all nodes in the session and removes it.
    Cannot delete the default session.

    **Arguments:**

        SESSION_ID    The session to delete

    **Examples:**

        nerve server session delete my-workspace --server myproject
    """
    from nerve.server.protocols import Command, CommandType

    async def run():
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        result = await client.send_command(
            Command(
                type=CommandType.DELETE_SESSION,
                params={"session_id": session_id},
            )
        )

        if result.success:
            click.echo(f"Deleted session: {session_id}")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@session.command("info")
@click.argument("session_id", required=False)
@click.option("--server", "-s", "server_name", required=True, help="Server name")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
def session_info(session_id: str | None, server_name: str, json_output: bool):
    """Get session info.

    If SESSION_ID is not provided, shows info for the default session.

    **Examples:**

        nerve server session info --server myproject

        nerve server session info my-workspace --server myproject
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
                type=CommandType.GET_SESSION,
                params=params,
            )
        )

        if result.success:
            if json_output:
                import json

                click.echo(json.dumps(result.data, indent=2))
            else:
                data = result.data
                click.echo(f"Session: {data.get('name', data.get('session_id'))}")
                click.echo(f"  ID: {data.get('session_id')}")
                if data.get("description"):
                    click.echo(f"  Description: {data.get('description')}")
                if data.get("tags"):
                    click.echo(f"  Tags: {', '.join(data.get('tags', []))}")
                click.echo(f"  Default: {'Yes' if data.get('is_default') else 'No'}")
                click.echo(f"  Nodes: {len(data.get('nodes_info', []))}")
                click.echo(f"  Graphs: {len(data.get('graphs', []))}")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())


@session.command("switch")
@click.argument("session_id")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
def session_switch(session_id: str, server_name: str):
    """Switch active session (for REPL use).

    Verifies the session exists and displays its info.
    Use this session ID with --session on node/graph commands.

    **Arguments:**

        SESSION_ID    The session to switch to

    **Examples:**

        nerve server session switch my-workspace --server myproject
    """
    from nerve.server.protocols import Command, CommandType

    async def run():
        try:
            client = create_client(server_name)
            await client.connect()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo(f"Error: Server '{server_name}' not running", err=True)
            sys.exit(1)

        result = await client.send_command(
            Command(
                type=CommandType.GET_SESSION,
                params={"session_id": session_id},
            )
        )

        if result.success:
            data = result.data
            click.echo(f"Switched to session: {data.get('name', session_id)}")
            click.echo(f"  ID: {data.get('session_id')}")
            click.echo(f"  Nodes: {len(data.get('nodes', []))}")
            click.echo(f"  Graphs: {len(data.get('graphs', []))}")
            click.echo("")
            click.echo("Use --session flag on node/graph commands to operate in this session.")
        else:
            click.echo(f"Error: {result.error}", err=True)

        await client.disconnect()

    asyncio.run(run())
