"""Graph subcommands for server."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import rich_click as click

from nerve.frontends.cli.server import server
from nerve.frontends.cli.utils import create_client

# ============================================================================
# Graph File Loading Helpers
# ============================================================================


def load_graph_from_file(filepath: str) -> dict[str, Any]:
    """Load a Graph definition from a Python file.

    The file should define a `graph` dict with structure:
    {
        "steps": [
            {
                "id": "step1",
                "node": "claude1",  # node name (alias)
                "prompt": "Hello!",
                "depends_on": [],
            },
            ...
        ]
    }

    Or use the Graph builder syntax which we'll convert.
    """
    namespace: dict[str, Any] = {"__name__": "__nerve_graph__"}

    with open(filepath) as f:
        code = f.read()

    exec(compile(code, filepath, "exec"), namespace)

    # Check for dict-style graph
    if "graph" in namespace and isinstance(namespace["graph"], dict):
        return namespace["graph"]

    # Check for Graph object and convert
    if "graph" in namespace and hasattr(namespace["graph"], "list_steps"):
        graph_obj = namespace["graph"]
        steps = []
        for step_id in graph_obj.list_steps():
            step = graph_obj.get_step(step_id)
            if step:
                steps.append(
                    {
                        "id": step_id,
                        "node": getattr(step, "node_name", None),
                        "prompt": getattr(step, "prompt", ""),
                        "depends_on": step.depends_on or [],
                    }
                )
        return {"steps": steps}

    raise ValueError("No 'graph' variable found in file")


async def run_graph_file(
    filepath: str,
    socket_path: str = "/tmp/nerve.sock",
    dry_run: bool = False,
    nodes: dict[str, str] | None = None,
) -> None:
    """Run a Graph file on the server.

    Args:
        filepath: Path to Python file defining the Graph
        socket_path: Server socket path
        dry_run: If True, only show execution order
        nodes: Optional dict mapping node names to IDs
    """
    from nerve.server.protocols import Command, CommandType
    from nerve.transport import UnixSocketClient

    print(f"Loading: {filepath}")

    try:
        graph_def = load_graph_from_file(filepath)
    except Exception as e:
        print(f"Error loading Graph: {e}")
        return

    steps = graph_def.get("steps", [])
    print(f"Found {len(steps)} steps")

    if dry_run:
        print("\n[DRY RUN] Execution order:")
        for i, step in enumerate(steps, 1):
            deps = step.get("depends_on", [])
            dep_str = f" (after: {', '.join(deps)})" if deps else ""
            print(f"  [{i}] {step['id']}{dep_str}")
        return

    # Connect to server
    print(f"\nConnecting to {socket_path}...")
    client = UnixSocketClient(socket_path)
    try:
        await client.connect()
    except Exception as e:
        print(f"Failed to connect: {e}")
        print("Make sure the server is running: nerve server start")
        return

    node_map = nodes or {}

    # Find required nodes
    required_nodes = set()
    for step in steps:
        if "node" in step and step["node"]:
            required_nodes.add(step["node"])

    # Create missing nodes
    for node_name in required_nodes:
        if node_name not in node_map:
            print(f"Creating node: {node_name}")
            result = await client.send_command(
                Command(
                    type=CommandType.CREATE_NODE,
                    params={"node_id": node_name, "command": "claude"},
                )
            )
            if result.success and result.data:
                node_map[node_name] = result.data["node_id"]
                print(f"  -> {result.data['node_id']}")
            else:
                print(f"  Error: {result.error}")
                await client.disconnect()
                return

    # Build server steps
    steps_for_server = []
    for step in steps:
        node_name = step.get("node")
        node_id = node_map.get(node_name) if node_name else None

        steps_for_server.append(
            {
                "id": step["id"],
                "node_id": node_id,
                "input": step.get("prompt", ""),
                "depends_on": step.get("depends_on", []),
            }
        )

    # Execute
    print("\nExecuting Graph...")
    result = await client.send_command(
        Command(
            type=CommandType.EXECUTE_GRAPH,
            params={"steps": steps_for_server},
        )
    )

    if result.success and result.data:
        print("\nResults:")
        print("=" * 50)
        for step_id, res in result.data.get("results", {}).items():
            status = res.get("status", "?")
            output = res.get("output", "")
            print(f"\n[{step_id}] {status}")
            if output:
                print(f"{output[:500]}{'...' if len(output) > 500 else ''}")
        print("=" * 50)
    else:
        print(f"Error: {result.error}")

    await client.disconnect()


# ============================================================================
# Graph CLI Commands
# ============================================================================


@server.group()
def graph() -> None:
    """Execute graphs on the server.

    Graphs are multi-step workflows that orchestrate node execution.
    Define graphs in Python files and execute them with 'graph run'.

    **Command:**

        nerve server graph run       Run a graph file
    """
    pass


@graph.command("run")
@click.argument("file")
@click.option("--server", "-s", "server_name", default="local", help="Server name (default: local)")
@click.option("--dry-run", "-d", is_flag=True, help="Show execution order without running")
def graph_run(file: str, server_name: str, dry_run: bool) -> None:
    """Run a graph definition file on the server.

    The file should define a `graph` dict or Graph object with steps.
    Nodes are created automatically if needed.

    **Examples:**

        nerve server graph run workflow.py

        nerve server graph run workflow.py --server myproject

        nerve server graph run workflow.py --server myproject --dry-run
    """
    socket = f"/tmp/nerve-{server_name}.sock"
    asyncio.run(run_graph_file(file, socket_path=socket, dry_run=dry_run))
