#!/usr/bin/env python3
"""Simple channel example - using core only, no server.

This demonstrates using nerve.core directly for basic AI CLI interaction.
No server, no transport, no events - just pure Python.

Usage:
    python examples/core_only/simple_session.py
"""

import asyncio

from nerve.core import ParserType, PTYChannel


async def main():
    print("Creating Claude channel...")

    # Create a terminal channel directly using core
    channel = await PTYChannel.create(
        command="claude",
        cwd=".",  # Current directory
    )

    print(f"Channel created: {channel.id}")
    print(f"State: {channel.state}")
    print()

    # Send a simple message with Claude parsing
    print("Sending: 'What is 2 + 2?'")
    print("-" * 40)

    response = await channel.send(
        "What is 2 + 2? Reply with just the number.",
        parser=ParserType.CLAUDE,
    )

    print(f"Response ({len(response.sections)} sections):")
    for section in response.sections:
        print(f"  [{section.type}] {section.content[:200]}")

    if response.tokens:
        print(f"\nTokens used: {response.tokens}")

    # Clean up
    await channel.close()
    print("\nChannel closed.")


if __name__ == "__main__":
    asyncio.run(main())
