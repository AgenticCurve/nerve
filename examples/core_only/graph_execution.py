#!/usr/bin/env python3
"""Graph execution example - using core only.

This demonstrates multi-step task orchestration with the Graph executor.

Usage:
    python examples/core_only/graph_execution.py
"""

import asyncio

from nerve.core import ParserType
from nerve.core.nodes import ExecutionContext, FunctionNode, Graph, PTYNode
from nerve.core.session import Session


async def main():
    print("Creating node...")

    # Create session and node (node is auto-registered)
    session = Session()
    claude = await PTYNode.create(id="claude", session=session, command="claude", cwd=".")

    print(f"Claude node: {claude.id}")
    print()

    # Build a Graph (auto-registered in session)
    graph = Graph(id="haiku-pipeline", session=session)

    # Step 1: Ask Claude to generate a haiku
    async def generate_haiku(ctx: ExecutionContext):
        response = await claude.execute(
            ExecutionContext(
                session=session,
                input="Write a haiku about programming. Just the haiku, nothing else.",
                parser=ParserType.CLAUDE_CODE,
            )
        )
        return response["attributes"]["raw"]

    graph.add_step(
        FunctionNode(id="haiku", session=session, fn=generate_haiku),
        step_id="haiku",
    )

    # Step 2: Ask Claude to critique the haiku
    async def critique_haiku(ctx: ExecutionContext):
        haiku = ctx.upstream["haiku"]["output"]
        response = await claude.execute(
            ExecutionContext(
                session=session,
                input=f"Critique this haiku in one sentence:\n{haiku}",
                parser=ParserType.CLAUDE_CODE,
            )
        )
        return response["attributes"]["raw"]

    graph.add_step(
        FunctionNode(id="critique", session=session, fn=critique_haiku),
        step_id="critique",
        depends_on=["haiku"],
    )

    # Step 3: Ask Claude to improve based on critique
    async def improve_haiku(ctx: ExecutionContext):
        haiku = ctx.upstream["haiku"]["output"]
        critique = ctx.upstream["critique"]["output"]
        response = await claude.execute(
            ExecutionContext(
                session=session,
                input=f"Original haiku:\n{haiku}\n\nCritique:\n{critique}\n\n"
                "Write an improved version. Just the haiku.",
                parser=ParserType.CLAUDE_CODE,
            )
        )
        return response["attributes"]["raw"]

    graph.add_step(
        FunctionNode(id="improved", session=session, fn=improve_haiku),
        step_id="improved",
        depends_on=["haiku", "critique"],
    )

    print("Graph structure:")
    for step_id in graph.list_steps():
        step = graph.get_step(step_id)
        deps = step.depends_on if step else []
        print(f"  {step_id} <- {deps}")
    print()

    print("Executing Graph...")
    print("=" * 50)

    results = await graph.execute(ExecutionContext(session=session))

    print("=" * 50)
    print()

    print("Results:")
    print("-" * 50)
    steps = results["attributes"]["steps"]
    print(f"Original haiku:\n{steps['haiku']['output']}\n")
    print(f"Critique:\n{steps['critique']['output']}\n")
    print(f"Improved haiku:\n{steps['improved']['output']}")

    await claude.stop()


if __name__ == "__main__":
    asyncio.run(main())
