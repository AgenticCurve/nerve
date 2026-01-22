"""WezTerm node optimized for Claude CLI.

This module provides ClaudeWezTermNode which wraps WezTermNode
with Claude-specific defaults and behavior.
"""

from __future__ import annotations

import asyncio
import shlex
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.history import HISTORY_BUFFER_LINES, HistoryWriter
from nerve.core.nodes.run_logging import log_complete, log_error, log_start
from nerve.core.nodes.terminal.wezterm_node import WezTermNode
from nerve.core.types import ParserType

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.nodes.tools import ToolDefinition
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
    _default_parser: ParserType = field(default=ParserType.CLAUDE_CODE, init=False)
    _last_input: str = field(default="", init=False)
    persistent: bool = field(default=True, init=False)
    state: NodeState = field(default=NodeState.READY, init=False)
    _history_writer: HistoryWriter | None = field(default=None, init=False, repr=False)
    _created_via_create: bool = field(default=False, init=False, repr=False)
    _proxy_url: str | None = field(default=None, init=False, repr=False)
    _execute_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    # Claude Code session tracking (for fork support)
    _claude_session_id: str | None = field(default=None, init=False, repr=False)
    # Timeout settings (preserved during fork)
    _ready_timeout: float = field(default=60.0, init=False, repr=False)
    _response_timeout: float = field(default=1800.0, init=False, repr=False)
    # Fork metadata (set when node is created via fork)
    _forked_from: str | None = field(default=None, init=False, repr=False)
    _fork_timestamp: float | None = field(default=None, init=False, repr=False)
    # MCP config (for Claude Code native MCP support)
    _mcp_config: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _mcp_config_path: Path | None = field(default=None, init=False, repr=False)

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
        parser: ParserType = ParserType.CLAUDE_CODE,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        proxy_url: str | None = None,
        claude_session_id: str | None = None,
        mcp_config: dict[str, Any] | None = None,
        strict_mcp_config: bool = False,
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
            proxy_url: URL for API proxy. If set, exports ANTHROPIC_BASE_URL
                       before running claude command.
            claude_session_id: Claude Code session ID. If not provided, a UUID
                              is generated. Used for fork support.
            mcp_config: MCP server configuration dict. Keys are server names,
                       values are server configs (command, args, env, etc.).
                       Passed to Claude via --mcp-config flag.
            strict_mcp_config: If True, add --strict-mcp-config flag to fail
                              if any MCP server fails to start.

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

        Example with proxy:
            >>> node = await ClaudeWezTermNode.create(
            ...     id="claude-openai",
            ...     session=session,
            ...     command="claude --dangerously-skip-permissions",
            ...     proxy_url="http://127.0.0.1:34561",
            ... )
        """
        import logging

        from nerve.core.nodes.history import HistoryError, HistoryWriter
        from nerve.core.validation import validate_name

        logger = logging.getLogger(__name__)

        # Validate
        validate_name(id, "node")
        # Validate uniqueness across both nodes and graphs
        session.validate_unique_id(id, "node")

        if "claude" not in command.lower():
            raise ValueError(f"Command must contain 'claude'. Got: {command}")

        # Handle Claude session ID for fork support
        # Reconcile provided claude_session_id with any --session-id in command
        import re
        import uuid as uuid_module

        # Pattern to match --session-id with quoted or unquoted value
        # Matches: --session-id value, --session-id "quoted value", --session-id 'quoted value'
        session_id_pattern = r'--session-id\s+("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|\S+)'

        # Extract existing --session-id from command if present
        session_id_match = re.search(session_id_pattern, command)
        if session_id_match:
            raw_value = session_id_match.group(1)
            # Strip quotes if present to get the actual session ID
            if (raw_value.startswith('"') and raw_value.endswith('"')) or (
                raw_value.startswith("'") and raw_value.endswith("'")
            ):
                existing_session_id = raw_value[1:-1]
            else:
                existing_session_id = raw_value
        else:
            existing_session_id = None

        if existing_session_id:
            if claude_session_id is None:
                # Use the session ID from the command (unquoted)
                claude_session_id = existing_session_id
            elif claude_session_id != existing_session_id:
                # Replace existing --session-id with provided one (unquoted)
                logger.warning(
                    f"Replacing --session-id in command: '{existing_session_id}' -> '{claude_session_id}' "
                    f"for node '{id}'"
                )
                command = re.sub(
                    session_id_pattern,
                    f"--session-id {claude_session_id}",
                    command,
                )
            # else: claude_session_id matches existing, no change needed
        else:
            # No --session-id in command
            if claude_session_id is None:
                claude_session_id = str(uuid_module.uuid4())
            command = f"{command} --session-id {claude_session_id}"

        # Handle MCP config (write to temp file, add --mcp-config flag)
        mcp_config_path: Path | None = None
        if mcp_config:
            import json
            import tempfile

            # Generate unique filename for MCP config
            config_filename = f"nerve-mcp-{id}-{uuid_module.uuid4().hex[:8]}.json"
            mcp_config_path = Path(tempfile.gettempdir()) / config_filename

            # Wrap in mcpServers format (Claude Code expects this structure)
            full_config = {"mcpServers": mcp_config}

            with open(mcp_config_path, "w") as f:
                json.dump(full_config, f, indent=2)

            # Append --mcp-config flag to command
            command = f"{command} --mcp-config {mcp_config_path}"

            if strict_mcp_config:
                command = f"{command} --strict-mcp-config"

            logger.debug(f"MCP config written to {mcp_config_path} for node '{id}'")

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

            # If proxy_url is set, export ANTHROPIC_BASE_URL before running claude
            if proxy_url:
                export_cmd = f"export ANTHROPIC_BASE_URL={shlex.quote(proxy_url)}"
                await inner.backend.write(export_cmd)
                await asyncio.sleep(0.1)
                await inner.backend.write("\r")
                await asyncio.sleep(0.3)  # Wait for export to complete
                logger.debug(f"Set ANTHROPIC_BASE_URL={proxy_url} for node '{id}'")

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
            wrapper._proxy_url = proxy_url
            wrapper._execute_lock = asyncio.Lock()  # Initialize lock for execute_when_ready
            wrapper._claude_session_id = claude_session_id
            wrapper._ready_timeout = ready_timeout
            wrapper._response_timeout = response_timeout
            wrapper._mcp_config = mcp_config
            wrapper._mcp_config_path = mcp_config_path

            # History: log the initial run command (buffer captured by first operation)
            if history_writer and history_writer.enabled:
                history_writer.log_run(command)

            # Wait for Claude to start
            await asyncio.sleep(2)

            # NOW register (only after successful async init)
            session.nodes[id] = wrapper

            # Log node registration and start (persistent node)
            if session.session_logger:
                session.session_logger.log_node_lifecycle(
                    id,
                    "ClaudeWezTermNode",
                    persistent=True,
                    started=True,
                    command=command,
                )

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

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Execute by sending input and waiting for response.

        Uses Claude parser by default.

        Args:
            context: Execution context with input string.

        Returns:
            Dict with standardized fields:
            - success: bool - True if terminal responded successfully
            - error: str | None - Error message if failed, None if success
            - error_type: str | None - "timeout", "node_stopped", "internal_error", etc.
            - node_type: str - "claude_wezterm"
            - node_id: str - ID of this node
            - input: str - The input sent to terminal
            - output: str - Last text section content (Claude-specific, filters thinking)
            - raw: str - Raw terminal output (DEPRECATED - use attributes.raw)
            - sections: list[dict] - Parsed sections (DEPRECATED - use attributes.sections)
            - is_ready: bool - Terminal is ready for new input (DEPRECATED - use attributes.is_ready)
            - is_complete: bool - Response is complete (DEPRECATED - use attributes.is_complete)
            - tokens: int | None - Token count (DEPRECATED - use attributes.tokens)
            - parser: str - Parser type used (DEPRECATED - use attributes.parser)
            - attributes: dict - Contains raw, sections, is_ready, is_complete, tokens, parser
        """
        # Capture pending buffer from previous run/write
        self._capture_pending_buffer_if_needed()

        self._last_input = str(context.input) if context.input else ""

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
            input=self._last_input[:200] + "..."
            if len(self._last_input) > 200
            else self._last_input,
            parser=str(context.parser or self._default_parser),
            pane_id=self.pane_id,
        )

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        # Override parser if not set
        parser_type = context.parser or self._default_parser
        exec_context = context.with_parser(parser_type)

        try:
            # Delegate to inner WezTermNode
            result = await self._inner.execute(exec_context)

            # Override node_type and node_id to reflect ClaudeWezTermNode
            result["node_type"] = "claude_wezterm"
            result["node_id"] = self.id

            # Override output with Claude-specific logic: extract last text section
            # This filters out thinking blocks and returns only the final text response
            # Note: sections are in result["attributes"]["sections"], not result["sections"]
            sections = result.get("attributes", {}).get("sections", [])
            text_sections = [s for s in sections if s.get("type") == "text"]
            result["output"] = text_sections[-1]["content"] if text_sections else ""

            # Log terminal complete
            duration = time.monotonic() - start_mono
            log_complete(
                log_ctx.logger,
                self.id,
                "terminal_complete",
                duration,
                exec_id=exec_id,
                output_len=len(self._inner.buffer),
                sections=len(result.get("sections", [])),
            )

            # History: log send
            if self._history_writer and self._history_writer.enabled and ts_start is not None:
                # Result is now a dict, sections are already in dict format
                response_data = {
                    "sections": result.get("sections", []),
                    "tokens": result.get("tokens"),
                    "is_complete": result.get("is_complete", False),
                    "is_ready": result.get("is_ready", False),
                }
                self._history_writer.log_send(
                    input=self._last_input,
                    response=response_data,
                    preceding_buffer_seq=None,
                    ts_start=ts_start,
                )

            return result

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

    async def execute_when_ready(
        self,
        context: ExecutionContext,
        ready_timeout: float = 300.0,
    ) -> dict[str, Any]:
        """Execute when ready. Waits if terminal is busy.

        This method checks if the terminal is busy (showing "esc to interrupt" markers)
        and waits until it's ready before executing. This prevents sending commands
        while Claude is still processing a previous request.

        Args:
            context: Execution context with input string.
            ready_timeout: Maximum time to wait for terminal to be ready (seconds).

        Returns:
            Dict with fields (same as execute()):
            - success: bool - True if terminal responded successfully
            - error: str | None - Error message if failed, None if success
            - error_type: str | None - "timeout", "node_stopped", "internal_error", etc.
            - input: str - The input sent to terminal
            - output: str - Last text section content (Claude-specific, filters thinking)
            - raw: str - Raw terminal output
            - sections: list[dict] - Parsed sections from Claude parser
            - is_ready: bool - Terminal is ready for new input
            - is_complete: bool - Response is complete
            - tokens: int | None - Token count from Claude parser
            - parser: str - Parser type used (typically "CLAUDE")
        """
        async with self._execute_lock:
            # Wait until terminal shows no busy markers
            await self._wait_until_ready(ready_timeout)

            # Now safe to execute
            return await self.execute(context)

    async def _wait_until_ready(self, timeout: float = 300.0) -> None:
        """Wait until terminal shows ready state using Claude parser.

        Uses the same logic as _wait_for_ready() but checks BEFORE sending input
        rather than after, to ensure the terminal is idle.

        Args:
            timeout: Maximum time to wait (seconds).

        Raises:
            TimeoutError: If terminal doesn't become ready within timeout.
        """
        from nerve.core.parsers import get_parser

        parser = get_parser(self._default_parser)  # Use Claude parser
        start = time.monotonic()

        ready_count = 0
        consecutive_required = 2  # Match WezTermNode behavior

        while time.monotonic() - start < timeout:
            # Check FULL buffer (same as _wait_for_ready does)
            check_content = self._inner.buffer

            if parser.is_ready(check_content):
                ready_count += 1
                if ready_count >= consecutive_required:
                    await asyncio.sleep(0.3)
                    return  # Ready!
            else:
                ready_count = 0

            await asyncio.sleep(2.0)  # Match WezTermNode poll interval

        raise TimeoutError(f"Terminal did not become ready within {timeout}s")

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
            input=self._last_input[:200] + "..."
            if len(self._last_input) > 200
            else self._last_input,
            parser=str(context.parser or self._default_parser),
            pane_id=self.pane_id,
        )

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        parser_type = context.parser or self._default_parser
        exec_context = context.with_parser(parser_type)

        try:
            async for chunk in self._inner.execute_stream(exec_context):
                chunks_count += 1
                yield chunk

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
                final_buffer = self._inner.read_tail(HISTORY_BUFFER_LINES)
                self._history_writer.log_send_stream(
                    input=self._last_input,
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
    ) -> dict[str, Any]:
        """Convenience method to send input and get response.

        Args:
            text: Input text to send.
            parser: Parser type (defaults to node's default).
            timeout: Response timeout (defaults to node's default).

        Returns:
            Response dict with success/error/error_type and terminal fields.
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

        # Clean up MCP config temp file
        if self._mcp_config_path and self._mcp_config_path.exists():
            import logging

            logger = logging.getLogger(__name__)
            try:
                self._mcp_config_path.unlink()
                logger.debug(f"Deleted MCP config file: {self._mcp_config_path}")
            except Exception as e:
                logger.warning(f"Failed to delete MCP config file {self._mcp_config_path}: {e}")

        # Log node stopped (persistent node)
        if self.session and self.session.session_logger:
            self.session.session_logger.log_node_stopped(self.id, reason="stopped")

    async def reset(self) -> None:
        """Reset state while keeping resources running.

        Clears the buffer and state for the inner WezTerm node.
        """
        await self._inner.reset()
        self._last_input = ""

    def to_info(self) -> NodeInfo:
        """Get node information."""
        metadata: dict[str, Any] = {
            "pane_id": self.pane_id,
            "command": self.command,
            "default_parser": self._default_parser.value,
            "last_input": self._last_input,
        }
        if self._proxy_url:
            metadata["proxy_url"] = self._proxy_url
        if self._claude_session_id:
            metadata["claude_session_id"] = self._claude_session_id
        if self._forked_from:
            metadata["forked_from"] = self._forked_from
        if self._fork_timestamp:
            metadata["fork_timestamp"] = self._fork_timestamp
        if self._mcp_config:
            metadata["mcp_servers"] = list(self._mcp_config.keys())
        return NodeInfo(
            id=self.id,
            node_type="claude-wezterm",
            state=self.state,
            persistent=self.persistent,
            metadata=metadata,
        )

    # -------------------------------------------------------------------------
    # Fork support
    # -------------------------------------------------------------------------

    def _extract_base_command(self) -> str:
        """Extract base command without session/resume/fork flags.

        Strips these flags and their arguments from the stored command:
        - --session-id <value>
        - --resume <value>
        - --fork-session

        Uses regex to preserve shell operators (&&, ||, ;, |) that would be
        incorrectly quoted by shlex.join().

        Returns:
            Command string without session-related flags.

        Example:
            >>> node._command = "claude --dangerously-skip-permissions --session-id abc123"
            >>> node._extract_base_command()
            'claude --dangerously-skip-permissions'

            >>> node._command = "cd ~/project && claude --session-id abc123"
            >>> node._extract_base_command()
            'cd ~/project && claude'
        """
        import re

        result = self._command

        # Remove --session-id and its argument (handles quoted values too)
        result = re.sub(r"--session-id\s+(?:\"[^\"]*\"|'[^']*'|\S+)", "", result)

        # Remove --resume and its argument
        result = re.sub(r"--resume\s+(?:\"[^\"]*\"|'[^']*'|\S+)", "", result)

        # Remove --fork-session flag
        result = re.sub(r"--fork-session\b", "", result)

        # Clean up extra whitespace
        result = re.sub(r"\s+", " ", result).strip()

        return result

    async def fork(self, new_id: str) -> ClaudeWezTermNode:
        """Fork this node by creating a new Claude session branched from this one.

        Uses Claude Code's native fork mechanism:
        - --resume <original-session-id>: Resume from existing session
        - --fork-session: Create a branch instead of continuing
        - --session-id <new-session-id>: ID for the new forked session

        The forked node is completely independent - it has its own WezTerm pane,
        its own Claude process, and its own conversation history branched from
        the fork point.

        Args:
            new_id: Unique ID for the forked node.

        Returns:
            New ClaudeWezTermNode with forked conversation.

        Raises:
            ValueError: If new_id already exists or session ID not tracked.

        Example:
            >>> node = await ClaudeWezTermNode.create(
            ...     id="claude", session=session,
            ...     command="claude --dangerously-skip-permissions"
            ... )
            >>> await node.send("What is Python?")
            >>> # Fork to explore alternative direction
            >>> researcher = await node.fork("researcher")
            >>> await researcher.send("Now focus on security aspects")
            >>> # Original continues independently
            >>> await node.send("Tell me about web frameworks")
        """
        import uuid as uuid_module

        # Validate new_id is unique
        self.session.validate_unique_id(new_id, "node")

        # Validate we have session ID to fork from
        if not self._claude_session_id:
            raise ValueError(
                f"Cannot fork node '{self.id}': Claude session ID not tracked. "
                "This node may have been created before session tracking was added."
            )

        # Generate new session ID for the fork
        new_claude_session_id = str(uuid_module.uuid4())

        # Build fork command using Claude's native fork mechanism
        base_command = self._extract_base_command()
        fork_command = (
            f"{base_command} "
            f"--resume {self._claude_session_id} "
            f"--fork-session "
            f"--session-id {new_claude_session_id}"
        )

        # Get cwd from inner node's backend
        cwd = self._inner.backend.config.cwd if self._inner.backend.config else None

        # Create new node with fork command
        # Note: We pass claude_session_id explicitly to avoid re-generation
        # All settings (parser, timeouts, proxy_url, cwd) are preserved from the original
        forked = await ClaudeWezTermNode.create(
            id=new_id,
            session=self.session,
            command=fork_command,
            cwd=cwd,
            history=self._history_writer is not None and self._history_writer.enabled,
            parser=self._default_parser,
            ready_timeout=self._ready_timeout,
            response_timeout=self._response_timeout,
            proxy_url=self._proxy_url,
            claude_session_id=new_claude_session_id,
        )

        # Set fork metadata for traceability
        forked._forked_from = self.id
        forked._fork_timestamp = time.time()

        return forked

    # -------------------------------------------------------------------------
    # Tool-capable interface (opt-in for LLMChatNode tool use)
    # -------------------------------------------------------------------------

    def list_tools(self) -> list[ToolDefinition]:
        """Return all tools this node provides.

        ClaudeWezTermNode is a single-tool node that provides the "ask_claude" tool.

        Returns:
            List containing one ToolDefinition for Claude interaction.
        """
        from nerve.core.nodes.tools import ToolDefinition

        return [
            ToolDefinition(
                name="ask_claude",
                description="Ask Claude (another AI assistant) for help, opinions, or to perform tasks",
                parameters={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message or question to send to Claude",
                        },
                    },
                    "required": ["message"],
                },
                node_id=self.id,
            )
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        """Execute the ask_claude tool.

        Args:
            name: Tool name (must be "ask_claude").
            args: Arguments with "message" key.

        Returns:
            Claude's response text (last text section only).

        Raises:
            ValueError: If tool name is not "ask_claude".
        """
        if name != "ask_claude":
            raise ValueError(
                f"Unknown tool '{name}'. ClaudeWezTermNode only provides 'ask_claude' tool."
            )

        message = args.get("message", "")
        message_str = str(message) if message else ""

        from nerve.core.nodes.context import ExecutionContext

        context = ExecutionContext(session=self.session, input=message_str)
        result = await self.execute(context)

        # Get only the last text section (most recent/final response)
        # Note: sections are in result["attributes"]["sections"]
        sections = result.get("attributes", {}).get("sections", [])
        text_sections = [s for s in sections if s.get("type") == "text"]
        if text_sections:
            content = text_sections[-1].get("content", "")
            return str(content) if content else "(no response)"
        return "(no response)"

    def __repr__(self) -> str:
        return (
            f"ClaudeWezTermNode(id={self.id!r}, pane_id={self.pane_id!r}, state={self.state.name})"
        )
