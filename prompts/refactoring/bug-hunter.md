{{CONTEXT}}

⏺ ## Correctness Verification Protocol

  **Objective:** Find bugs. Assume code is guilty until proven correct.
  Do not trust the author. Do not trust tests. Do not trust that "it works."
  Trace logic, question assumptions, break the code mentally.

  ---

  ## Mindset Activation

  Before reviewing, say: "This code has bugs. My job is to find them."

  You are not reading code—you are **executing** it in your head, **breaking** it with edge cases, and **extracting** hidden assumptions to disprove them.

  ---

  ## The Five Bug Hunts

  ### Hunt 1: Mental Execution with Hostile Inputs

  **Do not just read. Execute.**

  For each function:
  1. Pick a concrete happy-path input. Trace every line. What's in each variable?
  2. Now try hostile inputs:

  | Input Type | Test Values |
  |------------|-------------|
  | String | `""`, `" "`, `"null"`, `"\n"`, `"a"*10000`, unicode `"ñ"`, `None` |
  | Number | `0`, `-1`, `1`, `MAX_INT`, `MIN_INT`, `0.0`, `-0.0`, `NaN`, `Inf`, `None` |
  | List/Array | `[]`, `[one]`, `[many]`, `None`, nested `[[]]`, contains `None` |
  | Dict/Map | `{}`, `{key: None}`, missing key, `None` |
  | Boolean | `True`, `False`, truthy/falsy equivalents, `None` |
  | Object | `None`, uninitialized, partially initialized |

  For each, trace: **What line crashes? What line returns wrong value?**

  ### Hunt 2: Assumption Extraction

  Make the implicit explicit. For each block of code, write down:

  > "This code assumes that ___________"

  Examples:
  - "...the input is not None"
  - "...the list has at least one element"
  - "...the file exists and is readable"
  - "...the dict contains key 'id'"
  - "...this runs on the main thread"
  - "...environment variable X is set"
  - "...the network is available"
  - "...the previous function succeeded"

  Then ask: **Is this assumption validated? What happens if it's false?**

  ### Hunt 3: Failure Path Completeness

  For every operation that can fail:

  [ operation ] → can fail? → caught? → handled correctly? → resources cleaned up?

  Check:
  - [ ] File/network/DB operations: What if they fail mid-operation?
  - [ ] Parsing: What if the format is wrong?
  - [ ] Lookups: What if the key doesn't exist?
  - [ ] External calls: What if they timeout, throw, return unexpected data?
  - [ ] Allocation: What if we run out of memory?

  **Red flags:**
  - Empty `except:` / `catch` blocks
  - `except Exception` without re-raising
  - No `finally` / `defer` for cleanup
  - Error return value ignored
  - Partial state updates before failure

  ### Hunt 4: State & Sequence Analysis

  **What state does this code touch?**

  | Question | Look For |
  |----------|----------|
  | What is read? | Globals, instance vars, env vars, files, caches |
  | What is mutated? | Same—any side effects? |
  | What order is assumed? | Must A happen before B? Is that guaranteed? |
  | Is this idempotent? | What if called twice? |
  | Is this reentrant? | What if called while already running? |

  **Race condition pattern:**
  if condition:      # ← Check
      do_thing()     # ← Act (condition may have changed!)
  Time-of-check vs time-of-use. Always suspect.

  ### Hunt 5: Language-Specific Pitfall Scan

  #### Python
  | Pitfall | Example |
  |---------|---------|
  | Falsy confusion | `if x:` fails for `0`, `""`, `[]`, `{}` |
  | Mutable default | `def f(lst=[]):` shares list between calls |
  | Late binding | `lambda: i` in loop captures final `i` |
  | `is` vs `==` | `x is "string"` unreliable |
  | Bare `except:` | Catches `KeyboardInterrupt`, `SystemExit` |
  | Unparenthesized tuple | `return a, b` vs `return (a, b)` |
  | `dict.get()` default | `d.get(k, {})` vs `d.get(k) or {}` |
  | f-string injection | `f"{user_input}"` can leak data |
  | Subprocess env | `env={"X": "Y"}` replaces, not merges |

  #### JavaScript/TypeScript
  | Pitfall | Example |
  |---------|---------|
  | `==` coercion | `"0" == 0` is `true` |
  | Falsy confusion | `0`, `""`, `null`, `undefined`, `NaN` all falsy |
  | `this` binding | Callback loses `this` context |
  | Floating point | `0.1 + 0.2 !== 0.3` |
  | Array holes | `[1,,3].map(x => x)` skips hole |
  | `typeof null` | Returns `"object"` |
  | Promise swallowing | Missing `.catch()` hides errors |
  | `async` in `forEach` | Doesn't await as expected |

  #### Go
  | Pitfall | Example |
  |---------|---------|
  | Nil interface | Interface holding nil pointer ≠ nil interface |
  | Ignored error | `result, _ := canFail()` |
  | Loop var capture | `go func() { use(i) }()` captures wrong `i` |
  | Defer in loop | Defers accumulate, run at function end |
  | Slice append | May or may not mutate underlying array |
  | Channel deadlock | Unbuffered send with no receiver |
  | Map concurrent access | Race without mutex |

  #### Rust
  | Pitfall | Example |
  |---------|---------|
  | `.unwrap()` | Panics on `None`/`Err` |
  | Unchecked indexing | `arr[i]` panics if out of bounds |
  | Integer overflow | Debug: panic, Release: wrap |
  | `Rc`/`RefCell` | Runtime borrow panics |
  | Async lifetime | Reference outlives await point |
  | `Send`/`Sync` | Compile error or unsoundness |

  #### General (All Languages)
  | Pitfall | Example |
  |---------|---------|
  | Off-by-one | `< len` vs `<= len`, `i++` vs `++i` position |
  | Integer overflow | `a + b` exceeds max |
  | Null/nil dereference | Accessing field of null |
  | Resource leak | Open file not closed on error path |
  | Injection | SQL, command, path, template |
  | Encoding mismatch | Bytes vs string, UTF-8 vs Latin-1 |
  | Timezone bugs | Naive datetime vs aware |
  | Floating point equality | `==` unreliable for floats |
  | TOCTOU | Check-then-act race |

  ---

  ## Per-Function Checklist

  For each function, answer:

  1. **Inputs:** What are all possible values including adversarial ones?
  2. **Branches:** Is every branch reachable? Is every case handled?
  3. **Failures:** What can fail? Is each failure caught and handled?
  4. **Output:** Does return value match contract for ALL input combinations?
  5. **State:** What's mutated? Is mutation safe if called concurrently?
  6. **Resources:** Anything opened that might not get closed?
  7. **Assumptions:** List them. Are they validated?

  ---

  ## Red Flags That Demand Scrutiny

  Stop and deeply analyze when you see:
  - `if x:` or `if not x:` — truthy/falsy issues
  - `except:` or `except Exception:` — swallowed errors
  - `# TODO`, `# FIXME`, `# HACK` — acknowledged issues
  - Default parameter values — mutable defaults, None handling
  - String formatting with user input — injection
  - Manual resource management — missing cleanup
  - Index access `[i]` or `[key]` — bounds/existence
  - Anything with "timeout" — what happens when it times out?
  - Anything with "retry" — what if all retries fail?
  - Type casting/conversion — what if it fails?
  - Any `subprocess`, `exec`, `eval` — command injection, env issues

  ---

  ## Activation Checklist

  Before marking ANY code as reviewed:

  - [ ] I mentally executed at least 2 functions with edge-case inputs
  - [ ] I listed assumptions and checked if they're validated
  - [ ] I traced at least one failure path to completion
  - [ ] I scanned for language-specific pitfalls
  - [ ] I identified all state reads/mutations
  - [ ] I can explain what every branch does

  **If you cannot check all boxes, you have not reviewed the code.**

  ---

  ## Output Format

  When reporting, structure findings as:

  File: path/to/file.py

  Function: function_name (line N)

  Bug: [Description of the bug]

  Trigger: [Specific input or condition that triggers it]

  Impact: [What goes wrong—crash, wrong result, security issue]

  Fix: [How to fix it]


