"""Shared request tracing functionality for gateway servers.

Provides human-readable trace IDs and debug data saving.

Can optionally integrate with a RunLogger for unified run-based logging:
- Pass a RunLogger instance to use its log directory
- Debug files are saved alongside other run logs
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.nodes.run_logging import RunLogger

logger = logging.getLogger(__name__)


class RequestTracer:
    """Handles request tracing and debug data saving for gateway servers.

    Debug files are saved to: {debug_dir}/logs/{session_id}/{trace_id}/

    When integrated with a RunLogger:
    - Uses RunLogger's log directory for debug files

    Example:
        # Standalone usage
        tracer = RequestTracer(debug_dir="/tmp/debug")

        # With RunLogger integration (from graph execution)
        tracer = RequestTracer.with_run_logger(run_logger)
    """

    def __init__(
        self,
        debug_dir: str | Path | None = None,
        run_logger: RunLogger | None = None,
    ):
        """Initialize tracer with optional debug directory or RunLogger.

        Args:
            debug_dir: Directory for debug files (ignored if run_logger provided).
            run_logger: Optional RunLogger for unified logging.
        """
        self._request_counter = 0
        self._session_id: str | None = None
        self._debug_dir_config = debug_dir
        self._run_logger = run_logger

    @classmethod
    def with_run_logger(cls, run_logger: RunLogger) -> RequestTracer:
        """Create a tracer that uses RunLogger for file storage.

        Args:
            run_logger: RunLogger instance to use.

        Returns:
            RequestTracer configured to use the RunLogger's directory.
        """
        return cls(run_logger=run_logger)

    @property
    def run_id(self) -> str | None:
        """Get the run ID if using RunLogger."""
        return self._run_logger.run_id if self._run_logger else None

    @property
    def debug_dir(self) -> Path | None:
        """Get the debug directory path, creating session folder on first access.

        If using RunLogger, returns the RunLogger's log directory.
        Otherwise creates a session-based directory.
        """
        # Use RunLogger directory if available
        if self._run_logger:
            return self._run_logger.log_dir / "gateway"

        if not self._debug_dir_config:
            return None

        if self._session_id is None:
            self._session_id = time.strftime("%Y-%m-%d_%H-%M-%S")

        return Path(self._debug_dir_config) / "logs" / self._session_id

    def generate_trace_id(self, body: dict[str, Any]) -> str:
        """Generate a human-readable trace ID with sequence number and context.

        Format: {counter}_{hhmmss}_{num_messages}msgs_{context}
        Example: 00001_031333_1msgs_Please_write_a
        """
        self._request_counter += 1

        # Get timestamp
        timestamp = time.strftime("%H%M%S")

        # Extract context from request
        msgs = body.get("messages", [])
        msg_count = len(msgs)

        # Get LAST user message with actual text content (skip tool_result messages)
        context = "empty"
        for m in reversed(msgs):
            if m.get("role") != "user":
                continue
            content = m.get("content", "")

            # String content - use it
            if isinstance(content, str) and content.strip():
                words = content.split()[:3]
                context = "_".join(w[:8] for w in words if w and not w.startswith("<"))[:20]
                break

            # List content - look for text blocks (skip if only tool_result)
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "text" and block.get("text", "").strip():
                        words = block.get("text", "").split()[:3]
                        context = "_".join(w[:8] for w in words if w and not w.startswith("<"))[:20]
                        break
                if context != "empty":
                    break

        # Clean context for filesystem
        context = "".join(c if c.isalnum() or c == "_" else "" for c in context) or "request"

        return f"{self._request_counter:05d}_{timestamp}_{msg_count}msgs_{context}"

    def save_debug(self, trace_id: str, filename: str, data: Any) -> None:
        """Save debug data to JSON file if debug_dir is configured."""
        if not self.debug_dir:
            return

        try:
            # Create trace-specific folder (and parent debug_dir if needed)
            trace_path = self.debug_dir / trace_id
            trace_path.mkdir(parents=True, exist_ok=True)

            filepath = trace_path / filename
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.debug("[%s] Saved debug file: %s", trace_id, filepath)
        except Exception as e:
            logger.warning("[%s] Failed to save debug file %s: %s", trace_id, filename, e)

    def log_request(
        self,
        trace_id: str,
        method: str,
        path: str,
        body_size: int,
        msg_count: int = 0,
    ) -> None:
        """Log a request event.

        Uses RunLogger if available, otherwise uses standard logging.

        Args:
            trace_id: Trace ID for this request.
            method: HTTP method.
            path: Request path.
            body_size: Size of request body in bytes.
            msg_count: Number of messages in request (for chat APIs).
        """
        if self._run_logger:
            from nerve.core.nodes.run_logging import log_start

            gw_logger = self._run_logger.get_logger("gateway")
            log_start(
                gw_logger,
                trace_id,
                "request_start",
                method=method,
                path=path,
                body_size=body_size,
                msg_count=msg_count,
                run_id=self._run_logger.run_id,
            )
        else:
            logger.debug(
                "[%s] request_start: method=%s, path=%s, body_size=%d, msg_count=%d",
                trace_id,
                method,
                path,
                body_size,
                msg_count,
            )

    def log_response(
        self,
        trace_id: str,
        status_code: int,
        duration_s: float,
        response_size: int = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        error: str | None = None,
    ) -> None:
        """Log a response event.

        Uses RunLogger if available, otherwise uses standard logging.

        Args:
            trace_id: Trace ID for this request.
            status_code: HTTP status code.
            duration_s: Request duration in seconds.
            response_size: Size of response body in bytes.
            tokens_in: Input tokens (for chat APIs).
            tokens_out: Output tokens (for chat APIs).
            error: Error message if request failed.
        """
        if self._run_logger:
            from nerve.core.nodes.run_logging import log_complete, log_error

            gw_logger = self._run_logger.get_logger("gateway")
            if error:
                log_error(
                    gw_logger,
                    trace_id,
                    "request_failed",
                    error,
                    status_code=status_code,
                    duration_s=f"{duration_s:.2f}",
                )
            else:
                log_complete(
                    gw_logger,
                    trace_id,
                    "request_complete",
                    duration_s,
                    status_code=status_code,
                    response_size=response_size,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )
        else:
            if error:
                logger.warning(
                    "[%s] request_failed: status=%d, error=%s (%.2fs)",
                    trace_id,
                    status_code,
                    error[:100],
                    duration_s,
                )
            else:
                logger.debug(
                    "[%s] request_complete: status=%d, size=%d, tokens_in=%d, tokens_out=%d (%.2fs)",
                    trace_id,
                    status_code,
                    response_size,
                    tokens_in,
                    tokens_out,
                    duration_s,
                )
