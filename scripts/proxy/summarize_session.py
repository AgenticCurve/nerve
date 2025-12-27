#!/usr/bin/env python3
"""Analyze proxy logs with cluster and turn-based grouping.

Two-level hierarchy:
- Clusters: Requests grouped by time proximity
- Turns: Clusters grouped by the same user message
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import rich_click as click
from prompt_toolkit import Application
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from shared import (
    C,
    DRACULA,
    configure_rich_click,
    get_style,
    is_tool_result_only,
    truncate_oneline,
)

# Configure rich-click with option groups
configure_rich_click(
    option_groups={
        "main": [
            {
                "name": "Display Options",
                "options": ["--main-only", "--flat", "--no-summary"],
            },
            {
                "name": "Selection",
                "options": ["--turn", "--window"],
            },
            {
                "name": "Interactive Mode",
                "options": ["--tui", "--watch"],
            },
        ],
    }
)

# Use shared Dracula theme
STYLE = get_style(dark=True)


# Type colors mapping
TYPE_COLORS = {
    "CHAT": C.GREEN,
    "TOOL": C.YELLOW,  # Tool result only (no new user text)
    "AUX": C.CYAN,  # Auxiliary chat (haiku, bash confirmations, etc.)
    "AGENT": C.MAGENTA,
    "TOPIC": C.DIM,
    "QUOTA": C.DIM,
    "COUNT": C.DIM,
    "UNKNOWN": C.DIM,
}


# =============================================================================
# Data Types
# =============================================================================

RequestType = Literal["CHAT", "TOOL", "AUX", "AGENT", "TOPIC", "QUOTA", "COUNT", "UNKNOWN"]


@dataclass
class LogRequest:
    """Parsed log request."""

    seq: int
    timestamp: datetime
    msg_count: int
    preview: str
    path: Path
    request_type: RequestType = "UNKNOWN"
    model: str = ""
    last_user_msg: str = ""
    last_tool_call: str = ""  # Last tool call name for fallback grouping
    is_tool_result_only: bool = False  # True if most recent user msg was only tool_result

    @property
    def time_str(self) -> str:
        return self.timestamp.strftime("%H:%M:%S")


@dataclass
class Cluster:
    """A group of requests within a time window."""

    number: int
    requests: list[LogRequest] = field(default_factory=list)

    @property
    def timestamp(self) -> datetime:
        return self.requests[0].timestamp if self.requests else datetime.min

    @property
    def time_str(self) -> str:
        return self.timestamp.strftime("%H:%M:%S")

    def get_grouping_key(self) -> str:
        """Get the key for grouping this cluster into a turn.

        Prefers CHAT requests (main conversation), then falls back to
        any real user message, then last tool call.
        """
        # First, try to find a CHAT request with real user message
        for req in self.requests:
            if req.request_type == "CHAT" and req.last_user_msg and not req.is_tool_result_only:
                return req.last_user_msg

        # Second, try any request with a real user message
        for req in self.requests:
            if req.last_user_msg and not req.is_tool_result_only:
                return req.last_user_msg

        # Fallback: use the last tool call from any request
        for req in reversed(self.requests):
            if req.last_tool_call:
                return f"[tool:{req.last_tool_call}]"

        # Last resort: use preview from first request
        return self.requests[0].preview if self.requests else ""


@dataclass
class Turn:
    """A group of clusters sharing the same user message."""

    number: int
    user_message: str  # The shared user message (or tool call fallback)
    clusters: list[Cluster] = field(default_factory=list)

    @property
    def timestamp(self) -> datetime:
        return self.clusters[0].timestamp if self.clusters else datetime.min

    @property
    def time_str(self) -> str:
        return self.timestamp.strftime("%H:%M:%S")

    @property
    def all_requests(self) -> list[LogRequest]:
        """Get all requests across all clusters."""
        return [req for cluster in self.clusters for req in cluster.requests]


# =============================================================================
# Parsing
# =============================================================================


def parse_dir_name(name: str) -> tuple[int, datetime, int, str] | None:
    """Parse directory name like '001_173039_1msgs_quota'.

    Returns (seq, timestamp, msg_count, preview) or None if invalid.
    """
    # Pattern: SEQ_HHMMSS_NNmsgs_PREVIEW
    match = re.match(r"(\d+)_(\d{6})_(\d+)msgs_(.+)", name)
    if not match:
        return None

    seq = int(match.group(1))
    time_str = match.group(2)
    msg_count = int(match.group(3))
    preview = match.group(4).replace("_", " ")

    # Parse time (assume today's date for grouping purposes)
    try:
        hour = int(time_str[0:2])
        minute = int(time_str[2:4])
        second = int(time_str[4:6])
        timestamp = datetime.now().replace(hour=hour, minute=minute, second=second, microsecond=0)
    except (ValueError, IndexError):
        return None

    return seq, timestamp, msg_count, preview


def detect_request_type(log_dir: Path, preview: str) -> tuple[RequestType, str, str, str, bool]:
    """Detect request type by examining content.

    Returns (type, model, last_user_message, last_tool_call, is_tool_result_only).
    """
    # Quick checks based on directory name
    preview_lower = preview.lower()
    if "quota" in preview_lower:
        return "QUOTA", "", "", "", False
    if "count" in preview_lower:
        return "COUNT", "", "", "", False

    # Read request file to determine type
    request_file = log_dir / "1_request.json"
    if not request_file.exists():
        request_file = log_dir / "1_anthropic_request.json"
    if not request_file.exists():
        return "UNKNOWN", "", "", "", False

    try:
        with open(request_file, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return "UNKNOWN", "", "", "", False

    model = data.get("model", "")
    messages = data.get("messages", [])

    # Check if the MOST RECENT user message is only tool_result (no actual text)
    tool_result_only = False
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        tool_result_only = is_tool_result_only(content)
        break  # Only check the most recent user message

    # Extract last user message with actual text (skip tool_result blocks)
    last_user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            last_user_msg = content
            break
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    # Skip system reminders
                    if text and not text.startswith("<system-reminder>"):
                        last_user_msg = text
                        break
            if last_user_msg:
                break

    # Extract last tool call from assistant messages (for fallback grouping)
    last_tool_call = ""
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in reversed(content):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    last_tool_call = block.get("name", "")
                    break
        if last_tool_call:
            break

    # Check system prompt for type indicators
    system = data.get("system", [])
    system_text = ""
    if isinstance(system, str):
        system_text = system
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                system_text += block.get("text", "") + "\n"

    # Topic detection - short prompt with topic analysis instructions
    if "isNewTopic" in system_text or "new conversation topic" in system_text.lower():
        return "TOPIC", model, last_user_msg, last_tool_call, tool_result_only

    # Sub-agent detection based on specialized system prompts
    # Sub-agents have shorter, focused prompts with specialized intros
    # Main Claude Code prompts are ~14K+ chars with full boilerplate
    is_short_prompt = len(system_text) < 12000

    # Look for specialized agent intro patterns (but not in full Claude Code prompt)
    specialized_patterns = [
        "You are an elite",
        "You are a specialized",
        "Your mission is",
        "## Your Mission",
        "You are an expert",
        "specializing in",
        "Your expertise spans",
    ]

    # Full Claude Code prompt markers (if these are present, it's main chat)
    main_prompt_markers = [
        "# Looking up your own documentation",
        "# Tone and style",
        "# Doing tasks",
        "If the user asks for help or wants to give feedback",
    ]

    has_specialized_intro = any(p in system_text for p in specialized_patterns)
    has_full_boilerplate = any(m in system_text for m in main_prompt_markers)

    # It's a sub-agent if: shorter prompt + specialized intro + missing full boilerplate
    if is_short_prompt and has_specialized_intro and not has_full_boilerplate:
        return "AGENT", model, last_user_msg, last_tool_call, tool_result_only

    # Also detect by explicit sub-agent markers (rare but possible)
    if "You are a sub-agent" in system_text:
        return "AGENT", model, last_user_msg, last_tool_call, tool_result_only

    # Check if this looks like a tool/utility call (very short, single message)
    if len(messages) == 1 and len(system_text) < 500:
        return "UNKNOWN", model, last_user_msg, last_tool_call, tool_result_only

    # Main conversation with full Claude Code boilerplate (opus/sonnet)
    if has_full_boilerplate:
        if tool_result_only:
            # TOOL: user message was just tool result, no new user text
            return "TOOL", model, last_user_msg, last_tool_call, tool_result_only
        else:
            # CHAT: real user input
            return "CHAT", model, last_user_msg, last_tool_call, tool_result_only

    # Auxiliary chat: lacks full boilerplate (haiku, bash confirmations, etc.)
    # These are sidecars like permission prompts, command confirmations
    return "AUX", model, last_user_msg, last_tool_call, tool_result_only


def load_requests(session_dir: Path) -> list[LogRequest]:
    """Load and parse all request directories in a session."""
    requests = []

    for d in session_dir.iterdir():
        if not d.is_dir():
            continue

        parsed = parse_dir_name(d.name)
        if not parsed:
            continue

        seq, timestamp, msg_count, preview = parsed
        req_type, model, last_user_msg, last_tool_call, tool_result_only = detect_request_type(
            d, preview
        )

        requests.append(
            LogRequest(
                seq=seq,
                timestamp=timestamp,
                msg_count=msg_count,
                preview=preview,
                path=d,
                request_type=req_type,
                model=model,
                last_user_msg=last_user_msg,
                last_tool_call=last_tool_call,
                is_tool_result_only=tool_result_only,
            )
        )

    return sorted(requests, key=lambda r: r.seq)


# =============================================================================
# Grouping
# =============================================================================


def group_into_clusters(requests: list[LogRequest], window_seconds: int = 5) -> list[Cluster]:
    """Group requests into clusters based on time proximity.

    Requests are added to the current cluster if they're within window_seconds
    of the LAST request in the cluster (not the first).
    """
    if not requests:
        return []

    clusters: list[Cluster] = []
    current_cluster = Cluster(number=1, requests=[requests[0]])

    for req in requests[1:]:
        # Compare to the LAST request in the cluster, not the first
        last_req = current_cluster.requests[-1]
        time_diff = abs((req.timestamp - last_req.timestamp).total_seconds())

        if time_diff <= window_seconds:
            current_cluster.requests.append(req)
        else:
            clusters.append(current_cluster)
            current_cluster = Cluster(number=len(clusters) + 1, requests=[req])

    clusters.append(current_cluster)
    return clusters


def group_clusters_into_turns(clusters: list[Cluster]) -> list[Turn]:
    """Group clusters into turns based on main CHAT user messages.

    Only CHAT requests (main conversation with full Claude Code prompt)
    create new turns. AUX, AGENT, and tool-result-only clusters are
    grouped with the preceding turn.
    """
    if not clusters:
        return []

    turns: list[Turn] = []
    current_turn: Turn | None = None

    for cluster in clusters:
        # Check if this cluster has a main CHAT request with a real user message
        # Only CHAT (not AUX, AGENT, etc.) should create new turns
        has_main_chat_msg = any(
            req.request_type == "CHAT" and req.last_user_msg and not req.is_tool_result_only
            for req in cluster.requests
        )

        if has_main_chat_msg:
            # New main chat user message - start a new turn
            if current_turn is not None:
                turns.append(current_turn)
            key = cluster.get_grouping_key()
            current_turn = Turn(
                number=len(turns) + 1,
                user_message=key,
                clusters=[cluster],
            )
        elif current_turn is not None:
            # Non-main cluster (AUX, AGENT, tool-result) - add to current turn
            current_turn.clusters.append(cluster)
        else:
            # First cluster has no main chat (edge case)
            key = cluster.get_grouping_key()
            current_turn = Turn(
                number=1,
                user_message=key,
                clusters=[cluster],
            )

    if current_turn is not None:
        turns.append(current_turn)

    return turns


# =============================================================================
# Display
# =============================================================================


def print_request(req: LogRequest, indent: int = 2) -> None:
    """Print a single request."""
    pad = " " * indent
    type_color = TYPE_COLORS.get(req.request_type, C.WHITE)

    # Format preview - prefer last user message if available
    preview = req.last_user_msg or req.preview
    preview = truncate_oneline(preview, 50)

    # Use yellow for tool_result_only (not real user input), green otherwise
    preview_color = C.YELLOW if req.is_tool_result_only else C.GREEN

    print(
        f"{pad}{type_color}[{req.request_type:5}]{C.RESET} "
        f"{C.CYAN}{req.seq:03d}{C.RESET}  "
        f"{req.msg_count:3d}msgs  "
        f'{preview_color}"{preview}"{C.RESET}'
    )


def print_cluster(
    cluster: Cluster, show_types: set[RequestType] | None = None, indent: int = 4
) -> None:
    """Print a cluster with its requests."""
    # Filter requests if needed
    requests = cluster.requests
    if show_types:
        requests = [r for r in requests if r.request_type in show_types]

    if not requests:
        return

    # Cluster header
    pad = " " * indent
    print(f"{pad}{C.DIM}Cluster {cluster.number} ({cluster.time_str}){C.RESET}")

    for req in requests:
        print_request(req, indent=indent + 2)


def print_turn(turn: Turn, show_types: set[RequestType] | None = None) -> None:
    """Print a turn with its clusters."""
    # Check if any requests match the filter
    all_requests = turn.all_requests
    if show_types:
        all_requests = [r for r in all_requests if r.request_type in show_types]

    if not all_requests:
        return

    # Turn header with user message preview
    preview = truncate_oneline(turn.user_message, 60)
    print(f"\n{C.BOLD}Turn {turn.number}{C.RESET} ", end="")
    print(f"{C.DIM}{'─' * 50}{C.RESET}")
    print(f'  {C.GREEN}"{preview}"{C.RESET}')

    # Print clusters
    for cluster in turn.clusters:
        print_cluster(cluster, show_types)


def print_flat(requests: list[LogRequest], show_types: set[RequestType] | None = None) -> None:
    """Print requests in flat list format."""
    for req in requests:
        if show_types and req.request_type not in show_types:
            continue
        print_request(req, indent=0)


def print_summary(requests: list[LogRequest], clusters: list[Cluster], turns: list[Turn]) -> None:
    """Print summary statistics."""
    print(f"\n{C.BOLD}Summary{C.RESET}")
    print(f"{C.DIM}{'─' * 50}{C.RESET}")

    # Count by type
    type_counts: dict[str, int] = {}
    for req in requests:
        type_counts[req.request_type] = type_counts.get(req.request_type, 0) + 1

    print(f"  {len(requests)} requests in {len(clusters)} clusters across {len(turns)} turns")
    print()

    # Type breakdown
    print(f"  {C.BOLD}By type:{C.RESET}")
    for req_type in ["CHAT", "TOOL", "AUX", "AGENT", "TOPIC", "QUOTA", "COUNT", "UNKNOWN"]:
        count = type_counts.get(req_type, 0)
        if count > 0:
            color = TYPE_COLORS.get(req_type, C.WHITE)
            bar = "█" * min(count, 40)
            print(f"    {color}[{req_type:5}]{C.RESET} {count:3d}  {C.DIM}{bar}{C.RESET}")

    # Model breakdown
    model_counts: dict[str, int] = {}
    for req in requests:
        if req.model:
            # Shorten model name
            model = req.model.split("/")[-1]  # Remove provider prefix
            model_counts[model] = model_counts.get(model, 0) + 1

    if model_counts:
        print()
        print(f"  {C.BOLD}By model:{C.RESET}")
        for model, count in sorted(model_counts.items(), key=lambda x: -x[1]):
            print(f"    {C.CYAN}{model}{C.RESET}: {count}")


def print_turn_detail(turn: Turn) -> None:
    """Print detailed view of a single turn."""
    print(f"\n{C.BOLD}Turn {turn.number} ({turn.time_str}){C.RESET}")
    print(f"{C.DIM}{'═' * 60}{C.RESET}")

    # Show the user message for this turn
    preview = truncate_oneline(turn.user_message, 100)
    print(f'{C.GREEN}User: "{preview}"{C.RESET}')

    for cluster in turn.clusters:
        print(f"\n  {C.DIM}Cluster {cluster.number} ({cluster.time_str}){C.RESET}")
        print(f"  {C.DIM}{'─' * 40}{C.RESET}")

        for req in cluster.requests:
            type_color = TYPE_COLORS.get(req.request_type, C.WHITE)
            print(
                f"\n    {type_color}[{req.request_type}]{C.RESET} "
                f"{C.BOLD}Request {req.seq:03d}{C.RESET}"
            )
            print(f"      {C.DIM}Path:{C.RESET} {req.path}")
            print(f"      {C.DIM}Messages:{C.RESET} {req.msg_count}")
            if req.model:
                print(f"      {C.DIM}Model:{C.RESET} {req.model}")
            if req.last_user_msg:
                msg_preview = truncate_oneline(req.last_user_msg, 80)
                print(f'      {C.DIM}User:{C.RESET} "{msg_preview}"')
            if req.last_tool_call:
                print(f"      {C.DIM}Tool:{C.RESET} {req.last_tool_call}")


# =============================================================================
# Watch Mode
# =============================================================================


def get_latest_log_dir(parent_dir: Path) -> Path | None:
    """Get the latest log directory from parent (sorted by name which includes timestamp)."""
    if not parent_dir.exists() or not parent_dir.is_dir():
        return None
    subdirs = [d for d in parent_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if not subdirs:
        return None
    # Sort by name (format: NNN_HHMMSS_Nmsgs_...) - latest is last
    return sorted(subdirs, key=lambda d: d.name)[-1]


# =============================================================================
# TUI Mode
# =============================================================================


# TUI style mappings (prompt_toolkit uses different style names)
TUI_TYPE_STYLES = {
    "CHAT": "class:green",
    "TOOL": "class:yellow",
    "AUX": "class:cyan",
    "AGENT": "class:magenta",
    "TOPIC": "class:dim",
    "QUOTA": "class:dim",
    "COUNT": "class:dim",
    "UNKNOWN": "class:dim",
}


class SessionExplorer:
    """Interactive TUI for exploring session turns and clusters."""

    def __init__(
        self,
        turns: list[Turn],
        clusters: list[Cluster],
        requests: list[LogRequest],
        session_name: str,
        window_seconds: int = 5,
        main_only: bool = False,
        watch_dir: Path | None = None,
    ):
        self.turns = turns
        self.clusters = clusters
        self.requests = requests
        self.session_name = session_name
        self.window_seconds = window_seconds
        self.main_only = main_only
        self.watch_dir = watch_dir

        # Navigation state
        self.selected_turn_idx = 0
        self._cursor_line = 0

        # Expansion state
        self.expanded_turns: set[int] = set()  # Turn numbers that are expanded
        self.expanded_clusters: set[tuple[int, int]] = set()  # (turn_num, cluster_idx)

        # Watcher state
        self._watcher_running = False
        self._watcher_thread: threading.Thread | None = None
        self._app: Application | None = None
        self._last_update_time = ""

    def _reload_session(self) -> bool:
        """Reload data from the session directory. Returns True if data changed."""
        if not self.watch_dir:
            return False

        try:
            requests = load_requests(self.watch_dir)
            if not requests:
                return False

            # Check if anything changed (compare request count and last seq)
            if (
                self.requests  # Ensure not empty before accessing [-1]
                and len(requests) == len(self.requests)
                and requests[-1].seq == self.requests[-1].seq
            ):
                return False

            clusters = group_into_clusters(requests, window_seconds=self.window_seconds)
            turns = group_clusters_into_turns(clusters)

            # Update state
            self.requests = requests
            self.clusters = clusters
            self.turns = turns
            self._last_update_time = time.strftime("%H:%M:%S")

            # Keep navigation in bounds
            items = self._get_visible_items()
            if self.selected_turn_idx >= len(items):
                self.selected_turn_idx = max(0, len(items) - 1)

            return True
        except Exception:
            return False

    def _watcher_loop(self):
        """Background thread that watches for new requests in the session."""
        while self._watcher_running:
            if self.watch_dir:
                if self._reload_session() and self._app:
                    self._app.invalidate()
            time.sleep(2)  # Check every 2 seconds

    def _get_filtered_requests(self, requests: list[LogRequest]) -> list[LogRequest]:
        """Filter requests based on main_only setting."""
        if self.main_only:
            return [r for r in requests if r.request_type in ("CHAT", "AGENT")]
        return requests

    def _get_visible_items(self) -> list[tuple[str, Turn | Cluster | LogRequest, int]]:
        """Get list of visible items based on expansion state.

        Returns list of (type, item, depth) tuples where type is 'turn', 'cluster', or 'request'.
        """
        items: list[tuple[str, Turn | Cluster | LogRequest, int]] = []

        for turn in self.turns:
            # Check if turn has any visible requests
            all_reqs = turn.all_requests
            filtered_reqs = self._get_filtered_requests(all_reqs)
            if not filtered_reqs:
                continue

            items.append(("turn", turn, 0))

            if turn.number in self.expanded_turns:
                for cluster_idx, cluster in enumerate(turn.clusters):
                    cluster_reqs = self._get_filtered_requests(cluster.requests)
                    if not cluster_reqs:
                        continue

                    items.append(("cluster", cluster, 1))

                    if (turn.number, cluster_idx) in self.expanded_clusters:
                        for req in cluster_reqs:
                            items.append(("request", req, 2))

        return items

    def _get_selected_item(self) -> tuple[str, Turn | Cluster | LogRequest] | None:
        """Get currently selected item."""
        items = self._get_visible_items()
        if 0 <= self.selected_turn_idx < len(items):
            item_type, item, _ = items[self.selected_turn_idx]
            return (item_type, item)
        return None

    def run(self):
        """Run the TUI application."""
        kb = self._create_key_bindings()

        header = Window(
            FormattedTextControl(lambda: FormattedText(self._render_header())),
            height=Dimension(min=4, max=6),
        )
        body = Window(
            FormattedTextControl(
                lambda: FormattedText(self._render_body()),
                get_cursor_position=lambda: Point(0, self._cursor_line),
            ),
        )
        footer = Window(
            FormattedTextControl(lambda: FormattedText(self._render_footer())),
            height=Dimension(min=2, max=2),
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

        @kb.add("q")
        def quit_app(e):
            e.app.exit()

        @kb.add("j")
        @kb.add("down")
        def move_down(e):
            items = self._get_visible_items()
            if self.selected_turn_idx < len(items) - 1:
                self.selected_turn_idx += 1

        @kb.add("k")
        @kb.add("up")
        def move_up(e):
            if self.selected_turn_idx > 0:
                self.selected_turn_idx -= 1

        @kb.add("tab")
        @kb.add("enter")
        def toggle_expand(e):
            items = self._get_visible_items()
            if 0 <= self.selected_turn_idx < len(items):
                item_type, item, _ = items[self.selected_turn_idx]
                if item_type == "turn":
                    turn = item
                    if turn.number in self.expanded_turns:
                        self.expanded_turns.discard(turn.number)
                        # Also collapse all clusters in this turn
                        self.expanded_clusters = {
                            (t, c) for t, c in self.expanded_clusters if t != turn.number
                        }
                    else:
                        self.expanded_turns.add(turn.number)
                elif item_type == "cluster":
                    cluster = item
                    # Find which turn this cluster belongs to
                    for turn in self.turns:
                        for cidx, c in enumerate(turn.clusters):
                            if c is cluster:
                                key = (turn.number, cidx)
                                if key in self.expanded_clusters:
                                    self.expanded_clusters.discard(key)
                                else:
                                    self.expanded_clusters.add(key)
                                return

        @kb.add("o")
        def expand_all(e):
            """Expand all turns and clusters."""
            for turn in self.turns:
                self.expanded_turns.add(turn.number)
                for cidx in range(len(turn.clusters)):
                    self.expanded_clusters.add((turn.number, cidx))

        @kb.add("c")
        def collapse_all(e):
            """Collapse all turns and clusters."""
            self.expanded_turns.clear()
            self.expanded_clusters.clear()
            self.selected_turn_idx = 0

        @kb.add("m")
        def toggle_main_only(e):
            """Toggle main-only filter."""
            self.main_only = not self.main_only
            # Reset selection if out of bounds
            items = self._get_visible_items()
            if self.selected_turn_idx >= len(items):
                self.selected_turn_idx = max(0, len(items) - 1)

        @kb.add("g")
        def go_to_top(e):
            """Go to first item."""
            self.selected_turn_idx = 0

        @kb.add("G")
        def go_to_bottom(e):
            """Go to last item."""
            items = self._get_visible_items()
            self.selected_turn_idx = max(0, len(items) - 1)

        @kb.add("c-c")
        @kb.add("c-d")
        def force_quit(e):
            e.app.exit()

        return kb

    def _render_header(self) -> list:
        view_mode = "MAIN ONLY" if self.main_only else "ALL"
        lines = [
            ("class:header", f" Session: {self.session_name} "),
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

        # Summary line
        lines.extend(
            [
                ("class:dim", "  "),
                ("class:info", f"{len(self.requests)} requests"),
                ("class:dim", " in "),
                ("class:info", f"{len(self.clusters)} clusters"),
                ("class:dim", " across "),
                ("class:info", f"{len(self.turns)} turns"),
                ("", "\n"),
            ]
        )

        # Type breakdown
        type_counts: dict[str, int] = {}
        for req in self.requests:
            type_counts[req.request_type] = type_counts.get(req.request_type, 0) + 1

        lines.append(("class:dim", "  "))
        for req_type in ["CHAT", "TOOL", "AUX", "AGENT"]:
            count = type_counts.get(req_type, 0)
            if count > 0:
                style = TUI_TYPE_STYLES.get(req_type, "class:dim")
                lines.append((style, f"{req_type}:{count} "))

        lines.append(("", "\n"))
        lines.append(("class:separator", "─" * 80 + "\n"))

        return lines

    def _render_body(self) -> list:
        lines: list[tuple[str, str]] = []
        items = self._get_visible_items()

        for idx, (item_type, item, depth) in enumerate(items):
            is_selected = idx == self.selected_turn_idx
            indent = "  " * depth

            if is_selected:
                self._cursor_line = idx

            if item_type == "turn":
                turn = item
                is_expanded = turn.number in self.expanded_turns
                icon = "▼ " if is_expanded else "▶ "
                preview = truncate_oneline(turn.user_message, 60)
                req_count = len(self._get_filtered_requests(turn.all_requests))
                cluster_count = len(
                    [c for c in turn.clusters if self._get_filtered_requests(c.requests)]
                )

                line = f'{indent}{icon}Turn {turn.number} ({req_count} reqs, {cluster_count} clusters) "{preview}"'
                if is_selected:
                    padded = line + " " * max(0, 100 - len(line))
                    lines.append(("class:selected", padded + "\n"))
                else:
                    lines.append(("class:header", f"{indent}{icon}Turn {turn.number} "))
                    lines.append(("class:dim", f"({req_count} reqs, {cluster_count} clusters) "))
                    lines.append(("class:green", f'"{preview}"\n'))

            elif item_type == "cluster":
                cluster = item
                # Find if expanded
                is_expanded = False
                for turn in self.turns:
                    for cidx, c in enumerate(turn.clusters):
                        if c is cluster and (turn.number, cidx) in self.expanded_clusters:
                            is_expanded = True
                            break

                icon = "▼ " if is_expanded else "▶ "
                req_count = len(self._get_filtered_requests(cluster.requests))

                line = (
                    f"{indent}{icon}Cluster {cluster.number} ({cluster.time_str}, {req_count} reqs)"
                )
                if is_selected:
                    padded = line + " " * max(0, 100 - len(line))
                    lines.append(("class:selected", padded + "\n"))
                else:
                    lines.append(("class:dim", f"{indent}{icon}"))
                    lines.append(("class:info", f"Cluster {cluster.number} "))
                    lines.append(("class:dim", f"({cluster.time_str}, {req_count} reqs)\n"))

            elif item_type == "request":
                req = item
                style = TUI_TYPE_STYLES.get(req.request_type, "class:dim")
                preview = truncate_oneline(req.last_user_msg or req.preview, 45)

                line = f'{indent}[{req.request_type:5}] {req.seq:03d}  {req.msg_count:3d}msgs  "{preview}"'
                if is_selected:
                    padded = line + " " * max(0, 100 - len(line))
                    lines.append(("class:selected", padded + "\n"))
                else:
                    lines.append(("class:dim", f"{indent}"))
                    lines.append((style, f"[{req.request_type:5}] "))
                    lines.append(("class:cyan", f"{req.seq:03d}  "))
                    lines.append(("class:dim", f"{req.msg_count:3d}msgs  "))
                    preview_style = "class:yellow" if req.is_tool_result_only else "class:green"
                    lines.append((preview_style, f'"{preview}"\n'))

        return lines

    def _render_footer(self) -> list:
        lines = [("class:separator", "─" * 80 + "\n")]
        keys = [
            ("↑↓/jk", "nav"),
            ("Tab/Enter", "expand"),
            ("o/c", "all"),
            ("m", "filter"),
            ("g/G", "top/end"),
            ("q", "quit"),
        ]
        for key, desc in keys:
            lines.extend([("class:key", f" {key}"), ("class:key-desc", f" {desc} ")])
        lines.append(("", "\n"))
        return lines


# =============================================================================
# Main
# =============================================================================


@click.command()
@click.argument(
    "session_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    metavar="SESSION_DIR",
)
@click.option(
    "-m",
    "--main-only",
    is_flag=True,
    help="Show only main conversation requests (CHAT + AGENT), hiding sidecars like TOPIC, QUOTA, COUNT.",
)
@click.option(
    "-f",
    "--flat",
    is_flag=True,
    help="Show flat list without turn-based grouping.",
)
@click.option(
    "-t",
    "--turn",
    type=int,
    metavar="N",
    help="Show detailed view for turn N (paths, models, full messages).",
)
@click.option(
    "-w",
    "--window",
    type=int,
    default=5,
    show_default=True,
    metavar="SECS",
    help="Time window in seconds for grouping requests into clusters.",
)
@click.option(
    "--no-summary",
    is_flag=True,
    help="Hide the summary statistics at the end.",
)
@click.option(
    "--tui",
    is_flag=True,
    help="Launch interactive TUI mode with vim-like navigation.",
)
@click.option(
    "--watch",
    is_flag=True,
    help="Watch session for new requests and auto-update (implies --tui).",
)
def main(
    session_dir: Path,
    main_only: bool,
    flat: bool,
    turn: int | None,
    window: int,
    no_summary: bool,
    tui: bool,
    watch: bool,
) -> None:
    """Analyze proxy session logs with cluster and turn-based grouping.

    Two-level hierarchy:
      - Clusters: Requests grouped by time proximity (--window)
      - Turns: Clusters grouped by shared user message

    \b
    SESSION_DIR is a proxy session directory containing request subdirectories:
      - 001_173039_1msgs_quota/
      - 002_173040_5msgs_Please_write.../
      - etc.

    \b
    Request Types:
      CHAT   - Main conversation with real user input (opus/sonnet, green)
      TOOL   - Tool result only, no new user text (yellow)
      AUX    - Auxiliary chat (haiku, bash confirmations, cyan)
      AGENT  - Sub-agent calls (magenta)
      TOPIC  - Topic detection sidecars (dim)
      QUOTA  - Quota check requests (dim)
      COUNT  - Token counting requests (dim)

    \b
    Examples:
      # Show grouped view (default)
      summarize_session.py /path/to/session

      # Show only main conversation (hide sidecars)
      summarize_session.py /path/to/session --main-only

      # Flat chronological list
      summarize_session.py /path/to/session --flat

      # Show details for turn 3
      summarize_session.py /path/to/session --turn 3

      # Use 10-second cluster window
      summarize_session.py /path/to/session --window 10

      # Interactive TUI mode
      summarize_session.py /path/to/session --tui

      # Watch session for new requests (auto-updates TUI)
      summarize_session.py /path/to/session --watch

    \b
    Output Legend:
      [CHAT]   Main conversation
      [AGENT]  Sub-agent/sidecar
      NNNmsgs  Number of messages in request
      Green    Real user input
      Yellow   Tool result (no new user text)

    \b
    TUI Keybindings:
      ↑↓/jk      Navigate
      Tab/Enter  Toggle expand/collapse
      o/c        Expand/collapse all
      m          Toggle main-only filter
      g/G        Go to top/bottom
      q          Quit
    """
    # Watch mode implies TUI
    if watch:
        tui = True

    # Load requests
    requests = load_requests(session_dir)
    if not requests:
        click.echo(f"No valid log directories found in {session_dir}", err=True)
        sys.exit(1)

    # Group into clusters (by time), then into turns (by user message)
    clusters = group_into_clusters(requests, window_seconds=window)
    turns = group_clusters_into_turns(clusters)

    # TUI mode
    if tui:
        explorer = SessionExplorer(
            turns=turns,
            clusters=clusters,
            requests=requests,
            session_name=session_dir.name,
            window_seconds=window,
            main_only=main_only,
            watch_dir=session_dir if watch else None,
        )
        explorer.run()
        return

    # Filter types if needed
    show_types: set[RequestType] | None = None
    if main_only:
        show_types = {"CHAT", "AGENT"}

    # Header
    print(f"{C.BOLD}Session: {session_dir.name}{C.RESET}")

    # Display based on mode
    if turn:
        if turn < 1 or turn > len(turns):
            click.echo(f"Error: Turn {turn} not found (valid: 1-{len(turns)})", err=True)
            sys.exit(1)
        print_turn_detail(turns[turn - 1])
    elif flat:
        print()
        print_flat(requests, show_types)
    else:
        for t in turns:
            print_turn(t, show_types)

    # Summary
    if not no_summary and not turn:
        print_summary(requests, clusters, turns)


if __name__ == "__main__":
    main()
