"""CLI entry point."""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    """Main entry point for the CLI."""
    import importlib.util

    if importlib.util.find_spec("rich_click") is None:
        print("CLI dependencies not installed. Run: pip install nerve[cli]")
        sys.exit(1)

    _run_cli()


def _run_cli() -> None:
    """CLI definition and runner."""
    import rich_click as click

    # Configure rich-click styling
    click.rich_click.USE_RICH_MARKUP = True
    click.rich_click.USE_MARKDOWN = True
    click.rich_click.SHOW_ARGUMENTS = True
    click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
    click.rich_click.STYLE_ERRORS_SUGGESTION = "magenta italic"
    click.rich_click.ERRORS_SUGGESTION = "Try running '--help' for more information."
    click.rich_click.ERRORS_EPILOGUE = ""
    click.rich_click.MAX_WIDTH = 100

    # =========================================================================
    # Root CLI
    # =========================================================================
    @click.group()
    @click.version_option(package_name="nerve")
    def cli():
        """Nerve - Programmatic control for AI CLI agents.

        Nerve provides tools for controlling AI CLI tools like Claude Code
        and Gemini CLI programmatically.

        **Standalone commands** (no server required):

            nerve extract    Parse AI CLI output into structured sections

            nerve repl       Interactive graph definition and execution

            nerve wezterm    Manage WezTerm panes directly

        **Server commands** (require running daemon):

            nerve server     Start/stop daemon and manage nodes
        """
        pass

    # =========================================================================
    # Import and register command groups
    # =========================================================================

    # Server commands (server start/stop/status, node/*, graph/*)
    from nerve.frontends.cli.server import server

    cli.add_command(server)

    # WezTerm standalone commands
    from nerve.frontends.cli.wezterm import wezterm

    cli.add_command(wezterm)

    # =========================================================================
    # Standalone commands
    # =========================================================================
    @cli.command()
    @click.argument("file", required=False)
    @click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
    @click.option("--raw", "-r", is_flag=True, help="Show only raw response")
    @click.option("--last", "-l", is_flag=True, help="Show only the last section")
    @click.option("--full", "-F", is_flag=True, help="Show full content without truncation")
    @click.option("--type", "-t", "cli_type", default="claude", help="CLI type (claude, gemini)")
    def extract(
        file: str | None,
        json_output: bool,
        raw: bool,
        last: bool,
        full: bool,
        cli_type: str,
    ):
        """Extract structured response from AI CLI output.

        Parse Claude Code or Gemini CLI output into structured sections
        (thinking, tool calls, text). Works standalone without a server.

        **Examples:**

            nerve extract output.txt

            nerve extract output.txt --json

            cat output.txt | nerve extract

            nerve extract --last output.txt
        """
        from nerve.frontends.cli.extract import main as extract_main

        args = []
        if file:
            args.append(file)
        if json_output:
            args.append("--json")
        if raw:
            args.append("--raw")
        if last:
            args.append("--last")
        if full:
            args.append("--full")
        if cli_type != "claude":
            args.extend(["--type", cli_type])

        sys.exit(extract_main(args))

    @cli.command()
    @click.argument("file", required=False)
    @click.option("--dry-run", "-d", is_flag=True, help="Show execution order without running")
    def repl(file: str | None, dry_run: bool):
        """Interactive graph definition and execution.

        A REPL for defining and running graphs (node execution pipelines)
        of AI CLI tasks. Works standalone without a server.

        **Examples:**

            nerve repl

            nerve repl script.py

            nerve repl script.py --dry-run
        """
        from nerve.frontends.cli.repl import run_from_file, run_interactive

        if file:
            asyncio.run(run_from_file(file, dry_run=dry_run))
        else:
            asyncio.run(run_interactive())

    cli()


if __name__ == "__main__":
    main()
