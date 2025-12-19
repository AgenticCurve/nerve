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
    channels/   Channel abstraction (terminal, SQL, HTTP)
    pty/        PTY/WezTerm backends for terminal channels
    parsers/    Output parsers (Claude, Gemini, None)
    session/    Session grouping and management
    dag/        DAG task orchestration
    types       Pure data types

Key Concepts:
    Channel:    Something you can send input to (terminal pane, SQL conn, etc.)
    Parser:     How to interpret output (specified per-command, not per-channel)
    Session:    Optional grouping of channels with metadata

Example (direct channel usage):
    >>> from nerve.core import TerminalChannel, ParserType
    >>>
    >>> async def main():
    ...     # Create a terminal channel
    ...     channel = await TerminalChannel.create(command="claude")
    ...
    ...     # Send with Claude parsing
    ...     response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    ...     print(response.sections)
    ...
    ...     # Same channel, different command
    ...     await channel.send("exit")
    ...     response = await channel.send("echo hi", parser=ParserType.NONE)
    ...
    ...     await channel.close()

Example (with session grouping):
    >>> from nerve.core import Session, TerminalChannel, ParserType
    >>>
    >>> async def main():
    ...     session = Session(name="my-project")
    ...
    ...     claude = await TerminalChannel.create(command="claude")
    ...     shell = await TerminalChannel.create(command="bash")
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
    TerminalChannel,
    TerminalConfig,
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

__all__ = [
    # Channel abstraction
    "Channel",
    "ChannelState",
    "ChannelType",
    "ChannelConfig",
    "ChannelInfo",
    "TerminalChannel",
    "TerminalConfig",
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
]
