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
    def cli() -> None:
        """Nerve - Programmatic control for AI CLI agents.

        Nerve provides tools for controlling AI CLI tools like Claude Code
        and Gemini CLI programmatically.

        **Standalone commands** (no server required):

            nerve parse      Parse AI CLI pane output into structured sections

            nerve repl       Interactive graph definition and execution

            nerve wezterm    Manage WezTerm panes directly

        **Server commands** (require running daemon):

            nerve server     Start/stop daemon and manage nodes
        """
        pass

    # =========================================================================
    # Import and register command groups
    # =========================================================================

    # Server commands (server start/stop/status, node/*, graph/*, workflow/*)
    # Import subcommands to register them with the server group
    from nerve.frontends.cli.server import graph, node, server, session, workflow  # noqa: F401

    cli.add_command(server)

    # WezTerm standalone commands
    from nerve.frontends.cli.wezterm import wezterm

    cli.add_command(wezterm)

    # =========================================================================
    # Standalone commands
    # =========================================================================
    @cli.command()
    @click.argument("file", required=False)
    @click.option(
        "--claude-code", "-c", "claude_code", is_flag=True, help="Parse Claude Code CLI pane output"
    )
    @click.option("--gemini", "-g", "gemini", is_flag=True, help="Parse Gemini CLI pane output")
    @click.option("--pane", "-p", "pane_id", help="WezTerm pane ID to parse from")
    @click.option("--list-panes", "-P", is_flag=True, help="List available WezTerm panes")
    @click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
    @click.option("--raw", "-r", is_flag=True, help="Show only raw response")
    @click.option("--last", "-l", is_flag=True, help="Show only the last section")
    @click.option("--full", "-F", is_flag=True, help="Show full content without truncation")
    def parse(
        file: str | None,
        claude_code: bool,
        gemini: bool,
        pane_id: str | None,
        list_panes: bool,
        json_output: bool,
        raw: bool,
        last: bool,
        full: bool,
    ) -> None:
        """Parse AI CLI pane output into structured sections.

        Parse Claude Code or Gemini CLI pane output into structured sections
        (thinking, tool calls, text). Works standalone without a server.

        **Examples:**

            nerve parse --claude-code pane.txt

            nerve parse --claude-code --json pane.txt

            cat pane.txt | nerve parse --claude-code

            nerve parse --claude-code --last pane.txt

            nerve parse --claude-code --pane 42

            nerve parse --list-panes
        """
        from nerve.frontends.cli.parse import main as parse_main

        args = []
        if file:
            args.append(file)
        if claude_code:
            args.append("--claude-code")
        if gemini:
            args.append("--gemini")
        if pane_id:
            args.extend(["--pane", pane_id])
        if list_panes:
            args.append("--list-panes")
        if json_output:
            args.append("--json")
        if raw:
            args.append("--raw")
        if last:
            args.append("--last")
        if full:
            args.append("--full")

        sys.exit(parse_main(args))

    @cli.command()
    @click.argument("file", required=False)
    @click.option("--dry-run", "-d", is_flag=True, help="Show execution order without running")
    @click.option(
        "--server",
        "-s",
        "server_name",
        default=None,
        help="Connect to server (default: local mode)",
    )
    @click.option(
        "--session",
        "session_name",
        default=None,
        help="Session to connect to (default: server's default session)",
    )
    def repl(
        file: str | None, dry_run: bool, server_name: str | None, session_name: str | None
    ) -> None:
        """Interactive graph definition and execution.

        A REPL for defining and running graphs (node execution pipelines)
        of AI CLI tasks.

        **Local mode** (default - no server):
            Creates in-memory session with full Python REPL

        **Server mode** (--server):
            Connects to running server, command-based only

        **Examples:**

            nerve repl                              # Local mode
            nerve repl --server local               # Connect to server (default session)
            nerve repl --server local --session my-project  # Connect to specific session
            nerve repl script.py                    # Load from file (local)
            nerve repl script.py --dry-run
        """
        from nerve.frontends.cli.repl import run_from_file, run_interactive

        if file:
            if server_name:
                print("Error: File mode not supported with --server")
                print("Use interactive mode or remove --server flag")
                sys.exit(1)
            asyncio.run(run_from_file(file, dry_run=dry_run))
        else:
            if session_name and not server_name:
                print("Error: --session requires --server")
                print("Use --server to specify which server to connect to")
                sys.exit(1)
            asyncio.run(run_interactive(server_name=server_name, session_name=session_name))

    @cli.command()
    @click.option(
        "--server",
        "-s",
        "server_name",
        default="local",
        help="Server to connect to (default: local)",
    )
    @click.option(
        "--session",
        "session_name",
        default="default",
        help="Session to use (default: default)",
    )
    @click.option(
        "--theme",
        "-t",
        default="default",
        type=click.Choice(["default", "nord", "dracula", "mono"]),
        help="Color theme (default: default)",
    )
    @click.option(
        "--bottom-gutter",
        "-g",
        default=3,
        type=int,
        help="Lines of space between prompt and screen bottom (default: 3)",
    )
    @click.option(
        "--config",
        "-c",
        type=click.Path(exists=True),
        help="Workspace config file (.py) to load at startup",
    )
    def commander(
        server_name: str, session_name: str, theme: str, bottom_gutter: int, config: str | None
    ) -> None:
        """Interactive command center for nodes.

        A block-based timeline interface for interacting with nodes.
        Each interaction is displayed as a discrete block with input/output.

        **Commands:**

            @node message     Send message to a node
            >>> code          Execute Python code
            Ctrl+C            Interrupt running command
            :nodes            List available nodes
            :timeline         Show session timeline
            :world node       Show node's history/state
            :theme name       Switch theme
            :exit             Exit

        **Examples:**

            nerve commander                    # Default theme
            nerve commander --theme nord       # Nord color scheme
            nerve commander -t dracula         # Dracula theme
            nerve commander -g 5               # More bottom padding
            nerve commander -c workspace.py    # Load workspace config
        """
        from nerve.frontends.tui.commander import run_commander

        asyncio.run(
            run_commander(
                server_name=server_name,
                session_name=session_name,
                theme=theme,
                bottom_gutter=bottom_gutter,
                config_path=config,
            )
        )

    cli()


if __name__ == "__main__":
    main()
