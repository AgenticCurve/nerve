"""ExecutionContext - runtime context passed through graph execution.

ExecutionContext carries all state needed during node execution:
- Session reference for node lookup
- Input data for the current node
- Results from upstream nodes
- Parser configuration
- Budget and resource tracking (P0 agent capabilities)
- Cancellation token (P0 agent capabilities)
- Execution trace (P0 agent capabilities)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nerve.core.nodes.budget import Budget, ResourceUsage
    from nerve.core.nodes.cancellation import CancellationToken
    from nerve.core.nodes.run_logging import RunLogger
    from nerve.core.nodes.trace import ExecutionTrace
    from nerve.core.session.session import Session
    from nerve.core.types import ParserType


@dataclass
class ExecutionContext:
    """Context passed through graph execution.

    ExecutionContext is immutable by convention - use with_* methods
    to create modified copies rather than mutating fields directly.

    Attributes:
        session: The session containing registered nodes.
        input: Input data for the current node execution.
        upstream: Results from upstream nodes, keyed by step_id.
        parser: Parser type for terminal nodes (optional override).
        timeout: Timeout in seconds for node execution.
        budget: Resource limits for execution (optional).
        usage: Resource usage tracking (optional).
        cancellation: Token for cooperative cancellation (optional).
        trace: Execution trace for observability (optional).
        run_id: Unique identifier for the current execution run (graph execution).
        run_logger: Logger scoped to the current run for file-based logging.
        exec_id: Unique identifier for direct node execution (outside graph).
        correlation_id: ID for correlating related operations (e.g., parallel steps).

    Example:
        >>> context = ExecutionContext(session=session, input="hello")
        >>> result = await node.execute(context)

        # Pass modified input to next node
        >>> next_context = context.with_input(result)
        >>> next_result = await next_node.execute(next_context)
    """

    session: Session | None = None
    input: Any = None
    upstream: dict[str, Any] = field(default_factory=dict)
    parser: ParserType | None = None
    timeout: float | None = None

    # P0 Agent Capabilities (initialized lazily when needed)
    budget: Budget | None = None
    usage: ResourceUsage | None = None
    cancellation: CancellationToken | None = None
    trace: ExecutionTrace | None = None

    # Run logging (initialized by Graph.execute if not provided)
    run_id: str | None = None
    run_logger: RunLogger | None = None

    # Direct execution ID (for node execution outside graph)
    exec_id: str | None = None

    # Correlation ID for tracking related operations (e.g., parallel steps)
    correlation_id: str | None = None

    def with_input(self, input: Any) -> ExecutionContext:
        """Create new context with different input.

        Args:
            input: New input value.

        Returns:
            New ExecutionContext with updated input.
        """
        return replace(self, input=input)

    def with_upstream(self, upstream: dict[str, Any]) -> ExecutionContext:
        """Create new context with updated upstream results.

        Args:
            upstream: Additional upstream results to merge.

        Returns:
            New ExecutionContext with merged upstream dict.
        """
        return replace(self, upstream={**self.upstream, **upstream})

    def with_parser(self, parser: ParserType) -> ExecutionContext:
        """Create new context with different parser.

        Args:
            parser: Parser type to use.

        Returns:
            New ExecutionContext with updated parser.
        """
        return replace(self, parser=parser)

    def with_correlation_id(self, correlation_id: str) -> ExecutionContext:
        """Create new context with correlation ID for tracking related operations.

        Use this when executing parallel steps or related operations that
        should be correlated in logs.

        Args:
            correlation_id: Unique ID to correlate related operations.

        Returns:
            New ExecutionContext with correlation_id set.
        """
        return replace(self, correlation_id=correlation_id)

    def check_cancelled(self) -> None:
        """Raise CancelledError if cancellation was requested.

        Should be called at checkpoints during execution (before each step,
        after each step, etc.) to support cooperative cancellation.

        Raises:
            CancelledError: If cancellation was requested.
        """
        if self.cancellation:
            if self.cancellation.is_cancelled:
                logger.debug(
                    "cancellation_triggered: run_id=%s",
                    self.run_id,
                )
            self.cancellation.check()

    def check_budget(self) -> None:
        """Raise BudgetExceededError if budget is exceeded.

        Should be called at checkpoints during execution (before each step,
        after each step, etc.) to enforce resource limits.

        Raises:
            BudgetExceededError: If any budget limit is exceeded.
        """
        if self.budget and self.usage:
            exceeded, reason = self.usage.exceeds(self.budget)
            if exceeded:
                logger.debug(
                    "budget_exceeded: run_id=%s, reason=%s, tokens=%d/%s, cost=%.4f/%s",
                    self.run_id,
                    reason,
                    self.usage.tokens_used,
                    self.budget.max_tokens,
                    self.usage.cost_dollars,
                    self.budget.max_cost_dollars,
                )
                # Import here to avoid circular dependency
                from nerve.core.nodes.budget import BudgetExceededError

                raise BudgetExceededError(self.usage, self.budget, reason or "")

    def with_sub_budget(self, sub_budget: Budget) -> ExecutionContext:
        """Create child context with isolated budget tracking.

        The child's usage counts toward the parent's budget AND the sub-budget.
        If either is exceeded, BudgetExceededError is raised.

        Args:
            sub_budget: Budget limit for the sub-context.

        Returns:
            New ExecutionContext with fresh usage tracking and parent reference.
        """
        # Import here to avoid circular dependency
        from nerve.core.nodes.budget import ResourceUsage

        # Create child usage that propagates to parent
        child_usage = ResourceUsage(_parent_usage=self.usage)

        logger.debug(
            "sub_budget_created: run_id=%s, max_tokens=%s, max_cost=%s, has_parent=%s",
            self.run_id,
            sub_budget.max_tokens,
            sub_budget.max_cost_dollars,
            self.usage is not None,
        )

        return replace(
            self,
            budget=sub_budget,
            usage=child_usage,
        )

    def record_step(
        self,
        step_id: str,
        node: Any,
        input: Any,
        output: Any,
        start_time: Any,
        end_time: Any,
        error: str | None = None,
        tokens_used: int = 0,
    ) -> None:
        """Record a step execution in the trace.

        Called by Graph during execution to record each step's inputs,
        outputs, timing, and any errors. No-op if trace is not set.

        Args:
            step_id: Step identifier.
            node: The node that was executed.
            input: Input passed to the node.
            output: Output returned by the node.
            start_time: When execution started.
            end_time: When execution ended.
            error: Error message if execution failed (optional).
            tokens_used: Token count for LLM calls (optional).
        """
        if self.trace is None:
            return

        # Import here to avoid circular dependency
        from nerve.core.nodes.trace import StepTrace

        # Calculate duration in milliseconds
        duration_ms = (end_time - start_time).total_seconds() * 1000

        # Get node type string
        node_type = type(node).__name__.lower().replace("node", "") or "unknown"

        step_trace = StepTrace(
            step_id=step_id,
            node_id=getattr(node, "id", str(id(node))),
            node_type=node_type,
            input=input,
            output=output,
            error=error,
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
        )

        self.trace.add_step(step_trace)
