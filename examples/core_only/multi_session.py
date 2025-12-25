#!/usr/bin/env python3
"""Multi-node example - using core only.

This demonstrates managing multiple terminal nodes with Session.

Usage:
    python examples/core_only/multi_session.py
"""

import asyncio

from nerve.core import ParserType
from nerve.core.nodes import ExecutionContext, PTYNode
from nerve.core.session import Session


async def main():
    print("Creating nodes...")

    session = Session()

    # Create multiple nodes (auto-registered)
    claude1 = await PTYNode.create(id="claude-1", session=session, command="claude")
    claude2 = await PTYNode.create(id="claude-2", session=session, command="claude")

    print(f"Active nodes: {session.list_nodes()}")
    print()

    # Send messages to both
    print("Sending to claude-1...")
    ctx1 = ExecutionContext(
        session=session,
        input="Say 'Hello from node 1'",
        parser=ParserType.CLAUDE,
    )
    r1 = await claude1.execute(ctx1)
    print(f"  Response: {r1.raw[:100]}...")

    print("Sending to claude-2...")
    ctx2 = ExecutionContext(
        session=session,
        input="Say 'Hello from node 2'",
        parser=ParserType.CLAUDE,
    )
    r2 = await claude2.execute(ctx2)
    print(f"  Response: {r2.raw[:100]}...")

    print()
    print(f"Active nodes: {session.list_nodes()}")

    # Delete one node (stops and removes it)
    print("\nDeleting claude-1...")
    await session.delete_node("claude-1")
    print(f"Active nodes: {session.list_nodes()}")

    # Stop session (stops all remaining nodes)
    print("\nStopping session...")
    await session.stop()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
