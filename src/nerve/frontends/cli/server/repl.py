"""Server-connected REPL for nerve.

Unlike the standalone REPL which creates nodes directly,
this REPL connects to a running nerve server and operates
on server-managed nodes.

Usage:
    nerve server repl myproject           # Connect to server named 'myproject'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.transport import UnixSocketClient


@dataclass
class ServerREPLState:
    """State for the server REPL."""

    client: UnixSocketClient | None = None
    socket_path: str = "/tmp/nerve.sock"
    history: list[str] = field(default_factory=list)


def print_help():
    """Print usage help."""
    print("""
Server REPL - Interactive interface to a running nerve server

Nodes:
  create <name> --command <cmd>   Create a node
  create <name> --command <cmd> --cwd <path>
  nodes                           List all nodes

Interaction:
  send <name> <prompt>            Send input and get response
  stream <name> <prompt>          Send with streaming output

Graphs:
  graph load <file>               Load graph definition file
  graph show                      Show graph structure
  graph dry                       Show execution order
  graph run                       Execute the graph

Other:
  help                            Show this help
  status                          Show connection status
  exit                            Exit the REPL

Examples:
  create claude --command claude
  send claude What is 2+2?
  nodes
""")


def print_nodes(server_nodes: list[str]):
    """Print nodes."""
    print("\nNodes:")
    print("-" * 50)
    if server_nodes:
        for name in server_nodes:
            print(f"  {name}")
    else:
        print("  No active nodes")
    print("-" * 50)


async def run_server_repl(socket_path: str = "/tmp/nerve.sock"):
    """Run interactive server-connected REPL."""
    from nerve.server.protocols import Command, CommandType

    from nerve.transport import UnixSocketClient

    state = ServerREPLState(socket_path=socket_path)
    current_graph: dict[str, Any] | None = None
    graph_nodes: dict[str, str] = {}  # Graph node names -> server node IDs

    # Set up readline
    try:
        import atexit
        import os
        import readline

        readline.parse_and_bind(r'"\e[1;3D": backward-word')
        readline.parse_and_bind(r'"\e[1;3C": forward-word')

        histfile = os.path.expanduser("~/.nerve_server_repl_history")
        try:
            readline.read_history_file(histfile)
        except FileNotFoundError:
            pass
        atexit.register(readline.write_history_file, histfile)
    except ImportError:
        pass

    # Connect to server
    print(f"Connecting to {socket_path}...")
    try:
        state.client = UnixSocketClient(socket_path)
        await state.client.connect()
        print("Connected!")
    except Exception as e:
        print(f"Failed to connect: {e}")
        print("Make sure the server is running: nerve server start")
        return

    # Use server's default session (no session_id = default)
    print("Using server's default session")

    print("=" * 50)
    print("Nerve Server REPL")
    print("=" * 50)
    print("\nType 'help' for commands.")
    print("-" * 50)

    interrupt_count = 0

    while True:
        try:
            line = input("server>>> ").strip()
            interrupt_count = 0
        except EOFError:
            print("\n")
            break
        except KeyboardInterrupt:
            interrupt_count += 1
            if interrupt_count >= 2:
                print("\nExiting...")
                break
            print("\n(Press Ctrl-C again to exit)")
            continue

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        try:
            # Help
            if cmd == "help":
                print_help()

            # Status
            elif cmd == "status":
                print(f"Connected to: {state.socket_path}")

            # Nodes list
            elif cmd == "nodes":
                result = await state.client.send_command(
                    Command(type=CommandType.LIST_NODES, params={})
                )
                if result.success:
                    print_nodes(result.data.get("nodes", []))
                else:
                    print(f"Error: {result.error}")

            # Create node
            elif cmd == "create":
                if len(parts) < 2:
                    print("Usage: create <name> [--command cmd] [--cwd path]")
                    continue

                from nerve.core.validation import validate_name

                name = parts[1]
                try:
                    validate_name(name, "node")
                except ValueError as e:
                    print(f"Error: {e}")
                    continue

                command = None
                cwd = None

                # Parse options
                i = 2
                while i < len(parts):
                    if parts[i] == "--command" and i + 1 < len(parts):
                        command = parts[i + 1]
                        i += 2
                    elif parts[i] == "--cwd" and i + 1 < len(parts):
                        cwd = parts[i + 1]
                        i += 2
                    else:
                        i += 1

                result = await state.client.send_command(
                    Command(
                        type=CommandType.CREATE_NODE,
                        params={"node_id": name, "command": command, "cwd": cwd},
                    )
                )

                if result.success:
                    print(f"Created node: {name}")
                else:
                    print(f"Error: {result.error}")

            # Send to node
            elif cmd in ("send", "stream"):
                if len(parts) < 3:
                    print(f"Usage: {cmd} <name> <prompt>")
                else:
                    name = parts[1]
                    prompt = " ".join(parts[2:])

                    result = await state.client.send_command(
                        Command(
                            type=CommandType.EXECUTE_INPUT,
                            params={
                                "node_id": name,
                                "text": prompt,
                                "stream": cmd == "stream",
                            },
                        )
                    )

                    if result.success:
                        print(result.data.get("response", ""))
                    else:
                        print(f"Error: {result.error}")

            # Graph commands
            elif cmd == "graph":
                if len(parts) < 2:
                    print("Usage: graph [load|show|dry|run] ...")
                    continue

                subcmd = parts[1].lower()

                if subcmd == "load":
                    if len(parts) < 3:
                        print("Usage: graph load <file.py>")
                        continue

                    filepath = parts[2]
                    try:
                        graph_def = load_graph_from_file(filepath)
                        current_graph = graph_def
                        graph_nodes.clear()
                        print(f"Loaded Graph with {len(graph_def.get('steps', []))} steps")

                        # Show required nodes
                        required = set()
                        for step in graph_def.get("steps", []):
                            if "node" in step:
                                required.add(step["node"])
                        if required:
                            print(f"Required nodes: {', '.join(required)}")
                            print("Use 'create <name>' to create them")
                    except Exception as e:
                        print(f"Error loading Graph: {e}")

                elif subcmd == "show":
                    if not current_graph:
                        print("No Graph loaded. Use 'graph load <file>'")
                    else:
                        print("\nGraph Structure:")
                        print("-" * 40)
                        for step in current_graph.get("steps", []):
                            deps = step.get("depends_on", [])
                            node = step.get("node", "?")
                            print(f"  {step['id']} (node: {node})")
                            if deps:
                                print(f"    depends on: {', '.join(deps)}")
                        print("-" * 40)

                elif subcmd == "dry":
                    if not current_graph:
                        print("No Graph loaded. Use 'graph load <file>'")
                    else:
                        # Simple topological sort for display
                        steps = current_graph.get("steps", [])
                        print("\nExecution order:")
                        for i, step in enumerate(steps, 1):
                            print(f"  [{i}] {step['id']}")

                elif subcmd == "run":
                    if not current_graph:
                        print("No Graph loaded. Use 'graph load <file>'")
                        continue

                    # Build steps using node names directly
                    steps_for_server = []

                    for step in current_graph.get("steps", []):
                        node_name = step.get("node")

                        steps_for_server.append(
                            {
                                "id": step["id"],
                                "node_id": node_name,  # Node name IS the ID now
                                "input": step.get("prompt", ""),
                                "depends_on": step.get("depends_on", []),
                            }
                        )

                    print("\nExecuting Graph...")
                    result = await state.client.send_command(
                        Command(
                            type=CommandType.EXECUTE_GRAPH,
                            params={"steps": steps_for_server},
                        )
                    )

                    if result.success:
                        print("\nResults:")
                        for step_id, res in result.data.get("results", {}).items():
                            status = res.get("status", "?")
                            output = res.get("output", "")[:200]
                            print(f"  {step_id}: {status}")
                            if output:
                                print(f"    {output}...")
                    else:
                        print(f"Error: {result.error}")

                else:
                    print(f"Unknown graph command: {subcmd}")

            # Exit
            elif cmd in ("exit", "quit"):
                print("Exiting...")
                break

            else:
                print(f"Unknown command: {cmd}")
                print("Type 'help' for available commands")

        except Exception as e:
            print(f"Error: {e}")

    # Cleanup
    if state.client:
        await state.client.disconnect()


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
):
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
                    params={"command": "claude"},
                )
            )
            if result.success:
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

    if result.success:
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
