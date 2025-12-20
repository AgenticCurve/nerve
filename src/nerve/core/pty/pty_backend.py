"""PTY Backend - Direct pseudo-terminal process management.

This is the default backend that uses Python's pty module to directly
spawn and manage processes. It's simple, fast, and works everywhere
Python runs.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import struct
import termios
from collections.abc import AsyncIterator

from nerve.core.pty.backend import Backend, BackendConfig


class PTYBackend(Backend):
    """Direct PTY backend using pty.fork().

    Manages a process running in a pseudo-terminal. Provides async I/O
    for reading and writing.

    Example:
        >>> backend = PTYBackend(["claude"], BackendConfig(cwd="/project"))
        >>> await backend.start()
        >>> await backend.write("hello\\n")
        >>> async for chunk in backend.read_stream():
        ...     print(chunk, end="")
        >>> await backend.stop()
    """

    def __init__(self, command: list[str], config: BackendConfig | None = None) -> None:
        """Initialize PTY backend.

        Args:
            command: Command and arguments to run (e.g., ["claude"]).
            config: Backend configuration options.
        """
        self._command = command
        self._config = config or BackendConfig()
        self._master_fd: int | None = None
        self._pid: int | None = None
        self._buffer: str = ""
        self._running = False

    @property
    def pid(self) -> int | None:
        """Process ID of the child process."""
        return self._pid

    @property
    def is_running(self) -> bool:
        """Whether the process is currently running."""
        return self._running

    @property
    def buffer(self) -> str:
        """Current accumulated output buffer."""
        return self._buffer

    @property
    def config(self) -> BackendConfig:
        """Backend configuration."""
        return self._config

    async def start(self) -> None:
        """Start the PTY process.

        Raises:
            OSError: If the process fails to start.
        """
        pid, master_fd = pty.fork()

        if pid == 0:
            # Child process
            if self._config.cwd:
                os.chdir(self._config.cwd)

            env = os.environ.copy()
            env.update(self._config.env)
            env["TERM"] = "xterm-256color"

            os.execvpe(self._command[0], self._command, env)
        else:
            # Parent process
            self._pid = pid
            self._master_fd = master_fd
            self._running = True

            # Set window size
            self._set_winsize(self._config.rows, self._config.cols)

            # Make non-blocking
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    async def write(self, data: str) -> None:
        """Write data to PTY stdin.

        Args:
            data: Text to write to the process.

        Raises:
            RuntimeError: If PTY is not started.
        """
        if not self._master_fd:
            raise RuntimeError("PTY not started")

        os.write(self._master_fd, data.encode())

    async def read_stream(self, chunk_size: int = 4096) -> AsyncIterator[str]:
        """Stream output chunks as they arrive.

        Args:
            chunk_size: Maximum bytes to read at once.

        Yields:
            Output chunks as strings.

        Raises:
            RuntimeError: If PTY is not started.
        """
        if not self._master_fd:
            raise RuntimeError("PTY not started")

        loop = asyncio.get_event_loop()

        while self._running:
            try:
                # Wait for data with timeout
                await loop.run_in_executor(None, lambda: self._wait_for_data(timeout=0.1))

                data = os.read(self._master_fd, chunk_size)
                if data:
                    chunk = data.decode("utf-8", errors="replace")
                    self._buffer += chunk
                    yield chunk

            except BlockingIOError:
                await asyncio.sleep(0.01)
            except OSError:
                # Process likely terminated
                break

    def read_buffer(self, clear: bool = False) -> str:
        """Read the accumulated output buffer.

        Args:
            clear: If True, clear the buffer after reading.

        Returns:
            The buffer contents.
        """
        content = self._buffer
        if clear:
            self._buffer = ""
        return content

    def read_tail(self, lines: int = 20) -> str:
        """Read the last N lines of the buffer.

        Args:
            lines: Number of lines to return.

        Returns:
            Last N lines of output.
        """
        all_lines = self._buffer.split("\n")
        return "\n".join(all_lines[-lines:])

    def clear_buffer(self) -> None:
        """Clear the output buffer."""
        self._buffer = ""

    async def resize(self, rows: int, cols: int) -> None:
        """Resize the PTY window.

        Args:
            rows: New height in rows.
            cols: New width in columns.
        """
        self._set_winsize(rows, cols)

    async def stop(self, timeout: float = 1.0) -> None:
        """Stop the PTY process.

        Sends SIGTERM first, waits briefly for graceful exit, then SIGKILL.

        Args:
            timeout: Seconds to wait for graceful exit before SIGKILL (default 1s).
        """
        import signal

        if self._pid:
            try:
                # First try SIGTERM for graceful shutdown
                os.kill(self._pid, signal.SIGTERM)

                # Wait briefly for process to exit gracefully
                for _ in range(int(timeout * 10)):
                    try:
                        pid, _ = os.waitpid(self._pid, os.WNOHANG)
                        if pid != 0:
                            break  # Process exited
                    except ChildProcessError:
                        break  # Already reaped
                    await asyncio.sleep(0.1)
                else:
                    # Process didn't exit, force kill
                    try:
                        os.kill(self._pid, signal.SIGKILL)
                        os.waitpid(self._pid, 0)  # Reap zombie
                    except (ProcessLookupError, ChildProcessError):
                        pass

            except ProcessLookupError:
                pass  # Already dead

        self._running = False
        self._pid = None

        if self._master_fd:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

    async def wait(self) -> int:
        """Wait for the process to exit.

        Returns:
            Exit status of the process.
        """
        if self._pid:
            _, status = os.waitpid(self._pid, 0)
            self._running = False
            return os.WEXITSTATUS(status)
        return -1

    def _set_winsize(self, rows: int, cols: int) -> None:
        """Set the terminal window size."""
        if self._master_fd:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    def _wait_for_data(self, timeout: float) -> bool:
        """Wait for data to be available on the PTY."""
        import select

        if self._master_fd:
            r, _, _ = select.select([self._master_fd], [], [], timeout)
            return bool(r)
        return False
