#!/usr/bin/env python3
"""Read and format proxy request/response logs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import rich_click as click
from shared import C, configure_rich_click, is_tool_result_only, print_indented

# Configure rich-click
configure_rich_click()


# =============================================================================
# Helper Functions
# =============================================================================


class OutputConfig:
    """Global output configuration."""

    full_output: bool = False


def truncate(text: str, max_len: int) -> str:
    """Truncate text with clear indicator of remaining chars."""
    if OutputConfig.full_output or len(text) <= max_len:
        return text
    remaining = len(text) - max_len
    return f"{text[:max_len]}\n{C.RED}[TRUNCATED: {remaining} more chars, use --full to see all]{C.RESET}"


def role_color(role: str, content: str | list | dict | None = None) -> str:
    """Get color code for a message role.

    For user messages, returns yellow if content is only tool_result blocks.
    """
    if role == "user" and content is not None:
        if is_tool_result_only(content):
            return C.YELLOW
        return C.GREEN
    return {
        "user": C.GREEN,
        "assistant": C.BLUE,
        "system": C.YELLOW,
    }.get(role, C.YELLOW)


def pretty_json(obj: Any, indent: int = 2) -> str:
    """Format object as pretty JSON string."""
    return json.dumps(obj, indent=indent)


def print_tool_call(name: str, call_id: str, args: str, indent: int = 2) -> None:
    """Print a formatted tool call with its arguments."""
    pad = " " * indent
    print(f"\n{pad}{C.YELLOW}[TOOL: {name}]{C.RESET} id={call_id}")

    if args:
        # Try to pretty-print JSON args
        try:
            args_json = json.loads(args)
            args_str = pretty_json(args_json)
        except json.JSONDecodeError:
            args_str = args

        truncated = truncate(args_str, 1000)
        print_indented(truncated, indent + 2)


# =============================================================================
# Content Formatting
# =============================================================================


def format_tool_result_content(content: str | list | dict) -> str:
    """Extract text from tool result content (can be various formats)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def print_message_content(content: str | list | dict, indent: int = 4, max_len: int = 500) -> None:
    """Print formatted message content (string, list of blocks, or dict)."""
    pad = " " * indent

    if isinstance(content, str):
        print_indented(truncate(content, max_len), indent)
        return

    if isinstance(content, dict):
        print(f"{pad}{pretty_json(content)}")
        return

    if not isinstance(content, list):
        print(f"{pad}{content}")
        return

    # Handle list of content blocks
    for block in content:
        if not isinstance(block, dict):
            print(f"{pad}{block}")
            continue

        block_type = block.get("type", "unknown")

        if block_type == "text":
            print_indented(truncate(block.get("text", ""), max_len), indent)

        elif block_type == "tool_use":
            print_tool_call(
                name=block.get("name", "?"),
                call_id=block.get("id", "?"),
                args=pretty_json(block.get("input", {})),
                indent=indent,
            )

        elif block_type == "tool_result":
            result_text = format_tool_result_content(block.get("content", ""))
            print(f"{pad}{C.YELLOW}[TOOL RESULT]{C.RESET} id={block.get('tool_use_id', '?')}")
            print_indented(truncate(result_text, 300), indent + 2)

        else:
            block_str = pretty_json(block)
            print(f"{pad}{C.DIM}[{block_type}]: {truncate(block_str, 200)}{C.RESET}")


# =============================================================================
# Request Printers
# =============================================================================


