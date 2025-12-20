"""PTY Channel - Direct pseudo-terminal process management.

PTYChannel owns and manages a process via a pseudo-terminal.
The buffer is a continuous stream that must be captured or data is lost.

Key characteristics:
- You own the process lifecycle (spawn, signal, exit code)
- Buffer grows continuously, requires background reader
- buffer_start tracking for incremental output
- Direct fd access for low-level control

Example:
    >>> channel = await PTYChannel.create("my-shell", command="bash")
    >>> await channel.run("echo hello")
    >>>
    >>> # Or with Claude
    >>> channel = await PTYChannel.create("claude", command="claude")
    >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from nerve.core.channels.base import ChannelConfig, ChannelInfo, ChannelState, ChannelType
from nerve.core.parsers import get_parser
from nerve.core.pty import BackendConfig
from nerve.core.pty.pty_backend import PTYBackend
from nerve.core.types import ParsedResponse, ParserType


@dataclass
class PTYConfig(ChannelConfig):
    """Configuration for PTY channels."""

    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    ready_timeout: float = 60.0
    response_timeout: float = 300.0


@dataclass
class PTYChannel:
    """PTY-based terminal channel.

    Manages a process running in a pseudo-terminal. The channel owns
    the process and maintains a continuously growing buffer that captures
    all output.

    Main methods:
        run(command)         Start a program (fire and forget)
        send(input, parser)  Send input and wait for parsed response
        interrupt()          Cancel current operation (Ctrl+C)
        write(data)          Low-level raw write

    Example:
        >>> channel = await PTYChannel.create("my-shell")
        >>> await channel.run("claude")
        >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    """

    id: str
    backend: PTYBackend
    command: str | None = None
    state: ChannelState = ChannelState.CONNECTING
    channel_type: ChannelType = field(default=ChannelType.TERMINAL, init=False)
    _ready_timeout: float = field(default=60.0, repr=False)
    _response_timeout: float = field(default=300.0, repr=False)
    _reader_task: asyncio.Task | None = field(default=None, repr=False)

    @classmethod
    async def create(
        cls,
        channel_id: str,
        command: list[str] | str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 300.0,
    ) -> PTYChannel:
        """Create a new PTY channel.

        Args:
            channel_id: Unique channel identifier (required).
            command: Command to run (e.g., "claude" or ["bash"]).
                     If not provided, starts a shell.
            cwd: Working directory.
            env: Additional environment variables.
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.

        Returns:
            A ready PTYChannel.

        Raises:
            ValueError: If channel_id is not provided.
        """
        if not channel_id:
            raise ValueError("channel_id is required")

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

        channel = cls(
            id=channel_id,
            backend=backend,
            command=command_str,
            state=ChannelState.OPEN,
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
        )

        # Start background reader - essential for PTY
        channel._start_reader()

        # Give the shell a moment to start
        await asyncio.sleep(0.5)

        return channel

    @property
    def buffer(self) -> str:
        """Current output buffer (accumulated stream)."""
        return self.backend.buffer

    @property
    def is_open(self) -> bool:
        """Whether the channel is open and ready."""
        return self.state in (ChannelState.OPEN, ChannelState.BUSY)

    @property
    def backend_type(self) -> str:
        """Backend type identifier."""
        return "pty"

    async def send(
        self,
        input: str,
        parser: ParserType = ParserType.NONE,
        timeout: float | None = None,
        submit: str | None = None,
    ) -> ParsedResponse:
        """Send input and wait for a parsed response.

        Args:
            input: Text to send.
            parser: How to parse the response (CLAUDE, GEMINI, NONE).
            timeout: Response timeout in seconds.
            submit: Submit sequence (default handles Claude specially).

        Returns:
            Parsed response with sections, token counts, etc.

        Raises:
            TimeoutError: If response times out.
            RuntimeError: If channel is closed.
        """
        if self.state == ChannelState.CLOSED:
            raise RuntimeError("Channel is closed")

        is_claude = parser == ParserType.CLAUDE and submit is None

        if submit is None and not is_claude:
            submit = "\n"

        timeout = timeout or self._response_timeout
        parser_instance = get_parser(parser)

        # Mark buffer position before sending
        buffer_start = len(self.backend.buffer)

        # Send input with appropriate submit handling
        if is_claude:
            # PTY + Claude: Handle INSERT mode
            await self.backend.write("i")
            await asyncio.sleep(0.2)
            await self.backend.write(input)
            await asyncio.sleep(0.5)
            await self.backend.write("\x1b")  # Escape
            await asyncio.sleep(0.5)
            await self.backend.write("\r")  # Enter
        else:
            await self.backend.write(input)
            await asyncio.sleep(0.1)
            await self.backend.write(submit)

        self.state = ChannelState.BUSY

        # Wait for response
        await self._wait_for_ready(
            timeout=timeout,
            parser_type=parser,
            buffer_start=buffer_start,
        )

        # Parse only the NEW output
        new_output = self.backend.buffer[buffer_start:]
        return parser_instance.parse(new_output)

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

    async def run(self, command: str) -> None:
        """Start a program in the terminal (fire and forget).

        Args:
            command: Program/command to start.
        """
        await self.backend.write(command + "\n")

    async def interrupt(self) -> None:
        """Send interrupt signal (Ctrl+C)."""
        await self.backend.write("\x03")

    async def close(self) -> None:
        """Close the channel and stop the backend."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        await self.backend.stop()
        self.state = ChannelState.CLOSED

    def _start_reader(self) -> None:
        """Start background task to continuously read and buffer output."""

        async def reader_loop():
            try:
                async for _chunk in self.backend.read_stream():
                    # Output is accumulated in backend.buffer
                    pass
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
        """Wait for terminal to be ready for input.

        For PTY, we check from buffer_start since buffer grows continuously.

        Args:
            timeout: Max time to wait in seconds.
            parser_type: Parser to use for checking readiness.
            buffer_start: Only check buffer content after this position.
        """
        parser = get_parser(parser_type)
        start = asyncio.get_event_loop().time()

        # For Claude, wait for processing to start first
        if parser_type == ParserType.CLAUDE:
            await self._wait_for_processing_start(timeout=10.0, buffer_start=buffer_start)

        # Wait for ready with consecutive checks
        ready_count = 0
        consecutive_required = 2

        while asyncio.get_event_loop().time() - start < timeout:
            # Check from buffer_start (PTY buffer grows continuously)
            check_content = self.backend.buffer[buffer_start:]

            if parser.is_ready(check_content):
                ready_count += 1
                if ready_count >= consecutive_required:
                    await asyncio.sleep(0.5)  # Post-ready delay
                    self.state = ChannelState.OPEN
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

    def to_info(self) -> ChannelInfo:
        """Get serializable channel info."""
        return ChannelInfo(
            id=self.id,
            channel_type=self.channel_type,
            state=self.state,
            metadata={
                "backend": "pty",
                "command": self.command,
            },
        )

    def __repr__(self) -> str:
        return f"PTYChannel(id={self.id!r}, state={self.state.name})"
