"""Anthropic upstream proxy server.

Exposes /v1/messages endpoint that accepts Anthropic Messages API format
and proxies requests to an Anthropic-compatible upstream (e.g., api.anthropic.com).

This server:
1. Accepts Anthropic format requests from Claude Code CLI
2. Logs the request for debugging
3. Forwards directly to upstream (no transformation needed)
4. Logs and streams the response back

Transparent mode uses httpx for upstream requests to match Claude Code's TLS fingerprint.
Non-transparent mode uses aiohttp for upstream requests.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx
    from aiohttp import web

from nerve.gateway.errors import ERROR_TYPE_MAP
from nerve.gateway.tracing import RequestTracer

logger = logging.getLogger(__name__)


@dataclass
class AnthropicProxyConfig:
    """Configuration for Anthropic passthrough proxy server."""

    host: str = "127.0.0.1"
    port: int = 3456

    # Upstream configuration
    upstream_base_url: str = "https://api.anthropic.com"
    upstream_api_key: str = ""
    upstream_model: str | None = None  # Optional: override model in requests

    # Transparent mode: forward original headers from client instead of using configured API key
    # This allows logging without needing explicit API credentials
    transparent: bool = False

    # Log headers: include request/response headers in debug logs (for research)
    log_headers: bool = False

    # Client configuration
    connect_timeout: float = 10.0
    read_timeout: float = 300.0

    # Request limits
    max_body_size: int = 500 * 1024 * 1024  # 500MB

    # Debug: save raw requests/responses to files
    debug_dir: str | None = None  # e.g., "/tmp/nerve-proxy-debug"


@dataclass
class AnthropicProxyServer:
    """Transport that accepts Anthropic Messages API requests
    and proxies them to an Anthropic-compatible upstream.

    Example:
        >>> config = AnthropicProxyConfig(
        ...     upstream_base_url="https://api.z.ai/api/anthropic",
        ...     upstream_api_key="your-api-key",
        ... )
        >>> server = AnthropicProxyServer(config=config)
        >>> await server.serve()
    """

    config: AnthropicProxyConfig
    _app: Any = None  # aiohttp.web.Application
    _runner: Any = None  # aiohttp.web.AppRunner
    _session: Any = None  # aiohttp.ClientSession (non-transparent mode)
    _httpx_client: httpx.AsyncClient | None = None  # httpx client (transparent mode)
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
        """Start the passthrough proxy server."""
        try:
            import aiohttp
            from aiohttp import web
        except ImportError as err:
            raise ImportError(
                "aiohttp is required for the proxy. Install with: pip install nerve[proxy]"
            ) from err

        if self.config.transparent:
            # Transparent mode: use httpx to match Claude Code's TLS fingerprint
            try:
                import httpx
            except ImportError as err:
                raise ImportError(
                    "httpx is required for transparent mode. Install with: pip install httpx"
                ) from err

            # Create httpx client with matching timeouts
            self._httpx_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=self.config.connect_timeout,
                    read=self.config.read_timeout,
                    write=self.config.read_timeout,
                    pool=self.config.read_timeout,
                ),
                http2=True,  # Match Claude Code's HTTP/2 usage
            )
        else:
            # Normal mode: use aiohttp with configured API key
            timeout = aiohttp.ClientTimeout(
                connect=self.config.connect_timeout,
                total=self.config.read_timeout,
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "x-api-key": self.config.upstream_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )

        # Create web application
        self._app = web.Application(client_max_size=self.config.max_body_size)
        self._app.router.add_post("/v1/messages", self._handle_messages)
        self._app.router.add_get("/health", self._handle_health)
        # Silently accept telemetry requests (Claude Code sends these)
        self._app.router.add_post("/api/event_logging/batch", self._handle_telemetry)

        # Start server
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()

        mode_str = "transparent" if self.config.transparent else "configured"
        logger.info(
            "Anthropic proxy listening on http://%s:%d (%s mode)",
            self.config.host,
            self.config.port,
            mode_str,
        )
        logger.info("Forwarding to: %s", self.config.upstream_base_url)
        if self.config.transparent:
            logger.info("Transparent mode: forwarding original client headers")
        if self.config.debug_dir:
            logger.info("Debug files will be saved to: %s", self.config.debug_dir)

        # Wait for shutdown
        await self._shutdown_event.wait()

    async def shutdown(self) -> None:
        """Shutdown the server gracefully."""
        logger.info("Shutting down Anthropic proxy...")
        self._shutdown_event.set()
        if self._session:
            await self._session.close()
            self._session = None
        if self._httpx_client:
            await self._httpx_client.aclose()
            self._httpx_client = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /health - health check endpoint."""
        from aiohttp import web

        return web.json_response({"status": "ok"})

    async def _handle_telemetry(self, request: web.Request) -> web.Response:
        """Handle POST /api/event_logging/batch - silently accept telemetry."""
        from aiohttp import web

        # Just return OK - we don't need to forward telemetry
        return web.json_response({"status": "ok"})

    def _error_response(self, error_type: str, message: str, status: int) -> web.Response:
        """Create an Anthropic-format error response."""
        from aiohttp import web

        return web.json_response(
            {"type": "error", "error": {"type": error_type, "message": message}},
            status=status,
        )

    def _extract_forward_headers(self, request: web.Request) -> dict[str, str]:
        """Extract headers to forward from client request (for transparent mode).

        Uses a blacklist approach: forwards ALL headers except hop-by-hop headers
        that shouldn't be forwarded through proxies. This ensures the upstream
        sees the exact same request signature as a direct connection.
        """
        # Headers to NEVER forward (hop-by-hop, proxy-specific, or must be recalculated)
        # See RFC 2616 Section 13.5.1 and RFC 7230 Section 6.1
        skip_headers = {
            # Hop-by-hop headers (connection-specific, not end-to-end)
            "host",  # Must be set to upstream host
            "connection",
            "keep-alive",
            "transfer-encoding",
            "te",
            "trailer",
            "upgrade",
            # Proxy-specific
            "proxy-authorization",
            "proxy-authenticate",
            "proxy-connection",
            # Will be recalculated by aiohttp
            "content-length",
        }

        headers = {}
        for key, value in request.headers.items():
            key_lower = key.lower()
            if key_lower not in skip_headers:
                headers[key] = value

        return headers

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

        # Extract headers for transparent mode (empty dict if not transparent)
        forward_headers = self._extract_forward_headers(request) if self.config.transparent else {}

        # Log anthropic-version for debugging
        anthropic_version = request.headers.get("anthropic-version", "unknown")
        logger.debug("[%s] anthropic-version: %s", trace_id, anthropic_version)
        logger.info("[%s] Incoming request from Claude Code", trace_id)

        # Save raw incoming request (optionally with headers)
        if self.config.log_headers:
            request_data = {
                "headers": dict(request.headers),
                "body": body,
            }
            self._save_debug(trace_id, "1_request.json", request_data)
        else:
            self._save_debug(trace_id, "1_request.json", body)

        # Optionally override model
        if self.config.upstream_model:
            body["model"] = self.config.upstream_model

        # Log request details
        requested_model = body.get("model", "unknown")
        message_count = len(body.get("messages", []))
        is_streaming = body.get("stream", True)
        logger.info(
            "[%s] Request: model=%s, messages=%d, stream=%s -> forwarding to %s",
            trace_id,
            requested_model,
            message_count,
            is_streaming,
            self.config.upstream_base_url,
        )

        # Forward to upstream
        if is_streaming:
            return await self._handle_streaming(request, body, trace_id, forward_headers)
        else:
            return await self._handle_non_streaming(body, trace_id, forward_headers)

    async def _handle_streaming(
        self,
        request: web.Request,
        body: dict[str, Any],
        trace_id: str,
        forward_headers: dict[str, str] | None = None,
    ) -> web.StreamResponse:
        """Handle streaming response - passthrough SSE events."""
        from aiohttp import web

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        # Collect events and optionally headers for debug logging
        debug_events: list[str] = []
        response_headers: dict[str, str] = {}  # Populated by handlers if log_headers

        url = f"{self.config.upstream_base_url}/v1/messages"

        if self.config.transparent and self._httpx_client:
            # Transparent mode: use httpx for matching TLS fingerprint
            await self._handle_streaming_httpx(
                response,
                body,
                url,
                trace_id,
                forward_headers or {},
                debug_events,
                response_headers if self.config.log_headers else None,
            )
        else:
            # Normal mode: use aiohttp
            await self._handle_streaming_aiohttp(
                response,
                body,
                url,
                trace_id,
                forward_headers,
                debug_events,
                response_headers if self.config.log_headers else None,
            )

        # Save debug events (optionally with headers)
        if self.config.log_headers:
            response_data = {
                "headers": response_headers,
                "events": debug_events,
            }
            self._save_debug(trace_id, "2_response_events.json", response_data)
        else:
            self._save_debug(trace_id, "2_response_events.json", debug_events)

        try:
            await response.write_eof()
        except Exception:
            pass

        return response

    async def _handle_streaming_httpx(
        self,
        response: web.StreamResponse,
        body: dict[str, Any],
        url: str,
        trace_id: str,
        forward_headers: dict[str, str],
        debug_events: list[str],
        response_headers: dict[str, str] | None = None,
    ) -> None:
        """Handle streaming using httpx client (transparent mode)."""
        assert self._httpx_client is not None

        try:
            async with self._httpx_client.stream(
                "POST",
                url,
                json=body,
                headers=forward_headers,
            ) as upstream_response:
                # Capture response headers if requested
                if response_headers is not None:
                    response_headers.update(dict(upstream_response.headers))

                if upstream_response.status_code != 200:
                    error_body = await upstream_response.aread()
                    error_text = error_body.decode("utf-8")
                    logger.error(
                        "[%s] Upstream error %d: %s",
                        trace_id,
                        upstream_response.status_code,
                        error_text[:500],
                    )
                    self._save_debug(
                        trace_id,
                        "2_error.json",
                        {
                            "status": upstream_response.status_code,
                            "body": error_text,
                        },
                    )
                    error_event = f"event: error\ndata: {error_text}\n\n"
                    await response.write(error_event.encode("utf-8"))
                    return

                # Stream response directly - no transformation needed
                line_count = 0
                async for line in upstream_response.aiter_lines():
                    if line.strip():
                        line_count += 1
                        debug_events.append(line.strip())
                        logger.debug("[%s] SSE line %d: %s", trace_id, line_count, line[:200])

                    try:
                        # Add newline back since aiter_lines strips it
                        await response.write((line + "\n").encode("utf-8"))
                    except ConnectionResetError:
                        logger.debug("[%s] Client disconnected during streaming", trace_id)
                        break

                logger.info("[%s] Stream complete, forwarded %d SSE lines", trace_id, line_count)

        except Exception as e:
            error_msg = str(e)
            if "closing transport" in error_msg.lower():
                logger.debug("[%s] Client closed connection early", trace_id)
            else:
                logger.exception("[%s] Error during streaming (httpx)", trace_id)

    async def _handle_streaming_aiohttp(
        self,
        response: web.StreamResponse,
        body: dict[str, Any],
        url: str,
        trace_id: str,
        forward_headers: dict[str, str] | None,
        debug_events: list[str],
        response_headers: dict[str, str] | None = None,
    ) -> None:
        """Handle streaming using aiohttp client (normal mode)."""
        try:
            post_kwargs: dict[str, Any] = {"json": body}
            if forward_headers:
                post_kwargs["headers"] = forward_headers
            async with self._session.post(url, **post_kwargs) as upstream_response:
                # Capture response headers if requested
                if response_headers is not None:
                    response_headers.update(dict(upstream_response.headers))

                if upstream_response.status != 200:
                    error_body = await upstream_response.text()
                    logger.error(
                        "[%s] Upstream error %d: %s",
                        trace_id,
                        upstream_response.status,
                        error_body[:500],
                    )
                    self._save_debug(
                        trace_id,
                        "2_error.json",
                        {
                            "status": upstream_response.status,
                            "body": error_body,
                        },
                    )
                    error_event = f"event: error\ndata: {error_body}\n\n"
                    await response.write(error_event.encode("utf-8"))
                    return

                # Stream response directly - no transformation needed
                line_count = 0
                async for line in upstream_response.content:
                    line_str = line.decode("utf-8")
                    if line_str.strip():
                        line_count += 1
                        debug_events.append(line_str.strip())
                        logger.debug("[%s] SSE line %d: %s", trace_id, line_count, line_str[:200])

                    try:
                        await response.write(line)
                    except ConnectionResetError:
                        logger.debug("[%s] Client disconnected during streaming", trace_id)
                        break

                logger.info("[%s] Stream complete, forwarded %d SSE lines", trace_id, line_count)

        except Exception as e:
            error_msg = str(e)
            if "closing transport" in error_msg.lower():
                logger.debug("[%s] Client closed connection early", trace_id)
            else:
                logger.exception("[%s] Error during streaming (aiohttp)", trace_id)

    async def _handle_non_streaming(
        self,
        body: dict[str, Any],
        trace_id: str,
        forward_headers: dict[str, str] | None = None,
    ) -> web.Response:
        """Handle non-streaming response."""

        url = f"{self.config.upstream_base_url}/v1/messages"

        if self.config.transparent and self._httpx_client:
            # Transparent mode: use httpx for matching TLS fingerprint
            return await self._handle_non_streaming_httpx(
                body, url, trace_id, forward_headers or {}
            )
        else:
            # Normal mode: use aiohttp
            return await self._handle_non_streaming_aiohttp(body, url, trace_id, forward_headers)

    async def _handle_non_streaming_httpx(
        self,
        body: dict[str, Any],
        url: str,
        trace_id: str,
        forward_headers: dict[str, str],
    ) -> web.Response:
        """Handle non-streaming using httpx client (transparent mode)."""
        from aiohttp import web

        assert self._httpx_client is not None

        try:
            upstream_response = await self._httpx_client.post(
                url,
                json=body,
                headers=forward_headers,
            )
            response_body = upstream_response.text

            # Save response (optionally with headers)
            response_data: dict[str, Any] = {
                "status": upstream_response.status_code,
                "body": json.loads(response_body) if response_body else None,
            }
            if self.config.log_headers:
                response_data["headers"] = dict(upstream_response.headers)
            self._save_debug(trace_id, "2_response.json", response_data)

            if upstream_response.status_code != 200:
                logger.error(
                    "[%s] Upstream error %d: %s",
                    trace_id,
                    upstream_response.status_code,
                    response_body[:500],
                )
                error_type = ERROR_TYPE_MAP.get(upstream_response.status_code, "api_error")
                return self._error_response(
                    error_type,
                    response_body,
                    upstream_response.status_code,
                )

            logger.info("[%s] Non-streaming response received (httpx)", trace_id)
            return web.Response(
                text=response_body,
                content_type="application/json",
                headers={"X-Trace-Id": trace_id},
            )

        except Exception as e:
            logger.exception("[%s] Error during non-streaming request (httpx)", trace_id)
            return self._error_response(
                "api_error",
                f"Upstream request failed: {e}",
                502,
            )

    async def _handle_non_streaming_aiohttp(
        self,
        body: dict[str, Any],
        url: str,
        trace_id: str,
        forward_headers: dict[str, str] | None,
    ) -> web.Response:
        """Handle non-streaming using aiohttp client (normal mode)."""
        from aiohttp import web

        try:
            post_kwargs: dict[str, Any] = {"json": body}
            if forward_headers:
                post_kwargs["headers"] = forward_headers
            async with self._session.post(url, **post_kwargs) as upstream_response:
                response_body = await upstream_response.text()

                # Save response (optionally with headers)
                response_data: dict[str, Any] = {
                    "status": upstream_response.status,
                    "body": json.loads(response_body) if response_body else None,
                }
                if self.config.log_headers:
                    response_data["headers"] = dict(upstream_response.headers)
                self._save_debug(trace_id, "2_response.json", response_data)

                if upstream_response.status != 200:
                    logger.error(
                        "[%s] Upstream error %d: %s",
                        trace_id,
                        upstream_response.status,
                        response_body[:500],
                    )
                    error_type = ERROR_TYPE_MAP.get(upstream_response.status, "api_error")
                    return self._error_response(
                        error_type,
                        response_body,
                        upstream_response.status,
                    )

                logger.info("[%s] Non-streaming response received (aiohttp)", trace_id)
                return web.Response(
                    text=response_body,
                    content_type="application/json",
                    headers={"X-Trace-Id": trace_id},
                )

        except Exception as e:
            logger.exception("[%s] Error during non-streaming request (aiohttp)", trace_id)
            return self._error_response(
                "api_error",
                f"Upstream request failed: {e}",
                502,
            )
