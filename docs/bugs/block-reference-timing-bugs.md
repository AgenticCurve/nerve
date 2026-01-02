# Block Reference Timing Bugs

**Date:** 2026-01-02
**Status:** Partially Fixed
**Severity:** High (user-facing) / Medium (latent)
**Components:** `variables.py`, `executor.py`, `blocks.py`

---

## Executive Summary

Investigation revealed 6 related bugs in the block reference system (`:::node`, `:::-N`, `:::last`). The critical user-facing bug (TOCTOU race) has been fixed. Five latent bugs remain that depend on a currently-maintained invariant.

| Bug | Description | Severity | Status |
|-----|-------------|----------|--------|
| #1 | TOCTOU race in `:::node` resolution | **HIGH** | **FIXED** |
| #2 | List index vs block number confusion in executor | MEDIUM | Latent |
| #3 | Inconsistent dependency value types | MEDIUM | Latent |
| #4 | `:::-0` semantic inconsistency | LOW | Latent |
| #5 | Out-of-order block addition | MEDIUM | Latent |
| #6 | Missing `exclude_block_from` in node lookups | **HIGH** | **FIXED** (same as #1) |

---

## Bug #1 & #6: TOCTOU Race in Node Reference Resolution

### Symptom

When rapidly typing commands that reference other nodes, the wrong content is silently used:

```text
@nav write a poem about sunset
@driver review :::nav         <- wants to review the poem
@nav write a story about rain
@driver critique :::nav       <- wants to critique the story
```

**Expected:** Driver reviews the poem, then critiques the story.
**Actual:** Driver might review the story (or empty content) instead of the poem.

### Root Cause

The `:::node` reference was resolved at **two different times** with different results:

1. **Dependency extraction** (block creation): Captured specific block number
2. **Variable expansion** (block execution): Re-resolved to "current last block"

Between these two moments, new blocks could be added to the timeline.

**Code flow:**

```text
Block 2: @driver review :::nav
  ├─ extract_block_dependencies() → :::nav = Block 1 → depends_on={1}
  ├─ Block 3: @nav write story (added to timeline)
  └─ expand_variables() → :::nav = Block 3 (WRONG!)
```

### Technical Details

**Before fix - `variables.py:132-139`:**
```python
def _get_node_blocks(self, node_ref: str) -> list[Block]:
    node_id = self._resolve_node_id(node_ref)
    return [b for b in self.timeline.blocks if b.node_id == node_id]
    # ↑ No filtering - sees ALL blocks including ones added after extraction
```

**After fix - `variables.py:132-150`:**
```python
def _get_node_blocks(self, node_ref: str) -> list[Block]:
    node_id = self._resolve_node_id(node_ref)
    blocks = [b for b in self.timeline.blocks if b.node_id == node_id]

    # Exclude blocks at or after the specified number
    if self.exclude_block_from is not None:
        blocks = [b for b in blocks if b.number < self.exclude_block_from]

    return blocks
```

### Fix Verification

The fix ensures that when Block N expands `:::nav`, it only sees nav blocks with `number < N`, matching what was captured at dependency extraction time.

---

## Bug #2: List Index vs Block Number Confusion in Executor

### Description

The executor uses list index access (`timeline.blocks[dep_num]`) instead of block number lookup (`timeline[dep_num]`).

### Affected Code

**`executor.py:105-111`:**
```python
for dep_num in block.depends_on:
    if dep_num >= len(self.timeline.blocks):
        all_ready = False
        break
    dep_block = self.timeline.blocks[dep_num]  # ← List index, not block number!
```

Same pattern at lines 199-205 and 238-244.

### Why It Works (For Now)

The `Timeline.add()` method maintains the invariant `blocks[i].number == i`:

```python
def add(self, block: Block) -> None:
    block.number = self._next_number  # Assigns sequential number
    self._next_number += 1
    self.blocks.append(block)          # Appends at end
```

### When It Would Break

If `reserve_number()` + `add_with_number()` are used out of order:

```python
num1 = timeline.reserve_number()  # Returns 0
num2 = timeline.reserve_number()  # Returns 1
timeline.add_with_number(blockA, num2)  # blocks[0].number = 1
timeline.add_with_number(blockB, num1)  # blocks[1].number = 0
# Now: blocks[0].number = 1, blocks[1].number = 0 (BROKEN!)
```

### Correct Implementation

```python
dep_block = self.timeline[dep_num]  # Uses Timeline.__getitem__ with proper lookup
# or
dep_block = self.timeline.get(dep_num)
```

---

## Bug #3: Inconsistent Dependency Value Types

### Description

`extract_block_dependencies()` adds different value types to the dependencies set:

| Pattern | Code | What's Added |
|---------|------|--------------|
| `:::N` | `int(match.group(1))` | Block NUMBER (from text) |
| `:::-N` | `len(blocks) + neg_idx` | List INDEX |
| `:::last` | `len(blocks) - 1` | List INDEX |
| `:::node[N]` | `target_block.number` | Block NUMBER |
| `:::node` | `node_blocks[-1].number` | Block NUMBER |

### Affected Code

