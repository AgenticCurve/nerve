#!/usr/bin/env python3
"""Multi-agent debate example.

This demonstrates two Claude instances debating each other.

Usage:
    python examples/agents/debate/main.py
"""

import asyncio

from nerve.core import ParserType
from nerve.core.nodes import ExecutionContext, PTYNode
from nerve.core.session import Session

from .prompts import (
    DEBATE_TOPIC,
    JS_ADVOCATE_PROMPT,
    PYTHON_ADVOCATE_PROMPT,
    ROUNDS,
)


async def main():
    print("Setting up debate between two Claude instances...")
    print()

    # Create session and nodes (nodes are auto-registered)
    session = Session()

    advocate_python = await PTYNode.create(id="python-advocate", session=session, command="claude")
    advocate_js = await PTYNode.create(id="js-advocate", session=session, command="claude")

    print(f"Python advocate: {advocate_python.id}")
    print(f"JavaScript advocate: {advocate_js.id}")
    print()

    message = f"Let's debate: {DEBATE_TOPIC}"

    print(f"Starting debate: Python vs JavaScript ({ROUNDS} rounds)")
    print("=" * 60)

    for round_num in range(1, ROUNDS + 1):
        print(f"\n--- Round {round_num} ---\n")

        # Python advocate's turn
        prompt = PYTHON_ADVOCATE_PROMPT.format(round_num=round_num, message=message)
        context = ExecutionContext(
            session=session,
            input=prompt,
            parser=ParserType.CLAUDE,
        )
        response = await advocate_python.execute(context)
        message = response.raw[:500]
        print(f"[PYTHON]: {message[:300]}...")

        # JavaScript advocate's turn
        prompt = JS_ADVOCATE_PROMPT.format(round_num=round_num, message=message)
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
