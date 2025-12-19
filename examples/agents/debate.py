#!/usr/bin/env python3
"""Multi-agent debate example.

This demonstrates two Claude instances debating each other.
Ported from the original wezterm dag_debate.py.

Usage:
    python examples/agents/debate.py
"""

import asyncio

from nerve.core import CLIType, Session

ROUNDS = 3


async def main():
    print("Setting up debate between two Claude instances...")
    print()

    # Create two sessions
    advocate_python = await Session.create(CLIType.CLAUDE, session_id="python-advocate")
    advocate_js = await Session.create(CLIType.CLAUDE, session_id="js-advocate")

    print(f"Python advocate: {advocate_python.id}")
    print(f"JavaScript advocate: {advocate_js.id}")
    print()

    message = "Let's debate: Is Python better than JavaScript? Keep responses under 100 words."

    print(f"Starting debate: Python vs JavaScript ({ROUNDS} rounds)")
    print("=" * 60)

    for round_num in range(1, ROUNDS + 1):
        print(f"\n--- Round {round_num} ---\n")

        # Python advocate's turn
        prompt = f"[Round {round_num}] You're arguing FOR Python. Opponent said: {message}. Keep it under 100 words."
        response = await advocate_python.send(prompt)
        message = response.raw[:500]
        print(f"[PYTHON]: {message[:300]}...")

        # JavaScript advocate's turn
        prompt = f"[Round {round_num}] You're arguing FOR JavaScript. Opponent said: {message}. Keep it under 100 words."
        response = await advocate_js.send(prompt)
        message = response.raw[:500]
        print(f"[JAVASCRIPT]: {message[:300]}...")

    print("\n" + "=" * 60)
    print("Debate finished!")

    # Clean up
    await advocate_python.close()
    await advocate_js.close()


if __name__ == "__main__":
    asyncio.run(main())
