# TUI Refactoring Plan

This document tracks refactoring opportunities identified in `src/nerve/frontends/tui/commander/`.

## Summary

- **Total opportunities:** 16
- **Estimated total effort:** 5-7 days
- **Primary issues:** Large files, duplicated patterns, missing abstractions

---

## Consolidated Opportunities

| Priority | ID | Opportunity | Files Affected | Effort | Status |
|----------|-----|-------------|----------------|--------|--------|
| **P0** | 1 | Fix `node.workflow` theme style | `themes.py` | 15 min | ✅ |
| **P1** | 2 | Extract Command Handlers from `commander.py` | `commander.py` (919 lines) | 4-6 hrs | ⬜ |
| **P1** | 3 | Split `workflow_runner.py` | `workflow_runner.py` (1093→802 lines) | 4-6 hrs | ✅ |
| **P1** | 4 | Extract Result Handler Abstraction | `executor.py`, `loop.py` | 2-3 hrs | ✅ |
| **P1** | 5 | Unify Status Indicators/Formatting | `blocks.py`, `workflow_runner.py`, `monitor.py`, `executor.py` | 2-3 hrs | ✅ |
| **P2** | 6 | Consolidate Rendering Utilities | `rendering.py`, `workflow_runner.py`, `monitor.py` | 3-4 hrs | ✅ |
| **P2** | 7 | Extract Variable Expansion Strategy | `variables.py` (543 lines) | 3-4 hrs | ⬜ |
| **P2** | 8 | Standardize Error Handling | Multiple files | 2-3 hrs | ⬜ |
| **P2** | 9 | Extract Clipboard Utility | `workflow_runner.py` | 1 hr | ✅ |
| **P2** | 10 | Entity Type Detection Logic | `commander.py`, `rendering.py`, `commands.py` | 1-2 hrs | ⬜ |
| **P2** | 11 | Consistent Table Rendering | `rendering.py:print_nodes` | 30 min | ✅ |
| **P3** | 12 | Theme Application Cleanup | `themes.py` + consumers | 2-3 hrs | ⬜ |
| **P3** | 13 | Command Dispatch Modernization | `commands.py` | 2-3 hrs | ⬜ |
| **P3** | 14 | Remove Unused Code | `executor.py` (606→451 lines) | 30 min | ✅ |
| **P3** | 15 | Entity Type Constants | Multiple files | 1 hr | ⏸️ Optional |
| **P3** | 16 | Add Block Type Annotations | `blocks.py` | 30 min | ✅ |

---

## Implementation Phases

### Phase 1 - Quick Wins & Foundations (1 day)
- #1: Fix `node.workflow` theme style (bug fix)
- #5: Unify status indicators (enables cleaner code later)
- #11: Consistent table rendering

### Phase 2 - Core Abstractions (2-3 days)
- #4: Extract result handler
- #6: Consolidate rendering utilities
- #9: Extract clipboard utility

### Phase 3 - Large Refactors (3-4 days)
- #3: Split `workflow_runner.py`
- #2: Extract commander handlers
- #7: Variable expansion strategy

### Phase 4 - Polish (1-2 days)
- #8, #10, #12-16

---

## Detailed Implementation Notes

---

# Phase 1: Quick Wins & Foundations

**Estimated time:** 1 day
**Items:** #1, #5, #11

---

## Item #1: Fix `node.workflow` Theme Style

**Priority:** P0 (Bug fix)
**Effort:** 15 minutes
**File:** `themes.py`

### Problem

`blocks.py:118-121` references `node.workflow` style but it's not defined in `themes.py`:

```python
# blocks.py:118-121
style = (
    f"node.{self.block_type}"
    if self.block_type in ("bash", "llm", "graph", "workflow")
    else "bold"
)
```

When `block_type == "workflow"`, Rich tries to use style `node.workflow` which doesn't exist.

### Solution

Add `node_workflow` parameter to `create_theme()` and include it in all theme definitions.

### Implementation Steps

