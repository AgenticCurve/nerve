#!/usr/bin/env python3
"""Visualize files read/written in a conversation turn."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import rich_click as click
from prompt_toolkit import Application, print_formatted_text
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from shared import DRACULA, FileOperation, ToolCall, configure_rich_click, get_style

# Configure rich-click with option groups
configure_rich_click(
    option_groups={
        "main": [
            {
                "name": "Display Options",
                "options": ["--compact", "--turn", "--root", "--all"],
            },
            {
                "name": "Interactive Mode",
                "options": ["--tui", "--watch", "--editor"],
            },
        ],
    }
)

# Use shared Dracula theme
COLORS = DRACULA
STYLE = get_style(dark=True)


@dataclass
class Turn:
    number: int
    tool_calls: list[ToolCall] = field(default_factory=list)

    def get_file_operations(self) -> dict[str, FileOperation]:
        """Extract file operations from tool calls."""
        ops: dict[str, FileOperation] = {}
        for tc in self.tool_calls:
            if tc.name in ("Read", "Write", "Edit"):
                fp = tc.args.get("file_path", "")
                if fp:
                    if fp not in ops:
                        ops[fp] = FileOperation(path=fp)
                    if tc.name == "Read":
                        ops[fp].was_read = True
                    else:  # Write or Edit
                        ops[fp].was_written = True
        return ops


def parse_conversation(log_dir: Path) -> list[Turn]:
    """Parse conversation log and extract turns with tool calls."""
    # Try different file formats
    messages_file = log_dir / "1_messages.json"
    request_file = log_dir / "1_request.json"
    anthropic_request_file = log_dir / "1_anthropic_request.json"

    if messages_file.exists():
        with open(messages_file) as f:
            messages = json.load(f)
    elif request_file.exists():
        with open(request_file) as f:
            data = json.load(f)
            messages = data.get("messages", [])
    elif anthropic_request_file.exists():
        with open(anthropic_request_file) as f:
            data = json.load(f)
            messages = data.get("messages", [])
    else:
        print(f"Error: No messages file found in {log_dir}", file=sys.stderr)
        sys.exit(1)

    turns: list[Turn] = []
    current_turn: Turn | None = None

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", [])

        if role == "user":
            # Check if this is a user message (not just tool results)
            has_user_text = any(
                isinstance(c, str) or (isinstance(c, dict) and c.get("type") == "text")
                for c in (content if isinstance(content, list) else [content])
            )
            if has_user_text:
                current_turn = Turn(number=len(turns) + 1)
                turns.append(current_turn)

        elif role == "assistant" and current_turn:
            # Extract tool calls
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tc = ToolCall(
                            name=block.get("name", ""),
                            args=block.get("input", {}),
                        )
                        current_turn.tool_calls.append(tc)

    return turns


def build_tree_structure(file_ops: dict[str, FileOperation], root: Path | None = None) -> dict:
    """Build a nested dict representing directory tree."""
    if not file_ops:
        return {}

    # Find common root if not specified
    if root is None:
        paths = [Path(fp) for fp in file_ops]
        try:
            root = Path(os.path.commonpath([p for p in paths if p.is_absolute()]))
            # If common path is a file (not a directory), use its parent
            if root.is_file() or not root.is_dir():
                root = root.parent
        except ValueError:
            root = Path.cwd()

    tree: dict = {}

    for fp, op in file_ops.items():
        path = Path(fp)
        try:
            rel_path = path.relative_to(root)
        except ValueError:
            rel_path = path

        # Build nested structure
        parts = rel_path.parts
        current = tree
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                # Leaf node (file)
                current[part] = op
            else:
                # Directory
                if part not in current:
                    current[part] = {}
                current = current[part]

    return tree


def get_full_tree(root: Path, file_ops: dict[str, FileOperation], max_depth: int = 10) -> dict:
    """Build full directory tree from filesystem, marking touched files."""
    tree: dict = {}
    found_paths: set[str] = set()

    # Normalize file_ops paths for comparison
    normalized_ops = {}
    for fp, op in file_ops.items():
        try:
            normalized = str(Path(fp).resolve())
            normalized_ops[normalized] = op
        except Exception:
            normalized_ops[fp] = op

    def walk_dir(dir_path: Path, current_tree: dict, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            # Skip hidden files and common non-essential dirs
            if entry.name.startswith(".") or entry.name in (
                "node_modules",
                "__pycache__",
                ".git",
                "venv",
                ".venv",
            ):
                continue

            if entry.is_dir():
                current_tree[entry.name] = {}
                walk_dir(entry, current_tree[entry.name], depth + 1)
                # Remove empty directories
                if not current_tree[entry.name]:
                    del current_tree[entry.name]
            else:
                resolved = str(entry.resolve())
                if resolved in normalized_ops:
                    current_tree[entry.name] = normalized_ops[resolved]
                    found_paths.add(resolved)
                else:
                    current_tree[entry.name] = FileOperation(
                        path=str(entry), was_read=False, was_written=False
                    )

    walk_dir(root, tree, 0)

    # Add any touched files that weren't found in the tree (outside root or deleted)
    missing_files = []
    for orig_path, op in file_ops.items():
        try:
            resolved = str(Path(orig_path).resolve())
        except Exception:
            resolved = orig_path
        if resolved not in found_paths and (op.was_read or op.was_written):
            missing_files.append((orig_path, op))

    if missing_files:
        # Add missing files section at the end
        missing_dict: dict = {}
        for fp, op in sorted(missing_files, key=lambda x: x[0]):
            missing_dict[f"{Path(fp).name} ({fp})"] = op
        tree["[NOT FOUND - deleted or outside root]"] = missing_dict

    return tree


def render_tree(
    tree: dict,
    compact: bool = False,
    prefix: str = "",
    is_root: bool = True,
    lines: list | None = None,
) -> list:
    """Render tree as formatted text."""
    if lines is None:
        lines = []

    items = list(tree.items())
    for i, (name, value) in enumerate(items):
        is_last_item = i == len(items) - 1

        # Tree branch characters
        if is_root:
            branch = ""
            child_prefix = "    "
        else:
            branch = "└── " if is_last_item else "├── "
            child_prefix = prefix + ("    " if is_last_item else "│   ")

        if isinstance(value, dict):
            # Directory
            lines.append(("class:tree", prefix + branch))
            lines.append(("class:dir", f"{name}/\n"))
            render_tree(value, compact, child_prefix, is_root=False, lines=lines)
        elif isinstance(value, FileOperation):
            # File
            lines.append(("class:tree", prefix + branch))

            # Determine style based on operations
            if value.was_read and value.was_written:
                style = "class:both"
                marker = " [R+W]"
            elif value.was_written:
                style = "class:write"
                marker = " [W]"
            elif value.was_read:
                style = "class:read"
                marker = " [R]"
            else:
                if compact:
                    continue  # Skip untouched files in compact mode
                style = "class:dim"
                marker = ""

            lines.append((style, name))
            if marker:
                lines.append((style, marker))
            lines.append(("", "\n"))

    return lines


def print_summary(file_ops: dict[str, FileOperation]):
    """Print summary of file operations."""
    read_only = sum(1 for op in file_ops.values() if op.was_read and not op.was_written)
    write_only = sum(1 for op in file_ops.values() if op.was_written and not op.was_read)
    both = sum(1 for op in file_ops.values() if op.was_read and op.was_written)

    lines = [
        ("class:header", "File Operations Summary\n"),
        ("class:dim", "─" * 40 + "\n"),
        ("class:read", "  Read only:  "),
        ("class:count", f"{read_only}\n"),
        ("class:write", "  Written:    "),
        ("class:count", f"{write_only}\n"),
        ("class:both", "  Read+Write: "),
        ("class:count", f"{both}\n"),
        ("class:dim", "  Total:      "),
        ("class:info", f"{len(file_ops)}\n"),
        ("", "\n"),
    ]
    print_formatted_text(FormattedText(lines), style=STYLE)


def get_latest_log_dir(parent_dir: Path) -> Path | None:
    """Get the latest log directory from parent (sorted by name which includes timestamp)."""
    if not parent_dir.exists() or not parent_dir.is_dir():
        return None
    subdirs = [d for d in parent_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if not subdirs:
        return None
    # Sort by name (format: NNN_HHMMSS_Nmsgs_...) - latest is last
    return sorted(subdirs, key=lambda d: d.name)[-1]


# ─────────────────────────────────────────────────────────────────────────────
# TUI Mode
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TreeNode:
    """A node in the file tree for TUI navigation."""

    name: str
    path: str
    is_dir: bool
    depth: int
    operation: FileOperation | None = None
    expanded: bool = True
    children: list[TreeNode] = field(default_factory=list)
    parent: TreeNode | None = None

    @property
    def has_touched_files(self) -> bool:
        """Check if this node or any descendant has touched files."""
        if self.operation and (self.operation.was_read or self.operation.was_written):
            return True
        return any(c.has_touched_files for c in self.children)


def build_tree_nodes(
    tree: dict,
    parent_path: str = "",
    depth: int = 0,
    parent: TreeNode | None = None,
) -> list[TreeNode]:
    """Convert nested dict tree to list of TreeNode objects."""
    nodes = []
    items = sorted(tree.items(), key=lambda x: (not isinstance(x[1], dict), x[0].lower()))

    for name, value in items:
        path = os.path.join(parent_path, name) if parent_path else name

        if isinstance(value, dict):
            # Directory
            node = TreeNode(
                name=name,
                path=path,
                is_dir=True,
                depth=depth,
                parent=parent,
            )
            node.children = build_tree_nodes(value, path, depth + 1, node)
            nodes.append(node)
        elif isinstance(value, FileOperation):
            # File
            node = TreeNode(
                name=name,
                path=value.path,
                is_dir=False,
                depth=depth,
                operation=value,
                parent=parent,
            )
            nodes.append(node)

    return nodes


def flatten_tree(nodes: list[TreeNode], include_collapsed: bool = False) -> list[TreeNode]:
    """Flatten tree to list, respecting expanded/collapsed state."""
    result = []
    for node in nodes:
        result.append(node)
        if node.is_dir and (node.expanded or include_collapsed):
            result.extend(flatten_tree(node.children, include_collapsed))
    return result


class FileTreeExplorer:
    """Interactive TUI for exploring file tree."""

    def __init__(
        self,
        tree_nodes: list[TreeNode],
        file_ops: dict[str, FileOperation],
        log_name: str,
        turn_desc: str,
        editor: str,
        compact: bool = False,
        watch_dir: Path | None = None,
        use_all_turns: bool = False,
        root_path: Path | None = None,
    ):
        self.root_nodes = tree_nodes
        self.file_ops = file_ops
        self.log_name = log_name
        self.turn_desc = turn_desc
        self.editor = editor
        self.compact = compact
        self.watch_dir = watch_dir
        self.use_all_turns = use_all_turns
        self.root_path = root_path
        self.current_log_dir: Path | None = None

        self.selected_index = 0
        self.search_input_mode = False  # Typing search query
        self.search_active = False  # Search committed, highlighting matches
        self.search_deep = False  # True for ? (deep), False for / (visible only)
        self.search_query = ""
        self.filtered_indices: list[int] = []
        self._cursor_line = 0

        # Watcher state
        self._watcher_running = False
        self._watcher_thread: threading.Thread | None = None
        self._app: Application | None = None
        self._last_update_time = ""

    def _reload_from_log_dir(self, log_dir: Path) -> bool:
        """Reload data from a log directory. Returns True if data changed."""
        if log_dir == self.current_log_dir:
            return False

        try:
            turns = parse_conversation(log_dir)
            if not turns:
                return False

            # Get file operations
            if self.use_all_turns:
                file_ops: dict[str, FileOperation] = {}
                for turn in turns:
                    for fp, op in turn.get_file_operations().items():
                        if fp not in file_ops:
                            file_ops[fp] = op
                        else:
                            file_ops[fp].was_read |= op.was_read
                            file_ops[fp].was_written |= op.was_written
                turn_desc = "all turns"
            else:
                file_ops = turns[-1].get_file_operations()
                turn_desc = f"turn {len(turns)}/{len(turns)}"

            if not file_ops:
                return False

            # Build tree
            root = self.root_path or Path.cwd()
            if self.compact:
                tree = build_tree_structure(file_ops, self.root_path)
            else:
                tree = (
                    get_full_tree(root, file_ops)
                    if root.exists()
                    else build_tree_structure(file_ops)
                )

            tree_nodes = build_tree_nodes(tree)

            # Update state
            self.root_nodes = tree_nodes
            self.file_ops = file_ops
            self.log_name = log_dir.name
            self.turn_desc = turn_desc
            self.current_log_dir = log_dir
            self._last_update_time = time.strftime("%H:%M:%S")

            # Reset navigation but keep view mode
            self.selected_index = 0
            self.search_active = False
            self.search_query = ""
            self.filtered_indices = []

            return True
        except Exception:
            return False

    def _watcher_loop(self):
        """Background thread that watches for new log directories."""
        while self._watcher_running:
            if self.watch_dir:
                latest = get_latest_log_dir(self.watch_dir)
                if latest and latest != self.current_log_dir:
                    if self._reload_from_log_dir(latest) and self._app:
                        self._app.invalidate()
            time.sleep(2)  # Check every 2 seconds

    def _get_visible_nodes(self) -> list[TreeNode]:
        """Get currently visible nodes based on expansion state."""
        all_nodes = flatten_tree(self.root_nodes)
        if self.compact:
            # In compact mode, only show nodes with touched files
            return [n for n in all_nodes if n.has_touched_files or n.is_dir]
        return all_nodes

    def _get_filtered_nodes(self) -> list[tuple[int, TreeNode]]:
        """Get nodes matching search filter."""
        visible = self._get_visible_nodes()
        if not self.search_query:
            return list(enumerate(visible))
        query = self.search_query.lower()
        return [(i, n) for i, n in enumerate(visible) if query in n.name.lower()]

    def _update_filtered_indices(self):
        """Update filtered indices based on search query."""
        self.filtered_indices = [i for i, _ in self._get_filtered_nodes()]

    def _expand_matching_paths(self):
        """For deep search: expand all directories containing matching nodes."""
        if not self.search_query:
            return
        query = self.search_query.lower()

        def expand_if_match(nodes: list[TreeNode]) -> bool:
            """Recursively check and expand if any descendant matches."""
            has_match = False
            for node in nodes:
                node_matches = query in node.name.lower()
                children_match = False
                if node.is_dir and node.children:
                    children_match = expand_if_match(node.children)
                    if children_match:
                        node.expanded = True
                if node_matches or children_match:
                    has_match = True
            return has_match

        expand_if_match(self.root_nodes)

    def _set_expanded_recursive(self, node: TreeNode, expanded: bool):
        """Recursively set expanded state for a node and all its children."""
        if node.is_dir:
            node.expanded = expanded
            for child in node.children:
                self._set_expanded_recursive(child, expanded)

    def run(self):
        """Run the TUI application."""
        kb = self._create_key_bindings()

        header = Window(
            FormattedTextControl(lambda: FormattedText(self._render_header())),
            height=Dimension(min=4, max=6),
        )
        body = Window(
            FormattedTextControl(
                lambda: FormattedText(self._render_tree()),
                get_cursor_position=lambda: Point(0, self._cursor_line),
            ),
        )
        footer = Window(
            FormattedTextControl(lambda: FormattedText(self._render_footer())),
            height=Dimension(min=3, max=3),
        )

        layout = Layout(HSplit([header, body, footer]))
        app = Application(layout=layout, key_bindings=kb, style=STYLE, full_screen=True)
        self._app = app

        # Start watcher thread if watching
        if self.watch_dir:
            self._watcher_running = True
            self._watcher_thread = threading.Thread(target=self._watcher_loop, daemon=True)
            self._watcher_thread.start()

        try:
            app.run()
        finally:
            # Stop watcher
            self._watcher_running = False
            if self._watcher_thread:
                self._watcher_thread.join(timeout=1)

    def _create_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        in_search_input = Condition(lambda: self.search_input_mode)

        @kb.add("q", filter=~in_search_input)
        def quit_app(e):
            e.app.exit()

        @kb.add("j", filter=~in_search_input)
        @kb.add("down", filter=~in_search_input)
        def move_down(e):
            visible = self._get_visible_nodes()
            if self.selected_index < len(visible) - 1:
                self.selected_index += 1

        @kb.add("k", filter=~in_search_input)
        @kb.add("up", filter=~in_search_input)
        def move_up(e):
            if self.selected_index > 0:
                self.selected_index -= 1

        @kb.add("n", filter=~in_search_input)
        def next_match(e):
            """Go to next search match."""
            if self.search_active and self.filtered_indices:
                if self.selected_index in self.filtered_indices:
                    curr = self.filtered_indices.index(self.selected_index)
                    next_idx = (curr + 1) % len(self.filtered_indices)
                    self.selected_index = self.filtered_indices[next_idx]
                elif self.filtered_indices:
                    # Find next match after current position
                    for idx in self.filtered_indices:
                        if idx > self.selected_index:
                            self.selected_index = idx
                            return
                    self.selected_index = self.filtered_indices[0]

        @kb.add("N", filter=~in_search_input)
        def prev_match(e):
            """Go to previous search match."""
            if self.search_active and self.filtered_indices:
                if self.selected_index in self.filtered_indices:
                    curr = self.filtered_indices.index(self.selected_index)
                    prev_idx = (curr - 1) % len(self.filtered_indices)
                    self.selected_index = self.filtered_indices[prev_idx]
                elif self.filtered_indices:
                    # Find prev match before current position
                    for idx in reversed(self.filtered_indices):
                        if idx < self.selected_index:
                            self.selected_index = idx
                            return
                    self.selected_index = self.filtered_indices[-1]

        @kb.add("tab", filter=~in_search_input)
        def toggle_fold(e):
            visible = self._get_visible_nodes()
            if 0 <= self.selected_index < len(visible):
                node = visible[self.selected_index]
                if node.is_dir:
                    node.expanded = not node.expanded

        @kb.add("enter", filter=~in_search_input)
        def open_file(e):
            visible = self._get_visible_nodes()
            if 0 <= self.selected_index < len(visible):
                node = visible[self.selected_index]
                if node.is_dir:
                    node.expanded = not node.expanded
                else:
                    # Open file in editor
                    try:
                        subprocess.Popen(
                            [self.editor, node.path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    except Exception:
                        pass

        @kb.add("enter", filter=in_search_input)
        def commit_search(e):
            """Commit search and switch to navigation mode."""
            self.search_input_mode = False
            self.search_active = bool(self.search_query)
            if self.search_deep and self.search_query:
                # Expand directories containing matches
                self._expand_matching_paths()
            self._update_filtered_indices()
            if self.filtered_indices:
                self.selected_index = self.filtered_indices[0]

        @kb.add("o", filter=~in_search_input)
        def expand_recursive(e):
            """Recursively expand selected directory and all children."""
            visible = self._get_visible_nodes()
            if 0 <= self.selected_index < len(visible):
                node = visible[self.selected_index]
                if node.is_dir:
                    self._set_expanded_recursive(node, True)

        @kb.add("c", filter=~in_search_input)
        def collapse_recursive(e):
            """Recursively collapse selected directory and all children."""
            visible = self._get_visible_nodes()
            if 0 <= self.selected_index < len(visible):
                node = visible[self.selected_index]
                if node.is_dir:
                    self._set_expanded_recursive(node, False)
                elif node.parent:
                    # If on a file, collapse parent directory
                    self._set_expanded_recursive(node.parent, False)
                    # Move cursor to parent
                    new_visible = self._get_visible_nodes()
                    for i, n in enumerate(new_visible):
                        if n is node.parent:
                            self.selected_index = i
                            break

        @kb.add("O", filter=~in_search_input)
        def expand_all(e):
            """Expand all directories."""
            for node in flatten_tree(self.root_nodes, include_collapsed=True):
                if node.is_dir:
                    node.expanded = True

        @kb.add("C", filter=~in_search_input)
        def collapse_all(e):
            """Collapse all directories to root level."""
            for node in flatten_tree(self.root_nodes, include_collapsed=True):
                if node.is_dir:
                    node.expanded = False
            # Reset cursor to top
            self.selected_index = 0

        @kb.add("v", filter=~in_search_input)
        def toggle_view(e):
            """Toggle between compact (touched only) and full view."""
            self.compact = not self.compact
            # Reset cursor to stay in bounds
            visible = self._get_visible_nodes()
            if self.selected_index >= len(visible):
                self.selected_index = max(0, len(visible) - 1)
            # Clear search when switching views
            self.search_active = False
            self.search_query = ""
            self.filtered_indices = []

        @kb.add("/", filter=~in_search_input)
        def start_search(e):
            """Start search in visible items only."""
            self.search_input_mode = True
            self.search_active = False
            self.search_deep = False
            self.search_query = ""
            self.filtered_indices = []

        @kb.add("?", filter=~in_search_input)
        def start_deep_search(e):
            """Start deep search through entire tree."""
            self.search_input_mode = True
            self.search_active = False
            self.search_deep = True
            self.search_query = ""
            self.filtered_indices = []

        @kb.add("escape")
        def cancel_search(e):
            self.search_input_mode = False
            self.search_active = False
            self.search_query = ""
            self.filtered_indices = []

        @kb.add("backspace", filter=in_search_input)
        def search_backspace(e):
            if self.search_query:
                self.search_query = self.search_query[:-1]
                self._update_filtered_indices()

        @kb.add("<any>", filter=in_search_input)
        def search_input(e):
            if e.data and len(e.data) == 1 and e.data.isprintable():
                self.search_query += e.data
                self._update_filtered_indices()

        @kb.add("c-c")
        @kb.add("c-d")
        def force_quit(e):
            e.app.exit()

        return kb

    def _render_header(self) -> list:
        view_mode = "COMPACT" if self.compact else "FULL"
        lines = [
            ("class:header", f" File Tree: {self.turn_desc} "),
            ("class:dim", f"({self.log_name}) "),
            ("class:count", f"[{view_mode}]"),
        ]

        # Watch indicator
        if self.watch_dir:
            lines.extend(
                [
                    ("class:dim", " "),
                    ("class:info", "[WATCHING]"),
                ]
            )
            if self._last_update_time:
                lines.append(("class:dim", f" @{self._last_update_time}"))

        lines.append(("", "\n"))

        # Summary
        read_only = sum(1 for op in self.file_ops.values() if op.was_read and not op.was_written)
        write_only = sum(1 for op in self.file_ops.values() if op.was_written and not op.was_read)
        both = sum(1 for op in self.file_ops.values() if op.was_read and op.was_written)
        lines.extend(
            [
                ("class:dim", "  "),
                ("class:read", f"Read: {read_only}"),
                ("class:dim", "  "),
                ("class:write", f"Written: {write_only}"),
                ("class:dim", "  "),
                ("class:both", f"Both: {both}"),
                ("class:dim", f"  Total: {len(self.file_ops)}\n"),
            ]
        )

        # Search bar
        if self.search_input_mode:
            search_type = "Deep Search" if self.search_deep else "Search"
            lines.extend(
                [
                    ("class:search-label", f"  {search_type}: "),
                    ("class:search-box", f" {self.search_query}█ "),
                    ("class:dim", " [Enter to commit]\n"),
                ]
            )
        elif self.search_active:
            match_pos = ""
            if self.selected_index in self.filtered_indices:
                pos = self.filtered_indices.index(self.selected_index) + 1
                match_pos = f" [{pos}/{len(self.filtered_indices)}]"
            prefix = "?" if self.search_deep else "/"
            lines.extend(
                [
                    ("class:search-label", f"  {prefix}{self.search_query}"),
                    (
                        "class:dim",
                        f" ({len(self.filtered_indices)} matches){match_pos} [n/N next/prev, Esc clear]\n",
                    ),
                ]
            )
        else:
            lines.append(("class:separator", "─" * 80 + "\n"))

        return lines

    def _render_tree(self) -> list:
        lines = []
        visible = self._get_visible_nodes()
        selected_line = 0

        for i, node in enumerate(visible):
            is_selected = i == self.selected_index
            is_match = self.search_active and i in self.filtered_indices

            if is_selected:
                selected_line = i

            # Indentation
            indent = "    " * node.depth

            # Build the line
            if node.is_dir:
                icon = "▼ " if node.expanded else "▶ "
                style = "class:dir" if node.expanded else "class:dir-collapsed"
                name_display = f"{node.name}/"
            else:
                icon = "  "
                # Determine style based on operation
                if node.operation:
                    if node.operation.was_read and node.operation.was_written:
                        style = "class:both"
                        marker = " [R+W]"
                    elif node.operation.was_written:
                        style = "class:write"
                        marker = " [W]"
                    elif node.operation.was_read:
                        style = "class:read"
                        marker = " [R]"
                    else:
                        style = "class:dim"
                        marker = ""
                else:
                    style = "class:dim"
                    marker = ""
                name_display = node.name + marker

            # Render line
            line_text = f"{indent}{icon}{name_display}"
            if is_selected and is_match:
                # Selected match - yellow background
                padded = line_text + " " * max(0, 100 - len(line_text))
                lines.append(("class:match-selected", padded + "\n"))
            elif is_selected:
                padded = line_text + " " * max(0, 100 - len(line_text))
                lines.append(("class:selected", padded + "\n"))
            elif is_match:
                # Highlighted match - yellow text
                lines.append(("class:tree", indent))
                lines.append(("class:match", f"{icon}{name_display}\n"))
            else:
                lines.append(("class:tree", indent))
                lines.append((style, f"{icon}{name_display}\n"))

        self._cursor_line = selected_line
        return lines

    def _render_footer(self) -> list:
        lines = [("class:separator", "─" * 80 + "\n")]
        if self.search_active:
            keys = [
                ("↑↓/jk", "nav"),
                ("n/N", "next/prev match"),
                ("Tab", "fold"),
                ("Enter", "open"),
                ("Esc", "clear search"),
                ("q", "quit"),
            ]
        else:
            keys = [
                ("↑↓/jk", "nav"),
                ("Tab", "fold"),
                ("Enter", "open"),
                ("o/c", "recursive"),
                ("O/C", "all"),
                ("v", "toggle view"),
                ("/", "search"),
                ("?", "deep"),
                ("q", "quit"),
            ]
        for key, desc in keys:
            lines.extend([("class:key", f" {key}"), ("class:key-desc", f" {desc} ")])
        lines.append(("", "\n"))
        lines.extend([("class:dim", f" Editor: {self.editor}\n")])
        return lines


@click.command()
@click.argument(
    "log_dir",
    type=click.Path(exists=True, path_type=Path),
    metavar="LOG_DIR",
)
@click.option(
    "-c",
    "--compact",
    is_flag=True,
    help="Show only files that were read/written (hide untouched files).",
)
@click.option(
    "-t",
    "--turn",
    type=int,
    metavar="N",
    help="Show files from turn N instead of the last turn. Use with --all to override.",
)
@click.option(
    "-r",
    "--root",
    type=click.Path(exists=True, path_type=Path),
    metavar="DIR",
    help="Root directory for the full tree view. Defaults to current working directory.",
)
@click.option(
    "-a",
    "--all",
    "use_all",
    is_flag=True,
    help="Aggregate file operations from all turns instead of just the last one.",
)
@click.option(
    "--tui",
    is_flag=True,
    help="Launch interactive TUI mode with vim-like navigation and search.",
)
@click.option(
    "-w",
    "--watch",
    is_flag=True,
    help="Watch for new logs and auto-update (implies --tui). Pass a session directory to monitor.",
)
@click.option(
    "-e",
    "--editor",
    type=str,
    default=os.environ.get("EDITOR", "code"),
    show_default=True,
    metavar="CMD",
    help="Editor command to open files in TUI mode (Enter key).",
)
def main(
    log_dir: Path,
    compact: bool,
    turn: int | None,
    root: Path | None,
    use_all: bool,
    tui: bool,
    watch: bool,
    editor: str,
) -> None:
    """Visualize files read/written during a conversation.

    Parses proxy logs and displays a tree view of files that were accessed
    (Read, Write, Edit operations) during the conversation.

    \b
    LOG_DIR can be:
      • A specific log directory (e.g., 001_173039_5msgs_...)
      • A session directory (when using --watch)

    \b
    Examples:
      # Show files from the last turn (compact view)
      visualize_files.py /path/to/log --compact

      # Show full directory tree with all files
      visualize_files.py /path/to/log

      # Interactive TUI mode
      visualize_files.py /path/to/log --tui

      # Watch a session for new logs (auto-updates)
      visualize_files.py /path/to/session --watch

      # Show files from all turns combined
      visualize_files.py /path/to/log --all --compact

    \b
    TUI Keybindings:
      ↑↓/jk    Navigate
      Tab      Toggle fold directory
      Enter    Open file in editor
      o/c      Recursive expand/collapse selected
      O/C      Expand/collapse all
      v        Toggle compact/full view
      /        Search visible items
      ?        Deep search (unfolds matches)
      n/N      Next/previous match
      q        Quit
    """
    # Determine the log directory and watch directory
    watch_dir = None
    actual_log_dir = log_dir

    if watch:
        # In watch mode, log_dir is the parent directory containing log subdirectories
        if log_dir.is_dir():
            # Check if it's a log directory or parent of log directories
            has_log_files = any(
                f.name.endswith(("_request.json", "_messages.json"))
                for f in log_dir.iterdir()
                if f.is_file()
            )
            if has_log_files:
                # It's a log directory, watch its parent
                watch_dir = log_dir.parent
                actual_log_dir = log_dir
            else:
                # It's a parent directory, find latest log
                watch_dir = log_dir
                actual_log_dir = get_latest_log_dir(watch_dir)
                if not actual_log_dir:
                    click.echo(f"Error: No log directories found in {watch_dir}", err=True)
                    sys.exit(1)
        tui = True  # Watch mode requires TUI

    if not actual_log_dir.exists():
        click.echo(f"Error: {actual_log_dir} not found", err=True)
        sys.exit(1)

    # Parse conversation
    turns = parse_conversation(actual_log_dir)
    if not turns:
        click.echo("No turns found in conversation", err=True)
        sys.exit(1)

    # Select turn(s)
    if use_all:
        file_ops: dict[str, FileOperation] = {}
        for t in turns:
            for fp, op in t.get_file_operations().items():
                if fp not in file_ops:
                    file_ops[fp] = op
                else:
                    file_ops[fp].was_read |= op.was_read
                    file_ops[fp].was_written |= op.was_written
        turn_desc = "all turns"
    else:
        turn_num = turn if turn else len(turns)
        if turn_num < 1 or turn_num > len(turns):
            click.echo(f"Error: Turn {turn_num} not found (have {len(turns)} turns)", err=True)
            sys.exit(1)
        selected_turn = turns[turn_num - 1]
        file_ops = selected_turn.get_file_operations()
        turn_desc = f"turn {turn_num}/{len(turns)}"

    if not file_ops:
        click.echo(f"No file operations found in {turn_desc}")
        sys.exit(0)

    # Build tree structure
    tree_root = root or Path.cwd()
    if compact:
        tree = build_tree_structure(file_ops, root)
    else:
        if not tree_root.exists():
            click.echo(f"Error: Root directory {tree_root} not found", err=True)
            sys.exit(1)
        tree = get_full_tree(tree_root, file_ops)

    # TUI mode
    if tui:
        tree_nodes = build_tree_nodes(tree)
        explorer = FileTreeExplorer(
            tree_nodes=tree_nodes,
            file_ops=file_ops,
            log_name=actual_log_dir.name,
            turn_desc=turn_desc,
            editor=editor,
            compact=compact,
            watch_dir=watch_dir,
            use_all_turns=use_all,
            root_path=root,
        )
        explorer.current_log_dir = actual_log_dir
        explorer.run()
        return

    # Static output mode
    header_lines = [
        ("class:header", f"Files from {turn_desc}"),
        ("class:dim", f" ({log_dir.name})\n"),
        ("", "\n"),
    ]
    print_formatted_text(FormattedText(header_lines), style=STYLE)
    print_summary(file_ops)

    if compact:
        lines = [("class:header", "Touched Files:\n"), ("class:dim", "─" * 40 + "\n")]
    else:
        lines = [
            ("class:header", "Directory Tree: "),
            ("class:info", f"{tree_root}\n"),
            ("class:dim", "─" * 40 + "\n"),
        ]

    render_tree(tree, compact, lines=lines)
    print_formatted_text(FormattedText(lines), style=STYLE)

    legend = [
        ("", "\n"),
        ("class:dim", "Legend: "),
        ("class:read", "[R]"),
        ("class:dim", " read  "),
        ("class:write", "[W]"),
        ("class:dim", " written  "),
        ("class:both", "[R+W]"),
        ("class:dim", " both\n"),
    ]
    print_formatted_text(FormattedText(legend), style=STYLE)


if __name__ == "__main__":
    main()
