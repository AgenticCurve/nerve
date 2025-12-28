"""Run-based logging for graph and node execution.

Provides:
- Run ID generation (unique per Graph.execute() call)
- RunLogger protocol for type hints
- Logging utility functions

Log Format:
    [<identifier>] action: key=value, key=value (duration)

Examples:
    [my-graph] graph_start: steps=5
    [my-graph] step_start: step=fetch, depends_on=[]
    [my-graph] step_complete: step=fetch (1.2s)
    [my-graph] graph_complete: steps=5 (3.5s)

Note:
    The actual RunLogger implementation is in session_logging.py.
    This module provides the protocol and utility functions.
"""

from __future__ import annotations

import logging
import random
import string
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


def generate_run_id() -> str:
    """Generate a unique run ID.

    Format: YYYYMMDD_HHMMSS_xxx
    - Timestamp at second precision
    - 3-char random suffix to avoid collision

    Returns:
        Run ID string like "20251228_143022_x7k"
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=3))
    return f"{timestamp}_{suffix}"


def generate_correlation_id() -> str:
    """Generate a unique correlation ID for tracking related operations.

    Format: corr_HHMMSS_xxx
    - Shorter than run_id (meant for intra-run correlation)
    - 3-char random suffix

    Returns:
        Correlation ID string like "corr_143022_x7k"
    """
    timestamp = time.strftime("%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=3))
    return f"corr_{timestamp}_{suffix}"


def truncate(value: Any, max_length: int = 100) -> str:
    """Truncate a value for logging.

    Args:
        value: Value to truncate.
        max_length: Maximum length before truncation.

    Returns:
        Truncated string with length indicator if truncated.
    """
    s = str(value)
    if len(s) <= max_length:
        return s
    return f"{s[:max_length]}... ({len(s)} chars)"


@runtime_checkable
class RunLogger(Protocol):
    """Protocol for run-scoped loggers.

    Implementations must provide:
    - run_id: Unique identifier for this run
    - log_dir: Path to the log directory
    - get_logger(name): Get a logger for a specific component
    - close(): Clean up resources

    The actual implementation is _GraphRunLogger in session_logging.py,
    which writes to .nerve/<server>/<session>/<timestamp>/graph-runs/<run_id>/
    """

    @property
    def run_id(self) -> str:
        """Unique identifier for this run."""
        ...

    @property
    def log_dir(self) -> Path:
        """Path to the log directory for this run."""
        ...

    def get_logger(self, name: str) -> logging.Logger:
        """Get or create a logger for a specific component.

        Args:
            name: Component name (e.g., "graph", "step-fetch", "bash").

        Returns:
            Logger configured to write to <name>.log in run directory.
        """
        ...

    def close(self) -> None:
        """Close all file handlers and clean up resources."""
        ...


# Convenience functions for logging patterns


def log_start(
    logger: logging.Logger | None,
    identifier: str,
    action: str,
    correlation_id: str | None = None,
    exec_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Log a start event.

    Args:
        logger: Logger to use. If None, this is a no-op.
        identifier: Primary identifier (graph_id, node_id, etc.).
        action: Action name (e.g., "graph_start", "step_start").
        correlation_id: Optional correlation ID for tracking related operations.
        exec_id: Optional execution ID for direct node execution.
        **kwargs: Additional key=value pairs to log.
    """
    if logger is None:
        return
    if correlation_id:
        kwargs["corr_id"] = correlation_id
    if exec_id:
        kwargs["exec_id"] = exec_id
    kv_pairs = ", ".join(f"{k}={truncate(v)}" for k, v in kwargs.items())
    msg = f"[{identifier}] {action}: {kv_pairs}" if kv_pairs else f"[{identifier}] {action}"
    logger.debug(msg)


