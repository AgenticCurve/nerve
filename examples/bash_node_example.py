"""Example: Using BashNode for command execution.

This example demonstrates how to use BashNode to run bash commands
and handle results in graphs.
"""

import asyncio

from nerve.core.nodes import BashNode, ExecutionContext
from nerve.core.session import Session


async def main():
    # Create session
    session = Session(name="bash-example")

    # Example 1: Basic BashNode usage
    print("=" * 60)
    print("Example 1: Basic Command Execution")
    print("=" * 60)

    bash = BashNode(id="bash", cwd="/tmp", timeout=30.0)
    context = ExecutionContext(session=session, input="ls -la")
    result = await bash.execute(context)

    if result["success"]:
        print("✓ Command succeeded")
        print(f"Output:\n{result['stdout']}")
    else:
        print(f"✗ Command failed: {result['error']}")

    # Example 2: Chained commands
    print("\n" + "=" * 60)
    print("Example 2: Chained Commands")
    print("=" * 60)

    bash2 = BashNode(id="bash2")
    result = await bash2.execute(
        ExecutionContext(
            session=session,
            input="cd ~/ && pwd && echo 'Current directory listed above'",
        )
    )

    print(f"Success: {result['success']}")
    print(f"Output:\n{result['stdout']}")

    # Example 3: Using BashNode in a Graph
    print("\n" + "=" * 60)
    print("Example 3: BashNode in Graph")
    print("=" * 60)

    # Create graph
    graph = session.create_graph("deploy-pipeline")

    # Create bash nodes for different steps
    checkout = BashNode(id="checkout", cwd="/tmp")
    test = BashNode(id="test", timeout=60.0)
    build = BashNode(id="build")

    # Add steps to graph
    graph.add_step(checkout, "checkout", input="echo 'Checking out code...' && sleep 0.5")
    graph.add_step(test, "test", input="echo 'Running tests...' && sleep 0.5", depends_on=["checkout"])
    graph.add_step(build, "build", input="echo 'Building project...' && sleep 0.5", depends_on=["test"])

    # Execute graph
    results = await graph.execute(ExecutionContext(session=session))

    print("Graph execution results:")
    for step_id, result in results.items():
        status = "✓" if result["success"] else "✗"
        print(f"  {status} {step_id}: {result['stdout'].strip()}")

    # Example 4: Interrupt handling
    print("\n" + "=" * 60)
    print("Example 4: Interrupting Long-Running Command")
    print("=" * 60)

    bash_long = BashNode(id="long-running")

    # Start long-running command
    task = asyncio.create_task(
        bash_long.execute(
            ExecutionContext(session=session, input="echo 'Starting...' && sleep 10")
        )
    )

    # Wait a bit, then interrupt
    print("Starting long-running command...")
    await asyncio.sleep(0.5)
    print("Interrupting command...")
    await bash_long.interrupt()

    # Get result
    result = await task
    print(f"Interrupted: {result['interrupted']}")
    print(f"Error: {result['error']}")

    # Example 5: Error handling
    print("\n" + "=" * 60)
    print("Example 5: Error Handling")
    print("=" * 60)

    bash_err = BashNode(id="error-test")
    result = await bash_err.execute(
        ExecutionContext(session=session, input="ls /nonexistent/directory")
    )

    print(f"Success: {result['success']}")
    print(f"Exit code: {result['exit_code']}")
    print(f"Error: {result['error']}")
    print(f"Stderr: {result['stderr']}")

    # Example 6: Environment variables
    print("\n" + "=" * 60)
    print("Example 6: Environment Variables")
    print("=" * 60)

    bash_env = BashNode(
        id="env-test",
        env={
            "MY_VAR": "Hello from environment",
            "MY_NUMBER": "42",
        },
    )

    result = await bash_env.execute(
        ExecutionContext(session=session, input="echo $MY_VAR && echo $MY_NUMBER")
    )

    print(f"Output:\n{result['stdout']}")

    # Cleanup
    await session.stop()


if __name__ == "__main__":
    asyncio.run(main())
