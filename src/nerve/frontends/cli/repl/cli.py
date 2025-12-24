"""CLI entry point for REPL."""

from __future__ import annotations

import argparse
import asyncio

from nerve.frontends.cli.repl.core import run_interactive
from nerve.frontends.cli.repl.file_runner import run_from_file


def main():
    """CLI entry point for REPL."""
    parser = argparse.ArgumentParser(
        description="Nerve Graph REPL - Interactive Graph definition and execution"
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Python file containing Graph definition",
    )
    parser.add_argument(
        "--dry-run",
        "-d",
        action="store_true",
        help="Show execution order without running",
    )

    args = parser.parse_args()

    if args.file:
        asyncio.run(run_from_file(args.file, dry_run=args.dry_run))
    else:
        asyncio.run(run_interactive())


if __name__ == "__main__":
    main()
