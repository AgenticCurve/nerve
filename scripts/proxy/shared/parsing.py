"""Shared parsing utilities for Anthropic message format."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def get_blocks(content: list | str, block_type: str) -> list[dict]:
    """Extract blocks of a specific type from message content.

    Args:
        content: Message content (list of blocks or string).
        block_type: Type of block to extract (e.g., "text", "tool_use", "tool_result").

    Returns:
        List of block dicts matching the type.
    """
    if isinstance(content, str):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == block_type]


def extract_text(content: list | str) -> str:
    """Extract text content, filtering system reminders.

    Args:
        content: Message content.

    Returns:
        Combined text from text blocks, excluding system reminders.
    """
    if isinstance(content, str):
        text = content.strip()
        return "" if text.startswith("<system-reminder>") else text
    texts = [
        b.get("text", "").strip()
        for b in get_blocks(content, "text")
        if not b.get("text", "").strip().startswith("<system-reminder>")
    ]
    return "\n".join(texts)


def extract_tool_calls(content: list | str) -> list[dict]:
    """Extract tool_use blocks from content.

    Args:
        content: Message content.

    Returns:
        List of dicts with name, id, and input for each tool call.
    """
    return [
        {"name": b.get("name", "?"), "id": b.get("id", ""), "input": b.get("input", {})}
        for b in get_blocks(content, "tool_use")
    ]


def extract_tool_results(content: list | str) -> dict[str, str]:
    """Extract tool_result blocks, mapping tool_use_id to result text.

    Args:
        content: Message content.

    Returns:
        Dict mapping tool_use_id to result text.
    """
    results = {}
    for b in get_blocks(content, "tool_result"):
        rc = b.get("content", "")
        if isinstance(rc, str):
            result_text = rc
        elif isinstance(rc, list):
            result_text = "\n".join(
                x.get("text", "") for x in rc if isinstance(x, dict) and x.get("type") == "text"
            )
        else:
            result_text = str(rc)
        results[b.get("tool_use_id", "")] = result_text
    return results


def extract_thinking(content: list | str) -> list[str]:
    """Extract thinking blocks from content.

    Args:
        content: Message content.

    Returns:
        List of thinking text strings.
    """
    return [b.get("thinking", "") for b in get_blocks(content, "thinking") if b.get("thinking")]


def is_tool_result_only(content: str | list | dict[str, Any]) -> bool:
    """Check if user message content is only tool_result blocks (no actual user text).

    This detects messages that are just tool results being passed back,
    not actual user input.

    Args:
        content: Message content to check.

    Returns:
        True if the content contains no real text (excluding system reminders).
    """
    if isinstance(content, str):
        text = content.strip()
        return not text or text.startswith("<system-reminder>")

    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "").strip()
                if text and not text.startswith("<system-reminder>"):
                    return False
        return True

    return False


def load_request_file(log_dir: Path) -> dict | None:
    """Load request JSON from log directory, handling multiple file formats.

    Supports:
    - 1_request.json (Anthropic direct)
    - 1_anthropic_request.json (OpenRouter format)
    - 1_messages.json (messages-only format)

    Args:
        log_dir: Path to log directory.

    Returns:
        Parsed JSON dict, or None if no request file found.
    """
    for name in ["1_request.json", "1_anthropic_request.json"]:
        path = log_dir / name
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)

    # Also check for messages-only format
    messages_file = log_dir / "1_messages.json"
    if messages_file.exists():
        with open(messages_file, encoding="utf-8") as f:
            return {"messages": json.load(f)}

    return None
