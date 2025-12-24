# Agent Capabilities PRD

## Product Requirements Document

**Document Version:** 1.0
**Status:** Draft
**Last Updated:** 2025-12-23

**Prerequisite:** [NODE_REFACTORING.md](./NODE_REFACTORING.md) Phase 1 must be complete before implementing this PRD.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Goals & Non-Goals](#2-goals--non-goals)
3. [Error Handling Requirements](#3-error-handling-requirements)
4. [Budget Requirements](#4-budget-requirements)
5. [Cancellation Requirements](#5-cancellation-requirements)
6. [Observability Requirements](#6-observability-requirements)
7. [Parallelism Requirements (P1)](#7-parallelism-requirements-p1) - Future work
8. [Implementation Phases](#8-implementation-phases)
9. [Testing Strategy](#9-testing-strategy)
10. [Design Decisions](#10-design-decisions)

---

## 1. Executive Summary

### Background

With the Node/Graph refactoring complete (see NODE_REFACTORING.md), the system has a unified abstraction for work units. This PRD adds P0 agent capabilities to enable safe, observable, and controllable graph execution.

### Proposal

Add four P0 capabilities to Graph execution:
1. **Error Handling**: Retry, skip, and fallback policies per step
2. **Budgets**: Token, time, step, and cost limits
3. **Cancellation**: Cooperative cancellation with tokens
4. **Observability**: Execution tracing for debugging and monitoring

### Benefits

1. **Safety**: Budgets prevent runaway executions
2. **Resilience**: Error policies handle transient failures
3. **Control**: Cancellation stops long-running graphs
4. **Debugging**: Traces show what happened during execution

### Scope

This PRD covers (P0):
- Error handling with retry, skip, and fallback policies
- Budget enforcement for tokens, time, steps, API calls, and cost
- Cooperative cancellation via CancellationToken
- Execution tracing with StepTrace and ExecutionTrace

This PRD does **not** cover:
- Parallel step execution (P1) - see [Section 7](#7-parallelism-requirements-p1) for future spec
- Long-term memory (P1)
- Human-in-the-loop (P1)
- Checkpointing (P2)
- Security sandboxing (P2)

---

## 2. Goals & Non-Goals

### 2.1 Goals (P0)

| ID | Goal | Rationale |
|----|------|-----------|
| G1 | Add error handling policies | Enable resilient graph execution |
| G2 | Enforce resource budgets | Prevent runaway costs and time |
| G3 | Support cooperative cancellation | Allow stopping long-running graphs |
| G4 | Provide execution tracing | Enable debugging and monitoring |
| G5 | Maintain backward compatibility | Existing graphs work without changes |

### 2.2 Non-Goals (this PRD)

| ID | Non-Goal | Rationale |
|----|----------|-----------|
| NG1 | Implement parallel execution | P1 priority, spec in Section 7 for future |
| NG2 | Implement long-term memory | P1 priority, separate PRD |
| NG3 | Implement human-in-the-loop | P1 priority, separate PRD |
| NG4 | Implement checkpointing | P2 priority, separate PRD |
| NG5 | Automatic retry detection | Complex, manual policy is sufficient |
| NG6 | Distributed tracing | Out of scope, single-process for now |

### 2.3 Success Criteria

| Criteria | Measurement |
|----------|-------------|
| Error policies work | Retry, skip, fallback tests pass |
| Budgets enforced | Budget exceeded tests pass |
| Cancellation works | Mid-execution cancellation tests pass |
| Traces generated | Trace contains all step info |

### 2.4 Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Performance overhead from tracing | Medium | Low | Opt-in tracing (D12) |
| Budget calculation drift | Low | Medium | Use monotonic clock; clear accounting |
| Cancellation deadlock | Low | High | Timeout on cancellation; clear check points |

---

## 3. Error Handling Requirements

### REQ-E1: Error Policy

```python
@dataclass
class ErrorPolicy:
    on_error: Literal["fail", "retry", "skip", "fallback"] = "fail"
    retry_count: int = 0
    retry_delay_ms: int = 1000
    retry_backoff: float = 2.0
    timeout_ms: int | None = None
    fallback_value: Any = None
    fallback_node: Node | None = None
```

### REQ-E2: Step Execution with Policy

```python
async def _execute_with_policy(
    self,
    step: Step,
    node: Node,
    context: ExecutionContext
) -> Any:
    policy = step.error_policy or ErrorPolicy()

    for attempt in range(policy.retry_count + 1):
        try:
            if policy.timeout_ms:
                return await asyncio.wait_for(
                    node.execute(context),
                    timeout=policy.timeout_ms / 1000
                )
            else:
                return await node.execute(context)

        except asyncio.TimeoutError:
            if attempt < policy.retry_count:
                delay = policy.retry_delay_ms / 1000 * (policy.retry_backoff ** attempt)
                await asyncio.sleep(delay)
                continue
            # Handle timeout based on policy (same as regular exception)
            if policy.on_error == "fail":
                raise
            elif policy.on_error == "skip":
                return policy.fallback_value
            elif policy.on_error == "fallback" and policy.fallback_node:
                return await policy.fallback_node.execute(context)
            else:
                raise

        except Exception as e:
            if attempt < policy.retry_count:
                delay = policy.retry_delay_ms / 1000 * (policy.retry_backoff ** attempt)
                await asyncio.sleep(delay)
                continue

            if policy.on_error == "fail":
                raise
            elif policy.on_error == "skip":
                return policy.fallback_value
            elif policy.on_error == "fallback" and policy.fallback_node:
                return await policy.fallback_node.execute(context)
            else:
                raise
```

---

## 4. Budget Requirements

### REQ-B1: Budget Definition

```python
@dataclass
class Budget:
    max_tokens: int | None = None
    max_time_seconds: float | None = None
    max_steps: int | None = None
    max_api_calls: int | None = None
    max_cost_dollars: float | None = None
```

### REQ-B2: Resource Usage Tracking

```python
import time

@dataclass
class ResourceUsage:
    tokens_used: int = 0
    steps_executed: int = 0
    api_calls: int = 0
    cost_dollars: float = 0.0
    _start_monotonic: float = field(default_factory=time.monotonic)
    start_time: datetime = field(default_factory=datetime.now)  # For display only

    @property
    def time_elapsed_seconds(self) -> float:
        """Elapsed time using monotonic clock (immune to system clock changes)."""
        return time.monotonic() - self._start_monotonic

    def exceeds(self, budget: Budget) -> tuple[bool, str | None]:
        """Check if usage exceeds budget. Returns (exceeded, reason)."""
        if budget.max_tokens and self.tokens_used >= budget.max_tokens:
            return True, f"Token limit exceeded: {self.tokens_used}/{budget.max_tokens}"
        if budget.max_steps and self.steps_executed >= budget.max_steps:
            return True, f"Step limit exceeded: {self.steps_executed}/{budget.max_steps}"
        elapsed = self.time_elapsed_seconds  # Uses monotonic clock
        if budget.max_time_seconds and elapsed >= budget.max_time_seconds:
            return True, f"Time limit exceeded: {elapsed:.1f}s/{budget.max_time_seconds}s"
        if budget.max_api_calls and self.api_calls >= budget.max_api_calls:
            return True, f"API call limit exceeded: {self.api_calls}/{budget.max_api_calls}"
        if budget.max_cost_dollars and self.cost_dollars >= budget.max_cost_dollars:
            return True, f"Cost limit exceeded: ${self.cost_dollars:.2f}/${budget.max_cost_dollars:.2f}"
        return False, None
```

**Note:** Uses `time.monotonic()` for elapsed time calculation to avoid issues with system clock adjustments (NTP sync, DST changes, etc.). The `start_time` datetime is kept for display/logging purposes only.

### REQ-B3: BudgetExceededError

```python
class BudgetExceededError(Exception):
    def __init__(self, usage: ResourceUsage, budget: Budget, reason: str):
        self.usage = usage
        self.budget = budget
        self.reason = reason
        super().__init__(reason)
```

### REQ-B4: ExecutionContext.check_budget()

ExecutionContext provides a method to check budget limits:

```python
@dataclass
class ExecutionContext:
    session: Session
    input: Any = None
    upstream: dict[str, Any] = field(default_factory=dict)
    budget: Budget | None = None
    usage: ResourceUsage = field(default_factory=ResourceUsage)
    cancellation: CancellationToken | None = None
    trace: ExecutionTrace | None = None

    def check_budget(self) -> None:
        """Raise BudgetExceededError if budget is exceeded.

        Should be called at checkpoints during execution (before each step,
        after each step, etc.) to enforce resource limits.

        Raises:
            BudgetExceededError: If any budget limit is exceeded.
        """
        if self.budget and self.usage:
            exceeded, reason = self.usage.exceeds(self.budget)
            if exceeded:
                raise BudgetExceededError(self.usage, self.budget, reason)

    def check_cancelled(self) -> None:
        """Raise CancelledError if cancellation was requested.

        Raises:
            CancelledError: If cancellation was requested.
        """
        if self.cancellation:
            self.cancellation.check()

    def with_input(self, input: Any) -> "ExecutionContext":
        """Create new context with different input."""
        return replace(self, input=input)

    def with_upstream(self, upstream: dict[str, Any]) -> "ExecutionContext":
        """Create new context with updated upstream results."""
        return replace(self, upstream={**self.upstream, **upstream})
```

### REQ-B5: Nested Graph Budget Propagation

When a graph contains subgraphs, budgets are **shared** by default (single resource pool):

```python
# Parent graph passes its context (with budget/usage) to subgraph
async def execute(self, context: ExecutionContext) -> dict[str, Any]:
    for step_id in self.execution_order():
        step = self._steps[step_id]
        node = self._resolve_node(step, context.session)

        # Subgraph gets SAME context - shares budget/usage
        result = await node.execute(context)

        # Usage is automatically tracked across all nested levels
        # because they share the same ResourceUsage instance
```

**Rationale:** Shared budget ensures the total execution respects limits regardless of nesting depth.

**Alternative: Sub-budgets (opt-in)**

For isolation, create a sub-budget for a step:

```python
@dataclass
class Step:
    # ... existing fields ...
    sub_budget: Budget | None = None  # Optional budget just for this step


# In Graph.execute():
if step.sub_budget:
    # Create isolated context for this step
    step_context = context.with_sub_budget(step.sub_budget)
else:
    step_context = context
```

```python
# ExecutionContext helper
def with_sub_budget(self, sub_budget: Budget) -> "ExecutionContext":
    """Create child context with isolated budget tracking.

    The child's usage counts toward the parent's budget AND the sub-budget.
    If either is exceeded, BudgetExceededError is raised.
    """
    return ExecutionContext(
        session=self.session,
        input=self.input,
        upstream=self.upstream,
        budget=sub_budget,
        usage=ResourceUsage(),  # Fresh usage for sub-budget
        parent_usage=self.usage,  # Still counts toward parent
        cancellation=self.cancellation,
        trace=self.trace,
    )
```

**Use case:** Limit a specific subgraph to 1000 tokens while the overall graph has 10000 token budget.

---

## 5. Cancellation Requirements

### REQ-C1: CancellationToken

```python
class CancellationToken:
    def __init__(self):
        self._cancelled = False
        self._event = asyncio.Event()

    def cancel(self) -> None:
        """Request cancellation."""
        self._cancelled = True
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        """Raise CancelledError if cancelled."""
        if self._cancelled:
            raise CancelledError()

    async def wait(self) -> None:
        """Wait until cancelled."""
        await self._event.wait()
```

### REQ-C2: CancelledError

```python
class CancelledError(Exception):
    """Raised when execution is cancelled."""
    pass
```

### REQ-C3: Cancellation Check Points

Graph execution must check for cancellation:
- Before each step execution
- After each step completion

---

## 6. Observability Requirements

### REQ-O1: StepTrace

```python
@dataclass
class StepTrace:
    step_id: str
    node_id: str
    node_type: str
    input: Any
    output: Any
    error: str | None
    start_time: datetime
    end_time: datetime
    duration_ms: float
    tokens_used: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
```

### REQ-O2: ExecutionTrace

```python
@dataclass
class ExecutionTrace:
    graph_id: str
    start_time: datetime
    end_time: datetime | None = None
    status: Literal["running", "completed", "failed", "cancelled"] = "running"
    steps: list[StepTrace] = field(default_factory=list)
    total_tokens: int = 0
    total_cost: float = 0.0
    error: str | None = None

    def add_step(self, step: StepTrace) -> None:
        self.steps.append(step)
        self.total_tokens += step.tokens_used

    def explain(self) -> str:
        """Human-readable execution summary."""
        lines = [f"Graph: {self.graph_id}", f"Status: {self.status}"]
        for step in self.steps:
            lines.append(f"  {step.step_id} ({step.node_type}): {step.duration_ms:.0f}ms")
            if step.error:
                lines.append(f"    Error: {step.error}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """JSON-serializable representation."""
        ...
```

### REQ-O3: Trace-History Correlation

ExecutionTrace and node history are **independent but correlatable**:

| To find... | Use... |
|------------|--------|
| History file for a step | `StepTrace.node_id` → `.nerve/history/[server]/[node_id].jsonl` |
| History entries for a step | Filter by `StepTrace.start_time` to `StepTrace.end_time` |

No automatic cross-referencing. Correlation is manual via node_id + timestamp.

---

## 7. Parallelism Requirements (P1)

> **Note:** This section documents P1 requirements for future implementation. These are NOT part of the current P0 scope.

### REQ-P1: Parallel Step Execution

Graph supports parallel execution of independent steps:

```python
class Graph(Node):
    def __init__(self, id: str, max_parallel: int = 1):
        self.id = id
        self.max_parallel = max_parallel
```

### REQ-P2: Parallel Execution Logic

```python
async def execute(self, context: ExecutionContext) -> dict[str, Any]:
    results = {}
    executed = set()
    semaphore = asyncio.Semaphore(self.max_parallel)

    while True:
        # Find steps whose dependencies are satisfied
        ready = [
            step_id for step_id, step in self._steps.items()
            if step_id not in executed
            and all(dep in executed for dep in step.depends_on)
        ]

        if not ready:
            break

        # Execute ready steps in parallel
        async def run_step(step_id: str):
            async with semaphore:
                context.check_cancelled()
                context.check_budget()
                step = self._steps[step_id]
                node = self._resolve_node(step, context.session)
                step_context = context.with_input(step.input).with_upstream(results)
                result = await self._execute_with_policy(step, node, step_context)
                results[step_id] = result
                executed.add(step_id)

        await asyncio.gather(*[run_step(sid) for sid in ready])

    return results
```

### REQ-P3: Persistent Node Mutual Exclusion

Persistent nodes should use locks for concurrent access:

```python
class PersistentNode(Node):
    def __init__(self, id: str):
        self.id = id
        self._lock = asyncio.Lock()

    async def execute(self, context: ExecutionContext) -> Any:
        async with self._lock:
            return await self._execute_impl(context)
```

### REQ-P4: Deadlock Prevention

**Problem:** If multiple graphs share nodes and acquire locks in different orders, deadlocks can occur.

**Prevention Strategy:** Graph-level lock ordering and timeout.

```python
class Graph(Node):
    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        # Strategy 1: Acquire all persistent node locks upfront in sorted order
        persistent_nodes = sorted(
            [n for n in self._collect_nodes() if n.persistent],
            key=lambda n: n.id  # Consistent ordering prevents deadlock
        )

        async def acquire_with_timeout(node: PersistentNode) -> None:
            try:
                await asyncio.wait_for(node._lock.acquire(), timeout=30.0)
            except asyncio.TimeoutError:
                raise DeadlockError(f"Timeout acquiring lock for node {node.id}")

        # Acquire locks in order
        for node in persistent_nodes:
            await acquire_with_timeout(node)

        try:
            return await self._execute_steps(context)
        finally:
            # Release in reverse order
            for node in reversed(persistent_nodes):
                node._lock.release()


class DeadlockError(Exception):
    """Raised when lock acquisition times out (potential deadlock)."""
    pass
```

**Alternative Strategy (simpler):** Don't allow same persistent node in parallel steps within same graph.

```python
def validate(self) -> list[str]:
    errors = []
    # ... existing validation ...

    # Check for parallel access to same persistent node
    for step_a, step_b in self._parallel_step_pairs():
        node_a = self._resolve_node(step_a)
        node_b = self._resolve_node(step_b)
        if node_a is node_b and node_a.persistent:
            errors.append(
                f"Steps '{step_a.id}' and '{step_b.id}' both use persistent "
                f"node '{node_a.id}' and can run in parallel. This may cause "
                "race conditions. Add a dependency between them."
            )
    return errors
```

**Recommendation:** Use the validation approach (simpler, catches issues at graph construction time).

---

## 8. Implementation Phases

### Phase 1: Error Handling, Budgets & Cancellation (P0)

**Goal:** Add P0 agent capabilities for safe execution.

**Deliverables:**

1. **Error Policy** (`core/nodes/policies.py`)
   - ErrorPolicy dataclass
   - Retry logic with backoff
   - Fallback execution

2. **Budgets** (`core/nodes/budget.py`)
   - Budget dataclass
   - ResourceUsage tracking
   - BudgetExceededError

3. **Cancellation** (`core/nodes/cancellation.py`)
   - CancellationToken
   - CancelledError
   - Cancellation check points in Graph

4. **Enhanced Graph Execution**
   - Integrate error policies
   - Integrate budget checking
   - Integrate cancellation

**Tests:**
- Error policy tests (retry, skip, fallback)
- Budget limit tests
- Cancellation tests

### Phase 2: Observability (P0)

**Goal:** Add execution tracing.

**Deliverables:**

1. **Tracing** (`core/nodes/trace.py`)
   - StepTrace dataclass
   - ExecutionTrace dataclass
   - Trace recording in Graph execution

**Tests:**
- Trace generation tests
- explain() output tests

### Future: Parallelism (P1)

**Goal:** Add parallel step execution.

**Deliverables:** See Section 7 for requirements.

**Tests:**
- Parallel execution tests
- Lock contention tests

---

## 9. Testing Strategy

### 9.1 Unit Tests

| Component | Test Focus |
|-----------|------------|
| ErrorPolicy | Retry logic, backoff calculation |
| Budget | Limit checking, resource accounting |
| CancellationToken | Cancel/check semantics |
| StepTrace | Field population |
| ExecutionTrace | Step aggregation, explain() |

### 9.2 Integration Tests (P0)

| Scenario | Verification |
|----------|--------------|
| Retry succeeds on 2nd attempt | Step executes twice, returns success |
| Skip on error | Graph continues, step has fallback_value |
| Fallback node | Fallback executes when primary fails |
| Budget exceeded mid-graph | BudgetExceededError raised, partial results |
| Cancel mid-graph | CancelledError raised, partial results |
| Trace captures all steps | explain() shows full history |

### 9.3 Performance Tests (P0)

| Test | Criteria |
|------|----------|
| Tracing overhead | <5% slowdown vs non-traced |

**Baseline Definition:**

Run a 100-step sequential graph using FunctionNodes with minimal computation (e.g., `lambda ctx: ctx.input + 1`). No I/O, no tracing. Measure average execution time over 10 runs.

**Test Protocol:**

```python
# Baseline: No tracing
for _ in range(10):
    results = await graph.execute(ExecutionContext(session=session))
    # Record execution time

# With tracing
for _ in range(10):
    trace = ExecutionTrace(graph_id="perf-test", start_time=datetime.now())
    results = await graph.execute(ExecutionContext(session=session, trace=trace))
    # Record execution time

# Calculate overhead percentage
overhead = (traced_avg - baseline_avg) / baseline_avg * 100
assert overhead < 5.0, f"Tracing overhead {overhead:.1f}% exceeds 5% limit"
```

### 9.4 P1 Tests (Future - Parallelism)

| Test | Criteria |
|------|----------|
| Parallel independent steps | Speedup observed |
| Parallel with shared node | Lock prevents race |
| Parallel speedup | 2 independent steps in ~1x time |
| Lock contention | No deadlocks under load |

---

## 10. Design Decisions

### Decision D12: Trace Storage

**Decision:** Opt-in via context parameter. Tracing is enabled by passing an ExecutionTrace to context.

```python
# Without tracing (default)
results = await graph.execute(ExecutionContext(session=session))

# With tracing
trace = ExecutionTrace(graph_id="main", start_time=datetime.now())
results = await graph.execute(ExecutionContext(session=session, trace=trace))
print(trace.explain())  # See what happened
```

**Rationale:** Tracing has memory and CPU overhead. Opt-in lets users enable it when debugging or monitoring, without paying the cost in production fast paths.

---

### Decision D13: History vs Trace

**Decision:** Keep both history (low-level audit log) and trace (high-level execution log).

| Log Type | Purpose | Granularity | Persistence |
|----------|---------|-------------|-------------|
| **History** | Audit trail of raw operations | Per-operation (write, read, send) | JSONL file per node |
| **Trace** | Execution flow visualization | Per-step in graph | In-memory, optional persist |

```python
# History (already exists, unchanged)
# Logs: send, send_stream, write, read, run, interrupt, close
# File: .nerve/history/{server_name}/{channel_id}.jsonl

# Trace (new)
# Logs: step start, step end, step error, graph complete
# Memory: ExecutionTrace object, can be serialized to JSON
```

**Rationale:** They serve different purposes. History is for debugging "what did the terminal receive?". Trace is for understanding "how did the workflow execute?". Both are valuable.

---

**End of PRD**
