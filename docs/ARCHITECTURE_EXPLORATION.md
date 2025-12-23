# Architecture Exploration: From Channels to Unified Nodes

This document captures the key explorations, decisions, and findings from our architectural review of the Nerve system.

---

## Part 1: The Exploration Journey

### Starting Point: Current Abstractions

We began by examining the existing abstractions:

| Abstraction | Purpose |
|-------------|---------|
| Channel | Interactive connection to a process (PTY) |
| Session | Groups channels, manages lifecycle |
| Task | Unit of work (async function) |
| DAG | Orchestrates tasks with dependencies |
| Parser | Interprets output from channels |
| Backend | Low-level PTY management |

### Initial Question: Should We Move to Node/Graph?

The question arose: Could we simplify by using just two abstractions—**Node** and **Graph**—instead of Channel, Task, DAG, Session, etc.?

This led to a deeper exploration of what each abstraction actually does.

---

## Part 2: Key Questions We Asked

### Question 1: How Are Channel and Task Different?

**Initial assumption:** They're fundamentally different.
- Channel = interactive, stateful
- Task = fire-and-forget, stateless

**What we discovered:**

| Property | Channel.send() | Task.execute() |
|----------|----------------|----------------|
| Blocking? | Yes (awaits response) | Yes (awaits completion) |
| Returns result? | Yes (ParsedResponse) | Yes (Any) |
| Takes input? | Yes (input string) | Yes (context) |

**Finding:** Both are blocking, send-and-response operations. The "fire-and-forget" characterization of Task was incorrect.

### Question 2: Where Does State Live?

**Channel state:**
- Connection state (OPEN, BUSY, CLOSED) — maintained by Channel
- Conversation history — maintained by Channel

**Task state:**
- Execution state (PENDING, RUNNING, COMPLETED) — maintained by DAG, not Task

**Finding:** Channel maintains its own state. Task is stateless (DAG manages execution state externally).

### Question 3: What's the Real Difference?

After deeper analysis, we identified the core distinction:

| Property | Channel | Task |
|----------|---------|------|
| Lifecycle | Persistent (lives until closed) | Ephemeral (created, executed, done) |
| Reusability | Used multiple times | Executed once per DAG run |
| State | Stateful (history accumulates) | Stateless |

**Finding:** The fundamental difference is **persistent vs. ephemeral**, not "interactive vs. batch" or "blocking vs. non-blocking."

### Question 4: Why Can't DAG Contain Channels?

Current model: DAG only contains Tasks. To use a Channel in a DAG, you wrap it in a Task.

```python
# Current: Wrapping required
task = Task(id="send", execute=lambda ctx: channel.send("ls", parser))
dag.add_task(task)
```

**Finding:** This is a design decision, not a fundamental limitation. DAG could support channel operations directly.

### Question 5: Do We Need Composable Graphs?

**Goals identified:**
1. Many types of nodes (HTTP, DB, channel operations, pure functions)
2. Composable graphs (graphs containing graphs)
3. Visual workflow builder (everything is a node)

**Finding:** For graphs to be composable, **Graph must be a Node**. This is the key architectural requirement.

### Question 6: What About Statefulness and Idempotency?

**Problem:** If a graph uses stateful nodes (like Claude with conversation history), running the same graph twice produces different results.

```python
# Run 1: "What is 1+1?" → "2", "Add 2" → "4"
# Run 2: "What is 1+1?" → "2", "Add 2" → "6" (context accumulated!)
```

**Finding:** This is expected behavior for stateful systems. The architecture should:
- Acknowledge statefulness explicitly
- Provide isolation mechanisms (scoping, reset) when needed
- Not hide the non-idempotency

### Question 7: Is Channel Just a Persistent Node?

This was the breakthrough question.

**Analysis:**

| Channel | Persistent Node |
|---------|-----------------|
| Has state | Has state |
| Has lifecycle (open/close) | Has lifecycle (start/stop) |
| Executes operations | Executes operations |
| Managed by Session | Managed by Session |
| Returns results | Returns results |

