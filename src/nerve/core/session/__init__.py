"""Session abstraction - combines PTY and Parser.

A Session is a high-level interface to an AI CLI instance.
It manages the PTY process and uses the appropriate parser.

Still pure library code - no server awareness, no events.

Classes:
    Session: Single AI CLI session.
    SessionManager: Manage multiple sessions.
    SessionMetadata: Serializable session info for persistence.
    SessionStore: Save/load sessions from JSON.

Example:
    >>> from nerve.core.session import Session
    >>> from nerve.core.types import CLIType
    >>>
    >>> async def main():
    ...     session = await Session.create(CLIType.CLAUDE, cwd="/project")
    ...
    ...     response = await session.send("Explain this codebase")
    ...     for section in response.sections:
    ...         print(f"[{section.type}] {section.content[:100]}")
    ...
    ...     await session.close()
"""

from nerve.core.session.manager import SessionManager
from nerve.core.session.persistence import (
    SessionMetadata,
    SessionStore,
    get_default_store,
    get_default_store_path,
)
from nerve.core.session.session import Session

__all__ = [
    "Session",
    "SessionManager",
    "SessionMetadata",
    "SessionStore",
    "get_default_store",
    "get_default_store_path",
]
