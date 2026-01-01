"""Example workspace configuration for Commander.

This file demonstrates how to set up a complete workspace that can be loaded
with: nerve commander --config examples/workspace_example.py

The config file can:
1. Create nodes (the session variable is available)
2. Define and register graphs
3. Define and register workflows
4. Specify startup commands to pre-populate the timeline

Usage:
    # Start the server first
    nerve server start

    # Then start commander with this config
    nerve commander --config examples/workspace_example.py
"""

from nerve.core.nodes.function import FunctionNode

from nerve.core.nodes.graph import Graph
from nerve.core.workflow import Workflow, WorkflowContext

# =============================================================================
# Node Creation
# =============================================================================
# The `session` variable is automatically available when this file is executed.
# You can create any type of node here.

# Create a simple function node for demonstration
FunctionNode(
    id="echo",
    session=session,  # noqa: F821 - session is injected
    fn=lambda ctx: {"output": f"Echo: {ctx.input}"},
    description="Simple echo node for testing",
)

# Create another function node that transforms input
FunctionNode(
    id="upper",
    session=session,  # noqa: F821
    fn=lambda ctx: {"output": str(ctx.input).upper()},
    description="Convert input to uppercase",
)

# For real usage, you'd typically create PTY nodes like:
# await PTYNode.create(id="claude1", session=session, command="claude")
# But note that PTYNode.create is async, so you'd need to handle that.

print("Created 2 nodes: echo, upper")

# =============================================================================
# Graph Creation
# =============================================================================

# Create a simple pipeline graph
pipeline = Graph(id="echo_upper", session=session)  # noqa: F821
pipeline.add_step_ref("echo", step_id="step1", input_fn=lambda upstream: upstream.get("input"))
pipeline.add_step_ref("upper", step_id="step2", depends_on=["step1"])

print("Created 1 graph: echo_upper")

# =============================================================================
# Workflow Creation
# =============================================================================


async def demo_workflow(ctx: WorkflowContext) -> str:
    """A simple demo workflow that chains echo and upper nodes."""
    # Run the echo node
    result1 = await ctx.run("echo", ctx.input)
    ctx.emit("step_complete", {"step": "echo", "output": result1["output"]})

    # Run the upper node
    result2 = await ctx.run("upper", result1["output"])
    ctx.emit("step_complete", {"step": "upper", "output": result2["output"]})

    return result2["output"]


Workflow(
    id="demo",
    session=session,  # noqa: F821
    fn=demo_workflow,
    description="Demo workflow that chains echo and upper",
)

print("Created 1 workflow: demo")

# =============================================================================
# Startup Commands
# =============================================================================
# These commands run in Commander after the workspace is loaded.
# They pre-populate the timeline with initial outputs.
#
# Supported command formats:
#   @node_id message     - Send message to a node
#   #graph_id input      - Execute a graph
#   %workflow_id input   - Execute a workflow
#   >>> python_code      - Execute Python code
#   :command             - Run a commander command

startup_commands = [
    "@echo Hello, workspace!",
    "@upper testing the workspace config",
]
