"""Nerve - Programmatic control layer for AI CLI agents.

Nerve provides a layered architecture for controlling AI CLI tools like
Claude Code and Gemini CLI programmatically.

Layers:
    core/       Pure business logic (PTY, parsers, DAG, sessions)
    server/     Stateful wrapper with event emission
    transport/  Communication adapters (socket, HTTP, in-process)
    frontends/  User interfaces (CLI, SDK, MCP)

Quick Start (core only):
    >>> from nerve.core import Session, CLIType
    >>> session = await Session.create(CLIType.CLAUDE)
    >>> response = await session.send("Hello!")
    >>> print(response.sections)

With server:
    >>> from nerve.server import NerveEngine
    >>> from nerve.transport import InProcessTransport
    >>> engine = NerveEngine(event_sink=transport)
"""

from nerve.__version__ import __version__

# Re-export core for convenience
from nerve.core import (
    CLIType,
    ParsedResponse,
    Section,
    Session,
    SessionState,
)

__all__ = [
    "__version__",
    "CLIType",
    "Session",
    "SessionState",
    "ParsedResponse",
    "Section",
]
