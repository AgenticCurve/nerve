"""Full-screen TUI for running workflows with step visualization.

Provides a dedicated interface for workflow execution that:
- Shows workflow steps in a navigable list (left panel)
- Displays input/output preview of selected step (right panel)
- Handles gates with interactive prompts (bottom panel)
- Supports full-screen step detail view with scrolling
- Supports events log view

Key bindings:
- Main view: ↑/↓ navigate steps, Enter full view, e events, c copy, Ctrl-Z bg, q/Esc cancel
- With gate: Tab/Shift-Tab switch panes, Enter submit (gate), q/Esc cancel
- Full screen: ↑/↓ scroll, h/l or ←/→ prev/next step, e events, c copy, q/Esc back
- Events: ↑/↓ scroll, q/Esc back

Usage:
    result = await run_workflow_tui(adapter, workflow_id, input_text)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import (
    ConditionalContainer,
    HSplit,
    Layout,
    ScrollablePane,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl

from nerve.frontends.tui.commander.clipboard import copy_to_clipboard
from nerve.frontends.tui.commander.workflow_state import (
    StepInfo,
    TUIWorkflowEvent,
    ViewMode,
)
from nerve.frontends.tui.commander.workflow_ui import WorkflowUIRendererMixin

if TYPE_CHECKING:
    from nerve.frontends.cli.repl.adapters import RemoteSessionAdapter


@dataclass
class WorkflowRunnerApp(WorkflowUIRendererMixin):
    """Full-screen TUI for running a workflow with step visualization."""

    adapter: RemoteSessionAdapter
    workflow_id: str
    input_text: str

    # Run state (populated after start)
    run_id: str = ""
    state: str = "pending"
    result: Any = None
    error: str | None = None
    start_time: float = field(default_factory=time.monotonic)
    events: list[TUIWorkflowEvent] = field(default_factory=list)
    steps: list[StepInfo] = field(default_factory=list)

    # Gate state
    pending_gate: dict[str, Any] | None = None
    gate_input_buffer: Buffer = field(default_factory=lambda: Buffer())

    # UI state
    cancelled: bool = False
    backgrounded: bool = False
    view_mode: ViewMode = ViewMode.MAIN
    selected_step_index: int = 0
    scroll_offset: int = 0
    focus_pane: str = "steps"  # "steps" or "gate"
    _app: Application[None] | None = field(default=None, init=False)
    _pending_answer: str | None = field(default=None, init=False)
    _status_message: str = ""  # Temporary status message (e.g., "Copied!")
    _status_message_consumed: bool = True  # Flag to track if message was shown

    def __post_init__(self) -> None:
        """Initialize the workflow runner UI."""
        self.kb = self._create_key_bindings()
        # Create controls we need to focus
        self._gate_buffer_control = BufferControl(buffer=self.gate_input_buffer)
        self._steps_control = FormattedTextControl(text=self._get_steps_list)
        # Dummy buffer for steps pane focus (invisible, just receives focus)
        self._steps_focus_buffer = Buffer(read_only=True)
        self._steps_focus_control = BufferControl(
            buffer=self._steps_focus_buffer,
            focusable=True,
        )
        self.layout = self._create_layout()
        self._app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            full_screen=True,
            refresh_interval=0.1,
        )

    def _is_main_view(self) -> bool:
        return self.view_mode == ViewMode.MAIN

    def _is_full_screen_view(self) -> bool:
        return self.view_mode == ViewMode.FULL_SCREEN

    def _is_events_view(self) -> bool:
        return self.view_mode == ViewMode.EVENTS

    def _is_workflow_active(self) -> bool:
        return self.state in ("pending", "running", "waiting")

    def _is_workflow_done(self) -> bool:
        return self.state in ("completed", "failed", "cancelled")

    def _has_gate(self) -> bool:
        return self.pending_gate is not None and self.state == "waiting"

    def _is_gate_focused(self) -> bool:
        return self._has_gate() and self.focus_pane == "gate"

    def _is_steps_focused(self) -> bool:
        return self.focus_pane == "steps"

    def _create_key_bindings(self) -> KeyBindings:
        """Create key bindings for workflow runner."""
        kb = KeyBindings()

        # ===== PANE SWITCHING =====

        # Tab switches focus to next pane, Shift+Tab to previous
        @kb.add("tab", filter=Condition(lambda: self._is_main_view() and self._has_gate()))
        def focus_next_pane(event: KeyPressEvent) -> None:
            if self.focus_pane == "steps":
                self.focus_pane = "gate"
                event.app.layout.focus(self._gate_buffer_control)
            else:
                self.focus_pane = "steps"
                event.app.layout.focus(self._steps_focus_control)

        @kb.add("s-tab", filter=Condition(lambda: self._is_main_view() and self._has_gate()))
        def focus_prev_pane(event: KeyPressEvent) -> None:
            if self.focus_pane == "gate":
                self.focus_pane = "steps"
                event.app.layout.focus(self._steps_focus_control)
            else:
                self.focus_pane = "gate"
                event.app.layout.focus(self._gate_buffer_control)

        # ===== MAIN VIEW =====

        # Navigate steps (main view, steps pane focused or no gate)
        @kb.add(
            "up",
            filter=Condition(
                lambda: self._is_main_view() and (not self._has_gate() or self._is_steps_focused())
            ),
        )
        @kb.add(
            "k",
            filter=Condition(
                lambda: self._is_main_view() and (not self._has_gate() or self._is_steps_focused())
            ),
        )
        def nav_up_main(event: KeyPressEvent) -> None:
            if self.selected_step_index > 0:
                self.selected_step_index -= 1

        @kb.add(
            "down",
            filter=Condition(
                lambda: self._is_main_view() and (not self._has_gate() or self._is_steps_focused())
            ),
        )
        @kb.add(
            "j",
            filter=Condition(
                lambda: self._is_main_view() and (not self._has_gate() or self._is_steps_focused())
            ),
        )
        def nav_down_main(event: KeyPressEvent) -> None:
            if self.selected_step_index < len(self.steps) - 1:
                self.selected_step_index += 1

        # Enter full screen view (main view, steps focused or no gate)
        @kb.add(
            "enter",
            filter=Condition(
                lambda: self._is_main_view()
                and (not self._has_gate() or self._is_steps_focused())
                and len(self.steps) > 0
            ),
        )
        def enter_full_screen(event: KeyPressEvent) -> None:
            self.view_mode = ViewMode.FULL_SCREEN
            self.scroll_offset = 0

        # Events view (main or full screen, not gate focused)
        @kb.add(
            "e",
            filter=Condition(
                lambda: self._is_main_view() and (not self._has_gate() or self._is_steps_focused())
            ),
        )
        @kb.add("e", filter=Condition(lambda: self._is_full_screen_view()))
        def enter_events(event: KeyPressEvent) -> None:
            self.view_mode = ViewMode.EVENTS
            self.scroll_offset = 0

        # Copy to clipboard (main or full screen, not gate focused)
        @kb.add(
            "c",
            filter=Condition(
                lambda: self._is_main_view()
                and (not self._has_gate() or self._is_steps_focused())
                and len(self.steps) > 0
            ),
        )
        @kb.add("c", filter=Condition(lambda: self._is_full_screen_view()))
        def copy_step(event: KeyPressEvent) -> None:
            self._copy_current_step()

        # Background workflow (Ctrl-Z)
        @kb.add(
            "c-z", filter=Condition(lambda: self._is_workflow_active() and self._is_main_view())
        )
        def background_workflow(event: KeyPressEvent) -> None:
            self.backgrounded = True
            event.app.exit()

        # Cancel/Exit (q or Esc in main view, not gate focused)
        @kb.add(
            "q",
            filter=Condition(
                lambda: self._is_main_view() and (not self._has_gate() or self._is_steps_focused())
            ),
        )
        @kb.add(
            "escape",
            filter=Condition(
                lambda: self._is_main_view() and (not self._has_gate() or self._is_steps_focused())
            ),
        )
        def cancel_or_exit_main(event: KeyPressEvent) -> None:
            if self._is_workflow_done():
                event.app.exit()
            else:
                self.cancelled = True

        # ===== GATE INPUT =====

        # Gate: submit answer (only when gate focused)
        @kb.add("enter", filter=Condition(lambda: self._is_gate_focused()))
        def submit_gate(event: KeyPressEvent) -> None:
            answer = self.gate_input_buffer.text.strip()
            if answer:
                choices = self.pending_gate.get("choices") if self.pending_gate else None
                if choices and answer.isdigit():
                    idx = int(answer) - 1
                    if 0 <= idx < len(choices):
                        answer = choices[idx]
                self._pending_answer = answer
                self.gate_input_buffer.reset()

        # Gate: cancel (only when gate focused)
        @kb.add("escape", filter=Condition(lambda: self._is_gate_focused()))
        @kb.add("c-c", filter=Condition(lambda: self._is_gate_focused()))
        def cancel_gate(event: KeyPressEvent) -> None:
            self.cancelled = True

        # ===== FULL SCREEN VIEW =====

        # Scroll in full screen
        @kb.add("up", filter=Condition(lambda: self._is_full_screen_view()))
        @kb.add("k", filter=Condition(lambda: self._is_full_screen_view()))
        def scroll_up_full(event: KeyPressEvent) -> None:
            if self.scroll_offset > 0:
                self.scroll_offset -= 1

        @kb.add("down", filter=Condition(lambda: self._is_full_screen_view()))
        @kb.add("j", filter=Condition(lambda: self._is_full_screen_view()))
        def scroll_down_full(event: KeyPressEvent) -> None:
            self.scroll_offset += 1

        # Navigate steps in full screen (h/l or arrows)
        @kb.add("left", filter=Condition(lambda: self._is_full_screen_view()))
        @kb.add("h", filter=Condition(lambda: self._is_full_screen_view()))
        def prev_step(event: KeyPressEvent) -> None:
            if self.selected_step_index > 0:
                self.selected_step_index -= 1
                self.scroll_offset = 0

        @kb.add("right", filter=Condition(lambda: self._is_full_screen_view()))
        @kb.add("l", filter=Condition(lambda: self._is_full_screen_view()))
        def next_step(event: KeyPressEvent) -> None:
            if self.selected_step_index < len(self.steps) - 1:
                self.selected_step_index += 1
                self.scroll_offset = 0

        # Back from full screen
        @kb.add("q", filter=Condition(lambda: self._is_full_screen_view()))
        @kb.add("escape", filter=Condition(lambda: self._is_full_screen_view()))
        def back_from_full(event: KeyPressEvent) -> None:
            self.view_mode = ViewMode.MAIN

        # ===== EVENTS VIEW =====

        # Scroll in events
        @kb.add("up", filter=Condition(lambda: self._is_events_view()))
        @kb.add("k", filter=Condition(lambda: self._is_events_view()))
        def scroll_up_events(event: KeyPressEvent) -> None:
            if self.scroll_offset > 0:
                self.scroll_offset -= 1

        @kb.add("down", filter=Condition(lambda: self._is_events_view()))
        @kb.add("j", filter=Condition(lambda: self._is_events_view()))
        def scroll_down_events(event: KeyPressEvent) -> None:
            self.scroll_offset += 1

        # Back from events
        @kb.add("q", filter=Condition(lambda: self._is_events_view()))
        @kb.add("escape", filter=Condition(lambda: self._is_events_view()))
        def back_from_events(event: KeyPressEvent) -> None:
            self.view_mode = ViewMode.MAIN
            self.scroll_offset = 0

        return kb

    def _copy_current_step(self) -> None:
        """Copy current step's input/output to clipboard."""
        if not self.steps or self.selected_step_index >= len(self.steps):
            return

        step = self.steps[self.selected_step_index]
        text = f"=== INPUT ===\n{step.input_text}\n\n=== OUTPUT ===\n{step.output_text}"

        _, self._status_message = copy_to_clipboard(text)
        self._status_message_consumed = False  # Reset so message shows

    def _create_layout(self) -> Layout:
        """Create the TUI layout with view switching."""
        # Main view layout
        main_view = HSplit(
            [
                # Header
                Window(content=FormattedTextControl(text=self._get_header), height=3),
                # Main content: steps list + preview
                VSplit(
                    [
                        # Left: Steps list with hidden focus receiver
                        HSplit(
                            [
                                # Hidden focus receiver (0 height, just for focus)
                                Window(content=self._steps_focus_control, height=0),
                                # Actual steps list
                                Window(
                                    content=self._steps_control,
                                ),
                            ],
                            width=30,
                        ),
                        # Separator
                        Window(width=1, char="│", style="dim"),
                        # Right: Step preview
                        Window(
                            content=FormattedTextControl(text=self._get_step_preview),
                            wrap_lines=True,
                        ),
                    ]
                ),
                # Gate input (conditional)
                ConditionalContainer(
                    HSplit(
                        [
                            Window(height=1, char="─", style="dim"),
                            ScrollablePane(
                                Window(
                                    content=FormattedTextControl(text=self._get_gate_prompt),
                                    wrap_lines=True,
                                ),
                            ),
                            Window(height=1, char="─", style="dim"),
                            Window(content=self._gate_buffer_control, height=1),
                        ],
                        height=12,  # Give gate panel more viewport space
                    ),
                    filter=Condition(lambda: self._has_gate()),
                ),
                # Status bar
                Window(
                    content=FormattedTextControl(text=self._get_status_bar),
                    height=1,
                    style="reverse",
                ),
            ]
        )

        # Full screen step view
        full_screen_view = HSplit(
            [
                Window(content=FormattedTextControl(text=self._get_full_screen_header), height=2),
                Window(height=1, char="─", style="dim"),
                ScrollablePane(
                    Window(
                        content=FormattedTextControl(text=self._get_full_screen_content),
                        wrap_lines=True,
                    ),
                ),
                Window(
                    content=FormattedTextControl(text=self._get_full_screen_status),
                    height=1,
                    style="reverse",
                ),
            ]
        )

        # Events view
        events_view = HSplit(
            [
                Window(
                    content=FormattedTextControl(
                        text=lambda: FormattedText([("bold", "Workflow Events\n")])
                    ),
                    height=2,
                ),
                Window(height=1, char="─", style="dim"),
                ScrollablePane(
                    Window(
                        content=FormattedTextControl(text=self._get_events_content), wrap_lines=True
                    ),
                ),
                Window(
                    content=FormattedTextControl(
                        text=lambda: FormattedText([("", " [↑/↓] Scroll │ [q/Esc] Back")])
                    ),
                    height=1,
                    style="reverse",
                ),
            ]
        )

        # Root with conditional containers
        root = HSplit(
            [
                ConditionalContainer(main_view, filter=Condition(lambda: self._is_main_view())),
                ConditionalContainer(
                    full_screen_view, filter=Condition(lambda: self._is_full_screen_view())
                ),
                ConditionalContainer(events_view, filter=Condition(lambda: self._is_events_view())),
            ]
        )

        return Layout(root)

    def _add_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Add a local event."""
        self.events.append(
            TUIWorkflowEvent(
                timestamp=time.monotonic(),
                event_type=event_type,
                data=data or {},
            )
        )

    def _update_steps_from_events(self, server_events: list[dict[str, Any]]) -> None:
        """Update steps list from server events."""
        for event in server_events:
            event_type = event.get("event_type", "")
            data = event.get("data", {})

            if event_type == "node_started":
                node_id = data.get("node_id", "unknown")
                input_text = data.get("input", "")
                # Avoid duplicate if already tracking this node as running
                if any(s.node_id == node_id and s.status == "running" for s in self.steps):
                    continue
                # Add new step
                self.steps.append(
                    StepInfo(
                        node_id=node_id,
                        input_text=input_text,
                        status="running",
                    )
                )

            elif event_type == "node_completed":
                node_id = data.get("node_id", "")
                output_text = data.get("output", "")
                # Find and update the step
                for step in reversed(self.steps):
                    if step.node_id == node_id and step.status == "running":
                        step.status = "completed"
                        step.output_text = output_text
                        break

            elif event_type == "node_error":
                node_id = data.get("node_id", "")
                error = data.get("error", "Unknown error")
                for step in reversed(self.steps):
                    if step.node_id == node_id and step.status == "running":
                        step.status = "error"
                        step.error = error
                        break

            elif event_type == "graph_started":
                graph_id = data.get("graph_id", "unknown")
                input_text = data.get("input", "")
                # Avoid duplicate if already tracking this graph as running
                if any(s.node_id == graph_id and s.status == "running" for s in self.steps):
                    continue
                # Add new step (graphs show as steps too)
                self.steps.append(
                    StepInfo(
                        node_id=f"[graph] {graph_id}",
                        input_text=input_text,
                        status="running",
                    )
                )

            elif event_type == "graph_completed":
                graph_id = data.get("graph_id", "")
                output_text = data.get("output", "")
                # Find and update the step
                for step in reversed(self.steps):
                    if step.node_id == f"[graph] {graph_id}" and step.status == "running":
                        step.status = "completed"
                        step.output_text = output_text
                        break

            elif event_type == "graph_error":
                graph_id = data.get("graph_id", "")
                error = data.get("error", "Unknown error")
                for step in reversed(self.steps):
                    if step.node_id == f"[graph] {graph_id}" and step.status == "running":
                        step.status = "error"
                        step.error = error
                        break

            elif event_type == "nested_workflow_started":
                workflow_id = data.get("workflow_id", "unknown")
                input_text = data.get("input", "")
                # Avoid duplicate if already tracking this workflow as running
                if any(
                    s.node_id == f"[workflow] {workflow_id}" and s.status == "running"
                    for s in self.steps
                ):
                    continue
                # Add new step (nested workflows show as steps)
                self.steps.append(
                    StepInfo(
                        node_id=f"[workflow] {workflow_id}",
                        input_text=input_text,
                        status="running",
                    )
                )

            elif event_type == "nested_workflow_completed":
                workflow_id = data.get("workflow_id", "")
                # Find and update the step
                for step in reversed(self.steps):
                    if step.node_id == f"[workflow] {workflow_id}" and step.status == "running":
                        step.status = "completed"
                        step.output_text = "(completed)"
                        break

            elif event_type == "nested_workflow_error":
                workflow_id = data.get("workflow_id", "")
                error = data.get("error", "Unknown error")
                for step in reversed(self.steps):
                    if step.node_id == f"[workflow] {workflow_id}" and step.status == "running":
                        step.status = "error"
                        step.error = error
                        break

    async def _poll_workflow(self) -> None:
        """Poll workflow status and update state."""
        last_event_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 10

        while self.state not in ("completed", "failed", "cancelled"):
            # Check for cancellation request
            if self.cancelled:
                try:
                    await self.adapter.cancel_workflow(self.run_id)
                    self._add_event("workflow_cancelled", {"by": "user"})
                except Exception as e:
                    self._add_event("cancel_error", {"error": str(e)})
                self.state = "cancelled"
                break

            # Check for pending gate answer
            if self._pending_answer and self.pending_gate:
                try:
                    await self.adapter.answer_gate(self.run_id, self._pending_answer)
                    self._add_event("gate_answered", {"answer": self._pending_answer})
                    self.pending_gate = None
                    self._pending_answer = None
                    self.focus_pane = "steps"  # Return focus to steps after gate answered
                    if self._app:
                        self._app.layout.focus(self._steps_focus_control)
                except Exception as e:
                    self._add_event("gate_error", {"error": str(e)})
                    self._pending_answer = None

            # Poll status
            try:
                run_info = await self.adapter.get_workflow_run(self.run_id)
                consecutive_errors = 0  # Reset on success
            except Exception as e:
                consecutive_errors += 1
                self._add_event("poll_error", {"error": str(e)})
                if consecutive_errors >= max_consecutive_errors:
                    self.error = f"Max poll errors exceeded ({consecutive_errors}): {e}"
                    self.state = "failed"
                    self._add_event("poll_failed", {"error": self.error})
                    break
                await asyncio.sleep(0.5)
                continue

            new_state = run_info.get("state", self.state)

            # Handle state transitions
            if new_state != self.state:
                self._add_event("state_changed", {"from": self.state, "to": new_state})
                self.state = new_state

            # Update steps from server events
            server_events = run_info.get("events", [])
            if len(server_events) > last_event_count:
                new_events = server_events[last_event_count:]
                self._update_steps_from_events(new_events)
                last_event_count = len(server_events)

            # Handle completion
            if self.state == "completed":
                self.result = run_info.get("result")
                self._add_event("workflow_completed", {"result_type": type(self.result).__name__})

            elif self.state == "failed":
                self.error = run_info.get("error", "Unknown error")
                self._add_event("workflow_failed", {"error": self.error})

            elif self.state == "waiting":
                gate = run_info.get("pending_gate")
                if gate and gate != self.pending_gate:
                    self.pending_gate = gate
                    self.focus_pane = "gate"  # Auto-focus gate when it appears
                    if self._app:
                        self._app.layout.focus(self._gate_buffer_control)
                    self._add_event("gate_waiting", {"prompt": gate.get("prompt", "")[:50]})

            await asyncio.sleep(0.2)

    def _serialize_steps(self) -> list[dict[str, Any]]:
        """Serialize steps for return payload."""
        return [
            {
                "node_id": s.node_id,
                "input": s.input_text,
                "output": s.output_text,
                "status": s.status,
            }
            for s in self.steps
        ]

    async def run(self) -> dict[str, Any]:
        """Run the workflow and return result."""
        # Start the workflow
        try:
            result = await self.adapter.execute_workflow(self.workflow_id, self.input_text)
            self.run_id = result.get("run_id", "unknown")
            self.state = result.get("state", "running")
            self._add_event("workflow_started", {"run_id": self.run_id})
        except Exception as e:
            self.error = str(e)
            self.state = "failed"
            self._add_event("start_error", {"error": str(e)})

        # Start polling in background
        poll_task = asyncio.create_task(self._poll_workflow())

        try:
            if self._app is None:
                raise RuntimeError(f"TUI app not initialized for workflow run {self.run_id}")
            await self._app.run_async()
        finally:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass

        duration_ms = (time.monotonic() - self.start_time) * 1000
        return {
            "state": "backgrounded" if self.backgrounded else self.state,
            "result": self.result,
            "error": self.error,
            "duration_ms": duration_ms,
            "run_id": self.run_id,
            "backgrounded": self.backgrounded,
            "events": self.events,
            "pending_gate": self.pending_gate,
            "steps": self._serialize_steps(),
        }

    async def resume(self) -> dict[str, Any]:
        """Resume a backgrounded workflow."""
        self._add_event("workflow_resumed", {"run_id": self.run_id})

        poll_task = asyncio.create_task(self._poll_workflow())

        try:
            if self._app is None:
                raise RuntimeError(f"TUI app not initialized for workflow run {self.run_id}")
            await self._app.run_async()
        finally:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass

        duration_ms = (time.monotonic() - self.start_time) * 1000
        return {
            "state": "backgrounded" if self.backgrounded else self.state,
            "result": self.result,
            "error": self.error,
            "duration_ms": duration_ms,
            "run_id": self.run_id,
            "backgrounded": self.backgrounded,
            "events": self.events,
            "pending_gate": self.pending_gate,
            "steps": self._serialize_steps(),
        }


async def run_workflow_tui(
    adapter: RemoteSessionAdapter,
    workflow_id: str,
    input_text: str,
) -> dict[str, Any]:
    """Launch the full-screen workflow runner TUI."""
    runner = WorkflowRunnerApp(
        adapter=adapter,
        workflow_id=workflow_id,
        input_text=input_text,
    )
    return await runner.run()


async def resume_workflow_tui(
    adapter: RemoteSessionAdapter,
    workflow_info: dict[str, Any],
) -> dict[str, Any]:
    """Resume a backgrounded workflow in the full-screen TUI."""
    runner = WorkflowRunnerApp(
        adapter=adapter,
        workflow_id=workflow_info.get("workflow_id", ""),
        input_text="(resumed)",
    )
    # Restore state from workflow info
    runner.run_id = workflow_info.get("run_id", "")
    runner.state = workflow_info.get("state", "running")
    runner.pending_gate = workflow_info.get("pending_gate")

    # Restore events - they may be TUIWorkflowEvent objects or serialized dicts
    raw_events = workflow_info.get("events", [])
    runner.events = []
    for ev in raw_events:
        if isinstance(ev, TUIWorkflowEvent):
            runner.events.append(ev)
        elif isinstance(ev, dict):
            runner.events.append(
                TUIWorkflowEvent(
                    timestamp=ev.get("timestamp", runner.start_time),
                    event_type=ev.get("event_type", "unknown"),
                    data=ev.get("data", {}),
                )
            )

    # Override to "waiting" if there's a pending gate
    if runner.pending_gate:
        runner.state = "waiting"

    # Restore steps
    for step_data in workflow_info.get("steps", []):
        runner.steps.append(
            StepInfo(
                node_id=step_data.get("node_id", ""),
                input_text=step_data.get("input", ""),
                output_text=step_data.get("output", ""),
                status=step_data.get("status", "completed"),
            )
        )

    return await runner.resume()
