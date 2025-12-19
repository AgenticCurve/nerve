"""CLI frontend for nerve.

Provides command-line interface for interacting with nerve.

Commands:
    nerve start     Start the nerve daemon
    nerve stop      Stop the nerve daemon
    nerve channel   Manage channels
    nerve send      Send input to a channel
    nerve dag       Execute DAGs

Example:
    $ nerve start
    $ nerve channel create --command claude --cwd /my/project
    $ nerve send channel_0 "Explain this codebase" --parser claude
    $ nerve stop
"""

from nerve.frontends.cli.main import main

__all__ = ["main"]
