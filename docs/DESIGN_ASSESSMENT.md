# Nerve Architecture: Design Assessment

## Executive Summary

The Nerve architecture is well-designed with excellent separation of concerns and solid Domain-Driven Design modeling. The core system is pure, reusable, and composable. However, there are several rough edges around parser safety, error handling, persistence, and concurrency that should be addressed before scaling to production.

**Overall verdict**: Strong foundations with some incompleteness in details that will become painful at scale.

---

## Table of Contents

1. [Strengths](#strengths)
2. [Concerns](#concerns)
3. [Strategic Questions](#strategic-questions)
4. [Prioritized Recommendations](#prioritized-recommendations)

---

## Strengths

### 1. Excellent Separation of Concerns

**Core is Pure Stdlib**: The core domain has zero external dependencies and contains no knowledge of servers, networking, or transport. This is a major architectural win.

**Benefits:**
- Embeddable anywhere (scripts, notebooks, libraries, applications)
- Easy to test in isolation
- No framework lock-in
- Simple to reason about

**Boundary Enforcement**: Core → Server → Transport → Frontends is a clean dependency flow. No circular dependencies or cross-layer contamination.

### 2. Solid Domain-Driven Design

**Well-Defined Entities & Aggregates**: Channel, Session, Task, DAG, NerveEngine, SessionStore each have clear responsibilities and enforce invariants.

**Value Objects**: ParsedResponse, Section, TaskResult, Event, Command are properly immutable.

**Aggregate Composition**: Aggregates own their compositions (e.g., DAG owns Tasks, Session owns Channels) and enforce constraints correctly.

**Will scale well**: As complexity grows, the DDD structure provides clear extension points and maintains coherence.

### 3. Flexible Abstraction Strategy

**Parser-per-Command Pattern**: Decoupling parsers from channels is semantically correct—different commands often need different interpretation strategies.

**Example**: A single terminal channel might interpret one command's output as code, another's as JSON, another's as raw text. The parser is a per-command concern, not a channel property.

**Multiple Backend Support**: PTY and WezTerm abstraction allows different terminal management strategies.

### 4. Event-Driven Without Coupling Core

**Server wraps Core with events**: NerveEngine adds event emission without contaminating core domain logic.

**Benefits:**
- Clients get reactive updates
- Core stays pure and testable
- Event infrastructure is pluggable (via EventSink protocol)

### 5. Independent Systems

**Core + Gateway separation**: CLI-based orchestration and API proxying are distinct bounded contexts. Neither depends on the other. Good architectural hygiene.

---

## Concerns

### 1. Parser-per-Command Safety Issue ⚠️ HIGH PRIORITY

**The Problem**: Parsers aren't type-safe. Users must manually remember which parser to use with which channel.

```python
# Both syntactically valid but semantically wrong
channel.send("some input", ClaudeParser)      # ✓ correct
channel.send("some input", GeminiParser)      # ✗ wrong but no error
```

**Risk**: Silent failures when wrong parser is applied. Output parses but yields nonsense.

**Alternative Approach**:
```python
# Default parser attached to channel, override per-command
claude_channel = PTYChannel(parser=ClaudeParser)
claude_channel.send("input")                    # uses ClaudeParser by default
claude_channel.send("input", parser=NoneParser) # override for this command
```

**Impact**: This would make the system safer without losing flexibility.

---

### 2. Session Persistence is Incomplete ⚠️ MEDIUM PRIORITY

**Current State**:
- `SessionMetadata` is persisted to `~/.nerve/sessions.json`
- Channels and their state are NOT persisted
- Users must manually recreate channels after session restore

**The Problem**: This is neither full persistence nor cleanly ephemeral. It's confusing.

```python
# User perspective
session.save()           # ✓ metadata saved
session = Session.load() # ✗ channels are gone, must recreate manually
```

**Design Decision Needed**:
1. **Option A (Full Persistence)**: Persist channel configs, restore them on load
2. **Option B (Cleanly Ephemeral)**: Don't persist sessions at all, or only persist metadata as a "template"
3. **Option C (Hybrid)**: Persist metadata (templates) but require explicit channel creation from metadata

**Current design seems to be Option C but isn't clearly documented.**

---

### 3. Storage Tightly Coupled to Filesystem ⚠️ MEDIUM PRIORITY

**Current**:
```python
# SessionStore directly writes JSON
def save(self, path: Path):
    with open(path, 'w') as f:
        json.dump(...)  # Direct file I/O
```

**Problems**:
- Can't unit test without hitting disk
- No alternative storage backends (databases, cloud)
- Harder to version/migrate session data
- No abstraction for testing

**Should Have**: `SessionRepository` protocol (similar to Channel, Parser, Backend)

```python
class SessionRepository(Protocol):
    async def save(self, session: Session) -> None: ...
    async def load(self, session_id: str) -> Session: ...
    async def delete(self, session_id: str) -> None: ...
    async def list_all(self) -> list[Session]: ...

# Implementations: JSONFileRepository, DatabaseRepository, CloudRepository
```

---

### 4. DAG Execution is Transient ⚠️ MEDIUM PRIORITY

**Current**: DAG results exist only during/after execution. They're not persisted.

**Missing Capabilities**:
- No execution history/audit trail
- Can't replay failed executions
- Can't inspect intermediate results
- Can't learn from past execution patterns

**For Reliable Automation**: Execution history is critical.

**Worth Considering**:
```python
# ExecutionLog aggregate
execution_log = dag.run(capture_history=True)
execution_log.task_results          # All task outcomes
execution_log.events                # Timeline of events
execution_log.replay(from_task_id)  # Re-run from checkpoint
```

Or implement simple event sourcing for DAG executions.

---

### 5. Error Handling Strategy Unclear ⚠️ HIGH PRIORITY

**Unanswered Questions**:
- What happens if a channel dies unexpectedly mid-operation?
- If a DAG task fails, do dependent tasks fail-cascade or skip?
- Parser exceptions—swallowed or propagated?
- Circular dependency detected—fail at add-time or validation-time?
- Channel read timeout—retry or fail immediately?

**Impact**: Critical behaviors aren't formalized. Different parts of the system might handle errors differently. This creates bugs and unpredictable behavior under stress.

**Recommendation**: Document error handling strategy for:
- Channel lifecycle failures
- Parser failures (timeout, exception)
- DAG execution failures (single task, cascade)
- PTY process crashes

Then make this explicit in aggregates:

```python
class DAG:
    def run(self,
            on_task_failure: Literal["cascade", "skip"] = "cascade",
            retry_count: int = 0,
            timeout_ms: int = 30000) -> dict[str, TaskResult]:
        """Explicit failure handling strategy."""
        ...
```

---

### 6. Concurrency Model Not Explicit ⚠️ MEDIUM PRIORITY

**Unanswered Questions**:
- Can two tasks write to the same channel simultaneously?
- Is there channel-level locking?
- Race conditions possible in ChannelManager?
- What guarantees does `run()` provide for concurrent task execution?

**Current Code Hint**: DAG uses `asyncio` with configurable concurrency, but thread-safety isn't documented.

**Recommendation**: Document explicitly:
```python
class DAG:
    """
    Execution guarantees:
    - Tasks execute concurrently up to max_workers
    - Dependency order is preserved
    - Each channel is single-writer (exclusive lock during task execution)
    - Task results are thread-safe (immutable)
    """
```

---

### 7. Event Ordering Guarantees Undefined ⚠️ MEDIUM PRIORITY

**Questions**:
- Are events ordered per-channel? (probably yes, but not stated)
- Across channels? (unclear)
- What if downstream task reads an event before upstream finishes writing?
- Consistency model? (eventual, strong, ???)

**For Correct Clients**: Event ordering must be specified.

**Recommendation**:
```python
class EventProtocol:
    """
    Guarantees:
    - Per-channel events are ordered by timestamp
    - Global ordering not guaranteed
    - Clients should not assume cross-channel event ordering
    - For DAG execution, use event types (TASK_COMPLETED) not timestamps
    """
```

---

### 8. Channel State Transitions are Implicit ⚠️ MEDIUM PRIORITY

**Current**: Channel state (CONNECTING → OPEN → BUSY → CLOSED) transitions seem driven by PTY output, not explicit API calls.

**Problem**: This is magic—hard to reason about, test, or predict.

```python
# Which of these transitions the state?
channel.send(input, parser)  # Does this change state to BUSY?
# Or does PTY reading output change state?
# When does BUSY → OPEN? After parse completes? After first output? Last output?
```

**Better Approach**: Make state transitions explicit via events or state machine:

```python
class Channel:
    @property
    def state(self) -> ChannelState: ...

    async def send(self, input: str, parser: Parser) -> ParsedResponse:
        """Transitions: OPEN → BUSY → OPEN (or OPEN → CLOSED on error)"""
        ...
```

---

### 9. Backend Selection is Manual ⚠️ LOW PRIORITY

**Current**: Users choose between PTYBackend and WezTermBackend explicitly.

**Questions**:
- Why not auto-detect?
- WezTerm is one specific tool—what about tmux, zellij, screen?
- Is PTY abstraction complete enough to support those?

**Low Priority** because this works, but feels like premature abstraction (only 2 backends) or incomplete abstraction (many terminal multiplexers exist).

---

### 10. Pattern Domain Feels Ad-Hoc ⚠️ LOW PRIORITY

**Current**: Dev-Coach and Debate patterns are hardcoded implementations.

**Questions**:
- How do users extend with custom patterns?
- Can patterns be composed (Dev-Coach + Debate together)?
- How are pattern parameters configured?

**Could Become Important**: If patterns are a key feature, there should be a principled framework for defining them (not just "hardcode the pattern in a Python class").

---

### 11. Gateway Duplicates Core Concepts ⚠️ LOW PRIORITY

**Observation**: Both Core and Gateway handle LLM interaction:
- Core: CLI-based via channels
- Gateway: HTTP API proxying

**Questions**:
- Are these truly separate concerns or could they be unified?
- Is separation intentional (different deployment models)?
- Could there be a shared abstraction?

**Probably intentional** (separate paths for different use cases), but worth revisiting if they grow more similar.

---

## Strategic Questions

These aren't problems, but design decisions worth revisiting:

### 1. Is Core the Right Abstraction Level?

Core is low-level and mechanical:
```python
session.send("channel_name", "input", ClaudeParser)
dag.add_task(task1)
dag.add_task(task2)
dag.chain(task1.id, task2.id)
dag.run()
```

Should there be a higher-level domain (Workflows? Automations?) that's still pure but less boilerplate?

```python
# Higher-level example (doesn't exist yet)
workflow = Workflow("my_workflow")
workflow.step("dev_task", ...)
workflow.step("review_task", ..., depends_on="dev_task")
workflow.run()
```

Or is the current low-level approach intentional for maximum flexibility?

### 2. Should Parsing Be Pluggable Per-CLI?

Current: Per-command unsafe approach

Alternative: Per-channel safe approach (discussed above)

This affects API design significantly. Worth deciding explicitly.

### 3. When Should DAG Validation Fail?

Current behavior unclear. Should:
- `add_task()` validate immediately?
- `validate()` be required before `run()`?
- `run()` fail on invalid DAG?

Fast-fail (immediate) vs lazy-fail (at validation/run time)?

### 4. What's the Failure Model?

Transient network failures, crashed processes, malformed output, long-running timeouts—how should these be handled?

Currently seems reactive (failure happens → then figure it out). Could be proactive (design for failure).

---

## Prioritized Recommendations

### Tier 1: Production-Critical (Do First)

1. **Fix Parser Safety**
   - Make parsers optionally attachable to channels
   - Support per-command override
   - Reduces silent bugs significantly

2. **Formalize Error Handling**
   - Document failure modes for: channels, parsers, DAG tasks, processes
   - Add explicit error handling parameters to public APIs
   - Ensures predictable behavior under stress

3. **Document Concurrency Model**
   - Specify thread-safety guarantees
   - Document what operations are atomic
   - Prevents race condition bugs

### Tier 2: Important for Scale (Do Before Production)

4. **Abstract Session Storage**
   - Create `SessionRepository` protocol
   - Enables testing, alternative backends
   - Keeps infrastructure code out of domain

5. **Add Execution History**
   - Simple event log or execution results cache
   - Enables debugging, auditing, replay
   - Critical for reliable automation

6. **Clarify Session Persistence Model**
   - Document whether sessions are ephemeral or persistent
   - Either fully persist or cleanly ephemeral
   - Resolve the half-baked feeling

### Tier 3: Nice-to-Have (Do if Time Allows)

7. **Make State Transitions Explicit**
   - Document channel state machine
   - Consider emitting state change events
   - Improves testability and predictability

8. **Define Event Ordering Guarantees**
   - Specify per-channel and cross-channel ordering
   - Update event protocol documentation
   - Prevents client-side ordering bugs

9. **Higher-Level Abstractions**
   - Consider Workflow/Automation layer above Core
   - Reduces boilerplate for common patterns
   - Makes API more user-friendly

---

## What Works Well (Keep As-Is)

- Separation of concerns (Core is pure)
- DDD modeling (Entities, Aggregates, Value Objects)
- Event-driven server layer (without coupling Core)
- Channel/Parser abstraction
- Independent bounded contexts
- Async-first implementation

These architectural decisions are solid. Don't change them.

---

## Conclusion

Nerve has a strong architectural foundation. The DDD modeling is clean, the separation of concerns is excellent, and the core abstraction is sound. The concerns identified here aren't design failures—they're incompleteness that will become painful as the system scales.

**Priority should be**:
1. Parser safety (prevents silent bugs)
2. Error handling clarity (ensures reliability)
3. Storage abstraction (enables testing)

The rest can be addressed iteratively as the system grows and use cases become clearer.
