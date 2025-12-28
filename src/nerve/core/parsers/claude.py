"""Claude Code CLI output parser.

Parses Claude Code's terminal output into structured sections.

Output Structure:
    - User prompt: "> " followed by user input
    - Thinking: "∴ Thinking…" followed by indented content
    - Tool calls: "⏺ ToolName(args)" with results starting with "⎿"
    - Text response: "⏺ " followed by regular text
    - Ready state: "-- INSERT --" with empty ">" prompt
"""

from __future__ import annotations

import logging
import re

from nerve.core.parsers.base import Parser
from nerve.core.types import ParsedResponse, Section

logger = logging.getLogger(__name__)


class ClaudeParser(Parser):
    """Parser for Claude Code CLI output.

    Parses the terminal output format used by Claude Code,
    extracting thinking blocks, tool calls, and text responses.

    Example:
        >>> parser = ClaudeParser()
        >>>
        >>> if parser.is_ready(content):
        ...     response = parser.parse(content)
        ...     for section in response.sections:
        ...         if section.type == "tool_call":
        ...             print(f"Tool: {section.metadata['tool']}")
    """

    def is_ready(self, content: str) -> bool:
        """Check if Claude is ready for input.

        Simple logic: if "esc to interrupt" is NOT in the last 50 lines,
        Claude is done processing.

        Args:
            content: Terminal output to check.

        Returns:
            True if Claude is waiting for input.
        """
        lines = content.strip().split("\n")
        if len(lines) < 3:
            return False

        # Check bottom 50 lines
        check_lines = lines[-50:] if len(lines) > 50 else lines

        # If "esc to interrupt" or "esc to cancel" is present, still processing
        for line in check_lines:
            line_lower = line.lower()
            if "esc to interrupt" in line_lower or "esc to cancel" in line_lower:
                return False

        return True

    def parse(self, content: str) -> ParsedResponse:
        """Parse Claude output into structured response.

        Args:
            content: Terminal output to parse.

        Returns:
            ParsedResponse with sections.
        """
        raw = self._extract_response(content)
        sections = self._parse_sections(raw)
        tokens = self._extract_tokens(content)
        is_ready = self.is_ready(content)

        # Count section types for logging
        section_counts: dict[str, int] = {}
        for s in sections:
            section_counts[s.type] = section_counts.get(s.type, 0) + 1

        logger.debug(
            "parse_complete: sections=%d, types=%s, tokens=%s, is_ready=%s, raw_len=%d",
            len(sections),
            section_counts,
            tokens,
            is_ready,
            len(raw),
        )

        return ParsedResponse(
            raw=raw,
            sections=tuple(sections),
            is_complete=True,
            is_ready=is_ready,
            tokens=tokens,
        )

    def _extract_response(self, content: str) -> str:
        """Extract response between last user prompt and current prompt.

        Handles two cases:
        1. Normal: line starting with "> " followed by actual content
        2. Auto-compacted: "Conversation compacted" separator line
        """
        lines = content.split("\n")

        # First, check for compaction separator (takes precedence)
        # Real compaction lines start with ─ (box drawing char) like:
        # ──── Conversation compacted ────────────────────────────────
        compaction_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("─") and "conversation compacted" in stripped.lower():
                compaction_idx = i

        # Find last user prompt ("> " followed by actual text, not suggestions)
        last_prompt_idx = -1
        for i, line in enumerate(lines):
            if line.startswith("> ") and len(line.strip()) > 1:
                if "(tab to accept)" not in line:
                    last_prompt_idx = i

        # Determine start point
        if compaction_idx > last_prompt_idx:
            # Compaction happened after last prompt - use compaction as start
            start_idx = compaction_idx
        elif last_prompt_idx != -1:
            # Normal case - use last prompt
            start_idx = last_prompt_idx
        else:
            # Fallback: if content starts with Claude response markers, use beginning
            # Markers must be first character of line (no leading whitespace)
            for i, line in enumerate(lines):
                if line.startswith("∴") or line.startswith("⏺"):
                    start_idx = i - 1
                    break
            else:
                return ""

        # Find end (empty prompt before status line)
        # Status lines start with "-- INSERT --" or "⏵⏵" (after stripping whitespace)
        end_idx = len(lines)
        for i in range(len(lines) - 1, start_idx, -1):
            stripped_line = lines[i].strip()
            if stripped_line.startswith("-- INSERT --") or stripped_line.startswith("⏵⏵"):
                for j in range(i - 1, max(start_idx, i - 10), -1):
                    stripped = lines[j].strip()
                    if stripped == ">" or stripped == "> ":
                        end_idx = j
                        # Also skip dash line before prompt if present
                        if j > start_idx and self._is_dash_line(lines[j - 1].strip()):
                            end_idx = j - 1
                        break
                    if stripped.startswith(">") and "(tab to accept)" in stripped:
                        end_idx = j
                        # Also skip dash line before prompt if present
                        if j > start_idx and self._is_dash_line(lines[j - 1].strip()):
                            end_idx = j - 1
                        break
                break

        response_lines = lines[start_idx + 1 : end_idx]

        # Strip trailing prompt/status area (dash line followed by ">")
        response_lines = self._strip_trailing_prompt(response_lines)

        return "\n".join(response_lines)

    def _strip_trailing_prompt(self, lines: list[str]) -> list[str]:
        """Strip trailing prompt/status area from response.

        Strips these patterns from the end:
        1. Dash line followed by ">" (prompt separator)
        2. Rating prompt ("How is Claude doing this session?")

        Args:
            lines: Response lines to process.

        Returns:
            Lines with trailing prompt area removed.
        """
        if len(lines) < 2:
            return lines

        # First, strip rating prompt if present at the end
        lines = self._strip_rating_prompt(lines)

        # Then, strip dash line + ">" pattern
        for i in range(len(lines) - 1, 0, -1):
            line = lines[i].strip()
            prev_line = lines[i - 1].strip()

            # Check if current line starts with ">" and previous is all dashes
            if line.startswith(">") and self._is_dash_line(prev_line):
                # Found the pattern - return everything before the dash line
                return lines[: i - 1]

        return lines

    def _strip_rating_prompt(self, lines: list[str]) -> list[str]:
        """Strip Claude rating prompt from end of response.

        Removes lines like:
        ● How is Claude doing this session? (optional)
          1: Bad    2: Fine   3: Good   0: Dismiss

        Args:
            lines: Response lines to process.

        Returns:
            Lines with rating prompt removed.
        """
        if len(lines) < 2:
            return lines

        # Search from the end for the rating prompt marker
        for i in range(len(lines) - 1, max(0, len(lines) - 20), -1):
            line = lines[i].strip()
            if "How is Claude doing this session" in line:
                # Found rating prompt - return everything before it
                return lines[:i]

        return lines

    def _is_dash_line(self, line: str) -> bool:
        """Check if a line is primarily horizontal dashes.

        Args:
            line: Line to check.

        Returns:
            True if line is mostly dash characters (─).
        """
        if not line:
            return False
        # Count dash characters (box drawing horizontal line)
        dash_count = line.count("─")
        # Consider it a dash line if > 50% are dashes and at least 10 dashes
        return dash_count >= 10 and dash_count / len(line) > 0.5

    def _parse_sections(self, response: str) -> list[Section]:
        """Parse response text into sections.

        Handles:
        - Thinking blocks (∴ Thinking...)
        - Tool calls (⏺ ToolName(...) with ⎿ results)
        - Text responses (⏺ followed by text)
        """
        sections: list[Section] = []
        lines = response.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # Thinking section - marker must be first character of line
            if line.startswith("∴"):
                content_lines: list[str] = []
                i += 1
                # Collect indented content until next section marker
                while i < len(lines):
                    if lines[i].startswith("⏺") or lines[i].startswith("∴"):
                        break
                    content_lines.append(lines[i])
                    i += 1
                sections.append(
                    Section(
                        type="thinking",
                        content="\n".join(content_lines).strip(),
                    )
                )
                continue

            # Tool call or text (both start with ⏺) - marker must be first character
            if line.startswith("⏺"):
                tool_match = re.match(r"^⏺\s+(\w+)\((.*)$", line)
                if tool_match:
                    # Tool call - collect full args and result
                    tool_name = tool_match.group(1)
                    args_start = tool_match.group(2)

                    # Collect full args (may span multiple lines)
                    args_lines = [args_start]
                    i += 1
                    while i < len(lines) and not lines[i].strip().startswith("⎿"):
                        if lines[i].startswith("⏺") or lines[i].startswith("∴"):
                            break
                        args_lines.append(lines[i])
                        i += 1

                    # Clean up args - remove trailing )
                    args_text = "\n".join(args_lines).strip()
                    if args_text.endswith(")"):
                        args_text = args_text[:-1]

                    # Collect result (starts with ⎿) - ⎿ is indented, so use strip()
                    result_lines: list[str] = []
                    while i < len(lines):
                        result_line = lines[i]
                        result_stripped = result_line.strip()
                        if result_stripped.startswith("⎿"):
                            # First result line - remove the ⎿ prefix
                            result_lines.append(result_stripped[1:].strip())
                            i += 1
                        elif result_line.startswith("⏺") or result_line.startswith("∴"):
                            break
                        elif result_lines:  # Continue collecting result
                            result_lines.append(result_line)
                            i += 1
                        else:
                            i += 1
                            break

                    sections.append(
                        Section(
                            type="tool_call",
                            content="\n".join(result_lines).strip(),
                            metadata={
                                "tool": tool_name,
                                "args": args_text.strip(),
                            },
                        )
                    )
                else:
                    # Text response - collect continuation lines
                    text_content = line[1:].strip()  # Remove ⏺
                    content_lines = [text_content] if text_content else []
                    i += 1
                    # Collect until next section marker
                    while i < len(lines):
                        if lines[i].startswith("⏺") or lines[i].startswith("∴"):
                            break
                        if lines[i].strip():
                            content_lines.append(lines[i])
                        i += 1

                    if content_lines:
                        sections.append(
                            Section(
                                type="text",
                                content="\n".join(content_lines).strip(),
                            )
                        )
                continue

            i += 1

        return sections

    def _extract_tokens(self, content: str) -> int | None:
        """Extract token count from status line."""
        for line in reversed(content.split("\n")):
            stripped = line.strip()
            # Look for token count in status lines
            # Valid status line patterns (must start with these to avoid diff/quoted content):
            # - "-- INSERT --" (insert mode)
            # - "?" (shortcuts hint)
            # - "⏵⏵" (bypass permissions mode)
            is_status_line = (
                stripped.startswith("-- INSERT --")
                or stripped.startswith("?")
                or stripped.startswith("⏵⏵")
            )
            if is_status_line and "tokens" in line:
                match = re.search(r"(\d+)\s*tokens", line)
                if match:
                    return int(match.group(1))
        return None
