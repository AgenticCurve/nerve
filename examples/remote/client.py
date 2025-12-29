#!/usr/bin/env python3
"""Remote client example - connect to nerve server.

This connects to a running nerve server and interacts with it.

Usage:
    # First, start the server:
    python examples/remote/server.py

    # Then run this client:
    python examples/remote/client.py
"""

import asyncio

from nerve.frontends.sdk import NerveClient

SOCKET_PATH = "/tmp/nerve-example.sock"


async def main():
    print(f"Connecting to nerve server at {SOCKET_PATH}...")

    client = await NerveClient.connect(SOCKET_PATH)
    print("Connected.")
    print()

    # Create a session
    print("Creating Claude session...")
    session = await client.create_session("claude", cwd=".")
    print(f"Session created: {session.id}")
    print()

    # Send a message
    print("Sending message...")
    response = await session.send("Hello! Please respond with just 'Hi there!'")
    print(f"Response: {(response.get('raw') or '')[:200]}")
    print()

    # List sessions
    sessions = await client.list_sessions()
    print(f"Active sessions: {sessions}")

    # Close session
    print("\nClosing session...")
    await session.close()

    # Disconnect
    await client.disconnect()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
