"""Backend protocol for terminal process management.

This module defines the interface that all backends must implement.
Backends handle the actual spawning and I/O with terminal processes.

Available backends:
    - PTYBackend: Direct PTY using pty.fork() (default)
    - WezTermBackend: Uses WezTerm CLI to manage panes
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum


class BackendType(Enum):
    """Available backend types."""

    PTY = "pty"
    WEZTERM = "wezterm"


@dataclass
class BackendConfig:
    """Configuration for backends.

    Attributes:
        rows: Terminal height in rows.
        cols: Terminal width in columns.
        env: Additional environment variables.
        cwd: Working directory for the process.
    """

    rows: int = 24
    cols: int = 80
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None


class Backend(ABC):
    """Abstract base class for terminal backends.

    A backend manages a terminal process - spawning it, sending input,
    and reading output. Different backends use different mechanisms:
    - PTY: Direct pseudo-terminal
    - WezTerm: WezTerm's CLI interface

    All backends provide the same interface so Session doesn't need
    to know which backend it's using.
    """

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the process is currently running."""
        ...

    @property
    @abstractmethod
    def buffer(self) -> str:
        """Current accumulated output buffer."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the terminal process.

        Raises:
            OSError: If the process fails to start.
        """
        ...

    @abstractmethod
    async def write(self, data: str) -> None:
        """Write data to the terminal.

        Args:
            data: Text to write to the process.

        Raises:
            RuntimeError: If backend is not started.
        """
        ...

    @abstractmethod
    def read_stream(self, chunk_size: int = 4096) -> AsyncIterator[str]:
        """Stream output chunks as they arrive.

        Args:
            chunk_size: Maximum bytes to read at once.

        Yields:
            Output chunks as strings.

        Raises:
            RuntimeError: If backend is not started.
        """
        ...

    @abstractmethod
    def read_buffer(self, clear: bool = False) -> str:
        """Read the accumulated output buffer.

        Args:
            clear: If True, clear the buffer after reading.

        Returns:
            The buffer contents.
        """
        ...

    @abstractmethod
    def read_tail(self, lines: int = 20) -> str:
        """Read the last N lines of the buffer.

        Args:
            lines: Number of lines to return.

        Returns:
            Last N lines of output.
        """
        ...

    @abstractmethod
    def clear_buffer(self) -> None:
        """Clear the output buffer."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the terminal process."""
        ...


def get_backend(
    backend_type: BackendType,
    command: list[str],
    config: BackendConfig | None = None,
    pane_id: str | None = None,
) -> Backend:
    """Get a backend instance.

    Args:
        backend_type: Type of backend to create.
        command: Command to run.
        config: Backend configuration.
        pane_id: For WezTerm, attach to existing pane instead of spawning.

    Returns:
        A Backend instance.

    Raises:
        ValueError: If backend type is not supported.
    """
    config = config or BackendConfig()

    if backend_type == BackendType.PTY:
        from nerve.core.pty.pty_backend import PTYBackend

        if pane_id is not None:
            raise ValueError("PTY backend does not support attaching to existing panes")

        return PTYBackend(command, config)

    elif backend_type == BackendType.WEZTERM:
        from nerve.core.pty.wezterm_backend import WezTermBackend

        return WezTermBackend(command, config, pane_id=pane_id)

    else:
        raise ValueError(f"Unknown backend type: {backend_type}")
