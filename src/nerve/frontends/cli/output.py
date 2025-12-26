"""Output formatting utilities for CLI commands."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any, NoReturn

import rich_click as click

if TYPE_CHECKING:
    from collections.abc import Callable


def print_table(
    headers: list[str],
    rows: list[list[str]],
    widths: list[int] | None = None,
    separator_width: int = 70,
) -> None:
    """Print a formatted table with headers.

    Args:
        headers: Column header strings
        rows: List of rows, each row is a list of cell values
        widths: Optional column widths. If None, uses header lengths.
        separator_width: Width of the separator line
    """
    if widths is None:
        widths = [len(h) for h in headers]

    # Build format string
    fmt_parts = []
    for i, width in enumerate(widths):
        if i == len(widths) - 1:
            # Last column doesn't need padding
            fmt_parts.append("{}")
        else:
            fmt_parts.append(f"{{:<{width}}}")
    fmt = " ".join(fmt_parts)

    # Print header
    click.echo(fmt.format(*headers))
    click.echo("-" * separator_width)

    # Print rows
    for row in rows:
        # Ensure row has enough elements
        padded_row = list(row) + [""] * (len(headers) - len(row))
        click.echo(fmt.format(*padded_row[: len(headers)]))


def output_json(data: Any, indent: int = 2) -> None:
    """Output data as formatted JSON."""
    click.echo(json.dumps(data, indent=indent))


def output_json_or_table(
    data: Any,
    json_flag: bool,
    table_fn: Callable[[], None],
) -> None:
    """Output as JSON if flag is set, otherwise call table function.

    Args:
        data: Data to output as JSON
        json_flag: If True, output as JSON
        table_fn: Function to call for table output
    """
    if json_flag:
        output_json(data)
    else:
        table_fn()


def error_exit(message: str, code: int = 1) -> NoReturn:
    """Print error message and exit with code."""
    click.echo(f"Error: {message}", err=True)
    sys.exit(code)


def error_print(message: str) -> None:
    """Print error message without exiting."""
    click.echo(f"Error: {message}", err=True)


def format_history_entry(entry: dict[str, Any]) -> str:
    """Format a single history entry for display.

    Args:
        entry: History entry dict with op, seq, ts, etc.

    Returns:
        Formatted string for display
    """
    seq = entry.get("seq", "?")
    op_type = entry.get("op", "unknown")
    ts = entry.get("ts", entry.get("ts_start", ""))

    # Format timestamp for display (just time portion)
    if ts:
        ts_display = ts.split("T")[1][:8] if "T" in ts else ts[:8]
    else:
        ts_display = ""

    if op_type == "send":
        input_text = entry.get("input", "")[:50]
        response = entry.get("response", {})
        sections = response.get("sections", [])
        section_count = len(sections)
        return f"[{seq:3}] {ts_display} SEND    {input_text!r} -> {section_count} sections"
    elif op_type == "send_stream":
        input_text = entry.get("input", "")[:50]
        return f"[{seq:3}] {ts_display} STREAM  {input_text!r}"
    elif op_type == "run":
        cmd = entry.get("input", "")[:50]
        return f"[{seq:3}] {ts_display} RUN     {cmd!r}"
    elif op_type == "write":
        data_str = entry.get("input", "")[:30].replace("\n", "\\n")
        return f"[{seq:3}] {ts_display} WRITE   {data_str!r}"
    elif op_type == "read":
        lines_count = entry.get("lines", 0)
        buffer_len = len(entry.get("buffer", ""))
        return f"[{seq:3}] {ts_display} READ    {lines_count} lines, {buffer_len} chars"
    elif op_type == "interrupt":
        return f"[{seq:3}] {ts_display} INTERRUPT"
    elif op_type == "delete":
        reason = entry.get("reason", "")
        return f"[{seq:3}] {ts_display} DELETE  {reason or ''}"
    else:
        return f"[{seq:3}] {ts_display} {op_type.upper()}"


def print_history_entries(entries: list[dict[str, Any]]) -> None:
    """Print formatted history entries."""
    for entry in entries:
        click.echo(format_history_entry(entry))


def print_history_summary(
    entries: list[dict[str, Any]],
    node_name: str,
    server_name: str,
    session_name: str,
) -> None:
    """Print history summary statistics."""
    ops_count: dict[str, int] = {}
    for entry in entries:
        op_type = entry.get("op", "unknown")
        ops_count[op_type] = ops_count.get(op_type, 0) + 1

    click.echo(f"Node: {node_name}")
    click.echo(f"Server: {server_name}")
    click.echo(f"Session: {session_name}")
    click.echo(f"Total entries: {len(entries)}")
    click.echo("\nOperations:")
    for op_name, count in sorted(ops_count.items()):
        click.echo(f"  {op_name}: {count}")


# =============================================================================
# REPL-compatible versions (use print instead of click.echo)
# =============================================================================


def print_table_repl(
    headers: list[str],
    rows: list[list[str]],
    widths: list[int] | None = None,
    separator_width: int = 40,
) -> None:
    """Print a formatted table with headers (REPL version using print)."""
    if widths is None:
        widths = [len(h) for h in headers]

    # Build format string
    fmt_parts = []
    for i, width in enumerate(widths):
        if i == len(widths) - 1:
            fmt_parts.append("{}")
        else:
            fmt_parts.append(f"{{:<{width}}}")
    fmt = " ".join(fmt_parts)

    # Print header
    print(fmt.format(*headers))
    print("-" * separator_width)

    # Print rows
    for row in rows:
        padded_row = list(row) + [""] * (len(headers) - len(row))
        print(fmt.format(*padded_row[: len(headers)]))
