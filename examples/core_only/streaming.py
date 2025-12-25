#!/usr/bin/env python3
"""Streaming output example - using core only.

This demonstrates streaming output from a terminal node.

Usage:
    python examples/core_only/streaming.py
"""

import asyncio

from nerve.core import ParserType
from nerve.core.nodes import ExecutionContext, PTYNode
from nerve.core.session import Session


async def main():
    print("Creating Claude node...")

    # Create session and node (auto-registered)
    session = Session()
    node = await PTYNode.create(
        id="claude",
        session=session,
        command="claude",
        cwd=".",
    )

    print(f"Node ready: {node.id}")
    print()
    print("Sending prompt and streaming response...")
    print("-" * 40)

    # Stream the response
    context = ExecutionContext(
        session=session,
        input="Count from 1 to 5, one number per line.",
        parser=ParserType.CLAUDE,
    )

    async for chunk in node.execute_stream(context):
        print(chunk, end="", flush=True)

    print()
    print("-" * 40)
    print("Streaming complete.")

    await node.stop()


if __name__ == "__main__":
    asyncio.run(main())
