#!/usr/bin/env python3
"""Streaming output example - using core only.

This demonstrates streaming output from a terminal channel.

Usage:
    python examples/core_only/streaming.py
"""

import asyncio

from nerve.core import ParserType, PTYChannel


async def main():
    print("Creating Claude channel...")

    channel = await PTYChannel.create(
        command="claude",
        cwd=".",
    )

    print(f"Channel ready: {channel.id}")
    print()
    print("Sending prompt and streaming response...")
    print("-" * 40)

    # Stream the response
    async for chunk in channel.send_stream(
        "Count from 1 to 5, one number per line.",
        parser=ParserType.CLAUDE,
    ):
        print(chunk, end="", flush=True)

    print()
    print("-" * 40)
    print("Streaming complete.")

    await channel.close()


if __name__ == "__main__":
    asyncio.run(main())
