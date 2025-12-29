#!/usr/bin/env python3
"""Simple node example - using core only, no server.

This demonstrates using nerve.core directly for basic AI CLI interaction.
No server, no transport, no events - just pure Python.

Usage:
    python examples/core_only/simple_session.py
"""

import asyncio

from nerve.core import ParserType
from nerve.core.nodes import ExecutionContext, PTYNode
from nerve.core.session import Session


async def main():
    print("Creating Claude node...")

    # Create session and node (node is auto-registered)
    session = Session()
    node = await PTYNode.create(
        id="claude",
        session=session,
        command="claude",
        cwd=".",  # Current directory
    )

    print(f"Node created: {node.id}")
    print(f"State: {node.state}")
    print()

    # Send a simple message with Claude parsing
    print("Sending: 'What is 2 + 2?'")
    print("-" * 40)

    context = ExecutionContext(
        session=session,
        input="What is 2 + 2? Reply with just the number.",
        parser=ParserType.CLAUDE,
    )
    response = await node.execute(context)

    # Response is now a dict with success/error/output fields
    sections = response["sections"]
    print(f"Response ({len(sections)} sections):")
    for section in sections:
        print(f"  [{section['type']}] {section['content'][:200]}")

    if response.get("tokens"):
        print(f"\nTokens used: {response['tokens']}")

    # Clean up
    await node.stop()
    print("\nNode stopped.")


if __name__ == "__main__":
    asyncio.run(main())
