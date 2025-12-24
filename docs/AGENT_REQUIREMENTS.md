# Agent Requirements: Gaps and Extensions

This document assesses whether the proposed Node/Graph/Session architecture is powerful enough for building truly autonomous agents, identifies gaps, and proposes solutions.

---

## Part 1: What the Architecture Handles Well

The core architecture provides a strong foundation for agent-like behavior:

| Capability | Support | Implementation |
|------------|---------|----------------|
| **Decision-making** | Strong | AgentNode with LLM deciding next action |
| **Tool use** | Strong | Different node types (Bash, HTTP, DB) in Session |
| **Short-term memory** | Strong | History in agent state, upstream results in context |
| **Planning** | Strong | LLM-driven graph construction, nested graphs |
| **Multi-step reasoning** | Strong | Graphs with dependencies, composable |
| **Goal persistence** | Strong | Agent loop continues until "done" |
| **Observation/feedback** | Strong | Results flow through context, inform next action |
| **Dynamic adaptation** | Strong | Self-modifying graphs, streaming execution |
| **Hierarchical decomposition** | Strong | Graphs containing graphs containing graphs |
| **Multi-agent collaboration** | Possible | Multiple persistent nodes in same graph |

### The Core Agent Loop Works

```python
# ReAct-style agent is fully expressible:
while not done:
    observation = get_current_state()
    thought = await llm.think(observation, history)
    action = await llm.decide(thought)
    result = await execute_action(action)  # Graph execution
    history.append((thought, action, result))
```

---

## Part 2: What's Missing for Production Agents

### Gap 1: Long-Term Memory

**Problem:** Agents forget everything when session closes. No learning across tasks.

**Current state:**
```python
# Memory lives in Python objects, dies with process
agent_state = AgentState(history=[])
```

**What's needed:**
```python
class MemoryStore(Protocol):
    """Persistent memory abstraction."""

    async def store(self, key: str, value: Any, metadata: dict = None) -> None:
        """Store a memory."""
        ...

    async def retrieve(self, query: str, limit: int = 10) -> list[Memory]:
        """Retrieve relevant memories (semantic search)."""
        ...

    async def list_recent(self, limit: int = 10) -> list[Memory]:
        """List recent memories (temporal)."""
        ...

@dataclass
class Memory:
    key: str
    value: Any
    timestamp: datetime
    metadata: dict
    embedding: list[float] | None  # For semantic search

# Memory types:
class EpisodicMemory(MemoryStore):
    """What happened (past experiences, task outcomes)."""
    pass

class SemanticMemory(MemoryStore):
    """What I know (facts, learned information)."""
    pass

class WorkingMemory:
    """Current task context (short-term, in-memory)."""
    pass
```

**Integration with architecture:**
```python
class Session:
    def __init__(self, memory: MemoryStore = None):
        self._registry = {}
        self.memory = memory or InMemoryStore()  # Default: no persistence

# Usage in agent:
class AgentNode(Node):
    async def execute(self, context) -> Any:
        # Retrieve relevant memories
        relevant = await context.session.memory.retrieve(context.input)

        # Use in decision making
        decision = await self.decide(context.input, relevant)

        # Store new memory
        await context.session.memory.store(
            key=f"task_{context.task_id}",
            value={"input": context.input, "result": result},
            metadata={"type": "task_completion"}
        )
```

**Implementation options:**
- `InMemoryStore` — Default, no persistence
- `SQLiteMemoryStore` — Local file persistence
- `VectorMemoryStore` — With embeddings for semantic search (using FAISS, Chroma, etc.)
- `RedisMemoryStore` — Distributed, shared across processes

---

### Gap 2: Error Handling & Recovery

**Problem:** One failure crashes the whole workflow. No retry, no fallback, no graceful degradation.

**Current state:**
```python
# If this fails, everything fails
result = await node.execute(context)
```

