"""BashNode - stateless node for running bash commands.

BashNode executes bash commands via subprocess and returns JSON results.
Each execution spawns a fresh subprocess - no state is maintained between calls.

Key features:
- Returns structured JSON with stdout/stderr/exit_code
- Errors are caught and returned in JSON (never raises)
- Supports interrupt() to send SIGINT (Ctrl+C) to running process
- Working directory and environment configured at node creation
- Auto-registers with session on creation
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.context import ExecutionContext
from nerve.core.nodes.run_logging import log_complete, log_error, log_start, log_warning

if TYPE_CHECKING:
    from nerve.core.session.session import Session


@dataclass
class BashNode:
    """Stateless node that runs bash commands and returns JSON results.

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
    - Auto-registers with session on creation

    Args:
        id: Unique identifier for this node.
        session: Session to register this node with.
        cwd: Working directory for command execution.
        env: Environment variables for command execution.
        timeout: Default timeout for commands (seconds).

    Example:
        >>> session = Session("my-session")
        >>> node = BashNode(id="runner", session=session, cwd="/tmp", timeout=30.0)
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

    # Required fields (no defaults)
    id: str
    session: Session

    # Optional fields (with defaults)
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)

    # Internal fields (not in __init__)
    persistent: bool = field(default=False, init=False)
    state: NodeState = field(default=NodeState.READY, init=False)
    _current_proc: asyncio.subprocess.Process | None = field(default=None, init=False, repr=False)
    _proc_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate and register with session."""
        from nerve.core.validation import validate_name

        # Validate node ID
        validate_name(self.id, "node")

        # Check for duplicates
        if self.id in self.session.nodes:
            raise ValueError(f"Node '{self.id}' already exists in session '{self.session.name}'")

        # Auto-register with session
        self.session.nodes[self.id] = self

        # Log node registration
        if self.session.session_logger:
            self.session.session_logger.log_node_lifecycle(
                self.id, "BashNode", persistent=self.persistent
            )

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
        from nerve.core.nodes.session_logging import get_execution_logger

        # Check if node is stopped
        if self.state == NodeState.STOPPED:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "command": str(context.input) if context.input else "",
                "error": "Node is stopped",
                "interrupted": False,
            }

        # Get logger and exec_id (fallback to context.exec_id for consistency)
        log_ctx = get_execution_logger(self.id, context, self.session)
        exec_id = log_ctx.exec_id or context.exec_id

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

        start_mono = time.monotonic()

        try:
            # Get command from context
            command = str(context.input) if context.input else ""
            result["command"] = command

            if not command:
                result["error"] = "No command provided in context.input"
                return result

            # Log command start
            log_start(
                log_ctx.logger,
                self.id,
                "bash_start",
                exec_id=exec_id,
                command=command,
                cwd=self.cwd,
                timeout=context.timeout or self.timeout,
            )

            # Build environment
            env = None
            if self.env:
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
                result["stdout"] = stdout_bytes.decode("utf-8", errors="replace")
                result["stderr"] = stderr_bytes.decode("utf-8", errors="replace")
                result["exit_code"] = proc.returncode

                # Handle exit code
                if proc.returncode is None:
                    # Should not happen after communicate(), but handle explicitly
                    result["error"] = "Process ended without exit code"
                elif proc.returncode in (-2, 130):
                    # Interrupted (SIGINT exit codes)
                    result["interrupted"] = True
                    result["error"] = "Command interrupted (Ctrl+C)"
                    duration = time.monotonic() - start_mono
                    log_warning(
                        log_ctx.logger,
                        self.id,
                        "bash_interrupted",
                        exec_id=exec_id,
                        exit_code=proc.returncode,
                        duration_s=f"{duration:.1f}",
                    )
                elif proc.returncode == 0:
                    result["success"] = True
                    duration = time.monotonic() - start_mono
                    log_complete(
                        log_ctx.logger,
                        self.id,
                        "bash_complete",
                        duration,
                        exec_id=exec_id,
                        exit_code=0,
                    )
                else:
                    error_msg = f"Command exited with code {proc.returncode}"
                    result["error"] = error_msg
                    duration = time.monotonic() - start_mono
                    log_error(
                        log_ctx.logger,
                        self.id,
                        "bash_failed",
                        error_msg,
                        exec_id=exec_id,
                        exit_code=proc.returncode,
                        duration_s=f"{duration:.1f}",
                    )

            except TimeoutError:
                # Kill the process on timeout
                proc.kill()
                await proc.wait()
                error_msg = f"Command timed out after {timeout}s"
                result["error"] = error_msg
                duration = time.monotonic() - start_mono
                log_error(
                    log_ctx.logger,
                    self.id,
                    "bash_timeout",
                    error_msg,
                    exec_id=exec_id,
                    timeout=timeout,
                    duration_s=f"{duration:.1f}",
                )

            finally:
                # Clear current process reference (critical for interrupt safety)
                async with self._proc_lock:
                    self._current_proc = None

        except Exception as e:
            # Catch any other exceptions (file not found, permission denied, etc.)
            result["error"] = f"{type(e).__name__}: {str(e)}"
            duration = time.monotonic() - start_mono
            log_error(
                log_ctx.logger,
                self.id,
                "bash_error",
                e,
                exec_id=exec_id,
                duration_s=f"{duration:.1f}",
            )

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

    async def stop(self) -> None:
        """Stop the node and mark as unusable.

        Sets state to STOPPED. Future execute() calls will return an error.
        Does not unregister from session (that's Session.delete_node's job).
        """
        self.state = NodeState.STOPPED

    def to_info(self) -> NodeInfo:
        """Get node information.

        Returns:
            NodeInfo for this node.
        """
        return NodeInfo(
            id=self.id,
            node_type="bash",
            state=self.state,
            persistent=self.persistent,
            metadata={
                "cwd": self.cwd,
                "timeout": self.timeout,
                "env_vars": list(self.env.keys()) if self.env else [],
                **self.metadata,  # Include user metadata
            },
        )

    # -------------------------------------------------------------------------
    # Tool-capable interface (opt-in for LLMChatNode tool use)
    # -------------------------------------------------------------------------

    def tool_description(self) -> str:
        """Return description of this tool for LLM.

        Returns:
            Human-readable description of what this tool does.
        """
        return "Execute bash/shell commands and return stdout/stderr"

    def tool_parameters(self) -> dict[str, Any]:
        """Return JSON Schema for tool parameters.

        Returns:
            JSON Schema dict defining accepted parameters.
        """
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                },
            },
            "required": ["command"],
        }

    def tool_input(self, args: dict[str, Any]) -> str:
        """Convert tool arguments to context.input value.

        Args:
            args: Arguments from LLM's tool call.

        Returns:
            Command string to execute.
        """
        command = args.get("command", "")
        return str(command) if command else ""

    def tool_result(self, result: dict[str, Any]) -> str:
        """Convert execute() result to string for LLM.

        Args:
            result: Result dict from execute().

        Returns:
            Formatted string with command output or error.
        """
        if result.get("success"):
            stdout = result.get("stdout", "")
            return stdout if stdout else "(no output)"

        # Error case - include stderr and exit code
        stderr = result.get("stderr", "")
        error = result.get("error", "")
        exit_code = result.get("exit_code", "?")
        error_msg = stderr or error or "Command failed"
        return f"Error (exit {exit_code}): {error_msg}"

    def __repr__(self) -> str:
        return f"BashNode(id={self.id!r}, cwd={self.cwd!r})"
