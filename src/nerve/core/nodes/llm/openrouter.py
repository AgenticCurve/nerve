"""OpenRouterNode - stateless node for OpenRouter LLM API calls.

OpenRouterNode makes HTTP requests to OpenRouter's API and returns structured results.
Each execution is independent - no state is maintained between calls.

Key features:
- Returns structured JSON with content/usage/error fields
- Errors are caught and returned in JSON (never raises)
- Built-in retry with exponential backoff for transient failures
- Supports string, messages array, or dict input formats
- Optional request/response logging to files
- Auto-registers with session on creation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from nerve.core.nodes.llm.base import StatelessLLMNode

if TYPE_CHECKING:
    pass


@dataclass(repr=False)
class OpenRouterNode(StatelessLLMNode):
    """Stateless node for OpenRouter LLM API calls.

    OpenRouterNode is stateless - each execute() call makes an independent HTTP request.
    Returns structured dict with response content or error (never raises).

    Features:
    - Returns structured JSON with content/model/usage/error fields
    - Errors are caught and returned in JSON (never raises exceptions)
    - Built-in retry with exponential backoff for 429, 5xx errors
    - Configurable timeout, model, and API parameters
    - Auto-registers with session on creation

    Args:
        id: Unique identifier for this node.
        session: Session to register this node with.
        api_key: OpenRouter API key.
        model: Model identifier (e.g., "anthropic/claude-3-opus").
        base_url: API base URL (default: https://openrouter.ai/api/v1).
        timeout: Request timeout in seconds.
        max_retries: Maximum retry attempts for retryable errors.
        retry_base_delay: Base delay between retries in seconds.
        retry_max_delay: Maximum delay between retries in seconds.
        http_referer: Optional HTTP-Referer header for OpenRouter rankings.
        x_title: Optional X-Title header for OpenRouter rankings.
        metadata: Additional metadata for the node.

    Example:
        >>> session = Session("my-session")
        >>> llm = OpenRouterNode(
        ...     id="llm",
        ...     session=session,
        ...     api_key="sk-or-...",
        ...     model="anthropic/claude-3-haiku",
        ... )
        >>>
        >>> # Simple string prompt
        >>> ctx = ExecutionContext(session=session, input="What is 2+2?")
        >>> result = await llm.execute(ctx)
        >>> print(result)
        {
            "success": True,
            "content": "2 + 2 equals 4.",
            "model": "anthropic/claude-3-haiku",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            "request": {"model": "anthropic/claude-3-haiku", "messages": [...]},
            "error": None,
            "error_type": None,
            "retries": 0
        }
        >>>
        >>> # Messages array input
        >>> ctx = ExecutionContext(session=session, input=[
        ...     {"role": "system", "content": "You are helpful."},
        ...     {"role": "user", "content": "Hello!"},
        ... ])
        >>> result = await llm.execute(ctx)
    """

    node_type: ClassVar[str] = "openrouter"

    # OpenRouter-specific optional headers
    http_referer: str | None = None
    x_title: str | None = None

    @classmethod
    def _get_default_base_url(cls) -> str:
        """Return OpenRouter's default API URL."""
        return "https://openrouter.ai/api/v1"

    def _get_extra_headers(self) -> dict[str, str]:
        """Return OpenRouter-specific headers for rankings."""
        headers: dict[str, str] = {}
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        if self.x_title:
            headers["X-Title"] = self.x_title
        return headers
