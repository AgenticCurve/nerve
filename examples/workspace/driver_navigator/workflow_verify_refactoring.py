"""Verify Refactoring workflow - ensure refactored code preserves behavior.

This workflow:
1. Spins up a fresh ClaudeWezTermNode for each execution
2. Sends the verify-refactoring.md prompt for regression detection
3. Loops asking "are you sure?" until the AI confirms with exit token
4. Cleans up the node (unless DEBUG env is set)
"""

import os
from pathlib import Path

from nerve.core.nodes.terminal import ClaudeWezTermNode
from nerve.core.workflow import WorkflowContext

# Exit token - AI must output this to confirm verification complete
EXIT_TOKEN = "8934323431"

# Max iterations to prevent infinite loops
MAX_ITERATIONS = 10

# Path to verify-refactoring prompt (relative to repo root)
VERIFY_REFACTORING_PROMPT_PATH = (
    Path(__file__).parent.parent.parent.parent / "prompts" / "refactoring" / "verify-refactoring.md"
)

# Follow-up prompt for each iteration
FOLLOWUP_PROMPT = """Have you done a complete and thorough verification or is there something you left by mistake or on purpose?

Do another round just to be sure. Check for:
- Dropped code paths
- Changed default values
- Lost error handling
- Broken imports
- Changed string literals
- Lost special cases

If you're 100% sure there are NO REGRESSIONS then reply with token 8934323431 in your output."""


async def verify_refactoring_workflow(ctx: WorkflowContext) -> dict[str, object]:
    """Verify refactoring workflow with multiple verification rounds.

    Args:
        ctx: Workflow context with optional input (description of refactoring to verify)

    Returns:
        dict with verification results and iteration count
    """
    cwd = os.getcwd()
    run_id = ctx._run.run_id if ctx._run else "unknown"
    node_id = f"verify-refactor-{run_id[:8]}"

    ctx.emit("setup", {"message": f"Creating verification node: {node_id}"})

    # Create a fresh ClaudeWezTermNode for this workflow run
    node = await ClaudeWezTermNode.create(
        id=node_id,
        session=ctx.session,
        command=f"cd {cwd} && claude --dangerously-skip-permissions",
    )

    ctx.emit("node_created", {"node_id": node_id, "cwd": cwd})

    try:
        # Read the verify-refactoring prompt
        if VERIFY_REFACTORING_PROMPT_PATH.exists():
            verify_prompt = VERIFY_REFACTORING_PROMPT_PATH.read_text(encoding="utf-8")
        else:
            ctx.emit(
                "warning", {"message": f"Prompt file not found: {VERIFY_REFACTORING_PROMPT_PATH}"}
            )
            verify_prompt = "{{CONTEXT}}\n\nVerify that the refactored code produces identical behavior to the original."

        # Replace {{CONTEXT}} with user input (or empty string if none)
        context = ctx.input if ctx.input else ""
        initial_prompt = verify_prompt.replace("{{CONTEXT}}", context)

        # Send initial prompt
        ctx.emit("verification_started", {"iteration": 1, "type": "initial"})
        result = await ctx.run(node_id, initial_prompt)

        if not result.get("success"):
            return {
                "status": "error",
                "error": result.get("error", "Initial verification failed"),
                "iterations": 1,
            }

        output = result.get("output", "")
        ctx.state["iterations"] = 1
        ctx.state["outputs"] = [output]

        # Check if exit token is already present
        if EXIT_TOKEN in output:
            ctx.emit("verification_complete", {"iterations": 1, "found_token": True})
            return {
                "status": "completed",
                "iterations": 1,
                "final_output": output,
                "outputs": ctx.state["outputs"],
            }

        # Loop with follow-up prompts
        for i in range(2, MAX_ITERATIONS + 1):
            ctx.emit("verification_started", {"iteration": i, "type": "followup"})

            result = await ctx.run(node_id, FOLLOWUP_PROMPT)

            if not result.get("success"):
                ctx.emit(
                    "warning", {"message": f"Iteration {i} failed", "error": result.get("error")}
                )
                continue

            output = result.get("output", "")
            ctx.state["iterations"] = i
            ctx.state["outputs"].append(output)

            # Check for exit token
            if EXIT_TOKEN in output:
                ctx.emit("verification_complete", {"iterations": i, "found_token": True})
                return {
                    "status": "completed",
                    "iterations": i,
                    "final_output": output,
                    "outputs": ctx.state["outputs"],
                }

            ctx.emit("iteration_complete", {"iteration": i, "found_token": False})

        # Max iterations reached
        ctx.emit("max_iterations_reached", {"iterations": MAX_ITERATIONS})
        return {
            "status": "max_iterations",
            "iterations": MAX_ITERATIONS,
            "outputs": ctx.state["outputs"],
        }

    finally:
        # Cleanup: stop and remove node (unless DEBUG is set)
        debug_mode = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")

        if debug_mode:
            ctx.emit("cleanup_skipped", {"node_id": node_id, "reason": "DEBUG mode"})
        else:
            ctx.emit("cleanup", {"node_id": node_id})
            await node.stop()
            # Remove from session
            if node_id in ctx.session.nodes:
                del ctx.session.nodes[node_id]
