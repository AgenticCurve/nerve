"""Core - Pure business logic for AI CLI control.

This module contains no knowledge of:
- Servers, clients, or networking
- Event systems or callbacks
- How it will be used

It's just pure Python primitives that can be used anywhere:
- In scripts
- In Jupyter notebooks
- Embedded in applications
- As building blocks for servers

Architecture:
    channels/   Channel abstraction (PTY, WezTerm, SQL, HTTP)
    pty/        PTY/WezTerm backends for terminal channels
    parsers/    Output parsers (Claude, Gemini, None)
    session/    Session grouping and management
    dag/        DAG task orchestration
    types       Pure data types

Key Concepts:
    Channel:    Something you can send input to (terminal pane, SQL conn, etc.)
    Parser:     How to interpret output (specified per-command, not per-channel)
    Session:    Optional grouping of channels with metadata

Example (PTY channel - you own the process):
    >>> from nerve.core import PTYChannel, ParserType
    >>>
    >>> async def main():
    ...     channel = await PTYChannel.create("my-claude", command="claude")
    ...     response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    ...     print(response.sections)
    ...     await channel.close()

Example (WezTerm channel - attach to existing pane):
    >>> from nerve.core import WezTermChannel, ParserType
    >>>
    >>> async def main():
    ...     channel = await WezTermChannel.attach("claude-pane", pane_id="4")
    ...     response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    ...     print(response.sections)
    ...     await channel.close()

Example (with session grouping):
    >>> from nerve.core import Session, PTYChannel, ParserType
    >>>
    >>> async def main():
    ...     session = Session(name="my-project")
    ...
    ...     claude = await PTYChannel.create("claude", command="claude")
    ...     shell = await PTYChannel.create("shell", command="bash")
    ...
    ...     session.add("claude", claude)
    ...     session.add("shell", shell)
    ...
    ...     response = await session.send("claude", "Hello!", parser=ParserType.CLAUDE)
    ...     await session.close()
"""

from nerve.core.channels import (
    Channel,
    ChannelConfig,
    ChannelInfo,
    ChannelState,
    ChannelType,
    PTYChannel,
    PTYConfig,
    WezTermChannel,
    WezTermConfig,
)
from nerve.core.dag import DAG, Task, TaskStatus
from nerve.core.parsers import ClaudeParser, GeminiParser, NoneParser, get_parser
from nerve.core.pty import (
    Backend,
    BackendConfig,
    BackendType,
    PTYBackend,
    PTYConfig,
    PTYManager,
    PTYProcess,
    WezTermBackend,
    get_backend,
    is_wezterm_available,
)
from nerve.core.session import (
    ChannelManager,
    Session,
    SessionManager,
    SessionMetadata,
    SessionStore,
    get_default_store,
)
from nerve.core.types import (
    ParsedResponse,
    ParserType,
    Section,
    SessionState,
    TaskResult,
)

# Lazy imports for optional proxy components (require pydantic)
def __getattr__(name: str):
    """Lazy import for optional proxy modules."""
    if name in ("transforms", "clients"):
        import importlib
        return importlib.import_module(f"nerve.core.{name}")
    raise AttributeError(f"module 'nerve.core' has no attribute {name!r}")

__all__ = [
    # Channel abstraction
    "Channel",
    "ChannelState",
    "ChannelType",
    "ChannelConfig",
    "ChannelInfo",
    # Channel types
    "PTYChannel",
    "PTYConfig",
    "WezTermChannel",
    "WezTermConfig",
    # Types
    "ParserType",
    "SessionState",
    "Section",
    "ParsedResponse",
    "TaskResult",
    # Session
    "Session",
    "ChannelManager",
    "SessionManager",
    "SessionMetadata",
    "SessionStore",
    "get_default_store",
    # Backends
    "Backend",
    "BackendConfig",
    "BackendType",
    "get_backend",
    "PTYBackend",
    "WezTermBackend",
    "is_wezterm_available",
    # PTY (legacy)
    "PTYProcess",
    "PTYConfig",
    "PTYManager",
    # Parsers
    "ClaudeParser",
    "GeminiParser",
    "NoneParser",
    "get_parser",
    # DAG
    "DAG",
    "Task",
    "TaskStatus",
    # Proxy components (lazy loaded)
    "transforms",
    "clients",
]
