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

            nerve repl       Interactive DAG definition and execution

            nerve wezterm    Manage WezTerm panes directly

        **Server commands** (require running daemon):

            nerve server     Start/stop daemon and manage channels
        """
        pass

    # =========================================================================
    # Server command group
    # =========================================================================
    @cli.group()
    def server():
        """Server commands - manage the nerve daemon.

        The nerve daemon provides a persistent service for managing
        AI CLI channels over Unix socket or HTTP.

        **Lifecycle:**

            nerve server start     Start the daemon

            nerve server stop      Stop the daemon

            nerve server status    Check if daemon is running

        **Channel management:**

            nerve server channel   Create, list, and send to channels

        **DAG execution:**

            nerve server dag       Run DAGs on the server

        **Interactive:**

            nerve server repl      Server-connected REPL
        """
        pass

    @server.command()
    @click.argument("name")
    @click.option("--host", default=None, help="Host to bind (enables network transport)")
    @click.option("--port", default=8080, help="Port for network transport")
    @click.option("--tcp", "use_tcp", is_flag=True, help="Use TCP socket transport (requires --host)")
    @click.option("--http", "use_http", is_flag=True, help="Use HTTP transport (requires --host)")
    def start(name: str, host: str | None, port: int, use_tcp: bool, use_http: bool):
        """Start the nerve daemon.

        NAME is required and determines the socket path (/tmp/nerve-NAME.sock).
        Names must be lowercase alphanumeric with dashes, 1-32 characters.

        **Transports:**

            Unix socket (default): Local-only, fast IPC via /tmp/nerve-NAME.sock

            TCP socket (--tcp): Network-capable, same JSON-line protocol

            HTTP (--http): REST API + WebSocket for web clients

        **Examples:**

            nerve server start myproject

            nerve server start myproject --tcp --host 0.0.0.0 --port 8080

            nerve server start myproject --http --host 0.0.0.0 --port 8080
        """
        from nerve.core.validation import validate_name

        try:
            validate_name(name, "server")
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

        # Validate transport options
        if use_tcp and use_http:
            click.echo("Error: Cannot use both --tcp and --http", err=True)
            sys.exit(1)
        if (use_tcp or use_http) and not host:
            click.echo("Error: --tcp and --http require --host", err=True)
            sys.exit(1)

        socket_path = f"/tmp/nerve-{name}.sock"
        pid_file = f"/tmp/nerve-{name}.pid"
        http_file = f"/tmp/nerve-{name}.http"
        tcp_file = f"/tmp/nerve-{name}.tcp"
        click.echo(f"Starting nerve daemon '{name}'...")

        from nerve.server import NerveEngine

        # Determine transport type
        transport_type = "unix"  # default
        if use_http:
            transport_type = "http"
        elif use_tcp:
            transport_type = "tcp"
        elif host:
            # Legacy: --host without --tcp/--http defaults to HTTP for backwards compatibility
            transport_type = "http"

        if transport_type == "http":
            from nerve.transport import HTTPServer

            transport = HTTPServer(host=host, port=port)
            click.echo(f"Listening on http://{host}:{port}")
        elif transport_type == "tcp":
            from nerve.transport import TCPSocketServer

            transport = TCPSocketServer(host=host, port=port)
            click.echo(f"Listening on tcp://{host}:{port}")
        else:
            from nerve.transport import UnixSocketServer

            transport = UnixSocketServer(socket_path)
            click.echo(f"Listening on {socket_path}")

        engine = NerveEngine(event_sink=transport)

        # Create new process group so we can kill all children on force stop
        import os
        import signal as sig
        os.setpgrp()

        # Write PID file (PID == PGID since we're the group leader)
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))

        # Write transport tracking file
        if transport_type == "http":
            with open(http_file, "w") as f:
                f.write(f"{host}:{port}")
        elif transport_type == "tcp":
            with open(tcp_file, "w") as f:
                f.write(f"{host}:{port}")

        async def run():
            loop = asyncio.get_running_loop()
            shutdown_event = asyncio.Event()
            shutdown_count = [0]  # Use list for nonlocal in closure

            def handle_shutdown(sig_name: str):
                shutdown_count[0] += 1
                if shutdown_count[0] == 1:
                    click.echo(f"\nReceived {sig_name}, shutting down gracefully...")
                    click.echo("(Cleaning up channels, press Ctrl+C again to force quit)")
                    engine._shutdown_requested = True
                    shutdown_event.set()
                else:
                    click.echo("\nForce quitting...")
                    os._exit(1)  # Immediate exit

            # Use asyncio signal handlers for proper event loop integration
            loop.add_signal_handler(sig.SIGTERM, lambda: handle_shutdown("SIGTERM"))
            loop.add_signal_handler(sig.SIGINT, lambda: handle_shutdown("SIGINT"))

            try:
                await transport.serve(engine)
            finally:
                # Clean up all channels before exiting
                click.echo("Cleaning up channels...")
                await engine._channel_manager.close_all()
                click.echo("Cleanup complete.")
                # Clean up tracking files on exit
                if os.path.exists(pid_file):
                    os.unlink(pid_file)
                if transport_type == "http" and os.path.exists(http_file):
                    os.unlink(http_file)
                if transport_type == "tcp" and os.path.exists(tcp_file):
                    os.unlink(tcp_file)
                # Remove signal handlers
                loop.remove_signal_handler(sig.SIGTERM)
                loop.remove_signal_handler(sig.SIGINT)

        asyncio.run(run())

    @server.command()
    @click.argument("name", required=False)
    @click.option("--all", "stop_all", is_flag=True, help="Stop all nerve servers")
    @click.option("--force", "-f", is_flag=True, help="Force kill (SIGKILL) without graceful shutdown")
    @click.option("--timeout", "-t", default=5.0, help="Graceful shutdown timeout in seconds (default: 5)")
    def stop(name: str | None, stop_all: bool, force: bool, timeout: float):
        """Stop the nerve daemon.

        Sends a shutdown command to the running daemon, which will:
        - Close all active channels
        - Cancel all running DAGs
        - Cleanup and exit

        If graceful shutdown times out, automatically falls back to force kill.

        **Examples:**

            nerve server stop myproject

            nerve server stop myproject --force

            nerve server stop myproject --timeout 10

            nerve server stop --all
        """
        import os
        import signal
        from glob import glob

        from nerve.server.protocols import Command, CommandType
        from nerve.transport import UnixSocketClient

        if not name and not stop_all:
            click.echo("Error: Provide server NAME or use --all", err=True)
            sys.exit(1)

        def get_server_name_from_socket(sock_path: str) -> str:
            """Extract server name from socket path."""
            # /tmp/nerve-myproject.sock -> myproject
            import re
            match = re.match(r"/tmp/nerve-(.+)\.sock", sock_path)
            return match.group(1) if match else ""

        def get_server_name_from_http(http_path: str) -> str:
            """Extract server name from HTTP tracking file path."""
            # /tmp/nerve-myproject.http -> myproject
            import re
            match = re.match(r"/tmp/nerve-(.+)\.http", http_path)
            return match.group(1) if match else ""

        def get_server_name_from_tcp(tcp_path: str) -> str:
            """Extract server name from TCP tracking file path."""
            # /tmp/nerve-myproject.tcp -> myproject
            import re
            match = re.match(r"/tmp/nerve-(.+)\.tcp", tcp_path)
            return match.group(1) if match else ""

        def get_server_transport(server_name: str) -> tuple[str, str | None]:
            """Get server transport type. Returns (type, host:port or None).

            Types: "http", "tcp", "unix"
            """
            http_file = f"/tmp/nerve-{server_name}.http"
            tcp_file = f"/tmp/nerve-{server_name}.tcp"
            if os.path.exists(http_file):
                with open(http_file) as f:
                    return "http", f.read().strip()
            if os.path.exists(tcp_file):
                with open(tcp_file) as f:
                    return "tcp", f.read().strip()
            return "unix", None

        def get_descendants(pid: int) -> list[int]:
            """Get all descendant PIDs of a process (children, grandchildren, etc.)."""
            import subprocess
            descendants = []
            try:
                # Use pgrep to find direct children
                result = subprocess.run(
                    ["pgrep", "-P", str(pid)],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n"):
                        if line:
                            child_pid = int(line)
                            descendants.append(child_pid)
                            # Recursively get grandchildren
                            descendants.extend(get_descendants(child_pid))
            except Exception:
                pass
            return descendants

        def wait_for_process_exit(pid: int, timeout: float = 5.0) -> bool:
            """Wait for a process to exit. Returns True if exited, False if still running."""
            import time
            start = time.time()
            while time.time() - start < timeout:
                try:
                    os.kill(pid, 0)  # Check if process exists
                    time.sleep(0.1)
                except ProcessLookupError:
                    return True  # Process exited
            return False  # Still running after timeout

        def force_kill_server(server_name: str) -> bool:
            """Force kill a server and all its channel processes.

            For PTY channels: kills child processes directly.
            For WezTerm channels: sends SIGTERM first to let server clean up panes,
            then SIGKILL if needed.
            """
            pid_file = f"/tmp/nerve-{server_name}.pid"
            socket_file = f"/tmp/nerve-{server_name}.sock"
            http_file = f"/tmp/nerve-{server_name}.http"
            tcp_file = f"/tmp/nerve-{server_name}.tcp"

            if os.path.exists(pid_file):
                try:
                    with open(pid_file) as f:
                        server_pid = int(f.read().strip())

                    # First, send SIGTERM to let server clean up gracefully
                    # This is important for WezTerm panes which aren't child processes
                    try:
                        os.kill(server_pid, signal.SIGTERM)
                        # Wait for process to exit (allows channel cleanup)
                        if wait_for_process_exit(server_pid, timeout=5.0):
                            click.echo(f"  Server {server_pid} exited gracefully")
                            # Clean up files
                            for f in [pid_file, socket_file, http_file, tcp_file]:
                                if os.path.exists(f):
                                    os.unlink(f)
                            return True
                    except ProcessLookupError:
                        # Already dead
                        click.echo(f"  Server {server_pid} already stopped")
                        for f in [pid_file, socket_file, http_file, tcp_file]:
                            if os.path.exists(f):
                                os.unlink(f)
                        return True

                    # Server didn't exit from SIGTERM, need to force kill
                    click.echo(f"  Server didn't respond to SIGTERM, force killing...")

                    # Find all descendant processes (PTY channels)
                    descendants = get_descendants(server_pid)

                    # Kill descendants first (PTY channels), then the server
                    killed_count = 0
                    for child_pid in descendants:
                        try:
                            os.kill(child_pid, signal.SIGKILL)
                            killed_count += 1
                        except ProcessLookupError:
                            pass  # Already dead

                    # Force kill the server process
                    try:
                        os.kill(server_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # Already dead

                    if killed_count > 0:
                        click.echo(f"  Killed server {server_pid} and {killed_count} channel process(es)")
                    else:
                        click.echo(f"  Killed server {server_pid}")

                    # Clean up files
                    for f in [pid_file, socket_file, http_file, tcp_file]:
                        if os.path.exists(f):
                            os.unlink(f)
                    return True
                except (ValueError, ProcessLookupError, PermissionError) as e:
                    click.echo(f"  Could not kill process: {e}", err=True)
                    # Still try to clean up stale files
                    for f in [pid_file, socket_file, http_file, tcp_file]:
                        if os.path.exists(f):
                            os.unlink(f)
                    return False
            else:
                # No PID file, just clean up stale files
                cleaned = False
                for f in [socket_file, http_file, tcp_file]:
                    if os.path.exists(f):
                        os.unlink(f)
                        cleaned = True
                if cleaned:
                    click.echo(f"  Cleaned up stale files")
                return False

        async def graceful_stop_socket(sock_path: str, timeout_secs: float) -> bool:
            """Try graceful shutdown via Unix socket. Returns True if successful."""
            try:
                client = UnixSocketClient(sock_path)
                await client.connect()
                result = await client.send_command(
                    Command(type=CommandType.SHUTDOWN, params={}),
                    timeout=timeout_secs,
                )
                await client.disconnect()
                return result.success
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                return False
            except TimeoutError:
                return False

        async def graceful_stop_http(host_port: str, timeout_secs: float) -> bool:
            """Try graceful shutdown via HTTP. Returns True if successful."""
            try:
                import aiohttp
            except ImportError:
                click.echo("  Warning: aiohttp not installed, cannot gracefully stop HTTP server")
                return False

            url = f"http://{host_port}/api/shutdown"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, timeout=aiohttp.ClientTimeout(total=timeout_secs)) as response:
                        if response.status == 200:
                            data = await response.json()
                            return data.get("success", False)
                        return False
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                return False

        async def graceful_stop_tcp(host_port: str, timeout_secs: float) -> bool:
            """Try graceful shutdown via TCP socket. Returns True if successful."""
            from nerve.transport import TCPSocketClient

            host, port_str = host_port.split(":")
            port = int(port_str)
            try:
                client = TCPSocketClient(host, port)
                await client.connect()
                result = await client.send_command(
                    Command(type=CommandType.SHUTDOWN, params={}),
                    timeout=timeout_secs,
                )
                await client.disconnect()
                return result.success
            except (ConnectionRefusedError, OSError):
                return False
            except TimeoutError:
                return False

        async def stop_server(server_name: str, force_mode: bool, timeout_secs: float) -> bool:
            """Stop a server - gracefully first, then force if needed."""
            sock_path = f"/tmp/nerve-{server_name}.sock"
            transport_type, host_port = get_server_transport(server_name)

            if force_mode:
                click.echo(f"  Force stopping '{server_name}'...")
                return force_kill_server(server_name)

            # Try graceful shutdown first
            click.echo(f"  Stopping '{server_name}' ({transport_type}, timeout: {timeout_secs}s)...")

            if transport_type == "http" and host_port:
                graceful_success = await graceful_stop_http(host_port, timeout_secs)
            elif transport_type == "tcp" and host_port:
                graceful_success = await graceful_stop_tcp(host_port, timeout_secs)
            else:
                graceful_success = await graceful_stop_socket(sock_path, timeout_secs)

            if graceful_success:
                # Wait briefly for server to clean up files
                await asyncio.sleep(0.5)
                click.echo(f"  Gracefully stopped '{server_name}'")
                return True

            # Graceful failed, try force kill
            click.echo(f"  Graceful shutdown failed, force killing...")
            if force_kill_server(server_name):
                return True

            click.echo(f"  Could not stop '{server_name}'", err=True)
            return False

        async def run():
            if stop_all:
                # Find all nerve servers (socket, HTTP, and TCP)
                sockets = glob("/tmp/nerve-*.sock")
                http_files = glob("/tmp/nerve-*.http")
                tcp_files = glob("/tmp/nerve-*.tcp")

                # Collect unique server names
                server_names = set()
                for sock_path in sockets:
                    sname = get_server_name_from_socket(sock_path)
                    if sname:
                        server_names.add(sname)
                for http_path in http_files:
                    sname = get_server_name_from_http(http_path)
                    if sname:
                        server_names.add(sname)
                for tcp_path in tcp_files:
                    sname = get_server_name_from_tcp(tcp_path)
                    if sname:
                        server_names.add(sname)

                if not server_names:
                    click.echo("No nerve servers found")
                    return

                click.echo(f"Found {len(server_names)} server(s)")
                for server_name in sorted(server_names):
                    await stop_server(server_name, force, timeout)
            else:
                await stop_server(name, force, timeout)

        asyncio.run(run())

    @server.command()
    @click.argument("name", required=False)
    @click.option("--all", "show_all", is_flag=True, help="Show all nerve servers")
    def status(name: str | None, show_all: bool):
        """Check if the nerve daemon is running.

        **Examples:**

            nerve server status myproject

            nerve server status --all
        """
        import os
        import re
        from glob import glob

        from nerve.server.protocols import Command, CommandType
        from nerve.transport import UnixSocketClient

        if not name and not show_all:
            click.echo("Error: Provide server NAME or use --all", err=True)
            sys.exit(1)

        def get_server_name_from_socket(sock_path: str) -> str:
            """Extract server name from socket path."""
            match = re.match(r"/tmp/nerve-(.+)\.sock", sock_path)
            return match.group(1) if match else ""

        def get_server_name_from_http(http_path: str) -> str:
            """Extract server name from HTTP file path."""
            match = re.match(r"/tmp/nerve-(.+)\.http", http_path)
            return match.group(1) if match else ""

        def get_server_name_from_tcp(tcp_path: str) -> str:
            """Extract server name from TCP file path."""
            match = re.match(r"/tmp/nerve-(.+)\.tcp", tcp_path)
            return match.group(1) if match else ""

        def get_transport_info(server_name: str) -> tuple[str, str | None]:
            """Get transport type and host:port. Returns (type, info)."""
            http_file = f"/tmp/nerve-{server_name}.http"
            tcp_file = f"/tmp/nerve-{server_name}.tcp"
            if os.path.exists(http_file):
                with open(http_file) as f:
                    return "http", f.read().strip()
            if os.path.exists(tcp_file):
                with open(tcp_file) as f:
                    return "tcp", f.read().strip()
            return "unix", None

        async def get_socket_status(sock_path: str) -> dict | None:
            """Get status via Unix socket. Returns None if not running."""
            try:
                client = UnixSocketClient(sock_path)
                await client.connect()
                result = await client.send_command(Command(type=CommandType.PING, params={}))
                await client.disconnect()
                if result.success:
                    return result.data
                return None
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                return None

        async def get_http_status(host_port: str) -> dict | None:
            """Get status via HTTP PING command. Returns None if not running."""
            from nerve.transport import HTTPClient

            try:
                client = HTTPClient(f"http://{host_port}")
                await client.connect()
                result = await client.send_command(
                    Command(type=CommandType.PING, params={}),
                    timeout=5.0,
                )
                await client.disconnect()
                if result.success:
                    return result.data
                return None
            except (Exception, asyncio.TimeoutError):
                return None

        async def get_tcp_status(host_port: str) -> dict | None:
            """Get status via TCP socket PING command. Returns None if not running."""
            from nerve.transport import TCPSocketClient

            try:
                host, port_str = host_port.split(":")
                port = int(port_str)
                client = TCPSocketClient(host, port)
                await client.connect()
                result = await client.send_command(
                    Command(type=CommandType.PING, params={}),
                    timeout=5.0,
                )
                await client.disconnect()
                if result.success:
                    return result.data
                return None
            except (Exception, asyncio.TimeoutError):
                return None

        async def get_server_status(server_name: str) -> dict | None:
            """Get status of a server by name. Returns None if not running."""
            transport_type, host_port = get_transport_info(server_name)

            if transport_type == "http" and host_port:
                status = await get_http_status(host_port)
                if status:
                    return {"transport": f"http://{host_port}", **status}
            elif transport_type == "tcp" and host_port:
                status = await get_tcp_status(host_port)
                if status:
                    return {"transport": f"tcp://{host_port}", **status}
            else:
                sock_path = f"/tmp/nerve-{server_name}.sock"
                status = await get_socket_status(sock_path)
                if status:
                    return {"transport": sock_path, **status}
            return None

        async def run():
            if show_all:
                # Find all nerve servers (socket, HTTP, and TCP)
                sockets = glob("/tmp/nerve-*.sock")
                http_files = glob("/tmp/nerve-*.http")
                tcp_files = glob("/tmp/nerve-*.tcp")

                # Collect unique server names
                server_names = set()
                for sock_path in sockets:
                    sname = get_server_name_from_socket(sock_path)
                    if sname:
                        server_names.add(sname)
                for http_path in http_files:
                    sname = get_server_name_from_http(http_path)
                    if sname:
                        server_names.add(sname)
                for tcp_path in tcp_files:
                    sname = get_server_name_from_tcp(tcp_path)
                    if sname:
                        server_names.add(sname)

                if not server_names:
                    click.echo("No nerve servers found")
                    return

                running = []
                for server_name in sorted(server_names):
                    status_data = await get_server_status(server_name)
                    if status_data:
                        running.append({"name": server_name, **status_data})

                if not running:
                    click.echo("No nerve servers running")
                    click.echo(f"(Found {len(server_names)} server file(s), but none responding)")
                    return

                click.echo(f"{'NAME':<20} {'TRANSPORT':<30} {'CHANNELS':<10} {'DAGS'}")
                click.echo("-" * 70)
                for s in running:
                    click.echo(
                        f"{s['name']:<20} {s['transport']:<30} {s.get('channels', '?'):<10} {s.get('dags', '?')}"
                    )
            else:
                status_data = await get_server_status(name)
                if status_data:
                    click.echo(f"Server '{name}' running on {status_data['transport']}")
                    if 'channels' in status_data:
                        click.echo(f"  Channels: {status_data.get('channels', 0)}")
                        click.echo(f"  DAGs: {status_data.get('dags', 0)}")
                else:
                    click.echo(f"Server '{name}' not running")
                    sys.exit(1)

        asyncio.run(run())

    # =========================================================================
    # Helper for getting the right client for a server
    # =========================================================================
    def get_server_client(server_name: str):
        """Get the appropriate client factory for a server.

        Returns (client_factory, connection_info) tuple where:
        - client_factory: callable that takes connection_info and returns client
        - connection_info: argument to pass to factory

        Usage:
            ClientFactory, conn_info = get_server_client("myserver")
            client = ClientFactory(conn_info)
            await client.connect()
        """
        import os

        from nerve.transport import HTTPClient, TCPSocketClient, UnixSocketClient

        http_file = f"/tmp/nerve-{server_name}.http"
        tcp_file = f"/tmp/nerve-{server_name}.tcp"

        if os.path.exists(http_file):
            with open(http_file) as f:
                host_port = f.read().strip()
            return HTTPClient, f"http://{host_port}"
        elif os.path.exists(tcp_file):
            with open(tcp_file) as f:
                host_port = f.read().strip()
            host, port_str = host_port.split(":")
            # Return a factory that unpacks the tuple
            return lambda args: TCPSocketClient(args[0], args[1]), (host, int(port_str))
        else:
            socket_path = f"/tmp/nerve-{server_name}.sock"
            return UnixSocketClient, socket_path

    # =========================================================================
    # Channel subgroup (under server)
    # =========================================================================
    @server.group()
    def channel():
        """Manage AI CLI channels.

        Channels are connections to AI CLI tools (Claude, Gemini) running
        in the daemon. Each channel represents a terminal pane or other
        connection type.

        **Commands:**

            nerve server channel create    Create a new channel

            nerve server channel list      List active channels

            nerve server channel run       Start a program (fire and forget)

            nerve server channel read      Read the output buffer

            nerve server channel send      Send input and wait for response
        """
        pass

    @channel.command("create")
    @click.argument("name")
    @click.option("--server", "-s", "server_name", required=True, help="Server name to create the channel on")
    @click.option("--command", "-c", default=None, help="Command to run (e.g., 'claude' or 'my-cli --flag')")
    @click.option("--cwd", default=None, help="Working directory for the channel")
    @click.option(
        "--backend",
        "-b",
        type=click.Choice(["pty", "wezterm", "claude-wezterm"]),
        default="pty",
        help="Backend (pty, wezterm, or claude-wezterm)",
    )
    @click.option("--pane-id", default=None, help="Attach to existing WezTerm pane (wezterm backend only)")
    def channel_create(
        name: str,
        server_name: str,
        command: str | None,
        cwd: str | None,
        backend: str,
        pane_id: str | None,
    ):
        """Create a new AI CLI channel.

        NAME is the channel name (required, must be unique).
        Names must be lowercase alphanumeric with dashes, 1-32 characters.

        **Examples:**

            nerve server channel create my-claude --server myproject --command claude

            nerve server channel create gemini-1 --server myproject --command gemini

            nerve server channel create attached --server myproject --backend wezterm --pane-id 4
        """
        from nerve.core.validation import validate_name
        from nerve.server.protocols import Command, CommandType

        try:
            validate_name(name, "channel")
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

        ClientClass, connection_arg = get_server_client(server_name)

        async def run():
            try:
                client = ClientClass(connection_arg)
                await client.connect()
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                click.echo(f"Error: Server '{server_name}' not running", err=True)
                sys.exit(1)

            params = {
                "channel_id": name,
                "cwd": cwd,
                "backend": backend,
            }
            if command:
                params["command"] = command
            if pane_id:
                params["pane_id"] = pane_id

            result = await client.send_command(
                Command(
                    type=CommandType.CREATE_CHANNEL,
                    params=params,
                )
            )

            if result.success:
                click.echo(f"Created channel: {name}")
            else:
                click.echo(f"Error: {result.error}", err=True)

            await client.disconnect()

        asyncio.run(run())

    @channel.command("list")
    @click.option("--server", "-s", "server_name", required=True, help="Server name to list channels from")
    @click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
    def channel_list(server_name: str, json_output: bool):
        """List active channels on a server.

        **Examples:**

            nerve server channel list --server myproject

            nerve server channel list --server myproject --json
        """
        from nerve.server.protocols import Command, CommandType

        ClientClass, connection_arg = get_server_client(server_name)

        async def run():
            client = ClientClass(connection_arg)
            await client.connect()

            result = await client.send_command(
                Command(
                    type=CommandType.LIST_CHANNELS,
                    params={},
                )
            )

            if result.success:
                channels_info = result.data.get("channels_info", [])
                channels = result.data.get("channels", [])

                if json_output:
                    import json

                    click.echo(json.dumps(channels_info, indent=2))
                elif channels_info:
                    click.echo(f"{'ID':<12} {'COMMAND':<15} {'BACKEND':<10} {'STATE'}")
                    click.echo("-" * 50)
                    for info in channels_info:
                        cmd = (info.get("command") or "-")[:14]
                        click.echo(
                            f"{info['id']:<12} {cmd:<15} "
                            f"{info['backend']:<10} {info['state']}"
                        )
                elif channels:
                    # Fallback for older server
                    for cid in channels:
                        click.echo(cid)
                else:
                    click.echo("No active channels")
            else:
                click.echo(f"Error: {result.error}", err=True)

            await client.disconnect()

        asyncio.run(run())

    # =========================================================================
    # Run command (under channel) - fire and forget
    # =========================================================================
    @channel.command("run")
    @click.argument("channel_name")
    @click.argument("command")
    @click.option("--server", "-s", "server_name", required=True, help="Server name the channel is on")
    def channel_run(channel_name: str, command: str, server_name: str):
        """Start a program in a channel (fire and forget).

        Use this to launch programs that take over the terminal,
        like claude, python, vim, etc. This does NOT wait for the
        program to be ready - use 'send' to interact with it after.

        **Arguments:**

            CHANNEL_NAME  The channel to run in

            COMMAND       The program/command to start

        **Examples:**

            nerve server channel run my-shell claude --server myproject

            nerve server channel run my-shell python --server myproject

            nerve server channel run my-shell "gemini --flag" --server myproject
        """
        from nerve.server.protocols import Command, CommandType

        ClientClass, connection_arg = get_server_client(server_name)

        async def run():
            try:
                client = ClientClass(connection_arg)
                await client.connect()
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                click.echo(f"Error: Server '{server_name}' not running", err=True)
                sys.exit(1)

            result = await client.send_command(
                Command(
                    type=CommandType.RUN_COMMAND,
                    params={
                        "channel_id": channel_name,
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

    # =========================================================================
    # Read command (under channel) - read buffer
    # =========================================================================
    @channel.command("read")
    @click.argument("channel_name")
    @click.option("--server", "-s", "server_name", required=True, help="Server name the channel is on")
    @click.option("--lines", "-n", default=None, type=int, help="Only show last N lines")
    def channel_read(channel_name: str, server_name: str, lines: int | None):
        """Read the output buffer of a channel.

        Shows all output from the channel since it was created.

        **Arguments:**

            CHANNEL_NAME  The channel to read from

        **Examples:**

            nerve server channel read my-shell --server local

            nerve server channel read my-shell --server local --lines 50
        """
        from nerve.server.protocols import Command, CommandType

        ClientClass, connection_arg = get_server_client(server_name)

        async def run():
            try:
                client = ClientClass(connection_arg)
                await client.connect()
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                click.echo(f"Error: Server '{server_name}' not running", err=True)
                sys.exit(1)

            params = {"channel_id": channel_name}
            if lines:
                params["lines"] = lines

            result = await client.send_command(
                Command(
                    type=CommandType.GET_BUFFER,
                    params=params,
                )
            )

            if result.success:
                click.echo(result.data.get("buffer", ""))
            else:
                click.echo(f"Error: {result.error}", err=True)

            await client.disconnect()

        asyncio.run(run())

    # =========================================================================
    # Send command (under channel) - send and wait
    # =========================================================================
    @channel.command("send")
    @click.argument("channel_name")
    @click.argument("text")
    @click.option("--server", "-s", "server_name", required=True, help="Server name the channel is on")
    @click.option(
        "--parser",
        "-p",
        type=click.Choice(["claude", "gemini", "none"]),
        default=None,
        help="Parser for output. Default: auto-detect from channel type.",
    )
    @click.option(
        "--submit",
        default=None,
        help="Submit sequence (e.g., '\\n', '\\r', '\\x1b\\r'). Default: auto based on parser.",
    )
    def channel_send(channel_name: str, text: str, server_name: str, parser: str | None, submit: str | None):
        """Send input to a channel and get JSON response.

        **Arguments:**

            CHANNEL_NAME  The channel to send to

            TEXT          The text/prompt to send

        **Examples:**

            nerve server channel send my-claude "Explain this code" --server myproject

            nerve server channel send my-shell "ls" --server myproject --parser none
        """
        import json

        from nerve.server.protocols import Command, CommandType

        ClientClass, connection_arg = get_server_client(server_name)

        async def run():
            client = ClientClass(connection_arg)
            await client.connect()

            params = {
                "channel_id": channel_name,
                "text": text,
            }
            # Only include parser if explicitly set (let channel use its default)
            if parser is not None:
                params["parser"] = parser
            # Decode escape sequences in submit string (e.g., "\\x1b" -> actual escape)
            if submit:
                params["submit"] = submit.encode().decode("unicode_escape")

            result = await client.send_command(
                Command(
                    type=CommandType.SEND_INPUT,
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

    # =========================================================================
    # Write command (under channel) - raw write
    # =========================================================================
    @channel.command("write")
    @click.argument("channel_name")
    @click.argument("data")
    @click.option("--server", "-s", "server_name", required=True, help="Server name the channel is on")
    def channel_write(channel_name: str, data: str, server_name: str):
        """Write raw data to a channel (no waiting).

        Low-level write for testing and debugging. Does not wait for response.
        Use escape sequences like \\x1b for Escape, \\r for CR, \\n for LF.

        **Arguments:**

            CHANNEL_NAME  The channel to write to

            DATA          Raw data to write (escape sequences supported)

        **Examples:**

            nerve server channel write my-shell "Hello" --server local

            nerve server channel write my-shell "\\x1b" --server local  # Send Escape

            nerve server channel write my-shell "\\r" --server local    # Send CR
        """
        from nerve.server.protocols import Command, CommandType

        ClientClass, connection_arg = get_server_client(server_name)

        # Decode escape sequences
        decoded_data = data.encode().decode("unicode_escape")

        async def run():
            try:
                client = ClientClass(connection_arg)
                await client.connect()
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                click.echo(f"Error: Server '{server_name}' not running", err=True)
                sys.exit(1)

            result = await client.send_command(
                Command(
                    type=CommandType.WRITE_DATA,
                    params={
                        "channel_id": channel_name,
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

    # =========================================================================
    # Interrupt command (under channel) - send Ctrl+C
    # =========================================================================
    @channel.command("interrupt")
    @click.argument("channel_name")
    @click.option("--server", "-s", "server_name", required=True, help="Server name the channel is on")
    def channel_interrupt(channel_name: str, server_name: str):
        """Send interrupt (Ctrl+C) to a channel.

        Cancels the current operation in the channel.

        **Arguments:**

            CHANNEL_NAME  The channel to interrupt

        **Examples:**

            nerve server channel interrupt my-claude --server local
        """
        from nerve.server.protocols import Command, CommandType

        ClientClass, connection_arg = get_server_client(server_name)

        async def run():
            try:
                client = ClientClass(connection_arg)
                await client.connect()
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                click.echo(f"Error: Server '{server_name}' not running", err=True)
                sys.exit(1)

            result = await client.send_command(
                Command(
                    type=CommandType.SEND_INTERRUPT,
                    params={"channel_id": channel_name},
                )
            )

            if result.success:
                click.echo("Interrupt sent")
            else:
                click.echo(f"Error: {result.error}", err=True)

            await client.disconnect()

        asyncio.run(run())

    # =========================================================================
    # DAG subgroup (under server)
    # =========================================================================
    @server.group()
    def dag():
        """Execute DAGs on the server.

        Run DAG definition files on the server, using server-managed channels.

        **Commands:**

            nerve server dag run       Run a DAG file
        """
        pass

    @dag.command("run")
    @click.argument("file")
    @click.option("--server", "-s", "server_name", required=True, help="Server name to run the DAG on")
    @click.option("--dry-run", "-d", is_flag=True, help="Show execution order without running")
    def dag_run(file: str, server_name: str, dry_run: bool):
        """Run a DAG definition file on the server.

        The file should define a `dag` dict or DAG object with tasks.
        Channels are created automatically if needed.

        **Examples:**

            nerve server dag run workflow.py --server myproject

            nerve server dag run workflow.py --server myproject --dry-run
        """
        from nerve.frontends.cli.server_repl import run_dag_file

        socket = f"/tmp/nerve-{server_name}.sock"
        asyncio.run(run_dag_file(file, socket_path=socket, dry_run=dry_run))

    # =========================================================================
    # Server REPL (under server)
    # =========================================================================
    @server.command("repl")
    @click.argument("name")
    def server_repl(name: str):
        """Interactive REPL connected to the server.

        Unlike the standalone `nerve repl`, this REPL connects to a running
        nerve server and operates on server-managed channels.

        **Examples:**

            nerve server repl myproject
        """
        from nerve.frontends.cli.server_repl import run_server_repl

        socket = f"/tmp/nerve-{name}.sock"
        asyncio.run(run_server_repl(socket_path=socket))

    # =========================================================================
    # Standalone commands (no server required)
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
    @click.option(
        "--backend",
        "-b",
        type=click.Choice(["pty", "wezterm"]),
        default="pty",
        help="Backend for channels (pty or wezterm)",
    )
    def repl(file: str | None, dry_run: bool, backend: str):
        """Interactive DAG definition and execution.

        A REPL for defining and running DAGs (Directed Acyclic Graphs)
        of AI CLI tasks. Works standalone without a server.

        **Examples:**

            nerve repl

            nerve repl --backend wezterm

            nerve repl script.py

            nerve repl script.py --dry-run
        """
        from nerve.core.pty import BackendType
        from nerve.frontends.cli.repl import run_from_file, run_interactive

        backend_type = BackendType.WEZTERM if backend == "wezterm" else BackendType.PTY

        if file:
            asyncio.run(run_from_file(file, dry_run=dry_run, backend_type=backend_type))
        else:
            asyncio.run(run_interactive(backend_type=backend_type))

    # =========================================================================
    # WezTerm command group (standalone)
    # =========================================================================
    @cli.group()
    def wezterm():
        """Manage WezTerm panes directly.

        Control AI CLI channels running in WezTerm panes without needing
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
    def wezterm_list(json_output: bool):
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
    @click.option("--command", "-c", "cmd", default="claude", help="Command to run (e.g., claude, gemini)")
    @click.option("--cwd", default=None, help="Working directory")
    @click.option("--name", "-n", default=None, help="Channel name for reference")
    def wezterm_spawn(cmd: str, cwd: str | None, name: str | None):
        """Spawn a new CLI channel in a WezTerm pane.

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

        async def run():
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
    def wezterm_send(pane_id: str, text: str):
        """Send text to a WezTerm pane.

        **Arguments:**

            PANE_ID    The WezTerm pane ID

            TEXT       The text to send

        **Examples:**

            nerve wezterm send 0 "Hello!"

            nerve wezterm send 0 "Explain this code"
        """
        import subprocess

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
    def wezterm_read(pane_id: str, lines: int | None, full: bool):
        """Read content from a WezTerm pane.

        **Arguments:**

            PANE_ID    The WezTerm pane ID

        **Examples:**

            nerve wezterm read 0

            nerve wezterm read 0 --lines 50

            nerve wezterm read 0 --full
        """
        import subprocess

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
    def wezterm_kill(pane_id: str):
        """Kill a WezTerm pane.

        **Arguments:**

            PANE_ID    The WezTerm pane ID to kill

        **Examples:**

            nerve wezterm kill 0
        """
        import subprocess

        result = subprocess.run(
            ["wezterm", "cli", "kill-pane", "--pane-id", pane_id],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            click.echo(f"Error: {result.stderr}", err=True)
            sys.exit(1)

        click.echo(f"Killed pane {pane_id}")

    cli()


if __name__ == "__main__":
    main()
