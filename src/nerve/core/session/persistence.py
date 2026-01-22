"""Session persistence - save/load sessions from JSON.

Provides session state persistence for:
- Saving session metadata to disk
- Restoring sessions from saved state
- Managing a collection of saved sessions

Note: This saves session *metadata*, not running PTY state.
Sessions must be re-created to actually run commands.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from nerve.core.types import ParserType


@dataclass
class SessionMetadata:
    """Serializable session metadata.

    This represents a saved session that can be restored.
    It does NOT contain the live PTY process - just the info
    needed to recreate a session.

    Attributes:
        id: Unique session identifier.
        name: Human-readable session name.
        description: What this session is for.
        parser_type: Parser type for output (CLAUDE, GEMINI, NONE).
        command: Command that was run.
        cwd: Working directory for the session.
        tags: Optional tags for organization.
        created_at: When the session was created.
        flags: Extra metadata flags.
    """

    id: str
    name: str
    parser_type: ParserType
    command: str = ""
    description: str = ""
    cwd: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    flags: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parser": self.parser_type.value,
            "command": self.command,
            "cwd": self.cwd,
            "tags": self.tags,
            "createdAt": self.created_at.isoformat(),
            "flags": self.flags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMetadata:
        """Create from JSON dict."""
        # Handle parser type
        parser_str = data.get("parser", data.get("provider", "none"))
        try:
            parser_type = ParserType(parser_str)
        except ValueError:
            parser_type = ParserType.NONE

        # Parse datetime
        created_at = datetime.now()
        if "createdAt" in data:
            try:
                created_at = datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            parser_type=parser_type,
            command=data.get("command", ""),
            cwd=data.get("cwd"),
            tags=data.get("tags", []),
            created_at=created_at,
            flags=data.get("flags", {}),
        )


@dataclass
class SessionStore:
    """Persistent storage for session metadata.

    Manages saving and loading sessions from a JSON file.

    Example:
        >>> store = SessionStore(Path("~/.nerve/sessions.json"))
        >>> store.add(SessionMetadata(
        ...     id="abc123",
        ...     name="my-project",
        ...     parser_type=ParserType.CLAUDE_CODE,
        ...     command="claude",
        ...     cwd="/path/to/project",
        ... ))
        >>> store.save()
        >>>
        >>> # Later...
        >>> store = SessionStore.load(Path("~/.nerve/sessions.json"))
        >>> sessions = store.list()
    """

    path: Path
    sessions: list[SessionMetadata] = field(default_factory=list)
    version: str = "1.0.0"

    def add(self, session: SessionMetadata) -> None:
        """Add a session to the store.

        If a session with the same ID exists, it's replaced.

        Args:
            session: Session metadata to add.
        """
        # Remove existing if present
        self.sessions = [s for s in self.sessions if s.id != session.id]
        self.sessions.append(session)

    def remove(self, session_id: str) -> bool:
        """Remove a session by ID.

        Args:
            session_id: ID of session to remove.

        Returns:
            True if session was removed, False if not found.
        """
        original_len = len(self.sessions)
        self.sessions = [s for s in self.sessions if s.id != session_id]
        return len(self.sessions) < original_len

    def get(self, session_id: str) -> SessionMetadata | None:
        """Get a session by ID.

        Args:
            session_id: ID of session to find.

        Returns:
            SessionMetadata if found, None otherwise.
        """
        for session in self.sessions:
            if session.id == session_id:
                return session
        return None

    def find_by_name(self, name: str) -> SessionMetadata | None:
        """Find a session by name.

        Args:
            name: Name to search for.

        Returns:
            First matching SessionMetadata, or None.
        """
        for session in self.sessions:
            if session.name == name:
                return session
        return None

    def find_by_tag(self, tag: str) -> list[SessionMetadata]:
        """Find all sessions with a given tag.

        Args:
            tag: Tag to search for.

        Returns:
            List of matching sessions.
        """
        return [s for s in self.sessions if tag in s.tags]

    def list(self) -> list[SessionMetadata]:
        """List all sessions.

        Returns:
            Copy of the sessions list.
        """
        return list(self.sessions)

    def save(self) -> None:
        """Save sessions to the JSON file.

        Creates parent directories if needed.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "sessions": [s.to_dict() for s in self.sessions],
            "version": self.version,
        }

        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: Path) -> SessionStore:
        """Load sessions from a JSON file.

        Args:
            path: Path to the sessions JSON file.

        Returns:
            SessionStore with loaded sessions.
            If file doesn't exist, returns empty store.
        """
        path = Path(path).expanduser()

        if not path.exists():
            return cls(path=path)

        try:
            with open(path) as f:
                data = json.load(f)

            sessions = [SessionMetadata.from_dict(s) for s in data.get("sessions", [])]

            return cls(
                path=path,
                sessions=sessions,
                version=data.get("version", "1.0.0"),
            )
        except (OSError, json.JSONDecodeError):
            return cls(path=path)


def get_default_store_path() -> Path:
    """Get the default path for session storage.

    Returns:
        Path to ~/.nerve/sessions.json
    """
    return Path.home() / ".nerve" / "sessions.json"


def get_default_store() -> SessionStore:
    """Get or create the default session store.

    Returns:
        SessionStore at the default path.
    """
    return SessionStore.load(get_default_store_path())
