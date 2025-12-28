"""GLMNode - stateless node for Z.AI GLM API calls.

GLMNode makes HTTP requests to Z.AI's GLM API and returns structured results.
Each execution is independent - no state is maintained between calls.

Key features:
- Returns structured JSON with content/usage/error fields
- Errors are caught and returned in JSON (never raises)
- Built-in retry with exponential backoff for transient failures
- Supports string, messages array, or dict input formats
- Optional thinking mode for enhanced reasoning
- Optional request/response logging to files
- Auto-registers with session on creation
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

from nerve.core.nodes.llm.base import SingleShotLLMNode


def _find_project_root() -> Path | None:
    """Walk up from current file to find project root (contains pyproject.toml)."""
    current = Path(__file__).parent
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return None


@lru_cache(maxsize=1)
def _load_env_and_get_headers() -> dict[str, str]:
    """Load .env.local and return GLM headers. Cached to run once."""
    from dotenv import load_dotenv

    # Load .env.local from project root (if found)
    project_root = _find_project_root()
    if project_root:
        env_local = project_root / ".env.local"
        if env_local.exists():
            load_dotenv(env_local)

    # Build headers from environment
    x_nerve_version = os.getenv("X_NERVE_VERSION", "X-Nerve-Version")
    version = os.getenv("GLM_VERSION", "4.138.0")
    app_name = os.getenv("GLM_X_TITLE", "Nerve AI")

    return {
        "HTTP-Referer": os.getenv("GLM_HTTP_REFERER", "www.nerve.ai"),
        "X-Title": app_name,
        x_nerve_version: version,
        "User-Agent": f"{app_name}/{version}",
    }


@dataclass(repr=False)
class GLMNode(SingleShotLLMNode):
    """Stateless node for Z.AI GLM API calls.

    GLMNode is stateless - each execute() call makes an independent HTTP request.
    Returns structured dict with response content or error (never raises).

    Features:
    - Returns structured JSON with content/model/usage/error fields
    - Errors are caught and returned in JSON (never raises exceptions)
    - Built-in retry with exponential backoff for 429, 5xx errors
    - Configurable timeout, model, and API parameters
    - Optional thinking mode for chain-of-thought reasoning
    - Auto-registers with session on creation

    Tool Calling Notes:
    - tool_choice parameter works correctly (force specific tool, "none", "auto")
    - parallel_tool_calls=False is NOT respected by GLM - the model will still
      make parallel tool calls regardless of this setting. This appears to be
      a limitation of the Z.AI API endpoint.

    Args:
        id: Unique identifier for this node.
        session: Session to register this node with.
        api_key: Z.AI API key.
        model: Model identifier (e.g., "GLM-4.7", "GLM-4-Plus").
        base_url: API base URL (default: https://api.z.ai/api/coding/paas/v4).
        timeout: Request timeout in seconds.
        max_retries: Maximum retry attempts for retryable errors.
        retry_base_delay: Base delay between retries in seconds.
        retry_max_delay: Maximum delay between retries in seconds.
        thinking: Enable thinking/reasoning mode (adds thinking param to requests).
        metadata: Additional metadata for the node.

    Example:
        >>> session = Session("my-session")
        >>> llm = GLMNode(
        ...     id="glm",
        ...     session=session,
        ...     api_key="your-api-key",
        ...     model="GLM-4.7",
        ... )
        >>>
        >>> # Simple string prompt
        >>> ctx = ExecutionContext(session=session, input="What is 2+2?")
        >>> result = await llm.execute(ctx)
        >>> print(result["content"])
        "4"
        >>>
        >>> # With thinking mode enabled
        >>> llm_thinking = GLMNode(
        ...     id="glm-think",
        ...     session=session,
        ...     api_key="your-api-key",
        ...     model="GLM-4.7",
        ...     thinking=True,
        ... )
        >>> ctx = ExecutionContext(session=session, input="Solve this step by step: 15 * 23")
        >>> result = await llm_thinking.execute(ctx)
    """

    node_type: ClassVar[str] = "glm"

    # GLM-specific options
    thinking: bool = False  # Enable thinking/reasoning mode

    @classmethod
    def _get_default_base_url(cls) -> str:
        """Return Z.AI GLM's default API URL."""
        return "https://api.z.ai/api/coding/paas/v4"

    def _get_extra_headers(self) -> dict[str, str]:
        """Return Nerve-identifying headers for GLM API requests."""
        return _load_env_and_get_headers().copy()

    def _get_default_request_params(self) -> dict[str, Any]:
        """Return GLM-specific default parameters."""
        params: dict[str, Any] = {}
        if self.thinking:
            params["thinking"] = {"type": "enabled"}
        return params
