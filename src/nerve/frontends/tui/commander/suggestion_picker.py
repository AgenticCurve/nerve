"""Full-screen suggestion picker for Commander.

Provides a navigable interface to view and select AI-generated suggestions.

Usage:
    Press Ctrl-P in Commander to open picker
    j/k or arrows to navigate
    Enter to select suggestion
    Esc to cancel
"""

from __future__ import annotations

from dataclasses import dataclass, field

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Frame


@dataclass
class SuggestionPickerApp:
    """Full-screen TUI for picking a suggestion.

    Simple list navigation:
    - j/k or arrows to navigate
    - Enter to select
    - Esc to cancel
    """

    suggestions: list[str]

    # Navigation state
    selected_index: int = 0
    selected_suggestion: str | None = field(default=None, init=False)

    # Internal
    _app: Application[None] | None = field(default=None, init=False)

    def _build_list_content(self) -> FormattedText:
        """Build the suggestion list with selection highlight."""
        if not self.suggestions:
            return FormattedText(
                [("class:dim", "No suggestions available.\n\nPress Esc to close.")]
            )

        fragments: list[tuple[str, str]] = []

        # Header
        fragments.append(("class:header", "  AI Suggestions\n"))
        fragments.append(("class:dim", "  ─" * 20 + "\n\n"))

        for i, suggestion in enumerate(self.suggestions):
            if i == self.selected_index:
                # Selected item
                fragments.append(("class:selected", f"  ▸ {suggestion}\n"))
            else:
                # Normal item
                fragments.append(("class:normal", f"    {suggestion}\n"))

        # Footer with instructions
        fragments.append(("class:dim", "\n  ─" * 20 + "\n"))
        fragments.append(("class:dim", "  ↑/↓ or j/k: Navigate  •  Enter: Select  •  Esc: Cancel"))

        return FormattedText(fragments)

    def _create_layout(self) -> Layout:
        """Create the layout with suggestion list."""
        list_control = FormattedTextControl(
            text=self._build_list_content,
            focusable=True,
        )

        list_window = Window(
            content=list_control,
            wrap_lines=True,
        )

        # Wrap in a frame
        root = Frame(
            HSplit([list_window]),
            title="Suggestion Picker (Ctrl-P)",
        )

        return Layout(root)

    def _create_keybindings(self) -> KeyBindings:
        """Create key bindings for navigation."""
        kb = KeyBindings()

        @kb.add("escape")
        @kb.add("c-c")
        @kb.add("c-p")  # Toggle off with same key
        def cancel(event: KeyPressEvent) -> None:
            """Cancel and close picker."""
            self.selected_suggestion = None
            event.app.exit()

        @kb.add("enter")
        def select(event: KeyPressEvent) -> None:
            """Select current suggestion and close."""
            if self.suggestions and 0 <= self.selected_index < len(self.suggestions):
                self.selected_suggestion = self.suggestions[self.selected_index]
            event.app.exit()

        @kb.add("up")
        @kb.add("k")
        def move_up(_event: KeyPressEvent) -> None:
            """Move selection up."""
            if self.suggestions:
                self.selected_index = (self.selected_index - 1) % len(self.suggestions)

        @kb.add("down")
        @kb.add("j")
        def move_down(_event: KeyPressEvent) -> None:
            """Move selection down."""
            if self.suggestions:
                self.selected_index = (self.selected_index + 1) % len(self.suggestions)

        @kb.add("home")
        @kb.add("g")
        def go_top(_event: KeyPressEvent) -> None:
            """Go to first suggestion."""
            if self.suggestions:
                self.selected_index = 0

        @kb.add("end")
        @kb.add("G")
        def go_bottom(_event: KeyPressEvent) -> None:
            """Go to last suggestion."""
            if self.suggestions:
                self.selected_index = len(self.suggestions) - 1

        return kb

    async def run(self) -> str | None:
        """Run the picker and return selected suggestion or None if cancelled."""
        from prompt_toolkit.styles import Style

        style = Style.from_dict(
            {
                "header": "bold cyan",
                "selected": "bold reverse",
                "normal": "",
                "dim": "gray",
            }
        )

        self._app = Application(
            layout=self._create_layout(),
            key_bindings=self._create_keybindings(),
            style=style,
            full_screen=True,
            mouse_support=True,
        )

        await self._app.run_async()
        return self.selected_suggestion


async def run_suggestion_picker(suggestions: list[str]) -> str | None:
    """Run the suggestion picker and return selected suggestion.

    Args:
        suggestions: List of suggestions to display.

    Returns:
        Selected suggestion string, or None if cancelled.
    """
    picker = SuggestionPickerApp(suggestions=suggestions)
    return await picker.run()
