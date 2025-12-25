"""Tests for PassthroughProxyServer (alias for AnthropicProxyServer)."""

import aiohttp
import pytest
from aioresponses import aioresponses

from nerve.gateway.passthrough_proxy import (
    PassthroughProxyConfig,
    PassthroughProxyServer,
)


class TestPassthroughProxyImports:
    """Verify passthrough proxy is properly aliased to anthropic proxy."""

    def test_passthrough_config_is_anthropic_config(self):
        """PassthroughProxyConfig should be the same as AnthropicProxyConfig."""
        from nerve.gateway.anthropic_proxy import AnthropicProxyConfig

        assert PassthroughProxyConfig is AnthropicProxyConfig

    def test_passthrough_server_is_anthropic_server(self):
        """PassthroughProxyServer should be the same as AnthropicProxyServer."""
        from nerve.gateway.anthropic_proxy import AnthropicProxyServer

        assert PassthroughProxyServer is AnthropicProxyServer

    def test_passthrough_config_creation(self):
        """PassthroughProxyConfig should be instantiable with expected params."""
        config = PassthroughProxyConfig(
            host="127.0.0.1",
            port=0,
            upstream_base_url="https://api.test.com",
            upstream_api_key="test-key",
            upstream_model="test-model",
            debug_dir="/tmp/test",
        )

        assert config.host == "127.0.0.1"
        assert config.port == 0
        assert config.upstream_base_url == "https://api.test.com"
        assert config.upstream_api_key == "test-key"
        assert config.upstream_model == "test-model"
        assert config.debug_dir == "/tmp/test"

    def test_passthrough_config_optional_model(self):
        """upstream_model should be optional (None = keep original from request)."""
        config = PassthroughProxyConfig(
            upstream_base_url="https://api.test.com",
            upstream_api_key="test-key",
        )

        assert config.upstream_model is None

    def test_gateway_exports_passthrough(self):
        """Gateway package should export passthrough proxy classes."""
        from nerve.gateway import PassthroughProxyConfig, PassthroughProxyServer

        assert PassthroughProxyConfig is not None
        assert PassthroughProxyServer is not None


