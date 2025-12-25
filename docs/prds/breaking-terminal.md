# PRD: Refactor terminal.py into Modular Package

## Summary

Refactor `src/nerve/core/nodes/terminal.py` (1676 lines) into a `terminal/` package with separate files for each dataclass. This is a pure refactoring with no feature changes - all existing functionality and public APIs must be preserved.

## Motivation

The current `terminal.py` file contains three large dataclasses:
- `PTYNode` (lines 37-604, ~570 lines)
- `WezTermNode` (lines 606-1253, ~650 lines)
- `ClaudeWezTermNode` (lines 1255-1676, ~420 lines)

This monolithic structure makes the codebase harder to navigate, maintain, and understand. Breaking it into separate modules improves:
- **Readability**: Each file focuses on one concept
- **Maintainability**: Changes to one node type don't require touching unrelated code
- **Testing**: Easier to isolate and test individual components
- **Code review**: Smaller, focused diffs

## Requirements

### Functional Requirements

1. **No Feature Regression**: All existing functionality must work exactly as before
2. **Clean Break**: No backward compatibility shims or aliases
3. **Same Public API**: All exported classes and their interfaces remain identical
4. **Test Compatibility**: All existing tests must pass without modification (except import paths if testing internal imports)

### Non-Functional Requirements

1. **One file per dataclass**: Each terminal node type gets its own file
2. **Package structure**: Use `terminal/` directory with `__init__.py` for namespace preservation
3. **Import consistency**: `from nerve.core.nodes.terminal import PTYNode` must continue to work
4. **No circular imports**: Module dependencies must be clean

## Current State Analysis

### File: `src/nerve/core/nodes/terminal.py`

**Current imports used by all three classes:**
```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.history import HISTORY_BUFFER_LINES, HistoryWriter
from nerve.core.parsers import get_parser
from nerve.core.pty import BackendConfig
from nerve.core.pty.pty_backend import PTYBackend
from nerve.core.pty.wezterm_backend import WezTermBackend
from nerve.core.types import ParsedResponse, ParserType

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session
```

**Class dependencies:**
- `PTYNode`: Uses `PTYBackend`
- `WezTermNode`: Uses `WezTermBackend`
- `ClaudeWezTermNode`: Uses `WezTermNode` (wraps it internally)

### Current Consumers (files that import from terminal.py)

| File | Import Pattern |
|------|----------------|
| `src/nerve/core/nodes/__init__.py` | `from nerve.core.nodes.terminal import ClaudeWezTermNode, PTYNode, WezTermNode` |
| `src/nerve/server/engine.py:208` | `from nerve.core.nodes.terminal import ClaudeWezTermNode, PTYNode, WezTermNode` |
| `src/nerve/server/engine.py:529` | `from nerve.core.nodes.terminal import ClaudeWezTermNode, PTYNode, WezTermNode` |
| `src/nerve/frontends/sdk/client.py:251` | `from nerve.core.nodes.terminal import PTYNode` |
| `src/nerve/frontends/cli/repl/file_runner.py:27` | `from nerve.core.nodes.terminal import ClaudeWezTermNode` |
| `src/nerve/frontends/cli/repl/core.py:83` | `from nerve.core.nodes.terminal import ClaudeWezTermNode` |
| `tests/core/nodes/test_terminal.py:13` | `from nerve.core.nodes.terminal import ClaudeWezTermNode, PTYNode, WezTermNode` |
| `tests/core/nodes/test_unified_api.py` | Multiple imports of individual classes |

### Test Mocking Patterns

Tests currently mock backends at the terminal module level:
```python
patch("nerve.core.nodes.terminal.PTYBackend", return_value=mock_backend)
patch("nerve.core.nodes.terminal.WezTermBackend", return_value=mock_backend)
patch("nerve.core.nodes.terminal.get_parser")
```

After refactoring, these paths will change to:
```python
patch("nerve.core.nodes.terminal.pty_node.PTYBackend", return_value=mock_backend)
patch("nerve.core.nodes.terminal.wezterm_node.WezTermBackend", return_value=mock_backend)
patch("nerve.core.nodes.terminal.pty_node.get_parser")  # or wezterm_node
```