**Finding:** Channel IS a persistent Node. We don't need it as a separate abstraction.

---

## Part 3: Key Decisions

### Decision 1: Unify Channel and Task into Node

Instead of separate Channel and Task abstractions, we use a single **Node** protocol with a `persistent` flag:

```python
class Node(Protocol):
    id: str
    persistent: bool = False  # Does this node maintain state?

    async def execute(self, context: ExecutionContext) -> Any: ...
```

**Rationale:**
- Both are units of work that take input and produce output
- The only real difference is lifecycle (persistent vs. ephemeral)
- A flag captures this distinction without needing separate abstractions

### Decision 2: Graph Implements Node

For composable graphs, Graph must be a Node:

```python
class Graph(Node):
    persistent = False

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        # Execute all steps in topological order
        ...
```

**Rationale:**
- Enables `user -> node A -> graph A -> graph B -> node B -> graph C -> user`
- Graphs can contain other graphs naturally
- Consistent abstraction: everything in a graph is a Node

### Decision 3: Session Manages Persistent Node Lifecycle

Session's role is clarified: it manages the lifecycle of persistent nodes.

```python
class Session:
    def register(self, node: Node) -> None: ...
    async def start(self) -> None: ...   # Start all persistent nodes
    async def stop(self) -> None: ...    # Stop all persistent nodes
    def get(self, node_id: str) -> Node: ...
```

**Rationale:**
- Persistent nodes need lifecycle management (start, stop, reset)
- Session is the natural owner of this responsibility
- Separates resource management from execution orchestration

### Decision 4: Graph Tracks Steps, Not Just Nodes

A graph contains **steps**, where each step is a (node, input, dependencies) tuple:

```python
graph.add_step(node, step_id="step1", input="...", depends_on=["step0"])
```

**Rationale:**
- The same persistent node can appear in multiple steps
- Each step can have different input
- Dependencies are between steps, not nodes

### Decision 5: Statefulness is Explicit

Nodes declare whether they're stateful:

```python
class ClaudeNode(Node):
    persistent = True  # Explicit: this node has state
```

And the system provides isolation mechanisms:

```python
# Option 1: Scoped session (fresh nodes)
with session.scope() as scoped:
    result = await graph.execute(scoped)

# Option 2: Reset before run
await session.reset_all()
result = await graph.execute(context)

# Option 3: Isolated execution
result = await graph.execute(context, isolated=True)
```

**Rationale:**
- Don't hide non-idempotency; make it visible
- Provide mechanisms for isolation when users need reproducibility
- Let users choose based on their use case

---

## Part 4: Key Findings

### Finding 1: Three Core Abstractions Are Sufficient

The system can be modeled with just three abstractions:

```
┌─────────────────────────────────────────────────────────────┐
│ NODE (Unit of Work)                                         │
├─────────────────────────────────────────────────────────────┤
│ - id: str                                                   │
│ - persistent: bool                                          │
│ - execute(context) -> Any                                   │
│                                                             │
│ Implementations:                                            │
│ - FunctionNode (ephemeral, stateless computation)           │
│ - ClaudeNode (persistent, stateful CLI interaction)         │
│ - HTTPNode (ephemeral or persistent)                        │
│ - DatabaseNode (persistent, connection pool)                │
│ - Graph (contains other nodes, is itself a node)            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ SESSION (Lifecycle Manager)                                 │
├─────────────────────────────────────────────────────────────┤
│ - Registers persistent nodes                                │
│ - Manages start/stop lifecycle                              │
│ - Provides node access by ID                                │
│ - Handles scoping/isolation for reproducibility             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ GRAPH (Execution Orchestrator, IS a Node)                   │
├─────────────────────────────────────────────────────────────┤
│ - Contains steps (node + input + dependencies)              │
│ - Executes in topological order                             │
│ - Passes results from upstream to downstream                │
│ - Can contain other Graphs (composable)                     │
│ - Same node can appear in multiple steps                    │
└─────────────────────────────────────────────────────────────┘
```

### Finding 2: Channel Abstraction is Unnecessary