**What's needed:**
```python
@dataclass
class ErrorPolicy:
    """How to handle errors for a step."""
    on_error: Literal["fail", "retry", "skip", "fallback"] = "fail"
    retry_count: int = 0
    retry_delay_ms: int = 1000
    retry_backoff: float = 2.0  # Exponential backoff multiplier
    fallback_node: Node | None = None
    fallback_value: Any = None
    timeout_ms: int | None = None

class Graph(Node):
    def add_step(
        self,
        node: Node,
        step_id: str,
        input: Any = None,
        depends_on: list[str] = None,
        error_policy: ErrorPolicy = None  # NEW
    ) -> None:
        ...

# Usage:
graph.add_step(
    risky_api_node,
    step_id="fetch_data",
    error_policy=ErrorPolicy(
        on_error="retry",
        retry_count=3,
        retry_delay_ms=1000,
        timeout_ms=30000
    )
)

graph.add_step(
    primary_llm,
    step_id="analyze",
    error_policy=ErrorPolicy(
        on_error="fallback",
        fallback_node=backup_llm,  # Try different LLM if primary fails
        timeout_ms=60000
    )
)

graph.add_step(
    optional_enrichment,
    step_id="enrich",
    error_policy=ErrorPolicy(
        on_error="skip",  # Continue without this step if it fails
        fallback_value={}  # Use empty dict as result
    )
)
```

**Graph execution with error handling:**
```python
async def execute_step(self, step: Step, context: ExecutionContext) -> Any:
    policy = step.error_policy or ErrorPolicy()

    for attempt in range(policy.retry_count + 1):
        try:
            if policy.timeout_ms:
                result = await asyncio.wait_for(
                    step.node.execute(context),
                    timeout=policy.timeout_ms / 1000
                )
            else:
                result = await step.node.execute(context)
            return result

        except Exception as e:
            if attempt < policy.retry_count:
                await asyncio.sleep(policy.retry_delay_ms / 1000 * (policy.retry_backoff ** attempt))
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

### Gap 3: Human-in-the-Loop

**Problem:** Agents either succeed or fail completely. No way to ask humans for help.

**What's needed:**
```python
class HumanInputNode(Node):
    """Pauses execution and requests human input."""

    def __init__(self, id: str, prompt_template: str = None):
        self.id = id
        self.prompt_template = prompt_template

    async def execute(self, context: ExecutionContext) -> Any:
        prompt = self.prompt_template.format(**context.upstream) if self.prompt_template else context.input
        return await context.request_human_input(prompt)

class ExecutionContext:
    human_input_handler: Callable[[str], Awaitable[str]] = None

    async def request_human_input(self, prompt: str) -> str:
        if self.human_input_handler is None:
            raise RuntimeError("No human input handler configured")
        return await self.human_input_handler(prompt)

# Usage:
async def cli_human_handler(prompt: str) -> str:
    print(f"\n🤖 Agent needs help: {prompt}")
    return input("Your response: ")

context = ExecutionContext(
    session=session,
    human_input_handler=cli_human_handler
)

# In graph:
graph.add_step(
    HumanInputNode(id="confirm", prompt_template="Should I proceed with: {previous_step}?"),
    step_id="human_confirm",
    depends_on=["previous_step"]
)
```

**Automatic escalation in agents:**
```python
class AgentNode(Node):
    async def execute(self, context) -> Any:
        for i in range(self.max_iterations):
            decision = await self.decide(state)

            # Low confidence? Ask human
            if decision.confidence < 0.3:
                human_guidance = await context.request_human_input(
                    f"I'm uncertain. My options are:\n"
                    f"1. {decision.option_a}\n"
                    f"2. {decision.option_b}\n"
                    f"What should I do?"
                )
                decision = self.parse_human_guidance(human_guidance)

            result = await self.act(decision)
            state = state.update(result)
```

---

### Gap 4: Resource Limits / Budgets

**Problem:** Agents can run forever, burn API credits, or get stuck in infinite loops.

**What's needed:**
```python
@dataclass
class Budget:
    """Resource limits for execution."""
    max_tokens: int | None = None
    max_time_seconds: float | None = None
    max_steps: int | None = None
    max_api_calls: int | None = None
    max_cost_dollars: float | None = None

