# PRD: Slash Prompts for TUI Commander

## Overview

Add support for `/` prompts in TUI Commander. Users can type `/` followed by a path to inject pre-defined prompt templates from markdown files into the input buffer.

## User Story

As a Commander user, I want to quickly insert saved prompt templates by typing `/path/to/prompt` so I can reuse common prompts without retyping them.

## Behavior

### Trigger Condition

- Slash prompt completion activates **only** when input starts with `/`
- If `/` appears elsewhere in the input (not at position 0), no completion triggered

### User Flow

1. User types `/` in empty prompt
2. Dropdown appears showing all available prompts (fuzzy filtered as user types)
3. User continues typing to filter: `/r/v` filters to `refactoring/verify-refactoring`
4. User selects with arrow keys + Enter (or clicks)
5. **Entire buffer** is replaced with the prompt file's content
6. User can edit the injected content before submitting

### Visual Example

```
/refac█
┌────────────────────────────────┐
│ refactoring/verify-refactoring │
│ refactoring/bug-hunter         │
└────────────────────────────────┘
```

After selecting `refactoring/verify-refactoring`:

```
{{CONTEXT}}

**Objective:** Verify refactored code produces IDENTICAL behavior to the original.
...
█
```

## Technical Specification

### File Structure

**Prompts Directory:** `{cwd}/prompts/`

**File Format:** Markdown files (`.md`)

**Path Convention:**
- File: `prompts/refactoring/verify-refactoring.md`
- User types: `/refactoring/verify-refactoring`
- Stored internally as: `refactoring/verify-refactoring` (no `.md`, no leading `/`)

### New Module: `prompt_completer.py`

**Location:** `src/nerve/frontends/tui/commander/prompt_completer.py`

```python
"""Slash prompt completion for Commander TUI.

Provides dropdown completion for `/path` syntax that injects
prompt templates from markdown files in the prompts/ directory.
"""

from pathlib import Path
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


class SlashPromptCompleter(Completer):
    """Completer for slash prompt syntax.

    Scans {cwd}/prompts/ for .md files and provides fuzzy-matched
    completions. On selection, replaces entire buffer with file content.

    Cache is lazy-loaded on first "/" keystroke.

    Example:
        >>> completer = SlashPromptCompleter()
        >>> # User types "/r/v"
        >>> # Dropdown shows: refactoring/verify-refactoring
        >>> # Selection replaces buffer with file content
    """

    def __init__(self, prompts_dir: Path | None = None):
        """Initialize completer.

        Args:
            prompts_dir: Directory containing prompt .md files.
                         Defaults to Path.cwd() / "prompts".
        """
        self.prompts_dir = prompts_dir or Path.cwd() / "prompts"
        self._cache: dict[str, str] | None = None  # path -> content

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        """Generate completions for slash prompts.

        Only activates when text starts with "/".
        Lazy-loads cache on first call.
        """
        ...

    def _load_cache(self) -> None:
        """Scan prompts_dir and cache all .md file contents.

        Populates self._cache with {path: content} mapping.
        Path format: "subdir/filename" (no .md extension, no leading /)
        """
        ...

    def _fuzzy_match(self, query: str) -> list[str]:
        """Return paths matching query using char-by-char fuzzy matching.

        Matches if all chars in query appear in path in order.
        Supports "/" in query for path-aware matching.

        Examples:
            - "r/v" matches "refactoring/verify-refactoring"
            - "bug" matches "refactoring/bug-hunter"
            - "xyz" matches nothing

        Args:
            query: User's query (after the leading "/")

        Returns:
            List of matching paths, sorted (TODO: by relevance?)
        """
        ...
```

### Fuzzy Matching Algorithm

Character-by-character in-order matching:

```python
def _matches(self, query: str, target: str) -> bool:
    """Check if all query chars appear in target in order."""
    query = query.lower()
    target = target.lower()
    target_idx = 0
    for char in query:
        idx = target.find(char, target_idx)
        if idx == -1:
            return False
        target_idx = idx + 1
    return True
```

| Query | Target | Result |
|-------|--------|--------|
| `r/v` | `refactoring/verify-refactoring` | ✓ Match |
| `bug` | `refactoring/bug-hunter` | ✓ Match |
| `ver` | `refactoring/verify-refactoring` | ✓ Match |
| `xyz` | `refactoring/verify-refactoring` | ✗ No match |
| `vr` | `refactoring/verify-refactoring` | ✓ Match (v before r in target) |

### Completion Object

```python
Completion(
    text=file_content,           # Full .md file content (inserted on accept)
    display=path,                # "refactoring/verify-refactoring" (shown in dropdown)
    start_position=-len(text),   # Replace entire buffer including "/"
)
```

### Integration Point: `commander.py`

In `Commander.__post_init__`, add completer to PromptSession:

```python
from nerve.frontends.tui.commander.prompt_completer import SlashPromptCompleter

self._prompt_session = PromptSession(
    history=InMemoryHistory(),
    bottom_toolbar=self._get_status_bar,
    style=prompt_style,
    key_bindings=kb,
    placeholder=self._suggestions.get_placeholder,
    auto_suggest=self._suggestions.get_auto_suggest(),
    completer=SlashPromptCompleter(),          # ADD THIS
    complete_while_typing=True,                 # ADD THIS
)
```

## Edge Cases

| Case | Behavior |
|------|----------|
| `prompts/` dir doesn't exist | No completions shown, no error |
| Empty `prompts/` dir | No completions shown |
| `/` typed mid-input (`@node /test`) | No completion (only triggers at start) |
| File read error | Skip that file, log warning |
| Nested dirs (`prompts/a/b/c.md`) | Path shown as `a/b/c` |
| Non-.md files in prompts/ | Ignored |

## Non-Goals (Out of Scope)

- Template variables/placeholders (e.g., `{{CONTEXT}}` expansion)
- Creating/editing prompts from TUI
- Remote/shared prompts
- Hot-reloading prompts mid-session (requires restart or re-trigger)

## Testing

### Manual Testing

1. Create `prompts/test/hello.md` with content "Hello World"
2. Start Commander: `nerve tui`
3. Type `/test/hello`
4. Verify dropdown shows `test/hello`
5. Select it
6. Verify buffer contains "Hello World"

### Unit Tests

**Location:** `tests/frontends/tui/test_prompt_completer.py`

Tests to write:
- [ ] `test_no_completion_without_slash` - Input "hello" yields no completions
- [ ] `test_completion_on_slash` - Input "/" yields all prompts
- [ ] `test_fuzzy_match_basic` - "bug" matches "refactoring/bug-hunter"
- [ ] `test_fuzzy_match_with_slash` - "r/v" matches "refactoring/verify-refactoring"
- [ ] `test_fuzzy_match_case_insensitive` - "BUG" matches "bug-hunter"
- [ ] `test_completion_replaces_entire_buffer` - start_position is correct
- [ ] `test_missing_prompts_dir` - No error, empty completions
- [ ] `test_cache_lazy_load` - Cache is None until first get_completions call
- [ ] `test_nested_directories` - Handles `a/b/c.md` correctly

## Acceptance Criteria

- [ ] Typing `/` at start of input shows dropdown with prompt files
- [ ] Fuzzy matching works with `/` in query (e.g., `r/v` matches `refactoring/verify-refactoring`)
- [ ] Selecting a prompt replaces entire buffer with file content
- [ ] Cache is lazy-loaded (not at Commander startup)
- [ ] Missing `prompts/` directory doesn't cause errors
- [ ] Nested directories are supported
- [ ] Only `.md` files are included
- [ ] Unit tests pass
