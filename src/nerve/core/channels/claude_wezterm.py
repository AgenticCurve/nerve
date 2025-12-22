"""ClaudeOnWezTerm Channel - WezTerm channel optimized for Claude.

A convenience wrapper around WezTermChannel that:
- Requires "claude" in the command
- Uses Claude parser by default
- Handles Claude-specific quirks automatically
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from nerve.core.channels.base import ChannelInfo, ChannelState, ChannelType
from nerve.core.channels.history import HISTORY_BUFFER_LINES, HistoryWriter
from nerve.core.channels.wezterm import WezTermChannel
from nerve.core.types import ParsedResponse, ParserType


@dataclass
class ClaudeOnWezTermChannel:
    """WezTerm channel optimized for Claude CLI.

    This is a convenience wrapper that:
    - Validates command contains "claude"
    - Uses Claude parser by default for send()
    - Delegates everything else to WezTermChannel

    HISTORY OWNERSHIP: This wrapper owns the history writer, NOT the inner
    WezTermChannel. All history logging happens at this level.

    Example:
        >>> channel = await ClaudeOnWezTermChannel.create(
        ...     "my-claude",
        ...     command="cd ~/project && claude --dangerously-skip-permissions"
        ... )
        >>> # Parser defaults to CLAUDE
        >>> response = await channel.send("What is 2+2?")
        >>> print(response.sections)
    """

    id: str
    _inner: WezTermChannel
    _command: str = ""
    _default_parser: ParserType = ParserType.CLAUDE
    _last_input: str = ""
    channel_type: ChannelType = field(default=ChannelType.TERMINAL, init=False)
    _history_writer: HistoryWriter | None = field(default=None, repr=False)

    @classmethod
    async def create(
        cls,
        channel_id: str,
        command: str,
        cwd: str | None = None,
        parser: ParserType = ParserType.CLAUDE,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,  # 30 minutes
        history_writer: HistoryWriter | None = None,
    ) -> ClaudeOnWezTermChannel:
        """Create a new ClaudeOnWezTerm channel.

        Args:
            channel_id: Unique channel identifier.
            command: Command to run (MUST contain "claude").
            cwd: Working directory.
            parser: Default parser (defaults to CLAUDE).
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            history_writer: Optional history writer for logging operations.

        Returns:
            A ready ClaudeOnWezTermChannel.

        Raises:
            ValueError: If command doesn't contain "claude".
        """
        if not channel_id:
            raise ValueError("channel_id is required")

        if "claude" not in command.lower():
            raise ValueError(
                f"Command must contain 'claude'. Got: {command}"
            )

        # Create inner channel WITHOUT history writer - wrapper owns history
        inner = await WezTermChannel.create(
            channel_id=channel_id,
            command=None,  # Use default shell
            cwd=cwd,
            ready_timeout=ready_timeout,
            response_timeout=response_timeout,
            history_writer=None,  # Inner has NO history
        )

        # Wait for shell to be ready
        await asyncio.sleep(0.5)

        # Type the command into the shell (don't use inner.run - we log ourselves)
        await inner.backend.write(command)
        await asyncio.sleep(0.1)
        await inner.backend.write("\r")

        wrapper = cls(
            id=channel_id,
            _inner=inner,
            _command=command,
            _default_parser=parser,
            _history_writer=history_writer,
        )

        # History: log the initial run command then read (no natural response for run)
        if history_writer and history_writer.enabled:
            history_writer.log_run(command)
            await asyncio.sleep(2)  # Wait for Claude to start
            buffer_content = inner.read_tail(HISTORY_BUFFER_LINES)
            history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)
        else:
            await asyncio.sleep(2)  # Wait for Claude to start

        return wrapper

    @property
    def state(self) -> ChannelState:
        """Channel state."""
        return self._inner.state

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

    @property
    def is_open(self) -> bool:
        """Whether the channel is open."""
        return self._inner.is_open

    @property
    def backend_type(self) -> str:
        """Backend type identifier."""
        return "claude-wezterm"

    async def send(
        self,
        input: str,
        parser: ParserType | None = None,
        timeout: float | None = None,
        submit: str | None = None,
    ) -> ParsedResponse:
        """Send input and wait for parsed response.

        Args:
            input: Text to send.
            parser: Parser to use (defaults to Claude parser).
            timeout: Response timeout in seconds.
            submit: Submit sequence (auto-detected for Claude).

        Returns:
            Parsed response with sections.
        """
        # Track last input
        self._last_input = input

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        # Delegate to inner (which has no history writer)
        actual_parser = parser if parser is not None else self._default_parser
        result = await self._inner.send(
            input=input,
            parser=actual_parser,
            timeout=timeout,
            submit=submit,
        )

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
                input=input,
                response=response_data,
                preceding_buffer_seq=None,
                ts_start=ts_start,
            )

        return result

    async def send_stream(
        self,
        input: str,
        parser: ParserType = ParserType.NONE,
    ) -> AsyncIterator[str]:
        """Send input and stream output chunks.

        History logs the final buffer state after streaming completes.

        Args:
            input: Text to send.
            parser: Parser to use (defaults to Claude parser if NONE).

        Yields:
            Output chunks as they arrive.
        """
        # Track last input
        self._last_input = input

        # History: capture timestamp
        ts_start = None
        if self._history_writer and self._history_writer.enabled:
            ts_start = self._history_writer._now()

        # Use default parser if none specified
        actual_parser = parser if parser != ParserType.NONE else self._default_parser

        # Delegate to inner channel (which has no history)
        async for chunk in self._inner.send_stream(input, parser=actual_parser):
            yield chunk

        # History: log streaming operation
        if self._history_writer and self._history_writer.enabled:
            final_buffer = self._inner.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_send_stream(
                input=input,
                final_buffer=final_buffer,
                parser=actual_parser.value,
                preceding_buffer_seq=None,
                ts_start=ts_start,
            )

    async def run(self, command: str) -> None:
        """Run a command (fire and forget)."""
        # Write command directly to avoid inner's history logging
        await self._inner.backend.write(command)
        await asyncio.sleep(0.1)
        await self._inner.backend.write("\r")

        # History: log run then read (no natural response for run)
        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_run(command)
            await asyncio.sleep(0.5)
            buffer_content = self._inner.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def write(self, data: str) -> None:
        """Write raw data."""
        # Write directly to avoid inner's history logging
        await self._inner.backend.write(data)

        # History: log write then read (no natural response for write)
        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_write(data)
            await asyncio.sleep(0.1)
            buffer_content = self._inner.read_tail(HISTORY_BUFFER_LINES)
            self._history_writer.log_read(buffer_content, lines=HISTORY_BUFFER_LINES)

    async def read(self) -> str:
        """Read current pane content."""
        return await self._inner.read()

    def read_tail(self, lines: int = 50) -> str:
        """Read last N lines."""
        return self._inner.read_tail(lines)

    async def interrupt(self) -> None:
        """Send interrupt (Ctrl+C)."""
        # Write directly to avoid inner's history logging
        await self._inner.backend.write("\x03")

        # History: log interrupt
        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_interrupt()

    async def focus(self) -> None:
        """Focus the pane."""
        await self._inner.focus()

    async def close(self) -> None:
        """Close the channel."""
        # History: log close
        if self._history_writer and self._history_writer.enabled:
            self._history_writer.log_close()
            self._history_writer.close()

        await self._inner.close()

    def to_info(self) -> ChannelInfo:
        """Get serializable channel info."""
        return ChannelInfo(
            id=self.id,
            channel_type=self.channel_type,
            state=self.state,
            metadata={
                "backend": "claude-wezterm",
                "pane_id": self.pane_id,
                "command": self.command,
                "default_parser": self._default_parser.value,
                "last_input": self._last_input,
            },
        )

    def __repr__(self) -> str:
        return f"ClaudeOnWezTermChannel(id={self.id!r}, pane_id={self.pane_id!r}, state={self.state.name})"
