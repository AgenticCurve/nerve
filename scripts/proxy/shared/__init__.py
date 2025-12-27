"""Shared utilities for proxy log analysis scripts."""

from .cli import configure_rich_click
from .colors import C
from .formatting import print_indented, truncate, truncate_oneline, truncate_with_count
from .models import FileOperation, ToolCall
from .parsing import (
    extract_text,
    extract_thinking,
    extract_tool_calls,
    extract_tool_results,
    get_blocks,
    is_tool_result_only,
    load_request_file,
)
from .themes import DRACULA, LIGHT, get_colors, get_style

__all__ = [
    # colors
    "C",
    # themes
    "DRACULA",
    "LIGHT",
    "get_colors",
    "get_style",
    # cli
    "configure_rich_click",
    # formatting
    "print_indented",
    "truncate",
    "truncate_oneline",
    "truncate_with_count",
    # models
    "FileOperation",
    "ToolCall",
    # parsing
    "get_blocks",
    "extract_text",
    "extract_tool_calls",
    "extract_tool_results",
    "extract_thinking",
    "is_tool_result_only",
    "load_request_file",
]
