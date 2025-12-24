"""WezTerm commands - manage WezTerm panes directly."""

from __future__ import annotations

import asyncio
import subprocess
import sys

import rich_click as click


@click.group()
def wezterm() -> None:
    """Manage WezTerm panes directly.

    Control AI CLI nodes running in WezTerm panes without needing
    the nerve server. Useful for visual debugging and interactive use.

    **Commands:**

        nerve wezterm list     List all WezTerm panes

        nerve wezterm spawn    Create new pane with AI CLI

        nerve wezterm send     Send text to a pane

        nerve wezterm read     Read content from a pane

        nerve wezterm kill     Kill a pane
    """
    pass


@wezterm.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
def wezterm_list(json_output: bool) -> None:
    """List all WezTerm panes.

    Shows all panes in WezTerm with their IDs, titles, and working directories.

    **Examples:**

        nerve wezterm list

        nerve wezterm list --json
    """
    from nerve.core.pty.wezterm_backend import is_wezterm_available, list_wezterm_panes

    if not is_wezterm_available():
        click.echo("WezTerm is not running or wezterm CLI is not available.", err=True)
        sys.exit(1)

    panes = list_wezterm_panes()

    if json_output:
        import json

        click.echo(json.dumps(panes, indent=2))
    else:
        if not panes:
            click.echo("No WezTerm panes found")
            return

        click.echo(f"{'PANE ID':<10} {'TAB':<6} {'CWD':<40} {'TITLE'}")
        click.echo("-" * 80)
        for pane in panes:
            pane_id = pane.get("pane_id", "?")
            tab_id = pane.get("tab_id", "?")
            cwd = pane.get("cwd", "")[:38]
            title = pane.get("title", "")[:30]
            click.echo(f"{pane_id:<10} {tab_id:<6} {cwd:<40} {title}")


@wezterm.command("spawn")
@click.option(
    "--command", "-c", "cmd", default="claude", help="Command to run (e.g., claude, gemini)"
)
@click.option("--cwd", default=None, help="Working directory")
@click.option("--name", "-n", default=None, help="Node name for reference")
def wezterm_spawn(cmd: str, cwd: str | None, name: str | None) -> None:
    """Spawn a new CLI node in a WezTerm pane.

    Creates a new pane in WezTerm running the specified command.
    Returns the pane ID which can be used with other commands.

    **Examples:**

        nerve wezterm spawn

        nerve wezterm spawn --command gemini

        nerve wezterm spawn --command "my-cli --flag"

        nerve wezterm spawn --cwd /path/to/project
    """
    from nerve.core.pty import BackendConfig
    from nerve.core.pty.wezterm_backend import WezTermBackend

    command = cmd.split() if " " in cmd else [cmd]
    config = BackendConfig(cwd=cwd)

    async def run() -> str | None:
        backend = WezTermBackend(command, config)
        # start() will auto-launch WezTerm if not running
        await backend.start()
        return backend.pane_id

    try:
        pane_id = asyncio.run(run())
        click.echo(f"Created pane: {pane_id}")
        if name:
            click.echo(f"Name: {name}")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@wezterm.command("send")
@click.argument("pane_id")
@click.argument("text")
def wezterm_send(pane_id: str, text: str) -> None:
    """Send text to a WezTerm pane.

    **Arguments:**

        PANE_ID    The WezTerm pane ID

        TEXT       The text to send

    **Examples:**

        nerve wezterm send 0 "Hello!"

        nerve wezterm send 0 "Explain this code"
    """
    result = subprocess.run(
        ["wezterm", "cli", "send-text", "--pane-id", pane_id, "--no-paste", text + "\n"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        click.echo(f"Error: {result.stderr}", err=True)
        sys.exit(1)

    click.echo(f"Sent to pane {pane_id}")


@wezterm.command("read")
@click.argument("pane_id")
@click.option("--lines", "-n", default=None, type=int, help="Number of lines from end")
@click.option("--full", "-f", is_flag=True, help="Include scrollback")
def wezterm_read(pane_id: str, lines: int | None, full: bool) -> None:
    """Read content from a WezTerm pane.

    **Arguments:**

        PANE_ID    The WezTerm pane ID

    **Examples:**

        nerve wezterm read 0

        nerve wezterm read 0 --lines 50

        nerve wezterm read 0 --full
    """
    cmd = ["wezterm", "cli", "get-text", "--pane-id", pane_id]

    if full:
        cmd.extend(["--start-line", "-1000"])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        click.echo(f"Error: {result.stderr}", err=True)
        sys.exit(1)

    content = result.stdout
    if lines:
        content = "\n".join(content.split("\n")[-lines:])

    click.echo(content)


@wezterm.command("kill")
@click.argument("pane_id")
def wezterm_kill(pane_id: str) -> None:
    """Kill a WezTerm pane.

    **Arguments:**

        PANE_ID    The WezTerm pane ID to kill

    **Examples:**

        nerve wezterm kill 0
    """
    result = subprocess.run(
        ["wezterm", "cli", "kill-pane", "--pane-id", pane_id],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        click.echo(f"Error: {result.stderr}", err=True)
        sys.exit(1)

    click.echo(f"Killed pane {pane_id}")