**`variables.py:488-496`:**
```python
# Pattern 2: :::-N - adds INDEX
for match in re.finditer(r":::(-\d+)", text):
    neg_idx = int(match.group(1))
    actual_idx = len(timeline.blocks) + neg_idx  # This is an INDEX
    if 0 <= actual_idx < len(timeline.blocks):
        dependencies.add(actual_idx)  # Adding INDEX, not NUMBER

# Pattern 3: :::last - adds INDEX
if ":::last" in text and timeline.blocks:
    dependencies.add(len(timeline.blocks) - 1)  # Adding INDEX, not NUMBER
```

### Correct Implementation

```python
# Pattern 2: :::-N
if 0 <= actual_idx < len(timeline.blocks):
    dependencies.add(timeline.blocks[actual_idx].number)  # Use .number

# Pattern 3: :::last
if ":::last" in text and timeline.blocks:
    dependencies.add(timeline.blocks[-1].number)  # Use .number
```

---

## Bug #4: `:::-0` Semantic Inconsistency

### Description

`:::-0` behaves inconsistently between dependency extraction and expansion.

### Behavior

**Dependency extraction (`variables.py:488-492`):**
```python
neg_idx = int("-0")  # = 0 (Python has no negative zero for int)
actual_idx = len(blocks) + 0  # = len(blocks)
if 0 <= len(blocks) < len(blocks):  # ALWAYS FALSE
    dependencies.add(...)  # Never executes!
```

**Variable expansion (`variables.py:209-224`):**
```python
neg_idx = int("-0")  # = 0
block = self._get_block_by_negative_index(0)
# In _get_block_by_negative_index:
return blocks[0]  # Returns FIRST block (Python: -0 == 0)
```

### Result

- Dependency extraction: Adds nothing (no wait)
- Variable expansion: Returns first block

This is semantically wrong - `:::-0` silently returns stale data without waiting.

### Suggested Fix

```python
# Reject -0 explicitly
if neg_idx == 0:
    continue  # or raise error: ":::-0 is not valid, use :::0 for first block"
```

---

## Bug #5: Out-of-Order Block Addition

### Description

`add_with_number()` always appends to the end of the list, regardless of the block number, which can break the `blocks[i].number == i` invariant.

### Affected Code

**`blocks.py:277-285`:**
```python
def add_with_number(self, block: Block, number: int) -> None:
    block.number = number
    self.blocks.append(block)  # Always appends at END, ignoring number
```

### Scenario

```python
timeline.reserve_number()  # Returns 0, _next_number = 1
timeline.reserve_number()  # Returns 1, _next_number = 2
timeline.add_with_number(blockA, 1)  # blocks = [blockA], blockA.number = 1
timeline.add_with_number(blockB, 0)  # blocks = [blockA, blockB], blockB.number = 0

# Result:
# blocks[0].number = 1  (WRONG - should be 0)
# blocks[1].number = 0  (WRONG - should be 1)
```

### Suggested Fix

```python
def add_with_number(self, block: Block, number: int) -> None:
    block.number = number
    # Insert at correct position to maintain ordering
    insert_idx = 0
    for i, b in enumerate(self.blocks):
        if b.number > number:
            break
        insert_idx = i + 1
    self.blocks.insert(insert_idx, block)
```

---

## The Critical Invariant

All latent bugs (#2, #3, #4, #5) depend on this invariant:

```text
blocks[i].number == i  for all i
```

This invariant is currently maintained because:
1. `add()` assigns sequential numbers and appends
2. `reserve_number()` + `add_with_number()` are not used in problematic patterns

**If this invariant is ever broken, bugs #2, #3, and #5 will manifest.**

---

## Reproduction Steps

### Bug #1/#6 (TOCTOU - now fixed)

```python
# Rapid command execution
@nav task1        # Block 0
@driver :::nav    # Block 1, depends on Block 0, should use Block 0
@nav task2        # Block 2

# If Block 1 executes after Block 2 is added:
# - Dependency was on Block 0
# - But expansion would see [Block 0, Block 2] and use Block 2 (WRONG)
```

### Bugs #2, #3, #5 (Latent - requires breaking invariant)

```python
# Would need to use reserve_number + add_with_number out of order
# Currently no code path does this
```

### Bug #4 (`:::-0`)

```python
@nav hello
@driver :::-0    # Silently uses Block 0 without dependency wait
```

---

## Recommendations

### Immediate (Done)

1. ~~Fix `_get_node_blocks()` to respect `exclude_block_from`~~ **FIXED**

### Short-term

1. Add assertion to verify invariant: `assert all(b.number == i for i, b in enumerate(timeline.blocks))`
2. Consider deprecating or removing `reserve_number()` / `add_with_number()` if not needed

### Long-term

1. Refactor to use block numbers consistently (not list indices)
2. Consider using a dict (`{number: block}`) instead of list for O(1) lookup by number
3. Add integration tests for rapid command execution scenarios

---

## Test Coverage

Tests should cover:

1. **TOCTOU scenario:** Rapid `:::node` references with interleaved blocks
2. **Cold start:** `:::node` when node has zero blocks
3. **Edge cases:** `:::-0`, `:::last` with empty timeline
4. **Invariant verification:** Block number matches list index after various operations

---

## References

- `src/nerve/frontends/tui/commander/variables.py` - Variable expansion and dependency extraction
- `src/nerve/frontends/tui/commander/executor.py` - Async execution with dependency handling
- `src/nerve/frontends/tui/commander/blocks.py` - Block and Timeline data structures
