"""Result handling utilities for Commander TUI.

Provides consistent handling of node execution results, updating blocks
with success/error states, output, and metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.frontends.tui.commander.blocks import Block


def update_block_from_result(
    block: Block,
    result: dict[str, Any],
    duration_ms: float,
    metadata: dict[str, str] | None = None,
) -> None:
    """Update a block from a node execution result.

    Handles the common pattern of checking result["success"] and updating
    block status, output, error, and metadata accordingly.

    Args:
        block: The block to update.
        result: Result dict from node execution with "success", "output",
                "error", "error_type" keys.
        duration_ms: Execution duration in milliseconds.
        metadata: Optional metadata to add to block (e.g., executed_node_id).
    """
    block.duration_ms = duration_ms
    block.raw = result

    if result.get("success"):
        block.status = "completed"
        block.output_text = str(result.get("output", "")).strip()
        block.error = None
    else:
        block.status = "error"
        error_msg = result.get("error", "Unknown error")
        error_type = result.get("error_type", "unknown")
        block.error = f"[{error_type}] {error_msg}"

    if metadata:
        block.metadata.update(metadata)


def format_error(error_type: str, error_msg: str) -> str:
    """Format an error message with type prefix.

    Args:
        error_type: Type of error (e.g., "execution", "timeout").
        error_msg: The error message.

    Returns:
        Formatted error string: "[error_type] error_msg"
    """
    return f"[{error_type}] {error_msg}"
