#!/usr/bin/env python3
"""Streaming output example - using core only.

This demonstrates streaming output from an AI CLI session.

Usage:
    python examples/core_only/streaming.py
"""

import asyncio

from nerve.core import CLIType, Session


async def main():
    print("Creating Claude session...")

    session = await Session.create(
        cli_type=CLIType.CLAUDE,
        cwd=".",
    )

    print(f"Session ready: {session.id}")
    print()
    print("Sending prompt and streaming response...")
    print("-" * 40)

    # Stream the response
    async for chunk in session.send_stream("Count from 1 to 5, one number per line."):
        print(chunk, end="", flush=True)

    print()
    print("-" * 40)
    print("Streaming complete.")

    await session.close()


if __name__ == "__main__":
    asyncio.run(main())
