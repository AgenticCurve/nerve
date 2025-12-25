"""SessionRegistry - Central registry for session state with dynamic lookup.

This module solves the shared mutable state bug that occurs when passing
_default_session as a reference to multiple handlers. Python doesn't share
references across assignments - each handler gets a copy of the reference.

SessionRegistry uses dynamic property lookup to ensure all handlers always
see the current default session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nerve.core.session import Session


@dataclass
class SessionRegistry:
    """Central registry for session state with dynamic lookup.

    All handlers receive a reference to this registry instead of raw session
    state. This ensures:
    - All handlers always see current default session (dynamic lookup)
    - SessionHandler controls all session access
    - Proper encapsulation (no direct dict access)
    - Single source of truth

    Example:
        >>> registry = SessionRegistry()
        >>> session = Session(name="default", server_name="test")
        >>> registry.add_session("default", session)
        >>> registry.set_default("default")
        >>>
        >>> # All handlers can now access sessions through registry
        >>> session = registry.get_session(None)  # Returns default
        >>> session = registry.get_session("default")  # Returns by name
    """

    _sessions: dict[str, Session] = field(default_factory=dict)
    _default_session_name: str | None = field(default=None)

    @property
    def default_session(self) -> Session | None:
        """Get current default session (dynamic lookup).

        Returns:
            The default session, or None if not set.
        """
        if not self._default_session_name:
            return None
        return self._sessions.get(self._default_session_name)

    @property
    def default_session_name(self) -> str | None:
        """Get the name of the default session.

        Returns:
            The default session name, or None if not set.
        """
        return self._default_session_name

    def set_default(self, session_name: str) -> None:
        """Set default session by name.

        Args:
            session_name: Name of the session to set as default.

        Raises:
            ValueError: If session doesn't exist.
        """
        if session_name not in self._sessions:
            raise ValueError(f"Cannot set default: session '{session_name}' not found")
        self._default_session_name = session_name

    def get_session(self, session_id: str | None) -> Session:
        """Get session by ID or return default.

        Args:
            session_id: Session identifier (name), or None for default.

        Returns:
            The requested session.

        Raises:
            ValueError: If session not found or no default session.
        """
        if session_id:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session not found: {session_id}")
            return session

        default = self.default_session
        if default is None:
            raise ValueError("No default session")
        return default

    def has_session(self, name: str) -> bool:
        """Check if session exists (for duplicate detection).

        Args:
            name: Session name to check.

        Returns:
            True if session exists, False otherwise.
        """
        return name in self._sessions

    def add_session(self, name: str, session: Session) -> None:
        """Register new session.

        Args:
            name: Session name (key for registry).
            session: Session instance to register.
        """
        self._sessions[name] = session

    def remove_session(self, name: str) -> Session | None:
        """Unregister session.

        Args:
            name: Session name to remove.

        Returns:
            The removed session, or None if not found.
        """
        return self._sessions.pop(name, None)

    def list_session_names(self) -> list[str]:
        """List all session names.

        Returns:
            List of session names.
        """
        return list(self._sessions.keys())

    def get_all_sessions(self) -> list[Session]:
        """Get all Session objects (for cleanup iteration).

        Returns:
            List of all Session objects.
        """
        return list(self._sessions.values())

    def session_count(self) -> int:
        """Get the number of registered sessions.

        Returns:
            Number of sessions.
        """
        return len(self._sessions)
