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
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.filters import Condition
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console

from nerve.frontends.tui.commander.blocks import Timeline
from nerve.frontends.tui.commander.entity_manager import EntityInfo, EntityManager
from nerve.frontends.tui.commander.executor import CommandExecutor
from nerve.frontends.tui.commander.input_dispatcher import InputDispatcher
from nerve.frontends.tui.commander.rendering import print_welcome
from nerve.frontends.tui.commander.suggestion_manager import SuggestionManager
from nerve.frontends.tui.commander.themes import get_ghost_text_color, get_theme
from nerve.frontends.tui.commander.workflow_tracker import WorkflowTracker

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
    config_path: str | None = None  # Workspace config file to load at startup
    async_threshold_ms: float = 200  # Show pending if execution exceeds this

    # State (initialized in __post_init__ or run)
    console: Console = field(init=False)
    timeline: Timeline = field(default_factory=Timeline)

    # Entity management (delegate)
    _entities: EntityManager = field(init=False)

    # Server connection (initialized in run)
    _client: UnixSocketClient | None = field(default=None, init=False)
    _adapter: RemoteSessionAdapter | None = field(default=None, init=False)

    # Internal
    _prompt_session: PromptSession[str] = field(init=False)
    _running: bool = field(default=False, init=False)
    _active_node_id: str | None = field(default=None, init=False)  # Node currently executing
    _current_world: str | None = field(default=None, init=False)  # Focused node world
    _open_monitor_requested: bool = field(default=False, init=False)  # Ctrl-Y pressed
    _open_suggestions_requested: bool = field(default=False, init=False)  # Ctrl-P pressed

    # Suggestion system (delegate)
    _suggestions: SuggestionManager = field(init=False)

    # Execution engine
    _executor: CommandExecutor = field(init=False)

    # Workflow tracking (delegate)
    _workflows: WorkflowTracker = field(init=False)

    # Input dispatching (delegate)
    _dispatcher: InputDispatcher = field(init=False)

    def __post_init__(self) -> None:
        """Initialize console, prompt session, entity manager, suggestion manager, and executor."""
        theme = get_theme(self.theme_name)
        # force_terminal=True ensures ANSI codes work with patch_stdout()
        self.console = Console(theme=theme, force_terminal=True)

        # Initialize entity manager (adapter and console set later in run())
        self._entities = EntityManager()

        # Initialize workflow tracker (adapter set later in run())
        self._workflows = WorkflowTracker(timeline=self.timeline)

        # Initialize suggestion manager (needs adapter set later in run())
        self._suggestions = SuggestionManager(
            entities=self._entities.entities,
            timeline=self.timeline,
            adapter=None,  # Set in run() after connection
            session_name=self.session_name,
            server_name=self.server_name,
        )

        # Initialize input dispatcher
        self._dispatcher = InputDispatcher(commander=self)

        # Get ghost text color from theme
        ghost_color = get_ghost_text_color(self.theme_name)

        # Create dynamic status bar (uses terminal's default colors)
        prompt_style = Style.from_dict(
            {
                "bottom-toolbar": "bg: noinherit",  # Explicitly use terminal default background
                "placeholder": f"fg:{ghost_color} italic",  # Ghost text when empty
                "auto-suggestion": f"fg:{ghost_color} italic",  # Ghost text while typing
            }
        )
        # Create key bindings for prompt session
        kb = KeyBindings()

        @kb.add("c-y")
        def open_monitor(event: KeyPressEvent) -> None:
            """Open full-screen monitor TUI with Ctrl-Y."""
            self._open_monitor_requested = True
            event.app.exit()

        @kb.add("c-p")
        def open_suggestions(event: KeyPressEvent) -> None:
            """Open full-screen suggestion picker with Ctrl-P."""
            self._open_suggestions_requested = True
            event.app.exit()

        def _is_suggestion_active() -> bool:
            """Check if a suggestion is selected and text is a prefix of it."""
            if self._prompt_session.app is None:
                return False
            text = self._prompt_session.app.current_buffer.text
            return self._suggestions.is_active(text)

        def _is_buffer_empty() -> bool:
            """Check if buffer is empty (for cycling suggestions)."""
            if self._prompt_session.app is None:
                return False
            return self._suggestions.is_buffer_empty(self._prompt_session.app.current_buffer.text)

        # Tab cycles to next suggestion (only when buffer is empty)
        @kb.add("tab", filter=Condition(_is_buffer_empty))
        def next_suggestion(_event: KeyPressEvent) -> None:
            """Cycle to next suggestion with Tab, or show first if available."""
            self._suggestions.cycle_next()

        # Shift+Tab cycles to previous suggestion (only when buffer is empty)
        @kb.add("s-tab", filter=Condition(_is_buffer_empty))
        def prev_suggestion(_event: KeyPressEvent) -> None:
            """Cycle to previous suggestion with Shift+Tab."""
            self._suggestions.cycle_prev()

        # Right arrow accepts suggestion word by word
        @kb.add("right", filter=Condition(_is_suggestion_active))
        def accept_suggestion_word(event: KeyPressEvent) -> None:
            """Accept next word from placeholder suggestion with Right Arrow."""
            text = event.app.current_buffer.text
            next_word = self._suggestions.get_next_word(text)
            if next_word:
                event.app.current_buffer.insert_text(next_word)

        # Cmd+Right (or End) accepts entire remaining suggestion
        @kb.add("end", filter=Condition(_is_suggestion_active))
        @kb.add("c-e", filter=Condition(_is_suggestion_active))  # Ctrl+E (end of line)
        def accept_suggestion_all(event: KeyPressEvent) -> None:
            """Accept entire remaining suggestion."""
            text = event.app.current_buffer.text
            remaining = self._suggestions.get_remaining(text)
            if remaining:
                event.app.current_buffer.insert_text(remaining)

        self._prompt_session = PromptSession(
            history=InMemoryHistory(),
            bottom_toolbar=self._get_status_bar,
            style=prompt_style,
            key_bindings=kb,
            placeholder=self._suggestions.get_placeholder,
            auto_suggest=self._suggestions.get_auto_suggest(),
        )
        # Wire up prompt session to suggestion manager for invalidation
        self._suggestions.set_prompt_session(self._prompt_session)

        # Initialize executor for threshold-based async execution
        self._executor = CommandExecutor(
            timeline=self.timeline,
            console=self.console,
            async_threshold_ms=self.async_threshold_ms,
            on_block_complete=self._suggestions.on_block_complete,
        )

    @property
    def entities(self) -> dict[str, EntityInfo]:
        """Access to entities dict (delegates to EntityManager).

        Returns:
            Dict mapping entity_id -> EntityInfo for all entities.
        """
        return self._entities.entities

    @property
    def nodes(self) -> dict[str, str]:
        """Backward-compatible nodes dict (filters entities to nodes only).

        Returns:
            Dict mapping node_id -> node_type for all entities of type "node".
        """
        return self._entities.nodes

    def _get_status_bar(self) -> str:
        """Generate dynamic status bar content.

        Returns gutter (empty lines) above the status line so it appears at the bottom.
        """
        parts = []

        # Entities info (nodes + graphs + workflows)
        entity_count = len(self.entities)
        if entity_count > 0:
            # Count nodes, graphs, and workflows separately
            node_count = sum(1 for e in self.entities.values() if e.type == "node")
            graph_count = sum(1 for e in self.entities.values() if e.type == "graph")
            workflow_count = sum(1 for e in self.entities.values() if e.type == "workflow")

            # Build status text
            entity_parts = []
            if node_count > 0:
                entity_parts.append(f"{node_count} node{'s' if node_count != 1 else ''}")
            if graph_count > 0:
                entity_parts.append(f"{graph_count} graph{'s' if graph_count != 1 else ''}")
            if workflow_count > 0:
                entity_parts.append(
                    f"{workflow_count} workflow{'s' if workflow_count != 1 else ''}"
                )

            parts.append(f"Entities: {', '.join(entity_parts)}")
        else:
            parts.append("Entities: none")

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

        # Active (backgrounded) workflows
        active_wf_count = self._workflows.get_active_count()
        if active_wf_count > 0:
            # Check if any have waiting gates
            waiting_gates = self._workflows.get_waiting_gates_count()
            if waiting_gates > 0:
                parts.append(f"🔄 {active_wf_count} wf ({waiting_gates} gate)")
            else:
                parts.append(f"🔄 {active_wf_count} wf")

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

        # Wire up entity manager with adapter and console
        self._entities.adapter = self._adapter
        self._entities.console = self.console

        # Wire up suggestion manager with adapter and sync callback
        self._suggestions.adapter = self._adapter
        self._suggestions.set_sync_callback(self._entities.sync)

        # Wire up workflow tracker with adapter
        self._workflows.adapter = self._adapter

        # Fetch nodes from session
        await self._entities.sync()

        # Print welcome
        print_welcome(self.console, self.server_name, self.session_name, self.nodes)

        # Load workspace config if provided (before initial suggestion fetch to avoid race condition)
        if self.config_path:
            await self._load_workspace_config()

        # Trigger initial suggestion fetch (runs in background)
        # This is done AFTER config loading so any block completions from startup commands
        # don't race with this initial fetch
        self._suggestions.trigger_fetch()

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

                        # Check if monitor was requested via Ctrl-Y
                        if self._open_monitor_requested:
                            self._open_monitor_requested = False
                            from nerve.frontends.tui.commander.monitor import run_monitor

                            await run_monitor(self.timeline)
                            # Clear the ghost text line that was printed when Ctrl-Y was pressed
                            print(f"\033[A\r\033[K{prompt}", flush=True)
                            continue

                        # Check if suggestion picker was requested via Ctrl-P
                        if self._open_suggestions_requested:
                            self._open_suggestions_requested = False
                            from nerve.frontends.tui.commander.suggestion_picker import (
                                run_suggestion_picker,
                            )

                            selected = await run_suggestion_picker(self._suggestions.suggestions)
                            # Clear the ghost text line from when Ctrl-P was pressed
                            print(f"\033[A\r\033[K{prompt}", flush=True)
                            if selected:
                                # Use the selected suggestion as input
                                user_input = selected
                            else:
                                # Cancelled - go back to prompt
                                continue

                        if not user_input or not user_input.strip():
                            # Clear the ghost text that prompt_toolkit printed with empty input
                            # \033[A = move cursor up one line (to the ghost text line)
                            # \r = move to start of line
                            # \033[K = clear from cursor to end of line
                            # Then reprint just the prompt to show empty input was submitted
                            print(f"\033[A\r\033[K{prompt}", flush=True)
                            continue

                        await self._dispatcher.dispatch(user_input.strip())

                    except KeyboardInterrupt:
                        self.console.print()
                        continue
                    except EOFError:
                        break
        finally:
            signal.signal(signal.SIGINT, original_handler)

        await self._cleanup()

    async def _load_workspace_config(self) -> None:
        """Load workspace config file at startup.

        Reads a Python file that sets up nodes, graphs, and workflows.
        Also looks for a `startup_commands` list to execute initial commands.

        The config file should:
        - Create nodes, graphs, workflows (these are executed server-side)
        - Optionally define `startup_commands = ["@node1 hello", ...]`

        Note: Startup commands are dispatched sequentially but execute
        asynchronously via the executor. They may complete out of order
        if some exceed async_threshold_ms, and may still be running after
        this method returns.

        Example workspace.py:
            from nerve.core.workflow import Workflow, WorkflowContext

            # Setup code runs on server (session is available)
            # ... node creation, workflow registration ...

            # Startup commands run in commander after setup
            startup_commands = [
                "@claude1 You are a helpful assistant",
                "@claude2 You are a code reviewer",
            ]
        """
        import ast
        import re
        from pathlib import Path

        if self._adapter is None or self.config_path is None:
            return

        config_file = Path(self.config_path)
        if not config_file.is_file():
            self.console.print(f"[error]Config file not found: {self.config_path}[/]")
            return

        self.console.print(f"[dim]Loading workspace config: {config_file.name}...[/]")

        try:
            code = config_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            self.console.print(f"[error]Failed to read config file: {e}[/]")
            return

        # Extract startup_commands from the config file (client-side parsing)
        # Look for: startup_commands = ["...", "..."]
        startup_commands: list[str] = []
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "startup_commands":
                            if isinstance(node.value, ast.List):
                                for elt in node.value.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        startup_commands.append(elt.value)
        except SyntaxError:
            # If AST parsing fails, fall back to regex
            match = re.search(r"startup_commands\s*=\s*\[(.*?)\]", code, re.DOTALL)
            if match:
                # Extract quoted strings
                startup_commands = re.findall(r'["\']([^"\']+)["\']', match.group(1))

        # Execute the config code on the server (creates nodes, graphs, workflows)
        # Inject __file__ so config can do relative imports
        config_file_path = str(config_file.resolve())
        code_with_file = f"__file__ = {config_file_path!r}\n{code}"
        try:
            output, error = await self._adapter.execute_python(code_with_file, {})
        except Exception as e:
            self.console.print(f"[error]Config execution failed: {e}[/]")
            return

        if error:
            self.console.print(f"[error]Config error: {error}[/]")
            return

        if output and output.strip():
            self.console.print(f"[dim]{output.strip()}[/]")

        # Sync entities to pick up newly created nodes/graphs/workflows
        await self._entities.sync()

        # Count entities
        node_count = sum(1 for e in self.entities.values() if e.type == "node")
        graph_count = sum(1 for e in self.entities.values() if e.type == "graph")
        workflow_count = sum(1 for e in self.entities.values() if e.type == "workflow")

        self.console.print(
            f"[green]✓[/] Workspace loaded: "
            f"[bold]{node_count}[/] nodes, "
            f"[bold]{graph_count}[/] graphs, "
            f"[bold]{workflow_count}[/] workflows"
        )

        # Execute startup commands
        if startup_commands:
            self.console.print(f"[dim]Running {len(startup_commands)} startup command(s)...[/]")
            for cmd in startup_commands:
                cmd = cmd.strip()
                if cmd:
                    self.console.print(f"[dim]  → {cmd}[/]")
                    await self._dispatcher.dispatch(cmd)

            self.console.print("[green]✓[/] Startup commands complete")

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

    def _set_active_node(self, node_id: str | None) -> None:
        """Set or clear the active node ID (for interrupt support)."""
        self._active_node_id = node_id

    async def _cleanup(self) -> None:
        """Cleanup resources including active workflows."""
        await self._executor.stop()

        # Cancel suggestion fetch task
        await self._suggestions.cleanup()

        # Cancel workflow polling and active workflows
        await self._workflows.cleanup()

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
    config_path: str | None = None,
) -> None:
    """Run the commander TUI.

    Args:
        server_name: Server to connect to (default: "local").
        session_name: Session to use (default: "default").
        theme: Theme name (default, nord, dracula, mono).
        bottom_gutter: Lines of space between prompt and screen bottom (default: 3).
        config_path: Optional workspace config file (.py) to load at startup.
    """
    commander = Commander(
        server_name=server_name,
        session_name=session_name,
        theme_name=theme,
        bottom_gutter=bottom_gutter,
        config_path=config_path,
    )
    await commander.run()
