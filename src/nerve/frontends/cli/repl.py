"""Interactive Graph REPL for nerve.

Ported from wezterm's run_commands.py - provides an interactive
environment for defining and executing Graphs.

Usage:
    nerve repl                    # Interactive mode
    nerve repl script.py          # Load and run from file
    nerve repl script.py --dry    # Dry run from file
"""

from __future__ import annotations

import asyncio
from code import compile_command
from dataclasses import dataclass, field
from typing import Any, Protocol

# =========================================================================
# Session Adapter - Abstraction for local vs remote sessions
# =========================================================================


class SessionAdapter(Protocol):
    """Protocol for session operations in both local and remote modes."""

    @property
    def name(self) -> str:
        """Session name."""
        ...

    @property
    def id(self) -> str:
        """Session ID."""
        ...

    @property
    def node_count(self) -> int:
        """Number of nodes in session."""
        ...

    @property
    def graph_count(self) -> int:
        """Number of graphs in session."""
        ...

    async def list_nodes(self) -> list[tuple[str, str]]:
        """List nodes as (name, info) tuples."""
        ...

    async def list_graphs(self) -> list[str]:
        """List graph IDs."""
        ...

    async def get_graph(self, graph_id: str):
        """Get graph by ID (returns Graph object or None)."""
        ...

    async def delete_node(self, node_id: str) -> bool:
        """Delete a node."""
        ...

    async def execute_on_node(self, node_id: str, text: str) -> str:
        """Execute input on a node and return response."""
        ...

    async def stop(self) -> None:
        """Stop session and cleanup."""
        ...


