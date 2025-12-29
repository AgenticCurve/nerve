"""Commander - Unified command center for nerve nodes.

A block-based timeline interface for interacting with nodes.
Connects to a nerve server and session for execution.

This module is the main orchestrator, delegating to specialized modules:
- variables.py: Variable expansion (:::N syntax)
- rendering.py: Display and rendering functions
- executor.py: Async execution with threshold handling
- commands.py: Command dispatch registry
- loop.py: Multi-node conversation loops
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console

from nerve.frontends.tui.commander.blocks import Block, Timeline
from nerve.frontends.tui.commander.commands import dispatch_command
from nerve.frontends.tui.commander.executor import (
    CommandExecutor,
    execute_node_command,
    execute_python_command,
    get_block_type,
)
from nerve.frontends.tui.commander.rendering import print_welcome
from nerve.frontends.tui.commander.themes import get_theme
from nerve.frontends.tui.commander.variables import expand_variables

if TYPE_CHECKING:
    from nerve.frontends.cli.repl.adapters import RemoteSessionAdapter
    from nerve.transport import UnixSocketClient

logger = logging.getLogger(__name__)


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

    # Execution engine
    _executor: CommandExecutor = field(init=False)

    def __post_init__(self) -> None:
        """Initialize console, prompt session, and executor."""
        theme = get_theme(self.theme_name)
        # force_terminal=True ensures ANSI codes work with patch_stdout()
        self.console = Console(theme=theme, force_terminal=True)
        # Create dynamic status bar (uses terminal's default colors)
        prompt_style = Style.from_dict(
            {
                "bottom-toolbar": "bg: noinherit",  # Explicitly use terminal default background
            }
        )
        self._prompt_session = PromptSession(
            history=InMemoryHistory(),
            bottom_toolbar=self._get_status_bar,
            style=prompt_style,
        )
        # Initialize executor for threshold-based async execution
        self._executor = CommandExecutor(
            timeline=self.timeline,
            console=self.console,
            async_threshold_ms=self.async_threshold_ms,
        )

    def _get_status_bar(self) -> str:
        """Generate dynamic status bar content.

        Returns gutter (empty lines) above the status line so it appears at the bottom.
        """
        parts = []

        # Nodes info
        node_count = len(self.nodes)
        if node_count > 0:
            nodes_text = f"{node_count} node{'s' if node_count != 1 else ''}"
            parts.append(f"Nodes: {nodes_text}")
        else:
            parts.append("Nodes: none")

        # World indicator
        if self._current_world:
            parts.append(f"World: {self._current_world}")
        else:
            parts.append("World: Timeline")

        # Block counts
        total_blocks = len(self.timeline.blocks)
        pending_count = sum(1 for b in self.timeline.blocks if b.status == "pending")
        waiting_count = sum(1 for b in self.timeline.blocks if b.status == "waiting")

        parts.append(f"Blocks: {total_blocks}")

        if pending_count > 0:
            parts.append(f"⏳ {pending_count}")
        if waiting_count > 0:
            parts.append(f"⏸️  {waiting_count}")

        # Clock
        current_time = datetime.now().strftime("%H:%M:%S")
        parts.append(current_time)

        # Help hint
        parts.append(":help for commands")

        # Join with separator
        status_line = " │ ".join(parts)

        # Add gutter spacing ABOVE the status line
        if self.bottom_gutter > 0:
            gutter = "\n" * self.bottom_gutter
            return f"{gutter} {status_line}"
        else:
            return f" {status_line}"

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
        print_welcome(self.console, self.server_name, self.session_name, self.nodes)

        # Start background executor
        await self._executor.start()

        # Setup SIGINT handler to interrupt active node
        original_handler = signal.getsignal(signal.SIGINT)

        def sigint_handler(signum: int, frame: Any) -> None:
            """Handle Ctrl-C by interrupting active node."""
            if self._active_node_id is not None and self._client is not None:
                import asyncio

                # Fire-and-forget with exception suppression to avoid silent failures
                task = asyncio.ensure_future(self._send_interrupt(self._active_node_id))
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

        signal.signal(signal.SIGINT, sigint_handler)

        try:
            # Main loop - wrap in patch_stdout for background print coordination
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
                        self.console.print()
                        continue
                    except EOFError:
                        break
        finally:
            signal.signal(signal.SIGINT, original_handler)

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

    def _get_nodes_by_type(self) -> dict[str, str]:
        """Build reverse mapping from node type to node ID.

        Returns:
            Dictionary mapping node_type/name -> node_id.
            E.g., {"claude": "1", "bash": "2"}
        """
        # Build reverse mapping: node_type -> node_id
        # If multiple nodes have the same type, only keep the first one
        result: dict[str, str] = {}
        for node_id, node_type in self.nodes.items():
            if node_type not in result:
                result[node_type] = node_id
        return result

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

    async def _handle_input(self, user_input: str) -> None:
        """Handle user input and dispatch to appropriate handler."""
        # Commands always start with : (works in any world)
        if user_input.startswith(":"):
            await dispatch_command(self, user_input[1:])
            return

        # If in a world, route directly to that node
        if self._current_world:
            if self._current_world == "python":
                await self._handle_python(user_input)
            else:
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

    async def _handle_node_message(self, message: str) -> None:
        """Handle @node_name message syntax with threshold-based async."""
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
            await self._sync_nodes()
            if node_id not in self.nodes:
                self.console.print(f"[error]Node not found: {node_id}[/]")
                self.console.print(
                    f"[dim]Available nodes: {', '.join(self.nodes.keys()) or 'none'}[/]"
                )
                return

        node_type = self.nodes[node_id]
        block_type = get_block_type(node_type)

        # DON'T expand variables yet - detect dependencies first
        from nerve.frontends.tui.commander.variables import extract_block_dependencies

        dependencies = extract_block_dependencies(text, self.timeline, self._get_nodes_by_type())

        # Create block with dependency info (input_text stores RAW text)
        block = Block(
            block_type=block_type,
            node_id=node_id,
            input_text=text,
            depends_on=dependencies,
        )
        self.timeline.add(block)

        # Execute with threshold handling
        start_time = time.monotonic()

        # IMPORTANT: Variable expansion happens INSIDE execute function
        # This ensures dependencies are completed before expansion
        async def execute() -> None:
            # By this point, execute_with_threshold has waited for dependencies
            expanded_text = expand_variables(self.timeline, text, self._get_nodes_by_type())

            await execute_node_command(
                self._adapter,  # type: ignore[arg-type]
                block,
                expanded_text,  # Now has correct values from completed dependencies
                start_time,
                self._set_active_node,
            )

        await self._executor.execute_with_threshold(block, execute)

    async def _handle_python(self, code: str) -> None:
        """Handle Python code execution with threshold-based async."""
        if not code:
            self.console.print("[dim]Enter Python code after >>>[/]")
            return

        if self._adapter is None:
            self.console.print("[error]Not connected to server[/]")
            return

        # Detect dependencies (Python code can reference blocks and nodes)
        from nerve.frontends.tui.commander.variables import extract_block_dependencies

        dependencies = extract_block_dependencies(code, self.timeline, self._get_nodes_by_type())

        # Create block with dependency info
        block = Block(
            block_type="python",
            node_id=None,
            input_text=code,
            depends_on=dependencies,
        )
        self.timeline.add(block)

        # Execute with threshold handling
        start_time = time.monotonic()

        async def execute() -> None:
            await execute_python_command(
                self._adapter,  # type: ignore[arg-type]
                block,
                code,
                start_time,
            )

        await self._executor.execute_with_threshold(block, execute)

    def _set_active_node(self, node_id: str | None) -> None:
        """Set or clear the active node ID (for interrupt support)."""
        self._active_node_id = node_id

    async def _cleanup(self) -> None:
        """Cleanup resources."""
        await self._executor.stop()

        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.debug(f"Error during client disconnect in cleanup: {e}")
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
