"""SuggestionRecord - data model for tracking suggestion interactions.

Captures the complete record of suggestion generation and user response,
enabling ML training, analytics, and debugging.

Key data captured:
- Context sent to LLM (blocks, entities, cwd)
- LLM request/response (messages, model, params, usage)
- Suggestions generated and parsed
- User viewing behavior (cycling through suggestions)
- User's final action and match type

Storage:
- Block metadata: Lightweight subset for timeline persistence
- JSONL file: Full self-contained record for ML training
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SuggestionRecord:
    """Complete record of suggestion generation and user response.

    Captures the full ML training pipeline:
    - What context was sent to the LLM
    - What the LLM returned (full request/response)
    - How the user interacted with suggestions
    - What the user ultimately did

    Example:
        >>> record = SuggestionRecord(
        ...     context={"blocks": [...], "nodes": [...]},
        ...     suggestions=["@claude explain", "@bash ls"],
        ... )
        >>> record.track_cycle(1)  # User cycled to suggestion 1
        >>> record.finalize("@claude explain", result_block_number=5)
        >>> record.match_type
        'exact'
    """

    # === Context Sent to LLM ===
    context: dict[str, Any] = field(default_factory=dict)
    # Structure:
    # {
    #     "nodes": ["claude", "bash", ...],
    #     "graphs": ["pipeline", ...],
    #     "workflows": ["debug", ...],
    #     "blocks": [
    #         {"input": "...", "output": "...", "success": True, "error": None},
    #         ...
    #     ],
    #     "cwd": "/path/to/project"
    # }

    # === LLM Request (what was sent to the model) ===
    llm_request: dict[str, Any] | None = None
    # Structure:
    # {
    #     "messages": [{"role": "system", "content": "..."}, ...],
    #     "model": "gpt-4o-mini",
    #     "temperature": 0.7,
    #     "max_tokens": 256,
    #     ... any other params passed to the LLM
    # }

    # === LLM Response (what came back) ===
    llm_response: dict[str, Any] | None = None
    # Structure:
    # {
    #     "raw_content": "1. @claude explain...",
    #     "model": "gpt-4o-mini",
    #     "usage": {"prompt_tokens": 150, "completion_tokens": 50, ...},
    #     "finish_reason": "stop",
    #     "latency_ms": 234.5,
    # }

    # === Suggestion Node Metadata ===
    suggestion_node_version: str | None = None

    # === Suggestions Returned ===
    suggestions: list[str] = field(default_factory=list)

    # === User Viewing Behavior ===
    cycle_count: int = 0
    viewed_indices: list[int] = field(default_factory=list)
    # Order preserved, may contain duplicates if user cycled back.
    # Example: [0, 1, 2, 1, 0] means user cycled forward then back.
    displayed_index_at_submit: int = -1  # Which suggestion was showing (-1 = hint)

    # === User Selection ===
    accepted_index: int | None = None  # Which suggestion picked (None = typed manually)
    actual_input: str = ""  # What user actually submitted
    match_type: str = "none"  # "exact", "partial", "prefix", "none"

    # === Timing ===
    fetch_start_ts: float = 0.0  # When fetch() started (monotonic)
    fetch_end_ts: float = 0.0  # When suggestions arrived (monotonic)
    submit_ts: float = 0.0  # When user submitted input (monotonic)
    time_to_action_ms: float = 0.0  # submit - fetch_end (user thinking time)

    # === Session Context ===
    session_name: str = ""
    server_name: str = ""
    trigger_block_number: int = -1  # Block that triggered fetch
    result_block_number: int | None = None  # Block created from user input
    context_block_count: int = 0  # How many blocks were in context

    def track_cycle(self, new_index: int) -> None:
        """Track that user cycled to a new suggestion index.

        Args:
            new_index: The index user is now viewing.
        """
        self.cycle_count += 1
        self.viewed_indices.append(new_index)

    def finalize(
        self,
        actual_input: str,
        result_block_number: int | None,
        displayed_index: int,
    ) -> None:
        """Finalize the record when user submits input.

        Args:
            actual_input: What the user typed/submitted.
            result_block_number: Block number created (None for : commands).
            displayed_index: Which suggestion was showing at submit time.
        """
        self.actual_input = actual_input
        self.submit_ts = time.monotonic()
        # Guard against unset fetch_end_ts (defensive - shouldn't happen in normal flow)
        if self.fetch_end_ts > 0:
            self.time_to_action_ms = (self.submit_ts - self.fetch_end_ts) * 1000
        else:
            self.time_to_action_ms = 0.0
        self.displayed_index_at_submit = displayed_index
        self.result_block_number = result_block_number

        # Classify match
        self.match_type, self.accepted_index = self._classify_match(actual_input, self.suggestions)

    def _classify_match(self, actual: str, suggestions: list[str]) -> tuple[str, int | None]:
        """Classify how user input relates to suggestions.

        Args:
            actual: What user typed.
            suggestions: Available suggestions.

        Returns:
            Tuple of (match_type, accepted_index).
        """
        # Empty input can't match anything (and "".startswith("") is True)
        if not actual:
            return ("none", None)

        for i, suggestion in enumerate(suggestions):
            if actual == suggestion:
                return ("exact", i)
            if actual.startswith(suggestion):
                return ("partial", i)  # User extended a suggestion
            if suggestion.startswith(actual):
                return ("prefix", i)  # User accepted prefix (word-by-word)
        return ("none", None)

    def to_lightweight_dict(self) -> dict[str, Any]:
        """Convert to lightweight dict for block metadata.

        Excludes heavy fields (context, LLM request/response) to keep
        timeline fast and memory-efficient.

        Returns:
            Dict with essential outcome data only.
        """
        return {
            "suggestions": self.suggestions,
            "accepted_index": self.accepted_index,
            "match_type": self.match_type,
            "cycle_count": self.cycle_count,
            "time_to_action_ms": self.time_to_action_ms,
        }

    def to_full_dict(self) -> dict[str, Any]:
        """Convert to full dict for JSONL ML training export.

        Includes everything needed for self-contained ML training:
        - Full context
        - Complete LLM request/response
        - User behavior and outcome

        Returns:
            Complete dict for JSONL storage.
        """
        return {
            # Timestamps
            "ts": time.time(),  # Wall clock for JSONL
            "session": self.session_name,
            "server": self.server_name,
            "trigger_block": self.trigger_block_number,
            "result_block": self.result_block_number,
            # Full context
            "context": self.context,
            "context_block_count": self.context_block_count,
            # LLM interaction
            "llm_request": self.llm_request,
            "llm_response": self.llm_response,
            "suggestion_node_version": self.suggestion_node_version,
            # Suggestions
            "suggestions": self.suggestions,
            # User behavior
            "viewed_indices": self.viewed_indices,
            "cycle_count": self.cycle_count,
            "displayed_index_at_submit": self.displayed_index_at_submit,
            # Outcome
            "accepted_index": self.accepted_index,
            "actual_input": self.actual_input,
            "match_type": self.match_type,
            # Timing
            "time_to_action_ms": self.time_to_action_ms,
        }
