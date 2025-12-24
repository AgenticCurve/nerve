"""BashNode - ephemeral node for running bash commands.

BashNode executes bash commands via subprocess and returns JSON results.
Each execution spawns a fresh subprocess - no state is maintained between calls.

Key features:
- Returns structured JSON with stdout/stderr/exit_code
- Errors are caught and returned in JSON (never raises)
- Supports interrupt() to send SIGINT (Ctrl+C) to running process
- Working directory and environment configured at node creation
"""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from typing import Any

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.context import ExecutionContext


@dataclass
class BashNode:
    """Ephemeral node that runs bash commands and returns JSON results.

    BashNode is stateless - each execute() call spawns a new subprocess.
    State does not persist between executions (unlike PTYNode/WezTermNode).

    However, commands can be chained within a single execution using shell
    operators like && or ; to maintain state within that execution:

        # This works - all runs in one subprocess
        result = await node.execute(ctx.with_input("cd ~/ && echo hello && pwd"))

    Features:
    - Returns structured JSON with stdout/stderr/exit_code/error fields
    - Errors are caught and returned in JSON (never raises exceptions)
    - Supports interrupt() to send SIGINT (Ctrl+C) to running process
    - Working directory and environment configured at node creation
    - Configurable timeout per-node or per-execution

    Example:
        >>> node = BashNode(id="runner", cwd="/tmp", timeout=30.0)
        >>> ctx = ExecutionContext(session=session, input="ls -la")
        >>> result = await node.execute(ctx)
        >>> print(result)
        {
            "success": True,
            "stdout": "total 48\\ndrwxr-xr-x ...",
            "stderr": "",
            "exit_code": 0,
            "command": "ls -la",
            "error": None,
            "interrupted": False
        }

        >>> # Interrupt long-running command
        >>> task = asyncio.create_task(node.execute(ctx.with_input("sleep 100")))
        >>> await asyncio.sleep(1)
        >>> await node.interrupt()  # Sends SIGINT immediately
        >>> result = await task
        >>> assert result["interrupted"] == True
    """

    id: str
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout: float = 30.0
    persistent: bool = field(default=False, init=False)
    metadata: dict[str, Any] = field(default_factory=dict)
    _current_proc: asyncio.subprocess.Process | None = field(default=None, init=False, repr=False)
    _proc_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Execute a bash command and return JSON result.

        Args:
            context: Execution context with command in context.input.
                     Optional context.timeout overrides node timeout.

        Returns:
            JSON dict with fields:
            - success (bool): Whether command succeeded (exit code 0)
            - stdout (str): Standard output
            - stderr (str): Standard error
            - exit_code (int | None): Process exit code (None if error before execution)
            - command (str): The command that was run
            - error (str | None): Error message if failed
            - interrupted (bool): Whether execution was interrupted (Ctrl+C)

        Note:
            This method never raises exceptions - all errors are returned in
            the result dict. CancellationToken is checked by graphs between
            steps, not here. Use interrupt() to stop execution during this
            node's execution.
        """
        # Initialize result structure
        result = {
            "success": False,
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "command": "",
            "error": None,
            "interrupted": False,
        }

        try:
            # Get command from context
            command = str(context.input) if context.input else ""
            result["command"] = command

            if not command:
                result["error"] = "No command provided in context.input"
                return result

            # Build environment
            env = None
            if self.env:
                import os
                env = os.environ.copy()
                env.update(self.env)

            # Resolve timeout
            timeout = context.timeout or self.timeout

            # Start subprocess and track it for interrupt support
            async with self._proc_lock:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.cwd,
                    env=env,
                )
                self._current_proc = proc

            try:
                # Wait for process to complete with timeout
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )

                # Decode output
                result["stdout"] = stdout_bytes.decode('utf-8', errors='replace')
                result["stderr"] = stderr_bytes.decode('utf-8', errors='replace')
                result["exit_code"] = proc.returncode or 0

                # Check if interrupted (SIGINT exit codes: -2 or 130)
                if proc.returncode in (-2, 130):
                    result["interrupted"] = True
                    result["error"] = "Command interrupted (Ctrl+C)"
                elif proc.returncode == 0:
                    result["success"] = True
                else:
                    result["error"] = f"Command exited with code {proc.returncode}"

            except TimeoutError:
                # Kill the process on timeout
                proc.kill()
                await proc.wait()
                result["error"] = f"Command timed out after {timeout}s"

            finally:
                # Clear current process reference (critical for interrupt safety)
                async with self._proc_lock:
                    self._current_proc = None

        except Exception as e:
            # Catch any other exceptions (file not found, permission denied, etc.)
            result["error"] = f"{type(e).__name__}: {str(e)}"

        return result

    async def interrupt(self) -> None:
        """Send interrupt signal (Ctrl+C / SIGINT) to the running process.

        This is immediate and works during node execution.
        Consistent with terminal node interrupt() pattern.

        This is different from CancellationToken:
        - CancellationToken: Graph checks between steps (cooperative)
        - interrupt(): Stops current node execution (immediate)

        This method is safe to call:
        - Multiple times
        - When no execution is in progress
        - From a different task/thread than execute()

        Example:
            >>> # Start long-running command
            >>> task = asyncio.create_task(
            ...     node.execute(ExecutionContext(session=session, input="sleep 100"))
            ... )
            >>>
            >>> # Interrupt it immediately
            >>> await asyncio.sleep(1)
            >>> await node.interrupt()  # ← Sends SIGINT right now
            >>>
            >>> result = await task
            >>> assert result["interrupted"] == True
        """
        async with self._proc_lock:
            if self._current_proc and self._current_proc.returncode is None:
                try:
                    self._current_proc.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    # Process already terminated - safe to ignore
                    pass

    def to_info(self) -> NodeInfo:
        """Get node information.

        Returns:
            NodeInfo for this node.
        """
        return NodeInfo(
            id=self.id,
            node_type="bash",
            state=NodeState.READY,  # Ephemeral nodes are always ready
            persistent=self.persistent,
            metadata={
                "cwd": self.cwd,
                "timeout": self.timeout,
                "env_vars": list(self.env.keys()) if self.env else [],
                **self.metadata,  # Include user metadata
            },
        )

    def __repr__(self) -> str:
        return f"BashNode(id={self.id!r}, cwd={self.cwd!r})"
