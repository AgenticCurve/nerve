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

    asyncio.run(cli_async())


async def cli_async() -> None:
    """Async CLI runner."""
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

    @click.group()
    @click.version_option(package_name="nerve")
    def cli():
        """Nerve - Programmatic control for AI CLI agents."""
        pass

    @cli.command()
    @click.option("--socket", default="/tmp/nerve.sock", help="Socket path")
    @click.option("--host", default=None, help="HTTP host (enables HTTP transport)")
    @click.option("--port", default=8080, help="HTTP port")
    def start(socket: str, host: str | None, port: int):
        """Start the nerve daemon."""
        click.echo("Starting nerve daemon...")

        from nerve.server import NerveEngine

        if host:
            from nerve.transport import HTTPServer

            transport = HTTPServer(host=host, port=port)
            click.echo(f"Listening on http://{host}:{port}")
        else:
            from nerve.transport import UnixSocketServer

            transport = UnixSocketServer(socket)
            click.echo(f"Listening on {socket}")

        engine = NerveEngine(event_sink=transport)

        async def run():
            await transport.serve(engine)

        asyncio.run(run())

    @cli.command()
    @click.option("--socket", default="/tmp/nerve.sock", help="Socket path")
    def stop(socket: str):
        """Stop the nerve daemon."""
        click.echo("Stopping nerve daemon...")
        # TODO: Send shutdown command
        click.echo("Done.")

    @cli.group()
    def session():
        """Manage sessions."""
        pass

    @session.command("create")
    @click.option("--type", "cli_type", default="claude", help="CLI type")
    @click.option("--cwd", default=None, help="Working directory")
    @click.option("--socket", default="/tmp/nerve.sock", help="Socket path")
    def session_create(cli_type: str, cwd: str | None, socket: str):
        """Create a new session."""
        from nerve.server.protocols import Command, CommandType
        from nerve.transport import UnixSocketClient

        async def run():
            client = UnixSocketClient(socket)
            await client.connect()

            result = await client.send_command(
                Command(
                    type=CommandType.CREATE_SESSION,
                    params={"cli_type": cli_type, "cwd": cwd},
                )
            )

            if result.success:
                click.echo(f"Created session: {result.data['session_id']}")
            else:
                click.echo(f"Error: {result.error}", err=True)

            await client.disconnect()

        asyncio.run(run())

    @session.command("list")
    @click.option("--socket", default="/tmp/nerve.sock", help="Socket path")
    def session_list(socket: str):
        """List sessions."""
        from nerve.server.protocols import Command, CommandType
        from nerve.transport import UnixSocketClient

        async def run():
            client = UnixSocketClient(socket)
            await client.connect()

            result = await client.send_command(
                Command(
                    type=CommandType.LIST_SESSIONS,
                    params={},
                )
            )

            if result.success:
                for sid in result.data.get("sessions", []):
                    click.echo(sid)
            else:
                click.echo(f"Error: {result.error}", err=True)

            await client.disconnect()

        asyncio.run(run())

    @cli.command()
    @click.argument("session_id")
    @click.argument("text")
    @click.option("--socket", default="/tmp/nerve.sock", help="Socket path")
    @click.option("--stream", is_flag=True, help="Stream output")
    def send(session_id: str, text: str, socket: str, stream: bool):
        """Send input to a session."""
        from nerve.server.protocols import Command, CommandType
        from nerve.transport import UnixSocketClient

        async def run():
            client = UnixSocketClient(socket)
            await client.connect()

            if stream:
                # Subscribe to events first
                async def print_events():
                    async for event in client.events():
                        if event.session_id == session_id:
                            if event.type.name == "OUTPUT_CHUNK":
                                click.echo(event.data.get("chunk", ""), nl=False)

                event_task = asyncio.create_task(print_events())

            result = await client.send_command(
                Command(
                    type=CommandType.SEND_INPUT,
                    params={
                        "session_id": session_id,
                        "text": text,
                        "stream": stream,
                    },
                )
            )

            if stream:
                await asyncio.sleep(0.5)  # Let events flush
                event_task.cancel()
                click.echo()  # Newline

            if not result.success:
                click.echo(f"Error: {result.error}", err=True)

            await client.disconnect()

        asyncio.run(run())

    @cli.command()
    @click.argument("file", required=False)
    @click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
    @click.option("--raw", "-r", is_flag=True, help="Show only raw response")
    @click.option("--last", "-l", is_flag=True, help="Show only the last section")
    @click.option("--full", "-F", is_flag=True, help="Show full content")
    @click.option("--type", "-t", "cli_type", default="claude", help="CLI type")
    def extract(
        file: str | None,
        json_output: bool,
        raw: bool,
        last: bool,
        full: bool,
        cli_type: str,
    ):
        """Extract structured response from AI CLI output."""
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
    @click.option("--dry-run", "-d", is_flag=True, help="Show execution order")
    def repl(file: str | None, dry_run: bool):
        """Interactive DAG definition and execution."""
        from nerve.frontends.cli.repl import run_from_file, run_interactive

        if file:
            asyncio.run(run_from_file(file, dry_run=dry_run))
        else:
            asyncio.run(run_interactive())

    cli()


# Allow running with: python -m nerve.frontends.cli.main
if __name__ == "__main__":
    main()
