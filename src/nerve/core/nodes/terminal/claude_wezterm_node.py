"""WezTerm node optimized for Claude CLI.

This module provides ClaudeWezTermNode which wraps WezTermNode
with Claude-specific defaults and behavior.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.history import HISTORY_BUFFER_LINES, HistoryWriter
from nerve.core.nodes.terminal.wezterm_node import WezTermNode
from nerve.core.types import ParsedResponse, ParserType

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session


@dataclass
class ClaudeWezTermNode:
    """WezTerm node optimized for Claude CLI.

    IMPORTANT: Cannot be instantiated directly. Use ClaudeWezTermNode.create() instead.

    A convenience wrapper that:
    - Validates command contains "claude"
    - Uses Claude parser by default
    - Delegates everything else to inner WezTermNode

    HISTORY OWNERSHIP: This wrapper owns the history writer.
    The inner WezTermNode has NO history writer.

    Example:
        >>> session = Session("my-session")
        >>> node = await ClaudeWezTermNode.create(
        ...     id="my-claude",
        ...     session=session,
        ...     command="cd ~/project && claude --dangerously-skip-permissions"
        ... )
        >>> context = ExecutionContext(session=session, input="What is 2+2?")
        >>> response = await node.execute(context)
        >>> print(response.sections)
    """

    # Required fields (set during .create())
    id: str
    session: Session
    _inner: WezTermNode
    _command: str = ""

    # Internal fields (not in __init__)
    _default_parser: ParserType = field(default=ParserType.CLAUDE, init=False)
    _last_input: str = field(default="", init=False)
    persistent: bool = field(default=True, init=False)
    state: NodeState = field(default=NodeState.READY, init=False)
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
        command: str,
        cwd: str | None = None,
        history: bool | None = None,
        parser: ParserType = ParserType.CLAUDE,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
    ) -> ClaudeWezTermNode:
        """Create a new ClaudeWezTerm node and register with session.

        This is the ONLY way to create a ClaudeWezTermNode. Direct instantiation
        via __init__ will raise TypeError.

        Args:
            id: Unique identifier for the node.
            session: Session to register this node with.
            command: Command to run (MUST contain "claude").
            cwd: Working directory.
            history: Enable history logging (default: session.history_enabled).
            parser: Default parser (defaults to CLAUDE).
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.

        Returns:
            A ready ClaudeWezTermNode, registered in the session.

        Raises:
            ValueError: If node_id already exists, is invalid, or command doesn't contain "claude".
            TypeError: If called via __init__ instead of create().

        Example:
            >>> session = Session("my-session")
            >>> node = await ClaudeWezTermNode.create(
            ...     id="claude",
            ...     session=session,
            ...     command="claude --dangerously-skip-permissions"
            ... )
            >>> assert "claude" in session.nodes
        """
        import logging

        from nerve.core.nodes.history import HistoryError, HistoryWriter
        from nerve.core.validation import validate_name

        logger = logging.getLogger(__name__)

        # Validate
        validate_name(id, "node")
        if id in session.nodes:
            raise ValueError(f"Node '{id}' already exists in session '{session.name}'")

        if "claude" not in command.lower():
            raise ValueError(f"Command must contain 'claude'. Got: {command}")

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

        inner: WezTermNode | None = None
        try:
            # Create inner node WITHOUT history writer - wrapper owns history
            # Use _create_internal which doesn't register with session
            inner = await WezTermNode._create_internal(
                id=id,
                command=None,  # Use default shell
                cwd=cwd,
                ready_timeout=ready_timeout,
                response_timeout=response_timeout,
                default_parser=parser,
            )

            await asyncio.sleep(0.5)

            # Type the command into the shell
            await inner.backend.write(command)
            await asyncio.sleep(0.1)
            await inner.backend.write("\r")

            # Create wrapper with flag to bypass __post_init__ check
            wrapper = object.__new__(cls)
            wrapper._created_via_create = True
            wrapper.id = id
            wrapper.session = session
            wrapper._inner = inner
            wrapper._command = command
            wrapper._default_parser = parser
            wrapper._last_input = ""
            wrapper.persistent = True
            wrapper.state = NodeState.READY
            wrapper._history_writer = history_writer

            # History: log the initial run command (buffer captured by first operation)
            if history_writer and history_writer.enabled:
                history_writer.log_run(command)

            # Wait for Claude to start
            await asyncio.sleep(2)

            # NOW register (only after successful async init)
            session.nodes[id] = wrapper

            return wrapper

        except Exception:
            # Cleanup on failure - close both inner node and history writer
            if inner is not None:
                await inner.stop()
            if history_writer is not None:
                history_writer.close()
            raise

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

    def _capture_pending_buffer_if_needed(self) -> None:
        """Capture buffer from previous run/write if needed.

        Called at the start of operations to capture deferred buffer
        from previous fire-and-forget operations (run/write).
        """
        if self._history_writer and self._history_writer.enabled:
            if self._history_writer.needs_buffer_capture():
                buffer_content = self._inner.read_tail(HISTORY_BUFFER_LINES)
                self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def execute(self, context: ExecutionContext) -> ParsedResponse:
        """Execute by sending input and waiting for response.

        Uses Claude parser by default.

        Args:
            context: Execution context with input string.

        Returns:
            Parsed response.
        """
        # Capture pending buffer from previous run/write
        self._capture_pending_buffer_if_needed()

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
                input=self._last_input,
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
        # Capture pending buffer from previous run/write
        self._capture_pending_buffer_if_needed()

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
        if self._history_writer and self._history_writer.enabled and ts_start is not None:
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
        # Capture pending buffer from previous run/write
        self._capture_pending_buffer_if_needed()

        await self._inner.backend.write(data)

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

        # WezTerm needs text and \r sent separately with a delay
        await self._inner.backend.write(command)
        await asyncio.sleep(0.1)
        await self._inner.backend.write("\r")

        # History: log run (buffer will be captured by next operation)
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
        # Capture pending buffer from previous run/write before closing
        self._capture_pending_buffer_if_needed()

        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_delete()
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
        return (
            f"ClaudeWezTermNode(id={self.id!r}, pane_id={self.pane_id!r}, state={self.state.name})"
        )
