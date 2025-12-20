"""Terminal channel - interact with terminal panes.

A TerminalChannel wraps a PTY process or WezTerm pane,
providing a unified interface for terminal-based interactions.

Key design: The parser is NOT attached to the channel - you specify it
per-command when you send input. This allows running different programs
in the same channel.

Methods:
    run(command)         Start a program (fire and forget)
    send(input, parser)  Send input and wait for parsed response
    interrupt()          Cancel current operation (Ctrl+C)
    write(data)          Low-level raw write

Example:
    >>> # Create a shell channel
    >>> channel = await TerminalChannel.create("my-channel")
    >>>
    >>> # Start Claude
    >>> await channel.run("claude")
    >>>
    >>> # Interact with Claude
    >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    >>> print(response.sections)
    >>>
    >>> # Or create with command directly
    >>> channel = await TerminalChannel.create("my-claude", command="claude")
    >>>
    >>> # Attach to existing WezTerm pane
    >>> channel = await TerminalChannel.attach("my-pane", pane_id="4")
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nerve.core.channels.base import ChannelConfig, ChannelInfo, ChannelState, ChannelType
from nerve.core.parsers import get_parser
from nerve.core.pty import Backend, BackendConfig, BackendType, get_backend
from nerve.core.types import ParsedResponse, ParserType

if TYPE_CHECKING:
    pass


@dataclass
class TerminalConfig(ChannelConfig):
    """Configuration for terminal channels."""

    backend_type: BackendType = BackendType.PTY
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    ready_timeout: float = 60.0
    response_timeout: float = 300.0


@dataclass
class TerminalChannel:
    """Terminal channel - wraps PTY or WezTerm pane.

    A channel is a connection to a terminal where you can run programs
    and interact with them. The parser is specified per-command, not
    attached to the channel.

    Main methods:
        run(command)         Start a program (fire and forget)
        send(input, parser)  Send input and wait for parsed response
        interrupt()          Cancel current operation (Ctrl+C)
        write(data)          Low-level raw write

    Example:
        >>> # Create a shell channel
        >>> channel = await TerminalChannel.create("my-channel")
        >>>
        >>> # Start Claude
        >>> await channel.run("claude")
        >>>
        >>> # Interact with Claude
        >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
        >>> print(response.sections)
        >>>
        >>> # Exit Claude and start something else
        >>> await channel.run("exit")
        >>> await channel.run("python")
    """

    id: str
    backend: Backend
    backend_type: BackendType
    command: str | None = None  # Command that was used to create the channel
    pane_id: str | None = None  # For WezTerm
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
        backend_type: BackendType = BackendType.PTY,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 300.0,
    ) -> TerminalChannel:
        """Create a new terminal channel.

        Args:
            channel_id: Unique channel identifier (required).
            command: Optional command to run immediately (e.g., "claude").
                     If not provided, starts a shell.
            backend_type: Backend to use (PTY or WEZTERM).
            cwd: Working directory.
            env: Additional environment variables.
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.

        Returns:
            A ready TerminalChannel.

        Raises:
            ValueError: If channel_id is not provided.
        """
        if not channel_id:
            raise ValueError("channel_id is required")

        # Normalize command and store original for display
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
        backend = get_backend(backend_type, command_list, config)

        await backend.start()

        channel = cls(
            id=channel_id,
            backend=backend,
            backend_type=backend_type,
            command=command_str,
            pane_id=getattr(backend, "pane_id", None),
            state=ChannelState.OPEN,  # Mark as open immediately
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
        )

        # Start background reader to continuously capture output
        channel._start_reader()

        # Give the shell a moment to start
        await asyncio.sleep(0.5)

        return channel

    @classmethod
    async def attach(
        cls,
        channel_id: str,
        pane_id: str,
        ready_timeout: float = 60.0,
        response_timeout: float = 300.0,
    ) -> TerminalChannel:
        """Attach to an existing WezTerm pane.

        Args:
            channel_id: Unique channel identifier (required).
            pane_id: WezTerm pane ID to attach to.
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.

        Returns:
            A TerminalChannel attached to the pane.

        Raises:
            ValueError: If channel_id is not provided.
        """
        if not channel_id:
            raise ValueError("channel_id is required")

        config = BackendConfig()
        backend = get_backend(BackendType.WEZTERM, [], config, pane_id=pane_id)

        if hasattr(backend, "attach"):
            await backend.attach(pane_id)

        channel = cls(
            id=channel_id,
            backend=backend,
            backend_type=BackendType.WEZTERM,
            pane_id=pane_id,
            state=ChannelState.CONNECTING,
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
        )

        # Sync buffer and mark ready
        if hasattr(backend, "sync_buffer"):
            await backend.sync_buffer()
        channel.state = ChannelState.OPEN

        # Start background reader
        channel._start_reader()

        return channel

    @property
    def buffer(self) -> str:
        """Current output buffer."""
        return self.backend.buffer

    @property
    def is_open(self) -> bool:
        """Whether the channel is open and ready."""
        return self.state in (ChannelState.OPEN, ChannelState.BUSY)

    async def send(
        self,
        input: str,
        parser: ParserType = ParserType.NONE,
        timeout: float | None = None,
        submit: str | None = None,
    ) -> ParsedResponse:
        """Send input and wait for a parsed response.

        This is the main method for interacting with whatever is running
        in the terminal. It:
        1. Sends input with submit sequence
        2. Waits for the program to be "ready" (determined by parser)
        3. Parses and returns the response

        The parser is specified per-call, not attached to the channel.
        This allows flexible parsing based on what's currently running.

        Args:
            input: Text to send.
            parser: How to parse the response (CLAUDE, GEMINI, NONE).
            timeout: Response timeout in seconds.
            submit: Submit sequence (default: "\\n\\n" for CLAUDE, "\\n" otherwise).
                    Claude CLI needs two Enters to submit.

        Returns:
            Parsed response with sections, token counts, etc.

        Raises:
            TimeoutError: If response times out.
            RuntimeError: If channel is closed.

        Example:
            >>> response = await channel.send("Explain this code", parser=ParserType.CLAUDE)
            >>> print(response.raw)
            >>> for section in response.sections:
            ...     print(section.type, section.content[:50])
        """
        if self.state == ChannelState.CLOSED:
            raise RuntimeError("Channel is closed")

        # Track if this is Claude parser without custom submit
        is_claude = (parser == ParserType.CLAUDE and submit is None)

        # Default submit sequence for non-Claude parsers
        if submit is None and not is_claude:
            submit = "\n"

        timeout = timeout or self._response_timeout
        parser_instance = get_parser(parser)

        # Mark buffer position before sending (to check only NEW output)
        buffer_start = len(self.backend.buffer)

        # Different submit handling based on backend type
        if is_claude:
            if self.backend_type == BackendType.WEZTERM:
                # WezTerm + Claude: Just send text + Enter
                # No INSERT mode handling needed - WezTerm sends directly
                await self.backend.write(input)
                await asyncio.sleep(0.1)
                await self.backend.write("\r")  # Enter to submit
            else:
                # PTY + Claude: Need to handle INSERT mode
                # 1. Press 'i' to enter INSERT mode (Claude exits to normal after response)
                # 2. Type input
                # 3. Press Escape to exit INSERT mode
                # 4. Press Enter to submit
                await self.backend.write("i")
                await asyncio.sleep(0.2)
                await self.backend.write(input)
                await asyncio.sleep(0.5)
                await self.backend.write("\x1b")  # Escape
                await asyncio.sleep(0.5)
                await self.backend.write("\r")  # Enter
        else:
            # Non-Claude: write input + submit sequence
            await self.backend.write(input)
            await asyncio.sleep(0.1)
            await self.backend.write(submit)

        self.state = ChannelState.BUSY

        # Wait for response (only checking NEW output after buffer_start)
        await self._wait_for_ready(timeout=timeout, parser_type=parser, buffer_start=buffer_start)

        # Parse only the NEW output (after our input was sent)
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

        Unlike send(), this does NOT:
        - Add a newline
        - Wait for a response
        - Parse output

        Use for control characters, partial input, or when you need
        precise control over what's sent.

        Args:
            data: Raw data to write.

        Example:
            >>> await channel.write("partial")  # No newline
            >>> await channel.write(" input\\n")  # Complete it
            >>> await channel.write("\\x03")  # Ctrl+C
        """
        await self.backend.write(data)

    async def read(self) -> str:
        """Read current output buffer.

        Returns:
            Current buffer contents.
        """
        if hasattr(self.backend, "sync_buffer"):
            await self.backend.sync_buffer()
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

        Use this to launch programs that take over the terminal,
        like `claude`, `python`, `vim`, etc.

        This does NOT wait for the program to be ready. If you need
        to wait, use send() with an appropriate parser after run().

        Args:
            command: Program/command to start.

        Example:
            >>> await channel.run("claude")
            >>> # claude is now starting...
            >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
        """
        await self.backend.write(command + "\n")

    async def interrupt(self) -> None:
        """Send interrupt signal to cancel current operation.

        Sends Ctrl+C to interrupt whatever is currently running.
        Use this to cancel a long-running command or AI response.

        Example:
            >>> await channel.send("Write a very long essay...")
            >>> # ... taking too long
            >>> await channel.interrupt()  # Cancel it
        """
        await self.backend.write("\x03")  # Ctrl+C

    async def close(self) -> None:
        """Close the channel and stop the backend."""
        # Stop the background reader
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
                    # Output is accumulated in backend.buffer by read_stream()
                    pass
            except asyncio.CancelledError:
                pass
            except Exception:
                pass  # Backend closed or error

        self._reader_task = asyncio.create_task(reader_loop())

    async def _wait_for_ready(
        self,
        timeout: float,
        parser_type: ParserType = ParserType.NONE,
        buffer_start: int = 0,
    ) -> None:
        """Wait for terminal to be ready for input.

        The background reader task is continuously populating the buffer,
        so we just need to poll the buffer until the parser says it's ready.

        Args:
            timeout: Max time to wait in seconds.
            parser_type: Parser to use for checking readiness.
            buffer_start: Only check buffer content after this position.
        """
        parser = get_parser(parser_type)
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            # Check if parser considers the NEW output ready
            # (only look at buffer content after buffer_start)
            new_output = self.backend.buffer[buffer_start:]
            if parser.is_ready(new_output):
                self.state = ChannelState.OPEN
                return

            # Small delay before next check
            await asyncio.sleep(0.3)

        raise TimeoutError(f"Terminal did not become ready within {timeout}s")

    def to_info(self) -> ChannelInfo:
        """Get serializable channel info."""
        return ChannelInfo(
            id=self.id,
            channel_type=self.channel_type,
            state=self.state,
            metadata={
                "backend": self.backend_type.value,
                "pane_id": self.pane_id,
            },
        )

    def __repr__(self) -> str:
        return f"TerminalChannel(id={self.id!r}, backend={self.backend_type.value}, state={self.state.name})"
