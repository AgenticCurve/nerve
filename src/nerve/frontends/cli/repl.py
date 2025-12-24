"""Interactive Graph REPL for nerve.

Ported from wezterm's run_commands.py - provides an interactive
environment for defining and executing Graphs.

Usage:
    nerve repl                    # Interactive mode
    nerve repl script.py          # Load and run from file
    nerve repl script.py --dry    # Dry run from file

Note: This module has been refactored into a modular structure under repl/.
      This file now serves as a compatibility layer.
"""

from __future__ import annotations

# Import and re-export from modular structure
from nerve.frontends.cli.repl import (
    LocalSessionAdapter,
    RemoteSessionAdapter,
    REPLState,
    SessionAdapter,
    main,
    run_from_file,
    run_interactive,
)

__all__ = [
    "SessionAdapter",
    "LocalSessionAdapter",
    "RemoteSessionAdapter",
    "REPLState",
    "run_interactive",
    "run_from_file",
    "main",
]


if __name__ == "__main__":
    main()
