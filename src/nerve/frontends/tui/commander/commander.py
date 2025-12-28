"""Commander - Unified command center for nerve nodes.

A block-based timeline interface for interacting with nodes.
Supports sending commands to nodes and executing Python code.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console

from nerve.core.nodes import BashNode, ExecutionContext
from nerve.core.session import Session
from nerve.frontends.tui.commander.blocks import Block, Timeline
from nerve.frontends.tui.commander.themes import DEFAULT_THEME, get_theme


@dataclass
class Commander:
    """Unified command center for interacting with nodes.

    Provides a block-based timeline interface where each interaction
    is displayed as a discrete block with input/output.

    Example:
        >>> commander = Commander(theme="nord")
        >>> await commander.run()
    """

    # Configuration
    theme_name: str = "default"
    session_name: str = "commander"

    # State (initialized in __post_init__ or run)
    console: Console = field(init=False)
    session: Session = field(init=False)
    timeline: Timeline = field(default_factory=Timeline)
    nodes: dict[str, Any] = field(default_factory=dict)

    # Internal
    _prompt_session: PromptSession[str] = field(init=False)
    _running: bool = field(default=False, init=False)
    _active_node: Any = field(default=None, init=False)  # Node currently executing
    _active_task: asyncio.Task[Any] | None = field(default=None, init=False)
    _current_world: str | None = field(default=None, init=False)  # Focused node world

    def __post_init__(self) -> None:
        """Initialize console and prompt session."""
        theme = get_theme(self.theme_name)
        self.console = Console(theme=theme)
        self._prompt_session = PromptSession(history=InMemoryHistory())

    async def run(self) -> None:
        """Run the commander REPL loop."""
        import signal

        self._running = True

        # Create session
        self.session = Session(name=self.session_name, server_name="commander")

        # Create default bash node
        self._create_default_nodes()

        # Print welcome
        self._print_welcome()

        # Setup SIGINT handler to interrupt active node
        original_handler = signal.getsignal(signal.SIGINT)

        def sigint_handler(signum: int, frame: Any) -> None:
            """Handle Ctrl-C by interrupting active node."""
            if self._active_node is not None and hasattr(self._active_node, "interrupt"):
                # Schedule interrupt on the event loop
                asyncio.ensure_future(self._active_node.interrupt())
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

    def _create_default_nodes(self) -> None:
        """Create default nodes for the session."""
        # Create a bash node
        bash = BashNode(id="bash", session=self.session, timeout=30.0)
        self.nodes["bash"] = bash

    def _print_welcome(self) -> None:
        """Print welcome message."""
        self.console.print()
        self.console.print("[bold]Commander[/] - Nerve Command Center", style="prompt")
        self.console.print("Type [bold]@bash <command>[/] to run bash commands", style="dim")
        self.console.print(
            "Type [bold]:help[/] for more commands, [bold]:exit[/] to quit", style="dim"
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
            self._print_nodes()

        elif command == "timeline":
            self._print_timeline(args)

        elif command == "clear":
            self.console.clear()

        elif command == "clean":
            self._clean_blocks()

        elif command == "refresh":
            self._refresh_view()

        elif command == "theme":
            self._switch_theme(args)

        elif command == "world":
            await self._show_world(args)

        else:
            self.console.print(f"[warning]Unknown command: {command}[/]")

    async def _handle_node_message(self, message: str) -> None:
        """Handle @node_name message syntax."""
        parts = message.split(maxsplit=1)
        if not parts:
            self.console.print("[warning]Usage: @node_name message[/]")
            return

        node_id = parts[0]
        text = parts[1] if len(parts) > 1 else ""

        if not text:
            self.console.print(f"[warning]No message provided for @{node_id}[/]")
            return

        # Expand variables like $blocks[1]['output']
        text = self._expand_variables(text)

        if node_id not in self.nodes:
            self.console.print(f"[error]Node not found: {node_id}[/]")
            self.console.print(f"[dim]Available nodes: {', '.join(self.nodes.keys())}[/]")
            return

        node = self.nodes[node_id]
        block_type = self._get_block_type(node)

        # Track active node for interrupt support
        self._active_node = node

        # Execute and time it
        start_time = time.monotonic()
        interrupted = False
        try:
            ctx = ExecutionContext(session=self.session, input=text)
            result = await node.execute(ctx)
            duration_ms = (time.monotonic() - start_time) * 1000

            # Check if result indicates interruption
            if isinstance(result, dict) and result.get("interrupted"):
                interrupted = True

            # Extract output based on result type
            raw_result = result if isinstance(result, dict) else {"result": result}
            if isinstance(result, dict):
                if result.get("success"):
                    output = result.get("stdout", "") or result.get("content", "")
                    error = None
                else:
                    output = result.get("stdout", "")
                    error = result.get("stderr") or result.get("error", "Command failed")
            else:
                output = str(result)
                error = None

            # Create and render block
            block = Block(
                block_type=block_type,
                node_id=node_id,
                input_text=text,
                output_text=output.strip() if isinstance(output, str) else str(output),
                error=error,
                raw=raw_result,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            block = Block(
                block_type=block_type,
                node_id=node_id,
                input_text=text,
                error=f"{type(e).__name__}: {e}",
                raw={"exception": str(e), "exception_type": type(e).__name__},
                duration_ms=duration_ms,
            )
        finally:
            self._active_node = None

        self.timeline.add(block)
        self.timeline.render_last(self.console)

        if interrupted:
            self.console.print("[dim]Command interrupted (Ctrl+C)[/]")

    async def _handle_python(self, code: str) -> None:
        """Handle Python code execution."""
        if not code:
            self.console.print("[dim]Enter Python code after >>>[/]")
            return

        # Build namespace with useful references
        namespace: dict[str, Any] = {
            "session": self.session,
            "nodes": self.nodes,
            "timeline": self.timeline,
            "blocks": self.timeline,  # Alias for easy access: blocks[1]['output']
        }

        start_time = time.monotonic()
        try:
            # Try eval first (for expressions)
            try:
                result = eval(code, namespace)
                output = repr(result) if result is not None else ""
            except SyntaxError:
                # Fall back to exec (for statements)
                exec(code, namespace)
                output = ""

            duration_ms = (time.monotonic() - start_time) * 1000

            block = Block(
                block_type="python",
                node_id=None,
                input_text=code,
                output_text=output,
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

    def _get_block_type(self, node: Any) -> str:
        """Determine block type from node class."""
        class_name = type(node).__name__
        if "Bash" in class_name:
            return "bash"
        elif "LLM" in class_name or "Chat" in class_name:
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

    def _print_nodes(self) -> None:
        """Print available nodes."""
        self.console.print()
        self.console.print("[bold]Available Nodes:[/]")
        for node_id, node in self.nodes.items():
            node_type = type(node).__name__
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
            self.console.print(f"[bold]World: python[/]")
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
            node = self.nodes[world_id]
            node_type = type(node).__name__
            self.console.print(f"[bold]World: @{world_id}[/] ({node_type})")
            self.console.print("[dim]Type commands directly. :exit or :back to leave.[/]")

            # Show node-specific state
            if hasattr(node, "messages"):
                messages = node.messages
                self.console.print(f"[dim]Conversation: {len(messages)} messages[/]")

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

    def _refresh_view(self) -> None:
        """Clear screen and re-render current view."""
        self.console.clear()

        # Re-render based on current context
        if self._current_world:
            # In a world - show world header and filtered blocks
            if self._current_world == "python":
                self.console.print(f"[bold]World: python[/]")
                blocks = self.timeline.filter_by_type("python")
            else:
                node = self.nodes.get(self._current_world)
                node_type = type(node).__name__ if node else "?"
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
        await self.session.stop()


async def run_commander(theme: str = "default") -> None:
    """Run the commander TUI.

    Args:
        theme: Theme name (default, nord, dracula, mono)
    """
    commander = Commander(theme_name=theme)
    await commander.run()
