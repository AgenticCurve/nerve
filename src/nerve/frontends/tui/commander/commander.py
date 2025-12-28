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

    def __post_init__(self) -> None:
        """Initialize console and prompt session."""
        theme = get_theme(self.theme_name)
        self.console = Console(theme=theme)
        self._prompt_session = PromptSession(history=InMemoryHistory())

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
            self.console.print(f"[error]Only unix socket servers supported[/]")
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
            # Main loop
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
            self.console.print(f"[dim]Use @<node> <message> to interact. :help for commands.[/]")
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
            self.console.clear()

        elif command == "clean":
            self._clean_blocks()

        elif command == "refresh":
            await self._refresh_view()

        elif command == "theme":
            self._switch_theme(args)

        elif command == "world":
            await self._show_world(args)

        else:
            self.console.print(f"[warning]Unknown command: {command}[/]")

    async def _handle_node_message(self, message: str) -> None:
        """Handle @node_name message syntax."""
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

        # Expand variables like :::1['output']
        text = self._expand_variables(text)

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

        # Track active node for interrupt support
        self._active_node_id = node_id

        # Execute via server and time it
        start_time = time.monotonic()
        try:
            response = await self._adapter.execute_on_node(node_id, text)
            duration_ms = (time.monotonic() - start_time) * 1000

            # Create block with response
            block = Block(
                block_type=block_type,
                node_id=node_id,
                input_text=text,
                output_text=response.strip() if response else "",
                error=None,
                raw={"response": response},
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            error_msg = str(e)
            block = Block(
                block_type=block_type,
                node_id=node_id,
                input_text=text,
                output_text="",
                error=error_msg,
                raw={"error": error_msg},
                duration_ms=duration_ms,
            )
        finally:
            self._active_node_id = None

        self.timeline.add(block)
        self.timeline.render_last(self.console)

    async def _handle_python(self, code: str) -> None:
        """Handle Python code execution via server."""
        if not code:
            self.console.print("[dim]Enter Python code after >>>[/]")
            return

        if self._adapter is None:
            self.console.print("[error]Not connected to server[/]")
            return

        start_time = time.monotonic()
        try:
            # execute_python returns (output, error) tuple
            # namespace is ignored in remote mode but required by interface
            output, error = await self._adapter.execute_python(code, {})
            duration_ms = (time.monotonic() - start_time) * 1000

            if error:
                block = Block(
                    block_type="python",
                    node_id=None,
                    input_text=code,
                    error=error,
                    duration_ms=duration_ms,
                )
            else:
                block = Block(
                    block_type="python",
                    node_id=None,
                    input_text=code,
                    output_text=output.strip() if output else "",
                    duration_ms=duration_ms,
                )

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            block = Block(
                block_type="python",
                node_id=None,
                input_text=code,
                error=f"{type(e).__name__}: {e}",
                duration_ms=duration_ms,
            )

        self.timeline.add(block)
        self.timeline.render_last(self.console)

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
            :::1['output']           - output from block 1 (stdout or stderr)
            :::1['input']            - input from block 1
            :::1['error']            - error from block 1
            :::1['raw']['stdout']    - raw stdout from block 1
            :::1['raw']['stderr']    - raw stderr from block 1
            :::last['output']        - output from last block
            :::last['raw']['stdout'] - raw stdout from last block

        Args:
            text: Text with variable references.

        Returns:
            Text with variables expanded to their values.
        """
        import re

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
                return f"<error: raw is not a dict>"
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
                return f"<error: raw is not a dict>"
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

        return text

    def _print_help(self) -> None:
        """Print help message."""
        self.console.print()
        self.console.print("[bold]Commands:[/]")
        self.console.print("  [bold]@node message[/]  Send message to a node")
        self.console.print("  [bold]>>> code[/]       Execute Python code")
        self.console.print("  [bold]Ctrl+C[/]         Interrupt running command")
        self.console.print()
        self.console.print("[bold]Block References:[/]")
        self.console.print("  [bold]:::N['output'][/]         Output (stdout or stderr)")
        self.console.print("  [bold]:::N['input'][/]          Input text")
        self.console.print("  [bold]:::N['raw']['stdout'][/]  Raw stdout")
        self.console.print("  [bold]:::N['raw']['stderr'][/]  Raw stderr")
        self.console.print("  [bold]:::last['output'][/]      Output from last block")
        self.console.print()
        self.console.print("[bold]Colon Commands:[/]")
        self.console.print("  [bold]:world bash[/]    Enter bash world (no @ prefix needed)")
        self.console.print("  [bold]:world python[/]  Enter python world (no >>> needed)")
        self.console.print("  [bold]:back[/]          Exit current world")
        self.console.print("  [bold]:timeline[/]      Show timeline (filtered in world)")
        self.console.print("  [bold]:refresh[/]       Clear screen and re-render view")
        self.console.print("  [bold]:clean[/]         Clear all blocks, start from :::1")
        self.console.print("  [bold]:nodes[/]         List available nodes")
        self.console.print("  [bold]:theme name[/]    Switch theme")
        self.console.print("  [bold]:exit[/]          Exit world or commander")
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
        self.console = Console(theme=theme)
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
        self.console.print(f"[dim]Cleared {count} blocks. Starting fresh from :::1[/]")
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

    async def _cleanup(self) -> None:
        """Cleanup resources."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass  # Ignore close errors
        self._client = None
        self._adapter = None


async def run_commander(
    server_name: str = "local",
    session_name: str = "default",
    theme: str = "default",
) -> None:
    """Run the commander TUI.

    Args:
        server_name: Server to connect to (default: "local").
        session_name: Session to use (default: "default").
        theme: Theme name (default, nord, dracula, mono).
    """
    commander = Commander(
        server_name=server_name,
        session_name=session_name,
        theme_name=theme,
    )
    await commander.run()
