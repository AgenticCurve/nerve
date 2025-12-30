"""Full-screen TUI monitor for Commander blocks.

Provides a navigable interface to view all blocks, their inputs/outputs,
and drill down into details with Markdown rendering.

Usage:
    Press Ctrl-Y in Commander to open monitor
    j/k or arrows to navigate
    Enter to view block details
    Ctrl-T to open section in external editor (read-only)
    Esc to go back / exit

Configuration:
    Set EDITOR environment variable to use your preferred editor
    Supported editors with read-only mode: vim, neovim, nano, emacs
    Default: VSCode (code)
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import (
    ConditionalContainer,
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console
from rich.markdown import Markdown

if TYPE_CHECKING:
    from nerve.frontends.tui.commander.blocks import Block, Timeline


def render_markdown(text: str) -> str:
    """Render text with Rich Markdown formatting and syntax highlighting.

    Uses Rich to render full Markdown with:
    - Code blocks with syntax highlighting
    - Headers, lists, blockquotes
    - Bold, italic, links
    - Tables

    Args:
        text: The Markdown text to render.

    Returns:
        Rendered text with ANSI color codes for terminal display.
    """
    # Create a Rich console that writes to a string buffer
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=True, width=100)

    # Create Markdown object and render it
    md = Markdown(text)
    console.print(md)

    # Get the rendered output with ANSI codes
    rendered = buffer.getvalue()
    buffer.close()

    return rendered.rstrip()


@dataclass
class MonitorApp:
    """Full-screen TUI for monitoring Commander blocks.

    Three-level navigation:
    - Level 1 (cards): All blocks as cards with input/output sections
    - Level 2 (card_detail): Single card with full input/output
    - Level 3 (section_view): Single section in vim-like viewport
    """

    timeline: Timeline

    # Configuration
    editor_command: str | None = None  # External editor command (None = auto-detect)

    # Navigation state
    view_mode: str = "cards"  # "cards", "card_detail", or "section_view"
    selected_card_index: int = 0  # Which card is selected
    selected_section: str = "input"  # "input" or "output" (for card_detail and section_view)
    scroll_offset: int = 0  # Scroll position in section_view

    # Vi mode text area (initialized in __post_init__)
    _text_area: TextArea = field(init=False)

    def __post_init__(self) -> None:
        """Initialize the monitor UI."""
        # Create TextArea for vi mode (section_view)
        self._text_area = TextArea(
            text="",
            read_only=True,
            scrollbar=True,
            focusable=True,
            focus_on_click=True,
        )

        # Create key bindings (vi bindings are merged with main bindings)
        self.kb = self._create_key_bindings()
        self.layout = self._create_layout()
        self.app: Application[None] = Application(
            layout=self.layout,
            key_bindings=self.kb,
            full_screen=True,
            refresh_interval=1.0,  # Live updates every second
        )

    def _get_editor_command(self) -> list[str]:
        """Get the editor command with read-only flags.

        Returns:
            List of command parts (command + flags).
        """
        # Use configured editor or fall back to environment variable or default
        editor = self.editor_command or os.environ.get("EDITOR", "code")

        # Add read-only flags for known editors
        editor_lower = editor.lower()
        if "vim" in editor_lower or "nvim" in editor_lower or "vi" in editor_lower:
            # Vim/Neovim: -R flag for read-only mode
            return [editor, "-R"]
        elif "emacs" in editor_lower:
            # Emacs: --eval to open in read-only mode
            return [editor, "--eval", "(setq buffer-read-only t)"]
        elif "code" in editor_lower or "vscode" in editor_lower:
            # VSCode: --wait to keep file open, --reuse-window to reuse existing window
            return [editor, "--wait", "--reuse-window"]
        elif "nano" in editor_lower:
            # Nano: -v flag for view (read-only) mode
            return [editor, "-v"]
        elif "less" in editor_lower or "more" in editor_lower:
            # Pagers are already read-only
            return [editor]
        else:
            # Unknown editor, just use as-is
            return [editor]

    def _open_in_external_editor(self) -> None:
        """Open the selected section in an external editor (read-only).

        Creates a temporary file with the section content and opens it
        in the user's configured editor. The file is made read-only.
        """
        if not self.timeline.blocks or self.selected_card_index >= len(self.timeline.blocks):
            return

        block = self.timeline.blocks[self.selected_card_index]

        # Get the content for selected section
        if self.selected_section == "input":
            content = block.input_text
            section_name = "input"
        else:
            content = block.output_text or (
                f"Error: {block.error}" if block.error else "(no output)"
            )
            section_name = "output"

        # Add metadata header
        node_display = f"{block.node_id}" if block.node_id else "python"
        header = f"# Block :::{block.number} @{node_display} - {section_name.upper()}\n\n"
        info = f"Status: {block.status}\nDuration: {block.duration_ms}ms\n\n---\n\n"
        full_content = header + info + content

        try:
            # Generate temp file path
            tmp_dir = tempfile.gettempdir()
            tmp_filename = f"nerve_block_{block.number}_{node_display}_{section_name}.md"
            tmp_path = os.path.join(tmp_dir, tmp_filename)

            # Write content to file
            with open(tmp_path, "w") as f:
                f.write(full_content)

            # Make the file read-only
            os.chmod(tmp_path, 0o444)  # r--r--r--

            # Get editor command with read-only flags
            editor_cmd = self._get_editor_command()
            editor_cmd.append(tmp_path)

            # Open in editor (blocking call - wait for editor to close)
            subprocess.run(editor_cmd, check=False)

            # Clean up temp file after editor closes
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        except Exception:
            # Silently ignore errors - TUI will continue
            pass

    def _create_key_bindings(self) -> KeyBindings:
        """Create key bindings for 3-level navigation."""
        kb = KeyBindings()

        # Exit monitor (Esc or q or Ctrl-Y)
        @kb.add("escape")
        @kb.add("q")
        @kb.add("c-y")
        def exit_or_back(event: KeyPressEvent) -> None:
            # In section_view, Esc is handled by vi bindings
            if self.view_mode == "section_view":
                self.view_mode = "card_detail"
                return
            # Exit monitor from cards view, otherwise go back one level
            if self.view_mode == "cards":
                event.app.exit()
            elif self.view_mode == "card_detail":
                self.view_mode = "cards"
                self.selected_section = "input"

        # Backspace: Go back one level (try both backspace and c-h)
        @kb.add("backspace")
        @kb.add("c-h")
        def go_back(event: KeyPressEvent) -> None:
            if self.view_mode == "card_detail":
                self.view_mode = "cards"
                self.selected_section = "input"
            elif self.view_mode == "section_view":
                self.view_mode = "card_detail"
                self.scroll_offset = 0

        # j/k or arrows: Navigate
        @kb.add("j")
        @kb.add("down")
        def move_down(event: KeyPressEvent) -> None:
            if self.view_mode == "cards":
                # Navigate between cards
                self.selected_card_index = min(
                    self.selected_card_index + 1, len(self.timeline.blocks) - 1
                )
            elif self.view_mode == "card_detail":
                # Toggle between input/output sections
                self.selected_section = "output" if self.selected_section == "input" else "input"
            elif self.view_mode == "section_view":
                # Vi mode: move down one line
                event.current_buffer.cursor_down()

        @kb.add("k")
        @kb.add("up")
        def move_up(event: KeyPressEvent) -> None:
            if self.view_mode == "cards":
                # Navigate between cards
                self.selected_card_index = max(self.selected_card_index - 1, 0)
            elif self.view_mode == "card_detail":
                # Toggle between input/output sections
                self.selected_section = "input" if self.selected_section == "output" else "output"
            elif self.view_mode == "section_view":
                # Vi mode: move up one line
                event.current_buffer.cursor_up()

        # Enter: Drill down
        @kb.add("enter")
        def drill_down(event: KeyPressEvent) -> None:
            if self.view_mode == "cards" and self.timeline.blocks:
                # Open card detail
                self.view_mode = "card_detail"
                self.selected_section = "input"
            elif self.view_mode == "card_detail":
                # Open section viewport with vi mode
                self._populate_text_area()
                self.view_mode = "section_view"
                self.scroll_offset = 0
                # Focus the text area
                event.app.layout.focus(self._text_area)

        # Ctrl-T: Open selected section in external editor (read-only)
        @kb.add("c-t")
        def open_external_editor(event: KeyPressEvent) -> None:
            if self.view_mode == "card_detail":
                # Open the selected section in external editor
                self._open_in_external_editor()

        # === Vi Mode Bindings (only active in section_view) ===

        # Vi navigation: hjkl
        @kb.add("h")
        def vi_left(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                event.current_buffer.cursor_position -= 1

        @kb.add("l")
        def vi_right(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                event.current_buffer.cursor_position += 1

        # Note: j/k are handled above for cards/card_detail navigation
        # In section_view, they need different behavior

        # Vi: gg and G
        @kb.add("g", "g")
        def vi_top(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                event.current_buffer.cursor_position = 0

        @kb.add("G")
        def vi_bottom(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                event.current_buffer.cursor_position = len(event.current_buffer.text)

        # Vi: 0 and $
        @kb.add("0")
        def vi_line_start(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                pos = event.current_buffer.document.get_start_of_line_position()
                event.current_buffer.cursor_position += pos

        @kb.add("$")
        def vi_line_end(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                pos = event.current_buffer.document.get_end_of_line_position()
                event.current_buffer.cursor_position += pos

        # Vi: word navigation (w, e, b)
        @kb.add("w")
        def vi_word_forward(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                pos = event.current_buffer.document.find_next_word_beginning()
                if pos:
                    event.current_buffer.cursor_position += pos

        @kb.add("e")
        def vi_word_end(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                pos = event.current_buffer.document.find_next_word_ending()
                if pos:
                    event.current_buffer.cursor_position += pos

        @kb.add("b")
        def vi_word_back(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                pos = event.current_buffer.document.find_previous_word_beginning()
                if pos:
                    event.current_buffer.cursor_position += pos

        # Vi: page navigation
        @kb.add("c-f")
        def vi_page_down(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                from prompt_toolkit.key_binding.bindings.scroll import scroll_page_down

                scroll_page_down(event)

        @kb.add("c-b")
        def vi_page_up(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                from prompt_toolkit.key_binding.bindings.scroll import scroll_page_up

                scroll_page_up(event)

        @kb.add("c-d")
        def vi_half_page_down(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                from prompt_toolkit.key_binding.bindings.scroll import scroll_half_page_down

                scroll_half_page_down(event)

        @kb.add("c-u")
        def vi_half_page_up(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                from prompt_toolkit.key_binding.bindings.scroll import scroll_half_page_up

                scroll_half_page_up(event)

        # Vi: yank (copy)
        @kb.add("y", "y")
        def vi_yank_line(event: KeyPressEvent) -> None:
            if self.view_mode == "section_view":
                line = event.current_buffer.document.current_line
                event.app.clipboard.set_text(line)

        return kb

    def _populate_text_area(self) -> None:
        """Populate text area with Rich-rendered content for section_view."""
        if not self.timeline.blocks or self.selected_card_index >= len(self.timeline.blocks):
            self._text_area.text = "No block selected"
            return

        block = self.timeline.blocks[self.selected_card_index]

        # Get the content for selected section
        if self.selected_section == "input":
            content = block.input_text
        else:
            content = block.output_text or (
                f"Error: {block.error}" if block.error else "(no output)"
            )

        # Render with Rich Markdown
        rendered_content = render_markdown(content)

        # Set the text in the TextArea
        self._text_area.text = rendered_content

    def _create_layout(self) -> Layout:
        """Create the TUI layout with conditional containers for vi mode."""
        # Regular content window (for cards and card_detail views)
        regular_content = Window(
            content=FormattedTextControl(
                text=self._get_content,
                focusable=True,
            ),
        )

        # Vi mode content (for section_view)
        vi_content = self._text_area

        # Conditional containers - switch based on view_mode
        content_container = ConditionalContainer(
            Frame(body=regular_content, title="Commander Monitor"),
            filter=Condition(lambda: self.view_mode != "section_view"),
        )

        vi_container = ConditionalContainer(
            Frame(body=vi_content, title=self._get_vi_title),
            filter=Condition(lambda: self.view_mode == "section_view"),
        )

        # Status bar at bottom
        status_window = Window(
            content=FormattedTextControl(text=self._get_status_bar),
            height=1,
            style="reverse",
        )

        # Main layout with both containers (only one visible at a time)
        root_container = HSplit(
            [
                content_container,
                vi_container,
                status_window,
            ]
        )

        return Layout(root_container)

    def _get_vi_title(self) -> str:
        """Get dynamic title for vi mode frame."""
        if not self.timeline.blocks or self.selected_card_index >= len(self.timeline.blocks):
            return "Section View"

        block = self.timeline.blocks[self.selected_card_index]
        node_display = f"@{block.node_id}" if block.node_id else "python"
        section_name = "Input" if self.selected_section == "input" else "Output"
        return f":::{block.number} {node_display} - {section_name} (Vi Mode)"

    def _get_content(self) -> FormattedText:
        """Get content based on current view mode."""
        if self.view_mode == "cards":
            return self._render_cards_view()
        elif self.view_mode == "card_detail":
            return self._render_card_detail_view()
        else:  # section_view
            return self._render_section_view()

    def _render_cards_view(self) -> FormattedText:
        """Render Level 1: All blocks as cards with input/output sections."""
        if not self.timeline.blocks:
            return FormattedText([("", "No blocks yet. Execute some commands in Commander!\n")])

        lines = []
        for i, block in enumerate(self.timeline.blocks):
            is_selected = i == self.selected_card_index
            card_lines = self._render_card(block, is_selected, truncate=True)
            lines.extend(card_lines)
            # Card already has separator built-in, no extra spacing needed

        return FormattedText(lines)

    def _render_card(self, block: Block, selected: bool, truncate: bool) -> list[tuple[str, str]]:
        """Render a single block as a card.

        Args:
            block: The block to render
            selected: Whether this card is selected
            truncate: Whether to truncate input/output (cards view) or show full (detail view)
        """
        lines = []
        border_style = "reverse" if selected else ""

        # Header: :::N @node status (duration)
        status_emoji = {
            "pending": "⏳",
            "waiting": "⏸️",
            "completed": "✓",
            "error": "✗",
        }.get(block.status, "?")
        node_display = f"@{block.node_id}" if block.node_id else "python"
        duration = f" ({block.duration_ms:.1f}ms)" if block.duration_ms else ""

        lines.append((border_style, f":::{block.number} {node_display} {status_emoji}{duration}\n"))
        lines.append(("", "\n"))  # Spacing after header

        # Input section (with generous spacing)
        lines.append(("", "Input\n"))
        lines.append(("dim", "─────\n"))
        input_content = self._format_section_content(block.input_text, truncate, max_lines=6)
        for line in input_content.split("\n"):
            lines.append(("", f"  {line}\n"))
        lines.append(("", "\n"))  # Spacing between sections

        # Output section (with generous spacing)
        lines.append(("", "Output\n"))
        lines.append(("dim", "──────\n"))
        output_text = block.output_text or (
            f"Error: {block.error}" if block.error else "(no output)"
        )
        output_content = self._format_section_content(output_text, truncate, max_lines=6)
        for line in output_content.split("\n"):
            line_style = "ansired" if block.error else ""
            lines.append((line_style, f"  {line}\n"))
        lines.append(("", "\n"))  # Spacing after output

        # Card separator
        lines.append(("dim", "─" * 70 + "\n"))

        return lines

    def _format_section_content(self, text: str, truncate: bool, max_lines: int = 3) -> str:
        """Format section content with optional truncation.

        Args:
            text: The text to format
            truncate: Whether to truncate
            max_lines: Maximum lines to show when truncating

        Returns:
            Formatted text, possibly with truncation notice
        """
        if not truncate:
            return text

        lines = text.split("\n")
        if len(lines) <= max_lines and len(text) <= 200:
            return text

        # Truncate and add notice
        preview_lines = lines[:max_lines]
        preview_text = "\n".join(preview_lines)

        truncated_chars = len(text) - len(preview_text)
        if truncated_chars > 0:
            preview_text += f"\n ... [Truncated {truncated_chars} characters]"

        return preview_text

    def _render_card_detail_view(self) -> FormattedText:
        """Render Level 2: Single card with full (non-truncated) input/output."""
        if not self.timeline.blocks or self.selected_card_index >= len(self.timeline.blocks):
            return FormattedText([("", "No block selected\n")])

        block = self.timeline.blocks[self.selected_card_index]
        lines = []

        # Header
        status_emoji = {
            "pending": "⏳",
            "waiting": "⏸️",
            "completed": "✓",
            "error": "✗",
        }.get(block.status, "?")
        node_display = f"@{block.node_id}" if block.node_id else "python"
        duration = f" ({block.duration_ms:.1f}ms)" if block.duration_ms else ""

        lines.append(("bold", f":::{block.number} {node_display} {status_emoji}{duration}\n"))
        lines.append(("", "\n"))

        # Input section (with selection highlight on label)
        input_label_style = "reverse" if self.selected_section == "input" else ""
        lines.append((input_label_style, "Input\n"))
        underline_style = "reverse" if self.selected_section == "input" else "dim"
        lines.append((underline_style, "─────\n"))

        # Render input with Markdown
        rendered_input = render_markdown(block.input_text)
        for line in rendered_input.split("\n"):
            lines.append(("", f"  {line}\n"))

        lines.append(("", "\n"))  # Spacing between sections

        # Output section (with selection highlight on label)
        output_label_style = "reverse" if self.selected_section == "output" else ""
        lines.append((output_label_style, "Output\n"))
        underline_style = "reverse" if self.selected_section == "output" else "dim"
        lines.append((underline_style, "──────\n"))

        if block.output_text:
            # Render output with Markdown and syntax highlighting
            rendered_output = render_markdown(block.output_text)
            for line in rendered_output.split("\n"):
                lines.append(("", f"  {line}\n"))
        elif block.error:
            lines.append(("ansired", f"  Error: {block.error}\n"))
        else:
            lines.append(("dim", "  (no output)\n"))

        lines.append(("", "\n"))

        return FormattedText(lines)

    def _render_section_view(self) -> FormattedText:
        """Render Level 3: Single section (input or output) in vim-like viewport."""
        if not self.timeline.blocks or self.selected_card_index >= len(self.timeline.blocks):
            return FormattedText([("", "No block selected\n")])

        block = self.timeline.blocks[self.selected_card_index]
        lines = []

        # Header showing which section we're viewing
        node_display = f"@{block.node_id}" if block.node_id else "python"
        section_name = "Input" if self.selected_section == "input" else "Output"
        lines.append(("bold", f":::{block.number} {node_display} - {section_name}\n"))
        lines.append(("", "═" * 70 + "\n\n"))

        # Get the content
        if self.selected_section == "input":
            content = block.input_text
        else:
            content = block.output_text or (
                f"Error: {block.error}" if block.error else "(no output)"
            )

        # Render with Markdown and syntax highlighting
        rendered_content = render_markdown(content)
        content_lines = rendered_content.split("\n")

        # Apply scroll offset
        visible_lines = content_lines[self.scroll_offset :]

        # Display content
        for line in visible_lines:
            style = "ansired" if block.error and self.selected_section == "output" else ""
            lines.append((style, line + "\n"))

        # Scroll indicator at bottom if there's more content
        if self.scroll_offset > 0:
            lines.append(
                ("dim", f"\n[Scrolled {self.scroll_offset} lines. Press 'k' to scroll up]\n")
            )

        return FormattedText(lines)

    def _get_status_bar(self) -> FormattedText:
        """Render status bar at bottom."""
        if self.view_mode == "cards":
            total = len(self.timeline.blocks)
            current = self.selected_card_index + 1 if total > 0 else 0
            status = f" Card {current}/{total} │ [j/k] Navigate │ [Enter] Open │ [Esc/q] Exit "
        elif self.view_mode == "card_detail":
            section_indicator = f"[{self.selected_section.upper()}]"
            status = f" Card Detail {section_indicator} │ [j/k] Switch │ [Enter] View │ [Ctrl-T] Editor │ [Esc] Back "
        else:  # section_view (Vi Mode)
            status = (
                " Vi Mode │ hjkl:Navigate │ gg/G:Top/Bottom │ w/e/b:Words │ yy:Yank │ [Esc/q] Back "
            )

        return FormattedText([("", status)])

    async def run(self) -> None:
        """Run the monitor application."""
        await self.app.run_async()


async def run_monitor(timeline: Timeline) -> None:
    """Launch the full-screen monitor TUI.

    Args:
        timeline: The Commander timeline to monitor.
    """
    monitor = MonitorApp(timeline=timeline)
    await monitor.run()
