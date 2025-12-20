"""WezTerm Backend - Manage processes via WezTerm CLI.

This backend uses WezTerm's CLI interface to spawn and manage processes
in WezTerm panes. Useful when you want to:
- See the terminal output visually in WezTerm
- Use WezTerm's features (splits, tabs, etc.)
- Debug what's happening in the terminal

Key difference from PTY: WezTerm maintains pane content internally,
so we query it directly instead of maintaining a separate buffer.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import AsyncIterator

from nerve.core.pty.backend import Backend, BackendConfig


class WezTermBackend(Backend):
    """WezTerm CLI backend.

    Manages a process running in a WezTerm pane. Uses wezterm CLI
    commands for all operations.

    Unlike PTY backend, WezTerm maintains pane content internally.
    The `buffer` property queries WezTerm directly for fresh content
    rather than maintaining a cached copy.

    Requirements:
        - WezTerm must be running
        - wezterm CLI must be available in PATH

    Example:
        >>> # Spawn new pane
        >>> backend = WezTermBackend(["claude"], BackendConfig(cwd="/project"))
        >>> await backend.start()  # Creates new pane in WezTerm
        >>> await backend.write("hello\\n")
        >>> content = backend.buffer  # Queries WezTerm directly
        >>> await backend.stop()  # Kills the pane
        >>>
        >>> # Attach to existing pane
        >>> backend = WezTermBackend([], pane_id="4")
        >>> await backend.attach("4")
        >>> content = backend.buffer
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
        self._running = pane_id is not None  # Already running if attaching
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
        """Current pane content - always fresh from WezTerm.

        Unlike PTY backend which maintains a cached buffer, WezTerm
        backend queries the pane content directly each time.
        """
        if not self._pane_id:
            return ""
        return self._get_pane_text_sync()

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
            _, stderr = await result.communicate()

            if result.returncode != 0:
                raise RuntimeError(f"Pane {pane_id} not found: {stderr.decode()}")

            self._pane_id = pane_id
            self._running = True
            self._attached = True

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

        Note: For WezTerm, this is mainly useful for compatibility.
        Direct buffer access via the `buffer` property is preferred.

        Args:
            chunk_size: Not used (kept for interface compatibility).

        Yields:
            Output chunks as strings.

        Raises:
            RuntimeError: If pane is not started.
        """
        if not self._pane_id:
            raise RuntimeError("WezTerm pane not started")

        last_content = ""
        while self._running:
            try:
                new_content = self._get_pane_text_sync()

                # Find new content by comparing with last seen
                if len(new_content) > len(last_content):
                    chunk = new_content[len(last_content):]
                    last_content = new_content
                    yield chunk
                elif new_content != last_content:
                    # Content changed but didn't grow (scrollback limit?)
                    last_content = new_content

                await asyncio.sleep(0.1)  # Poll interval

            except Exception:
                # Pane might be gone
                break

    def _get_pane_text_sync(self, start_line: int | None = None) -> str:
        """Synchronously get text content from the pane.

        Args:
            start_line: Starting line (negative for scrollback).

        Returns:
            Pane text content.
        """
        if not self._pane_id:
            return ""

        cmd = ["wezterm", "cli", "get-text", "--pane-id", self._pane_id]

        if start_line is not None:
            cmd.extend(["--start-line", str(start_line)])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        return result.stdout if result.returncode == 0 else ""

    def get_tail(self, lines: int = 20) -> str:
        """Get the last N lines from the pane - fresh from WezTerm.

        Args:
            lines: Number of lines to fetch.

        Returns:
            Last N lines of pane content.
        """
        # Use negative start-line to get from scrollback
        content = self._get_pane_text_sync()
        all_lines = content.split("\n")
        return "\n".join(all_lines[-lines:])

    def read_buffer(self, clear: bool = False) -> str:
        """Read pane content.

        Note: For WezTerm, `clear` has no effect since we query
        WezTerm directly and don't maintain a local buffer.

        Args:
            clear: Ignored for WezTerm backend.

        Returns:
            Current pane content.
        """
        return self.buffer

    def read_tail(self, lines: int = 20) -> str:
        """Read the last N lines from the pane.

        Args:
            lines: Number of lines to return.

        Returns:
            Last N lines of pane content.
        """
        return self.get_tail(lines)

    def clear_buffer(self) -> None:
        """No-op for WezTerm - pane content is managed by WezTerm."""
        pass

    async def sync_buffer(self) -> str:
        """Get fresh pane content.

        For WezTerm, this is equivalent to accessing the buffer property
        since we always query fresh content. Kept for interface compatibility.

        Returns:
            Current pane content.
        """
        return self.buffer

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
                _, stderr = await result.communicate()
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
