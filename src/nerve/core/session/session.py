"""Session - PTY + Parser combined."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nerve.core.parsers import Parser, get_parser
from nerve.core.pty import PTYConfig, PTYProcess
from nerve.core.types import CLIType, ParsedResponse, SessionState

if TYPE_CHECKING:
    from nerve.core.session.persistence import SessionMetadata


def _get_cli_command(cli_type: CLIType) -> list[str]:
    """Get command for CLI type."""
    commands = {
        CLIType.CLAUDE: ["claude"],
        CLIType.GEMINI: ["gemini"],
    }
    return commands.get(cli_type, ["claude"])


@dataclass
class Session:
    """AI CLI session - combines PTY process with output parser.

    This is still pure library code - doesn't know about:
    - Server (can be used standalone)
    - Events (uses return values and async iterators)
    - Transport (no network awareness)

    Example:
        >>> session = await Session.create(CLIType.CLAUDE, cwd="/project")
        >>>
        >>> # Send and wait for complete response
        >>> response = await session.send("explain this")
        >>> print(response.sections)
        >>>
        >>> # Or stream output
        >>> async for chunk in session.send_stream("explain this"):
        ...     print(chunk, end="")
        >>>
        >>> await session.close()
    """

    id: str
    cli_type: CLIType
    pty: PTYProcess
    parser: Parser
    state: SessionState = SessionState.STARTING
    _ready_timeout: float = field(default=60.0, repr=False)
    _response_timeout: float = field(default=300.0, repr=False)

    @classmethod
    async def create(
        cls,
        cli_type: CLIType,
        cwd: str | None = None,
        session_id: str | None = None,
        env: dict[str, str] | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 300.0,
    ) -> Session:
        """Create and start a new session.

        Args:
            cli_type: Type of AI CLI (CLAUDE, GEMINI).
            cwd: Working directory for the CLI.
            session_id: Optional session ID (auto-generated if not provided).
            env: Additional environment variables.
            ready_timeout: Timeout for CLI to become ready.
            response_timeout: Timeout for responses.

        Returns:
            A started Session instance.

        Raises:
            TimeoutError: If CLI doesn't become ready.
        """
        session_id = session_id or str(uuid.uuid4())[:8]
        command = _get_cli_command(cli_type)
        parser = get_parser(cli_type)

        config = PTYConfig(cwd=cwd, env=env or {})
        pty = PTYProcess(command, config)
        await pty.start()

        session = cls(
            id=session_id,
            cli_type=cli_type,
            pty=pty,
            parser=parser,
            state=SessionState.STARTING,
            _ready_timeout=ready_timeout,
            _response_timeout=response_timeout,
        )

        # Wait for CLI to be ready
        await session._wait_for_ready(timeout=ready_timeout)

        return session

    @property
    def buffer(self) -> str:
        """Current PTY output buffer."""
        return self.pty.buffer

    @property
    def is_ready(self) -> bool:
        """Whether the CLI is ready for input."""
        return self.state == SessionState.READY

    async def send(self, text: str, timeout: float | None = None) -> ParsedResponse:
        """Send input and wait for complete response.

        Args:
            text: Text to send to the CLI.
            timeout: Response timeout (uses default if not provided).

        Returns:
            Parsed response.

        Raises:
            TimeoutError: If response times out.
            RuntimeError: If session is not ready.
        """
        if self.state == SessionState.STOPPED:
            raise RuntimeError("Session is stopped")

        timeout = timeout or self._response_timeout

        await self.pty.write(text + "\n")
        self.state = SessionState.BUSY

        # Wait for response
        await self._wait_for_ready(timeout=timeout)

        # Parse and return
        return self.parser.parse(self.pty.buffer)

    async def send_stream(self, text: str) -> AsyncIterator[str]:
        """Send input and stream output chunks.

        Yields output as it arrives. Useful for real-time display.

        Args:
            text: Text to send to the CLI.

        Yields:
            Output chunks.
        """
        if self.state == SessionState.STOPPED:
            raise RuntimeError("Session is stopped")

        await self.pty.write(text + "\n")
        self.state = SessionState.BUSY

        async for chunk in self.pty.read_stream():
            yield chunk

            if self.parser.is_ready(self.pty.buffer):
                self.state = SessionState.READY
                break

    async def send_raw(self, text: str) -> None:
        """Send raw text without waiting for response.

        Useful for sending control characters or partial input.

        Args:
            text: Raw text to send (no newline added).
        """
        await self.pty.write(text)

    async def interrupt(self) -> None:
        """Send interrupt signal to the CLI.

        Uses Escape for Claude, Ctrl+C for others.
        """
        if self.cli_type == CLIType.CLAUDE:
            await self.pty.write("\x1b")  # Escape
        else:
            await self.pty.write("\x03")  # Ctrl+C

    async def close(self) -> None:
        """Close the session and stop the PTY process."""
        await self.pty.stop()
        self.state = SessionState.STOPPED

    async def _wait_for_ready(self, timeout: float) -> None:
        """Wait for CLI to be ready for input."""
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            # Read any pending output
            try:
                async for _ in self.pty.read_stream():
                    break  # Just trigger a read
            except Exception:
                pass

            if self.parser.is_ready(self.pty.read_tail()):
                self.state = SessionState.READY
                return

            await asyncio.sleep(0.5)

        raise TimeoutError(f"CLI did not become ready within {timeout}s")

    def to_metadata(
        self,
        name: str | None = None,
        description: str = "",
        tags: list[str] | None = None,
    ) -> SessionMetadata:
        """Create serializable metadata from this session.

        Useful for saving session info to persistent storage.

        Args:
            name: Human-readable name (defaults to session ID).
            description: What this session is for.
            tags: Optional tags for organization.

        Returns:
            SessionMetadata that can be saved to JSON.
        """
        from nerve.core.session.persistence import SessionMetadata

        return SessionMetadata(
            id=self.id,
            name=name or self.id,
            cli_type=self.cli_type,
            description=description,
            cwd=self.pty.config.cwd,
            tags=tags or [],
        )

    def __repr__(self) -> str:
        return f"Session(id={self.id!r}, cli_type={self.cli_type}, state={self.state})"
