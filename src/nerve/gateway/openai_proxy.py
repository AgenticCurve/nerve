"""OpenAI upstream proxy server.

Exposes /v1/messages endpoint that accepts Anthropic Messages API format
and proxies requests to an OpenAI-compatible upstream LLM API.

This is a standalone server (not integrated with NerveEngine) that:
1. Accepts Anthropic format requests from Claude Code CLI
2. Transforms to OpenAI format
3. Forwards to upstream LLM API
4. Transforms responses back to Anthropic format
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp import web

from nerve.gateway.clients.llm_client import (
    CircuitOpenError,
    LLMClient,
    LLMClientConfig,
    UpstreamError,
)
from nerve.gateway.errors import ERROR_TYPE_MAP
from nerve.gateway.tracing import RequestTracer
from nerve.gateway.transforms.anthropic import AnthropicTransformer
from nerve.gateway.transforms.openai import OpenAITransformer
from nerve.gateway.transforms.tool_id_mapper import ToolIDMapper
from nerve.gateway.transforms.types import StreamChunk
from nerve.gateway.transforms.validation import validate_request

logger = logging.getLogger(__name__)


@dataclass
class OpenAIProxyConfig:
    """Configuration for OpenAI upstream proxy server."""

    host: str = "127.0.0.1"
    port: int = 3456

    # Upstream configuration
    upstream_base_url: str = ""
    upstream_api_key: str = ""
    upstream_model: str = ""

    # Client configuration
    connect_timeout: float = 10.0
    read_timeout: float = 300.0
    max_retries: int = 3

    # Request limits
    max_body_size: int = 500 * 1024 * 1024  # 500MB

    # Debug: save raw requests/responses to files
    debug_dir: str | None = None  # e.g., "/tmp/nerve-proxy-debug"


@dataclass
class OpenAIProxyServer:
    """Transport that accepts Anthropic Messages API requests
    and proxies them to an OpenAI-compatible upstream.

    Follows HTTPServer patterns from nerve/transport/http.py.

    Example:
        >>> config = OpenAIProxyConfig(
        ...     upstream_base_url="https://api.openai.com/v1",
        ...     upstream_api_key="sk-...",
        ...     upstream_model="gpt-4o",
        ... )
        >>> server = OpenAIProxyServer(config=config)
        >>> await server.serve()
    """

    config: OpenAIProxyConfig
    _app: Any = None  # aiohttp.web.Application
    _runner: Any = None  # aiohttp.web.AppRunner
    _client: LLMClient | None = None
    _shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)
    _tracer: RequestTracer = field(init=False)

    def __post_init__(self) -> None:
        """Initialize tracer with debug directory from config."""
        self._tracer = RequestTracer(debug_dir=self.config.debug_dir)

    def _generate_trace_id(self, body: dict[str, Any]) -> str:
        """Generate a human-readable trace ID with sequence number and context."""
        # Use the shared tracer to generate trace ID
        return self._tracer.generate_trace_id(body)

    def _save_debug(self, trace_id: str, filename: str, data: Any) -> None:
        """Save debug data to JSON file if debug_dir is configured."""
        # Use the shared tracer to save debug data
        self._tracer.save_debug(trace_id, filename, data)

    async def serve(self) -> None:
        """Start the proxy server."""
        try:
            from aiohttp import web
        except ImportError as err:
            raise ImportError(
                "aiohttp is required for the proxy. Install with: pip install nerve[proxy]"
            ) from err

        # Initialize upstream client
        self._client = LLMClient(
            config=LLMClientConfig(
                base_url=self.config.upstream_base_url,
                api_key=self.config.upstream_api_key,
                model=self.config.upstream_model,
                connect_timeout=self.config.connect_timeout,
                read_timeout=self.config.read_timeout,
                max_retries=self.config.max_retries,
            )
        )
        await self._client.connect()

        # Setup aiohttp app
        self._app = web.Application(client_max_size=self.config.max_body_size)
        self._app.router.add_post("/v1/messages", self._handle_messages)
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_post("/api/shutdown", self._handle_shutdown)

        # Start server
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()
        logger.info(
            "Anthropic proxy listening on %s:%s -> %s",
            self.config.host,
            self.config.port,
            self.config.upstream_base_url,
        )

        # Wait for shutdown signal
        await self._shutdown_event.wait()
        logger.info("Anthropic proxy shutdown requested")
        await self.stop()

    async def stop(self) -> None:
        """Stop the proxy server."""
        if self._client:
            await self._client.close()
            self._client = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def _handle_messages(self, request: web.Request) -> web.StreamResponse:
        """Handle POST /v1/messages - main proxy endpoint."""
        # Header validation
        content_type = request.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            return self._error_response(
                "invalid_request_error",
                f"Content-Type must be application/json, got: {content_type}",
                400,
            )

        # Parse request body
        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            return self._error_response(
                "invalid_request_error",
                f"Invalid JSON: {e}",
                400,
            )

        # Generate human-readable trace ID with context from request
        trace_id = self._generate_trace_id(body)

        # Log anthropic-version for debugging
        anthropic_version = request.headers.get("anthropic-version", "unknown")
        logger.debug("[%s] anthropic-version: %s", trace_id, anthropic_version)
        logger.info("[%s] Incoming request from Claude Code", trace_id)

        # Validate request
        validation_errors = validate_request(body)
        if validation_errors:
            return self._error_response(
                "invalid_request_error",
                "; ".join(validation_errors),
                400,
            )

        # Save raw Anthropic request from Claude Code
        self._save_debug(trace_id, "1_anthropic_request.json", body)

        # Create request-scoped ToolIDMapper
        tool_id_mapper = ToolIDMapper()

        # Transform request: Anthropic -> Internal -> OpenAI
        anthropic_transformer = AnthropicTransformer()
        openai_transformer = OpenAITransformer()

        internal_request = anthropic_transformer.to_internal(body)
        openai_request = openai_transformer.to_upstream(
            internal_request,
            self.config.upstream_model,
            tool_id_mapper,
        )

        # Log request details
        requested_model = body.get("model", "unknown")
        message_count = len(body.get("messages", []))
        logger.info(
            "[%s] Request: model=%s, messages=%d, stream=%s -> forwarding to %s (%s)",
            trace_id,
            requested_model,
            message_count,
            body.get("stream", True),
            self.config.upstream_base_url,
            self.config.upstream_model,
        )

        # Save transformed OpenAI request
        self._save_debug(trace_id, "2_openai_request.json", openai_request)
        logger.debug(
            "[%s] Transformed OpenAI request: %s",
            trace_id,
            json.dumps(openai_request, indent=2, default=str),
        )

        # Handle streaming vs non-streaming
        is_streaming = body.get("stream", True)

        if is_streaming:
            return await self._handle_streaming(
                request,
                openai_request,
                tool_id_mapper,
                trace_id,
                body,
            )
        else:
            return await self._handle_non_streaming(
                openai_request,
                tool_id_mapper,
                trace_id,
                body,
            )

    async def _handle_streaming(
        self,
        request: web.Request,
        openai_request: dict[str, Any],
        tool_id_mapper: ToolIDMapper,
        trace_id: str,
        original_body: dict[str, Any],
    ) -> web.StreamResponse:
        """Handle streaming response."""
        from aiohttp import web

        if not self._client:
            return self._error_response("api_error", "Upstream client not initialized", 503)

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Trace-Id": trace_id,
            },
        )
        await response.prepare(request)

        anthropic_transformer = AnthropicTransformer()
        request_model = original_body.get("model", self.config.upstream_model)

        # Track state for proper SSE event generation
        has_sent_message_start = False
        text_block_started = False
        current_block_index = 0

        # Collect chunks for debug logging
        debug_chunks: list[dict[str, Any]] = []

        try:
            async for chunk in self._client.stream(openai_request, trace_id):
                # Save chunk for debug
                debug_chunks.append(
                    {
                        "type": chunk.type,
                        "content": chunk.content,
                        "tool_name": chunk.tool_name,
                        "tool_call_id": chunk.tool_call_id,
                        "tool_arguments_delta": chunk.tool_arguments_delta,
                        "index": chunk.index,
                    }
                )
                # Generate proper Anthropic SSE event sequence
                if not has_sent_message_start:
                    # Send message_start first
                    start_chunk = StreamChunk(
                        type="message_start",
                        usage=chunk.usage,
                    )
                    sse_bytes = anthropic_transformer.chunk_to_sse(
                        start_chunk, tool_id_mapper, request_model
                    )
                    await response.write(sse_bytes)
                    has_sent_message_start = True

                # Handle text content
                if chunk.type == "text" and chunk.content:
                    if not text_block_started:
                        # Send content_block_start for text
                        start_chunk = StreamChunk(
                            type="content_block_start",
                            index=current_block_index,
                        )
                        sse_bytes = anthropic_transformer.chunk_to_sse(
                            start_chunk, tool_id_mapper, request_model
                        )
                        await response.write(sse_bytes)
                        text_block_started = True

                    # Send text delta
                    sse_bytes = anthropic_transformer.chunk_to_sse(
                        chunk, tool_id_mapper, request_model
                    )
                    await response.write(sse_bytes)

                # Handle tool calls
                elif chunk.type == "tool_call_start":
                    # Close text block if open
                    if text_block_started:
                        stop_chunk = StreamChunk(
                            type="content_block_stop",
                            index=current_block_index,
                        )
                        sse_bytes = anthropic_transformer.chunk_to_sse(
                            stop_chunk, tool_id_mapper, request_model
                        )
                        await response.write(sse_bytes)
                        text_block_started = False
                        current_block_index += 1

                    # Start tool use block
                    chunk = StreamChunk(
                        type="content_block_start",
                        tool_name=chunk.tool_name,
                        tool_call_id=chunk.tool_call_id,
                        index=current_block_index,
                    )
                    sse_bytes = anthropic_transformer.chunk_to_sse(
                        chunk, tool_id_mapper, request_model
                    )
                    await response.write(sse_bytes)

                elif chunk.type == "tool_call_delta":
                    delta_chunk = StreamChunk(
                        type="content_block_delta",
                        tool_arguments_delta=chunk.tool_arguments_delta,
                        index=current_block_index,
                    )
                    sse_bytes = anthropic_transformer.chunk_to_sse(
                        delta_chunk, tool_id_mapper, request_model
                    )
                    await response.write(sse_bytes)

                elif chunk.type == "tool_call_end":
                    stop_chunk = StreamChunk(
                        type="content_block_stop",
                        index=current_block_index,
                    )
                    sse_bytes = anthropic_transformer.chunk_to_sse(
                        stop_chunk, tool_id_mapper, request_model
                    )
                    await response.write(sse_bytes)
                    current_block_index += 1

                elif chunk.type == "done":
                    # Close any open text block
                    if text_block_started:
                        stop_chunk = StreamChunk(
                            type="content_block_stop",
                            index=current_block_index,
                        )
                        sse_bytes = anthropic_transformer.chunk_to_sse(
                            stop_chunk, tool_id_mapper, request_model
                        )
                        await response.write(sse_bytes)

                    # Log completion with usage
                    if chunk.usage:
                        logger.info(
                            "[%s] Response complete: input_tokens=%s, output_tokens=%s",
                            trace_id,
                            chunk.usage.input_tokens,
                            chunk.usage.output_tokens,
                        )
                    else:
                        logger.info("[%s] Response complete (no usage info)", trace_id)

                    # Send message_delta and message_stop
                    done_chunk = StreamChunk(
                        type="done",
                        usage=chunk.usage,
                    )
                    sse_bytes = anthropic_transformer.chunk_to_sse(
                        done_chunk, tool_id_mapper, request_model
                    )
                    await response.write(sse_bytes)

        except CircuitOpenError:
            logger.warning("[%s] Circuit breaker is open", trace_id)
            error_sse = self._format_error_sse("api_error", "Service temporarily unavailable")
            await response.write(error_sse)
        except UpstreamError as e:
            logger.error("[%s] Upstream error: %s", trace_id, e)
            error_type = ERROR_TYPE_MAP.get(e.status_code, "api_error")
            error_sse = self._format_error_sse(error_type, str(e))
            await response.write(error_sse)
        except (ConnectionResetError, BrokenPipeError):
            # Client disconnected - this is normal
            logger.debug("[%s] Client disconnected during streaming", trace_id)
        except Exception as e:
            if "closing transport" in str(e).lower():
                # Client disconnected - this is normal
                logger.debug("[%s] Client disconnected during streaming", trace_id)
            else:
                logger.exception("[%s] Unexpected error during streaming", trace_id)
                error_sse = self._format_error_sse("api_error", f"Internal error: {e}")
                try:
                    await response.write(error_sse)
                except Exception:
                    pass  # Client disconnected

        # Save collected response chunks for debugging
        self._save_debug(trace_id, "3_openai_response_chunks.json", debug_chunks)

        try:
            await response.write_eof()
        except Exception:
            pass  # Client already disconnected

        return response

    async def _handle_non_streaming(
        self,
        openai_request: dict[str, Any],
        tool_id_mapper: ToolIDMapper,
        trace_id: str,
        original_body: dict[str, Any],
    ) -> web.Response:
        """Handle non-streaming response."""
        from aiohttp import web

        if not self._client:
            return self._error_response("api_error", "Upstream client not initialized", 503)

        openai_request["stream"] = False

        try:
            internal_response = await self._client.send(openai_request, trace_id)
        except CircuitOpenError:
            return self._error_response(
                "api_error",
                "Service temporarily unavailable (circuit breaker open)",
                503,
            )
        except UpstreamError as e:
            error_type = ERROR_TYPE_MAP.get(e.status_code, "api_error")
            return self._error_response(error_type, str(e), e.status_code)
        except Exception as e:
            logger.exception("[%s] Unexpected error", trace_id)
            return self._error_response("api_error", f"Internal error: {e}", 500)

        anthropic_transformer = AnthropicTransformer()
        anthropic_response = anthropic_transformer.from_internal(
            internal_response,
            tool_id_mapper,
            original_body.get("model", self.config.upstream_model),
        )

        # Log completion
        usage = anthropic_response.get("usage", {})
        logger.info(
            "[%s] Response complete: input_tokens=%s, output_tokens=%s",
            trace_id,
            usage.get("input_tokens", "?"),
            usage.get("output_tokens", "?"),
        )

        return web.json_response(anthropic_response)

    def _error_response(
        self,
        error_type: str,
        message: str,
        status: int,
    ) -> web.Response:
        """Return Anthropic-format error response."""
        from aiohttp import web

        return web.json_response(
            {
                "type": "error",
                "error": {
                    "type": error_type,
                    "message": message,
                },
            },
            status=status,
        )

    def _format_error_sse(self, error_type: str, message: str) -> bytes:
        """Format an error as an SSE event."""
        error_data = {
            "type": "error",
            "error": {
                "type": error_type,
                "message": message,
            },
        }
        return f"event: error\ndata: {json.dumps(error_data)}\n\n".encode()

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /health."""
        from aiohttp import web

        health: dict[str, Any] = {"status": "ok"}

        # Check circuit breaker state
        if self._client and self._client._circuit:
            circuit_state = self._client._circuit.state.name
            if circuit_state == "OPEN":
                health["status"] = "degraded"
                health["upstream"] = "circuit_open"
                return web.json_response(health, status=503)
            elif circuit_state == "HALF_OPEN":
                health["upstream"] = "recovering"

        return web.json_response(health)

    async def _handle_shutdown(self, request: web.Request) -> web.Response:
        """Handle POST /api/shutdown."""
        from aiohttp import web

        self._shutdown_event.set()
        return web.json_response({"success": True, "message": "Shutdown initiated"})