1. **Edit `themes.py`** - Add parameter to `create_theme()`:

   ```python
   def create_theme(
       *,
       # ... existing params ...
       node_python: str = "yellow",
       node_workflow: str = "blue",  # ADD THIS LINE (after node_python)
       # ...
   ) -> Theme:
   ```

2. **Edit `themes.py`** - Add to the returned Theme dict (after `node.python`):

   ```python
   return Theme(
       {
           # ...
           "node.python": node_python,
           "node.workflow": node_workflow,  # ADD THIS LINE
           # ...
       }
   )
   ```

3. **Edit `themes.py`** - Add to each theme definition:

   **NORD_THEME** (line ~74):
   ```python
   node_workflow="#81A1C1",  # Nord frost blue
   ```

   **DRACULA_THEME** (line ~94):
   ```python
   node_workflow="#BD93F9",  # Dracula purple
   ```

   **MONO_THEME** (line ~114):
   ```python
   node_workflow="bold",
   ```

### Verification

```bash
# Run the TUI and execute a workflow to verify styling works
nerve commander
# Then: %some_workflow input
```

---

## Item #5: Unify Status Indicators/Formatting

**Priority:** P1 (Foundational)
**Effort:** 2-3 hours
**Files:** `themes.py`, `blocks.py`, `workflow_runner.py`, `monitor.py`

### Problem

Status emoji mappings are duplicated in multiple locations with slight variations:

| Location | pending | waiting | running | completed | error |
|----------|---------|---------|---------|-----------|-------|
| `blocks.py:130-136` | ⏳ | ⏸️ | - | ⚡ (async) | - |
| `workflow_runner.py:512-515` | ⏳ | ⏸️ | ▶️ | ✅ | - |
| `workflow_runner.py:550-552` | - | - | ⏳ | ✅ | ❌ |
| `workflow_runner.py:672` | - | - | ⏳ | ✅ | ❌ |
| `monitor.py:501-505` | ⏳ | ⏸️ | - | ✓ | ✗ |
| `monitor.py:575-579` | ⏳ | ⏸️ | - | ✓ | ✗ |

This leads to:
- Inconsistent icons for same status (✓ vs ✅)
- Maintenance burden when changing icons
- Easy to miss locations when updating

### Solution

Create a single source of truth in `themes.py` with helper function.

### Implementation Steps

#### Step 1: Add constants to `themes.py`

Add at the end of the file (before or after `get_theme()`):

```python
# =============================================================================
# Status Indicators
# =============================================================================

STATUS_INDICATORS: dict[str, str] = {
    "pending": "⏳",
    "waiting": "⏸️",
    "running": "▶️",
    "completed": "✅",
    "error": "❌",
    "failed": "❌",
    "cancelled": "⊘",
}

# Compact indicators for dense UIs (monitor cards)
STATUS_INDICATORS_COMPACT: dict[str, str] = {
    "pending": "⏳",
    "waiting": "⏸️",
    "running": "▶️",
    "completed": "✓",
    "error": "✗",
    "failed": "✗",
    "cancelled": "⊘",
}


def get_status_indicator(status: str, *, compact: bool = False, default: str = "?") -> str:
    """Get emoji indicator for a status.

    Args:
        status: Status string (pending, waiting, running, completed, error, failed, cancelled).
        compact: Use compact single-char indicators (for dense UIs).
        default: Fallback if status not recognized.

    Returns:
        Emoji/character indicator for the status.
    """
    indicators = STATUS_INDICATORS_COMPACT if compact else STATUS_INDICATORS
    return indicators.get(status, default)
```

#### Step 2: Update `blocks.py`

**File:** `blocks.py`

1. Add import at top (after existing imports):
   ```python
   from nerve.frontends.tui.commander.themes import get_status_indicator
   ```

