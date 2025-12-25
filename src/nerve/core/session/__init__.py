"""Session management - central workspace abstraction.

Session is the central workspace for nodes and graphs. All nodes and graphs
take a session parameter and auto-register on creation.

Example:
    >>> from nerve.core.session import Session
    >>> from nerve.core.nodes.terminal import PTYNode
    >>> from nerve.core.nodes.graph import Graph
    >>>
    >>> # Create session
    >>> session = Session(name="my-project")
    >>>
    >>> # Create nodes (auto-registered)
    >>> claude = await PTYNode.create(id="claude", session=session, command="claude")
    >>> shell = await PTYNode.create(id="shell", session=session, command="bash")
    >>>
    >>> # Create graphs (auto-registered)
    >>> workflow = Graph(id="workflow", session=session)
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
    >>> from nerve.core.nodes.terminal import PTYNode
    >>>
    >>> manager = SessionManager()
    >>> session = manager.create_session(name="my-project")
    >>> node = await PTYNode.create(id="claude", session=session, command="claude")
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