What we called "Channel" is just a persistent Node:

| Old | New |
|-----|-----|
| Channel | Persistent Node (`persistent=True`) |
| channel.send(input, parser) | node.execute(context) |
| Session.add_channel() | Session.register(node) |
| ChannelOperationNode | Just use the node directly in graph steps |

### Finding 3: DAG Becomes Graph

What we called "DAG" becomes "Graph" with one key change: Graph is a Node.

| Old | New |
|-----|-----|
| DAG | Graph (implements Node) |
| dag.add_task(task) | graph.add_step(node, step_id, input) |
| Task.depends_on | graph.add_step(..., depends_on=[...]) |
| DAG can't contain DAG | Graph can contain Graph |

### Finding 4: Dependencies Move to Graph

In the old model, Task had `depends_on`. In the new model, dependencies are expressed in the Graph:

```python
# Old: Dependencies in Task
task = Task(id="b", execute=..., depends_on=["a"])

# New: Dependencies in Graph
graph.add_step(node_b, step_id="b", depends_on=["a"])
```

**Benefit:** Nodes are more reusable. The same node can have different dependencies in different graphs.

### Finding 5: State Ownership is Clear

| State Type | Owner | Lifetime |
|------------|-------|----------|
| Node internal state (history, connection) | Node | Node lifetime |
| Execution results | ExecutionContext | Graph run |
| Node registry | Session | Session lifetime |
| Step dependencies | Graph | Graph definition |

### Finding 6: The System Supports Multiple Node Types

With the unified model, adding new node types is straightforward:

```python
# All implement the same Node protocol
class FunctionNode(Node): ...      # Pure computation
class ClaudeNode(Node): ...        # CLI interaction
class HTTPNode(Node): ...          # HTTP requests
class DatabaseNode(Node): ...      # Database queries
class FileNode(Node): ...          # File operations
class Graph(Node): ...             # Composition of nodes
```

---

## Part 5: The Unified Architecture

### Before (Current)

```
Session
├── Channel 1 (ClaudeChannel)
├── Channel 2 (BashChannel)
└── Channel 3 (PythonChannel)

DAG
├── Task A (wraps channel operation)
├── Task B (wraps channel operation)
└── Task C (pure function)
```

**Problems:**
- Channel and Task are separate abstractions that do similar things
- DAG can't contain another DAG
- Wrapping channel operations in Tasks is boilerplate
- Two parallel hierarchies (Session→Channel, DAG→Task)

### After (Unified)

```
Session (manages lifecycle of persistent nodes)
├── ClaudeNode (persistent=True)
├── BashNode (persistent=True)
└── DatabaseNode (persistent=True)

Graph (is a Node, orchestrates steps)
├── Step 1: ClaudeNode with input "..."
├── Step 2: ClaudeNode with input "..." (same node, different input)
├── Step 3: FunctionNode (pure computation)
├── Step 4: Subgraph A (Graph is a Node!)
│   ├── Step 4.1: ...
│   └── Step 4.2: ...
└── Step 5: BashNode with input "..."
```

**Benefits:**
- One abstraction for all work: Node
- Composable: Graph is a Node, so graphs can contain graphs
- No wrapping: Use nodes directly in graph steps
- Clear ownership: Session manages persistent nodes, Graph manages execution flow

---

## Part 6: Example Usage

```python
# 1. Define nodes
claude = ClaudeNode(id="claude")
bash = BashNode(id="bash")
process = FunctionNode(id="process", fn=lambda ctx: transform(ctx.upstream))

# 2. Register persistent nodes with session
session = Session()
session.register(claude)
session.register(bash)

# 3. Build a subgraph
setup_graph = Graph(id="setup")
setup_graph.add_step(bash, step_id="check_env", input="echo $PATH")
setup_graph.add_step(bash, step_id="check_version", input="python --version", depends_on=["check_env"])

# 4. Build main graph (contains nodes AND subgraph)
main = Graph(id="main")
main.add_step(setup_graph, step_id="setup")  # Graph as a step!
main.add_step(claude, step_id="ask", input="What is 1+1?", depends_on=["setup"])
main.add_step(claude, step_id="followup", input="Add 2 to that", depends_on=["ask"])
main.add_step(process, step_id="process", depends_on=["followup"])

# 5. Execute
await session.start()
result = await main.execute(ExecutionContext(session=session))
await session.stop()

# 6. Access results
print(result["setup"])     # Subgraph results
print(result["ask"])       # Claude's first response
print(result["followup"])  # Claude's second response
print(result["process"])   # Processed output
```

