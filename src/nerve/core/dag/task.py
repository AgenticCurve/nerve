"""DAG task definition."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    """A task in a DAG.

    Tasks are pure - they just wrap a callable with metadata.
    They don't know about PTY, sessions, or events.

    The execute function receives a context dict with results
    from upstream tasks, keyed by task ID.

    Attributes:
        id: Unique identifier for this task.
        execute: Async function that performs the task.
        depends_on: List of task IDs this task depends on.
        name: Optional human-readable name.
        metadata: Optional additional metadata.

    Example:
        >>> task = Task(
        ...     id="analyze",
        ...     execute=lambda ctx: analyze_data(ctx["fetch"]),
        ...     depends_on=["fetch"],
        ...     name="Analyze fetched data",
        ... )
    """

    id: str
    execute: Callable[[dict[str, Any]], Awaitable[Any]]
    depends_on: list[str] = field(default_factory=list)
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Task):
            return self.id == other.id
        return False
