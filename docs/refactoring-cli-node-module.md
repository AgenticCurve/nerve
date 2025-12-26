# Refactoring Analysis: CLI Frontend Node Module

**Date:** 2025-12-26
**Analyzed By:** Claude Code Refactoring Analyzer
**Scope:** `src/nerve/frontends/cli/server/` module

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total refactoring opportunities | 12 |
| High-impact opportunities (score > 8) | 6 |
| Medium-impact opportunities (score 5-8) | 4 |
| Low-impact opportunities (score < 5) | 2 |
| Potential code reduction | ~250-300 lines |
| Estimated effort | 6-8 person-days |

### Primary Architectural Issues

1. **Repetitive async wrapper pattern** - Every CLI command wraps logic in `async def run() ... asyncio.run(run())`
2. **Inconsistent error handling** - Mix of `error_exit()` and `click.echo(..., err=True)` with different behaviors
3. **Hardcoded node type mapping** - Protocol-level constant embedded in CLI code
4. **Duplicate history formatting** - Same logic in `output.py` and `repl/commands.py` (only differing by truncation length)
5. **Scattered session parameter handling** - Same pattern duplicated across commands
6. **Embedded validation logic** - Provider options validation mixed into command handler

---

## Refactoring Opportunities (Ranked by Impact)

### 1. Extract Async CLI Command Wrapper Pattern

**Impact Score:** 9.5/10
**Category:** Duplication Elimination, Architecture
**Files Affected:**
- `src/nerve/frontends/cli/server/node.py` (9 occurrences)
- `src/nerve/frontends/cli/server/session.py` (4 occurrences)
- `src/nerve/frontends/cli/server/__init__.py` (estimated 8+ occurrences)
- `src/nerve/frontends/cli/server/graph.py` (estimated 3+ occurrences)

#### Current State

Every CLI command follows the exact same pattern:

```python
@node.command("list")
@click.option("--server", "-s", "server_name", default="local")
def node_list(server_name: str, ...) -> None:
    """Docs..."""
    async def run() -> None:
        async with server_connection(server_name) as client:
            # ... command logic ...

    asyncio.run(run())
```

This pattern appears:
- **node.py**: Lines 57-97, 243-286, 312-330, 360-377, 401-419, 459-487, 519-536, 557-571 (8 occurrences)
- **session.py**: Lines 49-87, 108-129, 151-165, 185-216 (4 occurrences)

#### Proposed Solution

Create a decorator in `src/nerve/frontends/cli/utils.py`:

```python
from functools import wraps
from typing import Callable, ParamSpec
import asyncio

P = ParamSpec('P')

def async_server_command(f: Callable[P, Awaitable[None]]) -> Callable[P, None]:
    """Decorator for async CLI commands that need server connection.

    Automatically handles asyncio.run() execution.
    The decorated function should be an async function.
    """
    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        asyncio.run(f(*args, **kwargs))
    return wrapper
```

Then simplify commands to:

```python
@node.command("list")
@click.option("--server", "-s", "server_name", default="local")
@async_server_command
async def node_list(server_name: str, ...) -> None:
    """Docs..."""
    async with server_connection(server_name) as client:
        # ... command logic ...
```

#### Impact Analysis

| Aspect | Details |
|--------|---------|
| Scope | ~23 functions across 4+ files |
| LOC Reduced | ~200 lines |
| Benefits | Eliminates boilerplate, consistent error handling, easier to add cross-cutting concerns |
| Risks | Breaking change to function signatures, must preserve Click's type introspection |
| Effort | 4-6 hours |

#### Implementation Notes

1. The decorator must preserve `__wrapped__` for Click's type introspection
2. Test each command conversion incrementally
3. Consider adding error handling decorator later for consistent error reporting

---

### 2. Unify Error Handling Across CLI Commands

**Impact Score:** 9/10
**Category:** Duplication Elimination, Consistency
**Files Affected:**
- `src/nerve/frontends/cli/server/node.py`
- `src/nerve/frontends/cli/server/session.py`
- `src/nerve/frontends/cli/server/__init__.py`
- `src/nerve/frontends/cli/server/graph.py`

#### Current State

Two different error handling patterns are used inconsistently:

**Pattern 1: `error_exit()` from output.py** (used in node.py)
```python
from nerve.frontends.cli.output import error_exit

if result.success:
    # ... success logic ...
else:
    error_exit(result.error or "Unknown error")  # Calls sys.exit(1)
```

Used at: node.py lines 95, 219, 224, 230, 233, 284, 328, 375, 417, 534, 569

**Pattern 2: `click.echo(..., err=True)`** (used in session.py, __init__.py, graph.py)
```python
if result.success and result.data:
    # ... success logic ...
else:
    click.echo(f"Error: {result.error}", err=True)  # Does NOT exit!
```

Used at: session.py lines 85, 127, 163, 214

#### The Bug

