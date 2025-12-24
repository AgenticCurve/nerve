"""Shared utilities for CLI commands."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from glob import glob
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.transport import HTTPClient, TCPSocketClient, UnixSocketClient


def get_server_client(
    server_name: str,
) -> tuple[type[HTTPClient] | type[TCPSocketClient] | type[UnixSocketClient], str | tuple[str, int]]:
    """Get the appropriate client class and connection info for a server.

    Returns (ClientClass, connection_info) tuple where:
    - ClientClass: The client class to instantiate
    - connection_info: Argument to pass to the constructor

    Usage:
        ClientClass, conn_info = get_server_client("myserver")
        client = ClientClass(conn_info)  # or ClientClass(*conn_info) for TCP
        await client.connect()
    """
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
        return TCPSocketClient, (host, int(port_str))
    else:
        socket_path = f"/tmp/nerve-{server_name}.sock"
        return UnixSocketClient, socket_path


def create_client(server_name: str) -> HTTPClient | TCPSocketClient | UnixSocketClient:
    """Create and return a client instance for a server.

    This handles the TCP case where we need to unpack the tuple.
    """
    from nerve.transport import HTTPClient, TCPSocketClient, UnixSocketClient

    client_class, conn_info = get_server_client(server_name)

    if client_class is TCPSocketClient:
        assert isinstance(conn_info, tuple)
        host, port = conn_info
        return TCPSocketClient(host, port)
    elif client_class is HTTPClient:
        assert isinstance(conn_info, str)
        return HTTPClient(conn_info)
    else:
        assert isinstance(conn_info, str)
        return UnixSocketClient(conn_info)


def get_server_transport(server_name: str) -> tuple[str, str | None]:
    """Get server transport type and connection info.

    Returns (type, connection_info).
    - For "http": connection_info is the base URL
    - For "tcp": connection_info is "host:port"
    - For "unix": connection_info is the socket path
    """
    http_file = f"/tmp/nerve-{server_name}.http"
    tcp_file = f"/tmp/nerve-{server_name}.tcp"

    if os.path.exists(http_file):
        with open(http_file) as f:
            return "http", f.read().strip()
    if os.path.exists(tcp_file):
        with open(tcp_file) as f:
            return "tcp", f.read().strip()
    # Default to unix socket
    socket_path = f"/tmp/nerve-{server_name}.sock"
    return "unix", socket_path


def get_server_name_from_socket(sock_path: str) -> str:
    """Extract server name from socket path.

    /tmp/nerve-myproject.sock -> myproject
    """
    match = re.match(r"/tmp/nerve-(.+)\.sock", sock_path)
    return match.group(1) if match else ""


def get_server_name_from_http(http_path: str) -> str:
    """Extract server name from HTTP tracking file path.

    /tmp/nerve-myproject.http -> myproject
    """
    match = re.match(r"/tmp/nerve-(.+)\.http", http_path)
    return match.group(1) if match else ""


def get_server_name_from_tcp(tcp_path: str) -> str:
    """Extract server name from TCP tracking file path.

    /tmp/nerve-myproject.tcp -> myproject
    """
    match = re.match(r"/tmp/nerve-(.+)\.tcp", tcp_path)
    return match.group(1) if match else ""


def find_all_servers() -> set[str]:
    """Find all nerve server names from tracking files.

    Returns a set of unique server names.
    """
    server_names: set[str] = set()

    for sock_path in glob("/tmp/nerve-*.sock"):
        name = get_server_name_from_socket(sock_path)
        if name:
            server_names.add(name)

    for http_path in glob("/tmp/nerve-*.http"):
        name = get_server_name_from_http(http_path)
        if name:
            server_names.add(name)

    for tcp_path in glob("/tmp/nerve-*.tcp"):
        name = get_server_name_from_tcp(tcp_path)
        if name:
            server_names.add(name)

    return server_names


def get_descendants(pid: int) -> list[int]:
    """Get all descendant PIDs of a process (children, grandchildren, etc.)."""
    descendants = []
    try:
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
                    descendants.extend(get_descendants(child_pid))
    except Exception:
        pass
    return descendants


def wait_for_process_exit(pid: int, timeout: float = 5.0) -> bool:
    """Wait for a process to exit.

    Returns True if exited, False if still running after timeout.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            os.kill(pid, 0)  # Check if process exists
            time.sleep(0.1)
        except ProcessLookupError:
            return True  # Process exited
    return False  # Still running after timeout


def force_kill_server(server_name: str, echo_fn: Callable[[str], Any] = print) -> bool:
    """Force kill a server and all its node processes.

    For PTY nodes: kills child processes directly.
    For WezTerm nodes: sends SIGTERM first to let server clean up panes,
    then SIGKILL if needed.

    Args:
        server_name: Name of the server to kill
        echo_fn: Function to use for output (default: print)

    Returns:
        True if server was killed, False otherwise
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
            try:
                os.kill(server_pid, signal.SIGTERM)
                if wait_for_process_exit(server_pid, timeout=5.0):
                    echo_fn(f"  Server {server_pid} exited gracefully")
                    for f_path in [pid_file, socket_file, http_file, tcp_file]:
                        if os.path.exists(f_path):
                            os.unlink(f_path)
                    return True
            except ProcessLookupError:
                echo_fn(f"  Server {server_pid} already stopped")
                for f_path in [pid_file, socket_file, http_file, tcp_file]:
                    if os.path.exists(f_path):
                        os.unlink(f_path)
                return True

            # Server didn't exit from SIGTERM, need to force kill
            echo_fn("  Server didn't respond to SIGTERM, force killing...")

            # Find all descendant processes (PTY nodes)
            descendants = get_descendants(server_pid)

            # Kill descendants first (PTY nodes), then the server
            killed_count = 0
            for child_pid in descendants:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                    killed_count += 1
                except ProcessLookupError:
                    pass

            # Force kill the server process
            try:
                os.kill(server_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

            if killed_count > 0:
                echo_fn(f"  Killed server {server_pid} and {killed_count} node process(es)")
            else:
                echo_fn(f"  Killed server {server_pid}")

            # Clean up files
            for f_path in [pid_file, socket_file, http_file, tcp_file]:
                if os.path.exists(f_path):
                    os.unlink(f_path)
            return True

        except (ValueError, ProcessLookupError, PermissionError) as e:
            echo_fn(f"  Could not kill process: {e}")
            for f_path in [pid_file, socket_file, http_file, tcp_file]:
                if os.path.exists(f_path):
                    os.unlink(f_path)
            return False
    else:
        # No PID file, just clean up stale files
        cleaned = False
        for f_path in [socket_file, http_file, tcp_file]:
            if os.path.exists(f_path):
                os.unlink(f_path)
                cleaned = True
        if cleaned:
            echo_fn("  Cleaned up stale files")
        return False
