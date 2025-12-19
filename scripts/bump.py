#!/usr/bin/env python3
"""Bump version and reinstall package."""

import subprocess
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run scripts/bump.py [patch|minor|major]")
        sys.exit(1)

    bump_type = sys.argv[1]
    if bump_type not in ("patch", "minor", "major"):
        print(f"Invalid bump type: {bump_type}")
        print("Must be one of: patch, minor, major")
        sys.exit(1)

    # Bump version
    print(f"Bumping {bump_type} version...")
    result = subprocess.run(
        ["hatch", "version", bump_type],
        capture_output=True,
        text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr)
        sys.exit(1)

    # Reinstall
    print("Reinstalling package...")
    result = subprocess.run(
        ["uv", "pip", "install", "-e", "."],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr)
        sys.exit(1)

    # Show new version
    result = subprocess.run(
        ["uv", "run", "nerve", "--version"],
        capture_output=True,
        text=True,
    )
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