def print_anthropic_request(data: dict) -> None:
    """Print formatted Anthropic request."""
    print(f"\n{C.BOLD}{C.CYAN}=== ANTHROPIC REQUEST ==={C.RESET}")
    print(f"{C.DIM}Model:{C.RESET} {data.get('model', '?')}")
    print(f"{C.DIM}Max tokens:{C.RESET} {data.get('max_tokens', '?')}")

    # System prompt
    system = data.get("system", [])
    if system:
        print(f"\n{C.BOLD}System:{C.RESET}")
        if isinstance(system, str):
            print_indented(truncate(system, 200), 2, C.DIM)
        elif isinstance(system, list):
            for block in system:
                if isinstance(block, dict) and block.get("type") == "text":
                    print_indented(truncate(block.get("text", ""), 200), 2, C.DIM)

    # Messages
    messages = data.get("messages", [])
    print(f"\n{C.BOLD}Messages ({len(messages)}):{C.RESET}")
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        print(f"\n  {C.BOLD}[{i + 1}] {role_color(role, content)}{role.upper()}{C.RESET}")
        print_message_content(content, indent=6)

    # Tools
    print_tools_summary(data.get("tools", []))


def print_openai_request(data: dict) -> None:
    """Print formatted OpenAI request."""
    print(f"\n{C.BOLD}{C.MAGENTA}=== OPENAI REQUEST ==={C.RESET}")
    print(f"{C.DIM}Model:{C.RESET} {data.get('model', '?')}")
    print(f"{C.DIM}Max tokens:{C.RESET} {data.get('max_tokens', '?')}")
    print(f"{C.DIM}Temperature:{C.RESET} {data.get('temperature', '?')}")
    print(f"{C.DIM}Stream:{C.RESET} {data.get('stream', False)}")

    messages = data.get("messages", [])
    print(f"\n{C.BOLD}Messages ({len(messages)}):{C.RESET}")
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        print(f"\n  {C.BOLD}[{i + 1}] {role_color(role, content)}{role.upper()}{C.RESET}")

        if isinstance(content, str):
            print_indented(truncate(content, 300), 6)
        else:
            print_message_content(content, indent=6)


def print_tools_summary(tools: list) -> None:
    """Print a summary of available tools."""
    if not tools:
        return

    print(f"\n{C.BOLD}Tools ({len(tools)}):{C.RESET}")
    tools_to_show = tools if OutputConfig.full_output else tools[:5]

    for tool in tools_to_show:
        name = tool.get("name", "?")
        desc = tool.get("description", "")

        if OutputConfig.full_output:
            print(f"  - {C.YELLOW}{name}{C.RESET}:")
            print_indented(desc, 6, C.DIM)
        else:
            desc_short = desc.replace("\n", " ")[:60]
            print(f"  - {C.YELLOW}{name}{C.RESET}: {C.DIM}{desc_short}{C.RESET}")

    remaining = len(tools) - len(tools_to_show)
    if remaining > 0:
        print(f"  {C.RED}[TRUNCATED: {remaining} more tools, use --full to see all]{C.RESET}")


# =============================================================================
# Response Printers
# =============================================================================


def print_response_chunks(chunks: list) -> None:
    """Print formatted response chunks (OpenAI streaming format)."""
    print(f"\n{C.BOLD}{C.GREEN}=== RESPONSE ==={C.RESET}")

    text_parts: list[str] = []
    tool_calls: dict[str, dict[str, str]] = {}  # id -> {name, args}

    for chunk in chunks:
        chunk_type = chunk.get("type", "")
        content = chunk.get("content", "")
        tool_call_id = chunk.get("tool_call_id")

        if chunk_type == "text" and content:
            text_parts.append(content)
        elif chunk_type == "tool_call_start" and tool_call_id:
            tool_calls[tool_call_id] = {
                "name": chunk.get("tool_name") or "?",
                "args": "",
            }
        elif chunk_type == "tool_call_delta" and tool_call_id in tool_calls:
            tool_calls[tool_call_id]["args"] += chunk.get("tool_arguments_delta", "")

    # Print text
    if text_parts:
        full_text = "".join(text_parts)
        print(f"\n{C.BOLD}Text Response:{C.RESET}")
        print_indented(truncate(full_text, 2000), 2)
        print(f"\n{C.DIM}Total: {len(full_text)} chars, {len(chunks)} chunks{C.RESET}")

    # Print tool calls
    print_collected_tool_calls(tool_calls)


