"""CLI frontend for nerve.

Provides command-line interface for interacting with nerve.

Commands:
    nerve start     Start the nerve daemon
    nerve stop      Stop the nerve daemon
    nerve node      Manage nodes
    nerve send      Send input to a node
    nerve graph     Execute graphs

Example:
    $ nerve start
    $ nerve node create --command claude --cwd /my/project
    $ nerve send node_0 "Explain this codebase" --parser claude
    $ nerve stop
"""

from nerve.frontends.cli.main import main

__all__ = ["main"]
