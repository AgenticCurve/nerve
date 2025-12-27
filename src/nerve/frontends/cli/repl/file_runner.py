"""File-based graph execution for REPL."""

from __future__ import annotations

import asyncio


async def run_from_file(
    filepath: str,
    dry_run: bool = False,
) -> None:
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
    from nerve.core.nodes.bash import BashNode
    from nerve.core.nodes.llm import OpenRouterNode
    from nerve.core.nodes.terminal import ClaudeWezTermNode
    from nerve.core.session import Session

    # Create default session for REPL
    session = Session(name="repl", server_name="repl")

    namespace = {
        "asyncio": asyncio,
        # Node classes (use with session parameter)
        "BashNode": BashNode,
        "FunctionNode": FunctionNode,
        "Graph": Graph,
        "OpenRouterNode": OpenRouterNode,
        "PTYNode": PTYNode,
        "WezTermNode": WezTermNode,
        "ClaudeWezTermNode": ClaudeWezTermNode,
        # Other classes
        "ExecutionContext": ExecutionContext,
        "Session": Session,
        "ParserType": ParserType,
        # Pre-configured instances
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
        graph_obj = namespace.get("graph")
        if graph_obj and isinstance(graph_obj, Graph):
            if dry_run:
                print("\n[DRY RUN]")
                order = graph_obj.execution_order()
                for i, step_id in enumerate(order, 1):
                    print(f"  [{i}] {step_id}")
            else:
                print("\nExecuting Graph...")
                # Use session from namespace (may have been replaced by file)
                exec_session = namespace.get("session")
                if not isinstance(exec_session, Session):
                    exec_session = session
                context = ExecutionContext(session=exec_session)
                await graph_obj.execute(context)
        else:
            print("No 'graph' variable found in file")

    except FileNotFoundError:
        print(f"Error: File not found: {filepath}")
    except Exception as e:
        print(f"Error: {e}")
