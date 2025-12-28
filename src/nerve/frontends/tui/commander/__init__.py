"""Commander - Unified command center for nerve nodes.

A block-based timeline interface for interacting with nodes.
"""

from nerve.frontends.tui.commander.blocks import Block, Timeline
from nerve.frontends.tui.commander.commander import Commander, run_commander
from nerve.frontends.tui.commander.themes import (
    DEFAULT_THEME,
    DRACULA_THEME,
    MONO_THEME,
    NORD_THEME,
    THEMES,
    create_theme,
    get_theme,
)

__all__ = [
    # Core
    "Commander",
    "run_commander",
    # Blocks
    "Block",
    "Timeline",
    # Themes
    "create_theme",
    "get_theme",
    "THEMES",
    "DEFAULT_THEME",
    "NORD_THEME",
    "DRACULA_THEME",
    "MONO_THEME",
]