2. Replace lines 129-136 in `_build_header()`:

   **Before:**
   ```python
   # Status indicator for pending/waiting/async-completed
   if self.status == "pending":
       header.append("⏳ ", style="pending")
   elif self.status == "waiting":
       header.append("⏸️ ", style="dim")
   elif self.status == "completed" and self.was_async:
       # Show ⚡ for blocks that completed asynchronously
       header.append("⚡ ", style="success")
   ```

   **After:**
   ```python
   # Status indicator for pending/waiting/async-completed
   if self.status == "pending":
       header.append(f"{get_status_indicator('pending')} ", style="pending")
   elif self.status == "waiting":
       header.append(f"{get_status_indicator('waiting')} ", style="dim")
   elif self.status == "completed" and self.was_async:
       # Show ⚡ for blocks that completed asynchronously
       header.append("⚡ ", style="success")
   ```

   Note: Keep the ⚡ hardcoded for async as it's a special case, not a status.

#### Step 3: Update `workflow_runner.py`

**File:** `workflow_runner.py`

1. Add import (find existing imports from themes, extend them):
   ```python
   from nerve.frontends.tui.commander.themes import get_status_indicator, get_theme
   ```

2. Replace lines 511-515 in `_get_header()`:

   **Before:**
   ```python
   status_emoji = {
       "pending": "⏳",
       "running": "▶️",
       "waiting": "⏸️",
       "completed": "✅",
   }.get(self.state, "○")
   ```

   **After:**
   ```python
   status_emoji = get_status_indicator(self.state, default="○")
   ```

3. Replace lines 549-554 in `_get_steps_list()`:

   **Before:**
   ```python
   status_icons = {
       "running": "⏳",
       "completed": "✅",
       "error": "❌",
   }
   status_icon = status_icons.get(step.status, "○")
   ```

   **After:**
   ```python
   status_icon = get_status_indicator(step.status, default="○")
   ```

4. Replace line 672 in `_get_full_screen_header()`:

   **Before:**
   ```python
   status_icon = {"running": "⏳", "completed": "✅", "error": "❌"}.get(step.status, "○")
   ```

   **After:**
   ```python
   status_icon = get_status_indicator(step.status, default="○")
   ```

#### Step 4: Update `monitor.py`

**File:** `monitor.py`

1. Add import at top:
   ```python
   from nerve.frontends.tui.commander.themes import get_status_indicator
   ```

2. Replace lines 501-506 in `_render_card()`:

   **Before:**
   ```python
   status_emoji = {
       "pending": "⏳",
       "waiting": "⏸️",
       "completed": "✓",
       "error": "✗",
   }.get(block.status, "?")
   ```

   **After:**
   ```python
   status_emoji = get_status_indicator(block.status, compact=True)
   ```

3. Replace lines 575-580 (second occurrence in same file):

   **Before:**
   ```python
   status_emoji = {
       "pending": "⏳",
       "waiting": "⏸️",
       "completed": "✓",
       "error": "✗",
   }.get(block.status, "?")
   ```

   **After:**
   ```python
   status_emoji = get_status_indicator(block.status, compact=True)
   ```

### Verification

```bash
# Run tests
uv run pytest src/nerve/frontends/tui/commander/ -v

# Manual verification - run commander and check status icons display correctly
nerve commander
```

---

## Item #11: Consistent Table Rendering

**Priority:** P2
**Effort:** 30 minutes
**File:** `rendering.py`

### Problem

`print_nodes()` uses simple text formatting while `print_graphs()`, `print_entities()`, and `print_workflows()` use Rich Table. This creates visual inconsistency.

**Current (`print_nodes`):**
```
Available Nodes:
  claude (llm)
  bash (bash)
```

**Other functions (using Table):**
```
┌────────┬──────┐
│ ID     │ Type │
├────────┼──────┤
│ claude │ llm  │
│ bash   │ bash │
└────────┴──────┘
```

### Solution

Update `print_nodes()` to use Rich Table, matching the other print functions.

### Implementation Steps

**File:** `rendering.py`

Replace `print_nodes()` function (lines 117-131):

**Before:**
```python
def print_nodes(console: Console, nodes: dict[str, str]) -> None:
    """Print available nodes.

    Args:
        console: Rich console for output.
        nodes: Dict of node_id -> node_type.
    """
    console.print()
    console.print("[bold]Available Nodes:[/]")
    if not nodes:
        console.print("  [dim]No nodes in session[/]")
    else:
        for node_id, node_type in nodes.items():
            console.print(f"  [bold]{node_id}[/] ({node_type})")
    console.print()
```