The second pattern **does not exit** - it prints the error but continues execution.
This means failed commands in session.py return with exit code 0 instead of 1.

#### Proposed Solution

Standardize on `error_exit()` for all command errors:

```python
# In all server command files:
from nerve.frontends.cli.output import error_exit

# Then use:
if result.success:
    # ... success logic ...
else:
    error_exit(result.error or "Unknown error")
```

#### Impact Analysis

| Aspect | Details |
|--------|---------|
| Scope | 4 files, ~15 locations |
| Benefits | Consistent error handling, proper exit codes, single point of control |
| Risks | None (behavioral change is intended - errors SHOULD exit) |
| Effort | 2-3 hours |

---

### 3. Extract Node Type Mapping to Shared Constant

**Impact Score:** 8/10
**Category:** Duplication Elimination, Architecture
**Files Affected:**
- `src/nerve/frontends/cli/server/node.py` (lines 236-241)
- `src/nerve/server/protocols.py` (new constant)

#### Current State

```python
# node.py lines 236-241
type_to_backend = {
    "PTYNode": "pty",
    "WezTermNode": "wezterm",
    "ClaudeWezTermNode": "claude-wezterm",
}
backend = type_to_backend.get(node_type, "pty")
```

This mapping is a protocol-level concern hardcoded in CLI-only code.

#### Proposed Solution

Move to `src/nerve/server/protocols.py`:

```python
# In protocols.py - after CommandType enum
NODE_TYPE_TO_BACKEND: dict[str, str] = {
    "PTYNode": "pty",
    "WezTermNode": "wezterm",
    "ClaudeWezTermNode": "claude-wezterm",
}
```

Then import and use:

```python
# node.py
from nerve.server.protocols import NODE_TYPE_TO_BACKEND

backend = NODE_TYPE_TO_BACKEND.get(node_type, "pty")
```

#### Impact Analysis

| Aspect | Details |
|--------|---------|
| Scope | 2 files |
| Benefits | Single source of truth, reusable by other parts, easier to add new types |
| Risks | None |
| Effort | 1 hour |

---

### 4. Consolidate History Formatting Code

**Impact Score:** 8/10
**Category:** Duplication Elimination
**Files Affected:**
- `src/nerve/frontends/cli/output.py` (lines 87-131)
- `src/nerve/frontends/cli/repl/commands.py` (lines 190-213)

#### Current State

**output.py - `format_history_entry()`** (50 char truncation):
```python
def format_history_entry(entry: dict[str, Any]) -> str:
    # ...
    if op_type == "send":
        input_text = entry.get("input", "")[:50]  # 50 chars
        # ...
```

**commands.py - `format_history_entry_repl()`** (40 char truncation):
```python
def format_history_entry_repl(entry: dict[str, Any]) -> str:
    # ...
    if op_type == "send":
        input_text = entry.get("input", "")[:40]  # 40 chars
        # ...
```

The logic is nearly identical - only the truncation length differs.

#### Proposed Solution

Consolidate into a single function in output.py with a parameter:

```python
def format_history_entry(entry: dict[str, Any], truncate: int = 50) -> str:
    """Format a single history entry for display.

    Args:
        entry: History entry dict with op, seq, ts, etc.
        truncate: Maximum length for input text (default: 50)

    Returns:
        Formatted string for display
    """
    seq = entry.get("seq", "?")
    op_type = entry.get("op", "unknown")
    ts = entry.get("ts", entry.get("ts_start", ""))

    if ts:
        ts_display = ts.split("T")[1][:8] if "T" in ts else ts[:8]
    else:
        ts_display = ""

    if op_type == "send":
        input_text = entry.get("input", "")[:truncate]  # Use parameter
        response = entry.get("response", {})
        sections = response.get("sections", [])
        section_count = len(sections)
        return f"[{seq:3}] {ts_display} SEND    {input_text!r} -> {section_count} sections"
    # ... rest of logic with 'truncate' parameter
```

Then in commands.py:
```python
from nerve.frontends.cli.output import format_history_entry

def format_history_entry_repl(entry: dict[str, Any]) -> str:
    return format_history_entry(entry, truncate=40)
```

#### Impact Analysis

| Aspect | Details |
|--------|---------|
| Scope | 2 files |
| Benefits | Single implementation, consistent formatting, ~40 LOC eliminated |
| Risks | None |
| Effort | 2 hours |

---

### 5. Extract Common Session Parameter Handling

**Impact Score:** 7.5/10
**Category:** Duplication Elimination
**Files Affected:**
- `src/nerve/frontends/cli/server/node.py`
- `src/nerve/frontends/cli/server/session.py`

#### Current State

The pattern of conditionally adding `session_id` to params is duplicated:

```python
# node.py line 60-61 (node_list)
if session_id:
    params["session_id"] = session_id

# node.py line 251-252 (node_create)
if session_id:
    params["session_id"] = session_id

# node.py line 315-316 (node_delete)
if session_id:
    params["session_id"] = session_id

# session.py line 188-189 (session_info)
if session_id:
    params["session_id"] = session_id
```

