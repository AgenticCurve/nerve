"""Test workspace for Commander config feature.

Usage:
    nerve server start
    nerve commander --config examples/test_workspace.py

This creates:
    - 2 Claude nodes (claude1, claude2)
    - 1 Graph (review_chain) that pipes claude1 -> claude2
    - 1 Workflow (qa_workflow) that asks claude1, then claude2 reviews
"""

from nerve.core.nodes.graph import Graph
from nerve.core.nodes.terminal import ClaudeWezTermNode
from nerve.core.workflow import Workflow, WorkflowContext

# =============================================================================
# Nodes - 2 Claude instances (in WezTerm tabs)
# =============================================================================

# NOTE: --dangerously-skip-permissions bypasses Claude's permission prompts.
# Only use for testing in controlled environments. In production, either:
# - Remove the flag to approve each permission explicitly, or
# - Use allowlist flags like --allowedTools to limit capabilities

claude1 = await ClaudeWezTermNode.create(  # noqa: F704
    id="claude1",
    session=session,  # noqa: F821
    command="claude --dangerously-skip-permissions",
)
print("Created node: claude1 (WezTerm)")

claude2 = await ClaudeWezTermNode.create(  # noqa: F704
    id="claude2",
    session=session,  # noqa: F821
    command="claude --dangerously-skip-permissions",
)
print("Created node: claude2 (WezTerm)")

# =============================================================================
# Graph - Chain claude1 -> claude2
# =============================================================================

review_chain = Graph(id="review_chain", session=session)  # noqa: F821
review_chain.add_step_ref(
    "claude1",
    step_id="generate",
    input_fn=lambda upstream: upstream.get("input", ""),
)
review_chain.add_step_ref(
    "claude2",
    step_id="review",
    input_fn=lambda upstream: f"Review this response and improve it:\n\n{upstream['generate']['output']}",
    depends_on=["generate"],
)
print("Created graph: review_chain")

# =============================================================================
# Workflow - Q&A with review
# =============================================================================


async def qa_workflow(ctx: WorkflowContext) -> str:
    """Ask claude1 a question, then have claude2 review and improve the answer."""
    # Step 1: Get initial answer
    ctx.emit("step", {"name": "asking claude1"})
    result1 = await ctx.run("claude1", ctx.input)

    # Step 2: Review and improve
    ctx.emit("step", {"name": "claude2 reviewing"})
    review_prompt = f"Review and improve this answer:\n\n{result1['output']}"
    result2 = await ctx.run("claude2", review_prompt)

    return result2["output"]


Workflow(
    id="qa_workflow",
    session=session,  # noqa: F821
    fn=qa_workflow,
    description="Ask claude1, then claude2 reviews the answer",
)
print("Created workflow: qa_workflow")

# =============================================================================
# Startup Commands - Initialize the nodes
# =============================================================================

startup_commands = [
    "@claude1 You are a helpful assistant. Keep responses concise (1-2 sentences). Just reply OK to confirm.",
    "@claude2 You are a code reviewer. Keep responses concise. Just reply OK to confirm.",
]