@dataclass
class ResourceUsage:
    """Track resource consumption."""
    tokens_used: int = 0
    time_elapsed_seconds: float = 0
    steps_executed: int = 0
    api_calls: int = 0
    cost_dollars: float = 0

    def exceeds(self, budget: Budget) -> bool:
        if budget.max_tokens and self.tokens_used >= budget.max_tokens:
            return True
        if budget.max_time_seconds and self.time_elapsed_seconds >= budget.max_time_seconds:
            return True
        if budget.max_steps and self.steps_executed >= budget.max_steps:
            return True
        if budget.max_api_calls and self.api_calls >= budget.max_api_calls:
            return True
        if budget.max_cost_dollars and self.cost_dollars >= budget.max_cost_dollars:
            return True
        return False

class ExecutionContext:
    budget: Budget | None = None
    usage: ResourceUsage = field(default_factory=ResourceUsage)

    def check_budget(self) -> None:
        if self.budget and self.usage.exceeds(self.budget):
            raise BudgetExceededError(self.usage, self.budget)

    def record_tokens(self, count: int) -> None:
        self.usage.tokens_used += count
        self.check_budget()

    def record_api_call(self, cost: float = 0) -> None:
        self.usage.api_calls += 1
        self.usage.cost_dollars += cost
        self.check_budget()

# Usage:
result = await graph.execute(
    ExecutionContext(
        session=session,
        budget=Budget(
            max_tokens=100000,
            max_time_seconds=300,
            max_steps=50,
            max_cost_dollars=1.00
        )
    )
)

print(f"Used {context.usage.tokens_used} tokens, ${context.usage.cost_dollars:.2f}")
```

**Integration with nodes:**
```python
class ClaudeNode(Node):
    async def execute(self, context) -> Any:
        context.record_api_call()  # Track API call

        response = await self.client.send(context.input)

        context.record_tokens(response.usage.total_tokens)
        context.usage.cost_dollars += self.calculate_cost(response.usage)

        return response
```

---

### Gap 5: Observability / Debugging

**Problem:** Hard to understand what an agent did and why. Black box behavior.

**What's needed:**
```python
@dataclass
class StepTrace:
    """Record of a single step execution."""
    step_id: str
    node_id: str
    node_type: str
    input: Any
    output: Any
    error: str | None
    start_time: datetime
    end_time: datetime
    duration_ms: float
    tokens_used: int
    metadata: dict

@dataclass
class ExecutionTrace:
    """Complete trace of a graph execution."""
    graph_id: str
    start_time: datetime
    end_time: datetime | None
    status: Literal["running", "completed", "failed", "cancelled"]
    steps: list[StepTrace]
    total_tokens: int
    total_cost: float
    error: str | None

    def add_step(self, step: StepTrace) -> None:
        self.steps.append(step)
        self.total_tokens += step.tokens_used

    def visualize(self) -> str:
        """Return ASCII/Mermaid visualization of execution flow."""
        ...

    def to_json(self) -> str:
        """Serialize for storage/analysis."""
        ...

    def explain(self) -> str:
        """Human-readable explanation of what happened."""
        lines = []
        for step in self.steps:
            lines.append(f"Step {step.step_id} ({step.node_type}):")
            lines.append(f"  Input: {truncate(step.input, 100)}")
            lines.append(f"  Output: {truncate(step.output, 100)}")
            lines.append(f"  Duration: {step.duration_ms:.0f}ms")
        return "\n".join(lines)

class ExecutionContext:
    trace: ExecutionTrace | None = None

    def record_step(self, step_id: str, node: Node, input: Any, output: Any,
                    start: datetime, end: datetime, error: str = None) -> None:
        if self.trace:
            self.trace.add_step(StepTrace(
                step_id=step_id,
                node_id=node.id,
                node_type=type(node).__name__,
                input=input,
                output=output,
                error=error,
                start_time=start,
                end_time=end,
                duration_ms=(end - start).total_seconds() * 1000,
                tokens_used=getattr(output, 'tokens', 0),
                metadata={}
            ))

# Usage:
trace = ExecutionTrace(graph_id="main", start_time=datetime.now(), steps=[], ...)
result = await graph.execute(ExecutionContext(session=session, trace=trace))

