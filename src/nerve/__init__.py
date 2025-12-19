"""Nerve - Programmatic control layer for AI CLI agents.

Nerve provides a layered architecture for controlling AI CLI tools like
Claude Code and Gemini CLI programmatically.

Layers:
    core/       Pure business logic (channels, parsers, DAG, sessions)
    server/     Stateful wrapper with event emission
    transport/  Communication adapters (socket, HTTP, in-process)
    frontends/  User interfaces (CLI, SDK, MCP)

Key Concepts:
    Channel:    Something you can send input to (terminal pane, SQL conn, etc.)
    Parser:     How to interpret output (specified per-command, not per-channel)
    Session:    Optional grouping of channels with metadata

Quick Start (direct channel usage):
    >>> from nerve import TerminalChannel, ParserType
    >>>
    >>> channel = await TerminalChannel.create(command="claude")
    >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    >>> print(response.sections)
    >>> await channel.close()

With WezTerm backend:
    >>> from nerve import TerminalChannel, ParserType, BackendType
    >>>
    >>> channel = await TerminalChannel.create(
    ...     command="claude",
    ...     backend_type=BackendType.WEZTERM,
    ... )
    >>> # Channel runs in a visible WezTerm pane

Attach to existing WezTerm pane:
    >>> channel = await TerminalChannel.attach(pane_id="4")

With session grouping:
    >>> from nerve import Session, TerminalChannel, ParserType
    >>>
    >>> session = Session(name="my-project")
    >>> claude = await TerminalChannel.create(command="claude")
    >>> session.add("claude", claude)
    >>> response = await session.send("claude", "Hello!", parser=ParserType.CLAUDE)

With server:
    >>> from nerve.server import NerveEngine
    >>> from nerve.transport import InProcessTransport
    >>> engine = NerveEngine(event_sink=transport)
"""

from nerve.__version__ import __version__

# Re-export core for convenience
from nerve.core import (
    BackendType,
    Channel,
    ChannelManager,
    ChannelState,
    ChannelType,
    ParsedResponse,
    ParserType,
    Section,
    Session,
    SessionManager,
    SessionState,
    TerminalChannel,
)

__all__ = [
    "__version__",
    # Channels
    "Channel",
    "ChannelState",
    "ChannelType",
    "TerminalChannel",
    # Session
    "Session",
    "SessionManager",
    "ChannelManager",
    "SessionState",
    # Types
    "BackendType",
    "ParserType",
    "ParsedResponse",
    "Section",
]
