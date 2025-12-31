# PRD: Workflow System with Control Nodes

**Status**: Draft
**Author**: Claude
**Created**: 2024-12-31
**Last Updated**: 2024-12-31

---

## Executive Summary

This PRD proposes adding a **Workflow System** to Nerve that enables complex, interactive agent orchestration with control flow (loops, conditionals, gates) while maintaining full Commander integration. Users can define workflows that coordinate multiple agents, respond to intermediate results, and request human input—all controllable from Commander.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Goals and Non-Goals](#2-goals-and-non-goals)
3. [User Stories](#3-user-stories)
4. [Design Alternatives](#4-design-alternatives) ← **Two approaches compared**
5. [Solution Overview](#5-solution-overview)
6. [Detailed Design](#6-detailed-design)
7. [Technical Implementation](#7-technical-implementation)
8. [API Reference](#8-api-reference)
9. [Testing Strategy](#9-testing-strategy)
10. [Rollout Plan](#10-rollout-plan)
11. [Open Questions](#11-open-questions)

---

## 1. Problem Statement

### Current State

Nerve currently supports two execution models:

1. **Nodes**: Single-step execution units (Claude, Bash, LLM APIs)
2. **Graphs**: DAG-based pipelines with dependencies, executed in topological order

Both are accessible from Commander:
```
@claude What is 2+2?           # Execute node
@my_pipeline                    # Execute graph (DAG)
```

### The Gap

**Graphs are DAGs—they have no control flow.** This means:

- ❌ No loops (repeat until condition)
- ❌ No conditionals (if/else branching)
- ❌ No human-in-the-loop (pause for approval)
- ❌ No dynamic iteration (process list of unknown size)

**Real-world agent workflows require control flow:**

```
Example: Code Review Workflow
1. Developer writes code
2. LOOP until approved:
   a. Coach reviews code
   b. IF approved: exit loop
   c. ELSE: Developer addresses feedback
3. Reviewer does final check
4. GATE: Wait for human approval
5. Merge
```

### Current Workaround

Users write Python scripts that manually orchestrate nodes:

```python
# examples/agents/dev_coach_review/main.py (400+ lines)
while outer_round < MAX_OUTER_ROUNDS and not reviewer_accepted:
    while inner_round < MAX_INNER_ROUNDS and not coach_accepted:
        result = await client.send_command(...)
        if COACH_ACCEPTANCE in response:
            break
    # ... more manual orchestration
```

**Problems with this approach:**

| Issue | Impact |
|-------|--------|
| Not integrated with Commander | Can't invoke with `@workflow` |
| No visibility | Can't see progress in Commander |
| No interactivity | Can't provide input mid-execution |
| No pause/resume | Can't checkpoint long workflows |
| Boilerplate heavy | Every workflow reinvents the wheel |
| Hard to compose | Can't nest workflows in graphs |

### Who is Affected

1. **Power users** building multi-agent systems
2. **Teams** needing human approval gates
3. **Developers** wanting reusable orchestration patterns

---

## 2. Goals and Non-Goals

### Goals

| ID | Goal | Success Metric |
|----|------|----------------|
| G1 | Enable control flow in graphs | Can express loops, conditionals, gates as nodes |
| G2 | Commander integration | Workflows invocable via `%workflow_id` |
| G3 | Interactive execution | Human can provide input during workflow |
| G4 | Live progress visibility | Commander shows real-time workflow state |
| G5 | Composability | Control nodes work like regular nodes |
| G6 | Pause/Resume/Stop | User can control running workflows |

### Non-Goals

| ID | Non-Goal | Rationale |
|----|----------|-----------|
| NG1 | Visual workflow editor | Out of scope; focus on programmatic definition |
| NG2 | Distributed execution | Single-server execution for v1 |
| NG3 | Workflow versioning | No version control for workflow definitions |
| NG4 | Automatic retry across restarts | Checkpointing is stretch goal |
| NG5 | YAML/JSON workflow definition | Python-first; declarative format is future work |

### Success Criteria

1. `dev_coach_review` can be expressed as a Graph with control nodes
2. User can run `%dev_coach_review` in Commander and see live progress
3. User can respond to approval gates from Commander
4. User can `/pause` and `/stop` running workflows
5. All existing Graph functionality continues to work

---

## 3. User Stories

### US1: Define Workflow with Loops

**As a** developer building a research agent
**I want to** define a search loop that continues until enough info is found
**So that** the agent autonomously refines its search

```python
research_loop = WhileNode(
    id="search_loop",
    session=session,
    condition=lambda state: not state.current_value.get("sufficient"),
    body=search_evaluate_graph,
    max_iterations=5,
)
```

### US2: Conditional Branching

**As a** developer building a review system
**I want to** branch based on review outcome (approved/rejected)
**So that** the workflow takes different paths

```python
review_branch = BranchNode(
    id="review_check",
    session=session,
    condition=lambda inp: "APPROVED" in inp.get("output", ""),
    then_branch=complete_node,
    else_branch=revision_loop,
)
```

### US3: Human Approval Gate

**As a** team lead
**I want to** require human approval before merging
**So that** automated workflows don't make irreversible changes without oversight

```python
approval_gate = GateNode(
    id="merge_approval",
    session=session,
    prompt="Review the changes and type 'approve' to merge:",
    timeout=3600.0,  # 1 hour
)
```

### US4: Invoke from Commander

**As a** user
**I want to** start workflows from Commander with `%workflow_id`
**So that** I have a unified interface for all operations

```
> %research_agent What are Rust error handling best practices?
```

### US5: See Live Progress

**As a** user running a long workflow
**I want to** see which step is executing and iteration progress
**So that** I know the workflow is making progress

```
╭─────────────────── Workflow Progress ───────────────────╮
│ 🔄 research_agent                                        │
│ ├─ ✓ init                                      (0.1s)   │
│ ├─ ● research_loop [2/5]                                │
│ │   └─ evaluating...                                    │
│ ├─ ○ synthesize                                          │
│ └─ ○ approve                                             │
╰──────────────────────────────────────────────────────────╯
```

### US6: Respond to Gates

**As a** user
**I want to** type responses when a workflow asks for input
**So that** I can guide the workflow interactively

```
╭──────────────── ⏸ Waiting for Input ─────────────────╮
│ Research complete. Approve to finalize?               │
╰───────────────────────────────────────────────────────╯
> approve
```

### US7: Control Running Workflows

**As a** user
**I want to** pause, resume, or stop workflows
**So that** I can manage long-running operations

```
> /pause      # Pause at next safe point
> /resume     # Continue execution
> /stop       # Abort workflow
```

---

## 4. Design Alternatives

We have two viable approaches to solve the control flow problem. Both achieve the same goals but with different trade-offs.

---

### Approach A: Python Workflow Functions (Simpler)

**Core Idea**: Workflows are async Python functions registered with the session. Full Python control flow, minimal new abstractions.

#### How It Works

```python
# nerve/core/workflow/workflow.py

class Workflow:
    """A registered async function that orchestrates nodes."""

    def __init__(
        self,
        id: str,
        session: Session,
        fn: Callable[[WorkflowContext], Awaitable[Any]],
        description: str = "",
    ) -> None:
        session.validate_unique_id(id, "workflow")
        self._id = id
        self._session = session
        self._fn = fn
        self._description = description

        # Auto-register
        session.workflows[id] = self

    async def execute(self, input: Any, params: dict | None = None) -> Any:
        ctx = WorkflowContext(
            session=self._session,
            input=input,
            params=params or {},
        )
        return await self._fn(ctx)
```

#### WorkflowContext - The Bridge

```python
@dataclass
class WorkflowContext:
    """Context passed to workflow functions - provides helpers for common ops."""

    session: Session
    input: Any
    params: dict[str, Any]
    state: dict[str, Any] = field(default_factory=dict)  # Mutable state

    # Event emission for Commander visibility
    _event_sink: EventSink | None = None

    async def run(self, node_id: str, input: Any, **kwargs) -> dict:
        """Execute a node and return result. Primary workflow building block."""
        node = self.session.get_node(node_id)
        if not node:
            raise ValueError(f"Node '{node_id}' not found")

        ctx = ExecutionContext(session=self.session, input=input, **kwargs)
        return await node.execute(ctx)

    async def run_graph(self, graph_id: str, input: Any = None) -> dict:
        """Execute a graph and return result."""
        graph = self.session.get_graph(graph_id)
        if not graph:
            raise ValueError(f"Graph '{graph_id}' not found")

        ctx = ExecutionContext(session=self.session, input=input)
        return await graph.execute(ctx)

    def emit(self, event_type: str, data: dict | None = None) -> None:
        """Emit event for Commander to display."""
        if self._event_sink:
            self._event_sink.emit(event_type, data or {})

    async def gate(self, prompt: str, timeout: float | None = None) -> str:
        """Pause and wait for user input. Returns user's response."""
        future = asyncio.Future()

        self.emit("gate_waiting", {"prompt": prompt})

        # Store future for external resolution
        self._pending_gate = future

        try:
            if timeout:
                return await asyncio.wait_for(future, timeout=timeout)
            return await future
        finally:
            self._pending_gate = None

    def receive_gate_input(self, value: str) -> None:
        """Called externally when user provides input."""
        if self._pending_gate and not self._pending_gate.done():
            self._pending_gate.set_result(value)
```

#### Defining Workflows - Pure Python

```python
# examples/workflows/research_agent.py

async def research_workflow(ctx: WorkflowContext) -> dict:
    """Research agent - searches until sufficient info, then synthesizes."""

    query = ctx.input
    max_iterations = ctx.params.get("max_iterations", 5)

    ctx.emit("phase", {"name": "research", "query": query})

    findings = []
    iteration = 0

    # Plain Python while loop!
    while iteration < max_iterations:
        iteration += 1
        ctx.emit("iteration", {"current": iteration, "max": max_iterations})

        # Search
        search_result = await ctx.run("searcher", f"Search for: {query}")
        findings.append(search_result["output"])

        # Evaluate
        eval_result = await ctx.run("evaluator", f"Is this sufficient?\n{findings[-1]}")

        # Plain Python if statement!
        if "SUFFICIENT" in eval_result["output"]:
            ctx.emit("phase", {"name": "sufficient", "iterations": iteration})
            break

        # Refine query
        refine_result = await ctx.run("evaluator", f"Suggest better query for: {query}")
        query = refine_result["output"]

    # Synthesize
    ctx.emit("phase", {"name": "synthesize"})
    all_findings = "\n---\n".join(findings)
    synthesis = await ctx.run("writer", f"Synthesize:\n{all_findings}")

    # Gate - wait for human approval
    approval = await ctx.gate(
        f"Research complete. Approve?\n\nPreview:\n{synthesis['output'][:500]}..."
    )

    if approval.lower() != "approve":
        return {"success": False, "reason": "rejected", "feedback": approval}

    return {
        "success": True,
        "answer": synthesis["output"],
        "iterations": iteration,
    }


# Registration
def register(session: Session):
    Workflow(
        id="research_agent",
        session=session,
        fn=research_workflow,
        description="Research and synthesize information",
    )
```

#### dev_coach_review as Python Workflow

```python
async def dev_coach_review_workflow(ctx: WorkflowContext) -> dict:
    """Dev + Coach + Reviewer collaboration."""

    task = ctx.input
    max_outer = ctx.params.get("max_outer", 10)
    max_inner = ctx.params.get("max_inner", 30)

    # Initial dev work
    ctx.emit("phase", {"name": "initial_dev"})
    dev_result = await ctx.run("dev", f"Implement: {task}")
    dev_response = dev_result["output"]

    outer_round = 0
    reviewer_accepted = False

    # Outer loop: Reviewer iterations
    while outer_round < max_outer and not reviewer_accepted:
        outer_round += 1
        ctx.emit("outer_round", {"round": outer_round, "max": max_outer})

        # Inner loop: Dev <-> Coach
        inner_round = 0
        coach_accepted = False

        while inner_round < max_inner and not coach_accepted:
            inner_round += 1
            ctx.emit("inner_round", {
                "outer": outer_round,
                "inner": inner_round,
                "max": max_inner,
            })

            # Coach reviews
            coach_result = await ctx.run("coach", f"Review:\n{dev_response}")

            if "ACCEPTED" in coach_result["output"]:
                coach_accepted = True
                ctx.emit("coach_accepted", {"round": inner_round})
                break

            # Dev addresses feedback
            dev_result = await ctx.run("dev", f"Address:\n{coach_result['output']}")
            dev_response = dev_result["output"]

        # Reviewer check
        ctx.emit("phase", {"name": "reviewer", "outer": outer_round})
        reviewer_result = await ctx.run("reviewer", "Final review")

        if "APPROVED" in reviewer_result["output"]:
            reviewer_accepted = True
            ctx.emit("reviewer_accepted", {"round": outer_round})

    # Final gate
    if reviewer_accepted:
        approval = await ctx.gate("Reviewer approved. Merge?")
        return {"success": approval.lower() == "approve", "rounds": outer_round}

    return {"success": False, "reason": "max_rounds", "rounds": outer_round}
```

#### Approach A: Pros and Cons

| Pros | Cons |
|------|------|
| ✅ Minimal new abstractions | ❌ Can't visualize workflow structure |
| ✅ Full Python expressiveness | ❌ Harder to serialize/store workflows |
| ✅ Easy to understand and debug | ❌ No declarative format (YAML/JSON) |
| ✅ No new "control node" concepts | ❌ Can't compose into other graphs |
| ✅ Faster to implement | ❌ Each workflow is a black box |
| ✅ Existing Python skills transfer | ❌ Harder to build tooling around |

---

### Approach B: Control Nodes (Composable)

**Core Idea**: Control flow constructs become nodes that compose in Graphs. Declarative, visual, tooling-friendly.

*(This is detailed in Section 5 onwards)*

#### Quick Example

```python
# Same research workflow, but as composable nodes
research_loop = WhileNode(
    id="search_loop",
    session=session,
    condition=lambda s: "SUFFICIENT" not in str(s.current_value),
    body=search_evaluate_graph,
    max_iterations=5,
)

workflow = Graph(id="research_agent", session=session)
workflow.add_step(init_node, "init")
workflow.add_step(research_loop, "research", depends_on=["init"])
workflow.add_step(synthesize_node, "synthesize", depends_on=["research"])
workflow.add_step(gate_node, "approve", depends_on=["synthesize"])
```

#### Approach B: Pros and Cons

| Pros | Cons |
|------|------|
| ✅ Composable - nest in other graphs | ❌ More abstractions to learn |
| ✅ Visual structure - can render DAG | ❌ Lambda conditions less intuitive |
| ✅ Declarative - could generate YAML | ❌ Complex nested loops get messy |
| ✅ Tooling-friendly - introspection | ❌ More code to implement |
| ✅ Consistent with existing Graph API | ❌ Python logic split across nodes |
| ✅ Can validate before execution | ❌ Debugging requires tracing |

---

### Comparison Matrix

| Criteria | Approach A (Python Fn) | Approach B (Control Nodes) |
|----------|------------------------|---------------------------|
| **Learning curve** | Low - just Python | Medium - new node types |
| **Implementation effort** | ~1 week | ~2-3 weeks |
| **Expressiveness** | Unlimited (Python) | Structured (node composition) |
| **Debuggability** | Python debugger | Graph tracing |
| **Commander integration** | Same for both | Same for both |
| **Composability** | Functions call functions | Nodes compose in graphs |
| **Serialization** | Hard (code is logic) | Easier (graph structure) |
| **Future YAML format** | Not feasible | Possible |
| **Tooling potential** | Limited | High (visual editors, etc.) |

---

### Recommendation: Hybrid Approach

**Start with Approach A (Python Workflows)** for immediate value:
- Faster to implement
- Solves the core problem (Commander integration)
- Lower learning curve for users
- Matches existing `dev_coach_review` pattern

**Add Approach B (Control Nodes) later** for power users:
- When users need visual workflows
- When we want YAML/JSON definitions
- When composability becomes important
- As building blocks for a workflow editor

```
Phase 1: Python Workflows (Approach A)
├── Workflow class
├── WorkflowContext with helpers
├── gate() for human input
├── emit() for Commander events
└── Commander integration

Phase 2: Control Nodes (Approach B) - Optional
├── WhileNode, LoopNode, BranchNode
├── GateNode (reused from Phase 1 concept)
├── MapNode, ReduceNode
└── Session.register_workflow(graph_with_control_nodes)
```

---

### Decision Required

**Q: Which approach should we implement first?**

| Option | Recommendation |
|--------|----------------|
| A only | Fast, simple, solves 90% of cases |
| B only | More powerful, but slower to ship |
| A then B | Best of both - start simple, add power later |
| B then A | Not recommended - higher initial investment |

---

## 5. Solution Overview

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           COMMANDER                                  │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ InputHandler                                                    │ │
│  │  - Routes %, @, / prefixes                                     │ │
│  │  - Sends gate responses                                        │ │
│  └───────────────────────────┬────────────────────────────────────┘ │
│                              │                                       │
│  ┌───────────────────────────▼────────────────────────────────────┐ │
│  │ WorkflowController                                              │ │
│  │  - Starts/stops workflows                                      │ │
│  │  - Subscribes to events                                        │ │
│  │  - Routes user input to gates                                  │ │
│  └───────────────────────────┬────────────────────────────────────┘ │
│                              │                                       │
│  ┌───────────────────────────▼────────────────────────────────────┐ │
│  │ WorkflowRenderer                                                │ │
│  │  - Renders progress tree (Rich TUI)                            │ │
│  │  - Shows gate prompts                                          │ │
│  │  - Displays output stream                                      │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │ WebSocket / Unix Socket
                                  │ (bidirectional events)
┌─────────────────────────────────▼───────────────────────────────────┐
│                             SERVER                                   │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ Session                                                         │ │
│  │  ├─ nodes: {claude, dev, coach, reviewer, ...}                 │ │
│  │  ├─ graphs: {simple_pipeline, ...}                             │ │
│  │  └─ workflows: {research_agent, dev_coach_review, ...}    NEW  │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ Control Nodes (composable in Graphs)                      NEW  │ │
│  │  ├─ WhileNode     - Loop while condition true                  │ │
│  │  ├─ LoopNode      - Loop N times or until condition            │ │
│  │  ├─ BranchNode    - If/else conditional                        │ │
│  │  ├─ SwitchNode    - Multi-way branch (match/case)              │ │
│  │  ├─ MapNode       - Parallel fan-out over collection           │ │
│  │  ├─ ReduceNode    - Aggregate results                          │ │
│  │  └─ GateNode      - Wait for external input                    │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ WorkflowRuntime                                           NEW  │ │
│  │  - Executes workflows                                          │ │
│  │  - Emits events to subscribers                                 │ │
│  │  - Routes gate inputs                                          │ │
│  │  - Manages pause/resume state                                  │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Control Node** | Node that controls execution flow (loop, branch, gate) |
| **Workflow** | A Graph that uses control nodes, registered with session |
| **WorkflowRun** | A single execution instance of a workflow |
| **Gate** | A pause point waiting for external input |
| **Event Stream** | Real-time events from workflow to Commander |

### Prefix Convention

| Prefix | Target | Example |
|--------|--------|---------|
| `@` | Node or Graph (no control flow) | `@claude hello` |
| `%` | Workflow (has control flow) | `%research_agent question` |
| `/` | Commander command | `/pause`, `/stop`, `/status` |

---

## 6. Detailed Design

### 6.1 Control Nodes

Control nodes implement the `Node` protocol and can be composed in Graphs.

#### 6.1.1 WhileNode

Executes body while condition returns True.

```python
@dataclass
class WhileState:
    """State passed to while condition function."""
    iteration: int           # Current iteration (0-indexed)
    current_value: Any       # Output from last iteration (or initial input)
    history: list[dict]      # All previous results

class WhileNode(Node):
    def __init__(
        self,
        id: str,
        session: Session,
        condition: Callable[[WhileState], bool],  # Continue while True
        body: Node | Graph,
        max_iterations: int = 100,
    ): ...

    async def execute(self, context: ExecutionContext) -> dict:
        state = WhileState(iteration=0, current_value=context.input, history=[])

        while self._condition(state) and state.iteration < self._max_iterations:
            # Emit iteration event
            context.emit("loop_iteration", {
                "loop_id": self.id,
                "iteration": state.iteration,
                "max": self._max_iterations,
            })

            # Execute body
            result = await self._body.execute(context.with_input(state.current_value))

            # Update state
            state.history.append(result)
            state.current_value = result.get("output")
            state.iteration += 1

        return {
            "success": True,
            "output": state.current_value,
            "attributes": {
                "iterations": state.iteration,
                "exited_early": state.iteration < self._max_iterations,
            },
        }
```

#### 6.1.2 LoopNode

Executes body N times or until condition is met.

```python
@dataclass
class LoopState:
    """State passed to loop condition function."""
    iteration: int
    result: dict              # Output from current iteration
    accumulated: list[dict]   # All results so far

class LoopNode(Node):
    def __init__(
        self,
        id: str,
        session: Session,
        body: Node | Graph,
        times: int | None = None,                    # Fixed iterations
        until: Callable[[LoopState], bool] | None = None,  # Or condition
        max_iterations: int = 100,
        accumulate: bool = False,  # Return all results vs just last
    ): ...
```

#### 6.1.3 BranchNode

Conditional execution based on input.

```python
class BranchNode(Node):
    def __init__(
        self,
        id: str,
        session: Session,
        condition: Callable[[Any], bool],
        then_branch: Node | Graph,
        else_branch: Node | Graph | None = None,
    ): ...

    async def execute(self, context: ExecutionContext) -> dict:
        branch_taken = "then" if self._condition(context.input) else "else"

        context.emit("branch_taken", {
            "node_id": self.id,
            "branch": branch_taken,
        })

        if branch_taken == "then":
            return await self._then_branch.execute(context)
        elif self._else_branch:
            return await self._else_branch.execute(context)
        else:
            # No else branch, pass through
            return {"success": True, "output": context.input}
```

#### 6.1.4 SwitchNode

Multi-way branching (like match/case).

```python
class SwitchNode(Node):
    def __init__(
        self,
        id: str,
        session: Session,
        key: Callable[[Any], str],  # Extract switch key from input
        cases: dict[str, Node | Graph],
        default: Node | Graph | None = None,
    ): ...
```

#### 6.1.5 MapNode

Parallel execution over a collection.

```python
class MapNode(Node):
    def __init__(
        self,
        id: str,
        session: Session,
        body: Node | Graph,
        max_parallel: int = 5,
    ): ...

    async def execute(self, context: ExecutionContext) -> dict:
        items = context.input if isinstance(context.input, list) else [context.input]

        semaphore = asyncio.Semaphore(self._max_parallel)

        async def process(idx: int, item: Any) -> tuple[int, dict]:
            async with semaphore:
                context.emit("map_item_start", {"index": idx, "total": len(items)})
                result = await self._body.execute(context.with_input(item))
                context.emit("map_item_complete", {"index": idx})
                return (idx, result)

        results = await asyncio.gather(*[process(i, item) for i, item in enumerate(items)])
        ordered = [r for _, r in sorted(results)]

        return {
            "success": all(r.get("success") for r in ordered),
            "output": [r.get("output") for r in ordered],
            "attributes": {"results": ordered},
        }
```

#### 6.1.6 GateNode

Pause execution and wait for external input.

```python
class GateNode(Node):
    def __init__(
        self,
        id: str,
        session: Session,
        prompt: str | Callable[[Any], str],
        options: list[str] | None = None,  # Suggested responses
        timeout: float | None = None,
        validator: Callable[[str], bool] | None = None,
    ): ...

    async def execute(self, context: ExecutionContext) -> dict:
        prompt_text = self._prompt(context.input) if callable(self._prompt) else self._prompt

        # Create response future
        self._response_future = asyncio.Future()

        # Emit gate_waiting event
        context.emit("gate_waiting", {
            "gate_id": self.id,
            "prompt": prompt_text,
            "options": self._options,
            "input_preview": str(context.input)[:200],
        })

        # Wait for response
        try:
            response = await asyncio.wait_for(
                self._response_future,
                timeout=self._timeout,
            ) if self._timeout else await self._response_future
        except asyncio.TimeoutError:
            return {"success": False, "error": "Gate timeout", "output": None}

        # Validate if validator provided
        if self._validator and not self._validator(response):
            return {"success": False, "error": "Invalid response", "output": response}

        context.emit("gate_resolved", {"gate_id": self.id, "response": response})

        return {"success": True, "output": response, "attributes": {"gate_input": response}}

    def receive_input(self, input: str) -> None:
        """Called by WorkflowRuntime when user provides input."""
        if self._response_future and not self._response_future.done():
            self._response_future.set_result(input)
```

### 6.2 Workflow Registration

Workflows are Graphs that use control nodes, registered with session.

```python
# Session gains workflows dict
class Session:
    def __init__(self, ...):
        self.nodes: dict[str, Node] = {}
        self.graphs: dict[str, Graph] = {}
        self.workflows: dict[str, Graph] = {}  # NEW

    def validate_unique_id(self, entity_id: str, entity_type: str) -> None:
        """Validate ID is unique across nodes, graphs, AND workflows."""
        if entity_id in self.nodes:
            raise ValueError(f"... conflicts with existing node ...")
        if entity_id in self.graphs:
            raise ValueError(f"... conflicts with existing graph ...")
        if entity_id in self.workflows:
            raise ValueError(f"... conflicts with existing workflow ...")
```

**Registering a workflow:**

```python
def build_research_workflow(session: Session) -> Graph:
    graph = Graph(id="research_agent", session=session)

    # Add steps with control nodes
    graph.add_step(init_node, step_id="init")
    graph.add_step(while_node, step_id="research_loop", depends_on=["init"])
    graph.add_step(synthesize_node, step_id="synthesize", depends_on=["research_loop"])
    graph.add_step(gate_node, step_id="approve", depends_on=["synthesize"])

    # Register as workflow (enables % prefix in Commander)
    session.workflows[graph.id] = graph

    return graph
```

### 6.3 Event System

Workflows emit events that Commander subscribes to.

```python
# nerve/core/workflow/events.py

class WorkflowEventType(str, Enum):
    # Lifecycle
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    RESUMED = "resumed"
    CANCELLED = "cancelled"

    # Progress
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"

    # Control flow
    LOOP_ITERATION = "loop_iteration"
    BRANCH_TAKEN = "branch_taken"
    MAP_ITEM_START = "map_item_start"
    MAP_ITEM_COMPLETE = "map_item_complete"

    # Interactive
    GATE_WAITING = "gate_waiting"
    GATE_RESOLVED = "gate_resolved"

    # Output
    OUTPUT_CHUNK = "output_chunk"
    LOG = "log"

@dataclass
class WorkflowEvent:
    workflow_id: str
    run_id: str
    event_type: WorkflowEventType
    timestamp: datetime
    data: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }
```

**ExecutionContext gains emit() method:**

```python
class ExecutionContext:
    # ... existing fields ...
    event_sink: EventSink | None = None  # NEW

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a workflow event."""
        if self.event_sink:
            self.event_sink.emit(WorkflowEvent(
                workflow_id=self.workflow_id,
                run_id=self.run_id,
                event_type=WorkflowEventType(event_type),
                timestamp=datetime.now(),
                data=data,
            ))
```

### 6.4 Server Commands

New command types for workflow operations:

```python
class CommandType(str, Enum):
    # ... existing ...

    # Workflow commands
    START_WORKFLOW = "start_workflow"
    STOP_WORKFLOW = "stop_workflow"
    PAUSE_WORKFLOW = "pause_workflow"
    RESUME_WORKFLOW = "resume_workflow"
    WORKFLOW_STATUS = "workflow_status"
    WORKFLOW_INPUT = "workflow_input"
    LIST_WORKFLOWS = "list_workflows"
    SUBSCRIBE_WORKFLOW = "subscribe_workflow"
```

**Handler implementations:**

```python
# nerve/server/handlers/workflow_handler.py

class WorkflowHandler:
    def __init__(self, session_registry: SessionRegistry, event_bus: EventBus):
        self.session_registry = session_registry
        self.event_bus = event_bus
        self.active_runs: dict[str, WorkflowRun] = {}

    async def start_workflow(self, params: dict) -> dict:
        session = self.session_registry.get_session(params.get("session_id"))
        workflow_id = params["workflow_id"]

        workflow = session.workflows.get(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found")

        # Create run
        run_id = f"{workflow_id}-{uuid.uuid4().hex[:8]}"
        run = WorkflowRun(
            run_id=run_id,
            workflow=workflow,
            session=session,
            input=params.get("input"),
            params=params.get("params", {}),
            event_bus=self.event_bus,
        )

        self.active_runs[run_id] = run

        # Start execution (non-blocking)
        asyncio.create_task(self._execute_run(run))

        return {"run_id": run_id, "workflow_id": workflow_id, "status": "started"}

    async def _execute_run(self, run: WorkflowRun) -> None:
        try:
            await run.execute()
        except Exception as e:
            run.emit(WorkflowEventType.FAILED, {"error": str(e)})
        finally:
            del self.active_runs[run.run_id]

    async def workflow_input(self, params: dict) -> dict:
        run_id = params["run_id"]
        gate_id = params["gate_id"]
        input_value = params["input"]

        run = self.active_runs.get(run_id)
        if not run:
            raise ValueError(f"No active run: {run_id}")

        run.send_gate_input(gate_id, input_value)
        return {"status": "input_sent"}

    async def stop_workflow(self, params: dict) -> dict:
        run_id = params["run_id"]
        run = self.active_runs.get(run_id)
        if run:
            await run.cancel()
        return {"status": "stopped"}

    async def subscribe_workflow(self, params: dict) -> AsyncIterator[WorkflowEvent]:
        run_id = params["run_id"]
        async for event in self.event_bus.subscribe(run_id):
            yield event
```

### 6.5 Commander Integration

#### 6.5.1 Input Handler

Routes input based on prefix:

```python
# nerve/commander/input_handler.py

class InputHandler:
    async def handle(self, raw_input: str) -> None:
        raw_input = raw_input.strip()

        # Check if waiting for gate input
        if self.workflow_controller.waiting_for_gate:
            await self.workflow_controller.send_gate_input(raw_input)
            return

        # Route by prefix
        if raw_input.startswith("/"):
            await self._handle_command(raw_input[1:])
        elif raw_input.startswith("%"):
            await self._handle_workflow(raw_input[1:])
        elif raw_input.startswith("@"):
            await self._handle_entity(raw_input[1:])
        else:
            await self._handle_default(raw_input)

    async def _handle_workflow(self, text: str) -> None:
        # Parse: workflow_id [--param=value]... [input]
        parts = text.split(maxsplit=1)
        workflow_id = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

        params, input_text = self._parse_args(rest)

        await self.workflow_controller.start(workflow_id, input_text, params)
```

#### 6.5.2 Workflow Controller

Manages workflow execution from Commander:

```python
# nerve/commander/workflow_controller.py

class WorkflowController:
    def __init__(self, client: SocketClient, renderer: WorkflowRenderer):
        self.client = client
        self.renderer = renderer
        self.active_run_id: str | None = None
        self.waiting_for_gate: str | None = None  # gate_id if waiting

    async def start(
        self,
        workflow_id: str,
        input: str,
        params: dict | None = None,
    ) -> None:
        # Start workflow
        result = await self.client.send_command(Command(
            type=CommandType.START_WORKFLOW,
            params={
                "workflow_id": workflow_id,
                "input": input,
                "params": params or {},
            },
        ))

        if not result.success:
            self.renderer.show_error(result.error)
            return

        self.active_run_id = result.data["run_id"]

        # Subscribe to events
        await self._subscribe()

    async def _subscribe(self) -> None:
        async for event in self.client.subscribe_workflow(self.active_run_id):
            await self._handle_event(event)

            if event.event_type in (WorkflowEventType.COMPLETED,
                                     WorkflowEventType.FAILED,
                                     WorkflowEventType.CANCELLED):
                self.active_run_id = None
                break

    async def _handle_event(self, event: WorkflowEvent) -> None:
        match event.event_type:
            case WorkflowEventType.STARTED:
                self.renderer.show_started(event.data)

            case WorkflowEventType.STEP_STARTED:
                self.renderer.update_step(event.data["step_id"], "running")

            case WorkflowEventType.STEP_COMPLETED:
                self.renderer.update_step(
                    event.data["step_id"],
                    "completed",
                    duration=event.data.get("duration_ms"),
                )

            case WorkflowEventType.LOOP_ITERATION:
                self.renderer.show_iteration(
                    event.data["loop_id"],
                    event.data["iteration"],
                    event.data.get("max"),
                )

            case WorkflowEventType.GATE_WAITING:
                self.waiting_for_gate = event.data["gate_id"]
                self.renderer.show_gate_prompt(event.data)

            case WorkflowEventType.GATE_RESOLVED:
                self.waiting_for_gate = None
                self.renderer.hide_gate_prompt()

            case WorkflowEventType.COMPLETED:
                self.renderer.show_completed(event.data)

            case WorkflowEventType.FAILED:
                self.renderer.show_failed(event.data["error"])

    async def send_gate_input(self, input: str) -> None:
        if not self.waiting_for_gate or not self.active_run_id:
            return

        await self.client.send_command(Command(
            type=CommandType.WORKFLOW_INPUT,
            params={
                "run_id": self.active_run_id,
                "gate_id": self.waiting_for_gate,
                "input": input,
            },
        ))

        self.waiting_for_gate = None

    async def pause(self) -> None:
        if self.active_run_id:
            await self.client.send_command(Command(
                type=CommandType.PAUSE_WORKFLOW,
                params={"run_id": self.active_run_id},
            ))

    async def stop(self) -> None:
        if self.active_run_id:
            await self.client.send_command(Command(
                type=CommandType.STOP_WORKFLOW,
                params={"run_id": self.active_run_id},
            ))
```

#### 6.5.3 Workflow Renderer

Rich TUI for workflow progress:

```python
# nerve/commander/workflow_renderer.py

from rich.console import Console
from rich.live import Live
from rich.tree import Tree
from rich.panel import Panel

class WorkflowRenderer:
    def __init__(self, console: Console):
        self.console = console
        self.live: Live | None = None
        self.tree: Tree | None = None
        self.step_nodes: dict[str, Any] = {}

    def show_started(self, data: dict) -> None:
        workflow_id = data["workflow_id"]
        steps = data.get("steps", [])

        self.tree = Tree(f"🔄 [bold blue]{workflow_id}[/]")
        for step_id in steps:
            node = self.tree.add(f"○ [dim]{step_id}[/]")
            self.step_nodes[step_id] = node

        self.live = Live(
            Panel(self.tree, title="Workflow Progress", border_style="blue"),
            console=self.console,
            refresh_per_second=4,
        )
        self.live.start()

    def update_step(self, step_id: str, status: str, **kwargs) -> None:
        if step_id not in self.step_nodes:
            return

        node = self.step_nodes[step_id]

        if status == "running":
            node.label = f"● [yellow]{step_id}[/]"
        elif status == "completed":
            duration = kwargs.get("duration", 0) / 1000
            node.label = f"✓ [green]{step_id}[/] [dim]({duration:.1f}s)[/]"
        elif status == "failed":
            node.label = f"✗ [red]{step_id}[/]"

    def show_iteration(self, loop_id: str, iteration: int, max_iter: int | None) -> None:
        max_str = f"/{max_iter}" if max_iter else ""
        self.console.print(f"  [dim]↻[/] {loop_id} iteration {iteration}{max_str}")

    def show_gate_prompt(self, data: dict) -> None:
        # Pause live display
        if self.live:
            self.live.stop()

        # Show prompt panel
        prompt = data["prompt"]
        options = data.get("options", [])

        content = prompt
        if options:
            content += "\n\nOptions:\n" + "\n".join(f"  • {opt}" for opt in options)

        self.console.print()
        self.console.print(Panel(
            content,
            title="[bold yellow]⏸ Waiting for Input[/]",
            border_style="yellow",
        ))
        self.console.print()

    def hide_gate_prompt(self) -> None:
        # Resume live display
        if self.live:
            self.live.start()

    def show_completed(self, data: dict) -> None:
        if self.live:
            self.live.stop()

        duration = data.get("duration_s", 0)
        self.console.print()
        self.console.print(Panel(
            f"✓ Completed in {duration:.1f}s",
            title="[bold green]Workflow Complete[/]",
            border_style="green",
        ))

    def show_failed(self, error: str) -> None:
        if self.live:
            self.live.stop()

        self.console.print()
        self.console.print(Panel(
            f"✗ {error}",
            title="[bold red]Workflow Failed[/]",
            border_style="red",
        ))
```

---

## 7. Technical Implementation

### 7.1 File Structure

```
src/nerve/
├── core/
│   ├── nodes/
│   │   ├── control/                      # NEW
│   │   │   ├── __init__.py
│   │   │   ├── base.py                   # ControlNode base class
│   │   │   ├── while_node.py
│   │   │   ├── loop_node.py
│   │   │   ├── branch_node.py
│   │   │   ├── switch_node.py
│   │   │   ├── map_node.py
│   │   │   ├── reduce_node.py
│   │   │   └── gate_node.py
│   │   └── __init__.py                   # Export control nodes
│   │
│   ├── workflow/                         # NEW
│   │   ├── __init__.py
│   │   ├── events.py                     # WorkflowEvent, WorkflowEventType
│   │   ├── run.py                        # WorkflowRun
│   │   └── runtime.py                    # WorkflowRuntime
│   │
│   └── session/
│       └── session.py                    # Add workflows dict
│
├── server/
│   ├── handlers/
│   │   └── workflow_handler.py           # NEW
│   └── protocols/
│       └── commands.py                   # Add workflow commands
│
└── commander/
    ├── input_handler.py                  # Add % prefix routing
    ├── workflow_controller.py            # NEW
    └── workflow_renderer.py              # NEW
```

### 7.2 Implementation Phases

#### Phase 1: Control Nodes (Core)

**Scope**: Implement control nodes that work in Graphs

**Files**:
- `src/nerve/core/nodes/control/*.py`
- `src/nerve/core/nodes/__init__.py` (exports)

**Deliverables**:
1. `WhileNode` - loop while condition true
2. `LoopNode` - loop N times or until condition
3. `BranchNode` - if/else conditional
4. `GateNode` - wait for input (async future)
5. Unit tests for each node

**Validation**:
```python
# Can compose control nodes in graph
graph = Graph(id="test", session=session)
graph.add_step(WhileNode(...), step_id="loop")
result = await graph.execute(context)
assert result["attributes"]["iterations"] == 3
```

#### Phase 2: Event System

**Scope**: Add event emission to ExecutionContext and control nodes

**Files**:
- `src/nerve/core/workflow/events.py`
- `src/nerve/core/nodes/context.py` (add emit method)
- Update control nodes to emit events

**Deliverables**:
1. `WorkflowEvent` dataclass
2. `WorkflowEventType` enum
3. `EventSink` protocol
4. `ExecutionContext.emit()` method
5. Control nodes emit appropriate events

**Validation**:
```python
events = []
context = ExecutionContext(..., event_sink=events.append)
await while_node.execute(context)
assert any(e.event_type == "loop_iteration" for e in events)
```

#### Phase 3: Workflow Registration

**Scope**: Session tracks workflows separately from graphs

**Files**:
- `src/nerve/core/session/session.py`

**Deliverables**:
1. `Session.workflows` dict
2. `Session.validate_unique_id()` checks workflows
3. `Session.register_workflow()` method
4. `Session.get_workflow()` method
5. `Session.list_workflows()` method

**Validation**:
```python
session = Session()
graph = Graph(id="my_workflow", session=session)
session.register_workflow(graph)
assert "my_workflow" in session.workflows
```

#### Phase 4: Server Commands

**Scope**: Add workflow commands to server protocol

**Files**:
- `src/nerve/server/protocols/commands.py`
- `src/nerve/server/handlers/workflow_handler.py`

**Deliverables**:
1. `START_WORKFLOW`, `STOP_WORKFLOW`, etc. command types
2. `WorkflowHandler` class
3. `WorkflowRun` class for execution tracking
4. Event streaming via `SUBSCRIBE_WORKFLOW`

**Validation**:
```python
result = await client.send_command(Command(
    type=CommandType.START_WORKFLOW,
    params={"workflow_id": "test", "input": "hello"},
))
assert result.data["run_id"] is not None
```

#### Phase 5: Commander Integration

**Scope**: Full Commander support for workflows

**Files**:
- `src/nerve/commander/input_handler.py`
- `src/nerve/commander/workflow_controller.py`
- `src/nerve/commander/workflow_renderer.py`

**Deliverables**:
1. `%` prefix routing to workflows
2. `WorkflowController` for lifecycle management
3. `WorkflowRenderer` for Rich TUI
4. Gate input routing
5. `/pause`, `/stop`, `/status` commands

**Validation**:
```
> %research_agent What is Rust?
[progress tree shown]
[gate prompt shown]
> approve
[completion shown]
```

#### Phase 6: MapNode and Advanced Control

**Scope**: Additional control nodes for parallel execution

**Files**:
- `src/nerve/core/nodes/control/map_node.py`
- `src/nerve/core/nodes/control/reduce_node.py`
- `src/nerve/core/nodes/control/switch_node.py`

**Deliverables**:
1. `MapNode` - parallel fan-out
2. `ReduceNode` - aggregate results
3. `SwitchNode` - multi-way branch

---

## 8. API Reference

### 8.1 Control Nodes

```python
# WhileNode
WhileNode(
    id: str,
    session: Session,
    condition: Callable[[WhileState], bool],
    body: Node | Graph,
    max_iterations: int = 100,
)

# LoopNode
LoopNode(
    id: str,
    session: Session,
    body: Node | Graph,
    times: int | None = None,
    until: Callable[[LoopState], bool] | None = None,
    max_iterations: int = 100,
    accumulate: bool = False,
)

# BranchNode
BranchNode(
    id: str,
    session: Session,
    condition: Callable[[Any], bool],
    then_branch: Node | Graph,
    else_branch: Node | Graph | None = None,
)

# GateNode
GateNode(
    id: str,
    session: Session,
    prompt: str | Callable[[Any], str],
    options: list[str] | None = None,
    timeout: float | None = None,
    validator: Callable[[str], bool] | None = None,
)

# MapNode
MapNode(
    id: str,
    session: Session,
    body: Node | Graph,
    max_parallel: int = 5,
)
```

### 8.2 Server Commands

```python
# Start workflow
Command(type=CommandType.START_WORKFLOW, params={
    "session_id": str,          # Optional, defaults to "default"
    "workflow_id": str,         # Required
    "input": Any,               # Input to workflow
    "params": dict[str, Any],   # Optional parameters
})
# Returns: {"run_id": str, "workflow_id": str, "status": "started"}

# Stop workflow
Command(type=CommandType.STOP_WORKFLOW, params={
    "run_id": str,
})
# Returns: {"status": "stopped"}

# Send gate input
Command(type=CommandType.WORKFLOW_INPUT, params={
    "run_id": str,
    "gate_id": str,
    "input": str,
})
# Returns: {"status": "input_sent"}

# List workflows
Command(type=CommandType.LIST_WORKFLOWS, params={
    "session_id": str,  # Optional
})
# Returns: {"workflows": [{"id": str, "description": str}, ...]}
```

### 8.3 Commander Syntax

```
# Start workflow
%workflow_id [--param=value]... [input text]

# Examples
%research_agent What is Rust?
%dev_coach_review --max-rounds=5 Implement auth
%code_review --strict

# Control commands
/workflows              # List available workflows
/status                 # Show active workflow status
/pause                  # Pause active workflow
/resume                 # Resume paused workflow
/stop                   # Stop active workflow
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

```python
# tests/core/nodes/control/test_while_node.py

class TestWhileNode:
    def test_loops_until_condition_false(self):
        """WhileNode loops until condition returns False."""
        session = Session()
        counter = {"value": 0}

        def increment(ctx):
            counter["value"] += 1
            return {"output": counter["value"]}

        body = FunctionNode(id="inc", session=session, fn=increment)

        while_node = WhileNode(
            id="counter_loop",
            session=session,
            condition=lambda state: state.current_value < 5,
            body=body,
        )

        ctx = ExecutionContext(session=session, input=0)
        result = await while_node.execute(ctx)

        assert result["output"] == 5
        assert result["attributes"]["iterations"] == 5

    def test_respects_max_iterations(self):
        """WhileNode stops at max_iterations."""
        # ... test infinite loop protection

    def test_emits_iteration_events(self):
        """WhileNode emits loop_iteration events."""
        events = []
        ctx = ExecutionContext(..., event_sink=lambda e: events.append(e))
        await while_node.execute(ctx)

        iteration_events = [e for e in events if e.event_type == "loop_iteration"]
        assert len(iteration_events) == 5


# tests/core/nodes/control/test_gate_node.py

class TestGateNode:
    async def test_waits_for_input(self):
        """GateNode waits for receive_input call."""
        gate = GateNode(id="approval", session=session, prompt="Approve?")

        async def provide_input():
            await asyncio.sleep(0.1)
            gate.receive_input("yes")

        asyncio.create_task(provide_input())

        ctx = ExecutionContext(session=session, input="data")
        result = await gate.execute(ctx)

        assert result["success"] is True
        assert result["output"] == "yes"

    async def test_timeout(self):
        """GateNode times out if no input."""
        gate = GateNode(id="approval", session=session, prompt="?", timeout=0.1)

        result = await gate.execute(ctx)

        assert result["success"] is False
        assert "timeout" in result["error"].lower()
```

### 9.2 Integration Tests

```python
# tests/integration/test_workflow_commander.py

class TestWorkflowCommander:
    async def test_start_workflow_from_commander(self):
        """Can start workflow with % prefix."""
        # Setup server with workflow
        session = server.get_session()
        build_test_workflow(session)

        # Simulate commander input
        await commander.handle_input("%test_workflow hello")

        # Verify workflow started
        assert commander.workflow_controller.active_run_id is not None

    async def test_gate_interaction(self):
        """Commander can respond to gate prompts."""
        # Start workflow with gate
        await commander.handle_input("%approval_workflow")

        # Wait for gate event
        await asyncio.sleep(0.5)
        assert commander.workflow_controller.waiting_for_gate is not None

        # Send approval
        await commander.handle_input("approve")

        # Verify gate resolved
        assert commander.workflow_controller.waiting_for_gate is None
```

### 9.3 Example Workflow Tests

```python
# tests/examples/test_research_agent.py

class TestResearchAgentWorkflow:
    async def test_full_workflow(self):
        """Research agent workflow completes successfully."""
        session = Session()

        # Mock nodes
        session.nodes["searcher"] = MockNode(responses=["Found: X, Y, Z"])
        session.nodes["evaluator"] = MockNode(responses=["SUFFICIENT"])
        session.nodes["writer"] = MockNode(responses=["Summary: ..."])

        workflow = build_research_workflow(session)

        # Auto-approve gate
        for step in workflow._steps.values():
            if isinstance(step.node, GateNode):
                step.node._auto_approve = True

        ctx = ExecutionContext(session=session, input="What is X?")
        result = await workflow.execute(ctx)

        assert result["success"] is True
        assert "Summary" in result["output"]["answer"]
```

---

## 10. Rollout Plan

### Phase 1: Alpha (Internal)
- Implement core control nodes
- Unit tests passing
- Manual testing with simple workflows
- No Commander integration yet

### Phase 2: Beta (Early Users)
- Full Commander integration
- Event streaming working
- Documentation with examples
- Collect feedback on API

### Phase 3: GA (General Availability)
- All control nodes implemented
- Comprehensive test coverage
- Migration guide for existing Python orchestration
- Performance optimization

---

## 11. Open Questions

| ID | Question | Options | Decision |
|----|----------|---------|----------|
| Q1 | Should workflows auto-register when using control nodes? | (a) Explicit registration (b) Auto-detect | TBD |
| Q2 | Pause/resume: checkpoint to disk? | (a) Memory only (b) Disk persistence | Memory only for v1 |
| Q3 | Should `@` work for workflows too? | (a) `%` only (b) Both `@` and `%` | `%` only - clear separation |
| Q4 | Nested workflow calls? | (a) Allow (b) Disallow for v1 | Allow - they're just Graphs |
| Q5 | YAML workflow definition format? | (a) v1 scope (b) Future | Future |

---

## Appendix A: Example Workflows

### A.1 Research Agent

See `examples/workflows/research_agent.py` in implementation.

### A.2 Dev-Coach-Review

```python
def build_dev_coach_review(session: Session) -> Graph:
    """Dev + Coach + Reviewer collaboration workflow."""

    # Inner loop body: Coach review -> Dev respond
    inner_body = Graph(id="_inner", session=session)
    inner_body.add_step_ref("coach", "review", input_fn=lambda up: up["input"])
    inner_body.add_step(
        BranchNode(
            id="_check_coach",
            session=session,
            condition=lambda inp: "ACCEPTED" not in inp.get("output", ""),
            then_branch=session.get_node("dev"),
        ),
        step_id="respond",
        depends_on=["review"],
    )

    # Inner loop
    inner_loop = WhileNode(
        id="coach_loop",
        session=session,
        condition=lambda s: "ACCEPTED" not in str(s.current_value),
        body=inner_body,
        max_iterations=30,
    )

    # Outer loop body: Inner loop -> Reviewer
    outer_body = Graph(id="_outer", session=session)
    outer_body.add_step(inner_loop, "dev_coach")
    outer_body.add_step_ref("reviewer", "review", depends_on=["dev_coach"])
    outer_body.add_step(
        BranchNode(
            id="_check_reviewer",
            session=session,
            condition=lambda inp: "APPROVED" in inp.get("output", ""),
            then_branch=FunctionNode(id="_done", session=session, fn=lambda c: {"done": True}),
            else_branch=session.get_node("coach"),  # Process feedback
        ),
        step_id="decide",
        depends_on=["review"],
    )

    # Main workflow
    workflow = Graph(id="dev_coach_review", session=session)
    workflow.add_step_ref("dev", "initial", input_fn=lambda up: up.get("input"))
    workflow.add_step(
        WhileNode(
            id="outer_loop",
            session=session,
            condition=lambda s: not s.current_value.get("done"),
            body=outer_body,
            max_iterations=10,
        ),
        step_id="collaboration",
        depends_on=["initial"],
    )
    workflow.add_step(
        GateNode(
            id="final_approval",
            session=session,
            prompt="Workflow complete. Approve to merge?",
        ),
        step_id="approve",
        depends_on=["collaboration"],
    )

    session.register_workflow(workflow)
    return workflow
```

---

## Appendix B: Migration Guide

### From Python Orchestration to Workflow

**Before** (manual Python):
```python
while not done:
    result = await client.send_command(...)
    if "ACCEPTED" in result:
        done = True
```

**After** (workflow):
```python
WhileNode(
    condition=lambda s: "ACCEPTED" not in str(s.current_value),
    body=review_node,
)
```

### Key Mappings

| Python Pattern | Control Node |
|----------------|--------------|
| `while condition:` | `WhileNode` |
| `for i in range(n):` | `LoopNode(times=n)` |
| `if x: ... else: ...` | `BranchNode` |
| `match x: case ...:` | `SwitchNode` |
| `input()` / `await approval` | `GateNode` |
| `asyncio.gather(...)` | `MapNode` |

---

*End of PRD*
