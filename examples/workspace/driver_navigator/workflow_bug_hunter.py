"""Bug Hunter workflow - thorough code analysis with multiple rounds.

This workflow:
1. Spins up a fresh ClaudeWezTermNode for each execution
2. Sends the bug-hunter.md prompt for initial analysis
3. Loops asking "are you sure?" until the AI confirms with exit token
4. Cleans up the node (unless DEBUG env is set)
"""

import os
from pathlib import Path

from nerve.core.nodes.terminal import ClaudeWezTermNode
from nerve.core.workflow import WorkflowContext

# Exit token - AI must output this to confirm no more bugs
EXIT_TOKEN = "8934323431"

# Max iterations to prevent infinite loops
MAX_ITERATIONS = 10

# Path to bug-hunter prompt (relative to repo root)
BUG_HUNTER_PROMPT_PATH = (
    Path(__file__).parent.parent.parent.parent / "prompts" / "refactoring" / "bug-hunter.md"
)

# Follow-up prompt for each iteration
FOLLOWUP_PROMPT = """Have you done a complete and thorough analysis or is there something you left by mistake or on purpose?

Do another round just to be sure. Look for edge cases, race conditions, resource leaks, and security issues.

If you're 100% sure there are NO MORE BUGS then reply with token 8934323431 in your output."""


async def bug_hunter_workflow(ctx: WorkflowContext) -> dict[str, object]:
    """Bug hunting workflow with multiple analysis rounds.

    Args:
        ctx: Workflow context with optional input (file/directory to analyze)

    Returns:
        dict with analysis results and iteration count
    """
    cwd = os.getcwd()
    run_id = ctx._run.run_id if ctx._run else "unknown"
    node_id = f"bug-hunter-{run_id[:8]}"

    ctx.emit("setup", {"message": f"Creating bug hunter node: {node_id}"})

    # Create a fresh ClaudeWezTermNode for this workflow run
    node = await ClaudeWezTermNode.create(
        id=node_id,
        session=ctx.session,
        command=f"cd {cwd} && claude --dangerously-skip-permissions",
    )

    ctx.emit("node_created", {"node_id": node_id, "cwd": cwd})

    try:
        # Read the bug-hunter prompt
        if BUG_HUNTER_PROMPT_PATH.exists():
            bug_hunter_prompt = BUG_HUNTER_PROMPT_PATH.read_text(encoding="utf-8")
        else:
            ctx.emit("warning", {"message": f"Prompt file not found: {BUG_HUNTER_PROMPT_PATH}"})
            bug_hunter_prompt = (
                "{{CONTEXT}}\n\nAnalyze the codebase for bugs, edge cases, and issues."
            )

        # Replace {{CONTEXT}} with user input (or empty string if none)
        context = ctx.input if ctx.input else ""
        initial_prompt = bug_hunter_prompt.replace("{{CONTEXT}}", context)

        # Send initial prompt
        ctx.emit("analysis_started", {"iteration": 1, "type": "initial"})
        result = await ctx.run(node_id, initial_prompt)

        if not result.get("success"):
            return {
                "status": "error",
                "error": result.get("error", "Initial analysis failed"),
                "iterations": 1,
            }

        output = result.get("output", "")
        ctx.state["iterations"] = 1
        ctx.state["outputs"] = [output]

        # Check if exit token is already present
        if EXIT_TOKEN in output:
            ctx.emit("analysis_complete", {"iterations": 1, "found_token": True})
            return {
                "status": "completed",
                "iterations": 1,
                "final_output": output,
                "outputs": ctx.state["outputs"],
            }

        # Loop with follow-up prompts
        for i in range(2, MAX_ITERATIONS + 1):
            ctx.emit("analysis_started", {"iteration": i, "type": "followup"})

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
                ctx.emit("analysis_complete", {"iterations": i, "found_token": True})
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
