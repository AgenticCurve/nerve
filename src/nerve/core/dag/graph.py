"""DAG graph and execution."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from graphlib import TopologicalSorter
from typing import Any

from nerve.core.dag.task import Task
from nerve.core.types import TaskResult, TaskStatus


class DAG:
    """Directed Acyclic Graph of tasks.

    Pure data structure and executor - doesn't know about:
    - PTY/Sessions (tasks are abstract callables)
    - Events (just returns results)
    - Server (can be used anywhere)

    Example:
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
        >>> # Chain syntax
        >>> dag.chain("fetch", "process", "output")
        >>>
        >>> # Validate
        >>> errors = dag.validate()
        >>>
        >>> # Execute
        >>> results = await dag.run()
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def add_task(self, task: Task) -> DAG:
        """Add a task to the DAG.

        Args:
            task: The task to add.

        Returns:
            Self for chaining.
        """
        self._tasks[task.id] = task
        return self

    def add_tasks(self, *tasks: Task) -> DAG:
        """Add multiple tasks.

        Args:
            tasks: Tasks to add.

        Returns:
            Self for chaining.
        """
        for task in tasks:
            self._tasks[task.id] = task
        return self

    def chain(self, *task_ids: str) -> DAG:
        """Set up linear dependencies: a >> b >> c.

        Args:
            task_ids: Task IDs in execution order.

        Returns:
            Self for chaining.
        """
        for i in range(1, len(task_ids)):
            current_id = task_ids[i]
            previous_id = task_ids[i - 1]

            if current_id in self._tasks:
                task = self._tasks[current_id]
                if previous_id not in task.depends_on:
                    task.depends_on.append(previous_id)

        return self

    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID.

        Args:
            task_id: The task ID.

        Returns:
            The task, or None if not found.
        """
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[str]:
        """List all task IDs.

        Returns:
            List of task IDs.
        """
        return list(self._tasks.keys())

    def validate(self) -> list[str]:
        """Validate the DAG.

        Checks for:
        - Missing dependencies
        - Cycles

        Returns:
            List of error messages (empty if valid).
        """
        errors: list[str] = []

        # Check for missing dependencies
        for task in self._tasks.values():
            for dep_id in task.depends_on:
                if dep_id not in self._tasks:
                    errors.append(f"Task '{task.id}' depends on unknown task '{dep_id}'")

        # Check for cycles
        if not errors:
            try:
                graph = {t.id: set(t.depends_on) for t in self._tasks.values()}
                list(TopologicalSorter(graph).static_order())
            except Exception as e:
                errors.append(f"Cycle detected: {e}")

        return errors

    def execution_order(self) -> list[str]:
        """Get topological execution order.

        Returns:
            List of task IDs in execution order.

        Raises:
            ValueError: If DAG is invalid.
        """
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid DAG: {errors}")

        graph = {t.id: set(t.depends_on) for t in self._tasks.values()}
        return list(TopologicalSorter(graph).static_order())

    async def run(
        self,
        parallel: bool = True,
        max_workers: int = 4,
        on_task_start: Callable[[str], None] | None = None,
        on_task_complete: Callable[[TaskResult], None] | None = None,
    ) -> dict[str, TaskResult]:
        """Execute the DAG.

        Args:
            parallel: Run independent tasks concurrently.
            max_workers: Max concurrent tasks.
            on_task_start: Optional callback when task starts.
            on_task_complete: Optional callback when task completes.

        Returns:
            Dict of task_id -> TaskResult.

        Raises:
            ValueError: If DAG is invalid.
        """
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid DAG: {errors}")

        graph = {t.id: set(t.depends_on) for t in self._tasks.values()}
        sorter = TopologicalSorter(graph)
        sorter.prepare()

        context: dict[str, Any] = {}
        results: dict[str, TaskResult] = {}

        async def run_task(task_id: str) -> TaskResult:
            task = self._tasks[task_id]

            if on_task_start:
                on_task_start(task_id)

            start_time = time.monotonic()

            try:
                output = await task.execute(context)
                result = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.COMPLETED,
                    output=output,
                    duration_ms=(time.monotonic() - start_time) * 1000,
                )
                context[task_id] = output
            except Exception as e:
                result = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=str(e),
                    duration_ms=(time.monotonic() - start_time) * 1000,
                )

            results[task_id] = result

            if on_task_complete:
                on_task_complete(result)

            return result

        if parallel:
            semaphore = asyncio.Semaphore(max_workers)

            async def run_with_semaphore(task_id: str) -> TaskResult:
                async with semaphore:
                    return await run_task(task_id)

            while sorter.is_active():
                ready = list(sorter.get_ready())
                if not ready:
                    break

                tasks = [run_with_semaphore(tid) for tid in ready]
                await asyncio.gather(*tasks)

                for tid in ready:
                    sorter.done(tid)
        else:
            for task_id in sorter.static_order():
                await run_task(task_id)

        return results

    def __repr__(self) -> str:
        task_ids = list(self._tasks.keys())
        return f"DAG({task_ids})"
