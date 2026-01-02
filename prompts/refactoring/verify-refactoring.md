{{CONTEXT}}

**Objective:** Verify refactored code produces IDENTICAL behavior to the original.
  Do not evaluate whether the logic is correct—only whether it is preserved.

  ---

  ## Core Principle

  For every line of OLD code, answer: "Where did this go, and does it still do the same thing?"

  ---

  ## Regression Detection Techniques

  ### 1. Function/Method Mapping
  Create explicit mapping of old → new locations:

  | Old Location | New Location | Status |
  |--------------|--------------|--------|
  | `file_a.py:func_x` | `file_b.py:func_x` | Moved |
  | `class_a.method_y` | `mixin.method_y` | Extracted |
  | `file_a.py:helper_z` | DELETED | Verify unused |

  For each row, verify:
  - Same signature (params, types, defaults, return type)?
  - Same body logic?
  - Same exceptions raised?

  ### 2. Line-by-Line Diff Analysis
  For every removed line, ask:
  - Where did this logic move to?
  - If deleted: Is it truly dead code? Prove it (grep for usages).

  For every added line, ask:
  - Is this new logic, or moved from elsewhere?
  - If new: Does it change behavior or is it structural (formatting, types)?

  For every modified line, ask:
  - What exactly changed?
  - Is the change semantic (affects behavior) or syntactic (formatting, renaming)?

  ### 3. Interface Preservation Check

  **Public API surface must be identical:**
  - [ ] Function/method names unchanged (or properly re-exported)
  - [ ] Parameter names unchanged (for kwargs compatibility)
  - [ ] Parameter order unchanged
  - [ ] Default values unchanged
  - [ ] Return types unchanged
  - [ ] Exceptions raised unchanged
  - [ ] Public imports still work

  **Ask:** "If a caller was using the old code, will their code still work unchanged?"

  ### 4. Side Effect Preservation

  Verify these remain identical:
  - [ ] Files read/written
  - [ ] Environment variables accessed
  - [ ] Logging calls (level, message format)
  - [ ] Metrics/telemetry emitted
  - [ ] State mutations (globals, class attributes, caches)
  - [ ] Network calls
  - [ ] Database operations

  ### 5. Control Flow Mapping

  For complex logic, trace control flow:
  OLD: if A → B → C → return X
  NEW: if A → B → C → return X  ✓ (identical)

  Watch for:
  - Reordered conditions (may change behavior due to short-circuit)
  - Changed boolean logic (De Morgan errors)
  - Different exception handling order
  - Early returns added/removed

  ### 6. Value & Constant Preservation

  Check that these are identical:
  - [ ] Magic numbers
  - [ ] String literals (error messages, format strings)
  - [ ] Default values
  - [ ] Timeout values
  - [ ] Regex patterns
  - [ ] Configuration keys

  ### 7. Import & Dependency Check

  - [ ] All old imports still available from same paths (or re-exported)
  - [ ] No circular imports introduced
  - [ ] No missing imports in new files
  - [ ] Conditional imports preserved

  ---

  ## Regression Checklist (Per File)

  For each modified file:

  1. **Deletions:** For every deleted function/class/block:
     - [ ] Grep codebase—confirm no remaining usages
     - [ ] Or confirm moved to new location with identical behavior

  2. **Extractions:** For code moved to new file:
     - [ ] Signature identical
     - [ ] Body identical (or equivalent)
     - [ ] Imports available in new location
     - [ ] Old location has proper import/re-export if needed

  3. **Modifications:** For changed code:
     - [ ] List every semantic change
     - [ ] Justify each: "This changes behavior" or "This is purely structural"

  4. **Additions:** For new code:
     - [ ] Is this new behavior? (Flag for review)
     - [ ] Or is this infrastructure (types, helpers) that doesn't change behavior?

  ---

  ## Common Regression Patterns to Hunt

  | Pattern | How to Detect |
  |---------|---------------|
  | Dropped code path | Diff shows deletion with no corresponding addition |
  | Changed default value | Compare function signatures old vs new |
  | Lost error handling | Exception handlers removed or changed |
  | Changed return value | Return statements differ |
  | Broken import | Old import path no longer works |
  | Reordered operations | Side effects may occur in different order |
  | Changed string literal | Error messages, log formats differ |
  | Lost special case | `if` branch removed without equivalent |
  | Changed condition | Boolean expression subtly different |
  | Closure/scope change | Variable captured differently in extracted code |

  ---

  ## Verification Commands

  Run these to verify no regressions:

  ```bash
  # Find all usages of deleted function
  grep -r "deleted_function_name" --include="*.py"

  # Verify old imports still work
  python -c "from old.path import thing"

  # Verify tests pass
  pytest tests/ -x

  # Compare function signatures
  diff <(grep -A2 "def func" old.py) <(grep -A2 "def func" new.py)

  ---
  Activation Instruction

  Before reviewing a refactor, state: "I am in regression detection mode. I will verify behavior is PRESERVED, not evaluate if it's correct. Every deletion must be accounted for. Every change must be justified as semantic or structural."

  For EACH file in the diff:
  1. Map every deleted/moved piece of code to its new location
  2. Verify signatures and logic are identical
  3. Confirm no callers are broken
  4. Only after full mapping, mark as "no regression"


