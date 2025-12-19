#!/usr/bin/env python3
"""DAG execution example - using core only.

This demonstrates multi-step task orchestration with the DAG executor.

Usage:
    python examples/core_only/dag_execution.py
"""

import asyncio

from nerve.core import CLIType, Session
from nerve.core.dag import DAG, Task


async def main():
    print("Creating sessions...")

    # Create two sessions for multi-agent interaction
    claude = await Session.create(CLIType.CLAUDE, cwd=".")

    print(f"Claude session: {claude.id}")
    print()

    # Build a DAG
    dag = DAG()

    # Task 1: Ask Claude to generate a haiku
    async def generate_haiku(ctx):
        response = await claude.send(
            "Write a haiku about programming. Just the haiku, nothing else."
        )
        return response.raw

    dag.add_task(
        Task(
            id="haiku",
            execute=generate_haiku,
            name="Generate Haiku",
        )
    )

    # Task 2: Ask Claude to critique the haiku
    async def critique_haiku(ctx):
        haiku = ctx["haiku"]
        response = await claude.send(f"Critique this haiku in one sentence:\n{haiku}")
        return response.raw

    dag.add_task(
        Task(
            id="critique",
            execute=critique_haiku,
            depends_on=["haiku"],
            name="Critique Haiku",
        )
    )

    # Task 3: Ask Claude to improve based on critique
    async def improve_haiku(ctx):
        haiku = ctx["haiku"]
        critique = ctx["critique"]
        response = await claude.send(
            f"Original haiku:\n{haiku}\n\nCritique:\n{critique}\n\n"
            "Write an improved version. Just the haiku."
        )
        return response.raw

    dag.add_task(
        Task(
            id="improved",
            execute=improve_haiku,
            depends_on=["haiku", "critique"],
            name="Improve Haiku",
        )
    )

    print("DAG structure:")
    for task_id in dag.list_tasks():
        task = dag.get_task(task_id)
        deps = task.depends_on if task else []
        print(f"  {task_id} <- {deps}")
    print()

    print("Executing DAG...")
    print("=" * 50)

    results = await dag.run(
        on_task_start=lambda tid: print(f"  Starting: {tid}"),
        on_task_complete=lambda r: print(f"  Completed: {r.task_id} ({r.duration_ms:.0f}ms)"),
    )

    print("=" * 50)
    print()

    print("Results:")
    print("-" * 50)
    print(f"Original haiku:\n{results['haiku'].output}\n")
    print(f"Critique:\n{results['critique'].output}\n")
    print(f"Improved haiku:\n{results['improved'].output}")

    await claude.close()


if __name__ == "__main__":
    asyncio.run(main())
