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

import re

from nerve.core.parsers.base import Parser
from nerve.core.types import ParsedResponse, Section


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

        Scan from bottom:
        1. Find the LAST "-- INSERT --" or "? for shortcuts" (current status)
        2. Check if "esc to interrupt" appears AFTER that status line
        3. If no "esc to interrupt" after status → ready

        Args:
            content: Terminal output to check.

        Returns:
            True if Claude is waiting for input.
        """
        lines = content.strip().split("\n")
        if len(lines) < 3:
            return False

        # Scan from bottom to find the LAST status line
        status_line_idx = -1
        for i in range(len(lines) - 1, max(0, len(lines) - 50), -1):
            line_lower = lines[i].lower()
            if "-- insert --" in line_lower or "? for shortcuts" in line_lower:
                status_line_idx = i
                break

        if status_line_idx == -1:
            return False  # No status line found

        # Only check AFTER the status line for "esc to interrupt"
        # (old "esc to interrupt" before status line is historical)
        for i in range(status_line_idx, len(lines)):
            line_lower = lines[i].lower()
            if "esc to interrupt" in line_lower or "esc to cancel" in line_lower:
                return False  # Still processing

        return True  # No "esc to interrupt" after status, we're ready

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

        return ParsedResponse(
            raw=raw,
            sections=tuple(sections),
            is_complete=True,
            is_ready=self.is_ready(content),
            tokens=tokens,
        )

    def _extract_response(self, content: str) -> str:
        """Extract response between last user prompt and current prompt."""
        lines = content.split("\n")

        # Find last user prompt ("> " followed by actual text, not suggestions)
        start_idx = -1
        for i, line in enumerate(lines):
            if line.startswith("> ") and len(line.strip()) > 1:
                if "(tab to accept)" not in line:
                    start_idx = i

        if start_idx == -1:
            # Try to find response markers directly
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("∴") or stripped.startswith("⏺"):
                    start_idx = i - 1
                    break
            else:
                return ""

        # Find end (empty prompt before INSERT)
        end_idx = len(lines)
        for i in range(len(lines) - 1, start_idx, -1):
            if "-- INSERT --" in lines[i]:
                for j in range(i - 1, max(start_idx, i - 10), -1):
                    stripped = lines[j].strip()
                    if stripped == ">" or stripped == "> ":
                        end_idx = j
                        break
                    if stripped.startswith(">") and "(tab to accept)" in stripped:
                        end_idx = j
                        break
                break

        response_lines = lines[start_idx + 1 : end_idx]
        return "\n".join(response_lines)

    def _parse_sections(self, response: str) -> list[Section]:
        """Parse response text into sections."""
        sections: list[Section] = []
        lines = response.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Thinking section
            if stripped.startswith("∴"):
                content_lines: list[str] = []
                i += 1
                while i < len(lines):
                    if lines[i].strip().startswith(("⏺", "∴")):
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

            # Tool call or text (both start with ⏺)
            if stripped.startswith("⏺"):
                tool_match = re.match(r"^⏺\s+(\w+)\((.*)$", stripped)
                if tool_match:
                    # Tool call
                    tool_name = tool_match.group(1)
                    sections.append(
                        Section(
                            type="tool_call",
                            content=stripped,
                            metadata={"tool": tool_name},
                        )
                    )
                else:
                    # Text response
                    text_content = stripped[1:].strip()
                    sections.append(
                        Section(
                            type="text",
                            content=text_content,
                        )
                    )
                i += 1
                continue

            i += 1

        return sections

    def _extract_tokens(self, content: str) -> int | None:
        """Extract token count from status line."""
        for line in reversed(content.split("\n")):
            # Look for token count in status lines (INSERT mode or shortcuts hint)
            if ("-- INSERT --" in line or "? for shortcuts" in line) and "tokens" in line:
                match = re.search(r"(\d+)\s*tokens", line)
                if match:
                    return int(match.group(1))
        return None
