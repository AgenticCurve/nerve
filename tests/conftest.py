"""Pytest configuration and fixtures."""

from pathlib import Path

import pytest

# Path to fixtures directory
FIXTURES_DIR = Path(__file__).parent / "core" / "fixtures"


def load_fixture(filename: str) -> str:
    """Load a fixture file by name."""
    return (FIXTURES_DIR / filename).read_text()


@pytest.fixture
def sample_claude_output():
    """Sample Claude Code output for parser testing."""
    return """
> What is 2+2?

∴ Thinking…
  The user is asking a simple math question.

⏺ The answer is 4.

───────────────────────────────────────────────────────────
>
───────────────────────────────────────────────────────────
  -- INSERT --                                    1234 tokens
"""


@pytest.fixture
def sample_claude_output_with_tool():
    """Sample Claude Code output with tool call."""
    return """
> Read the file main.py

∴ Thinking…
  I need to read the file to understand its contents.

⏺ Read(file_path="main.py")
⎿  def main():
      print("Hello, World!")

⏺ This is a simple Python program that prints "Hello, World!".

───────────────────────────────────────────────────────────
>
───────────────────────────────────────────────────────────
  -- INSERT --                                    2345 tokens
"""


# Real-world sample fixtures from captured Claude Code sessions
@pytest.fixture
def claude_code_pane_02():
    """Real Claude output with Search tool call and text response.

    Contains:
    - Search tool call with results
    - Thinking section
    - Text response with code blocks
    - Ready state with token count
    """
    return load_fixture("claude_code_pane_02.txt")


@pytest.fixture
def claude_code_pane_03():
    """Real Claude output with Bash tool, BigQuery results.

    Contains:
    - File references (Read tool results truncated)
    - Thinking section
    - Bash tool call with table output
    - Multi-line thinking
    - Text response
    - Session rating prompt
    - Ready state
    """
    return load_fixture("claude_code_pane_03.txt")


@pytest.fixture
def claude_code_pane_04():
    """Real Claude output with multiple Search tool calls.

    Contains:
    - Text response with numbered list
    - Multiple Search tool calls
    - Multiple thinking sections
    - Complex multi-step conversation
    - Ready state
    """
    return load_fixture("claude_code_pane_04.txt")


@pytest.fixture
def claude_code_pane_content():
    """Captured pane content mid-session (processing state).

    Contains:
    - Thinking indicator
    - Read tool references
    - In-progress status (not ready)
    """
    return load_fixture("claude_code_pane_content.txt")
