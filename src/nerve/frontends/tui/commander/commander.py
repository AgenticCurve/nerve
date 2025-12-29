"""Commander - Unified command center for nerve nodes.

A block-based timeline interface for interacting with nodes.
Connects to a nerve server and session for execution.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console

from nerve.frontends.tui.commander.blocks import Block, Timeline
from nerve.frontends.tui.commander.themes import get_theme

if TYPE_CHECKING:
    from nerve.frontends.cli.repl.adapters import RemoteSessionAdapter
    from nerve.transport import UnixSocketClient


@dataclass
class Commander:
    """Unified command center for interacting with nodes.

    Connects to a nerve server/session and provides a block-based
    timeline interface for interacting with nodes.

    Example:
        >>> commander = Commander(server_name="local", session_name="default")
        >>> await commander.run()
    """

    # Configuration
    server_name: str = "local"
    session_name: str = "default"
    theme_name: str = "default"
    bottom_gutter: int = 3  # Lines of space between prompt and screen bottom
    async_threshold_ms: float = 200  # Show pending if execution exceeds this

    # State (initialized in __post_init__ or run)
    console: Console = field(init=False)
    timeline: Timeline = field(default_factory=Timeline)
    nodes: dict[str, str] = field(default_factory=dict)  # node_id -> node_type

    # Server connection (initialized in run)
    _client: UnixSocketClient | None = field(default=None, init=False)
    _adapter: RemoteSessionAdapter | None = field(default=None, init=False)

    # Internal
    _prompt_session: PromptSession[str] = field(init=False)
    _running: bool = field(default=False, init=False)
    _active_node_id: str | None = field(default=None, init=False)  # Node currently executing
    _current_world: str | None = field(default=None, init=False)  # Focused node world

    # Command queue for non-blocking execution
    # Queue items: (block, command_type, task)
    # - block: The block to update when task completes
    # - command_type: "node_task" or "python_task"
    # - task: asyncio.Task that's already running
    _command_queue: asyncio.Queue[tuple[Block, str, Any]] = field(init=False)
    _executor_task: asyncio.Task[None] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Initialize console and prompt session."""
        theme = get_theme(self.theme_name)
        # force_terminal=True ensures ANSI codes work with patch_stdout()
        self.console = Console(theme=theme, force_terminal=True)
        # Create bottom toolbar with empty lines for gutter space
        # Use empty style to make it invisible (no background color)
        toolbar = "\n" * self.bottom_gutter if self.bottom_gutter > 0 else None
        prompt_style = Style.from_dict(
            {
                "bottom-toolbar": "noreverse",  # Remove default reverse video
            }
        )
        self._prompt_session = PromptSession(
            history=InMemoryHistory(),
            bottom_toolbar=toolbar,
            style=prompt_style,
        )
        # Initialize command queue for tasks that exceed the async threshold
        self._command_queue = asyncio.Queue()

    async def run(self) -> None:
        """Run the commander REPL loop."""
        import signal

        from nerve.frontends.cli.repl.adapters import RemoteSessionAdapter
        from nerve.frontends.cli.utils import get_server_transport
        from nerve.transport import UnixSocketClient

        self._running = True

        # Connect to server
        transport_type, socket_path = get_server_transport(self.server_name)

        if transport_type != "unix":
            self.console.print("[error]Only unix socket servers supported[/]")
            self.console.print(f"[dim]Server '{self.server_name}' uses {transport_type}[/]")
            return

        if socket_path is None:
            self.console.print("[error]Could not determine socket path[/]")
            return

        self.console.print(f"[dim]Connecting to server '{self.server_name}'...[/]")
        try:
            self._client = UnixSocketClient(socket_path)
            await self._client.connect()
        except Exception as e:
            self.console.print(f"[error]Failed to connect: {e}[/]")
            self.console.print(
                f"[dim]Make sure server is running: nerve server start --name {self.server_name}[/]"
            )
            return

        self._adapter = RemoteSessionAdapter(self._client, self.server_name, self.session_name)
        self.console.print(f"[dim]Connected! Session: {self.session_name}[/]")

        # Fetch nodes from session
        await self._sync_nodes()

        # Print welcome
        self._print_welcome()

        # Start background executor for non-blocking command processing
        self._executor_task = asyncio.create_task(self._command_executor())

        # Setup SIGINT handler to interrupt active node
        original_handler = signal.getsignal(signal.SIGINT)

        def sigint_handler(signum: int, frame: Any) -> None:
            """Handle Ctrl-C by interrupting active node."""
            if self._active_node_id is not None and self._client is not None:
                # Schedule interrupt on the event loop
                asyncio.ensure_future(self._send_interrupt(self._active_node_id))
            # Don't exit - let the command complete with interrupted status

        signal.signal(signal.SIGINT, sigint_handler)

        try:
            # Main loop - wrap in patch_stdout to coordinate background prints
            # with prompt_toolkit's input line management
            # raw=True preserves ANSI escape sequences in output
            with patch_stdout(raw=True):
                while self._running:
                    try:
                        # Dynamic prompt based on current world
                        if self._current_world:
                            prompt = f"{self._current_world}❯ "
                        else:
                            prompt = "❯ "

                        user_input = await self._prompt_session.prompt_async(prompt)

                        if not user_input.strip():
                            continue

                        await self._handle_input(user_input.strip())

                    except KeyboardInterrupt:
                        # Ctrl-C at prompt - just print newline and continue
                        self.console.print()
                        continue
                    except EOFError:
                        break
        finally:
            # Restore original signal handler
            signal.signal(signal.SIGINT, original_handler)

        # Cleanup
        await self._cleanup()

    async def _sync_nodes(self) -> None:
        """Fetch nodes from server session."""
        if self._adapter is None:
            return

        try:
            node_list = await self._adapter.list_nodes()
            self.nodes.clear()
            for node_id, node_type in node_list:
                self.nodes[node_id] = node_type
        except Exception as e:
            self.console.print(f"[warning]Failed to fetch nodes: {e}[/]")

    async def _send_interrupt(self, node_id: str) -> None:
        """Send interrupt signal to a node via server."""
        if self._client is None:
            return

        from nerve.server.protocols import Command, CommandType

        try:
            await self._client.send_command(
                Command(
                    type=CommandType.SEND_INTERRUPT,
                    params={"node_id": node_id, "session_id": self.session_name},
                )
            )
        except Exception:
            pass  # Ignore errors during interrupt

    def _print_welcome(self) -> None:
        """Print welcome message."""
        self.console.print()
        self.console.print("[bold]Commander[/] - Nerve Command Center", style="prompt")
        self.console.print(
            f"[dim]Server: {self.server_name} | Session: {self.session_name} | Nodes: {len(self.nodes)}[/]"
        )
        if self.nodes:
            self.console.print("[dim]Use @<node> <message> to interact. :help for commands.[/]")
        else:
            self.console.print(
                "[dim]No nodes in session. Create nodes first with: nerve server node create[/]"
            )
        self.console.print()

    async def _handle_input(self, user_input: str) -> None:
        """Handle user input and dispatch to appropriate handler."""
        # Commands always start with : (works in any world)
        if user_input.startswith(":"):
            await self._handle_command(user_input[1:])
            return

        # If in a world, route directly to that node
        if self._current_world:
            # Check if it's a python world
            if self._current_world == "python":
                await self._handle_python(user_input)
            else:
                # Route to the current world's node
                await self._handle_node_message(f"{self._current_world} {user_input}")
            return

        # Node messages start with @
        if user_input.startswith("@"):
            await self._handle_node_message(user_input[1:])

        # Python code starts with >>>
        elif user_input.startswith(">>>"):
            await self._handle_python(user_input[3:].strip())

        # Default: show help
        else:
            self.console.print(
                "[dim]Prefix with @node_name to send to a node, "
                ">>> for Python, or :help for commands[/]"
            )

    async def _handle_command(self, cmd: str) -> None:
        """Handle colon commands like :help, :quit, :timeline."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        if command == "exit":
            # If in a world, exit the world; otherwise exit commander
            if self._current_world:
                self._exit_world()
            else:
                self._running = False
                self.console.print("[dim]Goodbye![/]")

        elif command == "back":
            # Exit current world back to main
            if self._current_world:
                self._exit_world()
            else:
                self.console.print("[dim]Already at main timeline[/]")

        elif command == "help":
            self._print_help()

        elif command == "nodes":
            await self._print_nodes()

        elif command == "timeline":
            self._print_timeline(args)

        elif command == "clear":
            # Full viewport clear using ANSI escape codes
            # \033[2J clears entire screen, \033[H moves cursor to home (0,0)
            # \033[3J also clears scrollback buffer for a true fresh start
            print("\033[2J\033[3J\033[H", end="", flush=True)

        elif command == "clean":
            self._clean_blocks()

        elif command == "refresh":
            await self._refresh_view()

        elif command == "theme":
            self._switch_theme(args)

        elif command == "world":
            await self._show_world(args)

        elif command == "loop":
            await self._handle_loop(args)

        else:
            self.console.print(f"[warning]Unknown command: {command}[/]")

    async def _handle_node_message(self, message: str) -> None:
        """Handle @node_name message syntax with threshold-based async.

        Fast operations (< async_threshold_ms) execute synchronously.
        Slow operations show pending state and execute in background.
        """
        if self._adapter is None:
            self.console.print("[error]Not connected to server[/]")
            return

        parts = message.split(maxsplit=1)
        if not parts:
            self.console.print("[warning]Usage: @node_name message[/]")
            return

        node_id = parts[0]
        text = parts[1] if len(parts) > 1 else ""

        if not text:
            self.console.print(f"[warning]No message provided for @{node_id}[/]")
            return

        if node_id not in self.nodes:
            # Try to sync nodes in case new ones were added
            await self._sync_nodes()
            if node_id not in self.nodes:
                self.console.print(f"[error]Node not found: {node_id}[/]")
                self.console.print(
                    f"[dim]Available nodes: {', '.join(self.nodes.keys()) or 'none'}[/]"
                )
                return

        node_type = self.nodes[node_id]
        block_type = self._get_block_type_from_str(node_type)

        # Expand variables BEFORE adding block to timeline
        # This ensures :::-1 references the previous block, not the current one
        expanded_text = self._expand_variables(text)

        # Create block with assigned number (don't render yet)
        # input_text stores RAW text (what user typed)
        block = Block(
            block_type=block_type,
            node_id=node_id,
            input_text=text,
            status="running",
        )
        self.timeline.add(block)

        # Try to execute within threshold - if fast, show result directly
        start_time = time.monotonic()
        threshold_seconds = self.async_threshold_ms / 1000

        try:
            # Create execution task with already-expanded text
            exec_task = asyncio.create_task(
                self._execute_node_command(block, expanded_text, start_time)
            )

            # Wait with timeout
            await asyncio.wait_for(
                asyncio.shield(exec_task),  # shield so we can continue if timeout
                timeout=threshold_seconds,
            )

            # Fast path: completed within threshold, render result
            self.timeline.render_last(self.console)

        except TimeoutError:
            # Slow path: show pending and queue for background completion
            block.status = "pending"
            self.timeline.render_last(self.console)

            # Queue the ongoing task for the executor to monitor
            await self._command_queue.put((block, "node_task", exec_task))

    async def _handle_python(self, code: str) -> None:
        """Handle Python code execution with threshold-based async.

        Fast operations (< async_threshold_ms) execute synchronously.
        Slow operations show pending state and execute in background.
        """
        if not code:
            self.console.print("[dim]Enter Python code after >>>[/]")
            return

        if self._adapter is None:
            self.console.print("[error]Not connected to server[/]")
            return

        # Create block with assigned number (don't render yet)
        block = Block(
            block_type="python",
            node_id=None,
            input_text=code,
            status="running",
        )
        self.timeline.add(block)

        # Try to execute within threshold - if fast, show result directly
        start_time = time.monotonic()
        threshold_seconds = self.async_threshold_ms / 1000

        try:
            # Create execution task
            exec_task = asyncio.create_task(self._execute_python_command(block, code, start_time))

            # Wait with timeout
            await asyncio.wait_for(
                asyncio.shield(exec_task),
                timeout=threshold_seconds,
            )

            # Fast path: completed within threshold, render result
            self.timeline.render_last(self.console)

        except TimeoutError:
            # Slow path: show pending and queue for background completion
            block.status = "pending"
            self.timeline.render_last(self.console)

            # Queue the ongoing task for the executor to monitor
            await self._command_queue.put((block, "python_task", exec_task))

    def _get_block_type_from_str(self, node_type: str) -> str:
        """Determine block type from node type string.

        Args:
            node_type: Node type name from server (e.g., "BashNode", "LLMChatNode").

        Returns:
            Block type for rendering ("bash", "llm", or "node").
        """
        node_type_lower = node_type.lower()
        if "bash" in node_type_lower:
            return "bash"
        elif "llm" in node_type_lower or "chat" in node_type_lower:
            return "llm"
        else:
            return "node"

    def _expand_variables(self, text: str) -> str:
        """Expand :::N['key'] variables in text.

        Supports:
            Block references (0-indexed):
                :::0                     - first block's output
                :::N['output']           - output from block N
                :::N['input']            - input from block N
                :::N['raw']['stdout']    - raw stdout from block N
                :::-1                    - last block (negative indexing)
                :::-2                    - second to last block
                :::last                  - last block's output

            Node references (per-node indexing):
                :::claude                - last block from node 'claude'
                :::claude[0]             - first block from 'claude'
                :::claude[-1]            - last block from 'claude'
                :::claude[-2]            - second to last from 'claude'
                :::bash[0]['input']      - first bash block's input

        Args:
            text: Text with variable references.

        Returns:
            Text with variables expanded to their values.
        """
        import re

        def get_block_by_negative_index(neg_idx: int) -> Block | None:
            """Get block by negative index (-1 = last, -2 = second to last)."""
            blocks = self.timeline.blocks
            if not blocks:
                return None
            try:
                return blocks[neg_idx]  # Python handles negative indexing
            except IndexError:
                return None

        def get_node_blocks(node_id: str) -> list[Block]:
            """Get all blocks for a specific node."""
            return [b for b in self.timeline.blocks if b.node_id == node_id]

        def get_node_block_by_index(node_id: str, idx: int) -> Block | None:
            """Get block by index within a node's blocks (supports negative indexing)."""
            node_blocks = get_node_blocks(node_id)
            if not node_blocks:
                return None
            try:
                return node_blocks[idx]
            except IndexError:
                return None

        # Pattern: :::-N['raw']['key'] - negative index nested raw access
        neg_raw_pattern = r":::(-\d+)\[(['\"])raw\2\]\[(['\"])(\w+)\3\]"

        def replace_neg_raw_var(match: re.Match[str]) -> str:
            neg_idx = int(match.group(1))
            key = match.group(4)
            block = get_block_by_negative_index(neg_idx)
            if block is None:
                return f"<error: no block at index {neg_idx}>"
            try:
                raw = block["raw"]
                if isinstance(raw, dict):
                    return str(raw.get(key, f"<no key: {key}>"))
                return "<error: raw is not a dict>"
            except KeyError as e:
                return f"<error: {e}>"

        text = re.sub(neg_raw_pattern, replace_neg_raw_var, text)

        # Pattern: :::-N['key'] - negative index simple access
        neg_pattern = r":::(-\d+)\[(['\"])(\w+)\2\]"

        def replace_neg_var(match: re.Match[str]) -> str:
            neg_idx = int(match.group(1))
            key = match.group(3)
            block = get_block_by_negative_index(neg_idx)
            if block is None:
                return f"<error: no block at index {neg_idx}>"
            try:
                value = block[key]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        text = re.sub(neg_pattern, replace_neg_var, text)

        # Pattern: :::-N (bare negative reference - shorthand for :::-N['output'])
        bare_neg_pattern = r":::(-\d+)(?!\[)"

        def replace_bare_neg_var(match: re.Match[str]) -> str:
            neg_idx = int(match.group(1))
            block = get_block_by_negative_index(neg_idx)
            if block is None:
                return f"<error: no block at index {neg_idx}>"
            try:
                value = block["output"]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        text = re.sub(bare_neg_pattern, replace_bare_neg_var, text)

        # Pattern: :::N['raw']['key'] - nested raw access (must match first)
        raw_pattern = r":::(\d+)\[(['\"])raw\2\]\[(['\"])(\w+)\3\]"

        def replace_raw_var(match: re.Match[str]) -> str:
            block_num = int(match.group(1))
            key = match.group(4)
            try:
                block = self.timeline[block_num]
                raw = block["raw"]
                if isinstance(raw, dict):
                    return str(raw.get(key, f"<no key: {key}>"))
                return "<error: raw is not a dict>"
            except (IndexError, KeyError) as e:
                return f"<error: {e}>"

        text = re.sub(raw_pattern, replace_raw_var, text)

        # Pattern: :::last['raw']['key'] - nested raw access for last block
        last_raw_pattern = r":::last\[(['\"])raw\1\]\[(['\"])(\w+)\2\]"

        def replace_last_raw_var(match: re.Match[str]) -> str:
            key = match.group(3)
            block = self.timeline.last()
            if block is None:
                return "<error: no blocks yet>"
            try:
                raw = block["raw"]
                if isinstance(raw, dict):
                    return str(raw.get(key, f"<no key: {key}>"))
                return "<error: raw is not a dict>"
            except KeyError as e:
                return f"<error: {e}>"

        text = re.sub(last_raw_pattern, replace_last_raw_var, text)

        # Pattern: :::N['key'] or :::N["key"] - simple access
        pattern = r":::(\d+)\[(['\"])(\w+)\2\]"

        def replace_block_var(match: re.Match[str]) -> str:
            block_num = int(match.group(1))
            key = match.group(3)
            try:
                block = self.timeline[block_num]
                value = block[key]
                return str(value) if not isinstance(value, str) else value
            except (IndexError, KeyError) as e:
                return f"<error: {e}>"

        text = re.sub(pattern, replace_block_var, text)

        # Pattern: :::last['key'] or :::last["key"]
        last_pattern = r":::last\[(['\"])(\w+)\1\]"

        def replace_last_var(match: re.Match[str]) -> str:
            key = match.group(2)
            block = self.timeline.last()
            if block is None:
                return "<error: no blocks yet>"
            try:
                value = block[key]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        text = re.sub(last_pattern, replace_last_var, text)

        # Pattern: :::N (bare reference - shorthand for :::N['output'])
        bare_pattern = r":::(\d+)(?!\[)"  # \d+ not followed by [

        def replace_bare_var(match: re.Match[str]) -> str:
            block_num = int(match.group(1))
            try:
                block = self.timeline[block_num]
                value = block["output"]
                return str(value) if not isinstance(value, str) else value
            except (IndexError, KeyError) as e:
                return f"<error: {e}>"

        text = re.sub(bare_pattern, replace_bare_var, text)

        # Pattern: :::last (bare reference - shorthand for :::last['output'])
        bare_last_pattern = r":::last(?!\[)"

        def replace_bare_last_var(match: re.Match[str]) -> str:
            block = self.timeline.last()
            if block is None:
                return "<error: no blocks yet>"
            try:
                value = block["output"]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        text = re.sub(bare_last_pattern, replace_bare_last_var, text)

        # =====================================================================
        # Node-based references: :::nodename, :::nodename[N], :::nodename[-1]
        # =====================================================================
        # Node names: start with letter/underscore, contain alphanumeric/underscore/hyphen
        # Must not match: numbers, "last", or negative numbers

        # Pattern: :::node[N]['raw']['key'] - node indexed with raw access
        node_idx_raw_pattern = (
            r":::([a-zA-Z_][a-zA-Z0-9_-]*)\[(-?\d+)\]\[(['\"])raw\3\]\[(['\"])(\w+)\4\]"
        )

        def replace_node_idx_raw_var(match: re.Match[str]) -> str:
            node_id = match.group(1)
            idx = int(match.group(2))
            key = match.group(5)
            block = get_node_block_by_index(node_id, idx)
            if block is None:
                return f"<error: no block for {node_id}[{idx}]>"
            try:
                raw = block["raw"]
                if isinstance(raw, dict):
                    return str(raw.get(key, f"<no key: {key}>"))
                return "<error: raw is not a dict>"
            except KeyError as e:
                return f"<error: {e}>"

        text = re.sub(node_idx_raw_pattern, replace_node_idx_raw_var, text)

        # Pattern: :::node[N]['key'] - node indexed with key access
        node_idx_key_pattern = r":::([a-zA-Z_][a-zA-Z0-9_-]*)\[(-?\d+)\]\[(['\"])(\w+)\3\]"

        def replace_node_idx_key_var(match: re.Match[str]) -> str:
            node_id = match.group(1)
            idx = int(match.group(2))
            key = match.group(4)
            block = get_node_block_by_index(node_id, idx)
            if block is None:
                return f"<error: no block for {node_id}[{idx}]>"
            try:
                value = block[key]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        text = re.sub(node_idx_key_pattern, replace_node_idx_key_var, text)

        # Pattern: :::node[N] - node indexed bare (output shorthand)
        node_idx_bare_pattern = r":::([a-zA-Z_][a-zA-Z0-9_-]*)\[(-?\d+)\](?!\[)"

        def replace_node_idx_bare_var(match: re.Match[str]) -> str:
            node_id = match.group(1)
            idx = int(match.group(2))
            block = get_node_block_by_index(node_id, idx)
            if block is None:
                return f"<error: no block for {node_id}[{idx}]>"
            try:
                value = block["output"]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        text = re.sub(node_idx_bare_pattern, replace_node_idx_bare_var, text)

        # Pattern: :::node['key'] - node last block with key access
        node_key_pattern = r":::([a-zA-Z_][a-zA-Z0-9_-]*)\[(['\"])(\w+)\2\]"

        def replace_node_key_var(match: re.Match[str]) -> str:
            node_id = match.group(1)
            key = match.group(3)
            block = get_node_block_by_index(node_id, -1)  # Last block for this node
            if block is None:
                return f"<error: no blocks for {node_id}>"
            try:
                value = block[key]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        text = re.sub(node_key_pattern, replace_node_key_var, text)

        # Pattern: :::node - node last block bare (output shorthand)
        # Must not match "last" or start with digit or hyphen
        node_bare_pattern = r":::([a-zA-Z_][a-zA-Z0-9_-]*)(?!\[)(?<!:::last)"

        def replace_node_bare_var(match: re.Match[str]) -> str:
            node_id = match.group(1)
            if node_id == "last":  # Skip, handled by bare_last_pattern
                return match.group(0)
            block = get_node_block_by_index(node_id, -1)  # Last block for this node
            if block is None:
                return f"<error: no blocks for {node_id}>"
            try:
                value = block["output"]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        text = re.sub(node_bare_pattern, replace_node_bare_var, text)

        return text

    def _print_help(self) -> None:
        """Print help message."""
        self.console.print()
        self.console.print("[bold]Commands:[/]")
        self.console.print("  [bold]@node message[/]  Send message to a node")
        self.console.print("  [bold]>>> code[/]       Execute Python code")
        self.console.print("  [bold]Ctrl+C[/]         Interrupt running command")
        self.console.print()
        self.console.print("[bold]Block References:[/] (0-indexed)")
        self.console.print("  [bold]:::0[/]                   First block's output")
        self.console.print("  [bold]:::N[/]                   Block N's output")
        self.console.print("  [bold]:::N['input'][/]          Block N's input text")
        self.console.print("  [bold]:::-1[/]                  Last block (negative indexing)")
        self.console.print("  [bold]:::-2[/]                  Second to last block")
        self.console.print()
        self.console.print("[bold]Node References:[/] (per-node indexing)")
        self.console.print("  [bold]:::claude[/]              Last block from node 'claude'")
        self.console.print("  [bold]:::claude[0][/]           First block from 'claude'")
        self.console.print("  [bold]:::claude[-2][/]          Second to last from 'claude'")
        self.console.print("  [bold]:::bash[0]['input'][/]    First bash block's input")
        self.console.print()
        self.console.print("[bold]Colon Commands:[/]")
        self.console.print("  [bold]:world bash[/]    Enter bash world (no @ prefix needed)")
        self.console.print("  [bold]:world python[/]  Enter python world (no >>> needed)")
        self.console.print("  [bold]:back[/]          Exit current world")
        self.console.print("  [bold]:timeline[/]      Show timeline (filtered in world)")
        self.console.print("  [bold]:refresh[/]       Clear screen and re-render view")
        self.console.print("  [bold]:clean[/]         Clear all blocks, start from :::0")
        self.console.print("  [bold]:nodes[/]         List available nodes")
        self.console.print("  [bold]:theme name[/]    Switch theme")
        self.console.print("  [bold]:exit[/]          Exit world or commander")
        self.console.print()
        self.console.print("[bold]Loop Command:[/]")
        self.console.print('  [bold]:loop @n1 @n2 "prompt" [options][/]')
        self.console.print("    Round-robin conversation between nodes")
        self.console.print('    [dim]--until "phrase"[/]  Stop when output contains phrase')
        self.console.print("    [dim]--max N[/]           Maximum rounds (default: 10)")
        self.console.print('    [dim]--node "template"[/] Per-node prompt template')
        self.console.print("    Template variables:")
        self.console.print("      [dim]{prev}[/]    Previous step's output")
        self.console.print(
            "      [dim]{node}[/]    That node's last output (e.g., {claude}, {bash})"
        )
        self.console.print(
            '  [dim]Example: :loop @claude @gemini "discuss AI" --until "AGREED" --max 5[/]'
        )
        self.console.print()

    async def _print_nodes(self) -> None:
        """Print available nodes (syncs from server first)."""
        await self._sync_nodes()

        self.console.print()
        self.console.print("[bold]Available Nodes:[/]")
        if not self.nodes:
            self.console.print("  [dim]No nodes in session[/]")
        else:
            for node_id, node_type in self.nodes.items():
                self.console.print(f"  [bold]{node_id}[/] ({node_type})")
        self.console.print()

    def _print_timeline(self, args: str) -> None:
        """Print timeline (optionally limited to last N)."""
        limit = None
        if args:
            try:
                limit = int(args)
            except ValueError:
                self.console.print(f"[warning]Invalid number: {args}[/]")
                return

        # Filter by current world if in one
        if self._current_world:
            if self._current_world == "python":
                blocks = self.timeline.filter_by_type("python")
            else:
                blocks = self.timeline.filter_by_node(self._current_world)
        else:
            blocks = self.timeline.blocks

        if not blocks:
            self.console.print("[dim]No blocks in timeline yet[/]")
            return

        self.console.print()
        blocks_to_render = blocks[-limit:] if limit else blocks
        for i, block in enumerate(blocks_to_render):
            self.console.print(block.render(self.console, show_separator=(i > 0)))

    def _switch_theme(self, theme_name: str) -> None:
        """Switch to a different theme."""
        if not theme_name:
            self.console.print("[dim]Available themes: default, nord, dracula, mono[/]")
            return

        theme = get_theme(theme_name)
        self.console = Console(theme=theme, force_terminal=True)
        self.theme_name = theme_name
        self.console.print(f"[success]Switched to theme: {theme_name}[/]")

    async def _show_world(self, node_id: str) -> None:
        """Enter a node's world (focused mode)."""
        # Handle "python" as a special world (not a node)
        if node_id == "python":
            self._enter_world("python")
            return

        if not node_id:
            # No argument - show current world or list available
            if self._current_world:
                self.console.print(f"[dim]Currently in world: {self._current_world}[/]")
            else:
                self.console.print("[dim]Available worlds:[/]")
                for nid in self.nodes:
                    self.console.print(f"  [bold]{nid}[/]")
                self.console.print("  [bold]python[/]")
            return

        if node_id not in self.nodes:
            self.console.print(f"[error]Node not found: {node_id}[/]")
            return

        self._enter_world(node_id)

    def _enter_world(self, world_id: str) -> None:
        """Enter a focused world."""
        self._current_world = world_id

        self.console.print()
        if world_id == "python":
            self.console.print("[bold]World: python[/]")
            self.console.print("[dim]Type Python code directly. :exit or :back to leave.[/]")
            # Show python blocks
            python_blocks = self.timeline.filter_by_type("python")
            if python_blocks:
                self.console.print(f"[dim]History: {len(python_blocks)} blocks[/]")
                self.console.print()
                for i, block in enumerate(python_blocks):
                    self.console.print(block.render(self.console, show_separator=(i > 0)))
            else:
                self.console.print()
        else:
            node_type = self.nodes.get(world_id, "?")
            self.console.print(f"[bold]World: @{world_id}[/] ({node_type})")
            self.console.print("[dim]Type commands directly. :exit or :back to leave.[/]")

            # Show blocks for this node
            node_blocks = self.timeline.filter_by_node(world_id)
            if node_blocks:
                self.console.print(f"[dim]History: {len(node_blocks)} blocks[/]")
                self.console.print()
                for i, block in enumerate(node_blocks):
                    self.console.print(block.render(self.console, show_separator=(i > 0)))
            else:
                self.console.print()

    def _exit_world(self) -> None:
        """Exit the current world back to main."""
        old_world = self._current_world
        self._current_world = None
        self.console.print(f"[dim]Left world: {old_world}[/]")
        self.console.print()

    def _clean_blocks(self) -> None:
        """Clear all blocks and reset numbering."""
        count = len(self.timeline)
        self.timeline.clear()
        self.console.clear()
        self._print_welcome()
        self.console.print(f"[dim]Cleared {count} blocks. Starting fresh from :::0[/]")
        self.console.print()

    async def _refresh_view(self) -> None:
        """Clear screen and re-render current view."""
        # Sync nodes from server before refresh
        await self._sync_nodes()

        self.console.clear()

        # Re-render based on current context
        if self._current_world:
            # In a world - show world header and filtered blocks
            if self._current_world == "python":
                self.console.print("[bold]World: python[/]")
                blocks = self.timeline.filter_by_type("python")
            else:
                node_type = self.nodes.get(self._current_world, "?")
                self.console.print(f"[bold]World: @{self._current_world}[/] ({node_type})")
                blocks = self.timeline.filter_by_node(self._current_world)

            if blocks:
                self.console.print(f"[dim]History: {len(blocks)} blocks[/]")
                self.console.print()
                for i, block in enumerate(blocks):
                    self.console.print(block.render(self.console, show_separator=(i > 0)))
            else:
                self.console.print()
        else:
            # Main view - show welcome and all blocks
            self._print_welcome()
            if self.timeline.blocks:
                for i, block in enumerate(self.timeline.blocks):
                    self.console.print(block.render(self.console, show_separator=(i > 0)))

    async def _handle_loop(self, args: str) -> None:
        """Handle :loop command for multi-node conversation chains.

        Syntax:
            :loop @node1 @node2 [@node3...] "start prompt" [options]

        Options:
            --until "phrase"     Stop when output contains phrase
            --max N              Maximum rounds (default: 10)
            --<node> "template"  Per-node prompt template ({prev} = previous output)

        Pattern: Chain (round-robin)
            A → B → C → A → B → C → ...

        Example:
            :loop @claude @gemini "implement fibonacci" --until "LGTM" --max 5
            :loop @dev @reviewer "write a parser" --dev "Feedback: {prev}" --reviewer "Review: {prev}"
        """
        if not args.strip():
            self.console.print(
                '[warning]Usage: :loop @node1 @node2 "start prompt" [--until phrase] [--max N][/]'
            )
            self.console.print('[dim]Example: :loop @claude @gemini "discuss AI" --max 5[/]')
            return

        # Parse the loop arguments
        parsed = self._parse_loop_args(args)
        if parsed is None:
            return  # Error already printed

        nodes, start_prompt, until_phrase, max_rounds, templates = parsed

        # Validate nodes exist
        await self._sync_nodes()
        for node_id in nodes:
            if node_id not in self.nodes:
                self.console.print(f"[error]Node not found: {node_id}[/]")
                return

        if len(nodes) < 2:
            self.console.print("[error]Loop requires at least 2 nodes[/]")
            return

        # Print loop start info
        self.console.print()
        self.console.print(f"[bold]Starting loop:[/] {' → '.join('@' + n for n in nodes)}")
        self.console.print(
            f"[dim]Max rounds: {max_rounds}"
            + (f', until: "{until_phrase}"' if until_phrase else "")
            + "[/]"
        )
        self.console.print()

        # Execute the loop
        prev_output = start_prompt
        node_outputs: dict[str, str] = {}  # Track last output from each node
        exchange_num = 0  # Total exchanges for reporting
        stopped_by_phrase = False
        aborted = False

        try:
            for round_num in range(max_rounds):
                for step, node_id in enumerate(nodes):
                    # Build the prompt
                    if round_num == 0 and step == 0:
                        # First exchange: use start prompt directly
                        prompt = start_prompt
                    else:
                        # Subsequent: use template or raw prev_output
                        template = templates.get(node_id, "{prev}")
                        prompt = template.replace("{prev}", prev_output)
                        # Replace {nodename} references with that node's last output
                        for nid, output in node_outputs.items():
                            prompt = prompt.replace("{" + nid + "}", output)

                    # Execute on node (creates block, updates timeline)
                    block = await self._execute_loop_step(node_id, prompt)
                    if block is None:
                        self.console.print("[error]Loop aborted due to execution error[/]")
                        aborted = True
                        break

                    # Get output for next iteration
                    prev_output = block.output_text or ""
                    node_outputs[node_id] = prev_output  # Track this node's output
                    exchange_num += 1

                    # Check stop condition
                    if until_phrase and until_phrase in prev_output:
                        stopped_by_phrase = True
                        break

                # Break outer loop if inner loop broke
                if stopped_by_phrase or aborted:
                    break

        except KeyboardInterrupt:
            self.console.print()
            self.console.print("[warning]Loop interrupted by user[/]")
            return

        # Print summary
        self.console.print()
        if stopped_by_phrase:
            self.console.print(
                f'[success]Loop ended: "{until_phrase}" detected after {exchange_num} exchanges[/]'
            )
        elif aborted:
            self.console.print(f"[error]Loop aborted after {exchange_num} exchanges[/]")
        else:
            self.console.print(
                f"[dim]Loop completed: {exchange_num} exchanges ({max_rounds} rounds)[/]"
            )

    def _parse_loop_args(
        self, args: str
    ) -> tuple[list[str], str, str | None, int, dict[str, str]] | None:
        """Parse :loop command arguments.

        Returns:
            Tuple of (nodes, start_prompt, until_phrase, max_rounds, templates)
            or None if parsing failed.
        """
        import shlex

        # Default values
        max_rounds = 10
        until_phrase: str | None = None
        templates: dict[str, str] = {}
        nodes: list[str] = []
        start_prompt: str | None = None

        try:
            # Use shlex to handle quoted strings properly
            tokens = shlex.split(args)
        except ValueError as e:
            self.console.print(f"[error]Parse error: {e}[/]")
            return None

        i = 0
        while i < len(tokens):
            token = tokens[i]

            if token.startswith("@"):
                # Node reference
                nodes.append(token[1:])
                i += 1

            elif token == "--until":
                # Until phrase
                if i + 1 >= len(tokens):
                    self.console.print("[error]--until requires a value[/]")
                    return None
                until_phrase = tokens[i + 1]
                i += 2

            elif token == "--max":
                # Max rounds
                if i + 1 >= len(tokens):
                    self.console.print("[error]--max requires a number[/]")
                    return None
                try:
                    max_rounds = int(tokens[i + 1])
                except ValueError:
                    self.console.print(f"[error]--max must be a number, got: {tokens[i + 1]}[/]")
                    return None
                i += 2

            elif token.startswith("--"):
                # Per-node template: --nodename "template"
                node_name = token[2:]
                if i + 1 >= len(tokens):
                    self.console.print(f"[error]{token} requires a template value[/]")
                    return None
                templates[node_name] = tokens[i + 1]
                i += 2

            elif start_prompt is None:
                # First non-option, non-node token is the start prompt
                start_prompt = token
                i += 1

            else:
                self.console.print(f"[error]Unexpected argument: {token}[/]")
                return None

        # Validate
        if not nodes:
            self.console.print("[error]No nodes specified. Use @node1 @node2 ...[/]")
            return None

        if start_prompt is None:
            self.console.print("[error]No start prompt specified[/]")
            return None

        return nodes, start_prompt, until_phrase, max_rounds, templates

    async def _execute_loop_step(self, node_id: str, prompt: str) -> Block | None:
        """Execute a single step in the loop, creating a block.

        Args:
            node_id: Node to execute on.
            prompt: Prompt to send.

        Returns:
            The completed Block, or None on error.
        """
        import time

        if self._adapter is None:
            return None

        node_type = self.nodes.get(node_id, "node")
        block_type = self._get_block_type_from_str(node_type)

        # Expand variables BEFORE adding block to timeline
        # This ensures :::-1 references the previous block, not the current one
        expanded_prompt = self._expand_variables(prompt)

        # Create and add block (input_text stores RAW prompt)
        block = Block(
            block_type=block_type,
            node_id=node_id,
            input_text=prompt,
            status="running",
        )
        self.timeline.add(block)

        # Render the running block
        self.timeline.render_last(self.console)

        # Execute
        start_time = time.monotonic()

        try:
            self._active_node_id = node_id
            result = await self._adapter.execute_on_node(node_id, expanded_prompt)
        except Exception as e:
            block.status = "error"
            block.error = f"{type(e).__name__}: {e}"
            block.duration_ms = (time.monotonic() - start_time) * 1000
            self._print_block(block)
            return None
        finally:
            self._active_node_id = None

        duration_ms = (time.monotonic() - start_time) * 1000

        # Update block with results
        if result.get("success"):
            block.status = "completed"
            block.output_text = str(result.get("output", "")).strip()
            block.raw = result
        else:
            block.status = "error"
            error_msg = result.get("error", "Unknown error")
            error_type = result.get("error_type", "unknown")
            block.error = f"[{error_type}] {error_msg}"
            block.raw = result

        block.duration_ms = duration_ms

        # Print the completed block
        self._print_block(block)

        return block if block.status == "completed" else None

    async def _command_executor(self) -> None:
        """Background task that processes commands from the queue.

        Waits for ongoing tasks (node_task, python_task) that exceeded the
        async threshold, then renders the completed block.
        """
        while True:
            try:
                # Wait for next item (block, command_type, task)
                block, _, task = await self._command_queue.get()

                try:
                    # Ongoing task - wait for it to complete
                    # The task is already running and will update the block
                    block.status = "running"
                    await task

                except Exception as e:
                    # Handle unexpected errors
                    block.status = "error"
                    block.error = f"{type(e).__name__}: {e}"

                # Render the completed block using print() which goes through patch_stdout
                self._print_block(block)

                self._command_queue.task_done()

            except asyncio.CancelledError:
                break

    def _print_block(self, block: Block) -> None:
        """Print a block ensuring output goes through patch_stdout.

        Uses Rich's capture to render to string, then print() to output.
        This ensures coordination with prompt_toolkit when printing from
        background tasks.
        """
        import sys

        # Render block to string using Rich
        with self.console.capture() as capture:
            self.console.print(block.render(self.console, show_separator=True))
        output = capture.get()

        # Use print() which goes through patch_stdout's proxy
        # This properly coordinates with prompt_toolkit's input line
        print(output, end="", file=sys.stdout, flush=True)

    async def _execute_node_command(self, block: Block, text: str, start_time: float) -> None:
        """Execute a node command and update the block with results.

        Args:
            block: The block to update with results.
            text: The input text (already expanded by caller).
            start_time: When execution started (for duration calculation).
        """
        if self._adapter is None:
            block.status = "error"
            block.error = "Not connected to server"
            block.duration_ms = (time.monotonic() - start_time) * 1000
            return

        node_id = block.node_id
        if not node_id:
            block.status = "error"
            block.error = "No node ID"
            block.duration_ms = (time.monotonic() - start_time) * 1000
            return

        # Track active node for interrupt support
        self._active_node_id = node_id

        try:
            result = await self._adapter.execute_on_node(node_id, text)
        finally:
            self._active_node_id = None

        duration_ms = (time.monotonic() - start_time) * 1000

        # Update block with results
        if result.get("success"):
            block.status = "completed"
            block.output_text = str(result.get("output", "")).strip()
            block.raw = result
            block.error = None
        else:
            block.status = "error"
            error_msg = result.get("error", "Unknown error")
            error_type = result.get("error_type", "unknown")
            block.error = f"[{error_type}] {error_msg}"
            block.raw = result

        block.duration_ms = duration_ms

    async def _execute_python_command(
        self, block: Block, raw_input: str, start_time: float
    ) -> None:
        """Execute a Python command and update the block with results.

        Args:
            block: The block to update with results.
            raw_input: The Python code to execute.
            start_time: When execution started (for duration calculation).
        """
        if self._adapter is None:
            block.status = "error"
            block.error = "Not connected to server"
            block.duration_ms = (time.monotonic() - start_time) * 1000
            return

        try:
            output, error = await self._adapter.execute_python(raw_input, {})
        except Exception as e:
            block.status = "error"
            block.error = f"{type(e).__name__}: {e}"
            block.duration_ms = (time.monotonic() - start_time) * 1000
            return

        duration_ms = (time.monotonic() - start_time) * 1000

        if error:
            block.status = "error"
            block.error = error
        else:
            block.status = "completed"
            block.output_text = output.strip() if output else ""

        block.duration_ms = duration_ms

    async def _cleanup(self) -> None:
        """Cleanup resources."""
        # Cancel background executor
        if self._executor_task is not None:
            self._executor_task.cancel()
            try:
                await self._executor_task
            except asyncio.CancelledError:
                pass
            self._executor_task = None

        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception as e:
                # Log but don't raise - we're in cleanup
                import logging

                logging.debug(f"Error during client disconnect in cleanup: {e}")
        self._client = None
        self._adapter = None


async def run_commander(
    server_name: str = "local",
    session_name: str = "default",
    theme: str = "default",
    bottom_gutter: int = 3,
) -> None:
    """Run the commander TUI.

    Args:
        server_name: Server to connect to (default: "local").
        session_name: Session to use (default: "default").
        theme: Theme name (default, nord, dracula, mono).
        bottom_gutter: Lines of space between prompt and screen bottom (default: 3).
    """
    commander = Commander(
        server_name=server_name,
        session_name=session_name,
        theme_name=theme,
        bottom_gutter=bottom_gutter,
    )
    await commander.run()
