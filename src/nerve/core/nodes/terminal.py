"""Terminal nodes - PTY and WezTerm based terminal interactions.

Terminal nodes implement the Node protocol for terminal-based interactions.
They use Backends directly (not wrapping Channels) for direct control.

Key characteristics:
- PTYNode: Owns process via pseudo-terminal, continuous buffer
- WezTermNode: Attaches to WezTerm panes, always-fresh buffer query
- ClaudeWezTermNode: WezTerm optimized for Claude CLI

All terminal nodes:
- Are persistent (maintain state across executions)
- Support execute() and execute_stream() methods
- Have history logging capability
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.core.channels.history import HISTORY_BUFFER_LINES, HistoryWriter
from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.parsers import get_parser
from nerve.core.pty import BackendConfig
from nerve.core.pty.pty_backend import PTYBackend
from nerve.core.pty.wezterm_backend import WezTermBackend
from nerve.core.types import ParsedResponse, ParserType

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext


@dataclass
class PTYNode:
    """PTY-based terminal node.

    BUFFER SEMANTICS: Continuous accumulation.
    - Buffer grows continuously as output is received
    - Use buffer_start position for incremental parsing
    - Background reader task captures output
    - Polling interval: 0.3 seconds for ready detection

    The node owns the process and maintains its lifecycle.
    Input comes from ExecutionContext.input (string).

    Example:
        >>> node = await PTYNode.create("shell", command="bash")
        >>> context = ExecutionContext(session=session, input="ls -la")
        >>> response = await node.execute(context)
        >>> print(response.raw)
        >>> await node.stop()
    """

    id: str
    backend: PTYBackend
    command: str | None = None
    state: NodeState = NodeState.STARTING
    persistent: bool = field(default=True, init=False)
    _default_parser: ParserType = ParserType.NONE
    _last_input: str = field(default="", repr=False)
    _ready_timeout: float = field(default=60.0, repr=False)
    _response_timeout: float = field(default=1800.0, repr=False)
    _reader_task: asyncio.Task | None = field(default=None, repr=False)
    _history_writer: HistoryWriter | None = field(default=None, repr=False)

    @classmethod
    async def create(
        cls,
        node_id: str,
        command: list[str] | str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        history_writer: HistoryWriter | None = None,
        default_parser: ParserType = ParserType.NONE,
    ) -> PTYNode:
        """Create and start a new PTY node.

        Args:
            node_id: Unique node identifier (required).
            command: Command to run (e.g., "claude" or ["bash"]).
                     If not provided, starts a shell.
            cwd: Working directory.
            env: Additional environment variables.
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            history_writer: Optional history writer for logging operations.
            default_parser: Default parser for execute() calls.

        Returns:
            A ready PTYNode.

        Raises:
            ValueError: If node_id is not provided.
        """
        if not node_id:
            raise ValueError("node_id is required")

        # Normalize command
        if command is None:
            command_list = ["bash"]
            command_str = "bash"
        elif isinstance(command, str):
            command_str = command
            command_list = command.split()
        else:
            command_list = command
            command_str = " ".join(command)

        config = BackendConfig(cwd=cwd, env=env or {})
        backend = PTYBackend(command_list, config)

        await backend.start()

        node = cls(
            id=node_id,
            backend=backend,
            command=command_str,
            state=NodeState.READY,
            _default_parser=default_parser,
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
            _history_writer=history_writer,
        )

        # Start background reader
        node._start_reader()

        # Give the shell a moment to start
        await asyncio.sleep(0.5)

        return node

    @property
    def buffer(self) -> str:
        """Current output buffer (accumulated stream)."""
        return self.backend.buffer

    async def execute(self, context: ExecutionContext) -> ParsedResponse:
        """Execute by sending input and waiting for response.

        Args:
            context: Execution context with input string.

        Returns:
            Parsed response.

        Raises:
            TimeoutError: If response times out.
            RuntimeError: If node is stopped.
        """
        if self.state == NodeState.STOPPED:
            raise RuntimeError("Node is stopped")

        input_str = str(context.input) if context.input is not None else ""
        self._last_input = input_str

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        # Resolve parser
        parser_type = context.parser or self._default_parser
        timeout = context.timeout or self._response_timeout

        is_claude = parser_type == ParserType.CLAUDE
        parser_instance = get_parser(parser_type)

        # Mark buffer position before sending
        buffer_start = len(self.backend.buffer)

        # Send input
        if is_claude:
            # PTY + Claude: Handle INSERT mode
            await self.backend.write("i")
            await asyncio.sleep(0.2)
            await self.backend.write(input_str)
            await asyncio.sleep(0.5)
            await self.backend.write("\x1b")  # Escape
            await asyncio.sleep(0.5)
            await self.backend.write("\r")  # Enter
        else:
            await self.backend.write(input_str)
            await asyncio.sleep(0.1)
            await self.backend.write("\n")

        self.state = NodeState.BUSY

        # Wait for response
        await self._wait_for_ready(
            timeout=timeout,
            parser_type=parser_type,
            buffer_start=buffer_start,
        )

        # Parse only the NEW output
        new_output = self.backend.buffer[buffer_start:]
        result = parser_instance.parse(new_output)

        # History: log send
        if self._history_writer and self._history_writer.enabled:
            response_data = {
                "sections": [
                    {"type": s.type, "content": s.content, "metadata": s.metadata}
                    for s in result.sections
                ],
                "tokens": result.tokens,
                "is_complete": result.is_complete,
                "is_ready": result.is_ready,
            }
            self._history_writer.log_send(
                input=input_str,
                response=response_data,
                preceding_buffer_seq=None,
                ts_start=ts_start,
            )

        return result

    async def execute_stream(
        self, context: ExecutionContext
    ) -> AsyncIterator[str]:
        """Execute and stream output chunks.

        Args:
            context: Execution context with input string.

        Yields:
            Output chunks as they arrive.
        """
        if self.state == NodeState.STOPPED:
            raise RuntimeError("Node is stopped")

        input_str = str(context.input) if context.input is not None else ""
        self._last_input = input_str

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        parser_type = context.parser or self._default_parser
        parser_instance = get_parser(parser_type)
        is_claude = parser_type == ParserType.CLAUDE

        # Send input
        if is_claude:
            # Claude CLI has vim-like INSERT mode
            await self.backend.write("i")  # Enter INSERT mode
            await asyncio.sleep(0.2)
            await self.backend.write(input_str)
            await asyncio.sleep(0.3)
            await self.backend.write("\x1b")  # Escape to exit INSERT mode
            await asyncio.sleep(0.3)
            await self.backend.write("\r")  # Submit
        else:
            await self.backend.write(input_str + "\n")

        self.state = NodeState.BUSY

        async for chunk in self.backend.read_stream():
            yield chunk

            if parser_instance.is_ready(self.backend.buffer):
                self.state = NodeState.READY
                break

        # History: log streaming operation
        if self._history_writer and self._history_writer.enabled:
            final_buffer = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_send_stream(
                input=input_str,
                final_buffer=final_buffer,
                parser=parser_type.value,
                preceding_buffer_seq=None,
                ts_start=ts_start,
            )

    async def send(
        self,
        text: str,
        parser: ParserType | None = None,
        timeout: float | None = None,
    ) -> ParsedResponse:
        """Convenience method to send input and get response.

        Args:
            text: Input text to send.
            parser: Parser type (defaults to node's default).
            timeout: Response timeout (defaults to node's default).

        Returns:
            Parsed response.
        """
        from nerve.core.nodes.context import ExecutionContext

        context = ExecutionContext(input=text, parser=parser, timeout=timeout)
        return await self.execute(context)

    async def send_stream(
        self,
        text: str,
        parser: ParserType | None = None,
    ) -> AsyncIterator[str]:
        """Convenience method to send input and stream response.

        Args:
            text: Input text to send.
            parser: Parser type (defaults to node's default).

        Yields:
            Output chunks as they arrive.
        """
        from nerve.core.nodes.context import ExecutionContext

        context = ExecutionContext(input=text, parser=parser)
        async for chunk in self.execute_stream(context):
            yield chunk

    async def write(self, data: str) -> None:
        """Write raw data to the terminal (low-level).

        Args:
            data: Raw data to write.
        """
        await self.backend.write(data)

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_write(data)
            await asyncio.sleep(0.1)
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def run(self, command: str) -> None:
        """Start a command (fire and forget).

        Writes command to terminal without waiting for response.
        Used for starting long-running processes like claude, python, etc.

        Args:
            command: Command to start.
        """
        await self.backend.write(command + "\n")

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_run(command)

    async def read(self) -> str:
        """Read current output buffer.

        Returns:
            Current buffer contents.
        """
        return self.backend.buffer

    def read_tail(self, lines: int = 50) -> str:
        """Read last N lines from buffer.

        Args:
            lines: Number of lines to read.

        Returns:
            Last N lines of buffer.
        """
        return self.backend.read_tail(lines)

    def clear_buffer(self) -> None:
        """Clear the accumulated buffer."""
        self.backend.clear_buffer()

    async def interrupt(self) -> None:
        """Send interrupt signal (Ctrl+C)."""
        await self.backend.write("\x03")

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_interrupt()

    async def start(self) -> None:
        """Start the node (lifecycle method).

        Called by Session.start() for persistent nodes.
        PTYNode is already started via create(), so this is a no-op.
        """
        pass  # Already started in create()

    async def stop(self) -> None:
        """Stop the node and release resources.

        Called by Session.stop() for persistent nodes.
        """
        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_close()
            self._history_writer.close()

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        await self.backend.stop()
        self.state = NodeState.STOPPED

    async def reset(self) -> None:
        """Reset state while keeping resources running.

        Clears the buffer and internal tracking state without stopping
        the underlying process. Useful for reusing the node for fresh
        interactions.
        """
        self.backend.buffer = ""
        self._last_input = ""

    def _start_reader(self) -> None:
        """Start background task to continuously read and buffer output."""

        async def reader_loop():
            try:
                async for _chunk in self.backend.read_stream():
                    pass  # Output accumulated in backend.buffer
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        self._reader_task = asyncio.create_task(reader_loop())

    async def _wait_for_ready(
        self,
        timeout: float,
        parser_type: ParserType = ParserType.NONE,
        buffer_start: int = 0,
    ) -> None:
        """Wait for terminal to be ready for input."""
        parser = get_parser(parser_type)
        start = asyncio.get_event_loop().time()

        if parser_type == ParserType.CLAUDE:
            await self._wait_for_processing_start(timeout=10.0, buffer_start=buffer_start)

        ready_count = 0
        consecutive_required = 2

        while asyncio.get_event_loop().time() - start < timeout:
            check_content = self.backend.buffer[buffer_start:]

            if parser.is_ready(check_content):
                ready_count += 1
                if ready_count >= consecutive_required:
                    await asyncio.sleep(0.5)
                    self.state = NodeState.READY
                    return
            else:
                ready_count = 0

            await asyncio.sleep(0.3)

        raise TimeoutError(f"Terminal did not become ready within {timeout}s")

    async def _wait_for_processing_start(
        self,
        timeout: float = 10.0,
        buffer_start: int = 0,
    ) -> bool:
        """Wait for Claude to start processing."""
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            check_content = self.backend.buffer[buffer_start:]

            if self._is_processing(check_content):
                return True

            await asyncio.sleep(0.1)

        return False

    def _is_processing(self, content: str) -> bool:
        """Check if Claude is currently processing."""
        content_lower = content.lower()
        return "esc to interrupt" in content_lower or "esc to cancel" in content_lower

    def to_info(self) -> NodeInfo:
        """Get node information."""
        return NodeInfo(
            id=self.id,
            node_type="pty",
            state=self.state,
            persistent=self.persistent,
            metadata={
                "command": self.command,
                "last_input": self._last_input,
            },
        )

    def __repr__(self) -> str:
        return f"PTYNode(id={self.id!r}, state={self.state.name})"


@dataclass
class WezTermNode:
    """WezTerm-based terminal node.

    BUFFER SEMANTICS: Always-fresh query.
    - WezTerm maintains pane content internally
    - Every buffer read queries WezTerm directly
    - No background reader needed
    - Polling interval: 2.0 seconds for ready detection

    Example:
        >>> node = await WezTermNode.create("claude", command="claude")
        >>> context = ExecutionContext(session=session, input="Hello!")
        >>> response = await node.execute(context)
        >>> print(response.raw)
    """

    id: str
    backend: WezTermBackend
    pane_id: str | None = None
    command: str | None = None
    state: NodeState = NodeState.STARTING
    persistent: bool = field(default=True, init=False)
    _default_parser: ParserType = ParserType.NONE
    _last_input: str = field(default="", repr=False)
    _ready_timeout: float = field(default=60.0, repr=False)
    _response_timeout: float = field(default=1800.0, repr=False)
    _history_writer: HistoryWriter | None = field(default=None, repr=False)

    @classmethod
    async def create(
        cls,
        node_id: str,
        command: list[str] | str | None = None,
        cwd: str | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        history_writer: HistoryWriter | None = None,
        default_parser: ParserType = ParserType.NONE,
    ) -> WezTermNode:
        """Create a new WezTerm node by spawning a pane.

        Args:
            node_id: Unique node identifier (required).
            command: Command to run (e.g., "claude" or ["bash"]).
            cwd: Working directory.
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            history_writer: Optional history writer for logging operations.
            default_parser: Default parser for execute() calls.

        Returns:
            A ready WezTermNode.
        """
        if not node_id:
            raise ValueError("node_id is required")

        # Normalize command
        if command is None:
            command_list = []
            command_str = None
        elif isinstance(command, str):
            command_str = command
            command_list = command.split()
        else:
            command_list = command
            command_str = " ".join(command)

        config = BackendConfig(cwd=cwd)
        backend = WezTermBackend(command_list, config)

        await backend.start()

        node = cls(
            id=node_id,
            backend=backend,
            pane_id=backend.pane_id,
            command=command_str,
            state=NodeState.READY,
            _default_parser=default_parser,
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
            _history_writer=history_writer,
        )

        await asyncio.sleep(0.5)

        return node

    @classmethod
    async def attach(
        cls,
        node_id: str,
        pane_id: str,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        history_writer: HistoryWriter | None = None,
        default_parser: ParserType = ParserType.NONE,
    ) -> WezTermNode:
        """Attach to an existing WezTerm pane.

        Args:
            node_id: Unique node identifier (required).
            pane_id: WezTerm pane ID to attach to.
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            history_writer: Optional history writer for logging operations.
            default_parser: Default parser for execute() calls.

        Returns:
            A WezTermNode attached to the pane.
        """
        if not node_id:
            raise ValueError("node_id is required")

        config = BackendConfig()
        backend = WezTermBackend([], config, pane_id=pane_id)

        await backend.attach(pane_id)

        return cls(
            id=node_id,
            backend=backend,
            pane_id=pane_id,
            state=NodeState.READY,
            _default_parser=default_parser,
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
            _history_writer=history_writer,
        )

    @property
    def buffer(self) -> str:
        """Current pane content (always fresh from WezTerm)."""
        return self.backend.buffer

    async def execute(self, context: ExecutionContext) -> ParsedResponse:
        """Execute by sending input and waiting for response.

        Args:
            context: Execution context with input string.

        Returns:
            Parsed response.
        """
        if self.state == NodeState.STOPPED:
            raise RuntimeError("Node is stopped")

        input_str = str(context.input) if context.input is not None else ""
        self._last_input = input_str

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        parser_type = context.parser or self._default_parser
        timeout = context.timeout or self._response_timeout

        is_claude = parser_type == ParserType.CLAUDE
        parser_instance = get_parser(parser_type)

        # Send input
        if is_claude:
            # Claude CLI has vim-like INSERT mode
            await self.backend.write("i")  # Enter INSERT mode
            await asyncio.sleep(0.2)
            await self.backend.write(input_str)
            await asyncio.sleep(0.3)
            await self.backend.write("\x1b")  # Escape to exit INSERT mode
            await asyncio.sleep(0.3)
            await self.backend.write("\r")  # Submit
        else:
            await self.backend.write(input_str)
            await asyncio.sleep(0.1)
            await self.backend.write("\n")

        self.state = NodeState.BUSY

        # Wait for response
        await self._wait_for_ready(timeout=timeout, parser_type=parser_type)

        await asyncio.sleep(0.5)

        buffer = self.backend.buffer
        result = parser_instance.parse(buffer)

        # History: log send
        if self._history_writer and self._history_writer.enabled:
            response_data = {
                "sections": [
                    {"type": s.type, "content": s.content, "metadata": s.metadata}
                    for s in result.sections
                ],
                "tokens": result.tokens,
                "is_complete": result.is_complete,
                "is_ready": result.is_ready,
            }
            self._history_writer.log_send(
                input=input_str,
                response=response_data,
                preceding_buffer_seq=None,
                ts_start=ts_start,
            )

        return result

    async def execute_stream(
        self, context: ExecutionContext
    ) -> AsyncIterator[str]:
        """Execute and stream output chunks.

        Args:
            context: Execution context with input string.

        Yields:
            Output chunks as they arrive.
        """
        if self.state == NodeState.STOPPED:
            raise RuntimeError("Node is stopped")

        input_str = str(context.input) if context.input is not None else ""
        self._last_input = input_str

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        parser_type = context.parser or self._default_parser
        parser_instance = get_parser(parser_type)
        is_claude = parser_type == ParserType.CLAUDE

        # Send input
        if is_claude:
            # Claude CLI has vim-like INSERT mode
            await self.backend.write("i")  # Enter INSERT mode
            await asyncio.sleep(0.2)
            await self.backend.write(input_str)
            await asyncio.sleep(0.3)
            await self.backend.write("\x1b")  # Escape to exit INSERT mode
            await asyncio.sleep(0.3)
            await self.backend.write("\r")  # Submit
        else:
            await self.backend.write(input_str + "\n")

        self.state = NodeState.BUSY

        async for chunk in self.backend.read_stream():
            yield chunk

            if parser_instance.is_ready(self.backend.buffer):
                self.state = NodeState.READY
                break

        # History: log streaming operation
        if self._history_writer and self._history_writer.enabled:
            final_buffer = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_send_stream(
                input=input_str,
                final_buffer=final_buffer,
                parser=parser_type.value,
                preceding_buffer_seq=None,
                ts_start=ts_start,
            )

    async def send(
        self,
        text: str,
        parser: ParserType | None = None,
        timeout: float | None = None,
    ) -> ParsedResponse:
        """Convenience method to send input and get response.

        Args:
            text: Input text to send.
            parser: Parser type (defaults to node's default).
            timeout: Response timeout (defaults to node's default).

        Returns:
            Parsed response.
        """
        from nerve.core.nodes.context import ExecutionContext

        context = ExecutionContext(input=text, parser=parser, timeout=timeout)
        return await self.execute(context)

    async def send_stream(
        self,
        text: str,
        parser: ParserType | None = None,
    ) -> AsyncIterator[str]:
        """Convenience method to send input and stream response.

        Args:
            text: Input text to send.
            parser: Parser type (defaults to node's default).

        Yields:
            Output chunks as they arrive.
        """
        from nerve.core.nodes.context import ExecutionContext

        context = ExecutionContext(input=text, parser=parser)
        async for chunk in self.execute_stream(context):
            yield chunk

    async def write(self, data: str) -> None:
        """Write raw data to the terminal."""
        await self.backend.write(data)

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_write(data)
            await asyncio.sleep(0.1)
            buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def run(self, command: str) -> None:
        """Start a command (fire and forget).

        Writes command to terminal without waiting for response.
        Used for starting long-running processes like claude, python, etc.

        Args:
            command: Command to start.
        """
        await self.backend.write(command + "\n")

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_run(command)

    async def read(self) -> str:
        """Read current pane content (fresh from WezTerm)."""
        return self.backend.buffer

    def read_tail(self, lines: int = 50) -> str:
        """Read last N lines from pane."""
        return self.backend.read_tail(lines)

    def clear_buffer(self) -> None:
        """Clear the buffer."""
        self.backend.clear_buffer()

    async def interrupt(self) -> None:
        """Send interrupt signal (Ctrl+C)."""
        await self.backend.write("\x03")

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_interrupt()

    async def focus(self) -> None:
        """Focus (activate) the WezTerm pane."""
        await self.backend.focus()

    async def get_pane_info(self) -> dict | None:
        """Get information about the pane."""
        return await self.backend.get_pane_info()

    async def start(self) -> None:
        """Start the node (lifecycle method)."""
        pass  # Already started in create()

    async def stop(self) -> None:
        """Stop the node and release resources."""
        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_close()
            self._history_writer.close()

        await self.backend.stop()
        self.state = NodeState.STOPPED

    async def reset(self) -> None:
        """Reset state while keeping resources running.

        Clears the buffer without stopping the WezTerm pane.
        """
        self.backend.clear_buffer()
        self._last_input = ""

    async def _wait_for_ready(
        self,
        timeout: float,
        parser_type: ParserType = ParserType.NONE,
    ) -> None:
        """Wait for terminal to be ready for input."""
        parser = get_parser(parser_type)
        start = asyncio.get_event_loop().time()

        ready_count = 0
        consecutive_required = 2

        while asyncio.get_event_loop().time() - start < timeout:
            check_content = self.backend.buffer

            if parser.is_ready(check_content):
                ready_count += 1
                if ready_count >= consecutive_required:
                    await asyncio.sleep(0.3)
                    self.state = NodeState.READY
                    return
            else:
                ready_count = 0

            await asyncio.sleep(2.0)

        raise TimeoutError(f"Terminal did not become ready within {timeout}s")

    def to_info(self) -> NodeInfo:
        """Get node information."""
        return NodeInfo(
            id=self.id,
            node_type="wezterm",
            state=self.state,
            persistent=self.persistent,
            metadata={
                "pane_id": self.pane_id,
                "command": self.command,
                "last_input": self._last_input,
            },
        )

    def __repr__(self) -> str:
        return f"WezTermNode(id={self.id!r}, pane_id={self.pane_id!r}, state={self.state.name})"


@dataclass
class ClaudeWezTermNode:
    """WezTerm node optimized for Claude CLI.

    A convenience wrapper that:
    - Validates command contains "claude"
    - Uses Claude parser by default
    - Delegates everything else to inner WezTermNode

    HISTORY OWNERSHIP: This wrapper owns the history writer.
    The inner WezTermNode has NO history writer.

    Example:
        >>> node = await ClaudeWezTermNode.create(
        ...     "my-claude",
        ...     command="cd ~/project && claude --dangerously-skip-permissions"
        ... )
        >>> context = ExecutionContext(session=session, input="What is 2+2?")
        >>> response = await node.execute(context)
        >>> print(response.sections)
    """

    id: str
    _inner: WezTermNode
    _command: str = ""
    _default_parser: ParserType = ParserType.CLAUDE
    _last_input: str = ""
    persistent: bool = field(default=True, init=False)
    state: NodeState = field(default=NodeState.READY, init=False)
    _history_writer: HistoryWriter | None = field(default=None, repr=False)

    @classmethod
    async def create(
        cls,
        node_id: str,
        command: str,
        cwd: str | None = None,
        parser: ParserType = ParserType.CLAUDE,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        history_writer: HistoryWriter | None = None,
    ) -> ClaudeWezTermNode:
        """Create a new ClaudeWezTerm node.

        Args:
            node_id: Unique node identifier.
            command: Command to run (MUST contain "claude").
            cwd: Working directory.
            parser: Default parser (defaults to CLAUDE).
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            history_writer: Optional history writer for logging operations.

        Returns:
            A ready ClaudeWezTermNode.

        Raises:
            ValueError: If command doesn't contain "claude".
        """
        if not node_id:
            raise ValueError("node_id is required")

        if "claude" not in command.lower():
            raise ValueError(f"Command must contain 'claude'. Got: {command}")

        # Create inner node WITHOUT history writer - wrapper owns history
        inner = await WezTermNode.create(
            node_id=node_id,
            command=None,  # Use default shell
            cwd=cwd,
            ready_timeout=ready_timeout,
            response_timeout=response_timeout,
            history_writer=None,  # Inner has NO history
            default_parser=parser,
        )

        await asyncio.sleep(0.5)

        # Type the command into the shell
        await inner.backend.write(command)
        await asyncio.sleep(0.1)
        await inner.backend.write("\r")

        wrapper = cls(
            id=node_id,
            _inner=inner,
            _command=command,
            _default_parser=parser,
            _history_writer=history_writer,
        )

        # History: log the initial run command
        if history_writer and history_writer.enabled:
            history_writer.log_run(command)
            await asyncio.sleep(2)
            buffer_content = inner.read_tail(HISTORY_BUFFER_LINES)
            history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)
        else:
            await asyncio.sleep(2)

        return wrapper

    @property
    def pane_id(self) -> str | None:
        """WezTerm pane ID."""
        return self._inner.pane_id

    @property
    def command(self) -> str:
        """Command that was run."""
        return self._command

    @property
    def buffer(self) -> str:
        """Current pane content."""
        return self._inner.buffer

    async def execute(self, context: ExecutionContext) -> ParsedResponse:
        """Execute by sending input and waiting for response.

        Uses Claude parser by default.

        Args:
            context: Execution context with input string.

        Returns:
            Parsed response.
        """
        self._last_input = str(context.input) if context.input else ""

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        # Override parser if not set
        parser_type = context.parser or self._default_parser
        exec_context = context.with_parser(parser_type)

        # Delegate to inner
        result = await self._inner.execute(exec_context)

        # History: log send
        if self._history_writer and self._history_writer.enabled:
            response_data = {
                "sections": [
                    {"type": s.type, "content": s.content, "metadata": s.metadata}
                    for s in result.sections
                ],
                "tokens": result.tokens,
                "is_complete": result.is_complete,
                "is_ready": result.is_ready,
            }
            self._history_writer.log_send(
                input=self._last_input,
                response=response_data,
                preceding_buffer_seq=None,
                ts_start=ts_start,
            )

        return result

    async def execute_stream(
        self, context: ExecutionContext
    ) -> AsyncIterator[str]:
        """Execute and stream output chunks.

        Args:
            context: Execution context with input string.

        Yields:
            Output chunks as they arrive.
        """
        self._last_input = str(context.input) if context.input else ""

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        parser_type = context.parser or self._default_parser
        exec_context = context.with_parser(parser_type)

        async for chunk in self._inner.execute_stream(exec_context):
            yield chunk

        # History: log streaming operation
        if self._history_writer and self._history_writer.enabled:
            final_buffer = self._inner.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_send_stream(
                input=self._last_input,
                final_buffer=final_buffer,
                parser=parser_type.value,
                preceding_buffer_seq=None,
                ts_start=ts_start,
            )

    async def send(
        self,
        text: str,
        parser: ParserType | None = None,
        timeout: float | None = None,
    ) -> ParsedResponse:
        """Convenience method to send input and get response.

        Args:
            text: Input text to send.
            parser: Parser type (defaults to node's default).
            timeout: Response timeout (defaults to node's default).

        Returns:
            Parsed response.
        """
        from nerve.core.nodes.context import ExecutionContext

        context = ExecutionContext(input=text, parser=parser, timeout=timeout)
        return await self.execute(context)

    async def send_stream(
        self,
        text: str,
        parser: ParserType | None = None,
    ) -> AsyncIterator[str]:
        """Convenience method to send input and stream response.

        Args:
            text: Input text to send.
            parser: Parser type (defaults to node's default).

        Yields:
            Output chunks as they arrive.
        """
        from nerve.core.nodes.context import ExecutionContext

        context = ExecutionContext(input=text, parser=parser)
        async for chunk in self.execute_stream(context):
            yield chunk

    async def write(self, data: str) -> None:
        """Write raw data."""
        await self._inner.backend.write(data)

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_write(data)
            await asyncio.sleep(0.1)
            buffer_content = self._inner.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def run(self, command: str) -> None:
        """Start a command (fire and forget).

        Writes command to terminal without waiting for response.
        Used for starting long-running processes like claude, python, etc.

        Args:
            command: Command to start.
        """
        await self._inner.backend.write(command + "\n")

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_run(command)

    async def read(self) -> str:
        """Read current pane content."""
        return await self._inner.read()

    def read_tail(self, lines: int = 50) -> str:
        """Read last N lines."""
        return self._inner.read_tail(lines)

    def clear_buffer(self) -> None:
        """Clear the buffer."""
        self._inner.clear_buffer()

    async def interrupt(self) -> None:
        """Send interrupt (Ctrl+C)."""
        await self._inner.backend.write("\x03")

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_interrupt()

    async def focus(self) -> None:
        """Focus the pane."""
        await self._inner.focus()

    async def start(self) -> None:
        """Start the node (lifecycle method)."""
        pass  # Already started in create()

    async def stop(self) -> None:
        """Stop the node and release resources."""
        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_close()
            self._history_writer.close()

        await self._inner.stop()
        self.state = NodeState.STOPPED

    async def reset(self) -> None:
        """Reset state while keeping resources running.

        Clears the buffer and state for the inner WezTerm node.
        """
        await self._inner.reset()
        self._last_input = ""

    def to_info(self) -> NodeInfo:
        """Get node information."""
        return NodeInfo(
            id=self.id,
            node_type="claude-wezterm",
            state=self.state,
            persistent=self.persistent,
            metadata={
                "pane_id": self.pane_id,
                "command": self.command,
                "default_parser": self._default_parser.value,
                "last_input": self._last_input,
            },
        )

    def __repr__(self) -> str:
        return f"ClaudeWezTermNode(id={self.id!r}, pane_id={self.pane_id!r}, state={self.state.name})"
