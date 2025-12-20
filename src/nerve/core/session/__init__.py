"""Session and channel management.

Sessions are optional logical groupings of channels with metadata.
Channels are the actual connections (terminal panes, SQL connections, etc.).

Two levels of management:
- ChannelManager: Manage channels directly (no grouping)
- SessionManager: Manage sessions (groups of channels)

Example (channels only):
    >>> from nerve.core.channels import PTYChannel
    >>> from nerve.core.session import ChannelManager
    >>>
    >>> manager = ChannelManager()
    >>> channel = await manager.create_terminal("my-claude", command="claude")
    >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    >>> await manager.close_all()

Example (with sessions):
    >>> from nerve.core.channels import PTYChannel
    >>> from nerve.core.session import Session, SessionManager
    >>>
    >>> manager = SessionManager()
    >>> session = manager.create_session(name="my-project")
    >>>
    >>> claude = await PTYChannel.create("claude", command="claude")
    >>> session.add("claude", claude)
    >>>
    >>> response = await session.send("claude", "Hello!", parser=ParserType.CLAUDE)
    >>> await session.close()
"""

from nerve.core.session.manager import ChannelManager, SessionManager
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
    # Managers
    "ChannelManager",
    "SessionManager",
    # Persistence
    "SessionMetadata",
    "SessionStore",
    "get_default_store",
    "get_default_store_path",
]
