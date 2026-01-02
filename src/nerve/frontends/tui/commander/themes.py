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
    node_graph: str = "cyan",
    node_python: str = "yellow",
    node_workflow: str = "blue",
    # Misc
    timestamp: str = "dim cyan",
    prompt: str = "bold green",
    success: str = "bold green",
    warning: str = "bold yellow",
    # Pending blocks (subdued appearance)
    pending: str = "bright_black",
    # Ghost text (suggestions/placeholders) - prompt_toolkit compatible color
    ghost_text: str = "#6e6e6e",
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
            "node.graph": node_graph,
            "node.python": node_python,
            "node.workflow": node_workflow,
            # Misc
            "timestamp": timestamp,
            "prompt": prompt,
            "success": success,
            "warning": warning,
            # Pending blocks
            "pending": pending,
            # Ghost text (for prompt_toolkit - stored here for theme consistency)
            "ghost": ghost_text,
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
    node_graph="#88C0D0",  # Nord frost cyan - subtle distinction
    node_python="#EBCB8B",
    node_workflow="#81A1C1",  # Nord frost blue
    timestamp="#4C566A",
    prompt="#88C0D0",
    success="#A3BE8C",
    warning="#EBCB8B",
    pending="#4C566A",  # Nord's comment color
    ghost_text="#4C566A",  # Nord comment gray
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
    node_graph="#8BE9FD",  # Dracula cyan - subtle distinction
    node_python="#F1FA8C",
    node_workflow="#BD93F9",  # Dracula purple
    timestamp="#6272A4",
    prompt="#50FA7B",
    success="#50FA7B",
    warning="#FFB86C",
    pending="#6272A4",  # Dracula's comment color
    ghost_text="#6272A4",  # Dracula comment purple-gray
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
    node_graph="bold",  # Same as nodes for true transparency
    node_python="bold",
    node_workflow="bold",
    timestamp="dim",
    prompt="bold",
    success="bold",
    warning="bold yellow",
    pending="bright_black",
    ghost_text="#555555",  # Dark gray for mono
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


# Ghost text colors for prompt_toolkit (intentionally separate from Rich theme).
#
# Why duplicated? Rich Theme stores Style objects with complex attributes (bold,
# italic, color, bgcolor, etc.), but prompt_toolkit needs simple hex color strings.
# Extracting hex from Rich Style objects is fragile (color may be named, RGB tuple,
# or None). Maintaining explicit hex values here ensures prompt_toolkit compatibility.
#
# These values MUST match the ghost_text parameter in each theme's create_theme() call.
GHOST_TEXT_COLORS: dict[str, str] = {
    "default": "#6e6e6e",  # Medium gray - visible but clearly different
    "nord": "#4C566A",  # Nord comment gray
    "dracula": "#6272A4",  # Dracula comment purple-gray
    "mono": "#555555",  # Dark gray
}


def get_ghost_text_color(theme_name: str) -> str:
    """Get the ghost text color for a theme (prompt_toolkit compatible).

    Note: This returns a hex color string for prompt_toolkit, which requires
    simple color values. Rich Theme stores Style objects which aren't directly
    compatible with prompt_toolkit's style system.

    Args:
        theme_name: Theme name (default, nord, dracula, mono)

    Returns:
        Hex color string for ghost text, e.g. "#6e6e6e"
    """
    return GHOST_TEXT_COLORS.get(theme_name.lower(), GHOST_TEXT_COLORS["default"])
