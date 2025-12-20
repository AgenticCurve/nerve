"""ClaudeOnWezTerm Channel - WezTerm channel optimized for Claude.

A convenience wrapper around WezTermChannel that:
- Requires "claude" in the command
- Uses Claude parser by default
- Handles Claude-specific quirks automatically
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from nerve.core.channels.base import ChannelInfo, ChannelState, ChannelType
from nerve.core.channels.wezterm import WezTermChannel
from nerve.core.types import ParsedResponse, ParserType


@dataclass
class ClaudeOnWezTermChannel:
    """WezTerm channel optimized for Claude CLI.

    This is a convenience wrapper that:
    - Validates command contains "claude"
    - Uses Claude parser by default for send()
    - Delegates everything else to WezTermChannel

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
    channel_type: ChannelType = field(default=ChannelType.TERMINAL, init=False)

    @classmethod
    async def create(
        cls,
        channel_id: str,
        command: str,
        cwd: str | None = None,
        parser: ParserType = ParserType.CLAUDE,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,  # 30 minutes
    ) -> ClaudeOnWezTermChannel:
        """Create a new ClaudeOnWezTerm channel.

        Args:
            channel_id: Unique channel identifier.
            command: Command to run (MUST contain "claude").
            cwd: Working directory.
            parser: Default parser (defaults to CLAUDE).
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.

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

        # Spawn a pane with default shell
        inner = await WezTermChannel.create(
            channel_id=channel_id,
            command=None,  # Use default shell
            cwd=cwd,
            ready_timeout=ready_timeout,
            response_timeout=response_timeout,
        )

        # Wait for shell to be ready
        await asyncio.sleep(0.5)

        # Type the command into the shell
        await inner.run(command)

        # Wait for Claude to start
        await asyncio.sleep(2)

        return cls(
            id=channel_id,
            _inner=inner,
            _command=command,
            _default_parser=parser,
        )

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
        # Use default parser if not specified
        actual_parser = parser if parser is not None else self._default_parser
        return await self._inner.send(
            input=input,
            parser=actual_parser,
            timeout=timeout,
            submit=submit,
        )

    async def run(self, command: str) -> None:
        """Run a command (fire and forget)."""
        await self._inner.run(command)

    async def write(self, data: str) -> None:
        """Write raw data."""
        await self._inner.write(data)

    async def read(self) -> str:
        """Read current pane content."""
        return await self._inner.read()

    def read_tail(self, lines: int = 50) -> str:
        """Read last N lines."""
        return self._inner.read_tail(lines)

    async def interrupt(self) -> None:
        """Send interrupt (Ctrl+C)."""
        await self._inner.interrupt()

    async def focus(self) -> None:
        """Focus the pane."""
        await self._inner.focus()

    async def close(self) -> None:
        """Close the channel."""
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
            },
        )

    def __repr__(self) -> str:
        return f"ClaudeOnWezTermChannel(id={self.id!r}, pane_id={self.pane_id!r}, state={self.state.name})"
