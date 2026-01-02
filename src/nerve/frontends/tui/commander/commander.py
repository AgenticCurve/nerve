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

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console

from nerve.frontends.tui.commander.blocks import Block, BlockType, Timeline
from nerve.frontends.tui.commander.commands import dispatch_command
from nerve.frontends.tui.commander.executor import (
    CommandExecutor,
    execute_graph_command,
    execute_node_command,
    execute_python_command,
    get_block_type,
)
from nerve.frontends.tui.commander.rendering import print_welcome
from nerve.frontends.tui.commander.themes import get_ghost_text_color, get_theme
from nerve.frontends.tui.commander.variables import expand_variables
from nerve.frontends.tui.commander.workflow_runner import run_workflow_tui

if TYPE_CHECKING:
    from nerve.frontends.cli.repl.adapters import RemoteSessionAdapter
    from nerve.transport import UnixSocketClient

logger = logging.getLogger(__name__)


class PrefixAutoSuggest(AutoSuggest):
    """Auto-suggest that shows remaining text when buffer is a prefix of suggestion."""

    def __init__(self, get_suggestion: Callable[[], str]) -> None:
        """Initialize with a callable that returns the current suggestion."""
        self._get_suggestion = get_suggestion

    def get_suggestion(self, buffer: Buffer, document: Document) -> Suggestion | None:
        """Return remaining suggestion if current text is a prefix."""
        text = document.text
        suggestion = self._get_suggestion()
        if text and suggestion.startswith(text) and text != suggestion:
            return Suggestion(suggestion[len(text) :])
        return None


