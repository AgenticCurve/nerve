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
