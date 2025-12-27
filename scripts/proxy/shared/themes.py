"""Color themes for prompt_toolkit TUI applications."""

from prompt_toolkit.styles import Style

# Dracula theme colors
DRACULA = {
    "bg": "#282a36",
    "bg_hl": "#44475a",
    "fg": "#f8f8f2",
    "comment": "#6272a4",
    "cyan": "#8be9fd",
    "green": "#50fa7b",
    "orange": "#ffb86c",
    "pink": "#ff79c6",
    "purple": "#bd93f9",
    "red": "#ff5555",
    "yellow": "#f1fa8c",
    "blue": "#6272f4",
}

# Light theme colors
LIGHT = {
    "bg": "#f8f8f2",
    "bg_hl": "#e2e2dc",
    "fg": "#282a36",
    "comment": "#6272a4",
    "cyan": "#0097a7",
    "green": "#2e7d32",
    "orange": "#ef6c00",
    "pink": "#c2185b",
    "purple": "#7c4dff",
    "red": "#d32f2f",
    "yellow": "#f9a825",
    "blue": "#1565c0",
}


def get_colors(dark: bool = True) -> dict[str, str]:
    """Get color palette for the given theme."""
    return DRACULA if dark else LIGHT


def get_style(dark: bool = True) -> Style:
    """Get prompt_toolkit Style for the given theme."""
    c = get_colors(dark)
    return Style.from_dict(
        {
            "": c["fg"],
            "header": f"bold {c['purple']}",
            "header-info": c["cyan"],
            "header-dim": c["comment"],
            "breadcrumb": f"bold {c['orange']}",
            "breadcrumb-dim": c["comment"],
            "separator": c["comment"],
            "selected": f"bold {c['bg']} bg:{c['purple']}",
            "turn-number": f"bold {c['pink']}",
            "turn-dim": c["comment"],
            "user-label": f"bold {c['green']}",
            "user-input": c["green"],
            "user-input-dim": c["comment"],
            "assistant-label": f"bold {c['cyan']}",
            "assistant": c["cyan"],
            "tool-summary": c["yellow"],
            "tool-icon": c["orange"],
            "tool-name": f"bold {c['orange']}",
            "tool-section": c["yellow"],
            "tool-count": c["purple"],
            "label": f"bold {c['pink']}",
            "arg-name": c["cyan"],
            "arg-value": c["fg"],
            "success": c["green"],
            "error": c["red"],
            "key": f"bold {c['purple']}",
            "key-desc": c["comment"],
            "search-box": f"{c['fg']} bg:{c['bg_hl']}",
            "search-label": f"bold {c['cyan']}",
            "search-mode": c["orange"],
            "match": f"bold {c['bg']} bg:{c['yellow']}",
            "no-match": c["red"],
            "section-header": f"bold {c['pink']}",
            "section-border": c["purple"],
            "thinking-text": c["comment"],
            "file-path": c["blue"],
            "file-name": c["orange"],
            # Additional styles for visualize_files.py
            "dim": c["comment"],
            "tree": c["purple"],
            "dir": f"bold {c['cyan']}",
            "dir-collapsed": f"bold {c['yellow']}",
            "file": c["fg"],
            "read": c["green"],
            "write": c["orange"],
            "both": c["pink"],
            "info": c["cyan"],
            "count": c["yellow"],
            "match-selected": f"bold {c['bg']} bg:{c['yellow']}",
        }
    )
