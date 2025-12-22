"""WezTerm Channel - Interact with WezTerm panes.

WezTermChannel attaches to WezTerm panes and interacts via CLI.
The buffer is always fresh - WezTerm maintains pane content internally.

Key characteristics:
- WezTerm owns the pane, you just attach/interact
- Buffer is queried fresh each time (no caching needed)
- Pane-specific features (focus, splits, etc.)
- No background reader needed

Example:
    >>> # Attach to existing pane running Claude
    >>> channel = await WezTermChannel.attach("my-claude", pane_id="4")
    >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    >>>
    >>> # Or spawn a new pane
    >>> channel = await WezTermChannel.create("new-claude", command="claude")
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from nerve.core.channels.base import ChannelConfig, ChannelInfo, ChannelState, ChannelType
from nerve.core.parsers import get_parser
from nerve.core.pty.wezterm_backend import WezTermBackend, BackendConfig
from nerve.core.types import ParsedResponse, ParserType


@dataclass
class WezTermConfig(ChannelConfig):
    """Configuration for WezTerm channels."""

    cwd: str | None = None
    ready_timeout: float = 60.0
    response_timeout: float = 1800.0  # 30 minutes


@dataclass
class WezTermChannel:
    """WezTerm-based terminal channel.

    Attaches to WezTerm panes and interacts via the wezterm CLI.
    Unlike PTY, WezTerm maintains pane content internally, so we
    query it fresh each time rather than maintaining a buffer.

    Main methods:
        run(command)         Start a program (fire and forget)
        send(input, parser)  Send input and wait for parsed response
        interrupt()          Cancel current operation (Ctrl+C)
        write(data)          Low-level raw write
        focus()              Activate/focus the pane

    Example:
        >>> channel = await WezTermChannel.attach("claude", pane_id="4")
        >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
        >>> await channel.focus()  # Bring pane to front
    """

    id: str
    backend: WezTermBackend
    pane_id: str | None = None
    command: str | None = None
    state: ChannelState = ChannelState.CONNECTING
    channel_type: ChannelType = field(default=ChannelType.TERMINAL, init=False)
    _last_input: str = field(default="", repr=False)
    _ready_timeout: float = field(default=60.0, repr=False)
    _response_timeout: float = field(default=1800.0, repr=False)  # 30 minutes

    @classmethod
    async def create(
        cls,
        channel_id: str,
        command: list[str] | str | None = None,
        cwd: str | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,  # 30 minutes
    ) -> WezTermChannel:
        """Create a new WezTerm channel by spawning a pane.

        Args:
            channel_id: Unique channel identifier (required).
            command: Command to run (e.g., "claude" or ["bash"]).
            cwd: Working directory.
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.

        Returns:
            A ready WezTermChannel.

        Raises:
            ValueError: If channel_id is not provided.
        """
        if not channel_id:
            raise ValueError("channel_id is required")

        # Normalize command
        if command is None:
            command_list = []  # Empty = use default shell
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

        channel = cls(
            id=channel_id,
            backend=backend,
            pane_id=backend.pane_id,
            command=command_str,
            state=ChannelState.OPEN,
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
        )

        # Give the command a moment to start
        await asyncio.sleep(0.5)

        return channel

    @classmethod
    async def attach(
        cls,
        channel_id: str,
        pane_id: str,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,  # 30 minutes
    ) -> WezTermChannel:
        """Attach to an existing WezTerm pane.

        Args:
            channel_id: Unique channel identifier (required).
            pane_id: WezTerm pane ID to attach to.
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.

        Returns:
            A WezTermChannel attached to the pane.

        Raises:
            ValueError: If channel_id is not provided.
            RuntimeError: If pane doesn't exist.
        """
        if not channel_id:
            raise ValueError("channel_id is required")

        config = BackendConfig()
        backend = WezTermBackend([], config, pane_id=pane_id)

        await backend.attach(pane_id)

        return cls(
            id=channel_id,
            backend=backend,
            pane_id=pane_id,
            state=ChannelState.OPEN,
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
        )

    @property
    def buffer(self) -> str:
        """Current pane content (always fresh from WezTerm)."""
        return self.backend.buffer

    @property
    def is_open(self) -> bool:
        """Whether the channel is open and ready."""
        return self.state in (ChannelState.OPEN, ChannelState.BUSY)

    @property
    def backend_type(self) -> str:
        """Backend type identifier."""
        return "wezterm"

    async def send(
        self,
        input: str,
        parser: ParserType | None = None,
        timeout: float | None = None,
        submit: str | None = None,
    ) -> ParsedResponse:
        """Send input and wait for a parsed response.

        Args:
            input: Text to send.
            parser: How to parse the response (CLAUDE, GEMINI, NONE). None defaults to NONE.
            timeout: Response timeout in seconds.
            submit: Submit sequence.

        Returns:
            Parsed response with sections, token counts, etc.

        Raises:
            TimeoutError: If response times out.
            RuntimeError: If channel is closed.
        """
        if self.state == ChannelState.CLOSED:
            raise RuntimeError("Channel is closed")

        # Track last input
        self._last_input = input

        # Default to NONE parser if not specified
        actual_parser = parser if parser is not None else ParserType.NONE

        is_claude = actual_parser == ParserType.CLAUDE and submit is None

        if submit is None and not is_claude:
            submit = "\n"

        timeout = timeout or self._response_timeout
        parser_instance = get_parser(actual_parser)

        # Send input
        if is_claude:
            # WezTerm + Claude: Just send text + Enter
            await self.backend.write(input)
            await asyncio.sleep(0.1)
            await self.backend.write("\r")
        else:
            await self.backend.write(input)
            await asyncio.sleep(0.1)
            await self.backend.write(submit)

        self.state = ChannelState.BUSY

        # Wait for response
        await self._wait_for_ready(timeout=timeout, parser_type=actual_parser)

        # Extra delay to ensure pane content is fully updated
        await asyncio.sleep(0.5)

        # Parse the full buffer (WezTerm always fresh)
        buffer = self.backend.buffer

        result = parser_instance.parse(buffer)
        return result

    async def send_stream(
        self,
        input: str,
        parser: ParserType = ParserType.NONE,
    ) -> AsyncIterator[str]:
        """Send input and stream output chunks.

        Args:
            input: Text to send.
            parser: Parser to determine when response is complete.

        Yields:
            Output chunks as they arrive.
        """
        if self.state == ChannelState.CLOSED:
            raise RuntimeError("Channel is closed")

        parser_instance = get_parser(parser)

        await self.backend.write(input + "\n")
        self.state = ChannelState.BUSY

        async for chunk in self.backend.read_stream():
            yield chunk

            if parser_instance.is_ready(self.backend.buffer):
                self.state = ChannelState.OPEN
                break

    async def write(self, data: str) -> None:
        """Write raw data to the terminal (low-level).

        Args:
            data: Raw data to write.
        """
        await self.backend.write(data)

    async def read(self) -> str:
        """Read current pane content (fresh from WezTerm).

        Returns:
            Current pane content.
        """
        return self.backend.buffer

    def read_tail(self, lines: int = 50) -> str:
        """Read last N lines from pane.

        Args:
            lines: Number of lines to read.

        Returns:
            Last N lines of pane content.
        """
        return self.backend.read_tail(lines)

    async def run(self, command: str) -> None:
        """Start a program in the terminal (fire and forget).

        Args:
            command: Program/command to start.
        """
        await self.backend.write(command)
        await asyncio.sleep(0.1)
        await self.backend.write("\r")

    async def interrupt(self) -> None:
        """Send interrupt signal (Ctrl+C)."""
        await self.backend.write("\x03")

    async def focus(self) -> None:
        """Focus (activate) the WezTerm pane."""
        await self.backend.focus()

    async def get_pane_info(self) -> dict | None:
        """Get information about the pane.

        Returns:
            Dict with pane info, or None if not available.
        """
        return await self.backend.get_pane_info()

    async def close(self) -> None:
        """Close the channel and stop the backend."""
        await self.backend.stop()
        self.state = ChannelState.CLOSED

    async def _wait_for_ready(
        self,
        timeout: float,
        parser_type: ParserType = ParserType.NONE,
    ) -> None:
        """Wait for terminal to be ready for input.

        For WezTerm, we always check the full buffer (it's always fresh).

        Args:
            timeout: Max time to wait in seconds.
            parser_type: Parser to use for checking readiness.
        """
        parser = get_parser(parser_type)
        start = asyncio.get_event_loop().time()

        # Wait for ready with consecutive checks
        ready_count = 0
        consecutive_required = 2

        while asyncio.get_event_loop().time() - start < timeout:
            # Check full buffer (WezTerm always fresh)
            check_content = self.backend.buffer

            if parser.is_ready(check_content):
                ready_count += 1
                if ready_count >= consecutive_required:
                    await asyncio.sleep(0.3)  # Brief post-ready delay
                    self.state = ChannelState.OPEN
                    return
            else:
                ready_count = 0

            await asyncio.sleep(2.0)  # Poll every 2 seconds

        raise TimeoutError(f"Terminal did not become ready within {timeout}s")

    def to_info(self) -> ChannelInfo:
        """Get serializable channel info."""
        return ChannelInfo(
            id=self.id,
            channel_type=self.channel_type,
            state=self.state,
            metadata={
                "backend": "wezterm",
                "pane_id": self.pane_id,
                "command": self.command,
                "last_input": self._last_input,
            },
        )

    def __repr__(self) -> str:
        return f"WezTermChannel(id={self.id!r}, pane_id={self.pane_id!r}, state={self.state.name})"