#### Proposed Solution

Create a helper in `utils.py`:

```python
def build_params(**base_params: Any) -> dict[str, Any]:
    """Build command params dict, excluding None values.

    Args:
        **base_params: Key-value pairs for params. None values are excluded.

    Returns:
        Dict with non-None values.
    """
    return {k: v for k, v in base_params.items() if v is not None}
```

Then usage becomes:

```python
# Before:
params = {}
if session_id:
    params["session_id"] = session_id
if node_id:
    params["node_id"] = node_id

# After:
params = build_params(
    session_id=session_id,
    node_id=node_name,
)
```

#### Impact Analysis

| Aspect | Details |
|--------|---------|
| Scope | node.py, session.py |
| Benefits | Cleaner code, consistent pattern, easier to extend |
| Risks | None |
| Effort | 2 hours |

---

### 6. Extract Provider Options Validation

**Impact Score:** 7/10
**Category:** Duplication Elimination, Validation
**Files Affected:**
- `src/nerve/frontends/cli/server/node.py` (lines 222-233)

#### Current State

```python
# node.py lines 222-233 - embedded in command handler
provider_opts = [api_format, provider_base_url, provider_api_key]
if any(provider_opts) and not all(provider_opts):
    error_exit(
        "--api-format, --provider-base-url, and --provider-api-key "
        "must all be specified together"
    )

if api_format == "openai" and not provider_model:
    error_exit("--provider-model is required for openai format")

if api_format and node_type != "ClaudeWezTermNode":
    error_exit("Provider options require --type ClaudeWezTermNode")
```

#### Proposed Solution

Extract to `utils.py`:

```python
def validate_provider_options(
    api_format: str | None,
    provider_base_url: str | None,
    provider_api_key: str | None,
    provider_model: str | None,
    node_type: str,
) -> None:
    """Validate provider configuration options.

    Raises:
        ValueError: With descriptive message if validation fails.
    """
    provider_opts = [api_format, provider_base_url, provider_api_key]
    if any(provider_opts) and not all(provider_opts):
        raise ValueError(
            "--api-format, --provider-base-url, and --provider-api-key "
            "must all be specified together"
        )

    if api_format == "openai" and not provider_model:
        raise ValueError("--provider-model is required for openai format")

    if api_format and node_type != "ClaudeWezTermNode":
        raise ValueError("Provider options require --type ClaudeWezTermNode")
```

Then in node.py:

```python
try:
    validate_provider_options(
        api_format, provider_base_url, provider_api_key, provider_model, node_type
    )
except ValueError as e:
    error_exit(str(e))
```

#### Impact Analysis

| Aspect | Details |
|--------|---------|
| Scope | 1 file (node.py + utils.py) |
| Benefits | Separation of concerns, testable validation, reusable |
| Risks | None |
| Effort | 1 hour |

---

## Secondary Opportunities (Lower Priority)

### 7. Extract Node Type Click Choice to Constant
**Impact Score:** 6/10** - Extract to `NODE_TYPE_CHOICES = ["PTYNode", "WezTermNode", "ClaudeWezTermNode"]`

### 8. Extract Command Result Handling Pattern
**Impact Score:** 6/10** - Create helper for common result handling pattern

### 9. Standardize Success Message Formatting
**Impact Score:** 5/10** - Minor consistency improvement

### 10. Consolidate Table Print Duplication
**Impact Score:** 5/10** - `print_table()` vs `print_table_repl()` duplication

### 11. Extract History Command to Separate Module
**Impact Score:** 5/10** - 105-line `node_history` command could be extracted

### 12. Commit Uncommitted Changes
**Impact Score:** 4/10** - Current git changes need to be committed and tested

---

## Recommended Implementation Sequence

### Phase 1: Foundation (Quick Wins)
1. **#3: Extract Node Type Mapping** - Enables other changes
2. **#7: Node Type Choice Constant** - Builds on #3
3. **#2: Unify Error Handling** - Low risk, high value

### Phase 2: Core Refactoring
4. **#1: Async CLI Command Wrapper** - Highest impact, requires careful testing
5. **#6: Provider Options Validation** - Clean separation

### Phase 3: Polish
6. **#4: Consolidate History Formatting** - Moderate value
7. **#5: Session Parameter Helper** - Minor improvement

### Phase 4: Optional / Future
8. **#12: Extract History Command** - If history commands grow
9. **#10: Commit Uncommitted Changes** - Should be done separately

---

## Summary Statistics

| Category | Count | Files Affected |
|----------|-------|----------------|
| Duplication Elimination | 8 | node.py, session.py, output.py, commands.py |
| Architecture | 2 | utils.py, protocols.py |
| Consistency | 2 | All server modules |

**Total lines of code that could be eliminated:** ~250-300 lines
**Total estimated effort:** 6-8 person-days