print(trace.explain())
trace.visualize()  # Show execution graph
```

**Trace storage for analysis:**
```python
class TraceStore(Protocol):
    async def save(self, trace: ExecutionTrace) -> str:
        """Save trace, return trace ID."""
        ...

    async def load(self, trace_id: str) -> ExecutionTrace:
        """Load trace by ID."""
        ...

    async def query(self, filters: dict) -> list[ExecutionTrace]:
        """Query traces (by time, status, graph_id, etc.)."""
        ...
```

---

### Gap 6: Parallelism

**Problem:** Unclear whether independent nodes can execute in parallel. Potential performance loss or race conditions.

**What's needed:**
```python
class Graph(Node):
    def __init__(self, id: str, max_parallel: int = 1):
        self.id = id
        self.max_parallel = max_parallel  # Max concurrent step executions

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        results = {}
        executed = set()
        semaphore = asyncio.Semaphore(self.max_parallel)

        while True:
            # Find all steps whose dependencies are satisfied
            ready = [
                step for step in self._steps.values()
                if step.id not in executed
                and all(dep in executed for dep in step.depends_on)
            ]

            if not ready:
                break

            # Execute ready steps in parallel (up to max_parallel)
            async def run_step(step):
                async with semaphore:
                    result = await self.execute_step(step, context, results)
                    results[step.id] = result
                    executed.add(step.id)

            await asyncio.gather(*[run_step(step) for step in ready])

        return results

# Mutual exclusion for persistent nodes:
class PersistentNode(Node):
    def __init__(self, id: str):
        self.id = id
        self._lock = asyncio.Lock()

    async def execute(self, context) -> Any:
        async with self._lock:  # Only one execution at a time
            return await self._execute_impl(context)
```

**Usage:**
```python
# Allow up to 3 parallel step executions
graph = Graph(id="parallel_workflow", max_parallel=3)

graph.add_step(fetch_a, step_id="fetch_a")  # These three can run
graph.add_step(fetch_b, step_id="fetch_b")  # in parallel
graph.add_step(fetch_c, step_id="fetch_c")  # (no dependencies)

graph.add_step(
    combine_node,
    step_id="combine",
    depends_on=["fetch_a", "fetch_b", "fetch_c"]  # Waits for all
)
```

---

### Gap 7: Cancellation / Interruption

**Problem:** No way to stop a running agent gracefully.

**What's needed:**
```python
class CancellationToken:
    """Cooperative cancellation mechanism."""

    def __init__(self):
        self._cancelled = False
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._cancelled = True
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        """Raise if cancelled."""
        if self._cancelled:
            raise CancelledError()

    async def wait(self) -> None:
        """Wait until cancelled."""
        await self._event.wait()

class ExecutionContext:
    cancellation_token: CancellationToken | None = None

    def check_cancelled(self) -> None:
        if self.cancellation_token:
            self.cancellation_token.check()

class Graph(Node):
    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        results = {}

        for step_id in self._topological_order():
            context.check_cancelled()  # Check before each step

            step = self._steps[step_id]
            results[step_id] = await self.execute_step(step, context, results)

        return results

# Usage:
token = CancellationToken()
context = ExecutionContext(session=session, cancellation_token=token)

# Start execution in background
task = asyncio.create_task(graph.execute(context))

# Later, cancel it
token.cancel()

try:
    result = await task
except CancelledError:
    print("Execution was cancelled")
```

**Cleanup on cancellation:**
```python
class PersistentNode(Node):
    async def execute(self, context) -> Any:
        try:
            return await self._execute_impl(context)
        except CancelledError:
            await self.cleanup()  # Release resources
            raise
```

---

### Gap 8: Checkpointing / Resumption

**Problem:** Long-running agents can't survive restarts. No pause/resume.

**What's needed:**
```python
@dataclass
class Checkpoint:
    """Serializable execution state."""
    graph_id: str
    completed_steps: dict[str, Any]  # step_id -> result
    pending_steps: list[str]
    context_state: dict  # Serialized context
    timestamp: datetime

    def save(self, path: str) -> None:
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: str) -> "Checkpoint":
        with open(path) as f:
            return cls.from_dict(json.load(f))