**After:**
```python
def print_nodes(console: Console, nodes: dict[str, str]) -> None:
    """Print available nodes.

    Args:
        console: Rich console for output.
        nodes: Dict of node_id -> node_type.
    """
    from rich.table import Table

    console.print()
    console.print("[bold]Available Nodes:[/]")
    if not nodes:
        console.print("  [dim]No nodes in session[/]")
    else:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="dim")
        for node_id, node_type in nodes.items():
            table.add_row(node_id, node_type)
        console.print(table)
    console.print()
```

### Verification

```bash
# Run commander and check :nodes output
nerve commander
# Then type: :nodes
```

---

## Phase 1 Checklist

- [x] #1: Add `node.workflow` to `themes.py` `create_theme()`
- [x] #1: Add `node.workflow` to Theme dict in `create_theme()`
- [x] #1: Add `node_workflow` to NORD_THEME
- [x] #1: Add `node_workflow` to DRACULA_THEME
- [x] #1: Add `node_workflow` to MONO_THEME
- [x] #5: Add `STATUS_INDICATORS` constants (in `status_indicators.py` - separate module)
- [x] #5: Add `get_status_indicator()` function (in `status_indicators.py`)
- [x] #5: Update `blocks.py` to use `get_status_indicator()`
- [x] #5: Update `workflow_runner.py` to use `get_status_emoji()` (3 locations)
- [x] #5: Update `monitor.py` to use `get_status_emoji(compact=True)` (2 locations)
- [x] #11: Update `print_nodes()` to use Rich Table
- [x] Run tests: `uv run pytest tests/frontends/tui/ -v` (76 passed)
- [ ] Manual verification in commander TUI

### Implementation Notes

**#5 Deviation from plan:** Created separate `status_indicators.py` module instead of adding to `themes.py`. This provides better separation of concerns - themes handle colors/styles, status_indicators handle status representations. The module includes:
- Standard indicators (✅, ❌) for most contexts
- Compact indicators (✓, ✗) for dense UIs like monitor cards
- `get_status_emoji(status, compact=False)` helper function

---

## Phase 3 Checklist (#3: Split workflow_runner.py)

- [x] Step 1: Extract state classes to `workflow_state.py`
  - ViewMode enum
  - StepInfo dataclass
  - TUIWorkflowEvent dataclass
- [x] Step 2: Extract UI rendering to `workflow_ui.py` with mixin pattern
  - WorkflowUIRendererMixin with 9 `_get_*` methods
  - WorkflowRunnerApp inherits from mixin
  - Removed 230+ lines of duplicated rendering code
- [x] Step 3: Evaluate polling extraction (skipped)
  - Polling logic (~196 lines) is tightly coupled to class state
  - Diminishing returns - further extraction adds complexity

### Results

- **Before:** 1093 lines
- **After:** 802 lines (27% reduction)
- **New files created:**
  - `workflow_state.py` (43 lines) - State classes
  - `workflow_ui.py` (288 lines) - UI rendering mixin
- Tests: 76 passed

---

## Phase 4 Checklist (Polish)

- [x] #14: Remove unused `execute_workflow_command()` and `_handle_workflow_gate()`
  - Removed 155 lines of dead code from executor.py (606→451 lines)
- [x] #16: Add `Literal` types to `block_type` and `status` fields
  - Added `BlockType` and `BlockStatus` type aliases to blocks.py
  - Provides compile-time type safety for constrained string values
- [~] #10, #12: Skipped - analysis showed these were incorrect approaches
  - #10: `get_block_type()` and `_infer_backend()` serve different purposes
  - #12: Magic strings in blocks.py are intentional design (dynamic theme lookup)
- [~] #8, #13, #15: Marked optional - diminishing returns

### Results

- **executor.py:** 606 → 451 lines (25% reduction)
- **blocks.py:** Added type constraints (no line change)
- Tests: 76 passed

---

## Status Legend

- ⬜ Not started
- 🔄 In progress
- ✅ Completed
- ⏸️ Blocked
