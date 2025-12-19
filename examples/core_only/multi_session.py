#!/usr/bin/env python3
"""Multi-session example - using core only.

This demonstrates managing multiple AI CLI sessions.

Usage:
    python examples/core_only/multi_session.py
"""

import asyncio

from nerve.core import CLIType, SessionManager


async def main():
    print("Creating session manager...")

    manager = SessionManager()

    # Create multiple sessions
    claude1 = await manager.create(CLIType.CLAUDE, session_id="claude-1")
    claude2 = await manager.create(CLIType.CLAUDE, session_id="claude-2")

    print(f"Active sessions: {manager.list()}")
    print()

    # Send messages to both
    print("Sending to claude-1...")
    r1 = await claude1.send("Say 'Hello from session 1'")
    print(f"  Response: {r1.raw[:100]}...")

    print("Sending to claude-2...")
    r2 = await claude2.send("Say 'Hello from session 2'")
    print(f"  Response: {r2.raw[:100]}...")

    print()
    print(f"Active sessions: {manager.list_active()}")

    # Close one
    print("\nClosing claude-1...")
    await manager.close("claude-1")
    print(f"Active sessions: {manager.list_active()}")

    # Close all
    print("\nClosing all sessions...")
    await manager.close_all()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