## Proposed Implementation

### Phase 1: Create Package Structure

Create the following directory structure:

```
src/nerve/core/nodes/
├── terminal/                    # NEW directory
│   ├── __init__.py             # Re-exports all node classes
│   ├── pty_node.py             # PTYNode class
│   ├── wezterm_node.py         # WezTermNode class
│   └── claude_wezterm_node.py  # ClaudeWezTermNode class
├── base.py
├── bash.py
├── budget.py
├── cancellation.py
├── context.py
├── graph.py
├── history.py
├── policies.py
└── trace.py
```

### Phase 2: File Contents

#### File: `terminal/__init__.py`

```python
"""Terminal nodes - PTY and WezTerm based terminal interactions.

Terminal nodes implement the Node protocol for terminal-based interactions.

Key characteristics:
- PTYNode: Owns process via pseudo-terminal, continuous buffer
- WezTermNode: Attaches to WezTerm panes, always-fresh buffer query
- ClaudeWezTermNode: WezTerm optimized for Claude CLI

All terminal nodes:
- Are persistent (maintain state across executions)
- Support execute() and execute_stream() methods
- Have history logging capability
"""

from nerve.core.nodes.terminal.claude_wezterm_node import ClaudeWezTermNode
from nerve.core.nodes.terminal.pty_node import PTYNode
from nerve.core.nodes.terminal.wezterm_node import WezTermNode

__all__ = [
    "PTYNode",
    "WezTermNode",
    "ClaudeWezTermNode",
]
```

#### File: `terminal/pty_node.py`

Contains:
- All imports required by PTYNode
- The `PTYNode` dataclass (lines 37-604 from original)
- No changes to the class implementation

Required imports:
```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.history import HISTORY_BUFFER_LINES, HistoryWriter
from nerve.core.parsers import get_parser
from nerve.core.pty import BackendConfig
from nerve.core.pty.pty_backend import PTYBackend
from nerve.core.types import ParsedResponse, ParserType

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session
```

#### File: `terminal/wezterm_node.py`

Contains:
- All imports required by WezTermNode
- The `WezTermNode` dataclass (lines 606-1253 from original)
- No changes to the class implementation

Required imports:
```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.history import HISTORY_BUFFER_LINES, HistoryWriter
from nerve.core.parsers import get_parser
from nerve.core.pty import BackendConfig
from nerve.core.pty.wezterm_backend import WezTermBackend
from nerve.core.types import ParsedResponse, ParserType

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session
```

#### File: `terminal/claude_wezterm_node.py`

Contains:
- All imports required by ClaudeWezTermNode
- The `ClaudeWezTermNode` dataclass (lines 1255-1676 from original)
- Import of `WezTermNode` from sibling module
- No changes to the class implementation

Required imports:
```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.history import HISTORY_BUFFER_LINES, HistoryWriter
from nerve.core.nodes.terminal.wezterm_node import WezTermNode
from nerve.core.types import ParsedResponse, ParserType

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session
```

### Phase 3: Update Test Mocking Paths

#### File: `tests/core/nodes/test_terminal.py`

Update mock paths for backend classes and parsers:

| Old Path | New Path |
|----------|----------|
| `nerve.core.nodes.terminal.PTYBackend` | `nerve.core.nodes.terminal.pty_node.PTYBackend` |
| `nerve.core.nodes.terminal.WezTermBackend` | `nerve.core.nodes.terminal.wezterm_node.WezTermBackend` |
| `nerve.core.nodes.terminal.get_parser` (for PTYNode tests) | `nerve.core.nodes.terminal.pty_node.get_parser` |
| `nerve.core.nodes.terminal.get_parser` (for WezTermNode/ClaudeWezTermNode tests) | `nerve.core.nodes.terminal.wezterm_node.get_parser` |

#### File: `tests/core/nodes/test_unified_api.py`

Update mock paths:

