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

Quick Start (PTY channel - you own the process):
    >>> from nerve import PTYChannel, ParserType
    >>>
    >>> channel = await PTYChannel.create("my-claude", command="claude")
    >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    >>> print(response.sections)
    >>> await channel.close()

WezTerm channel (spawn new pane):
    >>> from nerve import WezTermChannel, ParserType
    >>>
    >>> channel = await WezTermChannel.create("claude", command="claude")
    >>> response = await channel.send("Hello!", parser=ParserType.CLAUDE)
    >>> # Channel runs in a visible WezTerm pane

Attach to existing WezTerm pane:
    >>> channel = await WezTermChannel.attach("claude-pane", pane_id="4")

With session grouping:
    >>> from nerve import Session, PTYChannel, ParserType
    >>>
    >>> session = Session(name="my-project")
    >>> claude = await PTYChannel.create("claude", command="claude")
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
    PTYChannel,
    Section,
    Session,
    SessionManager,
    SessionState,
    WezTermChannel,
)

__all__ = [
    "__version__",
    # Channels
    "Channel",
    "ChannelState",
    "ChannelType",
    "PTYChannel",
    "WezTermChannel",
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