class LocalSessionAdapter:
    """Adapter for local in-memory session."""

    def __init__(self, session: Any):  # Session type
        self.session = session

    @property
    def name(self) -> str:
        return self.session.name

    @property
    def id(self) -> str:
        return self.session.id

    @property
    def node_count(self) -> int:
        return len(self.session.nodes)

    @property
    def graph_count(self) -> int:
        return len(self.session.graphs)

    async def list_nodes(self) -> list[tuple[str, str]]:
        """Return list of (name, info_string) tuples."""
        result = []
        for name, node in self.session.nodes.items():
            if hasattr(node, "state"):
                info = node.state.name
            else:
                info = type(node).__name__
            result.append((name, info))
        return result

    async def list_graphs(self) -> list[str]:
        return self.session.list_graphs()

    async def get_graph(self, graph_id: str):
        return self.session.get_graph(graph_id)

    async def delete_node(self, node_id: str) -> bool:
        return await self.session.delete_node(node_id)

    async def execute_on_node(self, node_id: str, text: str) -> str:
        """Execute on a node (for send command)."""
        from nerve.core.nodes.context import ExecutionContext

        node = self.session.get_node(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        ctx = ExecutionContext(session=self.session, input=text)
        result = await node.execute(ctx)
        return result.raw if hasattr(result, "raw") else str(result)

    async def stop(self) -> None:
        await self.session.stop()


class RemoteSessionAdapter:
    """Adapter for remote server session."""

    def __init__(
        self, client: Any, server_name: str, session_name: str | None = None
    ):  # UnixSocketClient type
        self.client = client
        self.server_name = server_name
        self._name = session_name or "default"  # Use provided or default
        self.session_id = session_name  # None means use server's default
        self._cached_nodes_info: list[dict] = []
        self._cached_graphs: list[dict] = []

    def _add_session_id(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add session_id to params if specified."""
        if self.session_id:
            params["session_id"] = self.session_id
        return params

    @property
    def name(self) -> str:
        return self._name

    @property
    def id(self) -> str:
        """Session ID (actual name on server)."""
        return self._name

    @property
    def node_count(self) -> int:
        """Get node count from cached data."""
        return len(self._cached_nodes_info)

    @property
    def graph_count(self) -> int:
        """Get graph count from cached data."""
        return len(self._cached_graphs)

    async def list_nodes(self) -> list[tuple[str, str]]:
        """List nodes from server with actual backend types."""
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(type=CommandType.LIST_NODES, params=self._add_session_id({}))
        )
        if result.success:
            nodes_info = result.data.get("nodes_info", [])
            self._cached_nodes_info = nodes_info  # Cache for node_count

            # Return (name, backend_type) tuples
            return [(info["id"], info.get("type", "UNKNOWN")) for info in nodes_info]
        return []

    async def list_graphs(self) -> list[str]:
        """List graphs from server."""
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(type=CommandType.LIST_GRAPHS, params=self._add_session_id({}))
        )
        if result.success:
            graphs = result.data.get("graphs", [])
            self._cached_graphs = graphs  # Cache for graph_count
            return [g["id"] for g in graphs]
        return []

    async def get_graph(self, graph_id: str):
        """Get graph from server - returns None (graphs are session-bound).

        NOTE: Graphs cannot be transferred from server to client because they
        must be bound to a session. Graphs exist only on the server.
        Use server-side execution instead.
        """
        # Graphs are now session-bound and cannot be reconstructed client-side
        # They must be accessed and executed on the server where they were created
        return None

    async def delete_node(self, node_id: str) -> bool:
        """Delete node on server."""
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(
                type=CommandType.DELETE_NODE,
                params=self._add_session_id({"node_id": node_id}),
            )
        )
        return result.success

    async def execute_on_node(self, node_id: str, text: str) -> str:
        """Execute on a server node."""
        from nerve.server.protocols import Command, CommandType

        result = await self.client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params=self._add_session_id({"node_id": node_id, "text": text, "stream": False}),
            )
        )
        if result.success:
            return result.data.get("response", "")
        else:
            raise ValueError(result.error)

    async def stop(self) -> None:
        """Disconnect from server."""
        await self.client.disconnect()


@dataclass
class REPLState:
    """State for the REPL."""

    namespace: dict[str, Any] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    nodes: dict[str, Any] = field(default_factory=dict)


def print_help():
    """Print usage help."""
    print("""
Nerve REPL - Interactive Python environment for AI CLI orchestration

Pre-loaded:
  session     - Session named 'repl' (ready to use)
  Session, Graph, FunctionNode, ExecutionContext
  ParserType, BackendType, PTYNode, WezTermNode

Python Examples:
  claude = await session.create_node("claude", command="claude")
  graph = session.create_graph("my-pipeline")
  graph.add_step(claude, step_id="q1", input="What is 2+2?")
  results = await graph.execute(ExecutionContext(session=session))

Commands:
  Session:
    session               Show session info
    nodes                 List all nodes
    graphs                List all graphs
    reset                 Reset session (stop all nodes, clear graphs)

  Nodes:
    send <node> <text>    Send input to node and get response
    read <node>           Read node's output buffer
    stop <node>           Stop a node
    delete <node>         Delete a node

  Graphs:
    show [name]           Show graph structure (default: 'graph' variable)
    validate [name]       Validate graph
    dry [name]            Show execution order
    run [name]            Execute graph

  Other:
    help                  Show this help
    exit                  Exit the REPL
""")


async def print_nodes(adapter: SessionAdapter):
    """Print active nodes."""
    nodes = await adapter.list_nodes()

    if not nodes:
        print("No active nodes")
        return

    print("\nActive Nodes:")
    print("-" * 40)
    for name, info in nodes:
        print(f"  {name}: {info}")
    print("-" * 40)


def print_graph(graph):
    """Print Graph structure."""
    if not graph or not graph.list_steps():
        print("No steps defined")
        return

    print("\nGraph Structure:")
    print("-" * 40)
    for step_id in graph.list_steps():
        step = graph.get_step(step_id)
        deps = step.depends_on if step else []
        print(f"  {step_id}")
        if deps:
            print(f"    depends on: {', '.join(deps)}")
    print("-" * 40)


async def run_interactive(
    state: REPLState | None = None,
    server_name: str | None = None,
    session_name: str | None = None,
):
    """Run interactive Graph definition mode.

    Args:
        state: Optional REPL state to resume from.
        server_name: Optional server name to connect to (None = local mode).
        session_name: Optional session name (only used with server_name).
    """
    if state is None:
        state = REPLState()

    # Set up readline for history and editing
    try:
        import atexit
        import os
        import readline

        # Key bindings for word movement
        readline.parse_and_bind(r'"\e[1;3D": backward-word')
        readline.parse_and_bind(r'"\e[1;3C": forward-word')

        # History file
        histfile = os.path.expanduser("~/.nerve_repl_history")
        try:
            readline.read_history_file(histfile)
        except FileNotFoundError:
            pass
        atexit.register(readline.write_history_file, histfile)
    except ImportError:
        pass

    # Lazy import to avoid circular deps
    from nerve.core import ParserType
    from nerve.core.nodes import (
        ExecutionContext,
        FunctionNode,
        Graph,
    )
    from nerve.core.session import BackendType, Session

    # Determine mode and create adapter
    adapter: SessionAdapter
    session: Session | None = None
    python_exec_enabled: bool

    if server_name:
        # Server mode - connect to existing server
        from nerve.frontends.cli.utils import get_server_transport
        from nerve.transport import UnixSocketClient

        transport_type, socket_path = get_server_transport(server_name)

        if transport_type != "unix":
            print("Error: Only unix socket servers supported for REPL")
            print(f"Server '{server_name}' uses {transport_type}")
            return

        print(f"Connecting to server '{server_name}'...")
        try:
            client = UnixSocketClient(socket_path)
            await client.connect()
            print("Connected!")
        except Exception as e:
            print(f"Failed to connect: {e}")
            print(f"Make sure server is running: nerve server start --name {server_name}")
            return

        adapter = RemoteSessionAdapter(client, server_name, session_name)
        session_display = session_name or "default"
        print(f"Using session: {session_display}")
        python_exec_enabled = False
    else:
        # Local mode - create in-memory session (NO server)
        session = Session(name="repl")
        adapter = LocalSessionAdapter(session)
        python_exec_enabled = True

    # Initialize namespace (only in local mode for Python REPL features)
    if python_exec_enabled:
        state.namespace = {
            "asyncio": asyncio,
            "FunctionNode": FunctionNode,
            "ExecutionContext": ExecutionContext,
            "Session": Session,
            "ParserType": ParserType,
            "BackendType": BackendType,
            "nodes": state.nodes,  # Node tracking dict
            "session": session,  # Default session
            "context": ExecutionContext(session=session),  # Pre-configured context
            "_state": state,
            # NOTE: Graph, PTYNode, WezTermNode removed - use session.create_*() instead
        }
    else:
        state.namespace = {}

    # Track current Graph
    current_graph: Graph | None = None

    # Print startup message
    mode_str = f"Server: {server_name}" if server_name else f"Session: {adapter.name}"
    print("Nerve REPL")
    print(f"{mode_str} | Type 'help' for commands\n")

    buffer = ""
    interrupt_count = 0

    async def run_async_operation(coro):
        """Helper to run async operations within the REPL."""
        return await coro

    while True:
        try:
            prompt = "... " if buffer else ">>> "
            line = input(prompt)
            interrupt_count = 0
        except EOFError:
            print("\n")
            break
        except KeyboardInterrupt:
            interrupt_count += 1
            if interrupt_count >= 2:
                print("\nExiting...")
                break
            print("\n(Press Ctrl-C again to exit, or continue typing)")
            buffer = ""
            continue

        # Handle REPL commands (only when not in multi-line mode)
        if not buffer:
            parts = line.strip().split(maxsplit=2)
            cmd = parts[0].lower() if parts else ""

            if cmd == "help":
                print_help()
                continue

            elif cmd == "nodes":
                await print_nodes(adapter)
                continue

            elif cmd == "graphs":
                graph_ids = await adapter.list_graphs()
                if graph_ids:
                    print("\nGraphs:")
                    for gid in graph_ids:
                        print(f"  {gid}")
                else:
                    print("No graphs defined")
                continue

            elif cmd == "session":
                # Refresh cached data before displaying
                await adapter.list_nodes()
                await adapter.list_graphs()

                print(f"\nSession: {adapter.name}")
                print(f"  ID: {adapter.id}")
                if hasattr(adapter, "server_name"):
                    print(f"  Server: {adapter.server_name}")
                print(f"  Nodes: {adapter.node_count}")
                print(f"  Graphs: {adapter.graph_count}")
                continue

            elif cmd == "send":
                if len(parts) < 3:
                    print("Usage: send <node> <text>")
                    continue
                node_name = parts[1]
                text = parts[2]
                try:
                    response = await adapter.execute_on_node(node_name, text)
                    # Pretty print the response
                    import json

                    if isinstance(response, (dict, list)):
                        print(json.dumps(response, indent=2))
                    elif isinstance(response, str):
                        # Try to parse as JSON/dict string
                        try:
                            # Try JSON first
                            parsed = json.loads(response)
                            print(json.dumps(parsed, indent=2))
                        except (json.JSONDecodeError, ValueError):
                            # Try eval as Python literal (safer than eval)
                            try:
                                import ast

                                parsed = ast.literal_eval(response)
                                print(json.dumps(parsed, indent=2))
                            except (ValueError, SyntaxError):
                                # Not JSON or dict, print as-is
                                print(response)
                    else:
                        print(response)
                except Exception as e:
                    print(f"Error: {e}")
                continue

            elif cmd == "read":
                # Local mode only - needs direct node access
                if not python_exec_enabled:
                    print("Command not available in server mode")
                    continue
                if len(parts) < 2:
                    print("Usage: read <node>")
                    continue
                node_name = parts[1]
                node = session.get_node(node_name) if session else None
                if not node:
                    print(f"Node not found: {node_name}")
                    continue
                if hasattr(node, "read_buffer"):
                    try:
                        buffer_content = await run_async_operation(node.read_buffer())
                        print(buffer_content)
                    except Exception as e:
                        print(f"Error: {e}")
                else:
                    print("Node does not support read_buffer")
                continue

            elif cmd == "stop":
                # Local mode only - needs direct node access
                if not python_exec_enabled:
                    print("Command not available in server mode")
                    continue
                if len(parts) < 2:
                    print("Usage: stop <node>")
                    continue
                node_name = parts[1]
                node = session.get_node(node_name) if session else None
                if not node:
                    print(f"Node not found: {node_name}")
                    continue
                if hasattr(node, "stop"):
                    try:
                        await run_async_operation(node.stop())
                        print(f"Stopped: {node_name}")
                    except Exception as e:
                        print(f"Error: {e}")
                else:
                    print("Node does not support stop")
                continue

            elif cmd == "delete":
                if len(parts) < 2:
                    print("Usage: delete <node>")
                    continue
                node_name = parts[1]
                try:
                    success = await adapter.delete_node(node_name)
                    if success:
                        print(f"Deleted: {node_name}")
                    else:
                        print(f"Node not found: {node_name}")
                except Exception as e:
                    print(f"Error: {e}")
                continue

            elif cmd == "reset":
                # Local mode only
                if not python_exec_enabled:
                    print("Command not available in server mode")
                    continue
                if session:
                    await run_async_operation(session.stop())
                state.nodes.clear()
                # Recreate session
                session = Session(name="repl")
                state.namespace["session"] = session
                state.namespace["context"] = ExecutionContext(session=session)
                state.namespace["nodes"] = state.nodes
                # Update adapter
                adapter = LocalSessionAdapter(session)
                current_graph = None
                print("Session reset")
                continue

            elif cmd == "show":
                # show [graph-name] - show specific graph or default 'graph' variable
                graph = None
                if len(parts) > 1:
                    graph_name = parts[1]
                    graph = await adapter.get_graph(graph_name)
                    if not graph:
                        print(f"Graph not found: {graph_name}")
                        continue
                else:
                    graph = state.namespace.get("graph") or current_graph
                print_graph(graph)
                continue

            elif cmd == "validate":
                # validate [graph-name] - validate specific graph or default
                graph = None
                if len(parts) > 1:
                    graph_name = parts[1]
                    graph = await adapter.get_graph(graph_name)
                    if not graph:
                        print(f"Graph not found: {graph_name}")
                        continue
                else:
                    graph = state.namespace.get("graph") or current_graph

                if graph:
                    errors = graph.validate()
                    if errors:
                        print("Validation FAILED:")
                        for e in errors:
                            print(f"  - {e}")
                    else:
                        print("Validation PASSED")
                else:
                    print("No Graph defined")
                continue

            elif cmd == "dry":
                # dry [graph-name] - dry run specific graph or default
                graph = None
                if len(parts) > 1:
                    graph_name = parts[1]
                    graph = await adapter.get_graph(graph_name)
                    if not graph:
                        print(f"Graph not found: {graph_name}")
                        continue
                else:
                    graph = state.namespace.get("graph") or current_graph

                if graph:
                    try:
                        order = graph.execution_order()
                        print("\nExecution order:")
                        for i, step_id in enumerate(order, 1):
                            print(f"  [{i}] {step_id}")
                    except ValueError as e:
                        print(f"Error: {e}")
                else:
                    print("No Graph defined")
                continue

            elif cmd == "run":
                # run [graph-name] - run specific graph or default 'graph' variable
                # Only works in local mode (needs to execute graph)
                if not python_exec_enabled:
                    print("Graph execution not available in server mode")
                    print("Use server REPL commands instead")
                    continue

                graph = None
                if len(parts) > 1:
                    # run <graph-name> - look up from adapter
                    graph_name = parts[1]
                    graph = await adapter.get_graph(graph_name)
                    if not graph:
                        print(f"Graph not found: {graph_name}")
                        continue
                else:
                    # run - use 'graph' variable or current_graph
                    graph = state.namespace.get("graph") or current_graph

                if graph:
                    try:
                        print("\nExecuting Graph...")
                        context = ExecutionContext(session=session)
                        results = await run_async_operation(graph.execute(context))
                        state.namespace["_results"] = results
                        print("\nResults stored in '_results'")
                    except Exception as e:
                        print(f"Error: {e}")
                else:
                    print("No Graph defined")
                continue

            elif cmd in ("exit", "quit"):
                print("Exiting...")
                break

        # Skip empty lines when not in multi-line mode
        if not buffer and not line.strip():
            continue

        # Accumulate input
        if buffer:
            buffer += "\n" + line
        else:
            buffer = line

        # Try to compile (skip if server mode with await)
        code = None
        if python_exec_enabled or "await " not in buffer:
            try:
                code = compile_command(buffer, symbol="single")

                if code is None:
                    # Incomplete - need more input
                    continue
            except SyntaxError:
                # If in server mode, send to server anyway (it can handle await)
                if not python_exec_enabled:
                    code = True  # Dummy value to proceed
                else:
                    raise
        else:
            # Server mode with await - skip compilation, send to server
            code = True  # Dummy value to proceed

        # Execute based on mode
        if code is not None:
            if python_exec_enabled:
                # LOCAL MODE - Execute locally
                try:
                    # Handle async code
                    if "await " in buffer:
                        # Wrap in async function and run
                        async_code = "async def __repl_async__():\n"
                        for ln in buffer.split("\n"):
                            async_code += f"    {ln}\n"
                        async_code += "\n__repl_result__ = asyncio.get_event_loop().run_until_complete(__repl_async__())"
                        exec(compile(async_code, "<repl>", "exec"), state.namespace)
                    else:
                        exec(code, state.namespace)

                    # Track nodes created
                    for name, value in state.namespace.items():
                        if hasattr(value, "state") and hasattr(value, "execute"):
                            if name not in ("PTYNode", "WezTermNode", "ParserType", "FunctionNode"):
                                state.nodes[name] = value

                    # Track Graph
                    if "graph" in state.namespace:
                        current_graph = state.namespace["graph"]

                except Exception as e:
                    print(f"Error: {e}")
            else:
                # SERVER MODE - Send to server for execution
                try:
                    from nerve.server.protocols import Command, CommandType

                    params = {"code": buffer}
                    if adapter.session_id:
                        params["session_id"] = adapter.session_id

                    result = await adapter.client.send_command(
                        Command(
                            type=CommandType.EXECUTE_PYTHON,
                            params=params,
                        )
                    )

                    if result.success:
                        output = result.data.get("output", "")
                        error = result.data.get("error")

                        if error:
                            print(f"Error: {error}")
                        elif output:
                            print(output, end="")
                    else:
                        print(f"Error: {result.error}")

                except Exception as e:
                    print(f"Error: {e}")

            buffer = ""


async def run_from_file(
    filepath: str,
    dry_run: bool = False,
):
    """Load and run Graph from a Python file.

    Args:
        filepath: Path to Python file containing Graph definition.
        dry_run: If True, only show execution order.
    """
    from nerve.core import ParserType
    from nerve.core.nodes import (
        ExecutionContext,
        FunctionNode,
        Graph,
        PTYNode,
        WezTermNode,
    )
    from nerve.core.session import BackendType, Session

    # Create default session named "repl"
    session = Session(name="repl")

    namespace = {
        "asyncio": asyncio,
        "Graph": Graph,
        "FunctionNode": FunctionNode,
        "ExecutionContext": ExecutionContext,
        "PTYNode": PTYNode,
        "WezTermNode": WezTermNode,
        "Session": Session,
        "ParserType": ParserType,
        "BackendType": BackendType,
        "session": session,  # Default session
        "__name__": "__nerve_repl__",
    }

    print(f"Loading: {filepath}")
    print("=" * 50)

    try:
        with open(filepath) as f:
            code = f.read()

        # Execute the file
        exec(compile(code, filepath, "exec"), namespace)

        # Look for a Graph to run
        graph = namespace.get("graph")
        if graph:
            if dry_run:
                print("\n[DRY RUN]")
                order = graph.execution_order()
                for i, step_id in enumerate(order, 1):
                    print(f"  [{i}] {step_id}")
            else:
                print("\nExecuting Graph...")
                # Use session from namespace (may have been replaced by file)
                exec_session = namespace.get("session") or session
                context = ExecutionContext(session=exec_session)
                await graph.execute(context)
        else:
            print("No 'graph' variable found in file")

    except FileNotFoundError:
        print(f"Error: File not found: {filepath}")
    except Exception as e:
        print(f"Error: {e}")


def main():
    """CLI entry point for REPL."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Nerve Graph REPL - Interactive Graph definition and execution"
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Python file containing Graph definition",
    )
    parser.add_argument(
        "--dry-run",
        "-d",
        action="store_true",
        help="Show execution order without running",
    )

    args = parser.parse_args()

    if args.file:
        asyncio.run(run_from_file(args.file, dry_run=args.dry_run))
    else:
        asyncio.run(run_interactive())


if __name__ == "__main__":
    main()
