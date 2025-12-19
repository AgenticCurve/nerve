"""Server-connected REPL for nerve.

Unlike the standalone REPL which creates channels directly,
this REPL connects to a running nerve server and operates
on server-managed channels.

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
Server REPL Commands:
---------------------

Channel Management:
  create <name> [--command cmd] [--cwd path]
                    Create a new channel (name is required)
  channels          List all channels on the server

Interaction:
  send <name> <prompt> [--parser claude|gemini|none]
                    Send a prompt to a channel
  stream <name> <prompt>
                    Send with streaming output

DAG Execution:
  dag load <file>   Load a DAG definition file
  dag show          Show current DAG structure
  dag dry           Show execution order
  dag run           Execute the DAG

Other:
  help              Show this help
  status            Show connection status
  exit              Exit the REPL

Examples:
---------
  >>> create my-claude --command claude
  Created channel: my-claude

  >>> send my-claude "Hello, how are you?" --parser claude
  [response...]

  >>> dag load my_workflow.py
  Loaded DAG with 3 tasks

  >>> dag run
  Executing...
""")


def print_channels(server_channels: list[str]):
    """Print channels."""
    print("\nChannels:")
    print("-" * 50)
    if server_channels:
        for name in server_channels:
            print(f"  {name}")
    else:
        print("  No active channels")
    print("-" * 50)


async def run_server_repl(socket_path: str = "/tmp/nerve.sock"):
    """Run interactive server-connected REPL."""
    from nerve.server.protocols import Command, CommandType
    from nerve.transport import UnixSocketClient

    state = ServerREPLState(socket_path=socket_path)
    current_dag: dict[str, Any] | None = None
    dag_channels: dict[str, str] = {}  # DAG channel names -> server channel IDs

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

            # Channels list
            elif cmd == "channels":
                result = await state.client.send_command(
                    Command(type=CommandType.LIST_CHANNELS, params={})
                )
                if result.success:
                    print_channels(result.data.get("channels", []))
                else:
                    print(f"Error: {result.error}")

            # Create channel
            elif cmd == "create":
                if len(parts) < 2:
                    print("Usage: create <name> [--command cmd] [--cwd path]")
                    continue

                from nerve.core.validation import validate_name

                name = parts[1]
                try:
                    validate_name(name, "channel")
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
                        type=CommandType.CREATE_CHANNEL,
                        params={"channel_id": name, "command": command, "cwd": cwd},
                    )
                )

                if result.success:
                    print(f"Created channel: {name}")
                else:
                    print(f"Error: {result.error}")

            # Send to channel
            elif cmd in ("send", "stream"):
                if len(parts) < 3:
                    print(f"Usage: {cmd} <name> <prompt>")
                else:
                    name = parts[1]
                    prompt = " ".join(parts[2:])

                    result = await state.client.send_command(
                        Command(
                            type=CommandType.SEND_INPUT,
                            params={
                                "channel_id": name,
                                "text": prompt,
                                "stream": cmd == "stream",
                            },
                        )
                    )

                    if result.success:
                        print(result.data.get("response", ""))
                    else:
                        print(f"Error: {result.error}")

            # DAG commands
            elif cmd == "dag":
                if len(parts) < 2:
                    print("Usage: dag [load|show|dry|run] ...")
                    continue

                subcmd = parts[1].lower()

                if subcmd == "load":
                    if len(parts) < 3:
                        print("Usage: dag load <file.py>")
                        continue

                    filepath = parts[2]
                    try:
                        dag_def = load_dag_from_file(filepath)
                        current_dag = dag_def
                        dag_channels.clear()
                        print(f"Loaded DAG with {len(dag_def.get('tasks', []))} tasks")

                        # Show required channels
                        required = set()
                        for task in dag_def.get("tasks", []):
                            if "channel" in task:
                                required.add(task["channel"])
                        if required:
                            print(f"Required channels: {', '.join(required)}")
                            print("Use 'create <name>' to create them")
                    except Exception as e:
                        print(f"Error loading DAG: {e}")

                elif subcmd == "show":
                    if not current_dag:
                        print("No DAG loaded. Use 'dag load <file>'")
                    else:
                        print("\nDAG Structure:")
                        print("-" * 40)
                        for task in current_dag.get("tasks", []):
                            deps = task.get("depends_on", [])
                            channel = task.get("channel", "?")
                            print(f"  {task['id']} (channel: {channel})")
                            if deps:
                                print(f"    depends on: {', '.join(deps)}")
                        print("-" * 40)

                elif subcmd == "dry":
                    if not current_dag:
                        print("No DAG loaded. Use 'dag load <file>'")
                    else:
                        # Simple topological sort for display
                        tasks = current_dag.get("tasks", [])
                        print("\nExecution order:")
                        for i, task in enumerate(tasks, 1):
                            print(f"  [{i}] {task['id']}")

                elif subcmd == "run":
                    if not current_dag:
                        print("No DAG loaded. Use 'dag load <file>'")
                        continue

                    # Build tasks using channel names directly
                    tasks_for_server = []

                    for task in current_dag.get("tasks", []):
                        channel_name = task.get("channel")

                        tasks_for_server.append(
                            {
                                "id": task["id"],
                                "channel_id": channel_name,  # Channel name IS the ID now
                                "text": task.get("prompt", ""),
                                "depends_on": task.get("depends_on", []),
                            }
                        )

                    print("\nExecuting DAG...")
                    result = await state.client.send_command(
                        Command(
                            type=CommandType.EXECUTE_DAG,
                            params={"tasks": tasks_for_server},
                        )
                    )

                    if result.success:
                        print("\nResults:")
                        for tid, res in result.data.get("results", {}).items():
                            status = res.get("status", "?")
                            output = res.get("output", "")[:200]
                            print(f"  {tid}: {status}")
                            if output:
                                print(f"    {output}...")
                    else:
                        print(f"Error: {result.error}")

                else:
                    print(f"Unknown dag command: {subcmd}")

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


