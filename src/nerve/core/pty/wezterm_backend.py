"""WezTerm Backend - Manage processes via WezTerm CLI.

This backend uses WezTerm's CLI interface to spawn and manage processes
in WezTerm panes. Useful when you want to:
- See the terminal output visually in WezTerm
- Use WezTerm's features (splits, tabs, etc.)
- Debug what's happening in the terminal
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncIterator

from nerve.core.pty.backend import Backend, BackendConfig


class WezTermBackend(Backend):
    """WezTerm CLI backend.

    Manages a process running in a WezTerm pane. Uses wezterm CLI
    commands for all operations.

    Requirements:
        - WezTerm must be running
        - wezterm CLI must be available in PATH

    Example:
        >>> # Spawn new pane
        >>> backend = WezTermBackend(["claude"], BackendConfig(cwd="/project"))
        >>> await backend.start()  # Creates new pane in WezTerm
        >>> await backend.write("hello\\n")
        >>> content = backend.read_buffer()
        >>> await backend.stop()  # Kills the pane
        >>>
        >>> # Attach to existing pane
        >>> backend = WezTermBackend([], pane_id="4")
        >>> await backend.attach("4")
        >>> content = backend.read_buffer()
    """

    def __init__(
        self,
        command: list[str],
        config: BackendConfig | None = None,
        pane_id: str | None = None,
    ) -> None:
        """Initialize WezTerm backend.

        Args:
            command: Command and arguments to run (e.g., ["claude"]).
            config: Backend configuration options.
            pane_id: Existing pane ID to attach to (skips spawn).
        """
        self._command = command
        self._config = config or BackendConfig()
        self._pane_id: str | None = pane_id
        self._buffer: str = ""
        self._running = pane_id is not None  # Already running if attaching
        self._last_line_count: int = 0
        self._attached = pane_id is not None  # Track if we attached vs spawned

    @property
    def pane_id(self) -> str | None:
        """WezTerm pane ID."""
        return self._pane_id

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
        """Spawn the command in a new WezTerm pane.

        Creates a new pane (split) in the current WezTerm window
        running the specified command.

        Raises:
            RuntimeError: If WezTerm is not available or spawn fails.
        """
        cmd = ["wezterm", "cli", "spawn", "--"]
        cmd.extend(self._command)

        if self._config.cwd:
            # Insert --cwd before the --
            cmd = ["wezterm", "cli", "spawn", "--cwd", self._config.cwd, "--"]
            cmd.extend(self._command)

        try:
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                raise RuntimeError(f"wezterm spawn failed: {stderr.decode()}")

            # spawn outputs the pane ID
            self._pane_id = stdout.decode().strip()
            self._running = True
            self._buffer = ""
            self._last_line_count = 0

        except FileNotFoundError as err:
            raise RuntimeError(
                "wezterm CLI not found. Make sure WezTerm is installed and in PATH."
            ) from err

    async def attach(self, pane_id: str) -> None:
        """Attach to an existing WezTerm pane.

        Args:
            pane_id: The pane ID to attach to.

        Raises:
            RuntimeError: If pane doesn't exist.
        """
        # Verify pane exists by trying to get its text
        cmd = ["wezterm", "cli", "get-text", "--pane-id", pane_id]

        try:
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                raise RuntimeError(f"Pane {pane_id} not found: {stderr.decode()}")

            self._pane_id = pane_id
            self._running = True
            self._attached = True
            self._buffer = stdout.decode("utf-8", errors="replace")

        except FileNotFoundError as err:
            raise RuntimeError(
                "wezterm CLI not found. Make sure WezTerm is installed and in PATH."
            ) from err

    async def write(self, data: str) -> None:
        """Send text to the WezTerm pane.

        Args:
            data: Text to send to the pane.

        Raises:
            RuntimeError: If pane is not started.
        """
        if not self._pane_id:
            raise RuntimeError("WezTerm pane not started")

        # Convert \n to \r for terminal (Enter key is carriage return)
        data = data.replace("\n", "\r")

        cmd = [
            "wezterm",
            "cli",
            "send-text",
            "--pane-id",
            self._pane_id,
            "--no-paste",  # Send directly, not as bracketed paste
            data,
        ]

        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await result.communicate()

        if result.returncode != 0:
            raise RuntimeError(f"wezterm send-text failed: {stderr.decode()}")

    async def read_stream(self, chunk_size: int = 4096) -> AsyncIterator[str]:
        """Stream output by polling WezTerm pane content.

        Since WezTerm CLI doesn't support true streaming, this polls
        get-text and yields new content as it appears.

        Args:
            chunk_size: Not used (kept for interface compatibility).

        Yields:
            Output chunks as strings.

        Raises:
            RuntimeError: If pane is not started.
        """
        if not self._pane_id:
            raise RuntimeError("WezTerm pane not started")

        while self._running:
            try:
                new_content = await self._get_pane_text()

                # Find new content by comparing with buffer
                if len(new_content) > len(self._buffer):
                    chunk = new_content[len(self._buffer) :]
                    self._buffer = new_content
                    yield chunk
                elif new_content != self._buffer:
                    # Content changed but didn't grow (scrollback limit?)
                    # Just update buffer
                    self._buffer = new_content

                await asyncio.sleep(0.1)  # Poll interval

            except Exception:
                # Pane might be gone
                break

    async def _get_pane_text(self, start_line: int | None = None) -> str:
        """Get text content from the pane.

        Args:
            start_line: Starting line (negative for scrollback).

        Returns:
            Pane text content.
        """
        cmd = ["wezterm", "cli", "get-text", "--pane-id", self._pane_id]

        if start_line is not None:
            cmd.extend(["--start-line", str(start_line)])

        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await result.communicate()

        return stdout.decode("utf-8", errors="replace")

    def read_buffer(self, clear: bool = False) -> str:
        """Read the accumulated output buffer.

        Note: For WezTerm, this returns the cached buffer. Call
        _sync_buffer() first if you need fresh content.

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

    async def sync_buffer(self) -> str:
        """Sync buffer with current pane content.

        Fetches latest content from WezTerm and updates the buffer.

        Returns:
            The updated buffer content.
        """
        if self._pane_id:
            self._buffer = await self._get_pane_text()
        return self._buffer

    async def stop(self) -> None:
        """Stop the backend.

        For spawned panes, kills the pane.
        For attached panes, just disconnects (doesn't kill).
        """
        if self._pane_id and not self._attached:
            # Only kill panes we spawned, not ones we attached to
            cmd = ["wezterm", "cli", "kill-pane", "--pane-id", self._pane_id]

            try:
                result = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await result.communicate()
                if result.returncode != 0:
                    import logging
                    logging.getLogger(__name__).warning(
                        "Failed to kill WezTerm pane %s: %s",
                        self._pane_id,
                        stderr.decode() if stderr else "unknown error",
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "Error killing WezTerm pane %s: %s", self._pane_id, e
                )

        self._running = False
        self._pane_id = None

    async def focus(self) -> None:
        """Focus (activate) the WezTerm pane."""
        if self._pane_id:
            cmd = ["wezterm", "cli", "activate-pane", "--pane-id", self._pane_id]

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await result.communicate()

    async def get_pane_info(self) -> dict | None:
        """Get information about the pane.

        Returns:
            Dict with pane info, or None if not available.
        """
        if not self._pane_id:
            return None

        cmd = ["wezterm", "cli", "list", "--format", "json"]

        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await result.communicate()

        if result.returncode == 0:
            import json

            try:
                panes = json.loads(stdout.decode())
                for pane in panes:
                    if str(pane.get("pane_id")) == self._pane_id:
                        return pane
            except json.JSONDecodeError:
                pass

        return None


def list_wezterm_panes() -> list[dict]:
    """List all WezTerm panes.

    Returns:
        List of pane info dicts.
    """
    import json

    try:
        result = subprocess.run(
            ["wezterm", "cli", "list", "--format", "json"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    return []


def is_wezterm_available() -> bool:
    """Check if WezTerm CLI is available.

    Returns:
        True if wezterm CLI is available and working.
    """
    try:
        result = subprocess.run(
            ["wezterm", "cli", "list"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
