#!/usr/bin/env python3
"""In-process server example - no sockets, direct communication.

This demonstrates using nerve with an in-process transport,
useful for embedding nerve in an application.

Usage:
    python examples/embedded/in_process.py
"""

import asyncio

from nerve.server import Command, CommandType, NerveEngine
from nerve.transport import InProcessTransport


async def main():
    print("Setting up in-process nerve...")

    # Create transport and engine
    transport = InProcessTransport()
    engine = NerveEngine(event_sink=transport)
    transport.bind(engine)

    print("Engine ready.")
    print()

    # Create a channel via command
    print("Creating channel...")
    result = await transport.send_command(
        Command(
            type=CommandType.CREATE_CHANNEL,
            params={"command": "claude"},
        )
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    channel_id = result.data["channel_id"]
    print(f"Channel created: {channel_id}")

    # Start listening for events in background
    async def print_events():
        async for event in transport.events():
            print(f"  [EVENT] {event.type.name}: {event.data}")

    event_task = asyncio.create_task(print_events())

    # Send input
    print()
    print("Sending input...")
    result = await transport.send_command(
        Command(
            type=CommandType.SEND_INPUT,
            params={
                "channel_id": channel_id,
                "text": "What is the capital of France? One word answer.",
                "parser": "claude",
                "stream": True,
            },
        )
    )

    if result.success:
        print(f"Response: {result.data.get('response', '')[:200]}")
    else:
        print(f"Error: {result.error}")

    # Clean up
    await asyncio.sleep(0.5)  # Let events flush
    event_task.cancel()

    await transport.send_command(
        Command(
            type=CommandType.CLOSE_CHANNEL,
            params={"channel_id": channel_id},
        )
    )

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
