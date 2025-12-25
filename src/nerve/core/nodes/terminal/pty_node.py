"""PTY-based terminal node.

This module provides PTYNode for pseudo-terminal based terminal interactions.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.history import HISTORY_BUFFER_LINES, HistoryWriter
from nerve.core.parsers import get_parser
from nerve.core.pty import BackendConfig
from nerve.core.pty.pty_backend import PTYBackend
from nerve.core.types import ParsedResponse, ParserType

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session


@dataclass
class PTYNode:
    """PTY-based terminal node.

    IMPORTANT: Cannot be instantiated directly. Use PTYNode.create() instead.

    BUFFER SEMANTICS: Continuous accumulation.
    - Buffer grows continuously as output is received
    - Use buffer_start position for incremental parsing
    - Background reader task captures output
    - Polling interval: 0.3 seconds for ready detection

    The node owns the process and maintains its lifecycle.
    Input comes from ExecutionContext.input (string).

    Example:
        >>> session = Session("my-session")
        >>> node = await PTYNode.create(
        ...     id="shell",
        ...     session=session,
        ...     command="bash"
        ... )
        >>> context = ExecutionContext(session=session, input="ls -la")
        >>> response = await node.execute(context)
        >>> print(response.raw)
        >>> await node.stop()
    """

    # Required fields (set during .create())
    id: str
    session: Session
    backend: PTYBackend
    command: str | None = None
    state: NodeState = NodeState.STARTING

    # Internal fields (not in __init__)
    persistent: bool = field(default=True, init=False)
    _default_parser: ParserType = field(default=ParserType.NONE, init=False)
    _last_input: str = field(default="", init=False, repr=False)
    _ready_timeout: float = field(default=60.0, init=False, repr=False)
    _response_timeout: float = field(default=1800.0, init=False, repr=False)
    _reader_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _history_writer: HistoryWriter | None = field(default=None, init=False, repr=False)
    _created_via_create: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        """Prevent direct instantiation."""
        if not self._created_via_create:
            raise TypeError(
                f"Cannot instantiate {self.__class__.__name__} directly. "
                f"Use: await {self.__class__.__name__}.create(id, session, ...)"
            )

    @classmethod
    async def create(
        cls,
        id: str,
        session: Session,
        command: list[str] | str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        history: bool | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        default_parser: ParserType | None = None,
    ) -> PTYNode:
        """Create a new PTY node and register with session.

        This is the ONLY way to create a PTYNode. Direct instantiation via
        __init__ will raise TypeError.

        Args:
            id: Unique identifier for the node.
            session: Session to register this node with.
            command: Command to run (e.g., "bash", ["bash", "-i"]).
            cwd: Working directory.
            env: Additional environment variables.
            history: Enable history logging (default: session.history_enabled).
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            default_parser: Default parser for execute() calls.

        Returns:
            A ready PTYNode, registered in the session.

        Raises:
            ValueError: If node_id already exists or is invalid.
            TypeError: If called via __init__ instead of create().

        Example:
            >>> session = Session("my-session")
            >>> node = await PTYNode.create(
            ...     id="shell",
            ...     session=session,
            ...     command="bash"
            ... )
            >>> assert "shell" in session.nodes
        """
        import logging

        from nerve.core.nodes.history import HistoryError, HistoryWriter
        from nerve.core.validation import validate_name

        logger = logging.getLogger(__name__)

        # Validate
        validate_name(id, "node")
        if id in session.nodes:
            raise ValueError(f"Node '{id}' already exists in session '{session.name}'")

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

        # Setup history
        use_history = history if history is not None else session.history_enabled
        history_writer = None
        if use_history:
            try:
                history_writer = HistoryWriter.create(
                    node_id=id,
                    server_name=session.server_name,
                    session_name=session.name,
                    base_dir=session.history_base_dir,
                    enabled=True,
                )
            except (HistoryError, ValueError) as e:
                logger.warning(f"Failed to create history writer for {id}: {e}")

        # Default parser
        actual_parser = default_parser or ParserType.NONE

        config = BackendConfig(cwd=cwd, env=env or {})
        backend = PTYBackend(command_list, config)

        try:
            await backend.start()

            # Create instance with flag to bypass __post_init__ check
            node = object.__new__(cls)
            node._created_via_create = True
            node.id = id
            node.session = session
            node.backend = backend
            node.command = command_str
            node.state = NodeState.READY
            node.persistent = True
            node._default_parser = actual_parser
            node._last_input = ""
            node._ready_timeout = ready_timeout
            node._response_timeout = response_timeout
            node._reader_task = None
            node._history_writer = history_writer

            # Start background reader
            node._start_reader()

            # Give the shell a moment to start
            await asyncio.sleep(0.5)

            # NOW register (only after successful async init)
            session.nodes[id] = node

            return node

        except Exception:
            # Cleanup on failure
            if history_writer is not None:
                history_writer.close()
            raise

    @property
    def buffer(self) -> str:
        """Current output buffer (accumulated stream)."""
        return self.backend.buffer

    def _capture_pending_buffer_if_needed(self) -> None:
        """Capture buffer from previous run/write if needed.

        Called at the start of operations to capture deferred buffer
        from previous fire-and-forget operations (run/write).
        """
        if self._history_writer and self._history_writer.enabled:
            if self._history_writer.needs_buffer_capture():
                buffer_content = self.read_tail(HISTORY_BUFFER_LINES)
                self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

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

        # Capture pending buffer from previous run/write
        self._capture_pending_buffer_if_needed()

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
        if self._history_writer and self._history_writer.enabled and ts_start is not None:
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

    async def execute_stream(self, context: ExecutionContext) -> AsyncIterator[str]:
        """Execute and stream output chunks.

        Args:
            context: Execution context with input string.

        Yields:
            Output chunks as they arrive.
        """
        if self.state == NodeState.STOPPED:
            raise RuntimeError("Node is stopped")

        # Capture pending buffer from previous run/write
        self._capture_pending_buffer_if_needed()

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
        if self._history_writer and self._history_writer.enabled and ts_start is not None:
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
        # Capture pending buffer from previous run/write
        self._capture_pending_buffer_if_needed()

        await self.backend.write(data)

        # History: log write (buffer will be captured by next operation)
        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_write(data)

    async def run(self, command: str) -> None:
        """Start a command (fire and forget).

        Writes command to terminal without waiting for response.
        Used for starting long-running processes like claude, python, etc.

        Args:
            command: Command to start.
        """
        # Capture pending buffer from previous run/write
        self._capture_pending_buffer_if_needed()

        await self.backend.write(command + "\n")

        # History: log run (buffer will be captured by next operation)
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
        # Capture pending buffer from previous run/write before closing
        self._capture_pending_buffer_if_needed()

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_delete()
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
        self.backend.clear_buffer()
        self._last_input = ""

    def _start_reader(self) -> None:
        """Start background task to continuously read and buffer output."""

        async def reader_loop() -> None:
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
