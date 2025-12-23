"""Error handling policies for graph execution.

ErrorPolicy defines how steps handle failures:
- fail: Propagate error immediately (default)
- retry: Retry with configurable backoff
- skip: Continue with fallback value
- fallback: Execute alternative node

These policies enable resilient graph execution without
cluttering node implementations with error handling logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from nerve.core.nodes.base import Node


@dataclass
class ErrorPolicy:
    """Error handling policy for a step.

    Configures how errors during step execution should be handled.
    The policy is evaluated after all retry attempts are exhausted.

    Attributes:
        on_error: What to do when step fails after retries.
            - "fail": Propagate the exception (default)
            - "retry": Retry then fail (retry_count must be > 0)
            - "skip": Return fallback_value and continue
            - "fallback": Execute fallback_node instead
        retry_count: Number of retry attempts (0 = no retries).
        retry_delay_ms: Initial delay between retries in milliseconds.
        retry_backoff: Multiplier for delay after each retry.
            E.g., 2.0 means delays are 1s, 2s, 4s, 8s...
        timeout_ms: Timeout for each execution attempt in milliseconds.
            None means no timeout.
        fallback_value: Value to return when on_error="skip".
        fallback_node: Node to execute when on_error="fallback".

    Example:
        # Retry up to 3 times with exponential backoff
        policy = ErrorPolicy(
            on_error="retry",
            retry_count=3,
            retry_delay_ms=1000,
            retry_backoff=2.0,
        )

        # Skip on error, return None
        policy = ErrorPolicy(on_error="skip", fallback_value=None)

        # Fall back to alternative node
        policy = ErrorPolicy(
            on_error="fallback",
            fallback_node=backup_node,
        )
    """

    on_error: Literal["fail", "retry", "skip", "fallback"] = "fail"
    retry_count: int = 0
    retry_delay_ms: int = 1000
    retry_backoff: float = 2.0
    timeout_ms: int | None = None
    fallback_value: Any = None
    fallback_node: Node | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Validate policy configuration."""
        if self.on_error == "retry" and self.retry_count <= 0:
            raise ValueError("retry_count must be > 0 when on_error='retry'")

        if self.on_error == "fallback" and self.fallback_node is None:
            raise ValueError("fallback_node must be set when on_error='fallback'")

        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")

        if self.retry_delay_ms < 0:
            raise ValueError("retry_delay_ms cannot be negative")

        if self.retry_backoff < 1.0:
            raise ValueError("retry_backoff must be >= 1.0")

    def get_delay_for_attempt(self, attempt: int) -> float:
        """Calculate delay in seconds for a retry attempt.

        Args:
            attempt: The attempt number (0-indexed).

        Returns:
            Delay in seconds before the next attempt.
        """
        delay_ms = self.retry_delay_ms * (self.retry_backoff**attempt)
        return delay_ms / 1000.0

    def should_retry(self, attempt: int) -> bool:
        """Check if another retry should be attempted.

        Args:
            attempt: The current attempt number (0-indexed).

        Returns:
            True if more retries are available.
        """
        return attempt < self.retry_count
