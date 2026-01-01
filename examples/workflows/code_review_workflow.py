"""Example: Code Review Workflow with Gates.

This example demonstrates a realistic workflow that:
- Uses gates to pause for human input
- Loops until a condition is met
- Coordinates multiple nodes for a review process

This is designed to work with LLM nodes (Claude, etc.) but uses
FunctionNode mocks for standalone testing.

Usage with real LLM nodes:
    1. Start a nerve server: nerve server start
    2. Create Claude nodes: nerve server node create reviewer --command claude
    3. Register this workflow via Python execution
    4. Execute in Commander: %code_review <your code here>
"""

import asyncio

from nerve.core.nodes.base import FunctionNode
from nerve.core.session import Session
from nerve.core.workflow import Workflow, WorkflowContext, WorkflowRun


async def main():
    """Run the code review workflow example."""
    session = Session(name="code-review-example")

    # =========================================================================
    # Setup: Create mock nodes that simulate LLM behavior
    # =========================================================================
    # In production, these would be real LLM nodes (ClaudeNode, etc.)

    review_count = {"n": 0}

    def mock_reviewer(ctx):
        """Mock reviewer that finds issues on first pass, approves on second."""
        review_count["n"] += 1
        # ctx.input contains the code to review

        if review_count["n"] == 1:
            return {
                "approved": False,
                "issues": [
                    "Missing docstring",
                    "Variable 'x' should be more descriptive",
                    "Consider adding type hints",
                ],
                "summary": "Found 3 issues in the code. Please address them.",
            }
        else:
            return {
                "approved": True,
                "issues": [],
                "summary": "Code looks good! All issues addressed.",
            }

    def mock_editor(ctx):
        """Mock editor that 'fixes' code based on feedback."""
        return f"# Fixed code with improvements\n{ctx.input}\n# Issues addressed"

    FunctionNode(id="reviewer", session=session, fn=mock_reviewer)
    FunctionNode(id="editor", session=session, fn=mock_editor)

    # =========================================================================
    # Define the Code Review Workflow
    # =========================================================================

    async def code_review_workflow(ctx: WorkflowContext) -> dict:
        """Interactive code review workflow with human gates.

        This workflow:
        1. Sends code to a reviewer node
        2. Presents review to human via gate
        3. Human can approve, reject, or request edits
        4. If editing, sends to editor node and loops back

        Args:
            ctx: Workflow context with code as input

        Returns:
            dict with final review status and history
        """
        code = ctx.input
        ctx.state["iterations"] = 0
        ctx.state["history"] = []

        max_iterations = ctx.params.get("max_iterations", 5)

        while ctx.state["iterations"] < max_iterations:
            ctx.state["iterations"] += 1
            iteration = ctx.state["iterations"]

            # Step 1: Get review from reviewer node
            ctx.emit("review_started", {"iteration": iteration})

            review_result = await ctx.run("reviewer", code)
            review = review_result["output"]

            ctx.emit(
                "review_complete",
                {
                    "iteration": iteration,
                    "approved": review.get("approved", False),
                    "issues": review.get("issues", []),
                },
            )

            # Record in history
            ctx.state["history"].append(
                {
                    "iteration": iteration,
                    "review": review,
                    "action": None,  # Will be filled after gate
                }
            )

            # Step 2: Present to human via gate
            if review.get("approved"):
                prompt = (
                    f"Review #{iteration}: APPROVED\n{review['summary']}\n\nAccept this review?"
                )
                choices = ["accept", "request_more_review"]
            else:
                issues_text = "\n".join(f"  - {issue}" for issue in review.get("issues", []))
                prompt = (
                    f"Review #{iteration}: NEEDS WORK\n"
                    f"{review['summary']}\n\n"
                    f"Issues:\n{issues_text}\n\n"
                    f"What would you like to do?"
                )
                choices = ["fix_and_retry", "accept_anyway", "reject"]

            # Gate pauses workflow and waits for human input
            decision = await ctx.gate(prompt, choices=choices)

            # Record decision
            ctx.state["history"][-1]["action"] = decision

            ctx.emit(
                "decision_made",
                {
                    "iteration": iteration,
                    "decision": decision,
                },
            )

            # Step 3: Handle decision
            if decision == "accept" or decision == "accept_anyway":
                return {
                    "status": "accepted",
                    "final_code": code,
                    "iterations": iteration,
                    "history": ctx.state["history"],
                }

            elif decision == "reject":
                return {
                    "status": "rejected",
                    "final_code": None,
                    "iterations": iteration,
                    "history": ctx.state["history"],
                }

            elif decision == "fix_and_retry":
                # Send to editor for fixes
                ctx.emit("editing_started", {"iteration": iteration})

                # Prepare context for editor
                feedback = "\n".join(review.get("issues", []))
                edit_input = f"Fix these issues:\n{feedback}\n\nCode:\n{code}"

                edit_result = await ctx.run("editor", edit_input)
                code = edit_result["output"]

                ctx.emit("editing_complete", {"iteration": iteration})
                # Loop continues with updated code

            elif decision == "request_more_review":
                # Just loop again with same code
                pass

        # Max iterations reached
        return {
            "status": "max_iterations",
            "final_code": code,
            "iterations": max_iterations,
            "history": ctx.state["history"],
        }

    # Register the workflow
    Workflow(
        id="code_review",
        session=session,
        fn=code_review_workflow,
        description="Interactive code review with human approval gates",
    )

    # =========================================================================
    # Run the workflow with simulated gate responses
    # =========================================================================
    print("=" * 60)
    print("Code Review Workflow Demo")
    print("=" * 60)
    print()
    print("This demo simulates a code review workflow.")
    print("In production, gates would pause and wait for user input.")
    print()

    # For demo purposes, we'll manually drive the workflow
    workflow = session.get_workflow("code_review")

    sample_code = """
def calculate(x):
    return x * 2
"""

    print(f"Submitting code for review:\n{sample_code}")
    print("-" * 40)

    # Create run with event tracking
    events = []

    async def capture_events(event):
        events.append(event)
        print(f"[EVENT] {event.event_type}: {event.data}")

    run = WorkflowRun(
        workflow=workflow,
        input=sample_code,
        params={"max_iterations": 3},
        event_callback=capture_events,
    )

    # Register with session for gate answering
    session.register_workflow_run(run)

    # Start the workflow
    await run.start()

    # Wait for first gate
    while run.state.value == "running":
        await asyncio.sleep(0.01)

    print()
    print("-" * 40)
    print("Workflow paused at gate!")
    print(f"Gate prompt: {run.pending_gate.prompt}")
    print(f"Choices: {run.pending_gate.choices}")
    print()

    # Simulate user choosing "fix_and_retry"
    print("User selects: fix_and_retry")
    run.answer_gate("fix_and_retry")

    # Wait for next gate
    while run.state.value == "running":
        await asyncio.sleep(0.01)

    print()
    print("-" * 40)
    print("Workflow paused at gate again!")
    print(f"Gate prompt: {run.pending_gate.prompt}")
    print(f"Choices: {run.pending_gate.choices}")
    print()

    # Simulate user accepting
    print("User selects: accept")
    run.answer_gate("accept")

    # Wait for completion
    result = await run.wait()

    print()
    print("=" * 60)
    print("Workflow Complete!")
    print("=" * 60)
    print(f"Status: {result['status']}")
    print(f"Iterations: {result['iterations']}")
    print(f"Final code:\n{result['final_code']}")

    # =========================================================================
    # Show how to use in Commander
    # =========================================================================
    print()
    print("=" * 60)
    print("Using in Commander")
    print("=" * 60)
    print("""
To use this workflow in Commander with real LLM nodes:

1. Start server and create nodes:
   $ nerve server start
   $ nerve server node create reviewer --command claude
   $ nerve server node create editor --command claude

2. Register workflow via Python execution in Commander:
   >>> from nerve.core.workflow import Workflow, WorkflowContext
   >>> async def code_review(ctx: WorkflowContext) -> dict:
   ...     # (paste workflow code here)
   ...     pass
   >>> Workflow(id="code_review", session=session, fn=code_review)

3. Execute the workflow:
   %code_review def my_function(): pass

4. Respond to gates when prompted:
   Gate: Review #1: NEEDS WORK...
   gate> fix_and_retry

5. Final result is shown in the timeline block.
""")


if __name__ == "__main__":
    asyncio.run(main())
