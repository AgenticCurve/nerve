"""SingleShotLLMNode - abstract base class for stateless LLM API nodes.

This module provides the common implementation for LLM nodes that use
OpenAI-compatible chat completion APIs. Each execute() call is independent -
no conversation state is maintained between calls.

Provider-specific nodes (OpenRouterNode, GLMNode) inherit from SingleShotLLMNode
and only need to specify their defaults and any custom headers.

For multi-turn conversations with tool support, use LLMChatNode instead.

Key features:
- Stateless: each execute() is independent
- Returns structured JSON with content/usage/error fields
- Errors are caught and returned in JSON (never raises)
- Built-in retry with exponential backoff for transient failures
- Supports string, messages array, or dict input formats
- Optional request/response logging to files
- Auto-registers with session on creation
- Supports multiple HTTP backends: aiohttp (default) or openai SDK
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal

import aiohttp

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.context import ExecutionContext
from nerve.gateway.tracing import RequestTracer

if TYPE_CHECKING:
    from openai import AsyncOpenAI

    from nerve.core.session.session import Session

# Valid HTTP backend choices
HttpBackend = Literal["aiohttp", "openai"]

# Status codes that should trigger a retry
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Error type mapping based on HTTP status codes
ERROR_TYPE_MAP = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    429: "rate_limit_error",
}


def _get_error_type(status_code: int) -> str:
    """Map HTTP status code to error type string."""
    if status_code in ERROR_TYPE_MAP:
        return ERROR_TYPE_MAP[status_code]
    if 500 <= status_code < 600:
        return "api_error"
    return "unknown_error"


def _truncate_messages(
    messages: list[dict[str, Any]], max_chars: int = 200
) -> list[dict[str, Any]]:
    """Truncate message content for logging."""
    truncated = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > max_chars:
            content = content[:max_chars] + "..."
        truncated.append({**msg, "content": content})
    return truncated


@dataclass
class SingleShotLLMNode:
    """Abstract base class for stateless OpenAI-compatible LLM API nodes.

    Each execute() call is independent - no conversation state is maintained.
    For multi-turn conversations, use LLMChatNode which wraps this.

    Subclasses should:
    1. Set the `node_type` class variable
    2. Override `_get_default_base_url()` to return the provider's default URL
    3. Override `_get_extra_headers()` if custom headers are needed

    All common functionality (execute, retry, logging, etc.) is inherited.
    """

    # Class variable for node type identification
    node_type: ClassVar[str] = "base_llm"

    # Required fields (no defaults)
    id: str
    session: Session
    api_key: str
    model: str

    # Optional configuration fields (with defaults)
    base_url: str | None = None  # If None, uses _get_default_base_url()
    timeout: float = 120.0  # LLM calls can be slow
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)

    # Debug: save raw requests/responses to files
    debug_dir: str | None = None

    # HTTP backend: "aiohttp" (default) or "openai" (uses OpenAI SDK)
    http_backend: HttpBackend = "aiohttp"

    # Internal fields (not in __init__)
    persistent: bool = field(default=False, init=False)
    _session_holder: aiohttp.ClientSession | None = field(default=None, init=False, repr=False)
    _openai_client: AsyncOpenAI | None = field(default=None, init=False, repr=False)
    _session_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _tracer: RequestTracer = field(init=False, repr=False)
    _resolved_base_url: str = field(init=False, repr=False)

    @classmethod
    @abstractmethod
    def _get_default_base_url(cls) -> str:
        """Return the default base URL for this provider.

        Subclasses must implement this to provide their default API endpoint.
        """
        ...

    def _get_extra_headers(self) -> dict[str, str]:
        """Return provider-specific headers.

        Subclasses can override to add custom headers (e.g., OpenRouter's HTTP-Referer).
        Default implementation returns empty dict.
        """
        return {}

    def _get_default_request_params(self) -> dict[str, Any]:
        """Return default parameters to include in every request.

        Subclasses can override to inject provider-specific defaults
        (e.g., GLM's thinking mode). These are merged into the request body
        but can be overridden by explicit input parameters.

        Default implementation returns empty dict.
        """
        return {}

    def __post_init__(self) -> None:
        """Validate and register with session."""
        from nerve.core.validation import validate_name

        # Resolve base URL
        self._resolved_base_url = self.base_url or self._get_default_base_url()

        # Validate node ID
        validate_name(self.id, "node")

        # Check for duplicates
        if self.id in self.session.nodes:
            raise ValueError(f"Node '{self.id}' already exists in session '{self.session.name}'")

        # Auto-register with session
        self.session.nodes[self.id] = self

        # Initialize request tracer for logging
        # Build nested path: {debug_dir}/{server_name}/{session_name}/{node_id}/
        tracer_dir = None
        if self.debug_dir:
            from pathlib import Path

            server_name = self.session.server_name or "local"
            session_name = self.session.name
            tracer_dir = Path(self.debug_dir) / server_name / session_name / self.id

        self._tracer = RequestTracer(debug_dir=tracer_dir)

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Execute an LLM request and return structured result.

        Args:
            context: Execution context with input. Input can be:
                - str: Simple prompt, wrapped as user message
                - list: Messages array (OpenAI format)
                - dict: Full request with "messages" key and optional params

        Returns:
            JSON dict with fields:
            - success (bool): Whether request succeeded
            - content (str | None): Response content
            - model (str | None): Model that generated response
            - finish_reason (str | None): Why generation stopped
            - usage (dict | None): Token usage counts
            - request (dict): Echo of request info (truncated)
            - error (str | None): Error message if failed
            - error_type (str | None): Error classification
            - retries (int): Number of retries attempted

        Note:
            This method never raises exceptions - all errors are returned
            in the result dict.
        """
        # Initialize result structure
        result: dict[str, Any] = {
            "success": False,
            "content": None,
            "model": None,
            "finish_reason": None,
            "usage": None,
            "request": {},
            "error": None,
            "error_type": None,
            "retries": 0,
        }

        trace_id: str | None = None

        try:
            # Parse input into messages and extra params
            messages, extra_params = self._parse_input(context.input)

            if not messages:
                result["error"] = "No messages provided in context.input"
                result["error_type"] = "invalid_request_error"
                return result

            # Build request body with default params (extra_params override defaults)
            request_body = {
                "model": self.model,
                "messages": messages,
                **self._get_default_request_params(),
                **extra_params,
            }

            # Generate trace ID and log raw request body
            trace_id = self._tracer.generate_trace_id(request_body)
            self._tracer.save_debug(trace_id, "request.json", request_body)

            # Store request info for debugging (truncated)
            result["request"] = {
                "model": self.model,
                "messages": _truncate_messages(messages),
            }

            # Execute with retry
            response_data, retries = await self._execute_with_retry(request_body)
            result["retries"] = retries

            # Log raw response body
            self._tracer.save_debug(trace_id, "response.json", response_data)

            # Parse response
            if "choices" in response_data and response_data["choices"]:
                choice = response_data["choices"][0]
                message = choice.get("message", {})
                result["content"] = message.get("content")
                result["finish_reason"] = choice.get("finish_reason")

            result["model"] = response_data.get("model", self.model)

            if "usage" in response_data:
                result["usage"] = {
                    "prompt_tokens": response_data["usage"].get("prompt_tokens", 0),
                    "completion_tokens": response_data["usage"].get("completion_tokens", 0),
                    "total_tokens": response_data["usage"].get("total_tokens", 0),
                }

            result["success"] = True

        except _UpstreamError as e:
            result["error"] = e.message
            result["error_type"] = e.error_type
            result["retries"] = e.retries
            if trace_id:
                self._tracer.save_debug(
                    trace_id,
                    "error.json",
                    {
                        "status_code": e.status_code,
                        "message": e.message,
                        "error_type": e.error_type,
                        "retries": e.retries,
                    },
                )

        except aiohttp.ClientError as e:
            result["error"] = f"Network error: {e}"
            result["error_type"] = "network_error"
            if trace_id:
                self._tracer.save_debug(
                    trace_id,
                    "error.json",
                    {
                        "error_type": "network_error",
                        "message": str(e),
                    },
                )

        except TimeoutError:
            result["error"] = f"Request timed out after {self.timeout}s"
            result["error_type"] = "timeout"
            if trace_id:
                self._tracer.save_debug(
                    trace_id,
                    "error.json",
                    {
                        "error_type": "timeout",
                        "timeout": self.timeout,
                    },
                )

        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
            result["error_type"] = "internal_error"
            if trace_id:
                self._tracer.save_debug(
                    trace_id,
                    "error.json",
                    {
                        "error_type": "internal_error",
                        "exception": type(e).__name__,
                        "message": str(e),
                    },
                )

        return result

    def _parse_input(self, input_data: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Parse context.input into messages and extra parameters.

        Args:
            input_data: The context.input value

        Returns:
            Tuple of (messages, extra_params)
        """
        if input_data is None:
            return [], {}

        if isinstance(input_data, str):
            # Simple string prompt
            return [{"role": "user", "content": input_data}], {}

        if isinstance(input_data, list):
            # Messages array
            return input_data, {}

        if isinstance(input_data, dict):
            # Dict with messages and optional extra params
            messages = input_data.get("messages", [])
            extra_params = {k: v for k, v in input_data.items() if k != "messages"}
            return messages, extra_params

        # Fallback: convert to string
        return [{"role": "user", "content": str(input_data)}], {}

    def _get_all_headers(self) -> dict[str, str]:
        """Get all headers including provider-specific headers.

        Subclasses can override _get_extra_headers() to add custom headers.
        """
        return self._get_extra_headers()

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session (lazy initialization)."""
        async with self._session_lock:
            if self._session_holder is None or self._session_holder.closed:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    **self._get_all_headers(),
                }

                self._session_holder = aiohttp.ClientSession(
                    headers=headers,
                    timeout=timeout,
                )
            return self._session_holder

    async def _get_openai_client(self) -> AsyncOpenAI:
        """Get or create OpenAI async client (lazy initialization)."""
        async with self._session_lock:
            if self._openai_client is None:
                from openai import AsyncOpenAI

                self._openai_client = AsyncOpenAI(
                    base_url=self._resolved_base_url,
                    api_key=self.api_key,
                    timeout=self.timeout,
                    max_retries=self.max_retries,
                    default_headers=self._get_all_headers(),
                )
            return self._openai_client

    async def _execute_with_retry(
        self,
        request_body: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        """Execute request with exponential backoff retry.

        Args:
            request_body: The JSON request body

        Returns:
            Tuple of (response_data, retry_count)

        Raises:
            _UpstreamError: For non-retryable API errors
            aiohttp.ClientError: For network errors after retries exhausted
        """
        if self.http_backend == "openai":
            return await self._execute_with_openai_sdk(request_body)
        else:
            return await self._execute_with_aiohttp(request_body)

    async def _execute_with_openai_sdk(
        self,
        request_body: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        """Execute request using OpenAI SDK (has built-in retry)."""
        from openai import APIConnectionError, APIStatusError

        client = await self._get_openai_client()

        try:
            # Extract messages and other params
            messages = request_body.pop("messages")
            model = request_body.pop("model")

            # Call OpenAI SDK
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                **request_body,
            )

            # Convert to dict format matching our expected structure
            response_dict = response.model_dump()
            return response_dict, 0  # OpenAI SDK handles retries internally

        except APIStatusError as e:
            raise _UpstreamError(
                status_code=e.status_code,
                message=f"API error ({e.status_code}): {e.message}",
                error_type=_get_error_type(e.status_code),
                retries=0,
            ) from e
        except APIConnectionError as e:
            raise aiohttp.ClientError(f"Connection error: {e}") from e

    async def _execute_with_aiohttp(
        self,
        request_body: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        """Execute request using aiohttp with manual retry logic."""
        url = f"{self._resolved_base_url.rstrip('/')}/chat/completions"
        last_error: Exception | None = None
        retries = 0

        for attempt in range(self.max_retries + 1):
            try:
                session = await self._get_http_session()
                async with session.post(url, json=request_body) as response:
                    if response.status == 200:
                        return await response.json(), retries

                    # Read error body
                    try:
                        error_body = await response.json()
                        error_message = error_body.get("error", {}).get("message", str(error_body))
                    except Exception:
                        error_message = await response.text()

                    # Check if retryable
                    if response.status in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                        retries = attempt + 1
                        delay = min(
                            self.retry_base_delay * (2**attempt),
                            self.retry_max_delay,
                        )
                        await asyncio.sleep(delay)
                        continue

                    # Non-retryable error
                    raise _UpstreamError(
                        status_code=response.status,
                        message=f"API error ({response.status}): {error_message}",
                        error_type=_get_error_type(response.status),
                        retries=retries,
                    )

            except aiohttp.ClientError as e:
                last_error = e
                if attempt < self.max_retries:
                    retries = attempt + 1
                    delay = min(
                        self.retry_base_delay * (2**attempt),
                        self.retry_max_delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        # Should not reach here, but handle edge case
        if last_error:
            raise last_error
        raise RuntimeError("Retry loop exited without result")

    async def interrupt(self) -> None:
        """No-op for HTTP requests.

        HTTP requests cannot be interrupted mid-flight.
        This method exists for Node protocol compatibility.
        """
        pass

    async def close(self) -> None:
        """Close HTTP session/client (optional cleanup).

        Call this when done using the node to release resources.
        The session/client will be recreated on next execute() if needed.
        """
        async with self._session_lock:
            if self._session_holder and not self._session_holder.closed:
                await self._session_holder.close()
                self._session_holder = None
            if self._openai_client is not None:
                await self._openai_client.close()
                self._openai_client = None

    def to_info(self) -> NodeInfo:
        """Get node information.

        Returns:
            NodeInfo for this node.
        """
        return NodeInfo(
            id=self.id,
            node_type=self.node_type,
            state=NodeState.READY,  # Ephemeral nodes are always ready
            persistent=self.persistent,
            metadata={
                "model": self.model,
                "base_url": self._resolved_base_url,
                "timeout": self.timeout,
                "max_retries": self.max_retries,
                "http_backend": self.http_backend,
                **self.metadata,
            },
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id!r}, model={self.model!r})"


class _UpstreamError(Exception):
    """Internal error for upstream API failures."""

    def __init__(
        self,
        status_code: int,
        message: str,
        error_type: str,
        retries: int = 0,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        self.retries = retries
