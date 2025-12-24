"""Core REPL loop and command execution."""

from __future__ import annotations

import asyncio
from code import compile_command

from nerve.frontends.cli.repl.adapters import (
    LocalSessionAdapter,
    RemoteSessionAdapter,
    SessionAdapter,
)
from nerve.frontends.cli.repl.display import print_graph, print_help, print_nodes
from nerve.frontends.cli.repl.state import REPLState


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
        session = Session(name="default", server_name="repl")
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

                if cmd == "help":
                    print_help()
                    continue

                elif cmd == "nodes":
                    await print_nodes(adapter)
                    continue

                elif cmd == "graphs":
                    try:
                        graph_ids = await adapter.list_graphs()
                        if graph_ids:
                            print("\nGraphs:")
                            for gid in graph_ids:
                                print(f"  {gid}")
                        else:
                            print("No graphs defined")
                    except (ConnectionError, ConnectionResetError, BrokenPipeError, RuntimeError):
                        if not python_exec_enabled:  # Only for remote mode
                            server_disconnected = True
                            break
                        raise
                    continue

                elif cmd == "session":
                    try:
                        # Refresh cached data before displaying
                        await adapter.list_nodes()
                        await adapter.list_graphs()

                        print(f"\nSession: {adapter.name}")
                        print(f"  ID: {adapter.id}")
                        if hasattr(adapter, "server_name"):
                            print(f"  Server: {adapter.server_name}")
                        print(f"  Nodes: {adapter.node_count}")
                        print(f"  Graphs: {adapter.graph_count}")
                    except (ConnectionError, ConnectionResetError, BrokenPipeError, RuntimeError):
                        if not python_exec_enabled:  # Only for remote mode
                            server_disconnected = True
                            break
                        raise
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
                    except (
                        ConnectionError,
                        ConnectionResetError,
                        BrokenPipeError,
                        RuntimeError,
                    ) as e:
                        if not python_exec_enabled:  # Only for remote mode
                            server_disconnected = True
                            break
                        print(f"Error: {e}")
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

                elif cmd == "history":
                    # Works in both local and server mode
                    if len(parts) < 2:
                        print("Usage: history <node> [--last N] [--op TYPE] [--summary]")
                        continue

                    node_name = parts[1]

                    # Parse optional flags
                    args = parts[2:] if len(parts) > 2 else []
                    last = None
                    op = None
                    summary = False

                    i = 0
                    while i < len(args):
                        if args[i] == "--last" and i + 1 < len(args):
                            try:
                                last = int(args[i + 1])
                                i += 2
                            except ValueError:
                                print(f"Invalid --last value: {args[i + 1]}")
                                break
                        elif args[i] == "--op" and i + 1 < len(args):
                            op = args[i + 1]
                            i += 2
                        elif args[i] == "--summary":
                            summary = True
                            i += 1
                        else:
                            i += 1

                    # Import here to avoid circular deps
                    import json
                    from collections import Counter

                    from nerve.core.nodes.history import HistoryReader

                    try:
                        # Determine server and session names
                        if python_exec_enabled:
                            # Local mode
                            server = session.server_name if session else "repl"
                            sess = session.name if session else "default"
                        else:
                            # Server mode
                            server = adapter.server_name
                            sess = adapter.name

                        # Try to read history
                        reader = HistoryReader.create(
                            node_id=node_name,
                            server_name=server,
                            session_name=sess,
                        )

                        # Get entries
                        if op:
                            entries = reader.get_by_op(op)
                        else:
                            entries = reader.get_all()

                        # Apply limit
                        if last is not None and last < len(entries):
                            entries = entries[-last:]

                        if not entries:
                            print("No history entries found")
                            continue

                        # Display
                        if summary:
                            ops_count = Counter(e["op"] for e in entries)
                            print(f"Node: {node_name}")
                            print(f"Server: {server}")
                            print(f"Session: {sess}")
                            print(f"Total entries: {len(entries)}")
                            print("\nOperations:")
                            for op_type, count in sorted(ops_count.items()):
                                print(f"  {op_type}: {count}")
                        else:
                            for entry in entries:
                                seq = entry.get("seq", "?")
                                op_type = entry.get("op", "unknown")
                                ts = entry.get("ts", entry.get("ts_start", ""))
                                ts_display = ts.split("T")[1][:8] if "T" in ts else ts[:8]

                                if op_type == "send":
                                    input_text = entry.get("input", "")[:40]
                                    response = entry.get("response", {})
                                    sections = response.get("sections", [])
                                    print(
                                        f"[{seq:3}] {ts_display} SEND    {input_text!r} -> {len(sections)} sections"
                                    )
                                elif op_type == "run":
                                    cmd = entry.get("input", "")[:40]
                                    print(f"[{seq:3}] {ts_display} RUN     {cmd!r}")
                                elif op_type == "write":
                                    data = entry.get("input", "")[:30].replace("\n", "\\n")
                                    print(f"[{seq:3}] {ts_display} WRITE   {data!r}")
                                elif op_type == "read":
                                    lines = entry.get("lines", 0)
                                    buffer_len = len(entry.get("buffer", ""))
                                    print(
                                        f"[{seq:3}] {ts_display} READ    {lines} lines, {buffer_len} chars"
                                    )
                                else:
                                    print(f"[{seq:3}] {ts_display} {op_type.upper()}")

                    except FileNotFoundError:
                        print(f"No history found for node '{node_name}'")
                    except Exception as e:
                        print(f"Error reading history: {e}")
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
                    session = Session(name="default", server_name="repl")
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
                    if not python_exec_enabled:
                        # SERVER MODE - Send to server
                        from nerve.server.protocols import Command, CommandType

                        if len(parts) < 2:
                            print("Usage: show <graph-name>")
                            continue

                        try:
                            params = {"command": "show", "args": [parts[1]]}
                            if adapter.session_id:
                                params["session_id"] = adapter.session_id

                            result = await adapter.client.send_command(
                                Command(type=CommandType.EXECUTE_REPL_COMMAND, params=params)
                            )

                            if result.success:
                                if result.data.get("output"):
                                    print(result.data["output"], end="")
                                if result.data.get("error"):
                                    print(f"Error: {result.data['error']}")
                            else:
                                print(f"Command failed: {result.error}")
                        except (
                            ConnectionError,
                            ConnectionResetError,
                            BrokenPipeError,
                            RuntimeError,
                        ):
                            server_disconnected = True
                            break
                    else:
                        # LOCAL MODE - Execute locally
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
                    if not python_exec_enabled:
                        # SERVER MODE - Send to server
                        from nerve.server.protocols import Command, CommandType

                        if len(parts) < 2:
                            print("Usage: validate <graph-name>")
                            continue

                        try:
                            params = {"command": "validate", "args": [parts[1]]}
                            if adapter.session_id:
                                params["session_id"] = adapter.session_id

                            result = await adapter.client.send_command(
                                Command(type=CommandType.EXECUTE_REPL_COMMAND, params=params)
                            )

                            if result.success:
                                if result.data.get("output"):
                                    print(result.data["output"], end="")
                                if result.data.get("error"):
                                    print(f"Error: {result.data['error']}")
                            else:
                                print(f"Command failed: {result.error}")
                        except (
                            ConnectionError,
                            ConnectionResetError,
                            BrokenPipeError,
                            RuntimeError,
                        ):
                            server_disconnected = True
                            break
                    else:
                        # LOCAL MODE - Execute locally
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
                    if not python_exec_enabled:
                        # SERVER MODE - Send to server
                        from nerve.server.protocols import Command, CommandType

                        if len(parts) < 2:
                            print("Usage: dry <graph-name>")
                            continue

                        try:
                            params = {"command": "dry", "args": [parts[1]]}
                            if adapter.session_id:
                                params["session_id"] = adapter.session_id

                            result = await adapter.client.send_command(
                                Command(type=CommandType.EXECUTE_REPL_COMMAND, params=params)
                            )

                            if result.success:
                                if result.data.get("output"):
                                    print(result.data["output"], end="")
                                if result.data.get("error"):
                                    print(f"Error: {result.data['error']}")
                            else:
                                print(f"Command failed: {result.error}")
                        except (
                            ConnectionError,
                            ConnectionResetError,
                            BrokenPipeError,
                            RuntimeError,
                        ) as e:
                            server_disconnected = True
                            break
                    else:
                        # LOCAL MODE - Execute locally
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

                    except (ConnectionError, ConnectionResetError, BrokenPipeError, RuntimeError):
                        server_disconnected = True
                        break
                    except Exception as e:
                        print(f"Error: {e}")

                buffer = ""
    finally:
        # Cleanup on REPL exit
        if server_disconnected:
            print("Server connection lost")
        try:
            await adapter.stop()
        except Exception:
            pass  # Best effort cleanup
