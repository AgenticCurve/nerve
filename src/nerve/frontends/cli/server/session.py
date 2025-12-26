"""Session subcommands for server."""

from __future__ import annotations

import asyncio

import rich_click as click

from nerve.frontends.cli.output import output_json_or_table, print_table
from nerve.frontends.cli.server import server
from nerve.frontends.cli.utils import server_connection


@server.group()
def session() -> None:
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
def session_list(server_name: str, json_output: bool) -> None:
    """List all sessions on a server.

    **Examples:**

        nerve server session list --server myproject

        nerve server session list --server myproject --json
    """
    from nerve.server.protocols import Command, CommandType

    async def run() -> None:
        async with server_connection(server_name) as client:
            result = await client.send_command(
                Command(
                    type=CommandType.LIST_SESSIONS,
                    params={},
                )
            )

            if result.success and result.data:
                sessions = result.data.get("sessions", [])

                def show_table() -> None:
                    if sessions:
                        rows = []
                        for s in sessions:
                            default_marker = "*" if s.get("is_default") else ""
                            rows.append(
                                [
                                    s["name"][:20],
                                    str(s.get("node_count", 0)),
                                    str(s.get("graph_count", 0)),
                                    default_marker,
                                ]
                            )
                        print_table(
                            ["NAME", "NODES", "GRAPHS", "DEFAULT"],
                            rows,
                            widths=[20, 8, 8, 7],
                            separator_width=60,
                        )
                    else:
                        click.echo("No sessions found")

                output_json_or_table(result.data, json_output, show_table)
            else:
                click.echo(f"Error: {result.error}", err=True)

    asyncio.run(run())


@session.command("create")
@click.argument("name")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
@click.option("--description", "-d", default="", help="Session description")
@click.option("--tags", "-t", multiple=True, help="Session tags")
def session_create(name: str, server_name: str, description: str, tags: tuple[str, ...]) -> None:
    """Create a new session.

    NAME is required and serves as the unique session identifier.

    **Examples:**

        nerve server session create my-workspace --server myproject

        nerve server session create dev --server myproject -d "Development" -t dev -t testing
    """
    from nerve.server.protocols import Command, CommandType

    async def run() -> None:
        async with server_connection(server_name) as client:
            params: dict[str, str | list[str]] = {"name": name}
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

            if result.success and result.data:
                session_name = result.data.get("name")
                click.echo(f"Created session: {session_name}")
            else:
                click.echo(f"Error: {result.error}", err=True)

    asyncio.run(run())


@session.command("delete")
@click.argument("session_id")
@click.option("--server", "-s", "server_name", required=True, help="Server name")
def session_delete(session_id: str, server_name: str) -> None:
    """Delete a session.

    Stops all nodes in the session and removes it.
    Cannot delete the default session.

    **Arguments:**

        SESSION_ID    The session to delete

    **Examples:**

        nerve server session delete my-workspace --server myproject
    """
    from nerve.server.protocols import Command, CommandType

    async def run() -> None:
        async with server_connection(server_name) as client:
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

    asyncio.run(run())


@session.command("info")
@click.argument("session_id", required=False)
@click.option("--server", "-s", "server_name", required=True, help="Server name")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
def session_info(session_id: str | None, server_name: str, json_output: bool) -> None:
    """Get session info.

    If SESSION_ID is not provided, shows info for the default session.

    **Examples:**

        nerve server session info --server myproject

        nerve server session info my-workspace --server myproject
    """
    from nerve.server.protocols import Command, CommandType

    async def run() -> None:
        async with server_connection(server_name) as client:
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
                data = result.data  # Capture for closure

                def show_info() -> None:
                    click.echo(f"Session: {data.get('name', data.get('session_id'))}")
                    click.echo(f"  ID: {data.get('session_id')}")
                    if data.get("description"):
                        click.echo(f"  Description: {data.get('description')}")
                    if data.get("tags"):
                        click.echo(f"  Tags: {', '.join(data.get('tags', []))}")
                    click.echo(f"  Default: {'Yes' if data.get('is_default') else 'No'}")
                    click.echo(f"  Nodes: {len(data.get('nodes_info', []))}")
                    click.echo(f"  Graphs: {len(data.get('graphs', []))}")

                output_json_or_table(data, json_output, show_info)
            else:
                click.echo(f"Error: {result.error}", err=True)

    asyncio.run(run())
