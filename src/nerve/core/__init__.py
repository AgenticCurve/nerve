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

Modules:
    pty/        PTY process management
    parsers/    AI CLI output parsers (Claude, Gemini)
    dag/        DAG task orchestration
    session/    Session abstraction (PTY + Parser)
    types       Pure data types

Example:
    >>> from nerve.core import Session, CLIType
    >>>
    >>> async def main():
    ...     session = await Session.create(CLIType.CLAUDE, cwd="/my/project")
    ...     response = await session.send("Explain this codebase")
    ...     for section in response.sections:
    ...         print(f"[{section.type}] {section.content[:100]}")
    ...     await session.close()
"""

from nerve.core.dag import DAG, Task, TaskStatus
from nerve.core.parsers import ClaudeParser, GeminiParser, get_parser
from nerve.core.pty import PTYConfig, PTYManager, PTYProcess
from nerve.core.session import (
    Session,
    SessionManager,
    SessionMetadata,
    SessionStore,
    get_default_store,
)
from nerve.core.types import (
    CLIType,
    ParsedResponse,
    Section,
    SessionState,
    TaskResult,
)

__all__ = [
    # Types
    "CLIType",
    "SessionState",
    "Section",
    "ParsedResponse",
    "TaskResult",
    # Session
    "Session",
    "SessionManager",
    "SessionMetadata",
    "SessionStore",
    "get_default_store",
    # PTY
    "PTYProcess",
    "PTYConfig",
    "PTYManager",
    # Parsers
    "ClaudeParser",
    "GeminiParser",
    "get_parser",
    # DAG
    "DAG",
    "Task",
    "TaskStatus",
]
