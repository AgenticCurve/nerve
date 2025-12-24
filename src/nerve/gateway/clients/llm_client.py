"""LLM client for upstream API calls.

Uses aiohttp.ClientSession for consistency with Nerve's HTTP transport.

Features:
- Circuit breaker for fault tolerance
- Retry with exponential backoff
- Both streaming and non-streaming requests
- Timeout handling
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import aiohttp

from nerve.gateway.transforms.openai import OpenAITransformer
from nerve.gateway.transforms.tool_id_mapper import ToolIDMapper
from nerve.gateway.transforms.types import (
    InternalResponse,
    StreamChunk,
    TokenUsage,
)

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = auto()  # Normal operation
    OPEN = auto()  # Failing, reject requests
    HALF_OPEN = auto()  # Testing recovery


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass


class UpstreamError(Exception):
    """Raised when upstream API returns an error."""

    def __init__(self, message: str, status_code: int, response_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


@dataclass
class LLMClientConfig:
    """Configuration for LLM client."""

    base_url: str
    api_key: str
    model: str

    # Timeouts (seconds)
    connect_timeout: float = 10.0
    read_timeout: float = 300.0

    # Retry configuration
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    retryable_status_codes: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    # Circuit breaker
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout: float = 30.0

    # Feature flags (provider-specific)
    supports_stream_usage: bool = True  # False for DeepSeek, Ollama


@dataclass
class CircuitBreaker:
    """Simple circuit breaker for upstream resilience.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests are rejected immediately
    - HALF_OPEN: Testing if service recovered, one request allowed
    """

    failure_threshold: int
    recovery_timeout: float
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0

    def record_success(self) -> None:
        """Record a successful request."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed request."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            logger.warning("Circuit breaker opened after %d failures", self.failure_count)
            self.state = CircuitState.OPEN

    def can_execute(self) -> bool:
        """Check if a request can be executed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                logger.info("Circuit breaker entering half-open state")
                self.state = CircuitState.HALF_OPEN
                return True
            return False

        # HALF_OPEN - allow one request
        return True


@dataclass
class LLMClient:
    """HTTP client for upstream LLM APIs.

    Provides both streaming and non-streaming methods.
    Uses aiohttp for HTTP (matches Nerve's existing patterns).
    """

    config: LLMClientConfig
    _session: aiohttp.ClientSession | None = None
    _circuit: CircuitBreaker = field(default_factory=lambda: CircuitBreaker(5, 30.0))

    # Event callbacks (for observability)
    on_request_start: Callable[[str, str], Awaitable[None]] | None = None
    on_request_complete: Callable[[str, float, TokenUsage | None], Awaitable[None]] | None = None
    on_request_failed: Callable[[str, str, int], Awaitable[None]] | None = None

    async def connect(self) -> None:
        """Initialize HTTP client and circuit breaker."""
        timeout = aiohttp.ClientTimeout(
            connect=self.config.connect_timeout,
            total=self.config.read_timeout,
        )
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        self._circuit = CircuitBreaker(
            failure_threshold=self.config.circuit_failure_threshold,
            recovery_timeout=self.config.circuit_recovery_timeout,
        )

    async def close(self) -> None:
        """Close HTTP client."""
        if self._session:
            await self._session.close()
            self._session = None

    async def send(
        self,
        request_body: dict[str, Any],
        trace_id: str | None = None,
    ) -> InternalResponse:
        """Non-streaming request.

        Args:
            request_body: OpenAI-format request body (stream should be False)
            trace_id: Optional trace ID for correlation

        Returns:
            InternalResponse with complete response

        Raises:
            CircuitOpenError: If circuit breaker is open
            UpstreamError: If upstream returns an error
        """
        trace_id = trace_id or f"req_{int(time.time() * 1000)}"

        if not self._circuit.can_execute():
            raise CircuitOpenError("Circuit breaker is open")

        # Ensure stream is False
        request_body = {**request_body, "stream": False}

        start_time = time.time()
        if self.on_request_start:
            await self.on_request_start(trace_id, self.config.model)

        try:
            response_data = await self._execute_with_retry(request_body, trace_id)
            self._circuit.record_success()

            # Parse response
            transformer = OpenAITransformer()
            mapper = ToolIDMapper()  # Dummy mapper for non-streaming
            result = transformer.from_upstream(response_data, mapper)

            duration = time.time() - start_time
            if self.on_request_complete:
                await self.on_request_complete(trace_id, duration, result.usage)

            return result

        except Exception as e:
            self._circuit.record_failure()
            if self.on_request_failed:
                status = getattr(e, "status_code", 0)
                await self.on_request_failed(trace_id, str(e), status)
            raise

    async def stream(
        self,
        request_body: dict[str, Any],
        trace_id: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming request.

        Args:
            request_body: OpenAI-format request body (stream should be True)
            trace_id: Optional trace ID for correlation

        Yields:
            StreamChunk for each piece of the response

        Raises:
            CircuitOpenError: If circuit breaker is open
            UpstreamError: If upstream returns an error
        """
        trace_id = trace_id or f"req_{int(time.time() * 1000)}"

        if not self._circuit.can_execute():
            raise CircuitOpenError("Circuit breaker is open")

        # Ensure stream is True
        request_body = {**request_body, "stream": True}

        start_time = time.time()
        if self.on_request_start:
            await self.on_request_start(trace_id, self.config.model)

        transformer = OpenAITransformer()
        mapper = ToolIDMapper()  # Will be passed through from caller
        total_usage: TokenUsage | None = None

        try:
            async for chunk in self._stream_with_retry(request_body, trace_id, transformer, mapper):
                if chunk.usage:
                    total_usage = chunk.usage
                yield chunk

            self._circuit.record_success()

            duration = time.time() - start_time
            if self.on_request_complete:
                await self.on_request_complete(trace_id, duration, total_usage)

        except Exception as e:
            self._circuit.record_failure()
            if self.on_request_failed:
                status = getattr(e, "status_code", 0)
                await self.on_request_failed(trace_id, str(e), status)
            raise

    async def _execute_with_retry(
        self,
        request_body: dict[str, Any],
        trace_id: str,
    ) -> dict[str, Any]:
        """Execute request with retry logic."""
        last_error: Exception | None = None
        url = f"{self.config.base_url}/chat/completions"

        for attempt in range(self.config.max_retries + 1):
            try:
                if self._session is None:
                    raise RuntimeError("Client not connected. Call connect() first.")

                async with self._session.post(
                    url,
                    json=request_body,
                ) as response:
                    if response.status == 200:
                        return await response.json()

                    # Read error body
                    error_body = await response.text()

                    # Check if retryable
                    if response.status in self.config.retryable_status_codes:
                        last_error = UpstreamError(
                            f"Upstream returned {response.status}",
                            response.status,
                            error_body,
                        )
                        # Calculate backoff delay
                        delay = min(
                            self.config.retry_base_delay * (2**attempt),
                            self.config.retry_max_delay,
                        )
                        logger.warning(
                            "Request %s failed with %d, retrying in %.1fs (attempt %d/%d)",
                            trace_id,
                            response.status,
                            delay,
                            attempt + 1,
                            self.config.max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue

                    # Non-retryable error
                    raise UpstreamError(
                        f"Upstream returned {response.status}: {error_body}",
                        response.status,
                        error_body,
                    )

            except aiohttp.ClientError as e:
                last_error = e
                if attempt < self.config.max_retries:
                    delay = min(
                        self.config.retry_base_delay * (2**attempt),
                        self.config.retry_max_delay,
                    )
                    logger.warning(
                        "Request %s failed with %s, retrying in %.1fs (attempt %d/%d)",
                        trace_id,
                        type(e).__name__,
                        delay,
                        attempt + 1,
                        self.config.max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        if last_error:
            raise last_error
        raise RuntimeError("Retry loop exited without result or error")

    async def _stream_with_retry(
        self,
        request_body: dict[str, Any],
        trace_id: str,
        transformer: OpenAITransformer,
        mapper: ToolIDMapper,
    ) -> AsyncIterator[StreamChunk]:
        """Stream response with retry logic.

        Note: Streaming retries only work for initial connection failures.
        Once streaming starts, we cannot retry mid-stream.
        """
        last_error: Exception | None = None
        url = f"{self.config.base_url}/chat/completions"

        for attempt in range(self.config.max_retries + 1):
            try:
                if self._session is None:
                    raise RuntimeError("Client not connected. Call connect() first.")

                async with self._session.post(
                    url,
                    json=request_body,
                ) as response:
                    if response.status != 200:
                        error_body = await response.text()
                        logger.error(
                            "[%s] Upstream error %d: %s",
                            trace_id,
                            response.status,
                            error_body[:500],
                        )
                        if response.status in self.config.retryable_status_codes:
                            last_error = UpstreamError(
                                f"Upstream returned {response.status}",
                                response.status,
                                error_body,
                            )
                            delay = min(
                                self.config.retry_base_delay * (2**attempt),
                                self.config.retry_max_delay,
                            )
                            logger.warning(
                                "Stream %s failed with %d, retrying in %.1fs",
                                trace_id,
                                response.status,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise UpstreamError(
                            f"Upstream returned {response.status}",
                            response.status,
                            error_body,
                        )

                    # Successful connection - start streaming
                    transformer.reset()
                    logger.debug("[%s] Starting to receive SSE stream", trace_id)
                    line_count = 0
                    async for line in response.content:
                        line_str = line.decode("utf-8").strip()
                        if not line_str:
                            continue

                        line_count += 1
                        logger.debug("[%s] SSE line %d: %s", trace_id, line_count, line_str[:200])

                        # Parse SSE chunks
                        chunks = transformer.parse_sse_chunk(line_str, mapper)
                        for chunk in chunks:
                            logger.debug(
                                "[%s] Parsed chunk: type=%s content=%s",
                                trace_id,
                                chunk.type,
                                chunk.content[:50] if chunk.content else "",
                            )
                            yield chunk

                    logger.debug("[%s] Stream complete, received %d lines", trace_id, line_count)
                    return  # Successfully completed

            except aiohttp.ClientError as e:
                last_error = e
                if attempt < self.config.max_retries:
                    delay = min(
                        self.config.retry_base_delay * (2**attempt),
                        self.config.retry_max_delay,
                    )
                    logger.warning(
                        "Stream %s failed with %s, retrying in %.1fs",
                        trace_id,
                        type(e).__name__,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        if last_error:
            raise last_error
