"""UI rendering mixin for workflow runner TUI.

Contains all _get_* methods that render FormattedText for the workflow
runner's various panels and views, plus layout construction.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout import (
    ConditionalContainer,
    HSplit,
    Layout,
    ScrollablePane,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl

from nerve.frontends.tui.commander.status_indicators import get_status_emoji
from nerve.frontends.tui.commander.text_builder import FormattedTextBuilder
from nerve.frontends.tui.commander.workflow_state import TUIWorkflowEvent

if TYPE_CHECKING:
    from nerve.frontends.tui.commander.workflow_state import StepInfo


class WorkflowUIRendererMixin:
    """Mixin providing UI rendering methods for WorkflowRunnerApp.

    Requires the host class to have these attributes:
    - start_time: float
    - state: str
    - steps: list[StepInfo]
    - selected_step_index: int
    - pending_gate: dict | None
    - events: list[TUIWorkflowEvent]
    - workflow_id: str
    - _status_message: str

    And these methods:
    - _has_gate() -> bool
    - _is_steps_focused() -> bool
    - _is_gate_focused() -> bool
    - _is_workflow_done() -> bool
    """

    # Type hints for attributes accessed from host class
    start_time: float
    state: str
    steps: list[StepInfo]
    selected_step_index: int
    pending_gate: dict[str, Any] | None
    events: list[TUIWorkflowEvent]
    workflow_id: str
    _status_message: str
    _status_message_consumed: bool

    def _has_gate(self) -> bool:  # type: ignore[empty-body]
        ...

    def _is_steps_focused(self) -> bool:  # type: ignore[empty-body]
        ...

    def _is_gate_focused(self) -> bool:  # type: ignore[empty-body]
        ...

    def _is_workflow_done(self) -> bool:  # type: ignore[empty-body]
        ...

    def _get_header(self) -> FormattedText:
        """Render header with workflow info."""
        elapsed = time.monotonic() - self.start_time
        state_emoji = get_status_emoji(self.state)

        step_info = f"{len(self.steps)} step{'s' if len(self.steps) != 1 else ''}"

        lines = [
            ("bold", f"Workflow: {self.workflow_id}"),
            ("", f" │ {state_emoji} {self.state.upper()} │ {step_info} │ {elapsed:.1f}s\n"),
            ("dim", "─" * 80 + "\n"),
        ]
        return FormattedText(lines)

    def _get_steps_list(self) -> FormattedText:
        """Render the steps list (left panel)."""
        lines: list[tuple[str, str]] = []

        # Show focus indicator when gate is present
        if self._has_gate():
            if self._is_steps_focused():
                lines.append(("bold ansigreen", "▌STEPS (focused)\n"))
            else:
                lines.append(("dim", "▌STEPS\n"))
            lines.append(("dim", "─" * 28 + "\n"))

        if not self.steps:
            lines.append(("dim", " (no steps yet)\n"))
            return FormattedText(lines)

        for i, step in enumerate(self.steps):
            is_selected = i == self.selected_step_index

            # Status indicator
            status_icon = get_status_emoji(step.status)

            # Selection indicator
            prefix = "▶ " if is_selected else "  "

            # Style
            if is_selected:
                style = "bold"
            elif step.status == "error":
                style = "ansired"
            elif step.status == "completed":
                style = ""
            else:
                style = "dim"

            lines.append((style, f"{prefix}{status_icon} {step.node_id}\n"))

        return FormattedText(lines)

    def _get_step_preview(self) -> FormattedText:
        """Render step preview (right panel)."""
        if not self.steps:
            return FormattedText([("dim", "(select a step to preview)")])

        if self.selected_step_index >= len(self.steps):
            return FormattedText([("dim", "(no step selected)")])

        step = self.steps[self.selected_step_index]
        builder = FormattedTextBuilder()

        # Input section
        input_content = step.input_text or "(no input)"
        builder.add_section("INPUT", input_content, max_chars=500)
        builder.add_spacing()

        # Output section
        builder.add_line("OUTPUT", style="bold")
        builder.add_separator(40)
        if step.status == "running":
            builder.add_line("(running...)", style="dim")
        elif step.error:
            builder.add_line(f"Error: {step.error}", style="ansired")
        else:
            output_content = step.output_text or "(no output)"
            if len(output_content) > 500:
                output_content = output_content[:500] + "..."
            builder.add_line(output_content)

        return builder.build()

    def _get_gate_prompt(self) -> FormattedText:
        """Render gate prompt."""
        if not self.pending_gate:
            return FormattedText([])

        prompt = self.pending_gate.get("prompt", "Input required:")
        choices = self.pending_gate.get("choices")

        lines: list[tuple[str, str]] = []

        # Focus indicator
        if self._is_gate_focused():
            lines.append(("bold ansigreen", "▌GATE (focused)\n"))
        else:
            lines.append(("dim", "▌GATE\n"))

        lines.append(("bold", f"⏸ {prompt}\n"))

        if choices:
            for i, choice in enumerate(choices, 1):
                lines.append(("", f"  {i}. {choice}\n"))
            lines.append(("dim", "Enter number or value: "))
        else:
            lines.append(("dim", "Enter value: "))

        return FormattedText(lines)

    def _get_status_bar(self) -> FormattedText:
        """Render status bar for main view."""
        parts = []

        if self._status_message and not self._status_message_consumed:
            parts.append(("ansigreen", f" {self._status_message} │"))
            self._status_message_consumed = True

        if self._has_gate():
            # Show focus indicator and context-appropriate keys
            focus_indicator = "[GATE]" if self._is_gate_focused() else "[STEPS]"
            parts.append(("bold", f" {focus_indicator} "))
            if self._is_gate_focused():
                parts.append(("", "│ [Enter] Submit │ [Tab] Switch │ [Ctrl-Z] Bg │ [Esc] Cancel"))
            else:
                parts.append(
                    (
                        "",
                        "│ [↑/↓] Navigate │ [Enter] Full View │ [Tab] Switch │ [Ctrl-Z] Bg │ [q] Cancel",
                    )
                )
        elif self._is_workflow_done():
            parts.append(("", " [Enter] Full View │ [e] Events │ [c] Copy │ [q] Exit"))
        else:
            parts.append(
                (
                    "",
                    " [↑/↓] Navigate │ [Enter] Full View │ [e] Events │ [c] Copy │ [Ctrl-Z] Bg │ [q] Cancel",
                )
            )

        return FormattedText(parts)

    def _get_full_screen_header(self) -> FormattedText:
        """Render full screen view header."""
        if not self.steps or self.selected_step_index >= len(self.steps):
            return FormattedText([("", "No step selected")])

        step = self.steps[self.selected_step_index]
        status_icon = get_status_emoji(step.status)

        return FormattedText(
            [
                ("bold", f"Step: {step.node_id}"),
                ("", f" │ {status_icon} {step.status}"),
                ("dim", f"  [{self.selected_step_index + 1}/{len(self.steps)}]\n"),
            ]
        )

    def _get_full_screen_content(self) -> FormattedText:
        """Render full screen step content with scrolling."""
        if not self.steps or self.selected_step_index >= len(self.steps):
            return FormattedText([("dim", "(no step selected)")])

        step = self.steps[self.selected_step_index]
        builder = FormattedTextBuilder()

        # Input section
        builder.add_section(
            "INPUT",
            step.input_text or "(no input)",
            separator_width=60,
        )
        builder.add_spacing()

        # Output section
        builder.add_line("OUTPUT", style="bold")
        builder.add_separator(60)
        if step.status == "running":
            builder.add_line("(running...)", style="dim")
        elif step.error:
            builder.add_line(f"Error: {step.error}", style="ansired")
        else:
            builder.add_line(step.output_text or "(no output)")

        return builder.build()

    def _get_full_screen_status(self) -> FormattedText:
        """Render full screen status bar."""
        return FormattedText(
            [
                (
                    "",
                    " [↑/↓] Scroll │ [←/→ or h/l] Prev/Next Step │ [e] Events │ [c] Copy │ [q/Esc] Back",
                )
            ]
        )

    def _get_events_content(self) -> FormattedText:
        """Render events list."""
        if not self.events:
            return FormattedText([("dim", "(no events yet)")])

        lines: list[tuple[str, str]] = []
        for event in self.events:
            elapsed = event.timestamp - self.start_time

            # Color based on event type
            if "error" in event.event_type or "failed" in event.event_type:
                style = "ansired"
            elif "completed" in event.event_type:
                style = "ansigreen"
            elif "gate" in event.event_type:
                style = "ansiyellow"
            elif "started" in event.event_type:
                style = "ansicyan"
            else:
                style = ""

            lines.append((style, f"[{elapsed:6.2f}s] {event.event_type}\n"))

            # Show data preview
            if event.data:
                data_str = str(event.data)
                if len(data_str) > 80:
                    data_str = data_str[:77] + "..."
                lines.append(("dim", f"  {data_str}\n"))

        return FormattedText(lines)


def create_workflow_layout(app: Any) -> Layout:
    """Create the TUI layout with view switching.

    Creates a Layout with three conditional views:
    - Main view: steps list + preview + optional gate input
    - Full screen view: single step detail with scrolling
    - Events view: workflow event log

    Args:
        app: WorkflowRunnerApp instance with required attributes/methods:
            - _steps_focus_control: BufferControl for steps focus
            - _steps_control: FormattedTextControl for steps list
            - _gate_buffer_control: BufferControl for gate input
            - _get_header, _get_step_preview, _get_gate_prompt, _get_status_bar
            - _get_full_screen_header, _get_full_screen_content, _get_full_screen_status
            - _get_events_content
            - _is_main_view, _is_full_screen_view, _is_events_view
            - _has_gate

    Returns:
        Layout configured for the workflow TUI.
    """
    # Main view layout
    main_view = HSplit(
        [
            # Header
            Window(content=FormattedTextControl(text=app._get_header), height=3),
            # Main content: steps list + preview
            VSplit(
                [
                    # Left: Steps list with hidden focus receiver
                    HSplit(
                        [
                            # Hidden focus receiver (0 height, just for focus)
                            Window(content=app._steps_focus_control, height=0),
                            # Actual steps list
                            Window(
                                content=app._steps_control,
                            ),
                        ],
                        width=30,
                    ),
                    # Separator
                    Window(width=1, char="│", style="dim"),
                    # Right: Step preview
                    Window(
                        content=FormattedTextControl(text=app._get_step_preview),
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
                                content=FormattedTextControl(text=app._get_gate_prompt),
                                wrap_lines=True,
                            ),
                        ),
                        Window(height=1, char="─", style="dim"),
                        Window(content=app._gate_buffer_control, height=1),
                    ],
                    height=12,  # Give gate panel more viewport space
                ),
                filter=Condition(lambda: app._has_gate()),
            ),
            # Status bar
            Window(
                content=FormattedTextControl(text=app._get_status_bar),
                height=1,
                style="reverse",
            ),
        ]
    )

    # Full screen step view
    full_screen_view = HSplit(
        [
            Window(content=FormattedTextControl(text=app._get_full_screen_header), height=2),
            Window(height=1, char="─", style="dim"),
            ScrollablePane(
                Window(
                    content=FormattedTextControl(text=app._get_full_screen_content),
                    wrap_lines=True,
                ),
            ),
            Window(
                content=FormattedTextControl(text=app._get_full_screen_status),
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
                    content=FormattedTextControl(text=app._get_events_content),
                    wrap_lines=True,
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
            ConditionalContainer(main_view, filter=Condition(lambda: app._is_main_view())),
            ConditionalContainer(
                full_screen_view, filter=Condition(lambda: app._is_full_screen_view())
            ),
            ConditionalContainer(events_view, filter=Condition(lambda: app._is_events_view())),
        ]
    )

    return Layout(root)
