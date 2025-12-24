#!/usr/bin/env python3
"""Multi-agent debate example.

This demonstrates two Claude instances debating each other.
Ported from the original wezterm dag_debate.py.

Usage:
    python examples/agents/debate.py
"""

import asyncio

from nerve.core import ParserType
from nerve.core.nodes import ExecutionContext
from nerve.core.session import Session

ROUNDS = 3


async def main():
    print("Setting up debate between two Claude instances...")
    print()

    # Create session and nodes (nodes are auto-registered)
    session = Session()

    advocate_python = await session.create_node(node_id="python-advocate", command="claude")
    advocate_js = await session.create_node(node_id="js-advocate", command="claude")

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
        context = ExecutionContext(
            session=session,
            input=prompt,
            parser=ParserType.CLAUDE,
        )
        response = await advocate_python.execute(context)
        message = response.raw[:500]
        print(f"[PYTHON]: {message[:300]}...")

        # JavaScript advocate's turn
        prompt = f"[Round {round_num}] You're arguing FOR JavaScript. Opponent said: {message}. Keep it under 100 words."
        context = ExecutionContext(
            session=session,
            input=prompt,
            parser=ParserType.CLAUDE,
        )
        response = await advocate_js.execute(context)
        message = response.raw[:500]
        print(f"[JAVASCRIPT]: {message[:300]}...")

    print("\n" + "=" * 60)
    print("Debate finished!")

    # Clean up
    await session.stop()


if __name__ == "__main__":
    asyncio.run(main())