---

## Part 7: What Remains

### Still Needed (Unchanged)

- **Parser**: Interprets output from persistent nodes (e.g., ClaudeParser)
- **Backend**: Low-level PTY/terminal abstraction (PTYBackend, WezTermBackend)
- **ExecutionContext**: Carries session, input, upstream results through execution

### Open Questions

1. **Parser attachment**: Where does parser config go?
   - Option A: Per-step in graph
   - Option B: Default on node, override per-step
   - Option C: In execution context

2. **Error handling**: How do persistent node failures propagate?
   - If ClaudeNode dies mid-graph, what happens to dependent steps?

3. **Concurrency**: Can two steps use the same persistent node simultaneously?
   - Probably not. Need mutual exclusion or queuing.

4. **History/logging**: Where does execution history live?
   - Probably ExecutionLog, passed through context

---

## Part 8: Session Stores Everything (Including Graphs)

### Question: Can Session Store Graphs?

**Yes, because Graph is a Node.**

If Session stores Nodes, and Graph implements Node, then Session can store Graphs. This is already consistent with our model.

```python
session.register(claude_node)   # Persistent node
session.register(bash_node)     # Persistent node
session.register(graph_a)       # Graph (is a Node)
session.register(main_graph)    # Graph (is a Node)
```

### Decision 6: Session Stores All Nodes (Including Graphs)

Session becomes a registry for all reusable components:

```python
class Session:
    def __init__(self):
        self._registry: dict[str, Node] = {}  # All nodes (including graphs)

    def register(self, node: Node) -> None:
        """Register any node (persistent, ephemeral, or graph)."""
        self._registry[node.id] = node

    def get(self, node_id: str) -> Node:
        """Get node by ID (could be a simple node or a graph)."""
        return self._registry[node_id]

    async def start(self) -> None:
        """Start all persistent nodes (recursively in graphs)."""
        for node in self._collect_persistent_nodes():
            await node.start()

    def _collect_persistent_nodes(self) -> list[Node]:
        """Find all persistent nodes, including inside graphs."""
        persistent = []
        for node in self._registry.values():
            if node.persistent:
                persistent.append(node)
            if isinstance(node, Graph):
                persistent.extend(node.collect_persistent_nodes())
        return persistent
```

### Two Ways to Reference Nodes in Graphs

**Direct reference:**
```python
graph.add_step(claude_node, step_id="ask", input="...")
```

**Reference by ID (resolved from session):**
```python
graph.add_step_ref("claude", step_id="ask", input="...")
# At execution time, resolves: session.get("claude")
```

### Graph API with Both Options

```python
class Graph(Node):
    def add_step(
        self,
        node: Node,           # Direct reference
        step_id: str,
        input: Any = None,
        depends_on: list[str] = None
    ) -> None:
        """Add step with direct node reference."""
        self._steps[step_id] = Step(node=node, input=input, depends_on=depends_on)

    def add_step_ref(
        self,
        node_id: str,         # Reference by ID
        step_id: str,
        input: Any = None,
        depends_on: list[str] = None
    ) -> None:
        """Add step with node reference (resolved at execution time)."""
        self._steps[step_id] = Step(node_ref=node_id, input=input, depends_on=depends_on)

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        results = {}
        for step_id in self._topological_order():
            step = self._steps[step_id]

            # Resolve node (direct or by ID)
            node = step.node if step.node else context.session.get(step.node_ref)

            step_context = context.with_input(step.input).with_upstream(results)
            results[step_id] = await node.execute(step_context)

        return results
```