@dataclass
class EntityInfo:
    """Information about an executable entity (node or graph).

    Provides unified tracking of both nodes and graphs in commander.
    """

    id: str
    type: str  # "node" or "graph"
    node_type: str  # "BashNode", "LLMChatNode", "graph", etc.
    metadata: dict[str, Any] = field(default_factory=dict)


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
    entities: dict[str, EntityInfo] = field(default_factory=dict)  # Unified nodes + graphs

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

    # Suggestion system
    _suggestion_node: str = field(
        default="suggestions", init=False
    )  # Node to fetch suggestions from
    _suggestions: list[str] = field(
        default_factory=list, init=False
    )  # Current suggestions (empty until fetched)
    _suggestion_idx: int = field(
        default=-1, init=False
    )  # -1 means show hint, 0+ means show suggestion
    _suggestion_task: asyncio.Task[None] | None = field(
        default=None, init=False
    )  # Background fetch task

    # Execution engine
    _executor: CommandExecutor = field(init=False)

    # Active (backgrounded) workflow runs: run_id -> workflow info
    _active_workflows: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)

    # Background task for polling workflow status
    _workflow_poll_task: asyncio.Task[None] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Initialize console, prompt session, and executor."""
        theme = get_theme(self.theme_name)
        # force_terminal=True ensures ANSI codes work with patch_stdout()
        self.console = Console(theme=theme, force_terminal=True)

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

        def _current_suggestion() -> str:
            """Get the current suggestion based on index, or empty if showing hint."""
            if self._suggestion_idx < 0 or not self._suggestions:
                return ""
            return self._suggestions[self._suggestion_idx]

        def _get_placeholder() -> HTML:
            """Get placeholder HTML - hint when no selection, suggestion otherwise."""
            if self._suggestion_idx < 0 or not self._suggestions:
                return HTML("<placeholder>Tab to cycle suggestions</placeholder>")
            return HTML(f"<placeholder>{_current_suggestion()}</placeholder>")

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
            if self._suggestion_idx < 0 or not self._suggestions:
                return False
            text = self._prompt_session.app.current_buffer.text
            suggestion = _current_suggestion()
            return suggestion.startswith(text) and text != suggestion

        def _is_buffer_empty() -> bool:
            """Check if buffer is empty (for cycling suggestions)."""
            if self._prompt_session.app is None:
                return False
            return not self._prompt_session.app.current_buffer.text

        # Tab cycles to next suggestion (only when buffer is empty)
        @kb.add("tab", filter=Condition(_is_buffer_empty))
        def next_suggestion(event: KeyPressEvent) -> None:
            """Cycle to next suggestion with Tab, or show first if available."""
            if not self._suggestions:
                return  # No suggestions available yet
            # If showing hint (-1), go to first suggestion (0)
            # Otherwise cycle to next
            if self._suggestion_idx < 0:
                self._suggestion_idx = 0
            else:
                self._suggestion_idx = (self._suggestion_idx + 1) % len(self._suggestions)

        # Shift+Tab cycles to previous suggestion (only when buffer is empty)
        @kb.add("s-tab", filter=Condition(_is_buffer_empty))
        def prev_suggestion(event: KeyPressEvent) -> None:
            """Cycle to previous suggestion with Shift+Tab."""
            if not self._suggestions:
                return  # No suggestions available yet
            # If showing hint (-1), go to last suggestion
            # Otherwise cycle to previous
            if self._suggestion_idx < 0:
                self._suggestion_idx = len(self._suggestions) - 1
            else:
                self._suggestion_idx = (self._suggestion_idx - 1) % len(self._suggestions)

        def _get_next_word() -> str:
            """Get the next word from suggestion to insert."""
            text = self._prompt_session.app.current_buffer.text
            suggestion = _current_suggestion()
            remaining = suggestion[len(text) :]
            # Find next word boundary (space or end)
            space_idx = remaining.find(" ")
            if space_idx == -1:
                return remaining  # Rest of suggestion
            return remaining[: space_idx + 1]  # Include the space

        # Right arrow accepts suggestion word by word
        @kb.add("right", filter=Condition(_is_suggestion_active))
        def accept_suggestion_word(event: KeyPressEvent) -> None:
            """Accept next word from placeholder suggestion with Right Arrow."""
            next_word = _get_next_word()
            if next_word:
                event.app.current_buffer.insert_text(next_word)

        def _get_remaining() -> str:
            """Get all remaining text from suggestion."""
            text = self._prompt_session.app.current_buffer.text
            return _current_suggestion()[len(text) :]

        # Cmd+Right (or End) accepts entire remaining suggestion
        @kb.add("end", filter=Condition(_is_suggestion_active))
        @kb.add("c-e", filter=Condition(_is_suggestion_active))  # Ctrl+E (end of line)
        def accept_suggestion_all(event: KeyPressEvent) -> None:
            """Accept entire remaining suggestion."""
            remaining = _get_remaining()
            if remaining:
                event.app.current_buffer.insert_text(remaining)

        self._prompt_session = PromptSession(
            history=InMemoryHistory(),
            bottom_toolbar=self._get_status_bar,
            style=prompt_style,
            key_bindings=kb,
            placeholder=_get_placeholder,  # Callable for dynamic placeholder
            auto_suggest=PrefixAutoSuggest(_current_suggestion),
        )
        # Initialize executor for threshold-based async execution
        self._executor = CommandExecutor(
            timeline=self.timeline,
            console=self.console,
            async_threshold_ms=self.async_threshold_ms,
            on_block_complete=self._on_block_complete,
        )

    @property
    def nodes(self) -> dict[str, str]:
        """Backward-compatible nodes dict (filters entities to nodes only).

        Returns:
            Dict mapping node_id -> node_type for all entities of type "node".
        """
        return {
            entity_id: entity.node_type
            for entity_id, entity in self.entities.items()
            if entity.type == "node"
        }

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
        active_wf_count = len(self._active_workflows)
        if active_wf_count > 0:
            # Check if any have waiting gates
            waiting_gates = sum(
                1 for wf in self._active_workflows.values() if wf.get("pending_gate") is not None
            )
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

        # Fetch nodes from session
        await self._sync_entities()

        # Print welcome
        print_welcome(self.console, self.server_name, self.session_name, self.nodes)

        # Load workspace config if provided (before initial suggestion fetch to avoid race condition)
        if self.config_path:
            await self._load_workspace_config()

        # Trigger initial suggestion fetch (runs in background)
        # This is done AFTER config loading so any block completions from startup commands
        # don't race with this initial fetch
        self._trigger_suggestion_fetch()

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

                            selected = await run_suggestion_picker(self._suggestions)
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

                        await self._handle_input(user_input.strip())

                    except KeyboardInterrupt:
                        self.console.print()
                        continue
                    except EOFError:
                        break
        finally:
            signal.signal(signal.SIGINT, original_handler)

        await self._cleanup()

    async def _sync_entities(self) -> None:
        """Fetch nodes, graphs, and workflows from server session."""
        if self._adapter is None:
            return

        try:
            # Fetch nodes with full metadata (includes command, backend, etc.)
            await self._adapter.list_nodes()  # Populates cache
            nodes_info = await self._adapter.get_nodes_info()
            self.entities.clear()
            for info in nodes_info:
                node_id = info.get("id", "")
                node_type = info.get("type", "unknown")
                # Extract all metadata fields except id, type, state
                metadata = {k: v for k, v in info.items() if k not in ("id", "type", "state")}
                self.entities[node_id] = EntityInfo(
                    id=node_id,
                    type="node",
                    node_type=node_type,
                    metadata=metadata,
                )

            # Fetch graphs
            graph_ids = await self._adapter.list_graphs()
            for graph_id in graph_ids:
                self.entities[graph_id] = EntityInfo(
                    id=graph_id,
                    type="graph",
                    node_type="graph",
                )

            # Fetch workflows
            workflows = await self._adapter.list_workflows()
            for wf in workflows:
                wf_id = wf.get("id", "")
                if wf_id:
                    self.entities[wf_id] = EntityInfo(
                        id=wf_id,
                        type="workflow",
                        node_type="workflow",
                        metadata={"description": wf.get("description", "")},
                    )
        except (ConnectionError, TimeoutError, RuntimeError, OSError) as e:
            # Handle known network/transport errors gracefully
            self.console.print(f"[warning]Failed to fetch entities: {e}[/]")
            logger.warning("Entity sync failed: %s", e, exc_info=True)

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
        await self._sync_entities()

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
                    await self._handle_input(cmd)

            self.console.print("[green]✓[/] Startup commands complete")

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

    def _validate_and_create_error_block(
        self, text: str, block_type: BlockType, node_id: str | None
    ) -> Block | None:
        """Validate variable references and return error block if invalid.

        Checks for unresolvable references (:::nav when nav has no blocks, etc.)
        and creates an error block if validation fails.

        Args:
            text: Text with potential variable references.
            block_type: Type for the error block if created.
            node_id: Node ID for the error block if created.

        Returns:
            None if validation passes, otherwise the error block
            (already added to timeline and rendered).
        """
        from nerve.frontends.tui.commander.rendering import print_block
        from nerve.frontends.tui.commander.variables import validate_variable_references

        errors = validate_variable_references(text, self.timeline, self._get_nodes_by_type())
        if not errors:
            return None

        block = Block(
            block_type=block_type,
            node_id=node_id,
            input_text=text,
            status="error",
            error=errors[0],
        )
        self.timeline.add(block)
        print_block(self.console, block)
        return block

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
        """Handle user input and dispatch to appropriate handler.

        Note: Suggestion refresh is triggered via on_block_complete callback
        for commands that create blocks (@node, %workflow, >>> python).
        Only : commands need explicit trigger here since they don't create blocks.
        """
        # Commands always start with : (works in any world)
        if user_input.startswith(":"):
            await dispatch_command(self, user_input[1:])
            # : commands don't create blocks, so trigger suggestions manually
            self._trigger_suggestion_fetch()

        # If in a world, route directly to that node
        elif self._current_world:
            if self._current_world == "python":
                await self._handle_python(user_input)
            else:
                await self._handle_entity_message(f"{self._current_world} {user_input}")

        # Node/graph messages start with @
        elif user_input.startswith("@"):
            await self._handle_entity_message(user_input[1:])

        # Workflow execution starts with %
        elif user_input.startswith("%"):
            await self._handle_workflow(user_input[1:])

        # Python code starts with >>>
        elif user_input.startswith(">>>"):
            await self._handle_python(user_input[3:].strip())

        # Default: show help
        else:
            self.console.print(
                "[dim]Prefix with @node to send to a node, "
                "%workflow for workflows, >>> for Python, or :help[/]"
            )

    def _gather_suggestion_context(self) -> dict[str, Any]:
        """Gather context for the suggestion node.

        Collects:
        - nodes: list of node IDs (excluding 'suggestions' node)
        - graphs: list of graph IDs
        - workflows: list of workflow IDs
        - blocks: list of block dicts with input/output/success (excluding suggestion blocks)
        - cwd: current working directory

        Returns:
            Context dict ready to send to SuggestionNode.
        """
        # Gather entities by type (exclude 'suggestions' node - AI shouldn't predict itself)
        nodes = [e.id for e in self.entities.values() if e.type == "node" and e.id != "suggestions"]
        graphs = [e.id for e in self.entities.values() if e.type == "graph"]
        workflows = [e.id for e in self.entities.values() if e.type == "workflow"]

        # Gather blocks from timeline (exclude suggestion blocks)
        blocks = []
        for block in self.timeline.blocks:
            if block.status == "completed" and block.node_id != "suggestions":
                blocks.append(
                    {
                        "input": block.input_text,
                        "output": block.output_text,
                        "success": block.error is None,
                        "error": block.error,
                    }
                )

        return {
            "nodes": nodes,
            "graphs": graphs,
            "workflows": workflows,
            "blocks": blocks,
            "cwd": os.getcwd(),
        }

    async def _fetch_suggestions(self) -> None:
        """Fetch suggestions from the suggestion node in background.

        Updates _suggestions list with new suggestions from the LLM.
        Falls back to default suggestions if node unavailable or errors.
        """
        if self._adapter is None:
            return

        # Check if suggestion node exists
        if self._suggestion_node not in self.entities:
            await self._sync_entities()
            if self._suggestion_node not in self.entities:
                return  # Node not available, keep current suggestions

        try:
            context = self._gather_suggestion_context()
            result = await self._adapter.execute_on_node(self._suggestion_node, json.dumps(context))

            if result.get("success"):
                output = result.get("output", [])
                if isinstance(output, list) and output:
                    self._suggestions = output
                    self._suggestion_idx = 0  # Show first suggestion immediately
                    # Invalidate prompt to trigger redraw with new suggestion
                    if self._prompt_session.app is not None:
                        self._prompt_session.app.invalidate()
        except Exception as e:
            # Keep existing suggestions on error
            logger.debug("Failed to fetch suggestions: %s", e)

    def _on_block_complete(self, block: Block) -> None:
        """Callback when any block completes execution.

        Triggers suggestion refresh unless it's a suggestion block.

        Args:
            block: The completed block.
        """
        # Skip suggestion refresh for suggestion blocks (avoid recursion)
        if block.node_id == "suggestions":
            return
        self._trigger_suggestion_fetch()

    def _trigger_suggestion_fetch(self) -> None:
        """Trigger background fetch of suggestions.

        Cancels any existing fetch and starts a new one.
        Called after commands complete to refresh suggestions.
        """
        # Cancel existing task if running
        if self._suggestion_task is not None and not self._suggestion_task.done():
            self._suggestion_task.cancel()
            # Suppress CancelledError - task is intentionally being replaced
            self._suggestion_task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )

        # Start new fetch task
        self._suggestion_task = asyncio.create_task(self._fetch_suggestions())

    async def _handle_entity_message(self, message: str) -> None:
        """Handle @entity_name message syntax for both nodes and graphs."""
        if self._adapter is None:
            self.console.print("[error]Not connected to server[/]")
            return

        parts = message.split(maxsplit=1)
        if not parts:
            self.console.print("[warning]Usage: @entity_name message[/]")
            return

        entity_id = parts[0]
        text = parts[1] if len(parts) > 1 else ""

        # Special handling for @suggestions - auto-gather context
        if entity_id == "suggestions" and not text:
            context = self._gather_suggestion_context()
            text = json.dumps(context)

        if not text:
            self.console.print(f"[warning]No message provided for @{entity_id}[/]")
            return

        if entity_id not in self.entities:
            await self._sync_entities()
            if entity_id not in self.entities:
                self.console.print(f"[error]Entity not found: {entity_id}[/]")
                self.console.print(
                    f"[dim]Available: {', '.join(self.entities.keys()) or 'none'}[/]"
                )
                return

        entity = self.entities[entity_id]
        block_type = get_block_type(entity.node_type)

        # Validate variable references before proceeding (fail fast on unresolvable refs)
        if self._validate_and_create_error_block(text, block_type, entity_id):
            return

        # DON'T expand variables yet - detect dependencies first
        from nerve.frontends.tui.commander.variables import extract_block_dependencies

        dependencies = extract_block_dependencies(text, self.timeline, self._get_nodes_by_type())

        # Create block with dependency info (input_text stores RAW text)
        block = Block(
            block_type=block_type,
            node_id=entity_id,  # Works for both nodes and graphs
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
            # Pass block.number to exclude current block from negative index resolution
            expanded_text = expand_variables(
                self.timeline, text, self._get_nodes_by_type(), exclude_block_from=block.number
            )

            # Route based on entity type
            if entity.type == "graph":
                await execute_graph_command(
                    self._adapter,  # type: ignore[arg-type]
                    block,
                    entity_id,
                    expanded_text,
                    start_time,
                )
            else:
                await execute_node_command(
                    self._adapter,  # type: ignore[arg-type]
                    block,
                    expanded_text,
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

        # Validate variable references before proceeding (fail fast on unresolvable refs)
        if self._validate_and_create_error_block(code, "python", None):
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

    async def _handle_workflow(self, message: str) -> None:
        """Handle %workflow_id input syntax for workflow execution.

        Workflows run in a dedicated full-screen TUI that:
        - Shows workflow state, events, and progress
        - Handles gates with interactive prompts
        - Returns result to store in the block

        NOTE: The workflow TUI is a separate prompt_toolkit Application that
        takes over the terminal, but does NOT stop the Commander's background
        executor. Any in-progress blocks continue executing while workflow runs.
        """
        if self._adapter is None:
            self.console.print("[error]Not connected to server[/]")
            return

        parts = message.split(maxsplit=1)
        if not parts:
            self.console.print("[warning]Usage: %workflow_id input[/]")
            return

        workflow_id = parts[0]
        input_text = parts[1] if len(parts) > 1 else ""

        # Check if workflow exists
        if workflow_id not in self.entities:
            await self._sync_entities()
            if workflow_id not in self.entities:
                self.console.print(f"[error]Workflow not found: {workflow_id}[/]")
                # List available workflows
                workflows = [e.id for e in self.entities.values() if e.type == "workflow"]
                if workflows:
                    self.console.print(f"[dim]Available workflows: {', '.join(workflows)}[/]")
                else:
                    self.console.print("[dim]No workflows registered[/]")
                return

        entity = self.entities[workflow_id]
        if entity.type != "workflow":
            self.console.print(f"[error]'{workflow_id}' is a {entity.type}, not a workflow[/]")
            self.console.print("[dim]Use @ for nodes/graphs, % for workflows[/]")
            return

        # Validate variable references before proceeding (fail fast on unresolvable refs)
        if self._validate_and_create_error_block(input_text, "workflow", workflow_id):
            return

        # Extract dependencies from input (for :::N references)
        from nerve.frontends.tui.commander.variables import extract_block_dependencies

        dependencies = extract_block_dependencies(
            input_text, self.timeline, self._get_nodes_by_type()
        )

        # Create block for workflow (stores raw input)
        block = Block(
            block_type="workflow",
            node_id=workflow_id,
            input_text=input_text,
            depends_on=dependencies,
        )
        self.timeline.add(block)

        # Wait for dependencies before expanding variables
        # This ensures :::N references see completed block data
        if dependencies:
            block.status = "waiting"
            from nerve.frontends.tui.commander.rendering import print_block

            print_block(self.console, block)
            dependencies_ready = await self._executor.wait_for_dependencies(block)

            # If dependency wait failed (returned False), stop here
            if not dependencies_ready:
                print_block(self.console, block)
                return

        # NOW expand variables - dependencies are complete
        expanded_input = expand_variables(
            self.timeline, input_text, self._get_nodes_by_type(), exclude_block_from=block.number
        )

        # Launch full-screen workflow TUI
        # This takes over the screen until workflow completes
        result = await run_workflow_tui(
            self._adapter,
            workflow_id,
            expanded_input,
        )

        # Update block with result
        block.duration_ms = result.get("duration_ms", 0)

        if result.get("backgrounded"):
            # Workflow was backgrounded - track it for resume
            block.status = "pending"  # Mark as pending since still running
            block.output_text = "(backgrounded - use :wf to resume)"
            block.raw = result
            run_id = result.get("run_id", "")
            if run_id:
                self._active_workflows[run_id] = {
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "block_number": block.number,
                    "events": result.get("events", []),
                    "pending_gate": result.get("pending_gate"),
                    "start_time": result.get("start_time", 0),
                    "steps": result.get("steps", []),
                }
            self.console.print(
                f"[dim]Workflow backgrounded. Use :world to list or :world {run_id[:8]} to resume[/]"
            )
            # Start background polling for status updates
            self._start_workflow_polling()
        else:
            # Handle completed, cancelled, or failed states
            from nerve.frontends.tui.commander.rendering import print_block

            if result.get("state") == "completed":
                block.status = "completed"
                block.output_text = str(result.get("result", ""))
                block.raw = result
            elif result.get("state") == "cancelled":
                block.status = "error"
                block.error = "Workflow cancelled"
                block.raw = result
            else:
                block.status = "error"
                block.error = result.get("error", "Workflow failed")
                block.raw = result

            print_block(self.console, block)

    def _set_active_node(self, node_id: str | None) -> None:
        """Set or clear the active node ID (for interrupt support)."""
        self._active_node_id = node_id

    def _start_workflow_polling(self) -> None:
        """Start background polling for active workflows if not already running.

        Polling fetches fresh workflow state from the server every 3 seconds,
        updating _active_workflows so the status bar shows accurate info.
        """
        if self._workflow_poll_task is not None and not self._workflow_poll_task.done():
            return  # Already polling

        self._workflow_poll_task = asyncio.create_task(self._poll_active_workflows())

    async def _poll_active_workflows(self) -> None:
        """Background task that polls workflow status every 3 seconds.

        Updates _active_workflows with fresh state and pending_gate info.
        Removes completed/failed workflows from tracking.
        Stops when no more active workflows.
        """
        poll_interval = 3.0  # seconds

        while self._active_workflows and self._adapter is not None:
            try:
                # Poll each active workflow
                completed_runs: list[str] = []

                for run_id, wf_info in list(self._active_workflows.items()):
                    try:
                        status = await self._adapter.get_workflow_run(run_id)

                        if status:
                            state = status.get("state", "unknown")

                            # Update workflow info with fresh data
                            wf_info["state"] = state
                            wf_info["pending_gate"] = status.get("pending_gate")
                            wf_info["events"] = status.get("events", [])

                            # If workflow completed, update block and remove from active
                            if state in ("completed", "failed", "cancelled"):
                                completed_runs.append(run_id)

                                # Update the associated block
                                block_num = wf_info.get("block_number")
                                if block_num is not None:
                                    block = self.timeline.get(block_num)
                                    if block:
                                        if state == "completed":
                                            block.status = "completed"
                                            block.output_text = str(status.get("result", ""))
                                        else:
                                            block.status = "error"
                                            block.error = status.get("error", f"Workflow {state}")
                                        block.raw = status

                    except Exception as e:
                        logger.debug(f"Failed to poll workflow {run_id}: {e}")

                # Remove completed workflows from tracking
                for run_id in completed_runs:
                    del self._active_workflows[run_id]

                # Sleep before next poll
                await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Workflow polling error: {e}")
                await asyncio.sleep(poll_interval)

    async def _cleanup(self) -> None:
        """Cleanup resources including active workflows."""
        await self._executor.stop()

        # Cancel suggestion fetch task
        if self._suggestion_task is not None and not self._suggestion_task.done():
            self._suggestion_task.cancel()
            try:
                await self._suggestion_task
            except asyncio.CancelledError:
                pass
            self._suggestion_task = None

        # Cancel workflow polling task
        if self._workflow_poll_task is not None and not self._workflow_poll_task.done():
            self._workflow_poll_task.cancel()
            try:
                await self._workflow_poll_task
            except asyncio.CancelledError:
                pass
            self._workflow_poll_task = None

        # Cancel any active (backgrounded) workflows
        if self._active_workflows and self._adapter is not None:
            for run_id in list(self._active_workflows.keys()):
                try:
                    await self._adapter.cancel_workflow(run_id)
                    logger.debug(f"Cancelled workflow {run_id} on exit")
                except Exception as e:
                    logger.debug(f"Failed to cancel workflow {run_id}: {e}")
            self._active_workflows.clear()

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