def load_dag_from_file(filepath: str) -> dict[str, Any]:
    """Load a DAG definition from a Python file.

    The file should define a `dag` dict with structure:
    {
        "tasks": [
            {
                "id": "task1",
                "channel": "claude1",  # channel name (alias)
                "prompt": "Hello!",
                "depends_on": [],
            },
            ...
        ]
    }

    Or use the DAG builder syntax which we'll convert.
    """
    namespace: dict[str, Any] = {"__name__": "__nerve_dag__"}

    with open(filepath) as f:
        code = f.read()

    exec(compile(code, filepath, "exec"), namespace)

    # Check for dict-style dag
    if "dag" in namespace and isinstance(namespace["dag"], dict):
        return namespace["dag"]

    # Check for DAG object and convert
    if "dag" in namespace and hasattr(namespace["dag"], "list_tasks"):
        dag_obj = namespace["dag"]
        tasks = []
        for task_id in dag_obj.list_tasks():
            task = dag_obj.get_task(task_id)
            if task:
                tasks.append(
                    {
                        "id": task_id,
                        "channel": getattr(task, "channel_name", None),
                        "prompt": getattr(task, "prompt", ""),
                        "depends_on": task.depends_on or [],
                    }
                )
        return {"tasks": tasks}

    raise ValueError("No 'dag' variable found in file")


async def run_dag_file(
    filepath: str,
    socket_path: str = "/tmp/nerve.sock",
    dry_run: bool = False,
    channels: dict[str, str] | None = None,
):
    """Run a DAG file on the server.

    Args:
        filepath: Path to Python file defining the DAG
        socket_path: Server socket path
        dry_run: If True, only show execution order
        channels: Optional dict mapping channel names to IDs
    """
    from nerve.server.protocols import Command, CommandType
    from nerve.transport import UnixSocketClient

    print(f"Loading: {filepath}")

    try:
        dag_def = load_dag_from_file(filepath)
    except Exception as e:
        print(f"Error loading DAG: {e}")
        return

    tasks = dag_def.get("tasks", [])
    print(f"Found {len(tasks)} tasks")

    if dry_run:
        print("\n[DRY RUN] Execution order:")
        for i, task in enumerate(tasks, 1):
            deps = task.get("depends_on", [])
            dep_str = f" (after: {', '.join(deps)})" if deps else ""
            print(f"  [{i}] {task['id']}{dep_str}")
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

    channel_map = channels or {}

    # Find required channels
    required_channels = set()
    for task in tasks:
        if "channel" in task and task["channel"]:
            required_channels.add(task["channel"])

    # Create missing channels
    for channel_name in required_channels:
        if channel_name not in channel_map:
            print(f"Creating channel: {channel_name}")
            result = await client.send_command(
                Command(
                    type=CommandType.CREATE_CHANNEL,
                    params={"command": "claude"},
                )
            )
            if result.success:
                channel_map[channel_name] = result.data["channel_id"]
                print(f"  -> {result.data['channel_id']}")
            else:
                print(f"  Error: {result.error}")
                await client.disconnect()
                return

    # Build server tasks
    tasks_for_server = []
    for task in tasks:
        channel_name = task.get("channel")
        channel_id = channel_map.get(channel_name) if channel_name else None

        tasks_for_server.append(
            {
                "id": task["id"],
                "channel_id": channel_id,
                "text": task.get("prompt", ""),
                "depends_on": task.get("depends_on", []),
            }
        )

    # Execute
    print("\nExecuting DAG...")
    result = await client.send_command(
        Command(
            type=CommandType.EXECUTE_DAG,
            params={"tasks": tasks_for_server},
        )
    )

    if result.success:
        print("\nResults:")
        print("=" * 50)
        for tid, res in result.data.get("results", {}).items():
            status = res.get("status", "?")
            output = res.get("output", "")
            print(f"\n[{tid}] {status}")
            if output:
                print(f"{output[:500]}{'...' if len(output) > 500 else ''}")
        print("=" * 50)
    else:
        print(f"Error: {result.error}")

    await client.disconnect()
