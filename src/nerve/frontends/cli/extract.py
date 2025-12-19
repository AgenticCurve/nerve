"""Extract and parse AI CLI responses.

Standalone tool for extracting structured responses from
Claude Code or Gemini CLI output.

Usage:
    # Extract from file
    nerve extract /tmp/output.txt

    # Extract from stdin
    cat /tmp/output.txt | nerve extract

    # Output as JSON
    nerve extract --json /tmp/output.txt

    # Show only raw response
    nerve extract --raw /tmp/output.txt

    # Show only the last section
    nerve extract --last /tmp/output.txt
"""

from __future__ import annotations

import argparse
import json
import sys

from nerve.core.parsers import get_parser
from nerve.core.types import ParsedResponse, ParserType


def extract_response(
    content: str,
    parser_type: ParserType = ParserType.CLAUDE,
) -> ParsedResponse:
    """Extract structured response from CLI output.

    Args:
        content: Raw text content from CLI output.
        parser_type: Parser type (CLAUDE, GEMINI, or NONE).

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
    """CLI entry point for extract command.

    Args:
        argv: Command line arguments (uses sys.argv if None).

    Returns:
        Exit code (0 for success).
    """
    parser = argparse.ArgumentParser(
        description="Extract structured responses from AI CLI output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    nerve extract output.txt          # Pretty print from file
    nerve extract --json output.txt   # JSON output
    cat output.txt | nerve extract    # From stdin
    nerve extract -l output.txt       # Last section only
    nerve extract -t gemini out.txt   # Parse Gemini output
        """,
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="File containing CLI output (stdin if not provided)",
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
    parser.add_argument(
        "--type",
        "-t",
        choices=["claude", "gemini"],
        default="claude",
        help="CLI type to parse (default: claude)",
    )

    args = parser.parse_args(argv)

    # Read input
    try:
        content, source = read_input(args.file)
    except FileNotFoundError:
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error reading input: {e}", file=sys.stderr)
        return 1

    # Parse
    parser_type = ParserType.CLAUDE if args.type == "claude" else ParserType.GEMINI
    response = extract_response(content, parser_type)

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
