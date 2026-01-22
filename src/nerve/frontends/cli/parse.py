"""Parse AI CLI pane output into structured sections.

Standalone tool for parsing Claude Code or Gemini CLI pane output.

Usage:
    # Parse Claude Code pane output from file
    nerve parse --claude-code /tmp/pane_output.txt

    # Parse from stdin
    cat /tmp/pane_output.txt | nerve parse --claude-code

    # Parse from WezTerm pane
    nerve parse --claude-code --pane 42

    # List available WezTerm panes
    nerve parse --list-panes

    # Watch a pane (use watch command)
    watch -n 2 'nerve parse --claude-code --pane 42'

    # Output as JSON
    nerve parse --claude-code --json /tmp/pane_output.txt

    # Show only raw response
    nerve parse --claude-code --raw /tmp/pane_output.txt

    # Show only the last section
    nerve parse --claude-code --last /tmp/pane_output.txt
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

from nerve.core.parsers import get_parser
from nerve.core.types import ParsedResponse, ParserType


def get_wezterm_pane_text(pane_id: str) -> str:
    """Get text content from a WezTerm pane.

    Args:
        pane_id: The WezTerm pane ID.

    Returns:
        The pane's text content.

    Raises:
        RuntimeError: If pane cannot be read.
    """
    cmd = ["wezterm", "cli", "get-text", "--pane-id", pane_id, "--start-line", "-50000"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to read pane {pane_id}: {result.stderr}")
        return result.stdout
    except FileNotFoundError as err:
        raise RuntimeError("wezterm CLI not found. Is WezTerm installed?") from err


def list_wezterm_panes() -> list[dict[str, Any]]:
    """List all WezTerm panes.

    Returns:
        List of pane info dicts with pane_id, title, cwd, etc.
    """
    try:
        result = subprocess.run(
            ["wezterm", "cli", "list", "--format", "json"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            panes: list[dict[str, Any]] = json.loads(result.stdout)
            return panes
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def format_pane_list(panes: list[dict[str, Any]]) -> str:
    """Format pane list for display.

    Args:
        panes: List of pane info dicts.

    Returns:
        Formatted string for terminal display.
    """
    if not panes:
        return "No WezTerm panes found. Is WezTerm running?"

    lines = ["WezTerm Panes:", "=" * 60]
    for pane in panes:
        pane_id = pane.get("pane_id", "?")
        title = pane.get("title", "")
        cwd = pane.get("cwd", "")
        # Truncate long paths
        if len(cwd) > 40:
            cwd = "..." + cwd[-37:]
        lines.append(f"  [{pane_id}] {title[:30]:<30} {cwd}")
    return "\n".join(lines)


def parse_pane_output(
    content: str,
    parser_type: ParserType = ParserType.CLAUDE_CODE,
) -> ParsedResponse:
    """Parse pane output into structured response.

    Args:
        content: Raw text content from CLI pane output.
        parser_type: Parser type (CLAUDE_CODE, GEMINI, or NONE).

    Returns:
        ParsedResponse with sections and metadata.
    """
    parser = get_parser(parser_type)
    return parser.parse(content)


def format_json(response: ParsedResponse) -> str:
    """Format response as JSON.

    Args:
        response: Parsed response.

    Returns:
        JSON string.
    """
    data = {
        "raw": response.raw,
        "tokens": response.tokens,
        "sections": [
            {
                "type": section.type,
                "content": section.content,
                **({"tool": section.tool} if section.tool else {}),
                **({"args": section.args} if section.args else {}),
                **({"result": section.result} if section.result else {}),
            }
            for section in response.sections
        ],
    }
    return json.dumps(data, indent=2)


def format_pretty(
    response: ParsedResponse,
    source: str = "stdin",
    full: bool = False,
) -> str:
    """Format response for human reading.

    Args:
        response: Parsed response.
        source: Source description (file path or "stdin").
        full: Show full content without truncation.

    Returns:
        Formatted string.
    """
    lines = [
        f"Source: {source}",
        f"Tokens: {response.tokens or 'N/A'}",
        "=" * 60,
    ]

    if response.sections:
        for i, section in enumerate(response.sections, 1):
            lines.append(f"\n[Section {i}: {section.type.upper()}]")

            if section.type == "tool_call":
                lines.append(f"Tool: {section.tool or 'N/A'}")
                args = section.args or ""
                result = section.result or ""
                if full:
                    lines.append(f"Args: {args}")
                    lines.append(f"Result: {result}")
                else:
                    lines.append(f"Args: {args[:100]}..." if len(args) > 100 else f"Args: {args}")
                    lines.append(
                        f"Result: {result[:200]}..." if len(result) > 200 else f"Result: {result}"
                    )
            else:
                content = section.content
                if full:
                    lines.append(content)
                else:
                    if len(content) > 500:
                        lines.append(content[:500])
                        lines.append(f"... ({len(content)} chars total)")
                    else:
                        lines.append(content)
    else:
        lines.append("\n[No structured sections found]")
        raw = response.raw
        if full:
            lines.append(raw if raw else "(empty)")
        else:
            lines.append(raw[:500] if raw else "(empty)")

    return "\n".join(lines)


def read_input(file_path: str | None = None) -> tuple[str, str]:
    """Read input from file or stdin.

    Args:
        file_path: Path to file, or None for stdin.

    Returns:
        Tuple of (content, source_description).
    """
    if file_path:
        with open(file_path) as f:
            return f.read(), f"file: {file_path}"
    else:
        if sys.stdin.isatty():
            print("Reading from stdin (Ctrl+D to end)...", file=sys.stderr)
        return sys.stdin.read(), "stdin"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for parse command.

    Args:
        argv: Command line arguments (uses sys.argv if None).

    Returns:
        Exit code (0 for success).
    """
    parser = argparse.ArgumentParser(
        description="Parse AI CLI pane output into structured sections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    nerve parse --claude-code pane.txt      # Parse Claude Code pane output
    nerve parse --claude-code --json pane.txt   # JSON output
    cat pane.txt | nerve parse --claude-code    # From stdin
    nerve parse --claude-code -l pane.txt   # Last section only
    nerve parse --gemini pane.txt           # Parse Gemini output
    nerve parse --claude-code --pane 42     # Parse from WezTerm pane
    nerve parse --list-panes                # List available panes
        """,
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="File containing CLI pane output (stdin if not provided)",
    )
    parser.add_argument(
        "--claude-code",
        "-c",
        action="store_true",
        help="Parse Claude Code CLI pane output",
    )
    parser.add_argument(
        "--gemini",
        "-g",
        action="store_true",
        help="Parse Gemini CLI pane output",
    )
    parser.add_argument(
        "--pane",
        "-p",
        metavar="ID",
        help="WezTerm pane ID to parse from",
    )
    parser.add_argument(
        "--list-panes",
        "-P",
        action="store_true",
        help="List available WezTerm panes",
    )
    parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--raw",
        "-r",
        action="store_true",
        help="Show only raw response (no sections)",
    )
    parser.add_argument(
        "--last",
        "-l",
        action="store_true",
        help="Show only the last section's content",
    )
    parser.add_argument(
        "--full",
        "-F",
        action="store_true",
        help="Show full content without truncation",
    )

    args = parser.parse_args(argv)

    # Handle --list-panes
    if args.list_panes:
        panes = list_wezterm_panes()
        print(format_pane_list(panes))
        return 0

    # Determine parser type
    if args.claude_code and args.gemini:
        print("Error: Cannot specify both --claude-code and --gemini", file=sys.stderr)
        return 1
    elif args.gemini:
        parser_type = ParserType.GEMINI
    elif args.claude_code:
        parser_type = ParserType.CLAUDE_CODE
    else:
        # Default to Claude Code if no parser specified
        parser_type = ParserType.CLAUDE_CODE

    # Read input
    try:
        if args.pane:
            content = get_wezterm_pane_text(args.pane)
            source = f"pane: {args.pane}"
        else:
            content, source = read_input(args.file)
    except FileNotFoundError:
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error reading input: {e}", file=sys.stderr)
        return 1

    # Parse
    response = parse_pane_output(content, parser_type)

    # Output
    if args.json:
        print(format_json(response))
    elif args.raw:
        print(response.raw)
    elif args.last:
        if response.sections:
            print(response.sections[-1].content)
        else:
            print(response.raw)
    else:
        print(format_pretty(response, source, args.full))

    return 0


if __name__ == "__main__":
    sys.exit(main())