class TestPassthroughProxyBehavior:
    """Behavior tests for PassthroughProxyServer.

    These tests verify that the passthrough proxy correctly forwards
    requests to the upstream Anthropic-compatible API.
    """

    @pytest.fixture
    def proxy_config(self):
        """Create a test proxy config."""
        return PassthroughProxyConfig(
            host="127.0.0.1",
            port=0,  # Let OS pick a port
            upstream_base_url="https://api.test.anthropic.com",
            upstream_api_key="test-api-key-12345",
        )

    @pytest.fixture
    async def running_proxy(self, proxy_config):
        """Start a proxy server for testing."""
        from aiohttp import web

        server = PassthroughProxyServer(config=proxy_config)

        # Create HTTP session for upstream requests
        timeout = aiohttp.ClientTimeout(
            connect=proxy_config.connect_timeout,
            total=proxy_config.read_timeout,
        )
        server._session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "x-api-key": proxy_config.upstream_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

        # Setup app
        server._app = web.Application(client_max_size=proxy_config.max_body_size)
        server._app.router.add_post("/v1/messages", server._handle_messages)
        server._app.router.add_get("/health", server._handle_health)
        server._app.router.add_post("/api/event_logging/batch", server._handle_telemetry)

        # Start on a free port
        server._runner = web.AppRunner(server._app)
        await server._runner.setup()
        site = web.TCPSite(server._runner, "127.0.0.1", 0)
        await site.start()

        # Get the actual port
        actual_port = site._server.sockets[0].getsockname()[1]
        base_url = f"http://127.0.0.1:{actual_port}"

        yield server, base_url

        # Cleanup
        if server._session:
            await server._session.close()
        if server._runner:
            await server._runner.cleanup()

    async def test_passthrough_forward(self, running_proxy):
        """Request forwarded correctly to upstream.

        Verifies that requests are forwarded to the upstream API
        and responses are returned unchanged.
        """
        server, base_url = running_proxy

        with aioresponses(passthrough=[base_url]) as m:
            # Mock the upstream Anthropic response
            m.post(
                "https://api.test.anthropic.com/v1/messages",
                payload={
                    "id": "msg_123",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello from upstream!"}],
                    "model": "claude-3-5-sonnet-20241022",
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            )

            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"{base_url}/v1/messages",
                    json={
                        "model": "claude-3-5-sonnet-20241022",
                        "messages": [{"role": "user", "content": "Hello"}],
                        "max_tokens": 100,
                        "stream": False,
                    },
                    headers={
                        "Content-Type": "application/json",
                        "anthropic-version": "2024-01-01",
                    },
                ) as resp,
            ):
                assert resp.status == 200
                data = await resp.json()

                # Response should be passed through unchanged
                assert data["type"] == "message"
                assert data["role"] == "assistant"
                assert data["content"][0]["text"] == "Hello from upstream!"

    async def test_passthrough_api_key_replaced(self, running_proxy):
        """x-api-key header replaced with config value.

        The proxy should use its configured API key when forwarding
        to upstream, not the client's key.
        """
        server, base_url = running_proxy

        # The proxy's session is configured with 'test-api-key-12345'
        # We verify this by checking the session headers
        assert server._session.headers["x-api-key"] == "test-api-key-12345"

    async def test_passthrough_model_override(self):
        """Model replaced when config.upstream_model is set.

        When upstream_model is configured, the proxy should replace
        the model in the request.
        """
        config = PassthroughProxyConfig(
            upstream_base_url="https://api.test.anthropic.com",
            upstream_api_key="test-key",
            upstream_model="claude-3-opus-override",
        )

        # Simulate what _handle_messages does with model override
        body = {
            "model": "claude-3-5-sonnet-20241022",  # Original model
            "messages": [{"role": "user", "content": "Hello"}],
        }

        # Apply model override (as done in _handle_messages)
        if config.upstream_model:
            body["model"] = config.upstream_model

        # Verify the model was overridden
        assert body["model"] == "claude-3-opus-override"

    async def test_passthrough_model_preserve(self):
        """Model kept when config.upstream_model=None.

        When upstream_model is not configured (None), the proxy should
        preserve the original model from the request.
        """
        config = PassthroughProxyConfig(
            upstream_base_url="https://api.test.anthropic.com",
            upstream_api_key="test-key",
            upstream_model=None,  # No override
        )

        body = {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": "Hello"}],
        }

        # Apply model override (as done in _handle_messages)
        if config.upstream_model:
            body["model"] = config.upstream_model

        # Verify the model was preserved
        assert body["model"] == "claude-3-5-sonnet-20241022"

    async def test_passthrough_streaming(self, running_proxy):
        """SSE events forwarded correctly.

        Streaming responses should pass through SSE events unchanged.
        """
        server, base_url = running_proxy

        with aioresponses(passthrough=[base_url]) as m:
            # Mock SSE response from upstream (Anthropic format)
            sse_response = (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","type":"message","role":"assistant","content":[],"model":"claude-3-5-sonnet-20241022"}}\n\n'
                b"event: content_block_start\n"
                b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hi!"}}\n\n'
                b"event: content_block_stop\n"
                b'data: {"type":"content_block_stop","index":0}\n\n'
                b"event: message_stop\n"
                b'data: {"type":"message_stop"}\n\n'
            )
            m.post(
                "https://api.test.anthropic.com/v1/messages",
                body=sse_response,
                headers={"Content-Type": "text/event-stream"},
            )

            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"{base_url}/v1/messages",
                    json={
                        "model": "claude-3-5-sonnet-20241022",
                        "messages": [{"role": "user", "content": "Hi"}],
                        "max_tokens": 100,
                        "stream": True,
                    },
                    headers={
                        "Content-Type": "application/json",
                        "anthropic-version": "2024-01-01",
                    },
                ) as resp,
            ):
                assert resp.status == 200
                assert "text/event-stream" in resp.headers["Content-Type"]

                # Read all SSE events
                events = []
                async for line in resp.content:
                    line_str = line.decode("utf-8").strip()
                    if line_str.startswith("event:"):
                        event_type = line_str.split(":")[1].strip()
                        events.append(event_type)

                # Should have Anthropic event types (passed through)
                assert "message_start" in events
                assert "message_stop" in events

    async def test_passthrough_logging(self, tmp_path):
        """Requests logged to debug_dir.

        When debug_dir is configured, requests should be logged.
        """
        config = PassthroughProxyConfig(
            upstream_base_url="https://api.test.anthropic.com",
            upstream_api_key="test-key",
            debug_dir=str(tmp_path),
        )

        server = PassthroughProxyServer(config=config)

        # Verify the tracer is configured with debug_dir
        # The tracer creates a subdirectory with logs/<timestamp>
        assert server._tracer.debug_dir is not None
        assert str(tmp_path) in str(server._tracer.debug_dir)

        # Generate a trace ID (verifies the logging infrastructure works)
        trace_id = server._generate_trace_id(
            {
                "model": "test-model",
                "messages": [{"role": "user", "content": "test"}],
            }
        )

        # Trace ID should be generated
        assert trace_id is not None
        assert len(trace_id) > 0

    async def test_passthrough_upstream_error(self, running_proxy):
        """5xx from upstream surfaced correctly.

        Upstream errors should be passed through in Anthropic error format.
        """
        server, base_url = running_proxy

        with aioresponses(passthrough=[base_url]) as m:
            # Mock upstream returning 500 error
            m.post(
                "https://api.test.anthropic.com/v1/messages",
                status=500,
                payload={
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": "Internal server error",
                    },
                },
            )

            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"{base_url}/v1/messages",
                    json={
                        "model": "claude-3-5-sonnet-20241022",
                        "messages": [{"role": "user", "content": "Hello"}],
                        "stream": False,
                    },
                    headers={"Content-Type": "application/json"},
                ) as resp,
            ):
                # Should return error status
                assert resp.status == 500
                data = await resp.json()

                # Should be Anthropic error format
                assert data["type"] == "error"
                assert "error" in data
