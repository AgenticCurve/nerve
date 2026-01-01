"""Workflow subcommands for server."""

from __future__ import annotations

import glob
from pathlib import Path

import rich_click as click

from nerve.frontends.cli.output import error_exit, output_json_or_table, print_table
from nerve.frontends.cli.server import server
from nerve.frontends.cli.utils import async_server_command, build_params, server_connection


@server.group()
def workflow() -> None:
    """Manage workflows.

    Workflows are async Python functions that orchestrate nodes with control flow
    (loops, conditionals, gates). They are registered with a Session and can be
    executed from Commander.

    **Commands:**

        nerve server workflow list     List registered workflows

        nerve server workflow load     Load workflow(s) from Python file(s)

    **Usage in Commander:**

        %workflow_id input            Execute a workflow
        :workflows                    List workflows
        :load file.py                 Load workflows from file
    """
    pass


@workflow.command("list")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
@async_server_command
async def workflow_list(server_name: str, session_id: str | None, json_output: bool) -> None:
    """List registered workflows in a session.

    Shows workflows in the specified session (or default session).

    **Examples:**

        nerve server workflow list

        nerve server workflow list --server myproject

        nerve server workflow list --session my-workspace

        nerve server workflow list --json
    """
    from nerve.server.protocols import Command, CommandType

    async with server_connection(server_name) as client:
        params = build_params(session_id=session_id)

        result = await client.send_command(
            Command(
                type=CommandType.LIST_WORKFLOWS,
                params=params,
            )
        )

        if result.success and result.data:
            workflows = result.data.get("workflows", [])

            def show_table() -> None:
                if workflows:
                    rows = []
                    for wf in workflows:
                        wf_id = wf.get("id", "?")
                        desc = wf.get("description", "")
                        if desc and len(desc) > 40:
                            desc = desc[:37] + "..."
                        rows.append([wf_id, desc])
                    print_table(
                        ["ID", "DESCRIPTION"],
                        rows,
                        widths=[25, 50],
                    )
                else:
                    click.echo("No workflows registered")

            output_json_or_table(workflows, json_output, show_table)
        else:
            error_exit(f"Failed to list workflows: {result.error}")


@workflow.command("load")
@click.argument("files", nargs=-1, required=True)
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option("--session", "session_id", default=None, help="Session ID (default: default session)")
@async_server_command
async def workflow_load(files: tuple[str, ...], server_name: str, session_id: str | None) -> None:
    """Load workflow(s) from Python file(s).

    The file should define workflow functions and register them using
    the Workflow class. The `session` variable is available in scope.

    Supports glob patterns like '*.py' or 'workflows/*.py'.

    **Example workflow file:**

        from nerve.core.workflow import Workflow, WorkflowContext

        async def my_workflow(ctx: WorkflowContext) -> str:
            result = await ctx.run("my-node", ctx.input)
            return result["output"]

        Workflow(id="my-workflow", session=session, fn=my_workflow)

    **Examples:**

        nerve server workflow load workflow.py

        nerve server workflow load workflows/*.py

        nerve server workflow load file1.py file2.py

        nerve server workflow load workflow.py --session my-workspace
    """
    from nerve.server.protocols import Command, CommandType

    # Expand glob patterns and collect all files
    files_to_load: list[Path] = []

    for pattern in files:
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
            if path.is_file() and path.suffix == ".py":
                files_to_load.append(path)
            elif path.is_file():
                click.echo(f"Warning: Skipping non-Python file: {pattern}", err=True)
            else:
                click.echo(f"Warning: File not found: {pattern}", err=True)

    if not files_to_load:
        error_exit("No Python files found to load")

    async with server_connection(server_name) as client:
        loaded_count = 0
        error_count = 0

        for file_path in files_to_load:
            try:
                code = file_path.read_text()
                params = build_params(session_id=session_id, code=code)

                result = await client.send_command(
                    Command(
                        type=CommandType.EXECUTE_PYTHON,
                        params=params,
                    )
                )

                if result.success:
                    error_msg = result.data.get("error") if result.data else None
                    if error_msg:
                        click.echo(f"Error loading {file_path.name}: {error_msg}", err=True)
                        error_count += 1
                    else:
                        click.echo(f"Loaded {file_path.name}")
                        output = result.data.get("output", "") if result.data else ""
                        if output and output.strip():
                            click.echo(f"  {output.strip()}")
                        loaded_count += 1
                else:
                    click.echo(f"Error loading {file_path.name}: {result.error}", err=True)
                    error_count += 1

            except Exception as e:
                click.echo(f"Failed to load {file_path.name}: {e}", err=True)
                error_count += 1

        # Summary
        if loaded_count > 0:
            click.echo(f"Loaded {loaded_count} file(s)")
        if error_count > 0:
            click.echo(f"Failed to load {error_count} file(s)", err=True)
