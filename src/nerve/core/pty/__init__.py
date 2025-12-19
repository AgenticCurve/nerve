"""PTY process management.

Pure PTY primitives with no external dependencies or assumptions.

Classes:
    PTYProcess: Single PTY process lifecycle and I/O.
    PTYConfig: Configuration for PTY spawning.
    PTYManager: Manage multiple PTY processes.

Example:
    >>> from nerve.core.pty import PTYProcess, PTYConfig
    >>>
    >>> async def main():
    ...     config = PTYConfig(rows=24, cols=80, cwd="/my/project")
    ...     pty = PTYProcess(["claude"], config)
    ...     await pty.start()
    ...
    ...     await pty.write("hello\\n")
    ...
    ...     async for chunk in pty.read_stream():
    ...         print(chunk, end="")
    ...         if "ready" in chunk:
    ...             break
    ...
    ...     await pty.stop()
"""

from nerve.core.pty.manager import PTYManager
from nerve.core.pty.process import PTYConfig, PTYProcess

__all__ = ["PTYProcess", "PTYConfig", "PTYManager"]
