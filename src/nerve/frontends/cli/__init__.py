"""CLI frontend for nerve.

Provides command-line interface for interacting with nerve.

Commands:
    nerve start     Start the nerve daemon
    nerve stop      Stop the nerve daemon
    nerve session   Manage sessions
    nerve send      Send input to a session
    nerve dag       Execute DAGs

Example:
    $ nerve start
    $ nerve session create --type claude --cwd /my/project
    $ nerve send session_0 "Explain this codebase"
    $ nerve stop
"""

from nerve.frontends.cli.main import main

__all__ = ["main"]