class Graph(Node):
    async def execute_with_checkpointing(
        self,
        context: ExecutionContext,
        checkpoint_interval: int = 5,  # Checkpoint every N steps
        checkpoint_path: str = None
    ) -> dict[str, Any]:
        results = {}
        steps_since_checkpoint = 0

        for step_id in self._topological_order():
            results[step_id] = await self.execute_step(...)
            steps_since_checkpoint += 1

            if checkpoint_path and steps_since_checkpoint >= checkpoint_interval:
                checkpoint = Checkpoint(
                    graph_id=self.id,
                    completed_steps=results.copy(),
                    pending_steps=self._remaining_steps(results.keys()),
                    context_state=context.serialize(),
                    timestamp=datetime.now()
                )
                checkpoint.save(checkpoint_path)
                steps_since_checkpoint = 0

        return results

    async def resume(
        self,
        checkpoint: Checkpoint,
        context: ExecutionContext
    ) -> dict[str, Any]:
        """Resume execution from checkpoint."""
        results = checkpoint.completed_steps.copy()

        for step_id in checkpoint.pending_steps:
            results[step_id] = await self.execute_step(...)

        return results

# Usage:
try:
    result = await graph.execute_with_checkpointing(
        context,
        checkpoint_interval=10,
        checkpoint_path="agent_checkpoint.json"
    )
except Exception:
    print("Failed! Can resume from checkpoint.")

# Later:
checkpoint = Checkpoint.load("agent_checkpoint.json")
result = await graph.resume(checkpoint, context)
```

---

### Gap 9: Security / Sandboxing

**Problem:** Agents with BashNode can do anything. Dangerous for untrusted input.

**What's needed:**
```python
@dataclass
class SecurityPolicy:
    """Restrictions on what agents can do."""

    # Node restrictions
    allowed_node_types: set[str] | None = None  # None = all allowed
    blocked_node_types: set[str] | None = None

    # File system
    file_access: Literal["none", "read_only", "read_write"] = "read_only"
    allowed_paths: list[str] | None = None  # None = all paths

    # Network
    network_access: Literal["none", "restricted", "full"] = "restricted"
    allowed_hosts: list[str] | None = None

    # Execution
    max_subprocess_time_seconds: float = 30
    allow_shell: bool = False

    # Resource limits
    max_memory_mb: int = 512
    max_output_size_bytes: int = 1_000_000

class ExecutionContext:
    security_policy: SecurityPolicy | None = None

    def check_node_allowed(self, node: Node) -> None:
        if not self.security_policy:
            return

        node_type = type(node).__name__
        policy = self.security_policy

        if policy.blocked_node_types and node_type in policy.blocked_node_types:
            raise SecurityError(f"Node type {node_type} is blocked")

        if policy.allowed_node_types and node_type not in policy.allowed_node_types:
            raise SecurityError(f"Node type {node_type} is not allowed")

class BashNode(Node):
    async def execute(self, context) -> Any:
        policy = context.security_policy

        if policy and not policy.allow_shell:
            raise SecurityError("Shell execution not allowed")

        if policy and policy.max_subprocess_time_seconds:
            # Enforce timeout
            ...

# Usage:
# Restrictive policy for untrusted agents
untrusted_context = ExecutionContext(
    session=session,
    security_policy=SecurityPolicy(
        allowed_node_types={"HTTPNode", "FunctionNode"},  # No BashNode!
        file_access="none",
        network_access="restricted",
        allowed_hosts=["api.openai.com", "api.anthropic.com"],
        allow_shell=False
    )
)

