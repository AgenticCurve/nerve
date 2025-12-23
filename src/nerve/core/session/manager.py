"""Session management.

SessionManager manages sessions (groups of nodes).

Example:
    >>> from nerve.core.session import Session, SessionManager
    >>>
    >>> session = Session()
    >>> node = await session.create_node("my-node", command="bash")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from nerve.core.session.session import Session

logger = logging.getLogger(__name__)


@dataclass
class SessionManager:
    """Manage sessions (groups of nodes).

    Use this when you need logical groupings of nodes with metadata.

    Example:
        >>> manager = SessionManager()
        >>>
        >>> # Create a session
        >>> session = manager.create_session(name="my-project")
        >>>
        >>> # Create nodes (auto-registered in session)
        >>> shell = await session.create_node("shell", command="bash")
        >>>
        >>> # Close session (stops all its nodes)
        >>> await manager.close_session(session.id)
    """

    _sessions: dict[str, Session] = field(default_factory=dict)

    def create_session(
        self,
        name: str | None = None,
        session_id: str | None = None,
        description: str = "",
        tags: list[str] | None = None,
    ) -> Session:
        """Create a new session.

        Args:
            name: Session name (defaults to ID).
            session_id: Optional session ID.
            description: Session description.
            tags: Optional tags.

        Returns:
            The created Session.
        """
        session = Session(
            id=session_id or "",
            name=name or "",
            description=description,
            tags=tags or [],
        )
        self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID.

        Args:
            session_id: The session ID.

        Returns:
            The Session, or None if not found.
        """
        return self._sessions.get(session_id)

    def find_by_name(self, name: str) -> Session | None:
        """Find a session by name.

        Args:
            name: Session name.

        Returns:
            The Session, or None if not found.
        """
        for session in self._sessions.values():
            if session.name == name:
                return session
        return None

    def list_sessions(self) -> list[str]:
        """List all session IDs.

        Returns:
            List of session IDs.
        """
        return list(self._sessions.keys())

    async def close_session(self, session_id: str) -> bool:
        """Close a session and stop all its nodes.

        Args:
            session_id: The session ID.

        Returns:
            True if closed, False if not found.
        """
        session = self._sessions.get(session_id)
        if session:
            await session.stop()
            del self._sessions[session_id]
            return True
        return False

    async def close_all(self) -> None:
        """Close all sessions."""
        for session in self._sessions.values():
            await session.stop()
        self._sessions.clear()
