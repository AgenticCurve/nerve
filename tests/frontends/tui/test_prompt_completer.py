"""Tests for slash prompt completion in Commander TUI."""

from pathlib import Path
from typing import Any

import pytest
from prompt_toolkit.completion import Completion
from prompt_toolkit.document import Document

from nerve.frontends.tui.commander.prompt_completer import SlashPromptCompleter


def get_display_text(completion: Completion) -> str:
    """Extract plain text from completion display.

    The display attribute can be a string or FormattedText.
    This helper extracts the plain text for comparison.
    """
    display: Any = completion.display
    if hasattr(display, "value"):
        # FormattedText-like object
        return str(display.value)
    if isinstance(display, list):
        # FormattedText is list of (style, text) tuples
        return "".join(text for _style, text in display)
    return str(display)


@pytest.fixture
def temp_prompts_dir(tmp_path: Path) -> Path:
    """Create a temporary prompts directory with test files."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    # Create test prompt files
    (prompts_dir / "hello.md").write_text("Hello World")

    refactoring_dir = prompts_dir / "refactoring"
    refactoring_dir.mkdir()
    (refactoring_dir / "verify-refactoring.md").write_text(
        "{{CONTEXT}}\n\n**Objective:** Verify refactored code."
    )
    (refactoring_dir / "bug-hunter.md").write_text("Find and fix bugs.")

    # Nested directories
    nested_dir = prompts_dir / "a" / "b"
    nested_dir.mkdir(parents=True)
    (nested_dir / "c.md").write_text("Nested content")

    return prompts_dir


class TestSlashPromptCompleter:
    """Test suite for SlashPromptCompleter."""

    def test_no_completion_without_slash(self, temp_prompts_dir: Path) -> None:
        """Input 'hello' yields no completions."""
        completer = SlashPromptCompleter(prompts_dir=temp_prompts_dir)
        doc = Document("hello")

        completions = list(completer.get_completions(doc, None))

        assert completions == []

    def test_completion_on_slash(self, temp_prompts_dir: Path) -> None:
        """Input '/' yields all prompts."""
        completer = SlashPromptCompleter(prompts_dir=temp_prompts_dir)
        doc = Document("/")

        completions = list(completer.get_completions(doc, None))

        # Should have 4 prompts: hello, refactoring/verify-refactoring,
        # refactoring/bug-hunter, a/b/c
        assert len(completions) == 4
        displays = [get_display_text(c) for c in completions]
        assert "hello" in displays
        assert "refactoring/verify-refactoring" in displays
        assert "refactoring/bug-hunter" in displays
        assert "a/b/c" in displays

    def test_fuzzy_match_basic(self, temp_prompts_dir: Path) -> None:
        """'bug' matches 'refactoring/bug-hunter'."""
        completer = SlashPromptCompleter(prompts_dir=temp_prompts_dir)
        doc = Document("/bug")

        completions = list(completer.get_completions(doc, None))

        displays = [get_display_text(c) for c in completions]
        assert "refactoring/bug-hunter" in displays

    def test_fuzzy_match_with_slash(self, temp_prompts_dir: Path) -> None:
        """'r/v' matches 'refactoring/verify-refactoring'."""
        completer = SlashPromptCompleter(prompts_dir=temp_prompts_dir)
        doc = Document("/r/v")

        completions = list(completer.get_completions(doc, None))

        displays = [get_display_text(c) for c in completions]
        assert "refactoring/verify-refactoring" in displays

    def test_fuzzy_match_case_insensitive(self, temp_prompts_dir: Path) -> None:
        """'BUG' matches 'bug-hunter' (case insensitive)."""
        completer = SlashPromptCompleter(prompts_dir=temp_prompts_dir)
        doc = Document("/BUG")

        completions = list(completer.get_completions(doc, None))

        displays = [get_display_text(c) for c in completions]
        assert "refactoring/bug-hunter" in displays

    def test_completion_replaces_entire_buffer(self, temp_prompts_dir: Path) -> None:
        """start_position replaces entire buffer including '/'."""
        completer = SlashPromptCompleter(prompts_dir=temp_prompts_dir)
        doc = Document("/hello")

        completions = list(completer.get_completions(doc, None))

        # Find the hello completion
        hello_completion = next(c for c in completions if get_display_text(c) == "hello")

        # start_position should be negative of entire text length
        assert hello_completion.start_position == -len("/hello")
        # Text should be the path (content expanded on Enter)
        assert hello_completion.text == "/hello"

    def test_missing_prompts_dir(self, tmp_path: Path) -> None:
        """No error, empty completions when prompts/ doesn't exist."""
        nonexistent = tmp_path / "nonexistent"
        completer = SlashPromptCompleter(prompts_dir=nonexistent)
        doc = Document("/test")

        completions = list(completer.get_completions(doc, None))

        assert completions == []

    def test_cache_lazy_load(self, temp_prompts_dir: Path) -> None:
        """Cache is None until first get_completions call."""
        completer = SlashPromptCompleter(prompts_dir=temp_prompts_dir)

        # Cache should be None before any completion call
        assert completer._cache is None

        # Trigger completions (even with no match to ensure cache loads)
        doc = Document("/")
        list(completer.get_completions(doc, None))

        # Cache should now be populated
        assert completer._cache is not None
        assert len(completer._cache) == 4

    def test_nested_directories(self, temp_prompts_dir: Path) -> None:
        """Handles nested directories like a/b/c.md correctly."""
        completer = SlashPromptCompleter(prompts_dir=temp_prompts_dir)
        doc = Document("/a/b/c")

        completions = list(completer.get_completions(doc, None))

        # Should match a/b/c
        displays = [get_display_text(c) for c in completions]
        assert "a/b/c" in displays

        # Completion text is the path (content expanded on Enter)
        abc_completion = next(c for c in completions if get_display_text(c) == "a/b/c")
        assert abc_completion.text == "/a/b/c"

    def test_slash_mid_input_no_completion(self, temp_prompts_dir: Path) -> None:
        """'@node /test' yields no completion (only triggers at start)."""
        completer = SlashPromptCompleter(prompts_dir=temp_prompts_dir)
        doc = Document("@node /test")

        completions = list(completer.get_completions(doc, None))

        assert completions == []

    def test_non_md_files_ignored(self, tmp_path: Path) -> None:
        """Non-.md files in prompts/ are ignored."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        # Create both .md and non-.md files
        (prompts_dir / "valid.md").write_text("Valid prompt")
        (prompts_dir / "ignored.txt").write_text("Should be ignored")
        (prompts_dir / "also_ignored.py").write_text("Also ignored")

        completer = SlashPromptCompleter(prompts_dir=prompts_dir)
        doc = Document("/")

        completions = list(completer.get_completions(doc, None))

        # Only .md file should appear
        assert len(completions) == 1
        assert get_display_text(completions[0]) == "valid"


class TestFuzzyMatchAlgorithm:
    """Test the fuzzy matching algorithm specifically."""

    def test_matches_basic(self) -> None:
        """Basic character-by-character matching."""
        completer = SlashPromptCompleter()

        assert completer._match_score("r/v", "refactoring/verify-refactoring") is not None
        assert completer._match_score("bug", "refactoring/bug-hunter") is not None
        assert completer._match_score("ver", "refactoring/verify-refactoring") is not None
        assert completer._match_score("xyz", "refactoring/verify-refactoring") is None

    def test_matches_order_matters(self) -> None:
        """Characters must appear in order."""
        completer = SlashPromptCompleter()

        # 'vr' should match because 'v' appears before 'r' in the target
        assert completer._match_score("vr", "refactoring/verify-refactoring") is not None

        # But order in query matters
        assert completer._match_score("zyx", "xyz") is None

    def test_matches_case_insensitive(self) -> None:
        """Matching is case insensitive."""
        completer = SlashPromptCompleter()

        assert completer._match_score("BUG", "bug-hunter") is not None
        assert completer._match_score("bug", "BUG-HUNTER") is not None
        assert completer._match_score("BuG", "buG-HuNter") is not None

    def test_matches_empty_query(self) -> None:
        """Empty query matches everything."""
        completer = SlashPromptCompleter()

        assert completer._match_score("", "anything") is not None
        assert completer._match_score("", "") is not None


class TestMatchQualitySorting:
    """Test that matches are sorted by quality, not alphabetically."""

    def test_exact_prefix_ranked_first(self, tmp_path: Path) -> None:
        """Exact prefix matches should appear before fuzzy matches."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        # Create prompts where "bug" is prefix of one, fuzzy match of another
        (prompts_dir / "bug-report.md").write_text("Bug report template")
        (prompts_dir / "debug-helper.md").write_text("Debug helper")  # 'bug' matches fuzzily

        completer = SlashPromptCompleter(prompts_dir=prompts_dir)
        doc = Document("/bug")

        completions = list(completer.get_completions(doc, None))
        displays = [get_display_text(c) for c in completions]

        # bug-report should come first (exact prefix)
        assert displays[0] == "bug-report"

    def test_word_boundary_match_ranked_higher(self, tmp_path: Path) -> None:
        """Matches at word boundaries should rank higher."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        # 'ver' matches at word boundary in verify, but mid-word in revert
        (prompts_dir / "revert-changes.md").write_text("Revert")  # 're[ver]t'
        (prompts_dir / "verify-code.md").write_text("Verify")  # '[ver]ify'

        completer = SlashPromptCompleter(prompts_dir=prompts_dir)
        doc = Document("/ver")

        completions = list(completer.get_completions(doc, None))
        displays = [get_display_text(c) for c in completions]

        # verify-code should come first (word boundary match)
        assert displays[0] == "verify-code"

    def test_shorter_path_preferred_on_tie(self, tmp_path: Path) -> None:
        """Shorter paths should be preferred when scores are similar."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        # Both are exact prefix matches, but one has longer path
        (prompts_dir / "test.md").write_text("Short")
        nested = prompts_dir / "very" / "long" / "path"
        nested.mkdir(parents=True)
        (nested / "test-thing.md").write_text("Long path")

        completer = SlashPromptCompleter(prompts_dir=prompts_dir)
        doc = Document("/test")

        completions = list(completer.get_completions(doc, None))
        displays = [get_display_text(c) for c in completions]

        # Shorter path should come first
        assert displays[0] == "test"

    def test_consecutive_chars_ranked_higher(self, tmp_path: Path) -> None:
        """Consecutive character matches should rank higher than scattered."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        # 'abc' consecutive in one, scattered in another (no word boundaries)
        (prompts_dir / "xaxxbxxcx.md").write_text("Scattered")  # xa..b..c
        (prompts_dir / "xabcx.md").write_text("Consecutive")  # xabcx

        completer = SlashPromptCompleter(prompts_dir=prompts_dir)
        doc = Document("/abc")

        completions = list(completer.get_completions(doc, None))
        displays = [get_display_text(c) for c in completions]

        # Consecutive match should come first
        assert displays[0] == "xabcx"

    def test_match_score_returns_none_for_no_match(self) -> None:
        """_match_score returns None when there's no match."""
        completer = SlashPromptCompleter()

        assert completer._match_score("xyz", "abc") is None
        assert completer._match_score("zzz", "hello") is None

    def test_match_score_returns_int_for_match(self) -> None:
        """_match_score returns an integer score for valid matches."""
        completer = SlashPromptCompleter()

        score = completer._match_score("bug", "bug-hunter")
        assert isinstance(score, int)

        score = completer._match_score("r/v", "refactoring/verify")
        assert isinstance(score, int)
