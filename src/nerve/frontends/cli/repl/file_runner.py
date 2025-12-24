"""File-based graph execution for REPL."""

from __future__ import annotations

import asyncio


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

    # Create default session for REPL
    session = Session(name="repl", server_name="repl")

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