# Permissive policy for trusted agents
trusted_context = ExecutionContext(
    session=session,
    security_policy=SecurityPolicy(
        file_access="read_write",
        allowed_paths=["/home/user/workspace"],
        network_access="full",
        allow_shell=True,
        max_subprocess_time_seconds=300
    )
)
```

---

### Gap 10: Learning / Improvement

**Problem:** Every task starts from scratch. No cumulative improvement.

**Note:** This is the hardest gap to fill. True learning requires:
- Collecting training data from executions
- Fine-tuning models or updating retrievable knowledge
- Evaluating what "better" means

**Practical approaches:**

**Approach 1: Few-shot learning from memory**
```python
class AgentNode(Node):
    async def execute(self, context) -> Any:
        # Retrieve similar past tasks
        similar_tasks = await context.session.memory.retrieve(
            query=context.input,
            filter={"type": "task_completion", "success": True},
            limit=3
        )

        # Include as examples in prompt
        examples = "\n".join([
            f"Task: {t.value['input']}\nSolution: {t.value['result']}"
            for t in similar_tasks
        ])

        prompt = f"""
        Here are some similar tasks I've solved:
        {examples}

        Now solve this task: {context.input}
        """

        return await llm.execute(context.with_input(prompt))
```

**Approach 2: Feedback collection for future fine-tuning**
```python
@dataclass
class Feedback:
    trace_id: str
    rating: int  # 1-5
    corrections: str | None
    timestamp: datetime

class FeedbackStore:
    async def record(self, feedback: Feedback) -> None: ...
    async def export_for_training(self) -> list[dict]: ...

# After execution:
feedback = await context.request_human_input(
    "How did I do? (1-5)"
)
await feedback_store.record(Feedback(
    trace_id=context.trace.id,
    rating=int(feedback),
    corrections=None,
    timestamp=datetime.now()
))
```

**Approach 3: Tool/strategy preference learning**
```python
class StrategySelector:
    """Learn which strategies work best for which tasks."""

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    async def select_strategy(self, task: str) -> str:
        # Find similar past tasks
        similar = await self.memory.retrieve(task, limit=10)

        # Count which strategies succeeded
        strategy_success = defaultdict(lambda: {"success": 0, "total": 0})
        for memory in similar:
            strategy = memory.value["strategy"]
            strategy_success[strategy]["total"] += 1
            if memory.value["success"]:
                strategy_success[strategy]["success"] += 1

        # Pick highest success rate
        best = max(
            strategy_success.items(),
            key=lambda x: x[1]["success"] / max(x[1]["total"], 1)
        )
        return best[0]
```

---

## Part 3: Priority and Roadmap

### Tier 1: Must Have for Production Agents

| Gap | Effort | Impact | Priority |
|-----|--------|--------|----------|
| Error Handling & Recovery | Medium | Critical | P0 |
| Resource Limits / Budgets | Low | Critical | P0 |
| Cancellation / Interruption | Low | Critical | P0 |
| Basic Observability | Medium | High | P0 |

**Rationale:** Without these, agents are dangerous to deploy. They can fail catastrophically, run forever, burn money, and can't be stopped.

### Tier 2: Important for Useful Agents

| Gap | Effort | Impact | Priority |
|-----|--------|--------|----------|
| Human-in-the-Loop | Low | High | P1 |
| Parallelism | Medium | Medium | P1 |
| Long-Term Memory | High | High | P1 |

**Rationale:** These make agents significantly more capable and safe. Human escalation is a safety net. Parallelism improves performance. Memory enables learning.

### Tier 3: Nice to Have

| Gap | Effort | Impact | Priority |
|-----|--------|--------|----------|
| Checkpointing / Resumption | High | Medium | P2 |
| Security / Sandboxing | High | High (for some use cases) | P2 |
| Learning / Improvement | Very High | Medium | P3 |

**Rationale:** These are valuable but not blocking for initial deployment. Can be added iteratively.

---

## Part 4: Implementation Sketch

### Minimal Viable Agent Framework

Adding just the P0 items to the current architecture:

```python
@dataclass
class ErrorPolicy:
    on_error: Literal["fail", "retry", "skip", "fallback"] = "fail"
    retry_count: int = 0
    timeout_ms: int | None = None
    fallback_value: Any = None

@dataclass
class Budget:
    max_tokens: int | None = None
    max_time_seconds: float | None = None
    max_steps: int | None = None

