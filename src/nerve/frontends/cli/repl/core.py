"""Core REPL loop and command execution."""

from __future__ import annotations

import asyncio
import os
from code import compile_command

from nerve.frontends.cli.repl.adapters import (
    LocalSessionAdapter,
    RemoteSessionAdapter,
    SessionAdapter,
)
from nerve.frontends.cli.repl.registry import (
    CommandAction,
    CommandContext,
    dispatch_command,
)
from nerve.frontends.cli.repl.state import REPLState

# Guard against registering atexit handler multiple times
_atexit_registered = False


async def run_interactive(
    state: REPLState | None = None,
    server_name: str | None = None,
    session_name: str | None = None,
) -> None:
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
        import readline

        # Key bindings for word movement
        readline.parse_and_bind(r'"\e[1;3D": backward-word')
        readline.parse_and_bind(r'"\e[1;3C": forward-word')

        # Limit history to prevent file from growing too large
        readline.set_history_length(1000)

        # History file
        histfile = os.path.expanduser("~/.nerve_repl_history")
        try:
            # Check file size before reading - skip if too large (>1MB)
            if os.path.exists(histfile):
                size = os.path.getsize(histfile)
                if size > 1_000_000:  # 1MB
                    print(
                        f"Warning: History file is too large ({size // 1_000_000}MB), skipping load"
                    )
                    print(f"Consider removing: {histfile}")
                else:
                    readline.read_history_file(histfile)
        except (FileNotFoundError, OSError):
            pass

        # Only register atexit handler once per process
        global _atexit_registered
        if not _atexit_registered:
            atexit.register(readline.write_history_file, histfile)
            _atexit_registered = True
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
    from nerve.core.nodes.bash import BashNode
    from nerve.core.nodes.terminal import ClaudeWezTermNode
    from nerve.core.session import Session

    # Determine mode and create adapter
    adapter: SessionAdapter
    session: Session | None = None
    python_exec_enabled: bool

    if server_name:
        # Server mode - connect to existing server
        from nerve.frontends.cli.utils import get_server_transport

        transport_type, socket_path = get_server_transport(server_name)

        if transport_type != "unix":
            print("Error: Only unix socket servers supported for REPL")
            print(f"Server '{server_name}' uses {transport_type}")
            return

        print(f"Connecting to server '{server_name}'...")
        if socket_path is None:
            print("Error: Could not determine socket path for server")
            return
        try:
            from nerve.transport import UnixSocketClient

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
        session = Session(name="default", server_name="repl")
        adapter = LocalSessionAdapter(session)
        python_exec_enabled = True

    # Initialize namespace (only in local mode for Python REPL features)
    if python_exec_enabled:
        state.namespace = {
            "asyncio": asyncio,
            # Node classes (use with session parameter)
            "BashNode": BashNode,
            "FunctionNode": FunctionNode,
            "Graph": Graph,
            "PTYNode": PTYNode,
            "WezTermNode": WezTermNode,
            "ClaudeWezTermNode": ClaudeWezTermNode,
            # Other classes
            "ExecutionContext": ExecutionContext,
            "Session": Session,
            "ParserType": ParserType,
            # Internal state
            "nodes": state.nodes,  # Node tracking dict
            # Pre-configured instances
            "session": session,  # Default session
            "context": ExecutionContext(session=session),  # Pre-configured context
            "_state": state,
        }
    else:
        state.namespace = {}

    # Track current Graph
    current_graph: Graph | None = None

    # Create command context
    ctx = CommandContext(
        adapter=adapter,
        state=state,
        session=session,
        current_graph=current_graph,
    )

    # Print startup message
    mode_str = f"Server: {server_name}" if server_name else f"Session: {adapter.name}"
    print("Nerve REPL")
    print(f"{mode_str} | Type 'help' for commands\n")

    buffer = ""
    interrupt_count = 0

    # Track if we should exit due to server disconnect
    server_disconnected = False

    try:
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

                # Build command args from parts[1:]
                cmd_args: list[str] = []
                if len(parts) > 1:
                    cmd_args.append(parts[1])
                if len(parts) > 2:
                    cmd_args.append(parts[2])

                # Dispatch to command handler
                result = await dispatch_command(ctx, cmd, cmd_args)
                if result is not None:
                    # Command was handled
                    if result.action == CommandAction.BREAK:
                        break
                    elif result.action == CommandAction.DISCONNECT:
                        server_disconnected = True
                        break
                    # Handle special case: reset command updates session/adapter
                    if "new_session" in ctx.mutable:
                        session = ctx.mutable.pop("new_session")
                        adapter = LocalSessionAdapter(session)
                        ctx.adapter = adapter
                        ctx.session = session
                        current_graph = ctx.current_graph
                    continue

            # Skip empty lines when not in multi-line mode
            if not buffer and not line.strip():
                continue

            # Accumulate input
            if buffer:
                buffer += "\n" + line
            else:
                buffer = line

            # Try to compile (skip if server mode with await)
            from types import CodeType

            code: CodeType | None = None
            should_execute = False
            if python_exec_enabled or "await " not in buffer:
                try:
                    code = compile_command(buffer, symbol="single")

                    if code is None:
                        # Incomplete - need more input
                        continue
                    should_execute = True
                except SyntaxError:
                    # If in server mode, send to server anyway (it can handle await)
                    if not python_exec_enabled:
                        should_execute = True  # Server can handle it
                    elif "await " in buffer:
                        # Local mode with await - skip compile, handle in async block
                        should_execute = True
                    else:
                        raise
            else:
                # Server mode with await - skip compilation, send to server
                should_execute = True

            # Execute based on mode
            if should_execute:
                if python_exec_enabled:
                    # LOCAL MODE - Execute locally
                    try:
                        # Handle async code
                        if "await " in buffer:
                            # Wrap in async function and await it
                            # (we're already in an async context)
                            async_code = "async def __repl_async__():\n"
                            for ln in buffer.split("\n"):
                                async_code += f"    {ln}\n"
                            async_code += "    return locals()\n"
                            exec(compile(async_code, "<repl>", "exec"), state.namespace)
                            # Await the async function and merge locals
                            repl_locals = await state.namespace["__repl_async__"]()
                            # Clean up the temp function
                            state.namespace.pop("__repl_async__", None)
                            # Merge captured locals back into namespace
                            if repl_locals:
                                state.namespace.update(repl_locals)
                        elif code is not None:
                            exec(code, state.namespace)

                        # Track nodes created
                        for name, value in state.namespace.items():
                            if hasattr(value, "state") and hasattr(value, "execute"):
                                if name not in (
                                    "PTYNode",
                                    "WezTermNode",
                                    "ParserType",
                                    "FunctionNode",
                                ):
                                    state.nodes[name] = value

                        # Track Graph
                        if "graph" in state.namespace:
                            current_graph = state.namespace["graph"]
                            ctx.update_graph(current_graph)

                    except Exception as e:
                        print(f"Error: {e}")
                else:
                    # SERVER MODE - Send to server for execution via adapter
                    # RemoteSessionAdapter has execute_python; not in Protocol (local mode uses inline exec)
                    try:
                        output, error = await ctx.adapter.execute_python(buffer, {})  # type: ignore[attr-defined]

                        if error:
                            print(f"Error: {error}")
                        elif output:
                            print(output, end="")

                    except (ConnectionError, ConnectionResetError, BrokenPipeError, RuntimeError):
                        server_disconnected = True
                        break
                    except Exception as e:
                        print(f"Error: {e}")

                buffer = ""
    finally:
        # Comprehensive cleanup on REPL exit - destroy EVERYTHING created in REPL
        import signal

        from nerve.frontends.cli.repl.cleanup import cleanup_repl_resources

        # Block SIGINT during cleanup to ensure it completes
        original_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)

        try:
            is_local = ctx.adapter.supports_local_execution
            await cleanup_repl_resources(
                adapter=ctx.adapter,
                namespace=state.namespace if is_local else None,
                is_local_mode=is_local,
                server_disconnected=server_disconnected,
            )
        finally:
            # Restore original signal handler
            signal.signal(signal.SIGINT, original_handler)
