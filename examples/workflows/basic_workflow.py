"""Example: Basic Workflow Usage.

This example demonstrates how to create and execute workflows
with control flow, gates, and event emission.

Workflows are async Python functions that can:
- Execute nodes with ctx.run()
- Pause for human input with ctx.gate()
- Emit events with ctx.emit()
- Use loops and conditionals for complex control flow
"""

import asyncio

from nerve.core.nodes.base import FunctionNode
from nerve.core.session import Session
from nerve.core.workflow import Workflow, WorkflowContext, WorkflowRun, WorkflowState


async def main():
    # Create session
    session = Session(name="workflow-example")

    # =========================================================================
    # Example 1: Simple Workflow
    # =========================================================================
    print("=" * 60)
    print("Example 1: Simple Workflow")
    print("=" * 60)

    # Create a simple node that uppercases input
    FunctionNode(
        id="upper",
        session=session,
        fn=lambda ctx: ctx.input.upper(),
    )

    # Define a simple workflow
    async def simple_workflow(ctx: WorkflowContext) -> str:
        """A simple workflow that processes input through a node."""
        result = await ctx.run("upper", ctx.input)
        return f"Processed: {result['output']}"

    # Register workflow
    Workflow(id="simple", session=session, fn=simple_workflow)

    # Execute workflow
    workflow = session.get_workflow("simple")
    run = WorkflowRun(workflow=workflow, input="hello world")

    await run.start()
    result = await run.wait()

    print("Input: hello world")
    print(f"Output: {result}")
    print(f"State: {run.state.value}")

    # =========================================================================
    # Example 2: Workflow with Multiple Nodes
    # =========================================================================
    print("\n" + "=" * 60)
    print("Example 2: Workflow with Multiple Nodes (Pipeline)")
    print("=" * 60)

    # Create nodes for a pipeline
    FunctionNode(
        id="step1",
        session=session,
        fn=lambda ctx: f"[step1: {ctx.input}]",
    )
    FunctionNode(
        id="step2",
        session=session,
        fn=lambda ctx: f"[step2: {ctx.input}]",
    )
    FunctionNode(
        id="step3",
        session=session,
        fn=lambda ctx: f"[step3: {ctx.input}]",
    )

    async def pipeline_workflow(ctx: WorkflowContext) -> str:
        """Chain multiple nodes together."""
        r1 = await ctx.run("step1", ctx.input)
        ctx.emit("step_complete", {"step": 1, "output": r1["output"]})

        r2 = await ctx.run("step2", r1["output"])
        ctx.emit("step_complete", {"step": 2, "output": r2["output"]})

        r3 = await ctx.run("step3", r2["output"])
        ctx.emit("step_complete", {"step": 3, "output": r3["output"]})

        return r3["output"]

    Workflow(id="pipeline", session=session, fn=pipeline_workflow)

    run = WorkflowRun(workflow=session.get_workflow("pipeline"), input="data")
    await run.start()
    result = await run.wait()

    print("Input: data")
    print(f"Output: {result}")

    # =========================================================================
    # Example 3: Workflow with Conditional Logic
    # =========================================================================
    print("\n" + "=" * 60)
    print("Example 3: Workflow with Conditional Logic")
    print("=" * 60)

    # Create nodes for different paths
    FunctionNode(
        id="validator",
        session=session,
        fn=lambda ctx: {"valid": len(ctx.input) > 3, "input": ctx.input},
    )
    FunctionNode(
        id="process-valid",
        session=session,
        fn=lambda ctx: f"Processed valid input: {ctx.input}",
    )
    FunctionNode(
        id="process-invalid",
        session=session,
        fn=lambda ctx: f"Rejected: {ctx.input} (too short)",
    )

    async def conditional_workflow(ctx: WorkflowContext) -> str:
        """Workflow with conditional branching."""
        validation = await ctx.run("validator", ctx.input)
        result = validation["output"]

        if result["valid"]:
            ctx.emit("path_taken", {"path": "valid"})
            processed = await ctx.run("process-valid", result["input"])
        else:
            ctx.emit("path_taken", {"path": "invalid"})
            processed = await ctx.run("process-invalid", result["input"])

        return processed["output"]

    Workflow(id="conditional", session=session, fn=conditional_workflow)

    # Test with valid input
    run = WorkflowRun(workflow=session.get_workflow("conditional"), input="hello")
    await run.start()
    result = await run.wait()
    print(f"Input 'hello': {result}")

    # Test with invalid input
    run = WorkflowRun(workflow=session.get_workflow("conditional"), input="hi")
    await run.start()
    result = await run.wait()
    print(f"Input 'hi': {result}")

    # =========================================================================
    # Example 4: Workflow with Loop
    # =========================================================================
    print("\n" + "=" * 60)
    print("Example 4: Workflow with Loop")
    print("=" * 60)

    # Create an incrementing node
    FunctionNode(
        id="increment",
        session=session,
        fn=lambda ctx: ctx.input + 1,
    )

    async def loop_workflow(ctx: WorkflowContext) -> int:
        """Workflow that loops until a condition is met."""
        target = ctx.params.get("target", 5)
        current = ctx.input

        iterations = 0
        while current < target:
            result = await ctx.run("increment", current)
            current = result["output"]
            iterations += 1
            ctx.emit("iteration", {"count": iterations, "value": current})

        ctx.state["iterations"] = iterations
        return current

    Workflow(id="loop", session=session, fn=loop_workflow)

    run = WorkflowRun(
        workflow=session.get_workflow("loop"),
        input=0,
        params={"target": 5},
    )
    await run.start()
    result = await run.wait()

    print("Started at 0, target 5")
    print(f"Final value: {result}")

    # =========================================================================
    # Example 5: Workflow with State
    # =========================================================================
    print("\n" + "=" * 60)
    print("Example 5: Workflow with Persistent State")
    print("=" * 60)

    FunctionNode(
        id="accumulate",
        session=session,
        fn=lambda ctx: ctx.input,
    )

    async def stateful_workflow(ctx: WorkflowContext) -> dict:
        """Workflow that maintains state across operations."""
        ctx.state["history"] = []
        ctx.state["sum"] = 0

        for item in ctx.input:
            result = await ctx.run("accumulate", item)
            value = result["output"]
            ctx.state["history"].append(value)
            ctx.state["sum"] += value
            ctx.emit("accumulated", {"value": value, "sum": ctx.state["sum"]})

        return {
            "history": ctx.state["history"],
            "sum": ctx.state["sum"],
            "count": len(ctx.state["history"]),
        }

    Workflow(id="stateful", session=session, fn=stateful_workflow)

    run = WorkflowRun(
        workflow=session.get_workflow("stateful"),
        input=[1, 2, 3, 4, 5],
    )
    await run.start()
    result = await run.wait()

    print("Input: [1, 2, 3, 4, 5]")
    print(f"Result: {result}")

    # =========================================================================
    # Example 6: Workflow with Event Capture
    # =========================================================================
    print("\n" + "=" * 60)
    print("Example 6: Capturing Workflow Events")
    print("=" * 60)

    events_captured = []

    async def event_callback(event):
        events_captured.append(event)

    async def event_workflow(ctx: WorkflowContext) -> str:
        """Workflow that emits various events."""
        ctx.emit("started", {"input": ctx.input})

        result = await ctx.run("upper", ctx.input)
        ctx.emit("processed", {"output": result["output"]})

        ctx.emit("finished", {"success": True})
        return result["output"]

    Workflow(id="evented", session=session, fn=event_workflow)

    run = WorkflowRun(
        workflow=session.get_workflow("evented"),
        input="test",
        event_callback=event_callback,
    )
    await run.start()
    await run.wait()

    print("Events captured:")
    for event in events_captured:
        print(f"  - {event.event_type}: {event.data}")

    # =========================================================================
    # Example 7: Workflow Error Handling
    # =========================================================================
    print("\n" + "=" * 60)
    print("Example 7: Error Handling")
    print("=" * 60)

    async def error_workflow(ctx: WorkflowContext) -> str:
        """Workflow that handles errors gracefully."""
        try:
            # This will fail - node doesn't exist
            await ctx.run("nonexistent", "input")
        except ValueError as e:
            ctx.emit("error_caught", {"error": str(e)})
            return f"Handled error: {e}"

    Workflow(id="error-handler", session=session, fn=error_workflow)

    run = WorkflowRun(workflow=session.get_workflow("error-handler"), input="test")
    await run.start()
    result = await run.wait()

    print(f"Result: {result}")

    # =========================================================================
    # Example 8: Cancellation
    # =========================================================================
    print("\n" + "=" * 60)
    print("Example 8: Workflow Cancellation")
    print("=" * 60)

    async def slow_workflow(ctx: WorkflowContext) -> str:
        """A workflow that can be cancelled."""
        ctx.emit("starting", {})
        await asyncio.sleep(10)  # Simulate long operation
        return "completed"

    Workflow(id="slow", session=session, fn=slow_workflow)

    run = WorkflowRun(workflow=session.get_workflow("slow"), input=None)
    await run.start()

    # Cancel after a short delay
    await asyncio.sleep(0.1)
    await run.cancel()

    print(f"State after cancel: {run.state.value}")
    assert run.state == WorkflowState.CANCELLED

    # Cleanup
    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
