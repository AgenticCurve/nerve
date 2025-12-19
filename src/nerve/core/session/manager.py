"""Session manager - manage multiple sessions."""

from __future__ import annotations

from dataclasses import dataclass, field

from nerve.core.session.session import Session
from nerve.core.types import CLIType


@dataclass
class SessionManager:
    """Manage multiple AI CLI sessions.

    A simple registry for tracking multiple sessions.
    Still pure library code - no server or event awareness.

    Example:
        >>> manager = SessionManager()
        >>>
        >>> # Create sessions
        >>> s1 = await manager.create(CLIType.CLAUDE, cwd="/project1")
        >>> s2 = await manager.create(CLIType.GEMINI, cwd="/project2")
        >>>
        >>> # Get a session
        >>> session = manager.get(s1.id)
        >>> response = await session.send("hello")
        >>>
        >>> # Close all
        >>> await manager.close_all()
    """

    _sessions: dict[str, Session] = field(default_factory=dict)

    async def create(
        self,
        cli_type: CLIType,
        cwd: str | None = None,
        session_id: str | None = None,
        **kwargs,
    ) -> Session:
        """Create a new session.

        Args:
            cli_type: Type of AI CLI.
            cwd: Working directory.
            session_id: Optional session ID.
            **kwargs: Additional args passed to Session.create.

        Returns:
            The created Session.
        """
        session = await Session.create(
            cli_type=cli_type,
            cwd=cwd,
            session_id=session_id,
            **kwargs,
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        """Get a session by ID.

        Args:
            session_id: The session ID.

        Returns:
            The Session, or None if not found.
        """
        return self._sessions.get(session_id)

    def list(self) -> list[str]:
        """List all session IDs.

        Returns:
            List of session IDs.
        """
        return list(self._sessions.keys())

    def list_active(self) -> list[str]:
        """List IDs of active (not stopped) sessions.

        Returns:
            List of active session IDs.
        """
        from nerve.core.types import SessionState

        return [
            sid for sid, session in self._sessions.items() if session.state != SessionState.STOPPED
        ]

    async def close(self, session_id: str) -> bool:
        """Close a session.

        Args:
            session_id: The session ID.

        Returns:
            True if closed, False if not found.
        """
        session = self._sessions.get(session_id)
        if session:
            await session.close()
            del self._sessions[session_id]
            return True
        return False

    async def close_all(self) -> None:
        """Close all sessions."""
        for session in self._sessions.values():
            await session.close()
        self._sessions.clear()
