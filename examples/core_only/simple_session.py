#!/usr/bin/env python3
"""Simple session example - using core only, no server.

This demonstrates using nerve.core directly for basic AI CLI interaction.
No server, no transport, no events - just pure Python.

Usage:
    python examples/core_only/simple_session.py
"""

import asyncio

from nerve.core import CLIType, Session


async def main():
    print("Creating Claude session...")

    # Create a session directly using core
    session = await Session.create(
        cli_type=CLIType.CLAUDE,
        cwd=".",  # Current directory
    )

    print(f"Session created: {session.id}")
    print(f"State: {session.state}")
    print()

    # Send a simple message
    print("Sending: 'What is 2 + 2?'")
    print("-" * 40)

    response = await session.send("What is 2 + 2? Reply with just the number.")

    print(f"Response ({len(response.sections)} sections):")
    for section in response.sections:
        print(f"  [{section.type}] {section.content[:200]}")

    if response.tokens:
        print(f"\nTokens used: {response.tokens}")

    # Clean up
    await session.close()
    print("\nSession closed.")


if __name__ == "__main__":
    asyncio.run(main())