### Benefits of Reference by ID

1. **Late binding**: Graphs can reference nodes/graphs defined later
2. **Reusable templates**: Define graph structure, swap implementations
3. **Graph libraries**: Build a library of reusable graphs
4. **Dynamic composition**: Choose which graph to use at runtime

### Complete Example: Deeply Nested Graphs

```python
# 1. Define persistent nodes
claude = ClaudeNode(id="claude")
bash = BashNode(id="bash")
db = DatabaseNode(id="db")

# 2. Define leaf graph (level 3)
query_graph = Graph(id="query_graph")
query_graph.add_step(db, step_id="fetch", input="SELECT * FROM users")
query_graph.add_step(FunctionNode(id="transform", fn=transform),
                     step_id="transform", depends_on=["fetch"])

# 3. Define mid graph (level 2) - embeds query_graph
process_graph = Graph(id="process_graph")
process_graph.add_step(bash, step_id="prepare", input="echo 'preparing'")
process_graph.add_step(query_graph, step_id="query", depends_on=["prepare"])
process_graph.add_step(claude, step_id="analyze",
                       input="Analyze this data", depends_on=["query"])

# 4. Define main graph (level 1) - embeds process_graph
main_graph = Graph(id="main")
main_graph.add_step(bash, step_id="init", input="echo 'starting'")
main_graph.add_step(process_graph, step_id="process", depends_on=["init"])
main_graph.add_step(bash, step_id="done", input="echo 'finished'", depends_on=["process"])

# 5. Register everything with session
session = Session()
session.register(claude)
session.register(bash)
session.register(db)
session.register(query_graph)
session.register(process_graph)
session.register(main_graph)

# 6. Execute
await session.start()
result = await main_graph.execute(ExecutionContext(session=session))
await session.stop()
```

---

## Part 9: Dynamic Graph Construction

### Question: Can Graphs Be Built at Runtime?

**Yes.** Graphs are just data structures. They can be:
- Built statically (before execution)
- Built dynamically (during execution)
- Modified mid-execution
- Built by LLMs
- Built by other graphs

This enables **adaptive workflows** and **agent-like behavior**.

### Pattern 1: Controller Node (Builds Subgraphs Dynamically)

A node that decides what to do next and builds a graph on the fly:

```python
class OrchestratorNode(Node):
    """Dynamically builds and executes subgraphs based on results."""

    async def execute(self, context) -> Any:
        # Step 1: Initial analysis
        initial_result = await self.analyze(context.input)

        # Step 2: Decide what graph to build based on result
        if initial_result.complexity == "high":
            subgraph = self.build_complex_workflow(initial_result)
        elif initial_result.needs_human_review:
            subgraph = self.build_review_workflow(initial_result)
        else:
            subgraph = self.build_simple_workflow(initial_result)

        # Step 3: Execute the dynamically built graph
        return await subgraph.execute(context)

    def build_complex_workflow(self, data) -> Graph:
        graph = Graph(id="complex_workflow")
        graph.add_step(deep_analysis_node, step_id="analyze", input=data)
        graph.add_step(validation_node, step_id="validate", depends_on=["analyze"])
        graph.add_step(synthesis_node, step_id="synthesize", depends_on=["validate"])
        return graph
```

### Pattern 2: Agent Loop (Iterative Graph Building)

An agent that iteratively decides what to do next:

```python
class AgentNode(Node):
    """An agent that dynamically builds its execution path."""

    def __init__(self, id: str, max_iterations: int = 10):
        self.id = id
        self.max_iterations = max_iterations

    async def execute(self, context) -> Any:
        state = AgentState(goal=context.input, history=[])

        for i in range(self.max_iterations):
            # 1. Decide next action
            next_action = await self.decide_next_action(state, context)

            if next_action.type == "done":
                return state.final_result

            # 2. Build a graph for this action
            action_graph = self.build_action_graph(next_action)

            # 3. Execute and update state
            result = await action_graph.execute(context)
            state = state.with_result(next_action, result)

        return state.final_result

    def build_action_graph(self, action: Action) -> Graph:
        graph = Graph(id=f"action_{action.type}")

        if action.type == "search":
            graph.add_step_ref("search", step_id="do", input=action.query)
        elif action.type == "analyze":
            graph.add_step_ref("claude", step_id="do", input=action.data)
        elif action.type == "execute_code":
            graph.add_step_ref("bash", step_id="do", input=action.code)

        return graph
```

