"""Simple loadable workflow example.

This file demonstrates the minimal workflow file format that can be loaded
via :load in Commander or 'nerve server workflow load'.

When this file is executed, the `session` variable is already in scope
(injected by the Python executor), so you can register workflows directly.

Usage:
    In Commander:  :load examples/workflows/simple_loadable.py
    From CLI:      nerve server workflow load examples/workflows/simple_loadable.py
"""

# Note: These imports are technically optional since Workflow and WorkflowContext
# are pre-loaded in the executor's namespace, but explicit imports are clearer.
from nerve.core.workflow import Workflow, WorkflowContext


# Define workflow functions
async def hello_workflow(ctx: WorkflowContext) -> str:
    """Simple hello workflow that returns a greeting."""
    name = ctx.input or "World"
    return f"Hello, {name}!"


async def echo_workflow(ctx: WorkflowContext) -> str:
    """Echo workflow that just returns the input."""
    return f"You said: {ctx.input}"


async def gate_demo(ctx: WorkflowContext) -> str:
    """Workflow demonstrating a gate (human-in-the-loop).

    Pauses and asks for confirmation before returning.
    """
    # Show what we received
    ctx.emit("received_input", {"input": ctx.input})

    # Ask for confirmation
    answer = await ctx.gate(
        f"Process '{ctx.input}'?",
        choices=["yes", "no"],
    )

    if answer == "yes":
        return f"Processed: {str(ctx.input or '').upper()}"
    else:
        return "Cancelled by user"


# Register workflows with the session
# Note: 'session' is injected by the Python executor
Workflow(id="hello", session=session, fn=hello_workflow)  # noqa: F821
Workflow(id="echo", session=session, fn=echo_workflow)  # noqa: F821
Workflow(id="gate-demo", session=session, fn=gate_demo)  # noqa: F821

# Print confirmation (will be shown in Commander/CLI output)
print("Registered 3 workflows: hello, echo, gate-demo")
