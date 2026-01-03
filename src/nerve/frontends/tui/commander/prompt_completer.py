"""Slash prompt completion for Commander TUI.

Provides dropdown completion for `/path` syntax that injects
prompt templates from markdown files in the .nerve/prompts/ directory.

The completion flow:
1. User types `/` - dropdown shows available prompt paths
2. User navigates with arrows and types to filter (fuzzy match)
3. User presses Enter/Tab to select
4. Buffer is replaced with the prompt file's content
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

logger = logging.getLogger(__name__)


class SlashPromptCompleter(Completer):
    """Completer for slash prompt syntax.

    Scans {cwd}/.nerve/prompts/ for .md files and provides fuzzy-matched
    completions. Shows paths in dropdown, inserts file content on selection.

    Cache is lazy-loaded on first "/" keystroke.
    Gracefully handles missing .nerve/ or .nerve/prompts/ directories.

    Example:
        >>> completer = SlashPromptCompleter()
        >>> # User types "/r/v"
        >>> # Dropdown shows: refactoring/verify-refactoring
        >>> # Selection replaces buffer with file content
    """

    def __init__(self, prompts_dir: Path | None = None) -> None:
        """Initialize completer.

        Args:
            prompts_dir: Directory containing prompt .md files.
                         Defaults to Path.cwd() / ".nerve" / "prompts".
        """
        self.prompts_dir = prompts_dir or Path.cwd() / ".nerve" / "prompts"
        self._cache: dict[str, str] | None = None  # path -> content

    def get_completions(self, document: Document, complete_event: object) -> Iterable[Completion]:
        """Generate completions for slash prompts.

        Only activates when text starts with "/".
        Lazy-loads cache on first call.

        Args:
            document: The current document being edited.
            complete_event: The completion event (unused).

        Yields:
            Completion objects with path as text (expanded to content on Enter).
        """
        text = document.text

        # Only activate when input starts with "/"
        if not text.startswith("/"):
            return

        # Lazy-load cache
        if self._cache is None:
            self._load_cache()

        # Extract query (everything after "/")
        query = text[1:]

        # Get fuzzy matches
        matches = self._fuzzy_match(query)

        # Yield completions - text is the path (content expanded on Enter)
        for path in matches:
            yield Completion(
                text=f"/{path}",  # Path inserted when user selects
                display=path,  # Path shown in dropdown
                start_position=-len(text),  # Replace entire input including "/"
                style="class:completion-path",
                selected_style="class:completion-path-selected",
            )

    def get_content(self, path: str) -> str | None:
        """Get the content for a prompt path.

        Args:
            path: The prompt path (without leading /, without .md extension).

        Returns:
            The file content, or None if not found.
        """
        if self._cache is None:
            self._load_cache()
        return self._cache.get(path) if self._cache else None

    def is_valid_prompt_path(self, text: str) -> bool:
        """Check if text is a valid prompt path that can be expanded.

        Args:
            text: The text to check (should start with /).

        Returns:
            True if this is a valid prompt path.
        """
        if not text.startswith("/"):
            return False
        path = text[1:]  # Remove leading /
        if self._cache is None:
            self._load_cache()
        return path in self._cache if self._cache else False

    def expand_prompt(self, text: str) -> str | None:
        """Expand a prompt path to its content.

        Args:
            text: The prompt path (with leading /).

        Returns:
            The file content, or None if not a valid path.
        """
        if not text.startswith("/"):
            return None
        path = text[1:]
        return self.get_content(path)

    def _load_cache(self) -> None:
        """Scan prompts_dir and cache all .md file contents.

        Populates self._cache with {path: content} mapping.
        Path format: "subdir/filename" (no .md extension, no leading /)
        """
        self._cache = {}

        if not self.prompts_dir.is_dir():
            return

        # Recursively find all .md files
        for md_file in self.prompts_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                # Build path relative to prompts_dir, without .md extension
                rel_path = md_file.relative_to(self.prompts_dir)
                path_key = str(rel_path.with_suffix(""))
                self._cache[path_key] = content
            except (OSError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to read prompt file {md_file}: {e}")

    def _fuzzy_match(self, query: str) -> list[str]:
        """Return paths matching query using char-by-char fuzzy matching.

        Matches if all chars in query appear in path in order.
        Results are sorted by match quality (best matches first).

        Examples:
            - "r/v" matches "refactoring/verify-refactoring"
            - "bug" matches "refactoring/bug-hunter"
            - "xyz" matches nothing

        Args:
            query: User's query (after the leading "/")

        Returns:
            List of matching paths, sorted by match quality (best first).
        """
        if self._cache is None:
            return []

        scored_results: list[tuple[int, str]] = []
        for path in self._cache:
            score = self._match_score(query, path)
            if score is not None:
                scored_results.append((score, path))

        # Sort by score (lower is better), then alphabetically for ties
        scored_results.sort(key=lambda x: (x[0], x[1]))
        return [path for _score, path in scored_results]

    def _match_score(self, query: str, target: str) -> int | None:
        """Score a fuzzy match (lower is better, None means no match).

        Scoring priorities:
        - Exact prefix match: best score
        - Matches at word boundaries (after /, -, _): bonus
        - Consecutive character matches: bonus
        - Shorter paths preferred over longer ones

        Args:
            query: The search query.
            target: The target string to match against.

        Returns:
            Score (lower is better) or None if no match.
        """
        query_lower = query.lower()
        target_lower = target.lower()

        # Exact prefix match gets best score
        if target_lower.startswith(query_lower):
            return -1000 + len(target)

        # Check if all chars match in order and compute score
        target_idx = 0
        score = 0
        prev_match_idx = -1
        word_boundary_chars = frozenset("/-_")

        for char in query_lower:
            idx = target_lower.find(char, target_idx)
            if idx == -1:
                return None  # No match

            # Bonus for word boundary match (char after /, -, _)
            if idx == 0 or target_lower[idx - 1] in word_boundary_chars:
                score -= 10  # Bonus (lower score is better)

            # Bonus for consecutive matches
            if idx == prev_match_idx + 1:
                score -= 5

            # Penalty for gaps
            gap = idx - target_idx
            score += gap

            prev_match_idx = idx
            target_idx = idx + 1

        # Slight preference for shorter paths
        score += len(target) // 10

        return score