def print_sse_response(events: list) -> None:
    """Print formatted SSE response events (Anthropic streaming format)."""
    print(f"\n{C.BOLD}{C.GREEN}=== RESPONSE (SSE) ==={C.RESET}")

    thinking_parts: list[str] = []
    text_parts: list[str] = []
    tool_calls: dict[str, dict[str, str]] = {}  # id -> {name, input}
    current_tool_id: str | None = None
    model: str | None = None
    usage: dict = {}

    for event_str in events:
        if not event_str.startswith("data: "):
            continue

        try:
            data = json.loads(event_str[6:])
        except json.JSONDecodeError:
            continue

        event_type = data.get("type", "")

        if event_type == "message_start":
            model = data.get("message", {}).get("model")

        elif event_type == "content_block_start":
            block = data.get("content_block", {})
            if block.get("type") == "tool_use":
                tool_id = block.get("id", "")
                tool_calls[tool_id] = {"name": block.get("name", "?"), "args": ""}
                current_tool_id = tool_id

        elif event_type == "content_block_delta":
            delta = data.get("delta", {})
            delta_type = delta.get("type")

            if delta_type == "thinking_delta":
                thinking_parts.append(delta.get("thinking", ""))
            elif delta_type == "text_delta":
                text_parts.append(delta.get("text", ""))
            elif delta_type == "input_json_delta" and current_tool_id in tool_calls:
                tool_calls[current_tool_id]["args"] += delta.get("partial_json", "")

        elif event_type == "content_block_stop":
            current_tool_id = None

        elif event_type == "message_delta":
            usage = data.get("usage", {})

    # Print results
    if model:
        print(f"{C.DIM}Model:{C.RESET} {model}")

    if thinking_parts:
        print(f"\n{C.BOLD}Thinking:{C.RESET}")
        print_indented(truncate("".join(thinking_parts), 1000), 2, C.DIM)

    if text_parts:
        print(f"\n{C.BOLD}Text Response:{C.RESET}")
        print_indented(truncate("".join(text_parts), 2000), 2)

    print_collected_tool_calls(tool_calls)

    if usage:
        print(
            f"\n{C.DIM}Usage: {usage.get('input_tokens', 0)} input, {usage.get('output_tokens', 0)} output tokens{C.RESET}"
        )


def print_collected_tool_calls(tool_calls: dict[str, dict[str, str]]) -> None:
    """Print collected tool calls from streaming responses."""
    if not tool_calls:
        return

    print(f"\n{C.BOLD}Tool Calls ({len(tool_calls)}):{C.RESET}")
    for call_id, tc in tool_calls.items():
        print_tool_call(tc["name"], call_id, tc["args"])


# =============================================================================
# File/Directory Handlers
# =============================================================================


def read_log_directory(log_dir: Path) -> None:
    """Read all files in a log directory."""
    print(f"{C.BOLD}Log: {log_dir.name}{C.RESET}")
    print(f"{C.DIM}Path: {log_dir}{C.RESET}")

    # Format 1: proxy-openrouter style
    anthropic_req = log_dir / "1_anthropic_request.json"
    openai_req = log_dir / "2_openai_request.json"
    response_chunks = log_dir / "3_openai_response_chunks.json"

    # Format 2: proxy-glm style
    request = log_dir / "1_request.json"
    response_events = log_dir / "2_response_events.json"

    if anthropic_req.exists():
        with open(anthropic_req, encoding="utf-8") as f:
            print_anthropic_request(json.load(f))
        if openai_req.exists():
            with open(openai_req, encoding="utf-8") as f:
                print_openai_request(json.load(f))
        if response_chunks.exists():
            with open(response_chunks, encoding="utf-8") as f:
                chunks = json.load(f)
                if chunks:
                    print_response_chunks(chunks)
                else:
                    print(f"\n{C.DIM}[No response chunks]{C.RESET}")

    elif request.exists():
        with open(request, encoding="utf-8") as f:
            print_anthropic_request(json.load(f))
        if response_events.exists():
            with open(response_events, encoding="utf-8") as f:
                events = json.load(f)
                if events:
                    print_sse_response(events)
                else:
                    print(f"\n{C.DIM}[No response events]{C.RESET}")
    else:
        print(f"{C.RED}Unknown log format - no recognized files found{C.RESET}")


