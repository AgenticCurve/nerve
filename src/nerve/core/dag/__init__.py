"""DAG task orchestration.

Pure DAG execution - no PTY knowledge, no events, no server awareness.
Just tasks, dependencies, and execution.

Classes:
    DAG: Directed Acyclic Graph of tasks.
    Task: A single task in the DAG.
    TaskStatus: Task execution status.

Example:
    >>> from nerve.core.dag import DAG, Task
    >>>
    >>> dag = DAG()
    >>>
    >>> dag.add_task(Task(
    ...     id="fetch",
    ...     execute=lambda ctx: fetch_data(),
    ... ))
    >>>
    >>> dag.add_task(Task(
    ...     id="process",
    ...     execute=lambda ctx: process(ctx["fetch"]),
    ...     depends_on=["fetch"],
    ... ))
    >>>
    >>> results = await dag.run()
    >>> print(results["process"].output)
"""

from nerve.core.dag.graph import DAG
from nerve.core.dag.task import Task
from nerve.core.types import TaskResult, TaskStatus

__all__ = ["DAG", "Task", "TaskStatus", "TaskResult"]
