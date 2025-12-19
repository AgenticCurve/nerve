"""PTY manager for multiple processes."""

from __future__ import annotations

from dataclasses import dataclass, field

from nerve.core.pty.process import PTYConfig, PTYProcess


@dataclass
class PTYManager:
    """Manage multiple PTY processes.

    A simple registry for tracking multiple PTY processes.
    Useful when you need to manage several AI CLI instances.

    Example:
        >>> manager = PTYManager()
        >>>
        >>> # Spawn processes
        >>> id1 = await manager.spawn(["claude"], cwd="/project1")
        >>> id2 = await manager.spawn(["gemini"], cwd="/project2")
        >>>
        >>> # Get a process
        >>> pty = manager.get(id1)
        >>> await pty.write("hello\\n")
        >>>
        >>> # Stop all
        >>> await manager.stop_all()
    """

    _processes: dict[str, PTYProcess] = field(default_factory=dict)
    _counter: int = 0

    async def spawn(
        self,
        command: list[str],
        config: PTYConfig | None = None,
        process_id: str | None = None,
    ) -> str:
        """Spawn a new PTY process.

        Args:
            command: Command and arguments to run.
            config: PTY configuration.
            process_id: Optional ID (auto-generated if not provided).

        Returns:
            The process ID.
        """
        if process_id is None:
            process_id = f"pty_{self._counter}"
            self._counter += 1

        pty = PTYProcess(command, config)
        await pty.start()

        self._processes[process_id] = pty
        return process_id

    def get(self, process_id: str) -> PTYProcess | None:
        """Get a PTY process by ID.

        Args:
            process_id: The process ID.

        Returns:
            The PTYProcess, or None if not found.
        """
        return self._processes.get(process_id)

    def list(self) -> list[str]:
        """List all process IDs.

        Returns:
            List of process IDs.
        """
        return list(self._processes.keys())

    def list_running(self) -> list[str]:
        """List IDs of running processes.

        Returns:
            List of running process IDs.
        """
        return [pid for pid, pty in self._processes.items() if pty.is_running]

    async def stop(self, process_id: str) -> bool:
        """Stop a PTY process.

        Args:
            process_id: The process ID.

        Returns:
            True if stopped, False if not found.
        """
        pty = self._processes.get(process_id)
        if pty:
            await pty.stop()
            del self._processes[process_id]
            return True
        return False

    async def stop_all(self) -> None:
        """Stop all PTY processes."""
        for pty in self._processes.values():
            await pty.stop()
        self._processes.clear()
