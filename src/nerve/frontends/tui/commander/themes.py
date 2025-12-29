"""Pluggable theme system for Commander TUI.

Themes define colors and styles for all UI elements.
Switch themes by passing a different theme to Console.
"""

from rich.theme import Theme


def create_theme(
    *,
    # Block styles
    block_border: str = "dim",
    block_title: str = "bold cyan",
    block_subtitle: str = "dim",
    # Content styles
    label: str = "bold",
    input_text: str = "white",
    output_text: str = "white",
    error_text: str = "bold red",
    # Node type colors
    node_bash: str = "green",
    node_llm: str = "magenta",
    node_python: str = "yellow",
    # Misc
    timestamp: str = "dim cyan",
    prompt: str = "bold green",
    success: str = "bold green",
    warning: str = "bold yellow",
    # Pending blocks (subdued appearance)
    pending: str = "bright_black",
) -> Theme:
    """Create a theme with the given styles.

    This factory allows easy theme customization while
    ensuring all required styles are defined.
    """
    return Theme(
        {
            # Block frame
            "block.border": block_border,
            "block.title": block_title,
            "block.subtitle": block_subtitle,
            # Content
            "label": label,
            "input": input_text,
            "output": output_text,
            "error": error_text,
            # Node types
            "node.bash": node_bash,
            "node.llm": node_llm,
            "node.python": node_python,
            # Misc
            "timestamp": timestamp,
            "prompt": prompt,
            "success": success,
            "warning": warning,
            # Pending blocks
            "pending": pending,
        }
    )


# =============================================================================
# Built-in Themes
# =============================================================================

# Default theme - clean and minimal
DEFAULT_THEME = create_theme()

# Nord-inspired theme
NORD_THEME = create_theme(
    block_border="#4C566A",
    block_title="#88C0D0",
    block_subtitle="#4C566A",
    label="#E5E9F0",
    input_text="#ECEFF4",
    output_text="#D8DEE9",
    error_text="#BF616A",
    node_bash="#A3BE8C",
    node_llm="#B48EAD",
    node_python="#EBCB8B",
    timestamp="#4C566A",
    prompt="#88C0D0",
    success="#A3BE8C",
    warning="#EBCB8B",
    pending="#4C566A",  # Nord's comment color
)

# Dracula-inspired theme
DRACULA_THEME = create_theme(
    block_border="#6272A4",
    block_title="#8BE9FD",
    block_subtitle="#6272A4",
    label="#F8F8F2",
    input_text="#F8F8F2",
    output_text="#F8F8F2",
    error_text="#FF5555",
    node_bash="#50FA7B",
    node_llm="#FF79C6",
    node_python="#F1FA8C",
    timestamp="#6272A4",
    prompt="#50FA7B",
    success="#50FA7B",
    warning="#FFB86C",
    pending="#6272A4",  # Dracula's comment color
)

# Minimal monochrome theme
MONO_THEME = create_theme(
    block_border="dim",
    block_title="bold",
    block_subtitle="dim",
    label="bold",
    input_text="white",
    output_text="white",
    error_text="bold red",
    node_bash="bold",
    node_llm="bold",
    node_python="bold",
    timestamp="dim",
    prompt="bold",
    success="bold",
    warning="bold yellow",
    pending="bright_black",
)

# Theme registry for easy lookup
THEMES: dict[str, Theme] = {
    "default": DEFAULT_THEME,
    "nord": NORD_THEME,
    "dracula": DRACULA_THEME,
    "mono": MONO_THEME,
}


def get_theme(name: str) -> Theme:
    """Get a theme by name.

    Args:
        name: Theme name (default, nord, dracula, mono)

    Returns:
        The theme, or DEFAULT_THEME if not found.
    """
    return THEMES.get(name.lower(), DEFAULT_THEME)
