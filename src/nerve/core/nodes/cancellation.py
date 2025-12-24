"""Cooperative cancellation for graph execution.

CancellationToken enables graceful stopping of long-running graph executions.
Cancellation is cooperative - nodes must check the token at appropriate points.

Typical usage:
1. Create a CancellationToken before starting graph execution
2. Pass it via ExecutionContext
3. Call token.cancel() from another task/thread to request cancellation
4. Graph execution checks token at each step boundary
"""

from __future__ import annotations

import asyncio


class CancelledError(Exception):
    """Raised when execution is cancelled.

    This exception should be caught at the graph execution level
    to handle partial results and cleanup.
    """

    pass


class CancellationToken:
    """Token for cooperative cancellation.

    Thread-safe token that can be used to request and check
    cancellation status across async boundaries.

    Example:
        >>> token = CancellationToken()
        >>> context = ExecutionContext(session=session, cancellation=token)
        >>>
        >>> # Start graph in background
        >>> task = asyncio.create_task(graph.execute(context))
        >>>
        >>> # Cancel after some condition
        >>> await asyncio.sleep(5)
        >>> token.cancel()
        >>>
        >>> # Graph will raise CancelledError at next check point
        >>> try:
        ...     await task
        ... except CancelledError:
        ...     print("Execution was cancelled")
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._event = asyncio.Event()

    def cancel(self) -> None:
        """Request cancellation.

        Sets the cancelled flag and signals any waiters.
        This is safe to call multiple times.
        """
        self._cancelled = True
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested.

        Returns:
            True if cancel() has been called.
        """
        return self._cancelled

    def check(self) -> None:
        """Raise CancelledError if cancelled.

        Call this at safe points during execution where
        it's okay to stop (e.g., between steps).

        Raises:
            CancelledError: If cancellation was requested.
        """
        if self._cancelled:
            raise CancelledError()

    async def wait(self) -> None:
        """Wait until cancelled.

        Blocks until cancel() is called. Useful for background
        tasks that should run until cancellation.
        """
        await self._event.wait()

    def reset(self) -> None:
        """Reset the token for reuse.

        Clears the cancelled flag and event. Use with caution -
        typically you should create a new token instead.
        """
        self._cancelled = False
        self._event.clear()