| Old Path | New Path |
|----------|----------|
| `nerve.core.nodes.terminal.PTYBackend` | `nerve.core.nodes.terminal.pty_node.PTYBackend` |
| `nerve.core.nodes.terminal.WezTermBackend` | `nerve.core.nodes.terminal.wezterm_node.WezTermBackend` |

#### File: `tests/server/test_engine.py`

These mocks target the class methods directly and will continue to work because:
- `nerve.core.nodes.terminal.PTYNode.create` - Still valid (imports from package `__init__.py`)
- `nerve.core.nodes.terminal.WezTermNode.create` - Still valid
- `nerve.core.nodes.terminal.WezTermNode.attach` - Still valid
- `nerve.core.nodes.terminal.ClaudeWezTermNode.create` - Still valid

**No changes required** for `test_engine.py` because the mocks use the package-level import path which re-exports the classes.

### Phase 4: Delete Old File

Remove:
- `src/nerve/core/nodes/terminal.py`

## Verification Checklist

### After Implementation, Verify:

- [ ] `from nerve.core.nodes.terminal import PTYNode` works
- [ ] `from nerve.core.nodes.terminal import WezTermNode` works
- [ ] `from nerve.core.nodes.terminal import ClaudeWezTermNode` works
- [ ] `from nerve.core.nodes import PTYNode, WezTermNode, ClaudeWezTermNode` works
- [ ] All tests in `tests/core/nodes/test_terminal.py` pass
- [ ] All tests in `tests/core/nodes/test_unified_api.py` pass
- [ ] `src/nerve/core/nodes/terminal.py` no longer exists
- [ ] `ls src/nerve/core/nodes/terminal/` shows: `__init__.py`, `pty_node.py`, `wezterm_node.py`, `claude_wezterm_node.py`
- [ ] No `__pycache__` issues (clean build)
- [ ] Run `uv run pytest tests/` - all tests pass

## Implementation Notes

### Order of Operations

1. Create `terminal/` directory
2. Create `terminal/__init__.py` with placeholder imports (will fail initially)
3. Create `terminal/pty_node.py` - copy PTYNode class with its imports
4. Create `terminal/wezterm_node.py` - copy WezTermNode class with its imports
5. Create `terminal/claude_wezterm_node.py` - copy ClaudeWezTermNode class, update WezTermNode import
6. Update `terminal/__init__.py` with real imports
7. Update test mock paths in `test_terminal.py`
8. Run tests to verify
9. Delete `terminal.py`
10. Run full test suite

### Potential Issues

1. **Import timing**: ClaudeWezTermNode imports WezTermNode - ensure no circular import by importing from the specific module, not the package
2. **Cached bytecode**: May need to clear `__pycache__` directories after deleting `terminal.py`
3. **IDE caching**: IDEs may cache old import paths - may need refresh

### What NOT to Change

- The implementation of any class methods
- Any public API signatures
- Any docstrings (except module-level docstrings which should match the module content)
- The `core/nodes/__init__.py` import line (it already uses the correct path pattern)
- Any consumer import statements (they use package-level imports which remain valid)

## Files to Create

| File Path | Description |
|-----------|-------------|
| `src/nerve/core/nodes/terminal/__init__.py` | Package init, re-exports all classes |
| `src/nerve/core/nodes/terminal/pty_node.py` | PTYNode dataclass |
| `src/nerve/core/nodes/terminal/wezterm_node.py` | WezTermNode dataclass |
| `src/nerve/core/nodes/terminal/claude_wezterm_node.py` | ClaudeWezTermNode dataclass |

## Files to Modify

| File Path | Change |
|-----------|--------|
| `tests/core/nodes/test_terminal.py` | Update mock paths to new module locations |
| `tests/core/nodes/test_unified_api.py` | Update mock paths to new module locations |

## Files to Delete

| File Path | Reason |
|-----------|--------|
| `src/nerve/core/nodes/terminal.py` | Replaced by terminal/ package |

## Success Criteria

1. All existing tests pass without modification to test logic (only mock paths change)
2. All consumer imports continue to work unchanged
3. `terminal.py` is deleted (no compatibility shim)
4. Each new file contains exactly one dataclass
5. No feature regression
