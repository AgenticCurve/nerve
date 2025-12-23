"""Session management - central workspace abstraction.

Session is the central workspace that creates, registers, and manages
nodes and graphs.

Example:
    >>> from nerve.core.session import Session, BackendType
    >>>
    >>> # Create session
    >>> session = Session(name="my-project")
    >>>
    >>> # Create nodes (auto-registered)
    >>> claude = await session.create_node("claude", command="claude")
    >>> shell = await session.create_node("shell", command="bash")
    >>>
    >>> # Create graphs (auto-registered)
    >>> workflow = session.create_graph("workflow")
    >>> workflow.add_step(claude, step_id="step1", input="Hello")
    >>>
    >>> # Execute
    >>> from nerve.core.nodes import ExecutionContext
    >>> context = ExecutionContext(session=session, input="...")
    >>> result = await claude.execute(context)
    >>>
    >>> # Cleanup
    >>> await session.stop()

Example (with session manager):
    >>> from nerve.core.session import Session, SessionManager
    >>>
    >>> manager = SessionManager()
    >>> session = manager.create_session(name="my-project")
    >>> node = await session.create_node("claude", command="claude")
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
from nerve.core.session.session import BackendType, Session

__all__ = [
    # Session
    "Session",
    "BackendType",
    # Manager
    "SessionManager",
    # Persistence
    "SessionMetadata",
    "SessionStore",
    "get_default_store",
    "get_default_store_path",
]
