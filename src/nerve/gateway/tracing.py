"""Shared request tracing functionality for gateway servers.

Provides human-readable trace IDs and debug data saving.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RequestTracer:
    """Handles request tracing and debug data saving for gateway servers.

    Debug files are saved to: {debug_dir}/logs/{session_id}/{trace_id}/
    """

    def __init__(self, debug_dir: str | Path | None = None):
        """Initialize tracer with optional debug directory."""
        self._request_counter = 0
        self._session_id: str | None = None
        self._debug_dir_config = debug_dir

    @property
    def debug_dir(self) -> Path | None:
        """Get the debug directory path, creating session folder on first access."""
        if not self._debug_dir_config:
            return None

        if self._session_id is None:
            self._session_id = time.strftime("%Y-%m-%d_%H-%M-%S")

        return Path(self._debug_dir_config) / "logs" / self._session_id

    def generate_trace_id(self, body: dict[str, Any]) -> str:
        """Generate a human-readable trace ID with sequence number and context.

        Format: {counter}_{hhmmss}_{num_messages}msgs_{context}
        Example: 001_031333_1msgs_Please_write_a
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

        return f"{self._request_counter:03d}_{timestamp}_{msg_count}msgs_{context}"

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
