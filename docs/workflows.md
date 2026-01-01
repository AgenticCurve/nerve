# Nerve Workflows

Workflows are async Python functions that orchestrate node execution with full control flow capabilities. Unlike graphs (which are DAGs with static dependencies), workflows support loops, conditionals, and human-in-the-loop gates.

## Quick Start

```python
from nerve.core.session import Session
from nerve.core.workflow import Workflow, WorkflowContext, WorkflowRun

# Create session and nodes
session = Session(name="my-session")

# Define a workflow function
async def my_workflow(ctx: WorkflowContext) -> str:
    # Execute a node
    result = await ctx.run("my-node", ctx.input)

    # Ask human for approval
    answer = await ctx.gate("Approve this result?", choices=["yes", "no"])

    if answer == "yes":
        return result["output"]
    else:
        return "Rejected"

# Register workflow
Workflow(id="my-workflow", session=session, fn=my_workflow)

# Execute workflow
workflow = session.get_workflow("my-workflow")
run = WorkflowRun(workflow=workflow, input="hello")
await run.start()
result = await run.wait()
```

## WorkflowContext API

The `WorkflowContext` provides three main methods:

### ctx.run(node_id, input, timeout=None)

Execute a node and wait for its result.

```python
async def my_workflow(ctx: WorkflowContext):
    # Execute a single node
    result = await ctx.run("claude", "What is 2+2?")
    output = result["output"]  # Node's output

    # Chain multiple nodes
    r1 = await ctx.run("summarizer", ctx.input)
    r2 = await ctx.run("translator", r1["output"])
    return r2["output"]
```

### ctx.gate(prompt, timeout=None, choices=None)

Pause workflow and wait for human input.

```python
async def approval_workflow(ctx: WorkflowContext):
    # Simple text input
    name = await ctx.gate("Enter your name:")

    # Multiple choice
    action = await ctx.gate(
        "What would you like to do?",
        choices=["continue", "retry", "cancel"]
    )

    if action == "continue":
        return f"Hello, {name}!"
    elif action == "retry":
        # Loop back...
```

### ctx.emit(event_type, data=None)

Emit an event (for monitoring/logging).

```python
async def tracked_workflow(ctx: WorkflowContext):
    ctx.emit("started", {"input": ctx.input})

    result = await ctx.run("processor", ctx.input)
    ctx.emit("processed", {"output": result["output"]})

    ctx.emit("completed", {"success": True})
    return result["output"]
```

## Context Properties

- `ctx.input` - The input passed to the workflow
- `ctx.params` - Optional parameters dict passed at execution time
- `ctx.state` - Mutable dict for workflow state (persists across the run)
- `ctx.session` - The Session object (for advanced use)

## Control Flow Examples

### Loops

```python
async def retry_workflow(ctx: WorkflowContext):
    max_attempts = ctx.params.get("max_attempts", 3)

    for attempt in range(max_attempts):
        result = await ctx.run("processor", ctx.input)

        if result["output"].get("success"):
            return result["output"]

        ctx.emit("retry", {"attempt": attempt + 1})

    raise RuntimeError("Max attempts exceeded")
```

### Conditionals

```python
async def routing_workflow(ctx: WorkflowContext):
    # Classify input
    classification = await ctx.run("classifier", ctx.input)
    category = classification["output"]

    # Route to appropriate handler
    if category == "urgent":
        return await ctx.run("urgent-handler", ctx.input)
    elif category == "normal":
        return await ctx.run("normal-handler", ctx.input)
    else:
        return await ctx.run("default-handler", ctx.input)
```

### Human-in-the-Loop

```python
async def review_workflow(ctx: WorkflowContext):
    while True:
        # Get AI review
        review = await ctx.run("reviewer", ctx.input)

        # Present to human
        decision = await ctx.gate(
            f"Review: {review['output']}\n\nApprove?",
            choices=["approve", "request_changes", "reject"]
        )

        if decision == "approve":
            return {"status": "approved", "review": review["output"]}
        elif decision == "reject":
            return {"status": "rejected"}
        else:
            # Loop continues with feedback
            ctx.input = f"{ctx.input}\n\nFeedback: Please revise"
```