### Pattern 3: Streaming Execution with Dynamic Expansion

Execute step by step, allowing modification between steps:

```python
class DynamicGraph(Graph):
    """A graph that can be modified during execution."""

    async def execute_streaming(self, context) -> AsyncIterator[StepResult]:
        executed = set()

        while True:
            ready = self.get_ready_steps(executed)
            if not ready:
                break

            for step in ready:
                result = await self.execute_step(step, context)
                executed.add(step.id)

                # Yield result - caller can add more steps!
                yield StepResult(step_id=step.id, result=result, graph=self)

# Usage:
graph = DynamicGraph(id="dynamic")
graph.add_step(start_node, step_id="start")

async for step_result in graph.execute_streaming(context):
    # Dynamically add steps based on results!
    if step_result.step_id == "start" and step_result.result.needs_analysis:
        graph.add_step(analyze_node, step_id="analyze", depends_on=["start"])
```

### Pattern 4: Self-Modifying Graph

Nodes can add steps to the graph they're part of:

```python
class GraphAwareNode(Node):
    """A node that can modify the graph it's part of."""

    async def execute(self, context) -> Any:
        result = await self.do_work(context.input)

        # Access the graph and add more steps!
        graph = context.current_graph

        if result.needs_followup:
            graph.add_step(
                followup_node,
                step_id=f"followup_{self.id}",
                input=result.followup_data,
                depends_on=[context.current_step_id]
            )

        return result
```

### Pattern 5: LLM-Driven Graph Construction

An LLM decides what graph to build:

```python
class LLMOrchestratorNode(Node):
    """Uses an LLM to decide what graph to build."""

    async def execute(self, context) -> Any:
        task = context.input

        # Ask LLM what steps are needed
        claude = context.session.get("claude")
        plan_result = await claude.execute(context.with_input(f"""
        Task: {task}

        Available tools: search, analyze, code, write

        What steps should I take? Return as JSON:
        [{{"action": "search", "input": "..."}}, ...]
        """))

        steps = parse_plan(plan_result)

        # Build graph from LLM's plan
        graph = Graph(id="llm_planned")
        prev_step = None

        for i, step in enumerate(steps):
            step_id = f"step_{i}"
            graph.add_step_ref(
                step.action,  # Node ID from session
                step_id=step_id,
                input=step.input,
                depends_on=[prev_step] if prev_step else None
            )
            prev_step = step_id

        return await graph.execute(context)
```

### Complete Example: Self-Building Dev Agent

```python
# Define available tools
claude = ClaudeNode(id="claude")
bash = BashNode(id="bash")
search = SearchNode(id="search")

session = Session()
session.register(claude)
session.register(bash)
session.register(search)

class DevAgent(Node):
    async def execute(self, context) -> Any:
        task = context.input
        history = []
        claude = context.session.get("claude")

        while True:
            # Ask Claude what to do
            decision = await claude.execute(context.with_input(f"""
            Task: {task}
            History: {history}

            What next? Options:
            1. SEARCH: <query>
            2. BASH: <command>
            3. THINK: <analysis>
            4. DONE: <final_answer>
            """))

            action = parse_decision(decision)

            if action.type == "DONE":
                return action.content

            # Build mini-graph for this action
            action_graph = Graph(id=f"action_{len(history)}")

            if action.type == "SEARCH":
                action_graph.add_step_ref("search", step_id="do", input=action.content)
            elif action.type == "BASH":
                action_graph.add_step_ref("bash", step_id="do", input=action.content)
            elif action.type == "THINK":
                action_graph.add_step_ref("claude", step_id="do", input=action.content)

            result = await action_graph.execute(context)
            history.append({"action": action, "result": result})

# Use the agent in a graph
agent = DevAgent(id="dev_agent")
main_graph = Graph(id="main")
main_graph.add_step(agent, step_id="agent", input="Find and fix the bug in auth.py")

await session.start()
result = await main_graph.execute(ExecutionContext(session=session))
```

