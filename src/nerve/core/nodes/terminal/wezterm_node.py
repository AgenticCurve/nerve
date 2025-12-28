"""WezTerm-based terminal node.

This module provides WezTermNode for WezTerm pane-based terminal interactions.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.history import HISTORY_BUFFER_LINES, HistoryWriter
from nerve.core.nodes.run_logging import log_complete, log_error, log_start
from nerve.core.parsers import get_parser
from nerve.core.pty import BackendConfig
from nerve.core.pty.wezterm_backend import WezTermBackend
from nerve.core.types import ParsedResponse, ParserType

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session


@dataclass
class WezTermNode:
    """WezTerm-based terminal node.

    IMPORTANT: Cannot be instantiated directly. Use WezTermNode.create() instead.

    BUFFER SEMANTICS: Always-fresh query.
    - WezTerm maintains pane content internally
    - Every buffer read queries WezTerm directly
    - No background reader needed
    - Polling interval: 2.0 seconds for ready detection

    Example:
        >>> session = Session("my-session")
        >>> node = await WezTermNode.create(
        ...     id="claude",
        ...     session=session,
        ...     command="claude"
        ... )
        >>> context = ExecutionContext(session=session, input="Hello!")
        >>> response = await node.execute(context)
        >>> print(response.raw)
    """

    # Required fields (set during .create())
    id: str
    session: Session
    backend: WezTermBackend
    pane_id: str | None = None
    command: str | None = None
    state: NodeState = NodeState.STARTING

    # Internal fields (not in __init__)
    persistent: bool = field(default=True, init=False)
    _default_parser: ParserType = field(default=ParserType.NONE, init=False)
    _last_input: str = field(default="", init=False, repr=False)
    _ready_timeout: float = field(default=60.0, init=False, repr=False)
    _response_timeout: float = field(default=1800.0, init=False, repr=False)
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
        history: bool | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        default_parser: ParserType | None = None,
    ) -> WezTermNode:
        """Create a new WezTerm node by spawning a pane.

        This is the ONLY way to create a WezTermNode. Direct instantiation via
        __init__ will raise TypeError.

        Args:
            id: Unique identifier for the node.
            session: Session to register this node with.
            command: Command to run (e.g., "claude" or ["bash"]).
            cwd: Working directory.
            history: Enable history logging (default: session.history_enabled).
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            default_parser: Default parser for execute() calls.

        Returns:
            A ready WezTermNode, registered in the session.

        Raises:
            ValueError: If node_id already exists or is invalid.
            TypeError: If called via __init__ instead of create().

        Example:
            >>> session = Session("my-session")
            >>> node = await WezTermNode.create(
            ...     id="terminal",
            ...     session=session,
            ...     command="bash"
            ... )
            >>> assert "terminal" in session.nodes
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
            command_list: list[str] = []
            command_str = None
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

        config = BackendConfig(cwd=cwd)
        backend: WezTermBackend | None = None

        try:
            backend = WezTermBackend(command_list, config)
            await backend.start()

            # Create instance with flag to bypass __post_init__ check
            node = object.__new__(cls)
            node._created_via_create = True
            node.id = id
            node.session = session
            node.backend = backend
            node.pane_id = backend.pane_id
            node.command = command_str
            node.state = NodeState.READY
            node.persistent = True
            node._default_parser = actual_parser
            node._last_input = ""
            node._ready_timeout = ready_timeout
            node._response_timeout = response_timeout
            node._history_writer = history_writer

            await asyncio.sleep(0.5)

            # NOW register (only after successful async init)
            session.nodes[id] = node

            # Log node registration and start (persistent node)
            if session.session_logger:
                session.session_logger.log_node_lifecycle(
                    id,
                    "WezTermNode",
                    persistent=True,
                    started=True,
                    command=command_str,
                )

            return node

        except Exception:
            # Cleanup on failure - close both backend and history writer
            if backend is not None:
                try:
                    await backend.stop()
                except Exception as cleanup_err:
                    logger.warning(f"Error during backend cleanup for {id}: {cleanup_err}")
            if history_writer is not None:
                history_writer.close()
            raise

    @classmethod
    async def attach(
        cls,
        id: str,
        session: Session,
        pane_id: str,
        history: bool | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        default_parser: ParserType | None = None,
    ) -> WezTermNode:
        """Attach to an existing WezTerm pane.

        This is an alternative way to create a WezTermNode by attaching to
        an existing WezTerm pane instead of spawning a new one.

        Args:
            id: Unique identifier for the node.
            session: Session to register this node with.
            pane_id: WezTerm pane ID to attach to.
            history: Enable history logging (default: session.history_enabled).
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            default_parser: Default parser for execute() calls.

        Returns:
            A WezTermNode attached to the pane, registered in the session.

        Raises:
            ValueError: If node_id already exists or is invalid.
            TypeError: If called via __init__ instead of attach().

        Example:
            >>> session = Session("my-session")
            >>> node = await WezTermNode.attach(
            ...     id="existing-pane",
            ...     session=session,
            ...     pane_id="12345"
            ... )
            >>> assert "existing-pane" in session.nodes
        """
        import logging

        from nerve.core.nodes.history import HistoryError, HistoryWriter
        from nerve.core.validation import validate_name

        logger = logging.getLogger(__name__)

        # Validate
        validate_name(id, "node")
        if id in session.nodes:
            raise ValueError(f"Node '{id}' already exists in session '{session.name}'")

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

        config = BackendConfig()
        backend: WezTermBackend | None = None

        try:
            backend = WezTermBackend([], config, pane_id=pane_id)
            await backend.attach(pane_id)

            # Create instance with flag to bypass __post_init__ check
            node = object.__new__(cls)
            node._created_via_create = True
            node.id = id
            node.session = session
            node.backend = backend
            node.pane_id = pane_id
            node.command = None
            node.state = NodeState.READY
            node.persistent = True
            node._default_parser = actual_parser
            node._last_input = ""
            node._ready_timeout = ready_timeout
            node._response_timeout = response_timeout
            node._history_writer = history_writer

            # Register with session
            session.nodes[id] = node

            # Log node registration and start (persistent node)
            if session.session_logger:
                session.session_logger.log_node_lifecycle(
                    id,
                    "WezTermNode",
                    persistent=True,
                    started=True,
                    command=f"attach:{pane_id}",
                )

            return node

        except Exception:
            # Cleanup on failure - close both backend and history writer
            if backend is not None:
                try:
                    await backend.stop()
                except Exception as cleanup_err:
                    logger.warning(f"Error during backend cleanup for {id}: {cleanup_err}")
            if history_writer is not None:
                history_writer.close()
            raise

    @classmethod
    async def _create_internal(
        cls,
        id: str,
        command: list[str] | str | None = None,
        cwd: str | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        default_parser: ParserType | None = None,
    ) -> WezTermNode:
        """Internal: Create a WezTermNode without session registration.

        This is for internal use by wrapper classes like ClaudeWezTermNode.
        The wrapper is responsible for session registration.

        Args:
            id: Unique identifier for the node.
            command: Command to run.
            cwd: Working directory.
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            default_parser: Default parser for execute() calls.

        Returns:
            A ready WezTermNode (NOT registered with any session).
        """
        # Normalize command
        if command is None:
            command_list: list[str] = []
            command_str = None
        elif isinstance(command, str):
            command_str = command
            command_list = command.split()
        else:
            command_list = command
            command_str = " ".join(command)

        # Default parser
        actual_parser = default_parser or ParserType.NONE

        config = BackendConfig(cwd=cwd)
        backend = WezTermBackend(command_list, config)

        await backend.start()

        # Create instance with flag to bypass __post_init__ check
        # Note: session is set to None for internal nodes
        node = object.__new__(cls)
        node._created_via_create = True
        node.id = id
        node.session = None  # type: ignore[assignment]  # Internal node, no session
        node.backend = backend
        node.pane_id = backend.pane_id
        node.command = command_str
        node.state = NodeState.READY
        node.persistent = True
        node._default_parser = actual_parser
        node._last_input = ""
        node._ready_timeout = ready_timeout
        node._response_timeout = response_timeout
        node._history_writer = None

        await asyncio.sleep(0.5)

        return node

    @property
    def buffer(self) -> str:
        """Current pane content (always fresh from WezTerm)."""
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
        """
        if self.state == NodeState.STOPPED:
            raise RuntimeError("Node is stopped")

        # Capture pending buffer from previous run/write
        self._capture_pending_buffer_if_needed()

        input_str = str(context.input) if context.input is not None else ""
        self._last_input = input_str

        # Get logger and exec_id
        from nerve.core.nodes.session_logging import get_execution_logger

        log_ctx = get_execution_logger(self.id, context, self.session)
        exec_id = log_ctx.exec_id or context.exec_id

        start_mono = time.monotonic()

        # Log terminal start
        log_start(
            log_ctx.logger,
            self.id,
            "terminal_start",
            exec_id=exec_id,
            input=input_str[:200] + "..." if len(input_str) > 200 else input_str,
            parser=str(context.parser or self._default_parser),
            timeout=context.timeout or self._response_timeout,
            pane_id=self.pane_id,
        )

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        parser_type = context.parser or self._default_parser
        timeout = context.timeout or self._response_timeout

        is_claude = parser_type == ParserType.CLAUDE
        parser_instance = get_parser(parser_type)

        try:
            # Send input (WezTerm sends keystrokes via CLI - no INSERT mode needed)
            if is_claude:
                # WezTerm + Claude: Just text + Enter
                await self.backend.write(input_str)
                await asyncio.sleep(0.1)
                await self.backend.write("\r")
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

            # Log terminal complete
            duration = time.monotonic() - start_mono
            log_complete(
                log_ctx.logger,
                self.id,
                "terminal_complete",
                duration,
                exec_id=exec_id,
                output_len=len(buffer),
                sections=len(result.sections),
            )

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

        except TimeoutError as e:
            duration = time.monotonic() - start_mono
            log_error(
                log_ctx.logger,
                self.id,
                "terminal_timeout",
                e,
                exec_id=exec_id,
                timeout=timeout,
                duration_s=f"{duration:.1f}",
            )
            raise

        except Exception as e:
            duration = time.monotonic() - start_mono
            log_error(
                log_ctx.logger,
                self.id,
                "terminal_error",
                e,
                exec_id=exec_id,
                duration_s=f"{duration:.1f}",
            )
            raise

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

        # Get logger and exec_id
        from nerve.core.nodes.session_logging import get_execution_logger

        log_ctx = get_execution_logger(self.id, context, self.session)
        exec_id = log_ctx.exec_id or context.exec_id

        start_mono = time.monotonic()
        chunks_count = 0

        # Log terminal stream start
        log_start(
            log_ctx.logger,
            self.id,
            "terminal_stream_start",
            exec_id=exec_id,
            input=input_str[:200] + "..." if len(input_str) > 200 else input_str,
            parser=str(context.parser or self._default_parser),
            pane_id=self.pane_id,
        )

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        parser_type = context.parser or self._default_parser
        parser_instance = get_parser(parser_type)
        is_claude = parser_type == ParserType.CLAUDE

        try:
            # Send input (WezTerm sends keystrokes via CLI - no INSERT mode needed)
            if is_claude:
                # WezTerm + Claude: Just text + Enter
                await self.backend.write(input_str)
                await asyncio.sleep(0.1)
                await self.backend.write("\r")
            else:
                await self.backend.write(input_str + "\n")

            self.state = NodeState.BUSY

            async for chunk in self.backend.read_stream():
                chunks_count += 1
                yield chunk

                if parser_instance.is_ready(self.backend.buffer):
                    self.state = NodeState.READY
                    break

            # Log terminal stream complete
            duration = time.monotonic() - start_mono
            log_complete(
                log_ctx.logger,
                self.id,
                "terminal_stream_complete",
                duration,
                exec_id=exec_id,
                chunks=chunks_count,
            )

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

        except Exception as e:
            duration = time.monotonic() - start_mono
            log_error(
                log_ctx.logger,
                self.id,
                "terminal_stream_error",
                e,
                exec_id=exec_id,
                chunks=chunks_count,
                duration_s=f"{duration:.1f}",
            )
            raise

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

        # WezTerm needs text and \r sent separately with a delay
        await self.backend.write(command)
        await asyncio.sleep(0.1)
        await self.backend.write("\r")

        # History: log run (buffer will be captured by next operation)
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

    async def get_pane_info(self) -> dict[str, Any] | None:
        """Get information about the pane."""
        return await self.backend.get_pane_info()

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

        await self.backend.stop()
        self.state = NodeState.STOPPED

        # Log node stopped (persistent node)
        if self.session and self.session.session_logger:
            self.session.session_logger.log_node_stopped(self.id, reason="stopped")

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