@dataclass
class ResourceUsage:
    tokens_used: int = 0
    steps_executed: int = 0
    start_time: datetime = field(default_factory=datetime.now)

    def check(self, budget: Budget) -> None:
        if budget.max_tokens and self.tokens_used >= budget.max_tokens:
            raise BudgetExceededError("Token limit reached")
        if budget.max_steps and self.steps_executed >= budget.max_steps:
            raise BudgetExceededError("Step limit reached")
        elapsed = (datetime.now() - self.start_time).total_seconds()
        if budget.max_time_seconds and elapsed >= budget.max_time_seconds:
            raise BudgetExceededError("Time limit reached")

class CancellationToken:
    def __init__(self):
        self._cancelled = False

    def cancel(self): self._cancelled = True
    def check(self):
        if self._cancelled:
            raise CancelledError()

@dataclass
class StepTrace:
    step_id: str
    node_id: str
    input: Any
    output: Any
    error: str | None
    duration_ms: float

@dataclass
class ExecutionTrace:
    steps: list[StepTrace] = field(default_factory=list)

    def add(self, step: StepTrace):
        self.steps.append(step)

    def explain(self) -> str:
        return "\n".join(
            f"{s.step_id}: {s.output}" for s in self.steps
        )

@dataclass
class ExecutionContext:
    session: Session
    budget: Budget | None = None
    usage: ResourceUsage = field(default_factory=ResourceUsage)
    cancellation: CancellationToken | None = None
    trace: ExecutionTrace | None = None
    input: Any = None
    upstream: dict = field(default_factory=dict)

    def with_input(self, input: Any) -> "ExecutionContext":
        return replace(self, input=input)

    def with_upstream(self, upstream: dict) -> "ExecutionContext":
        return replace(self, upstream=upstream)

class Graph(Node):
    def add_step(
        self,
        node: Node,
        step_id: str,
        input: Any = None,
        depends_on: list[str] = None,
        error_policy: ErrorPolicy = None
    ) -> None:
        self._steps[step_id] = Step(
            node=node,
            input=input,
            depends_on=depends_on or [],
            error_policy=error_policy or ErrorPolicy()
        )

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        results = {}

        for step_id in self._topological_order():
            # Check cancellation
            if context.cancellation:
                context.cancellation.check()

            # Check budget
            if context.budget:
                context.usage.check(context.budget)

            step = self._steps[step_id]
            start = datetime.now()

            try:
                result = await self._execute_with_policy(step, context, results)
                error = None
            except Exception as e:
                result = None
                error = str(e)
                raise
            finally:
                # Record trace
                if context.trace:
                    context.trace.add(StepTrace(
                        step_id=step_id,
                        node_id=step.node.id,
                        input=step.input,
                        output=result,
                        error=error,
                        duration_ms=(datetime.now() - start).total_seconds() * 1000
                    ))
                context.usage.steps_executed += 1

            results[step_id] = result

        return results

    async def _execute_with_policy(
        self, step: Step, context: ExecutionContext, results: dict
    ) -> Any:
        policy = step.error_policy
        step_context = context.with_input(step.input).with_upstream(results)

        for attempt in range(policy.retry_count + 1):
            try:
                if policy.timeout_ms:
                    return await asyncio.wait_for(
                        step.node.execute(step_context),
                        timeout=policy.timeout_ms / 1000
                    )
                else:
                    return await step.node.execute(step_context)
            except Exception as e:
                if attempt < policy.retry_count:
                    continue
                if policy.on_error == "skip":
                    return policy.fallback_value
                raise
```

---

## Summary

| Question | Answer |
|----------|--------|
| Is the architecture powerful enough for agents? | Yes, for basic agents |
| What's missing for production? | Error handling, budgets, cancellation, observability |
| What's missing for advanced agents? | Memory, human-in-loop, learning |
| What's the priority order? | P0: Safety/control, P1: Capability, P2: Resilience, P3: Learning |
| Can gaps be filled without restructuring? | Yes, all are additive |

**The Node/Graph/Session architecture is a solid foundation. The gaps are extensions, not redesigns.**
