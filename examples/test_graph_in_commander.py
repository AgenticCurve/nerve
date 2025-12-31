#!/usr/bin/env python3
"""Register a test graph using CREATE_GRAPH API with steps.

Demonstrates the proper graph registration API that creates a complete
graph with steps in one atomic command (no EXECUTE_PYTHON workarounds needed).

Setup:
    nerve server start graph-test
    nerve server session create default --server graph-test
    nerve server node create claude1 --server graph-test --session default --type ClaudeWezTermNode --command claude
    nerve server node create claude2 --server graph-test --session default --type ClaudeWezTermNode --command claude

Register graph:
    python examples/test_graph_in_commander.py

Test in commander:
    nerve commander /tmp/nerve-graph-test.sock default
"""

import asyncio

from nerve.server.protocols import Command, CommandType
from nerve.transport import UnixSocketClient


async def register_graph(server_name: str = "graph-test", session_name: str = "default"):
    """Register a complete graph with steps using CREATE_GRAPH API.

    Uses the new CREATE_GRAPH command with 'steps' parameter to create
    a complete, validated graph in one atomic operation.
    """
    socket_path = f"/tmp/nerve-{server_name}.sock"

    print(f"Connecting to {socket_path}...")
    client = UnixSocketClient(socket_path)

    try:
        await client.connect()
        print("✓ Connected!")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        print("\nMake sure server is running:")
        print(f"  nerve server start {server_name}")
        print(f"  nerve server session create {session_name} --server {server_name}")
        print(
            f"  nerve server node create claude1 --server {server_name} --session {session_name} --type ClaudeWezTermNode --command claude"
        )
        print(
            f"  nerve server node create claude2 --server {server_name} --session {session_name} --type ClaudeWezTermNode --command claude"
        )
        return

    print("\nCreating graph 'number_doubler' with 2 steps...")

    # Create graph with steps in one command using CREATE_GRAPH API
    # {input} = user's prompt to the graph
    # {step_id} = output from a previous step
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_GRAPH,
            params={
                "session_id": session_name,
                "graph_id": "number_doubler",
                "steps": [
                    {
                        "step_id": "pick_number",
                        "node_id": "claude1",
                        "input": "{input}",  # Use graph's input (user prompt)
                    },
                    {
                        "step_id": "double_it",
                        "node_id": "claude2",
                        "input": "Double this number: {pick_number}. Reply with ONLY the doubled number, nothing else.",
                        "depends_on": ["pick_number"],
                    },
                ],
            },
        )
    )

    if result.success:
        step_count = result.data.get("step_count", 0)
        print(f"✓ Graph '{result.data['graph_id']}' created with {step_count} steps")
    else:
        print(f"✗ Failed: {result.error}")
        return

    await client.disconnect()

    print("\n" + "=" * 60)
    print("Graph registered! Now test in commander:")
    print("=" * 60)
    print(f"  nerve commander /tmp/nerve-{server_name}.sock {session_name}")
    print()
    print("Then try:")
    print("  :entities                                    # See all (nodes + graphs)")
    print("  :graphs                                      # See only graphs")
    print("  @number_doubler Pick a random number 1-100   # Your prompt goes to step 1")
    print("  :info number_doubler                         # Graph details")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    server = sys.argv[1] if len(sys.argv) > 1 else "graph-test"
    session = sys.argv[2] if len(sys.argv) > 2 else "default"
    asyncio.run(register_graph(server, session))