def read_single_file(file_path: Path) -> None:
    """Read and format a single JSON file."""
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    name = file_path.name
    handlers = {
        "anthropic_request": print_anthropic_request,
        "openai_request": print_openai_request,
        "response_chunks": print_response_chunks,
        "1_request.json": print_anthropic_request,
        "2_response_events.json": print_sse_response,
    }

    for pattern, handler in handlers.items():
        if pattern in name:
            handler(data)
            return

    # Fallback: just print JSON
    print(pretty_json(data))


def list_logs(session_dir: Path) -> None:
    """List all log directories in a session."""
    print(f"{C.BOLD}Session: {session_dir.name}{C.RESET}\n")

    dirs = sorted(d for d in session_dir.iterdir() if d.is_dir())
    for d in dirs:
        parts = d.name.split("_", 3)
        if len(parts) >= 4:
            seq, time, msgs, preview = parts
            print(f"  {C.CYAN}{seq}{C.RESET} {C.DIM}{time}{C.RESET} {msgs:>6} {preview[:40]}")
        else:
            print(f"  {d.name}")

    print(f"\n{C.DIM}Total: {len(dirs)} requests{C.RESET}")


# =============================================================================
# Main
# =============================================================================


@click.command()
@click.argument(
    "path",
    type=click.Path(exists=True, path_type=Path),
    metavar="PATH",
)
@click.option(
    "-f",
    "--full",
    is_flag=True,
    help="Show full content without truncation. By default, long content is truncated.",
)
@click.option(
    "-l",
    "--list",
    "list_logs_flag",
    is_flag=True,
    help="List all request logs in a session directory.",
)
def main(path: Path, full: bool, list_logs_flag: bool) -> None:
    """Read and format proxy request/response logs.

    Parses and pretty-prints proxy log files with syntax highlighting,
    message formatting, and tool call extraction.

    \b
    PATH can be:
      - A log directory (e.g., 001_173039_5msgs_...)
      - A session directory (parent of log directories)
      - A single JSON file (request or response)

    \b
    Supported Formats:
      - Anthropic format (1_request.json, 2_response_events.json)
      - OpenRouter format (1_anthropic_request.json, 2_openai_request.json, etc.)

    \b
    Examples:
      # Read a specific log (truncated output)
      read_proxy_logs.py /path/to/001_173039_5msgs_...

      # Read with full content (no truncation)
      read_proxy_logs.py /path/to/log --full

      # List all requests in a session
      read_proxy_logs.py /path/to/session --list

      # Auto-detect: if path is a session dir, lists logs
      read_proxy_logs.py /path/to/session

    \b
    Output includes:
      - Model and parameters
      - System prompt (truncated)
      - Messages with role coloring
      - Tool calls with arguments
      - Response text and usage stats
    """
    OutputConfig.full_output = full

    if list_logs_flag:
        if path.is_dir():
            list_logs(path)
        else:
            click.echo("Error: --list requires a directory", err=True)
            sys.exit(1)
        return

    if path.is_file():
        read_single_file(path)
    elif path.is_dir():
        is_log_dir = (path / "1_anthropic_request.json").exists() or (
            path / "1_request.json"
        ).exists()
        if is_log_dir:
            read_log_directory(path)
        else:
            list_logs(path)
            click.echo(f"\n{C.DIM}Tip: Pass a specific log directory to see details{C.RESET}")


if __name__ == "__main__":
    main()
