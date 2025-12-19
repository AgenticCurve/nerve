"""Interactive DAG REPL for nerve.

Ported from wezterm's run_commands.py - provides an interactive
environment for defining and executing DAGs.

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
    """State for the REPL session."""

    namespace: dict[str, Any] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    sessions: dict[str, Any] = field(default_factory=dict)


def print_help():
    """Print usage help."""
    print("""
DAG Definition Syntax:
----------------------
  from nerve.core import Session, CLIType
  from nerve.core.dag import DAG, Task

  # Create sessions
  claude = await Session.create(CLIType.CLAUDE)
  gemini = await Session.create(CLIType.GEMINI)

  # Define tasks
  dag = DAG()

  dag.add_task(Task(
      id="ask",
      execute=lambda ctx: claude.send("Hello!"),
  ))

  dag.add_task(Task(
      id="respond",
      execute=lambda ctx: gemini.send(f"Reply to: {ctx['ask'].raw}"),
      depends_on=["ask"],
  ))

  # Chain shorthand
  dag.chain("ask", "respond")

  # Execute
  results = await dag.run()

Commands:
---------
  help      - Show this help
  sessions  - List active sessions
  clear     - Clear namespace and sessions
  show      - Show current DAG
  validate  - Validate current DAG
  dry       - Dry run (show execution order)
  run       - Execute the DAG
  exit      - Exit the REPL
""")


def print_sessions(state: REPLState):
    """Print active sessions."""
    if not state.sessions:
        print("No active sessions")
        return

    print("\nActive Sessions:")
    print("-" * 40)
    for sid, session in state.sessions.items():
        print(f"  {sid}: {session.cli_type.value} ({session.state.name})")
    print("-" * 40)


def print_dag(dag):
    """Print DAG structure."""
    if not dag or not dag.list_tasks():
        print("No tasks defined")
        return

    print("\nDAG Structure:")
    print("-" * 40)
    for task_id in dag.list_tasks():
        task = dag.get_task(task_id)
        deps = task.depends_on if task else []
        print(f"  {task_id}")
        if deps:
            print(f"    depends on: {', '.join(deps)}")
    print("-" * 40)


async def run_interactive(state: REPLState | None = None):
    """Run interactive DAG definition mode."""
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

    # Initialize namespace with nerve imports
    state.namespace = {
        "asyncio": asyncio,
        "DAG": None,
        "Task": None,
        "Session": None,
        "CLIType": None,
        "sessions": state.sessions,
        "_state": state,
    }

    # Lazy import to avoid circular deps
    from nerve.core import CLIType, Session
    from nerve.core.dag import DAG, Task

    state.namespace.update(
        {
            "DAG": DAG,
            "Task": Task,
            "Session": Session,
            "CLIType": CLIType,
        }
    )

    # Track current DAG
    current_dag: DAG | None = None

    print("=" * 50)
    print("Nerve DAG REPL - Interactive Mode")
    print("=" * 50)
    print("\nType 'help' for syntax guide.")
    print("Commands: help, sessions, clear, show, validate, dry, run, exit")
    print("-" * 50)

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
            cmd = line.strip().lower()

            if cmd == "help":
                print_help()
                continue
            elif cmd == "sessions":
                print_sessions(state)
                continue
            elif cmd == "clear":
                state.sessions.clear()
                state.namespace["sessions"] = state.sessions
                current_dag = None
                print("Cleared sessions and DAG")
                continue
            elif cmd == "show":
                dag = state.namespace.get("dag") or current_dag
                print_dag(dag)
                continue
            elif cmd == "validate":
                dag = state.namespace.get("dag") or current_dag
                if dag:
                    errors = dag.validate()
                    if errors:
                        print("Validation FAILED:")
                        for e in errors:
                            print(f"  - {e}")
                    else:
                        print("Validation PASSED")
                else:
                    print("No DAG defined")
                continue
            elif cmd == "dry":
                dag = state.namespace.get("dag") or current_dag
                if dag:
                    try:
                        order = dag.execution_order()
                        print("\nExecution order:")
                        for i, tid in enumerate(order, 1):
                            print(f"  [{i}] {tid}")
                    except ValueError as e:
                        print(f"Error: {e}")
                else:
                    print("No DAG defined")
                continue
            elif cmd == "run":
                dag = state.namespace.get("dag") or current_dag
                if dag:
                    try:
                        print("\nExecuting DAG...")
                        results = asyncio.get_event_loop().run_until_complete(
                            dag.run(
                                on_task_start=lambda tid: print(f"  Starting: {tid}"),
                                on_task_complete=lambda r: print(
                                    f"  Completed: {r.task_id} ({r.status.name})"
                                ),
                            )
                        )
                        state.namespace["_results"] = results
                        print("\nResults stored in '_results'")
                    except Exception as e:
                        print(f"Error: {e}")
                else:
                    print("No DAG defined")
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

                # Track sessions created
                for name, value in state.namespace.items():
                    if hasattr(value, "cli_type") and hasattr(value, "state"):
                        if name not in ("Session", "CLIType"):
                            state.sessions[name] = value

                # Track DAG
                if "dag" in state.namespace:
                    current_dag = state.namespace["dag"]

            except Exception as e:
                print(f"Error: {e}")

            buffer = ""

        except SyntaxError as e:
            print(f"SyntaxError: {e}")
            buffer = ""


async def run_from_file(filepath: str, dry_run: bool = False):
    """Load and run DAG from a Python file."""
    from nerve.core import CLIType, Session
    from nerve.core.dag import DAG, Task

    namespace = {
        "asyncio": asyncio,
        "DAG": DAG,
        "Task": Task,
        "Session": Session,
        "CLIType": CLIType,
        "__name__": "__nerve_repl__",
    }

    print(f"Loading: {filepath}")
    print("=" * 50)

    try:
        with open(filepath) as f:
            code = f.read()

        # Execute the file
        exec(compile(code, filepath, "exec"), namespace)

        # Look for a DAG to run
        dag = namespace.get("dag")
        if dag:
            if dry_run:
                print("\n[DRY RUN]")
                order = dag.execution_order()
                for i, tid in enumerate(order, 1):
                    print(f"  [{i}] {tid}")
            else:
                print("\nExecuting DAG...")
                await dag.run(
                    on_task_start=lambda tid: print(f"  Starting: {tid}"),
                    on_task_complete=lambda r: print(f"  Completed: {r.task_id} ({r.status.name})"),
                )
        else:
            print("No 'dag' variable found in file")

    except FileNotFoundError:
        print(f"Error: File not found: {filepath}")
    except Exception as e:
        print(f"Error: {e}")


def main():
    """CLI entry point for REPL."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Nerve DAG REPL - Interactive DAG definition and execution"
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Python file containing DAG definition",
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
