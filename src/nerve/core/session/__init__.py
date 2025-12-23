"""Session management.

Sessions are logical groupings of nodes with metadata.
Use NodeFactory to create nodes, and Session.register() to add them.

Example (standalone nodes):
    >>> from nerve.core.nodes import NodeFactory
    >>> from nerve.core.session import Session
    >>>
    >>> factory = NodeFactory()
    >>> node = await factory.create_terminal("my-node", command="bash")
    >>>
    >>> session = Session()
    >>> session.register(node)
    >>> await session.stop()

Example (with session manager):
    >>> from nerve.core.nodes import NodeFactory
    >>> from nerve.core.session import Session, SessionManager
    >>>
    >>> manager = SessionManager()
    >>> factory = NodeFactory()
    >>>
    >>> session = manager.create_session(name="my-project")
    >>> node = await factory.create_terminal("claude", command="claude")
    >>> session.register(node)
    >>>
    >>> await manager.close_session(session.id)
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
    # Session
    "Session",
    # Manager
    "SessionManager",
    # Persistence
    "SessionMetadata",
    "SessionStore",
    "get_default_store",
    "get_default_store_path",
]
