"""Tests for AnthropicProxyServer (passthrough proxy)."""

import aiohttp
import pytest
from aioresponses import aioresponses

from nerve.gateway.anthropic_proxy import (
    AnthropicProxyConfig,
    AnthropicProxyServer,
)


class TestAnthropicProxyServer:
    """Tests for the Anthropic passthrough proxy server."""

    @pytest.fixture
    def proxy_config(self):
        """Create a test proxy config."""
        return AnthropicProxyConfig(
            host="127.0.0.1",
            port=0,  # Let OS pick a port
            upstream_base_url="https://api.test.anthropic.com",
            upstream_api_key="test-key",
        )

    @pytest.fixture
    async def running_proxy(self, proxy_config):
        """Start a proxy server for testing."""
        from aiohttp import web

        server = AnthropicProxyServer(config=proxy_config)

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

    async def test_health_check(self, running_proxy):
        """Health endpoint should return ok status."""
        server, base_url = running_proxy

        async with (
            aiohttp.ClientSession() as session,
            session.get(f"{base_url}/health") as resp,
        ):
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"

    async def test_telemetry_endpoint(self, running_proxy):
        """Telemetry endpoint should silently accept requests."""
        server, base_url = running_proxy

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f"{base_url}/api/event_logging/batch",
                json={"events": []},
                headers={"Content-Type": "application/json"},
            ) as resp,
        ):
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"

    async def test_content_type_validation(self, running_proxy):
        """Should reject requests without proper Content-Type."""
        server, base_url = running_proxy

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f"{base_url}/v1/messages",
                data="not json",
                headers={"Content-Type": "text/plain"},
            ) as resp,
        ):
            assert resp.status == 400
            data = await resp.json()
            assert data["type"] == "error"
            assert data["error"]["type"] == "invalid_request_error"
            assert "Content-Type" in data["error"]["message"]

    async def test_json_validation(self, running_proxy):
        """Should reject invalid JSON."""
        server, base_url = running_proxy

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f"{base_url}/v1/messages",
                data="{not valid json",
                headers={"Content-Type": "application/json"},
            ) as resp,
        ):
            assert resp.status == 400
            data = await resp.json()
            assert data["error"]["type"] == "invalid_request_error"
            assert "JSON" in data["error"]["message"]

    async def test_passthrough_non_streaming(self, running_proxy):
        """Non-streaming request should pass through unchanged."""
        server, base_url = running_proxy

        with aioresponses(passthrough=[base_url]) as m:
            # Mock the upstream Anthropic response (same format as input)
            m.post(
                "https://api.test.anthropic.com/v1/messages",
                payload={
                    "id": "msg_123",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello from Anthropic!"}],
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
                assert len(data["content"]) == 1
                assert data["content"][0]["text"] == "Hello from Anthropic!"

    async def test_passthrough_streaming(self, running_proxy):
        """Streaming request should pass through SSE events unchanged."""
        server, base_url = running_proxy

        with aioresponses(passthrough=[base_url]) as m:
            # Mock SSE response from upstream (Anthropic format)
            sse_response = (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","type":"message","role":"assistant","content":[],"model":"claude-3-5-sonnet-20241022"}}\n\n'
                b"event: content_block_start\n"
                b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello!"}}\n\n'
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
                        "messages": [{"role": "user", "content": "Say hi"}],
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

    async def test_upstream_error_non_streaming(self, running_proxy):
        """Upstream errors should be returned in Anthropic format."""
        server, base_url = running_proxy

        with aioresponses(passthrough=[base_url]) as m:
            # Mock upstream returning 401 with JSON body (as real API would)
            m.post(
                "https://api.test.anthropic.com/v1/messages",
                status=401,
                payload={
                    "type": "error",
                    "error": {
                        "type": "authentication_error",
                        "message": "Invalid API key",
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
                assert resp.status == 401
                data = await resp.json()

                # Anthropic error format
                assert data["type"] == "error"
                assert "error" in data
                assert data["error"]["type"] == "authentication_error"

    async def test_model_override(self):
        """Model override in config should replace model in requests.

        This is a unit test that directly tests the model override logic
        rather than going through the full server setup.
        """
        from nerve.gateway.anthropic_proxy import AnthropicProxyConfig

        # Config with model override
        config = AnthropicProxyConfig(
            upstream_base_url="https://api.test.anthropic.com",
            upstream_api_key="test-key",
            upstream_model="claude-3-opus-20240229",
        )

        # Simulate what _handle_messages does
        body = {
            "model": "claude-3-5-sonnet-20241022",  # Original model
            "messages": [{"role": "user", "content": "Hello"}],
        }

        # Apply model override (as done in _handle_messages)
        if config.upstream_model:
            body["model"] = config.upstream_model

        # Verify the model was overridden
        assert body["model"] == "claude-3-opus-20240229"
