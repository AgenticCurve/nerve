"""Budget and resource tracking for graph execution.

Budgets enforce limits on resource consumption:
- Token usage
- Time elapsed
- Step count
- API calls
- Cost in dollars

ResourceUsage tracks consumption against these budgets.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Budget:
    """Resource limits for graph execution.

    All limits are optional - only set limits are enforced.
    A budget with no limits set allows unlimited execution.

    Attributes:
        max_tokens: Maximum token usage allowed.
        max_time_seconds: Maximum wall-clock time in seconds.
        max_steps: Maximum number of steps to execute.
        max_api_calls: Maximum number of API calls.
        max_cost_dollars: Maximum cost in dollars.

    Example:
        # Allow up to 10000 tokens and 60 seconds
        budget = Budget(max_tokens=10000, max_time_seconds=60.0)

        # Allow up to 5 steps
        budget = Budget(max_steps=5)
    """

    max_tokens: int | None = None
    max_time_seconds: float | None = None
    max_steps: int | None = None
    max_api_calls: int | None = None
    max_cost_dollars: float | None = None

    def is_limited(self) -> bool:
        """Check if any limits are set.

        Returns:
            True if at least one limit is configured.
        """
        return any(
            [
                self.max_tokens is not None,
                self.max_time_seconds is not None,
                self.max_steps is not None,
                self.max_api_calls is not None,
                self.max_cost_dollars is not None,
            ]
        )


@dataclass
class ResourceUsage:
    """Tracks resource consumption during execution.

    Uses monotonic clock for elapsed time to avoid issues
    with system clock adjustments (NTP sync, DST changes, etc.).
    The start_time datetime is kept for display/logging purposes only.

    When created via ExecutionContext.with_sub_budget(), the usage
    automatically propagates to the parent context's usage tracking.

    Attributes:
        tokens_used: Total tokens consumed.
        steps_executed: Number of steps executed.
        api_calls: Number of API calls made.
        cost_dollars: Total cost in dollars.
        start_time: When execution started (for display).
    """

    tokens_used: int = 0
    steps_executed: int = 0
    api_calls: int = 0
    cost_dollars: float = 0.0
    _start_monotonic: float = field(default_factory=time.monotonic)
    start_time: datetime = field(default_factory=datetime.now)
    _parent_usage: ResourceUsage | None = field(default=None, repr=False)

    @property
    def time_elapsed_seconds(self) -> float:
        """Elapsed time using monotonic clock (immune to system clock changes)."""
        return time.monotonic() - self._start_monotonic

    def exceeds(self, budget: Budget) -> tuple[bool, str | None]:
        """Check if usage exceeds budget.

        Args:
            budget: The budget limits to check against.

        Returns:
            Tuple of (exceeded: bool, reason: str | None).
            If exceeded is True, reason explains which limit was hit.
        """
        if budget.max_tokens is not None and self.tokens_used >= budget.max_tokens:
            return True, f"Token limit exceeded: {self.tokens_used}/{budget.max_tokens}"

        if budget.max_steps is not None and self.steps_executed >= budget.max_steps:
            return True, f"Step limit exceeded: {self.steps_executed}/{budget.max_steps}"

        elapsed = self.time_elapsed_seconds
        if budget.max_time_seconds is not None and elapsed >= budget.max_time_seconds:
            return (
                True,
                f"Time limit exceeded: {elapsed:.1f}s/{budget.max_time_seconds}s",
            )

        if budget.max_api_calls is not None and self.api_calls >= budget.max_api_calls:
            return (
                True,
                f"API call limit exceeded: {self.api_calls}/{budget.max_api_calls}",
            )

        if budget.max_cost_dollars is not None and self.cost_dollars >= budget.max_cost_dollars:
            return (
                True,
                f"Cost limit exceeded: ${self.cost_dollars:.2f}/${budget.max_cost_dollars:.2f}",
            )

        return False, None

    def add_tokens(self, count: int) -> None:
        """Add to token usage.

        Also propagates to parent usage if this is a sub-budget context.

        Args:
            count: Number of tokens to add.
        """
        self.tokens_used += count
        if self._parent_usage is not None:
            self._parent_usage.add_tokens(count)

    def add_step(self) -> None:
        """Increment step count.

        Also propagates to parent usage if this is a sub-budget context.
        """
        self.steps_executed += 1
        if self._parent_usage is not None:
            self._parent_usage.add_step()

    def add_api_call(self) -> None:
        """Increment API call count.

        Also propagates to parent usage if this is a sub-budget context.
        """
        self.api_calls += 1
        if self._parent_usage is not None:
            self._parent_usage.add_api_call()

    def add_cost(self, amount: float) -> None:
        """Add to cost.

        Also propagates to parent usage if this is a sub-budget context.

        Args:
            amount: Cost in dollars to add.
        """
        self.cost_dollars += amount
        if self._parent_usage is not None:
            self._parent_usage.add_cost(amount)


class BudgetExceededError(Exception):
    """Raised when execution exceeds budget limits.

    Attributes:
        usage: The resource usage when the limit was hit.
        budget: The budget that was exceeded.
        reason: Human-readable explanation of which limit was hit.
    """

    def __init__(self, usage: ResourceUsage, budget: Budget, reason: str):
        self.usage = usage
        self.budget = budget
        self.reason = reason
        super().__init__(reason)