## Workflow States

A WorkflowRun progresses through these states:

- `PENDING` - Created but not started
- `RUNNING` - Actively executing
- `WAITING` - Paused at a gate, waiting for input
- `COMPLETED` - Finished successfully
- `FAILED` - Terminated with an error
- `CANCELLED` - Manually cancelled

## Running Workflows

### Programmatically

```python
from nerve.core.workflow import WorkflowRun

# Create run
run = WorkflowRun(
    workflow=session.get_workflow("my-workflow"),
    input="hello",
    params={"max_retries": 3},
)

# Start execution
await run.start()

# Check state
if run.state == WorkflowState.WAITING:
    print(f"Gate: {run.pending_gate.prompt}")
    run.answer_gate("yes")

# Wait for completion
result = await run.wait()
```

### In Commander

Use the `%` prefix to execute workflows:

```
%my-workflow Hello, please process this
```

When a gate is encountered, Commander prompts for input:

```
⏸ Gate: Approve this result?
  1. yes
  2. no
gate> 1
```

## Loading Workflows from Files

Since workflows are Python functions, they need to be registered with the session. You can define workflows in separate `.py` files and load them.

### Workflow File Format

Create a Python file that defines workflow functions and registers them. The `session` variable is automatically available:

```python
# my_workflows.py
from nerve.core.workflow import Workflow, WorkflowContext

async def hello(ctx: WorkflowContext) -> str:
    return f"Hello, {ctx.input}!"

async def process(ctx: WorkflowContext) -> str:
    result = await ctx.run("my-node", ctx.input)
    return result["output"]

# Register with session (session is injected automatically)
Workflow(id="hello", session=session, fn=hello)
Workflow(id="process", session=session, fn=process)

print("Loaded 2 workflows")  # Optional: confirmation message
```

### Loading in Commander

Use the `:load` command:

```
:load my_workflows.py              # Load single file
:load workflows/*.py               # Load with glob pattern
:load file1.py file2.py            # Load multiple files
```

After loading, workflows appear in `:workflows` and can be executed with `%workflow_id`.

### Loading via CLI

Use the `nerve server workflow load` command:

```bash
nerve server workflow load my_workflows.py
nerve server workflow load workflows/*.py
nerve server workflow load file1.py file2.py --session my-workspace
```

List registered workflows:

```bash
nerve server workflow list
nerve server workflow list --json
```

### Example Loadable Workflow

See `examples/workflows/simple_loadable.py` for a complete example that can be loaded directly.

## Server Commands

Workflows are exposed via these server commands:

- `EXECUTE_WORKFLOW` - Start a workflow
- `LIST_WORKFLOWS` - List registered workflows
- `GET_WORKFLOW_RUN` - Get run status
- `LIST_WORKFLOW_RUNS` - List runs (optionally filtered)
- `ANSWER_GATE` - Answer a pending gate
- `CANCEL_WORKFLOW` - Cancel a running workflow

## Best Practices

1. **Keep workflows focused** - Each workflow should have a single responsibility
2. **Use gates sparingly** - Too many gates makes workflows tedious
3. **Emit meaningful events** - Helps with debugging and monitoring
4. **Handle errors gracefully** - Use try/except around ctx.run() calls
5. **Use ctx.state for persistence** - Don't rely on local variables across gates

## Examples

See the `examples/workflows/` directory for complete examples:

- `basic_workflow.py` - Core concepts (run, state, events, loops)
- `code_review_workflow.py` - Interactive review with gates
- `simple_loadable.py` - Minimal loadable workflow file format

## Comparison: Workflows vs Graphs

| Feature | Workflows | Graphs |
|---------|-----------|--------|
| Control flow | Full Python (loops, conditionals) | Static DAG |
| Human input | Gates (pause and wait) | Not supported |
| Definition | Async function | Step declarations |
| Dependencies | Explicit in code | Declared via depends_on |
| Use case | Interactive, complex logic | Parallel pipelines |
