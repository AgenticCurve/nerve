#!/usr/bin/env python3
"""Multi-node example - using core only.

This demonstrates managing multiple terminal nodes with Session.

Usage:
    python examples/core_only/multi_session.py
"""

import asyncio

from nerve.core import ParserType
from nerve.core.nodes import ExecutionContext, NodeFactory
from nerve.core.session import Session


async def main():
    print("Creating nodes...")

    factory = NodeFactory()
    session = Session()

    # Create multiple nodes
    claude1 = await factory.create_terminal(node_id="claude-1", command="claude")
    claude2 = await factory.create_terminal(node_id="claude-2", command="claude")

    # Register in session
    session.register(claude1)
    session.register(claude2)

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

    # Unregister and stop one
    print("\nStopping claude-1...")
    session.unregister("claude-1")
    await claude1.stop()
    print(f"Active nodes: {session.list_nodes()}")

    # Stop session (stops all remaining nodes)
    print("\nStopping session...")
    await session.stop()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
