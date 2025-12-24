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
from typing import Any


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
    show                  Show current graph structure
    validate              Validate graph
    dry                   Show execution order
    run                   Execute the graph

  Other:
    help                  Show this help
    exit                  Exit the REPL
""")


def print_nodes(state: REPLState):
    """Print active nodes."""
    if not state.nodes:
        print("No active nodes")
        return

    print("\nActive Nodes:")
    print("-" * 40)
    for name, node in state.nodes.items():
        state_name = node.state.name if hasattr(node, "state") else "?"
        print(f"  {name}: {state_name}")
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
):
    """Run interactive Graph definition mode.

    Args:
        state: Optional REPL state to resume from.
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
        PTYNode,
        WezTermNode,
    )
    from nerve.core.session import BackendType, Session

    # Create default session named "repl"
    session = Session(name="repl")

    # Initialize namespace with nerve imports and default session
    state.namespace = {
        "asyncio": asyncio,
        "Graph": Graph,
        "FunctionNode": FunctionNode,
        "ExecutionContext": ExecutionContext,
        "PTYNode": PTYNode,
        "WezTermNode": WezTermNode,
        "Session": Session,
        "ParserType": ParserType,
        "BackendType": BackendType,
        "nodes": state.nodes,  # Node tracking dict
        "session": session,  # Default session
        "_state": state,
    }

    # Track current Graph
    current_graph: Graph | None = None

    print("Nerve REPL")
    print(f"Session: {session.name} | Type 'help' for commands\n")

    buffer = ""
    interrupt_count = 0

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
                print_nodes(state)
                continue

            elif cmd == "graphs":
                sess = state.namespace.get("session")
                if sess:
                    graph_ids = sess.list_graphs()
                    if graph_ids:
                        print("\nGraphs:")
                        for gid in graph_ids:
                            print(f"  {gid}")
                    else:
                        print("No graphs defined")
                else:
                    print("No session")
                continue

            elif cmd == "session":
                sess = state.namespace.get("session")
                if sess:
                    print(f"\nSession: {sess.name}")
                    print(f"  ID: {sess.id}")
                    print(f"  Nodes: {len(sess.nodes)}")
                    print(f"  Graphs: {len(sess.graphs)}")
                else:
                    print("No session")
                continue

            elif cmd == "send":
                if len(parts) < 3:
                    print("Usage: send <node> <text>")
                    continue
                node_name = parts[1]
                text = parts[2]
                node = state.nodes.get(node_name)
                if not node:
                    print(f"Node not found: {node_name}")
                    continue
                try:
                    sess = state.namespace.get("session")
                    ctx = ExecutionContext(session=sess, input=text)
                    result = asyncio.get_event_loop().run_until_complete(
                        node.execute(ctx)
                    )
                    print(result.raw if hasattr(result, "raw") else str(result))
                except Exception as e:
                    print(f"Error: {e}")
                continue

            elif cmd == "read":
                if len(parts) < 2:
                    print("Usage: read <node>")
                    continue
                node_name = parts[1]
                node = state.nodes.get(node_name)
                if not node:
                    print(f"Node not found: {node_name}")
                    continue
                if hasattr(node, "read_buffer"):
                    try:
                        buffer_content = asyncio.get_event_loop().run_until_complete(
                            node.read_buffer()
                        )
                        print(buffer_content)
                    except Exception as e:
                        print(f"Error: {e}")
                else:
                    print("Node does not support read_buffer")
                continue

            elif cmd == "stop":
                if len(parts) < 2:
                    print("Usage: stop <node>")
                    continue
                node_name = parts[1]
                node = state.nodes.get(node_name)
                if not node:
                    print(f"Node not found: {node_name}")
                    continue
                if hasattr(node, "stop"):
                    try:
                        asyncio.get_event_loop().run_until_complete(node.stop())
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
                sess = state.namespace.get("session")
                if sess and node_name in sess.nodes:
                    try:
                        asyncio.get_event_loop().run_until_complete(
                            sess.delete_node(node_name)
                        )
                        state.nodes.pop(node_name, None)
                        print(f"Deleted: {node_name}")
                    except Exception as e:
                        print(f"Error: {e}")
                else:
                    print(f"Node not found: {node_name}")
                continue

            elif cmd == "reset":
                sess = state.namespace.get("session")
                if sess:
                    asyncio.get_event_loop().run_until_complete(sess.stop())
                state.nodes.clear()
                state.namespace["nodes"] = state.nodes
                # Recreate session
                state.namespace["session"] = Session(name="repl")
                current_graph = None
                print("Session reset")
                continue

            elif cmd == "show":
                graph = state.namespace.get("graph") or current_graph
                print_graph(graph)
                continue

            elif cmd == "validate":
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
                graph = state.namespace.get("graph") or current_graph
                if graph:
                    try:
                        print("\nExecuting Graph...")
                        sess = state.namespace.get("session") or Session()
                        context = ExecutionContext(session=sess)
                        results = asyncio.get_event_loop().run_until_complete(
                            graph.execute(context)
                        )
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

        # Try to compile
        try:
            code = compile_command(buffer, symbol="single")

            if code is None:
                # Incomplete - need more input
                continue

            # Complete - execute
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

            buffer = ""

        except SyntaxError as e:
            print(f"SyntaxError: {e}")
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
