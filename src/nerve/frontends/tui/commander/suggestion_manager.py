"""Suggestion management for Commander TUI.

Handles fetching, storing, and cycling through AI-generated command suggestions.
Interfaces with a suggestion node to generate context-aware recommendations.

This module extracts suggestion-related logic from commander.py for better
separation of concerns and testability.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML

if TYPE_CHECKING:
    from prompt_toolkit import PromptSession

    from nerve.frontends.cli.repl.adapters import RemoteSessionAdapter
    from nerve.frontends.tui.commander.blocks import Block, Timeline
    from nerve.frontends.tui.commander.entity_manager import EntityInfo

logger = logging.getLogger(__name__)


class PrefixAutoSuggest(AutoSuggest):
    """Auto-suggest that shows remaining text when buffer is a prefix of suggestion."""

    def __init__(self, get_suggestion: Callable[[], str]) -> None:
        """Initialize with a callable that returns the current suggestion."""
        self._get_suggestion = get_suggestion

    def get_suggestion(self, buffer: Buffer, document: Document) -> Suggestion | None:
        """Return remaining suggestion if current text is a prefix."""
        text = document.text
        suggestion = self._get_suggestion()
        if text and suggestion.startswith(text) and text != suggestion:
            return Suggestion(suggestion[len(text) :])
        return None


@dataclass
class SuggestionManager:
    """Manages AI-generated command suggestions for the Commander TUI.

    Fetches suggestions from a dedicated suggestion node, stores them,
    and provides methods for cycling through and accepting suggestions.

    Example:
        >>> manager = SuggestionManager(entities, timeline, adapter)
        >>> manager.trigger_fetch()  # Start background fetch
        >>> current = manager.get_current()  # Get current suggestion
        >>> manager.cycle_next()  # Move to next suggestion
    """

    # References (not owned, just references)
    entities: dict[str, EntityInfo]
    timeline: Timeline
    adapter: RemoteSessionAdapter | None

    # Configuration
    suggestion_node: str = "suggestions"

    # State
    suggestions: list[str] = field(default_factory=list)
    current_idx: int = field(default=-1)  # -1 = show hint, 0+ = show suggestion
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _prompt_session: PromptSession[str] | None = field(default=None, init=False)

    # Callback for entity sync (since we don't own entities)
    _sync_entities: Callable[[], Any] | None = field(default=None, init=False)

    def set_prompt_session(self, session: PromptSession[str]) -> None:
        """Set the prompt session for invalidation on suggestion updates."""
        self._prompt_session = session

    def set_sync_callback(self, callback: Callable[[], Any]) -> None:
        """Set callback to sync entities when suggestion node not found."""
        self._sync_entities = callback

    def get_current(self) -> str:
        """Get the current suggestion based on index, or empty if showing hint."""
        if self.current_idx < 0 or not self.suggestions:
            return ""
        return self.suggestions[self.current_idx]

    def get_placeholder(self) -> HTML:
        """Get placeholder HTML - hint when no selection, suggestion otherwise."""
        if self.current_idx < 0 or not self.suggestions:
            return HTML("<placeholder>Tab to cycle suggestions</placeholder>")
        return HTML(f"<placeholder>{html.escape(self.get_current())}</placeholder>")

    def is_active(self, buffer_text: str) -> bool:
        """Check if a suggestion is selected and text is a prefix of it."""
        if self.current_idx < 0 or not self.suggestions:
            return False
        suggestion = self.get_current()
        return suggestion.startswith(buffer_text) and buffer_text != suggestion

    def is_buffer_empty(self, buffer_text: str) -> bool:
        """Check if buffer is empty (for cycling suggestions)."""
        return not buffer_text

    def cycle_next(self) -> None:
        """Cycle to next suggestion, or show first if available."""
        if not self.suggestions:
            return
        if self.current_idx < 0:
            self.current_idx = 0
        else:
            self.current_idx = (self.current_idx + 1) % len(self.suggestions)

    def cycle_prev(self) -> None:
        """Cycle to previous suggestion."""
        if not self.suggestions:
            return
        if self.current_idx < 0:
            self.current_idx = len(self.suggestions) - 1
        else:
            self.current_idx = (self.current_idx - 1) % len(self.suggestions)

    def get_next_word(self, buffer_text: str) -> str:
        """Get the next word from suggestion to insert."""
        suggestion = self.get_current()
        remaining = suggestion[len(buffer_text) :]
        # Find next word boundary (space or end)
        space_idx = remaining.find(" ")
        if space_idx == -1:
            return remaining  # Rest of suggestion
        return remaining[: space_idx + 1]  # Include the space

    def get_remaining(self, buffer_text: str) -> str:
        """Get all remaining text from suggestion."""
        return self.get_current()[len(buffer_text) :]

    def get_auto_suggest(self) -> PrefixAutoSuggest:
        """Create an AutoSuggest instance that uses this manager."""
        return PrefixAutoSuggest(self.get_current)

    def _gather_context(self) -> dict[str, Any]:
        """Gather context for the suggestion node.

        Collects:
        - nodes: list of node IDs (excluding 'suggestions' node)
        - graphs: list of graph IDs
        - workflows: list of workflow IDs
        - blocks: list of block dicts with input/output/success (excluding suggestion blocks)
        - cwd: current working directory

        Returns:
            Context dict ready to send to SuggestionNode.
        """
        # Gather entities by type (exclude 'suggestions' node - AI shouldn't predict itself)
        nodes = [e.id for e in self.entities.values() if e.type == "node" and e.id != "suggestions"]
        graphs = [e.id for e in self.entities.values() if e.type == "graph"]
        workflows = [e.id for e in self.entities.values() if e.type == "workflow"]

        # Gather blocks from timeline (exclude suggestion blocks)
        blocks = []
        for block in self.timeline.blocks:
            if block.status == "completed" and block.node_id != "suggestions":
                blocks.append(
                    {
                        "input": block.input_text,
                        "output": block.output_text,
                        "success": block.error is None,
                        "error": block.error,
                    }
                )

        return {
            "nodes": nodes,
            "graphs": graphs,
            "workflows": workflows,
            "blocks": blocks,
            "cwd": os.getcwd(),
        }

    async def fetch(self) -> None:
        """Fetch suggestions from the suggestion node in background.

        Updates suggestions list with new suggestions from the LLM.
        Falls back to keeping existing suggestions if node unavailable or errors.
        """
        if self.adapter is None:
            return

        # Check if suggestion node exists
        if self.suggestion_node not in self.entities:
            if self._sync_entities is not None:
                await self._sync_entities()
            if self.suggestion_node not in self.entities:
                return  # Node not available, keep current suggestions

        try:
            context = self._gather_context()
            result = await self.adapter.execute_on_node(self.suggestion_node, json.dumps(context))

            if result.get("success"):
                output = result.get("output", [])
                if isinstance(output, list) and output:
                    self.suggestions = output
                    self.current_idx = 0  # Show first suggestion immediately
                    # Invalidate prompt to trigger redraw with new suggestion
                    if self._prompt_session is not None and self._prompt_session.app is not None:
                        self._prompt_session.app.invalidate()
        except Exception as e:
            # Keep existing suggestions on error
            logger.debug("Failed to fetch suggestions: %s", e)

    def trigger_fetch(self) -> None:
        """Trigger background fetch of suggestions.

        Cancels any existing fetch and starts a new one.
        Called after commands complete to refresh suggestions.
        """
        # Cancel existing task if running
        if self._task is not None and not self._task.done():
            self._task.cancel()
            # Suppress CancelledError - task is intentionally being replaced
            self._task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

        # Start new fetch task
        self._task = asyncio.create_task(self.fetch())

    def on_block_complete(self, block: Block) -> None:
        """Callback when any block completes execution.

        Triggers suggestion refresh unless it's a suggestion block.

        Args:
            block: The completed block.
        """
        # Skip suggestion refresh for suggestion blocks (avoid recursion)
        if block.node_id == "suggestions":
            return
        self.trigger_fetch()

    async def cleanup(self) -> None:
        """Cancel any pending suggestion fetch task."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
