#!/usr/bin/env python3
"""Interactive conversation flow explorer for proxy logs."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import rich_click as click
from prompt_toolkit import Application
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, ScrollOffsets, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from shared import (
    ToolCall,
    configure_rich_click,
    extract_text,
    extract_tool_results,
    get_style,
    is_tool_result_only,
)

# Configure rich-click
configure_rich_click()


class SearchMode(Enum):
    NONE = "none"
    CURRENT = "current"
    NESTED = "nested"


@dataclass
class ContentBlock:
    """A block in the conversation flow - preserves original order."""

    kind: str  # "thinking", "text", "tool"
    content: str | ToolCall  # str for thinking/text, ToolCall for tool


@dataclass
class Turn:
    number: int
    user_input: str
    user_msg_indices: list[int]
    blocks: list[ContentBlock] = field(default_factory=list)  # Ordered flow
    start_msg_idx: int = 0
    end_msg_idx: int = 0
    is_tool_result_only: bool = False

    @property
    def total_messages(self) -> int:
        return self.end_msg_idx - self.start_msg_idx + 1

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [b.content for b in self.blocks if b.kind == "tool"]

    @property
    def thinking_blocks(self) -> list[str]:
        return [b.content for b in self.blocks if b.kind == "thinking"]

    @property
    def text_blocks(self) -> list[str]:
        return [b.content for b in self.blocks if b.kind == "text"]

    def tool_summary(self) -> str:
        tools = self.tool_calls
        if not tools:
            return ""
        counts = {}
        for tc in tools:
            counts[tc.name] = counts.get(tc.name, 0) + 1
        parts = [f"{n}: {c}" for n, c in sorted(counts.items(), key=lambda x: -x[1])]
        return " │ ".join(parts)

    def files_table(self) -> list[tuple[str, bool, bool]]:
        """Return list of (relative_path, was_read, was_edited) sorted by path."""
        read_set, edited_set, all_paths = set(), set(), []
        for tc in self.tool_calls:
            fp = tc.args.get("file_path", "")
            if fp:
                all_paths.append(fp)
                if tc.name == "Read":
                    read_set.add(fp)
                elif tc.name in ("Edit", "Write"):
                    edited_set.add(fp)

        if not all_paths:
            return []

        # Find common prefix to make paths relative
        abs_paths = [p for p in all_paths if p.startswith("/")]
        prefix = os.path.commonpath(abs_paths) if abs_paths else ""
        if prefix == "/":
            prefix = ""

        def make_relative(p: str) -> str:
            if prefix and p.startswith(prefix):
                return p[len(prefix) :].lstrip("/")
            return p

        # Build table with unique files, sorted by path
        unique_files = sorted(set(all_paths))
        return [(make_relative(fp), fp in read_set, fp in edited_set) for fp in unique_files]

    def get_sections(self) -> list[tuple[str, str, str]]:
        """Return list of (name, style, content) preserving original flow order."""
        sections = [("USER INPUT", "class:user-input", self.user_input or "(empty)")]

        # Add blocks in original order, numbering each type
        thinking_num, text_num, tool_num = 0, 0, 0
        n_thinking = len(self.thinking_blocks)
        n_text = len(self.text_blocks)
        n_tools = len(self.tool_calls)

        for block in self.blocks:
            if block.kind == "thinking":
                thinking_num += 1
                label = f"THINKING #{thinking_num}" if n_thinking > 1 else "THINKING"
                sections.append((label, "class:thinking-text", block.content))
            elif block.kind == "text":
                text_num += 1
                label = f"RESPONSE #{text_num}" if n_text > 1 else "RESPONSE"
                sections.append((label, "class:assistant", block.content))
            elif block.kind == "tool":
                tool_num += 1
                tc = block.content
                label = f"TOOL #{tool_num}: {tc.name}" if n_tools > 1 else f"TOOL: {tc.name}"
                content = f"{tc.summary()}\n\nResult: {tc.result[:400]}{'...' if len(tc.result) > 400 else ''}"
                sections.append((label, "class:tool-name", content))

        return sections

    def matches_search(self, query: str, nested: bool = False) -> bool:
        q = query.lower()
        if q in self.user_input.lower():
            return True
        for block in self.blocks:
            if block.kind in ("thinking", "text") and q in block.content.lower():
                return True
            if block.kind == "tool" and nested and block.content.matches_search(query):
                return True
        return False


@dataclass
class Conversation:
    turns: list[Turn]
    total_messages: int
    model: str
    raw_messages: list[dict]

    @property
    def user_turn_count(self) -> int:
        return sum(1 for t in self.turns if not t.is_tool_result_only)


# Parser uses shared functions from shared.parsing
def parse_conversation(data: dict) -> Conversation:
    messages, turns, current_turn, pending = data.get("messages", []), [], None, {}

    for idx, msg in enumerate(messages):
        role, content = msg.get("role", ""), msg.get("content", "")

        if role == "user":
            # Process tool results - add completed tools to blocks
            for tool_id, result in extract_tool_results(content).items():
                if tool_id in pending and current_turn:
                    tc_info = pending.pop(tool_id)
                    tool_call = ToolCall(
                        name=tc_info["name"],
                        args=tc_info["input"],
                        result=result[:500],
                        index=len(current_turn.tool_calls) + 1,
                        tool_use_id=tool_id,
                    )
                    current_turn.blocks.append(ContentBlock("tool", tool_call))

            user_text = extract_text(content)
            if user_text and not is_tool_result_only(content):
                if current_turn:
                    current_turn.end_msg_idx = idx - 1
                    turns.append(current_turn)
                current_turn = Turn(len(turns) + 1, user_text, [idx], start_msg_idx=idx)
            elif current_turn:
                current_turn.user_msg_indices.append(idx)

        elif role == "assistant":
            if not current_turn:
                current_turn = Turn(
                    len(turns) + 1,
                    "[conversation start]",
                    [],
                    start_msg_idx=idx,
                    is_tool_result_only=True,
                )

            # Process content blocks in order as they appear
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type", "")
                    if btype == "thinking" and block.get("thinking"):
                        current_turn.blocks.append(ContentBlock("thinking", block["thinking"]))
                    elif btype == "text":
                        text = block.get("text", "").strip()
                        if text and not text.startswith("<system-reminder>"):
                            current_turn.blocks.append(ContentBlock("text", text))
                    elif btype == "tool_use":
                        # Store pending tool call - will be added when result arrives
                        pending[block.get("id", "")] = {
                            "name": block.get("name", "?"),
                            "input": block.get("input", {}),
                        }
            elif (
                isinstance(content, str)
                and content.strip()
                and not content.strip().startswith("<system-reminder>")
            ):
                current_turn.blocks.append(ContentBlock("text", content.strip()))

    if current_turn:
        current_turn.end_msg_idx = len(messages) - 1
        turns.append(current_turn)
    return Conversation(turns, len(messages), data.get("model", "?"), messages)


def load_conversation(log_dir: Path) -> Conversation:
    for name in ["1_request.json", "1_anthropic_request.json"]:
        f = log_dir / name
        if f.exists():
            with open(f, encoding="utf-8") as fp:
                return parse_conversation(json.load(fp))
    raise FileNotFoundError(f"No request file found in {log_dir}")


class ConversationExplorer:
    """Interactive TUI with unified hierarchical drill-down navigation."""

    def __init__(self, conversation: Conversation, log_path: Path, dark_theme: bool = True):
        self.conversation, self.log_path = conversation, log_path

        # View hierarchy: turns -> sections -> content/tools -> tool_content
        self.view_mode = "turns"  # turns, sections, content, tools, tool_content
        self.selected_index = 0
        self.scroll_offset = 0

        # Selected items at each level
        self.selected_turn: Turn | None = None
        self.selected_section: tuple[str, str, str] | None = None  # (name, style, content)
        self.selected_tool: ToolCall | None = None

        # Content lines for scrollable views
        self.content_lines: list[tuple[str, str]] = []

        # Search state
        self.search_mode, self.search_query, self.filtered_indices = SearchMode.NONE, "", []

        self._cursor_line = 0
        self.kb, self.style = self._create_key_bindings(), get_style(dark_theme)
        self.app = self._create_app()

    def _get_visible_items(self) -> list[int]:
        if self.search_query and self.filtered_indices:
            return self.filtered_indices
        if self.view_mode == "turns":
            return list(range(len(self.conversation.turns)))
        if self.view_mode == "sections" and self.selected_turn:
            return list(range(len(self.selected_turn.get_sections())))
        return []

    def _update_filtered_indices(self):
        if not self.search_query:
            self.filtered_indices = []
            return
        q = self.search_query.lower()
        nested = self.search_mode == SearchMode.NESTED

        if self.view_mode == "turns":
            # /: search user_input, response, thinking only
            # ?: also search in tool calls
            self.filtered_indices = [
                i
                for i, t in enumerate(self.conversation.turns)
                if t.matches_search(self.search_query, nested)
            ]

        elif self.view_mode == "sections" and self.selected_turn:
            # /: search section name and content
            # ?: for tool sections, also search in full tool args/result
            results = []
            for i, (name, _, content) in enumerate(self.selected_turn.get_sections()):
                if q in name.lower() or q in content.lower():
                    results.append(i)
                elif nested and name.startswith("TOOL"):
                    # Deep search in tool - find tool index
                    try:
                        tool_idx = int(name.split("#")[1].split(":")[0]) - 1 if "#" in name else 0
                    except (ValueError, IndexError):
                        tool_idx = 0
                    if tool_idx < len(self.selected_turn.tool_calls):
                        if self.selected_turn.tool_calls[tool_idx].matches_search(q, nested=True):
                            results.append(i)
            self.filtered_indices = results

    def _create_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        in_search = Condition(lambda: self.search_mode != SearchMode.NONE)
        not_search = Condition(lambda: self.search_mode == SearchMode.NONE)
        in_scroll = Condition(lambda: self.view_mode in ("content", "tool_content"))
        in_list = Condition(lambda: self.view_mode in ("turns", "sections"))

        @kb.add("q", filter=not_search)
        def quit_(e):
            e.app.exit()

        @kb.add("escape")
        def esc(e):
            if self.search_mode != SearchMode.NONE:
                self._clear_search()
            else:
                self._go_back()

        @kb.add("backspace", filter=not_search)
        def back(e):
            self._go_back()

        @kb.add("backspace", filter=in_search)
        def bksp_search(e):
            if self.search_query:
                self.search_query = self.search_query[:-1]
                self._update_filtered_indices()
                if self.filtered_indices:
                    self.selected_index = 0

        # List navigation
        @kb.add("up", filter=in_list & not_search)
        @kb.add("k", filter=in_list & not_search)
        def up(e):
            if self.selected_index > 0:
                self.selected_index -= 1

        @kb.add("down", filter=in_list & not_search)
        @kb.add("j", filter=in_list & not_search)
        def down(e):
            visible = self._get_visible_items()
            if self.selected_index < len(visible) - 1:
                self.selected_index += 1

        @kb.add("g", "g", filter=in_list & not_search)
        def top(e):
            self.selected_index = 0

        @kb.add("G", filter=in_list & not_search)
        def bot(e):
            self.selected_index = max(0, len(self._get_visible_items()) - 1)

        @kb.add("enter", filter=in_list & not_search)
        def enter(e):
            self._drill_down()

        @kb.add("h", filter=in_list & not_search)
        def back_h(e):
            self._go_back()

        # Scroll navigation for content views
        @kb.add("up", filter=in_scroll)
        @kb.add("k", filter=in_scroll)
        def scroll_up(e):
            self.scroll_offset = max(0, self.scroll_offset - 1)

        @kb.add("down", filter=in_scroll)
        @kb.add("j", filter=in_scroll)
        def scroll_down(e):
            max_scroll = max(0, len(self.content_lines) - 40)
            self.scroll_offset = min(max_scroll, self.scroll_offset + 1)

        @kb.add("pageup", filter=in_scroll)
        def page_up(e):
            self.scroll_offset = max(0, self.scroll_offset - 20)

        @kb.add("pagedown", filter=in_scroll)
        @kb.add("space", filter=in_scroll)
        def page_down(e):
            max_scroll = max(0, len(self.content_lines) - 40)
            self.scroll_offset = min(max_scroll, self.scroll_offset + 20)

        @kb.add("g", "g", filter=in_scroll)
        def scroll_top(e):
            self.scroll_offset = 0

        @kb.add("G", filter=in_scroll)
        def scroll_bot(e):
            self.scroll_offset = max(0, len(self.content_lines) - 40)

        # Search
        @kb.add("/", filter=not_search)
        def search(e):
            self.search_mode, self.search_query, self.filtered_indices = SearchMode.CURRENT, "", []

        @kb.add("?", filter=not_search & in_list)
        def nested_search(e):
            self.search_mode, self.search_query, self.filtered_indices = SearchMode.NESTED, "", []

        @kb.add("enter", filter=in_search)
        def confirm_search(e):
            self.search_mode = SearchMode.NONE

        @kb.add("<any>", filter=in_search)
        def search_input(e):
            if e.data and len(e.data) == 1 and e.data.isprintable():
                self.search_query += e.data
                self._update_filtered_indices()
                if self.filtered_indices:
                    self.selected_index = 0

        @kb.add("c-c")
        @kb.add("c-d")
        def cc(e):
            e.app.exit()

        return kb

    def _clear_search(self):
        self.search_mode, self.search_query, self.filtered_indices, self.selected_index = (
            SearchMode.NONE,
            "",
            [],
            0,
        )

    def _drill_down(self):
        """Enter into the selected item."""
        visible = self._get_visible_items()
        if not visible:
            return
        idx = visible[min(self.selected_index, len(visible) - 1)]

        if self.view_mode == "turns":
            self.selected_turn = self.conversation.turns[idx]
            self.view_mode = "sections"
            self.selected_index = 0
            self._clear_search()

        elif self.view_mode == "sections" and self.selected_turn:
            sections = self.selected_turn.get_sections()
            if idx < len(sections):
                self.selected_section = sections[idx]
                name, style, content = self.selected_section
                # Check if it's a tool section (starts with "TOOL")
                if name.startswith("TOOL"):
                    # Find the corresponding tool and show tool_content
                    tool_idx = int(name.split("#")[1].split(":")[0]) - 1 if "#" in name else 0
                    if tool_idx < len(self.selected_turn.tool_calls):
                        self.selected_tool = self.selected_turn.tool_calls[tool_idx]
                        self.view_mode = "tool_content"
                        self._build_tool_content_lines()
                        self.scroll_offset = 0
                else:
                    self.view_mode = "content"
                    self._build_content_lines(content, style)
                    self.scroll_offset = 0

    def _go_back(self):
        """Go back to parent view."""
        if self.view_mode == "tool_content":
            self.view_mode = "sections"
            self.selected_tool = None
        elif self.view_mode == "content":
            self.view_mode = "sections"
            self.selected_section = None
        elif self.view_mode == "sections":
            self.view_mode = "turns"
            if self.selected_turn:
                self.selected_index = self.selected_turn.number - 1
            self.selected_turn = None
        self.scroll_offset = 0
        self.content_lines = []

    def _build_content_lines(self, content: str, style: str):
        """Build scrollable content lines."""
        self.content_lines = [(style, line) for line in content.split("\n")]

    def _build_tool_content_lines(self):
        """Build scrollable content for a tool call."""
        if not self.selected_tool:
            return
        tc = self.selected_tool
        lines = [
            ("class:tool-name", f"{tc.name} (call #{tc.index})"),
            ("class:separator", "═" * 60),
            ("", ""),
            ("class:label", "Arguments:"),
            ("class:separator", "─" * 40),
        ]
        for k, v in tc.args.items():
            lines.append(("class:arg-name", f"  {k}:"))
            vt = v if isinstance(v, str) else json.dumps(v, indent=2)
            # Highlight file_path in orange for Read/Write/Edit tools
            is_file_arg = k == "file_path" and tc.name in ("Read", "Write", "Edit")
            style = "class:file-name" if is_file_arg else "class:arg-value"
            for vl in vt.split("\n"):
                lines.append((style, f"    {vl}"))
        lines.extend([("", ""), ("class:label", "Result:"), ("class:separator", "─" * 40)])
        result, style = tc.result or "(empty)", "class:success" if tc.success else "class:error"
        for rl in result.split("\n"):
            lines.append((style, f"  {rl}"))
        self.content_lines = lines

    def _pad(self, text, width):
        return " " * max(0, width - len(text))

    def _render_with_paths(self, lines: list, text: str, path_style: str = "class:file-path"):
        """Render text with file paths highlighted."""
        import re

        # Match file paths: /path/to/file.ext, relative/path/file.ext, or simple file.ext
        # Note: longer extensions (json, yaml, toml, html) must come before shorter ones (js, ts, md, sh, go, rs, rb, c, h)
        path_pattern = r"(/[\w./\-_]+\.[\w]+|[\w./\-_]+/[\w./\-_]+\.[\w]+|[\w\-_]+\.(?:json|yaml|yml|toml|html|java|cpp|hpp|php|sql|xml|csv|tsx|jsx|txt|css|py|js|ts|md|sh|go|rs|rb|c|h))"
        parts = re.split(path_pattern, text)
        for part in parts:
            if re.match(path_pattern, part):
                lines.append((path_style, part))
            else:
                lines.append(("class:header-dim", part))

    def _render_header(self) -> list:
        lines = []
        name = self.log_path.name[:50]
        lines.extend(
            [
                ("class:header", f" {name} "),
                ("class:header-dim", " │ "),
                ("class:header-info", f"{self.conversation.user_turn_count} turns"),
                ("class:header-dim", " │ "),
                ("class:header-info", f"{self.conversation.total_messages} msgs"),
                ("class:header-dim", " │ "),
                ("class:header-dim", self.conversation.model),
                ("", "\n"),
            ]
        )

        # Search bar
        if self.search_mode != SearchMode.NONE:
            label = "Search" if self.search_mode == SearchMode.CURRENT else "Search (nested)"
            lines.extend(
                [
                    ("class:search-label", f" {label}: "),
                    ("class:search-box", self.search_query or ""),
                    ("class:search-box", "█"),
                ]
            )
            if self.search_query:
                n = len(self.filtered_indices)
                lines.extend(
                    [
                        ("", "  "),
                        (
                            "class:success" if n else "class:no-match",
                            f"{n} matches" if n else "No matches",
                        ),
                    ]
                )
            lines.append(("", "\n"))
        elif self.search_query:
            lines.extend(
                [
                    ("class:search-mode", f' Filter: "{self.search_query}" '),
                    ("class:key-desc", "(Esc to clear)\n"),
                ]
            )

        # Breadcrumb
        if self.view_mode == "turns":
            lines.append(("class:breadcrumb", " ● Turns"))
        elif self.view_mode == "sections":
            lines.extend(
                [
                    ("class:breadcrumb-dim", " Turns › "),
                    ("class:breadcrumb", f"Turn {self.selected_turn.number}"),
                ]
            )
        elif self.view_mode == "content":
            lines.extend(
                [
                    ("class:breadcrumb-dim", " Turns › "),
                    ("class:breadcrumb-dim", f"Turn {self.selected_turn.number} › "),
                    ("class:breadcrumb", self.selected_section[0] if self.selected_section else ""),
                ]
            )
        elif self.view_mode == "tool_content":
            lines.extend(
                [
                    ("class:breadcrumb-dim", " Turns › "),
                    ("class:breadcrumb-dim", f"Turn {self.selected_turn.number} › "),
                    ("class:breadcrumb", self.selected_tool.name if self.selected_tool else ""),
                ]
            )

        lines.extend([("", "\n"), ("class:separator", "─" * 100 + "\n")])
        return lines

    def _render_turns_with_cursor(self) -> tuple[list, int]:
        lines = []
        selected_line = 0
        current_line = 0
        visible = self._get_visible_items()
        if not visible:
            if self.search_query:
                lines.append(("class:no-match", "  No matching turns\n"))
            return lines, 0

        for li, ti in enumerate(visible):
            t, sel = self.conversation.turns[ti], li == self.selected_index
            card_start_line = current_line  # Track start of this card
            pre = " → " if sel else "   "
            hdr = f"Turn {t.number} ({t.total_messages} msgs)"

            if sel:
                lines.extend([("class:selected", pre + hdr + self._pad(hdr, 60)), ("", "\n")])
            else:
                sty = "class:turn-dim" if t.is_tool_result_only else "class:turn-number"
                lines.extend(
                    [
                        ("", pre),
                        (sty, f"Turn {t.number}"),
                        ("class:turn-dim", f" ({t.total_messages} msgs)\n"),
                    ]
                )
            current_line += 1

            if t.user_input:
                pv = t.user_input[:150].replace("\n", " ") + (
                    "..." if len(t.user_input) > 150 else ""
                )
                txt = f'     YOU: "{pv}"'
                if sel:
                    lines.extend([("class:selected", txt + self._pad(txt, 160)), ("", "\n")])
                else:
                    lines.extend(
                        [
                            ("class:user-label", "     YOU: "),
                            (
                                "class:user-input-dim"
                                if t.is_tool_result_only
                                else "class:user-input",
                                f'"{pv}"\n',
                            ),
                        ]
                    )
                current_line += 1

            if t.thinking_blocks:
                tcount = len(t.thinking_blocks)
                txt = f"     💭 {tcount} thinking{'s' if tcount > 1 else ''}"
                if sel:
                    lines.extend([("class:selected", txt + self._pad(txt, 100)), ("", "\n")])
                else:
                    lines.extend([("class:thinking-text", txt + "\n")])
                current_line += 1

            if t.tool_calls:
                ts = t.tool_summary()
                txt = f"     ⚡ {len(t.tool_calls)} tools: {ts}"
                if sel:
                    lines.extend([("class:selected", txt + self._pad(txt, 160)), ("", "\n")])
                else:
                    lines.extend(
                        [
                            ("class:tool-icon", "     ⚡ "),
                            ("class:tool-count", f"{len(t.tool_calls)} tools: "),
                            ("class:tool-summary", ts + "\n"),
                        ]
                    )
                current_line += 1
                # Show files read/edited as table
                files_table = t.files_table()
                if files_table:
                    for fp, was_read, was_edited in files_table[:12]:
                        r_icon = "📖" if was_read else "  "
                        w_icon = "✏️" if was_edited else "  "
                        # Pad filepath to align columns
                        fp_padded = fp[:60] + ("..." if len(fp) > 60 else "")
                        txt = f"        {fp_padded:<63} {r_icon}  {w_icon}"
                        if sel:
                            lines.extend(
                                [("class:selected", txt + self._pad(txt, 160)), ("", "\n")]
                            )
                        else:
                            lines.extend(
                                [
                                    ("class:header-dim", "        "),
                                    ("class:file-name", f"{fp_padded:<63} "),
                                    ("class:user-input", f"{r_icon}  "),
                                    ("class:tool-icon", f"{w_icon}\n"),
                                ]
                            )
                        current_line += 1
                    if len(files_table) > 12:
                        lines.append(
                            (
                                "class:header-dim",
                                f"        ... +{len(files_table) - 12} more files\n",
                            )
                        )
                        current_line += 1

            if t.text_blocks:
                # Show last response text as preview
                last_response = t.text_blocks[-1]
                pv = last_response[:150].replace("\n", " ") + (
                    "..." if len(last_response) > 150 else ""
                )
                if sel:
                    lines.append(("class:selected", f"     CLAUDE: {pv}\n"))
                else:
                    lines.extend(
                        [("class:assistant-label", "     CLAUDE: "), ("class:assistant", pv + "\n")]
                    )
                current_line += 1

            lines.extend([("", "\n"), ("class:separator", "  " + "─" * 100 + "\n")])
            current_line += 2

            # Set cursor to START of card - scroll_offsets keeps lines below visible
            if sel:
                selected_line = card_start_line

        return lines, selected_line

    def _render_sections_with_cursor(self) -> tuple[list, int]:
        if not self.selected_turn:
            return [], 0
        lines = []
        selected_line = 0
        current_line = 0
        sections = self.selected_turn.get_sections()

        for i, (name, _style, content) in enumerate(sections):
            sel = i == self.selected_index
            if sel:
                selected_line = current_line
            pre = " → " if sel else "   "

            # Determine color based on section type
            if name == "USER INPUT":
                section_style = "class:user-input"
            elif name.startswith("TOOL"):
                section_style = "class:tool-section"
            elif name.startswith("THINKING"):
                section_style = "class:thinking-text"
            elif name.startswith("RESPONSE"):
                section_style = "class:assistant"
            else:
                section_style = "class:section-header"

            if sel:
                lines.extend([("class:selected", f"{pre}{name}" + self._pad(name, 65)), ("", "\n")])
            else:
                lines.extend([("", pre), (section_style, name), ("", "\n")])
            current_line += 1

            # Preview (first 6 lines) - highlight file paths in tool sections
            preview_lines = content.split("\n")[:6]
            is_tool = name.startswith("TOOL")
            # Read/Write/Edit tools should show file paths in orange
            is_file_tool = is_tool and any(t in name for t in ("Read", "Write", "Edit"))
            for pl in preview_lines:
                pv = pl[:140] + ("..." if len(pl) > 140 else "")
                if sel:
                    lines.extend(
                        [("class:selected", f"     {pv}" + self._pad(pv, 150)), ("", "\n")]
                    )
                elif is_tool:
                    # Highlight file paths in tool sections
                    lines.append(("class:header-dim", "     "))
                    path_style = "class:file-name" if is_file_tool else "class:file-path"
                    self._render_with_paths(lines, pv, path_style)
                    lines.append(("", "\n"))
                else:
                    lines.append(("class:header-dim", f"     {pv}\n"))
                current_line += 1

            if len(content.split("\n")) > 6:
                more = len(content.split("\n")) - 6
                if sel:
                    lines.extend(
                        [
                            (
                                "class:selected",
                                f"     ... {more} more lines"
                                + self._pad(f"... {more} more lines", 100),
                            ),
                            ("", "\n"),
                        ]
                    )
                else:
                    lines.append(("class:header-dim", f"     ... {more} more lines\n"))
                current_line += 1

            lines.extend([("", "\n"), ("class:separator", "  " + "─" * 100 + "\n")])
            current_line += 2
        return lines, selected_line

    def _render_content(self) -> list:
        lines = []
        total = len(self.content_lines)
        start, end = self.scroll_offset, min(self.scroll_offset + 45, total)

        if start > 0:
            lines.append(("class:header-dim", f"  ↑ {start} lines above\n"))

        for i in range(start, end):
            style, text = self.content_lines[i]
            lines.append((style, text + "\n"))

        if end < total:
            lines.append(("class:header-dim", f"\n  ↓ {total - end} more lines below\n"))

        return lines

    def _render_footer(self) -> list:
        lines = [("class:separator", "─" * 100 + "\n")]
        keys = {
            "turns": [
                ("↑↓", "nav"),
                ("Enter", "open"),
                ("/", "search"),
                ("?", "deep search"),
                ("q", "quit"),
            ],
            "sections": [
                ("↑↓", "nav"),
                ("Enter", "open"),
                ("/", "search"),
                ("?", "deep search"),
                ("Esc/Bksp", "back"),
                ("q", "quit"),
            ],
            "content": [
                ("↑↓/j/k", "scroll"),
                ("gg/G", "top/bot"),
                ("Esc/Bksp", "back"),
                ("q", "quit"),
            ],
            "tool_content": [
                ("↑↓/j/k", "scroll"),
                ("gg/G", "top/bot"),
                ("Esc/Bksp", "back"),
                ("q", "quit"),
            ],
            "search": [("Enter", "confirm"), ("Esc", "cancel"), ("Bksp", "delete")],
        }
        mode = "search" if self.search_mode != SearchMode.NONE else self.view_mode
        for k, d in keys.get(mode, []):
            lines.extend([("class:key", f" {k}"), ("class:key-desc", f" {d}  ")])
        return lines

    def _get_formatted_text(self) -> FormattedText:
        lines = self._render_header()
        header_lines = sum(1 for s, t in lines if "\n" in t or t.endswith("\n"))

        if self.view_mode == "turns":
            content, selected_line = self._render_turns_with_cursor()
            lines.extend(content)
            self._cursor_line = header_lines + selected_line
        elif self.view_mode == "sections":
            content, selected_line = self._render_sections_with_cursor()
            lines.extend(content)
            self._cursor_line = header_lines + selected_line
        elif self.view_mode in ("content", "tool_content"):
            lines.extend(self._render_content())
            self._cursor_line = header_lines + self.scroll_offset
        else:
            self._cursor_line = 0

        return FormattedText(lines)

    def _get_footer_text(self) -> FormattedText:
        return FormattedText(self._render_footer())

    def _create_app(self) -> Application:
        main_ctrl = FormattedTextControl(
            self._get_formatted_text,
            focusable=True,
            show_cursor=False,
            get_cursor_position=lambda: Point(0, self._cursor_line),
        )
        footer_ctrl = FormattedTextControl(self._get_footer_text)
        layout = Layout(
            HSplit(
                [
                    Window(
                        content=main_ctrl,
                        wrap_lines=True,
                        scroll_offsets=ScrollOffsets(bottom=20),
                    ),
                    Window(content=footer_ctrl, height=Dimension.exact(2)),
                ]
            )
        )
        return Application(
            layout=layout,
            key_bindings=self.kb,
            style=self.style,
            full_screen=True,
            mouse_support=True,
        )

    def run(self):
        self.app.run()


@click.command()
@click.argument(
    "log_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    metavar="LOG_DIR",
)
@click.option(
    "-l",
    "--light",
    is_flag=True,
    help="Use light theme instead of dark (Dracula) theme.",
)
def main(log_dir: Path, light: bool) -> None:
    """Interactive TUI for exploring conversation flow in proxy logs.

    Provides a hierarchical view of conversation turns with drill-down
    navigation into thinking blocks, responses, and tool calls.

    \b
    LOG_DIR is a proxy log directory containing request/response files:
      • 1_request.json or 1_anthropic_request.json
      • 2_response_events.json (optional)

    \b
    Navigation:
      ↑↓/jk        Move up/down in lists
      Enter/l      Drill down into selected item
      Esc/Bksp/h   Go back to parent view
      gg/G         Jump to top/bottom
      /            Search current level
      ?            Deep search (includes nested content)
      q            Quit

    \b
    View Hierarchy:
      1. Turns     - Overview of all conversation turns
      2. Sections  - USER INPUT, THINKING, RESPONSE, TOOL blocks
      3. Content   - Full scrollable content view

    \b
    Examples:
      # Explore a specific log
      explore_conversation.py /path/to/001_173039_5msgs_...

      # Use light theme
      explore_conversation.py /path/to/log --light
    """
    try:
        conv = load_conversation(log_dir)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    if not conv.turns:
        click.echo("No turns found in conversation", err=True)
        sys.exit(1)
    ConversationExplorer(conv, log_dir, dark_theme=not light).run()


if __name__ == "__main__":
    main()
