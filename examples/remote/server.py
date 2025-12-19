#!/usr/bin/env python3
"""Remote server example - run nerve as a daemon.

This starts nerve as a server listening on a Unix socket.
Clients can connect to interact with AI CLIs.

Usage:
    python examples/remote/server.py

Then in another terminal:
    python examples/remote/client.py
"""

import asyncio

from nerve.server import NerveEngine
from nerve.transport import UnixSocketServer

SOCKET_PATH = "/tmp/nerve-example.sock"


async def main():
    print("Starting nerve server...")

    transport = UnixSocketServer(SOCKET_PATH)
    engine = NerveEngine(event_sink=transport)

    print(f"Listening on: {SOCKET_PATH}")
    print("Press Ctrl+C to stop.")
    print()

    try:
        await transport.serve(engine)
    except KeyboardInterrupt:
        print("\nShutting down...")
        await transport.stop()


if __name__ == "__main__":
    asyncio.run(main())
