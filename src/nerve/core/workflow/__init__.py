"""Workflow - orchestrated Python functions with control flow.

Workflows are async Python functions that orchestrate nodes with
control flow (loops, conditionals, gates). They are registered with
a Session and can be executed from Commander.

Example:
    >>> from nerve.core.workflow import Workflow, WorkflowContext, WorkflowRun
    >>> from nerve.core.session import Session
    >>>
    >>> session = Session(name="my-session")
    >>>
    >>> async def review_loop(ctx: WorkflowContext) -> str:
    ...     code = ctx.input
    ...     while True:
    ...         review = await ctx.run("reviewer", code)
    ...         decision = await ctx.gate("Accept or reject?")
    ...         if decision == "accept":
    ...             return review["output"]
    ...         code = await ctx.run("editor", f"Fix: {decision}")
    ...         code = code["output"]
    >>>
    >>> workflow = Workflow(id="review", session=session, fn=review_loop)
    >>>
    >>> run = WorkflowRun(workflow=workflow, input="my code")
    >>> await run.start()
    >>> result = await run.wait()
"""

from nerve.core.workflow.context import WorkflowContext
from nerve.core.workflow.events import WorkflowEvent
from nerve.core.workflow.run import GateInfo, WorkflowRun, WorkflowRunInfo
from nerve.core.workflow.workflow import Workflow, WorkflowInfo, WorkflowState

__all__ = [
    # Core classes
    "Workflow",
    "WorkflowContext",
    "WorkflowRun",
    # Info classes
    "WorkflowInfo",
    "WorkflowRunInfo",
    "GateInfo",
    # Events
    "WorkflowEvent",
    # Enums
    "WorkflowState",
]
