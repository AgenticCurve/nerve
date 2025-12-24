"""Display and output formatting utilities for REPL."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nerve.core.nodes import Graph
    from nerve.frontends.cli.repl.adapters import SessionAdapter


def print_help() -> None:
    """Print usage help."""
    print("""
Nerve REPL - Interactive Python environment for AI CLI orchestration

Pre-loaded:
  session     - Session named 'default' (ready to use)
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
    history <node>        View node's history (supports --last, --op, --summary)

  Graphs:
    show [name]           Show graph structure (default: 'graph' variable)
    validate [name]       Validate graph
    dry [name]            Show execution order
    run [name]            Execute graph

  Other:
    help                  Show this help
    exit                  Exit the REPL
""")


async def print_nodes(adapter: SessionAdapter) -> None:
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


def print_graph(graph: Graph | None) -> None:
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
