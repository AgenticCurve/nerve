"""Server commands - manage the nerve daemon."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import rich_click as click

from nerve.frontends.cli.utils import (
    find_all_servers,
    force_kill_server,
    get_server_transport,
)


@click.group()
def server() -> None:
    """Server commands - manage the nerve daemon.

    The nerve daemon provides a persistent service for managing
    AI CLI nodes over Unix socket or HTTP.

    **Lifecycle:**

        nerve server start     Start the daemon

        nerve server stop      Stop the daemon

        nerve server status    Check if daemon is running

        nerve server list      List all running servers

    **Session management:**

        nerve server session   Manage sessions (workspaces with nodes/graphs)

    **Node management:**

        nerve server node      Create and interact with nodes

    **Graph execution:**

        nerve server graph     Run graphs on the server

    **Interactive:**

        nerve repl --server <name>    Connect to server REPL (unified command)
    """
    pass


@server.command()
@click.argument("name", default="local")
@click.option("--host", default=None, help="Host to bind (enables network transport)")
@click.option("--port", default=8080, help="Port for network transport")
@click.option("--tcp", "use_tcp", is_flag=True, help="Use TCP socket transport (requires --host)")
@click.option("--http", "use_http", is_flag=True, help="Use HTTP transport (requires --host)")
def start(name: str, host: str | None, port: int, use_tcp: bool, use_http: bool) -> None:
    """Start the nerve daemon.

    NAME determines the socket path (/tmp/nerve-NAME.sock). Defaults to "local".
    Names must be lowercase alphanumeric with dashes, 1-32 characters.

    **Transports:**

        Unix socket (default): Local-only, fast IPC via /tmp/nerve-NAME.sock

        TCP socket (--tcp): Network-capable, same JSON-line protocol

        HTTP (--http): REST API + WebSocket for web clients

    **Examples:**

        nerve server start

        nerve server start myproject

        nerve server start myproject --tcp --host 0.0.0.0 --port 8080
    """
    import os
    import signal as sig

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

    # Check if server with this name is already running
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            # Check if process is still running
            os.kill(pid, 0)
            click.echo(f"Error: Server '{name}' is already running (pid {pid})", err=True)
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            # Process not running, clean up stale files
            pass

    click.echo(f"Starting nerve daemon '{name}'...")

    from nerve.server import NerveEngine
    from nerve.transport import HTTPServer, TCPSocketServer, UnixSocketServer

    # Determine transport type
    transport_type = "unix"  # default
    if use_http:
        transport_type = "http"
    elif use_tcp:
        transport_type = "tcp"
    elif host:
        # Legacy: --host without --tcp/--http defaults to HTTP for backwards compatibility
        transport_type = "http"

    transport: HTTPServer | TCPSocketServer | UnixSocketServer
    if transport_type == "http":
        assert host is not None  # Type narrowing
        transport = HTTPServer(host=host, port=port)
        click.echo(f"Listening on http://{host}:{port}")
    elif transport_type == "tcp":
        assert host is not None  # Type narrowing
        transport = TCPSocketServer(host=host, port=port)
        click.echo(f"Listening on tcp://{host}:{port}")
    else:
        transport = UnixSocketServer(socket_path)
        click.echo(f"Listening on {socket_path}")

    engine = NerveEngine(event_sink=transport, _server_name=name)

    # Create new process group so we can kill all children on force stop
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

    async def run() -> None:
        loop = asyncio.get_running_loop()
        shutdown_event = asyncio.Event()
        shutdown_count = [0]  # Use list for nonlocal in closure

        async def force_cleanup_and_exit() -> None:
            """Force kill all nodes and exit."""
            click.echo("Killing nodes...")
            for session in engine._sessions.values():
                for node_id, node in list(session.nodes.items()):
                    try:
                        if hasattr(node, "stop"):
                            await asyncio.wait_for(node.stop(), timeout=2.0)
                    except TimeoutError:
                        click.echo(f"  {node_id}: timeout, force killing...")
                        if hasattr(node, "backend") and hasattr(node.backend, "process"):
                            try:
                                node.backend.process.kill()
                            except Exception:
                                pass
                    except Exception:
                        pass  # Best effort
                session.nodes.clear()
            click.echo("Done.")
            os._exit(0)

        def handle_shutdown(sig_name: str) -> None:
            shutdown_count[0] += 1
            if shutdown_count[0] == 1:
                click.echo(f"\nReceived {sig_name}, shutting down gracefully...")
                click.echo("(Press Ctrl+C again to force quit)")
                engine._shutdown_requested = True
                shutdown_event.set()
            else:
                click.echo("\nForce quitting...")
                loop.create_task(force_cleanup_and_exit())

        # Use asyncio signal handlers for proper event loop integration
        loop.add_signal_handler(sig.SIGTERM, lambda: handle_shutdown("SIGTERM"))
        loop.add_signal_handler(sig.SIGINT, lambda: handle_shutdown("SIGINT"))

        try:
            await transport.serve(engine)
        finally:
            # Clean up all nodes before exiting
            click.echo("Cleaning up nodes...")
            for session in engine._sessions.values():
                for _node_id, node in list(session.nodes.items()):
                    try:
                        if hasattr(node, "stop"):
                            await node.stop()
                    except Exception:
                        pass  # Best effort cleanup
                session.nodes.clear()
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
@click.argument("name", default="local")
@click.option("--all", "stop_all", is_flag=True, help="Stop all nerve servers")
@click.option("--force", "-f", is_flag=True, help="Force kill (SIGKILL) without graceful shutdown")
@click.option(
    "--timeout", "-t", default=5.0, help="Graceful shutdown timeout in seconds (default: 5)"
)
def stop(name: str, stop_all: bool, force: bool, timeout: float) -> None:
    """Stop the nerve daemon.

    Sends a shutdown command to the running daemon, which will:
    - Close all active nodes
    - Cancel all running graphs
    - Cleanup and exit

    If graceful shutdown times out, automatically falls back to force kill.

    **Examples:**

        nerve server stop

        nerve server stop myproject --force

        nerve server stop --all
    """
    from nerve.server.protocols import Command, CommandType
    from nerve.transport import UnixSocketClient

    async def graceful_stop_socket(sock_path: str, timeout_secs: float) -> bool:
        """Try graceful shutdown via Unix socket. Returns True if successful."""
        try:
            client = UnixSocketClient(sock_path)
            await client.connect()
            result = await client.send_command(
                Command(type=CommandType.STOP, params={}),
                timeout=timeout_secs,
            )
            await client.disconnect()
            return bool(result.success)
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
            async with (
                aiohttp.ClientSession() as session,
                session.post(url, timeout=aiohttp.ClientTimeout(total=timeout_secs)) as response,
            ):
                if response.status == 200:
                    data = await response.json()
                    return bool(data.get("success", False))
                return False
        except (TimeoutError, Exception):
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
                Command(type=CommandType.STOP, params={}),
                timeout=timeout_secs,
            )
            await client.disconnect()
            return bool(result.success)
        except (ConnectionRefusedError, OSError):
            return False
        except TimeoutError:
            return False

    async def stop_server(server_name: str, force_mode: bool, timeout_secs: float) -> bool:
        """Stop a server - gracefully first, then force if needed."""
        sock_path = f"/tmp/nerve-{server_name}.sock"
        transport_type, host_port = get_server_transport(server_name)
        graceful_success: bool

        if force_mode:
            click.echo(f"  Force stopping '{server_name}'...")
            return force_kill_server(server_name, echo_fn=click.echo)

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
        click.echo("  Graceful shutdown failed, force killing...")
        if force_kill_server(server_name, echo_fn=click.echo):
            return True

        click.echo(f"  Could not stop '{server_name}'", err=True)
        return False

    async def run() -> None:
        if stop_all:
            server_names = find_all_servers()

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
@click.argument("name", default="local")
@click.option("--all", "show_all", is_flag=True, help="Show all nerve servers")
def status(name: str, show_all: bool) -> None:
    """Check if the nerve daemon is running.

    **Examples:**

        nerve server status

        nerve server status myproject

        nerve server status --all
    """
    from nerve.server.protocols import Command, CommandType
    from nerve.transport import UnixSocketClient

    async def get_socket_status(sock_path: str) -> dict[str, Any] | None:
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

    async def get_http_status(host_port: str) -> dict[str, Any] | None:
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
        except (TimeoutError, Exception):
            return None

    async def get_tcp_status(host_port: str) -> dict[str, Any] | None:
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
        except (TimeoutError, Exception):
            return None

    async def get_server_status(server_name: str) -> dict[str, Any] | None:
        """Get status of a server by name. Returns None if not running."""
        transport_type, host_port = get_server_transport(server_name)

        if transport_type == "http" and host_port:
            status_data = await get_http_status(host_port)
            if status_data:
                return {"transport": f"http://{host_port}", **status_data}
        elif transport_type == "tcp" and host_port:
            status_data = await get_tcp_status(host_port)
            if status_data:
                return {"transport": f"tcp://{host_port}", **status_data}
        else:
            sock_path = f"/tmp/nerve-{server_name}.sock"
            status_data = await get_socket_status(sock_path)
            if status_data:
                return {"transport": sock_path, **status_data}
        return None

    async def run() -> None:
        if show_all:
            server_names = find_all_servers()

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

            click.echo(f"{'NAME':<20} {'TRANSPORT':<30} {'NODES':<10} {'GRAPHS'}")
            click.echo("-" * 70)
            for s in running:
                click.echo(
                    f"{s['name']:<20} {s['transport']:<30} "
                    f"{s.get('nodes', '?'):<10} {s.get('graphs', '?')}"
                )
        else:
            status_data = await get_server_status(name)
            if status_data:
                click.echo(f"Server '{name}' running on {status_data['transport']}")
                if "nodes" in status_data:
                    click.echo(f"  Nodes: {status_data.get('nodes', 0)}")
                    click.echo(f"  Graphs: {status_data.get('graphs', 0)}")
            else:
                click.echo(f"Server '{name}' not running")
                sys.exit(1)

    asyncio.run(run())


@server.command("list")
def server_list() -> None:
    """List all running nerve servers.

    Shows all nerve daemon instances currently running on this machine.

    **Examples:**

        nerve server list
    """
    from nerve.server.protocols import Command, CommandType
    from nerve.transport import HTTPClient, TCPSocketClient, UnixSocketClient

    async def get_server_status(server_name: str) -> dict[str, Any] | None:
        """Get status of a server by name. Returns None if not running."""

        transport_type, host_port = get_server_transport(server_name)
        result_dict: dict[str, Any]

        if transport_type == "http" and host_port:
            try:
                http_client = HTTPClient(f"http://{host_port}")
                await http_client.connect()
                result = await http_client.send_command(
                    Command(type=CommandType.PING, params={}),
                    timeout=5.0,
                )
                await http_client.disconnect()
                if result.success and result.data:
                    result_dict = {"transport": f"http://{host_port}"}
                    result_dict.update(result.data)
                    return result_dict
            except Exception:
                pass
        elif transport_type == "tcp" and host_port:
            try:
                host, port_str = host_port.split(":")
                port = int(port_str)
                tcp_client = TCPSocketClient(host, port)
                await tcp_client.connect()
                result = await tcp_client.send_command(
                    Command(type=CommandType.PING, params={}),
                    timeout=5.0,
                )
                await tcp_client.disconnect()
                if result.success and result.data:
                    result_dict = {"transport": f"tcp://{host_port}"}
                    result_dict.update(result.data)
                    return result_dict
            except Exception:
                pass
        else:
            sock_path = f"/tmp/nerve-{server_name}.sock"
            try:
                unix_client = UnixSocketClient(sock_path)
                await unix_client.connect()
                result = await unix_client.send_command(Command(type=CommandType.PING, params={}))
                await unix_client.disconnect()
                if result.success and result.data:
                    result_dict = {"transport": sock_path}
                    result_dict.update(result.data)
                    return result_dict
            except Exception:
                pass
        return None

    async def run() -> None:
        server_names = find_all_servers()

        if not server_names:
            click.echo("No nerve servers running")
            return

        running = []
        for server_name in sorted(server_names):
            status_data = await get_server_status(server_name)
            if status_data:
                running.append({"name": server_name, **status_data})

        if not running:
            click.echo("No nerve servers running")
            return

        click.echo(f"{'NAME':<20} {'TRANSPORT':<30} {'NODES':<10} {'GRAPHS'}")
        click.echo("-" * 70)
        for s in running:
            click.echo(
                f"{s['name']:<20} {s['transport']:<30} "
                f"{s.get('nodes', '?'):<10} {s.get('graphs', '?')}"
            )

    asyncio.run(run())
