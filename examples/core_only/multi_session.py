#!/usr/bin/env python3
"""Multi-channel example - using core only.

This demonstrates managing multiple terminal channels.

Usage:
    python examples/core_only/multi_session.py
"""

import asyncio

from nerve.core import ChannelManager, ParserType


async def main():
    print("Creating channel manager...")

    manager = ChannelManager()

    # Create multiple channels
    claude1 = await manager.create_terminal(command="claude", channel_id="claude-1")
    claude2 = await manager.create_terminal(command="claude", channel_id="claude-2")

    print(f"Active channels: {manager.list()}")
    print()

    # Send messages to both
    print("Sending to claude-1...")
    r1 = await claude1.send("Say 'Hello from channel 1'", parser=ParserType.CLAUDE)
    print(f"  Response: {r1.raw[:100]}...")

    print("Sending to claude-2...")
    r2 = await claude2.send("Say 'Hello from channel 2'", parser=ParserType.CLAUDE)
    print(f"  Response: {r2.raw[:100]}...")

    print()
    print(f"Active channels: {manager.list_open()}")

    # Close one
    print("\nClosing claude-1...")
    await manager.close("claude-1")
    print(f"Active channels: {manager.list_open()}")

    # Close all
    print("\nClosing all channels...")
    await manager.close_all()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