def log_complete(
    logger: logging.Logger | None,
    identifier: str,
    action: str,
    duration_s: float,
    correlation_id: str | None = None,
    exec_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Log a completion event with duration.

    Args:
        logger: Logger to use. If None, this is a no-op.
        identifier: Primary identifier.
        action: Action name (e.g., "graph_complete", "step_complete").
        duration_s: Duration in seconds.
        correlation_id: Optional correlation ID for tracking related operations.
        exec_id: Optional execution ID for direct node execution.
        **kwargs: Additional key=value pairs to log.
    """
    if logger is None:
        return
    if correlation_id:
        kwargs["corr_id"] = correlation_id
    if exec_id:
        kwargs["exec_id"] = exec_id
    kv_pairs = ", ".join(f"{k}={truncate(v)}" for k, v in kwargs.items())
    if kv_pairs:
        msg = f"[{identifier}] {action}: {kv_pairs} ({duration_s:.1f}s)"
    else:
        msg = f"[{identifier}] {action}: ({duration_s:.1f}s)"
    logger.debug(msg)


def log_error(
    logger: logging.Logger | None,
    identifier: str,
    action: str,
    error: str | Exception,
    correlation_id: str | None = None,
    exec_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Log an error event.

    Args:
        logger: Logger to use. If None, this is a no-op.
        identifier: Primary identifier.
        action: Action name (e.g., "step_failed", "graph_failed").
        error: Error message or exception.
        correlation_id: Optional correlation ID for tracking related operations.
        exec_id: Optional execution ID for direct node execution.
        **kwargs: Additional key=value pairs to log.
    """
    if logger is None:
        return
    if correlation_id:
        kwargs["corr_id"] = correlation_id
    if exec_id:
        kwargs["exec_id"] = exec_id
    error_msg = truncate(str(error), max_length=200)
    kwargs["error"] = error_msg
    kv_pairs = ", ".join(f"{k}={truncate(v)}" for k, v in kwargs.items())
    msg = f"[{identifier}] {action}: {kv_pairs}"
    logger.error(msg)


def log_warning(
    logger: logging.Logger | None,
    identifier: str,
    action: str,
    correlation_id: str | None = None,
    exec_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Log a warning event.

    Args:
        logger: Logger to use. If None, this is a no-op.
        identifier: Primary identifier.
        action: Action name (e.g., "retry", "budget_warning").
        correlation_id: Optional correlation ID for tracking related operations.
        exec_id: Optional execution ID for direct node execution.
        **kwargs: Additional key=value pairs to log.
    """
    if logger is None:
        return
    if correlation_id:
        kwargs["corr_id"] = correlation_id
    if exec_id:
        kwargs["exec_id"] = exec_id
    kv_pairs = ", ".join(f"{k}={truncate(v)}" for k, v in kwargs.items())
    msg = f"[{identifier}] {action}: {kv_pairs}" if kv_pairs else f"[{identifier}] {action}"
    logger.warning(msg)


def log_info(
    logger: logging.Logger | None,
    identifier: str,
    action: str,
    correlation_id: str | None = None,
    exec_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Log an info event.

    Args:
        logger: Logger to use. If None, this is a no-op.
        identifier: Primary identifier.
        action: Action name.
        correlation_id: Optional correlation ID for tracking related operations.
        exec_id: Optional execution ID for direct node execution.
        **kwargs: Additional key=value pairs to log.
    """
    if logger is None:
        return
    if correlation_id:
        kwargs["corr_id"] = correlation_id
    if exec_id:
        kwargs["exec_id"] = exec_id
    kv_pairs = ", ".join(f"{k}={truncate(v)}" for k, v in kwargs.items())
    msg = f"[{identifier}] {action}: {kv_pairs}" if kv_pairs else f"[{identifier}] {action}"
    logger.info(msg)


# Track which components have already warned about missing run_logger
_warned_no_run_logger: set[str] = set()


def warn_no_run_logger(component: str, context_info: str | None = None) -> None:
    """Emit a one-time warning when run_logger is unavailable.

    This helps users understand why logs are not being generated.
    The warning is only emitted once per component to avoid noise.

    Args:
        component: Component identifier (e.g., "graph:my-graph", "node:bash").
        context_info: Optional additional context (e.g., "no session in context").
    """
    if component in _warned_no_run_logger:
        return

    _warned_no_run_logger.add(component)

    logger = logging.getLogger("nerve.run_logging")
    msg = f"Run logging unavailable for {component}"
    if context_info:
        msg += f" ({context_info})"
    msg += ". Execution will not be logged to run files."
    logger.warning(msg)