### Finding 7: Graphs Are Data, Not Just Structure

Graphs are runtime data structures that can be:

| Capability | Description |
|------------|-------------|
| Built statically | Defined before execution |
| Built dynamically | Created during execution based on results |
| Modified mid-run | Steps added while executing |
| Nested arbitrarily | Graphs in graphs in graphs |
| LLM-generated | AI decides the workflow structure |
| Self-modifying | Nodes add their own follow-up steps |

This is the foundation for building **AI agents** on top of the Node/Graph architecture.

---

## Part 10: Updated Architecture Summary

### The Three Core Abstractions (Final)

```
┌─────────────────────────────────────────────────────────────┐
│ NODE (Unit of Work)                                         │
├─────────────────────────────────────────────────────────────┤
│ Protocol:                                                   │
│ - id: str                                                   │
│ - persistent: bool                                          │
│ - execute(context) -> Any                                   │
│                                                             │
│ Implementations:                                            │
│ - FunctionNode (ephemeral, stateless)                       │
│ - ClaudeNode (persistent, stateful)                         │
│ - HTTPNode, DatabaseNode, etc.                              │
│ - Graph (composable, contains other nodes)                  │
│ - AgentNode (dynamic, builds graphs at runtime)             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ SESSION (Registry & Lifecycle Manager)                      │
├─────────────────────────────────────────────────────────────┤
│ Responsibilities:                                           │
│ - Stores all nodes (persistent, ephemeral, graphs)          │
│ - Provides access by ID (for reference-based composition)   │
│ - Manages lifecycle of persistent nodes (start/stop)        │
│ - Handles scoping/isolation for reproducibility             │
│ - Recursively finds persistent nodes in nested graphs       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ GRAPH (Execution Orchestrator, IS a Node)                   │
├─────────────────────────────────────────────────────────────┤
│ Capabilities:                                               │
│ - Contains steps (node + input + dependencies)              │
│ - Supports direct references and ID-based references        │
│ - Executes in topological order                             │
│ - Can contain other Graphs (arbitrarily nested)             │
│ - Can be built/modified at runtime (dynamic workflows)      │
│ - Same node can appear in multiple steps                    │
│ - Supports streaming execution for dynamic expansion        │
└─────────────────────────────────────────────────────────────┘
```

### Execution Patterns Supported

| Pattern | Description | Use Case |
|---------|-------------|----------|
| Static Graph | Pre-defined structure | Simple workflows |
| Nested Graphs | Graphs containing graphs | Modular composition |
| Controller Node | Node builds subgraph based on input | Conditional workflows |
| Agent Loop | Iterative decide-act-observe | Goal-driven agents |
| Streaming Execution | Step-by-step with dynamic additions | Reactive workflows |
| Self-Modifying | Nodes add follow-up steps | Adaptive processing |
| LLM-Driven | AI decides graph structure | Autonomous agents |

---

## Summary

| Question | Answer |
|----------|--------|
| Is Channel different from Node? | No. Channel is a persistent Node. |
| Do we need separate Channel abstraction? | No. Use `persistent=True` on Node. |
| Can DAG contain DAG? | Yes, Graph implements Node. |
| Can Session store Graphs? | Yes, Graph is a Node. |
| Can Graphs be built at runtime? | Yes, graphs are just data structures. |
| Can Graphs modify themselves during execution? | Yes, via streaming execution or graph-aware nodes. |
| What are the core abstractions? | Node, Graph (is a Node), Session |
| Where does state live? | In persistent Nodes, managed by Session |
| Is non-idempotency a bug? | No. It's expected. Provide isolation mechanisms. |

**The unified model is simpler, more consistent, enables composable graphs, and supports dynamic/agent-like behavior.**
