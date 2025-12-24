"""Interactive REPL for nerve - modular structure.

This module provides an interactive Python REPL environment for
defining and executing nerve Graphs.

Public API:
    run_interactive: Main interactive REPL function
    run_from_file: Execute graph from Python file
    main: CLI entry point
    REPLState: REPL state management
    SessionAdapter: Protocol for session operations
"""

from __future__ import annotations

from nerve.frontends.cli.repl.adapters import (
    LocalSessionAdapter,
    RemoteSessionAdapter,
    SessionAdapter,
)
from nerve.frontends.cli.repl.cli import main
from nerve.frontends.cli.repl.core import run_interactive
from nerve.frontends.cli.repl.file_runner import run_from_file
from nerve.frontends.cli.repl.state import REPLState

__all__ = [
    "main",
    "run_interactive",
    "run_from_file",
    "REPLState",
    "SessionAdapter",
    "LocalSessionAdapter",
    "RemoteSessionAdapter",
]
