"""End-to-end tests for OpenAIProxyServer (Anthropic→OpenAI transformation)."""

import aiohttp
import pytest
from aioresponses import aioresponses

from nerve.gateway.openai_proxy import (
    OpenAIProxyConfig,
    OpenAIProxyServer,
)


class TestOpenAIProxyServer:
    """End-to-end tests for the proxy server."""

    @pytest.fixture
    def proxy_config(self):
        """Create a test proxy config."""
        return OpenAIProxyConfig(
            host="127.0.0.1",
            port=0,  # Let OS pick a port
            upstream_base_url="https://api.test.openai.com/v1",
            upstream_api_key="test-key",
            upstream_model="gpt-4o-test",
            max_retries=1,
        )

    @pytest.fixture
    async def running_proxy(self, proxy_config):
        """Start a proxy server for testing."""
        server = OpenAIProxyServer(config=proxy_config)

        # We need to start the server but get the actual port
        # Since serve() blocks, we'll need to set up the server manually
        from aiohttp import web

        server._client = server._client or None

        # Initialize client with mocked upstream
        from nerve.gateway.clients.llm_client import LLMClient, LLMClientConfig

        server._client = LLMClient(
            config=LLMClientConfig(
                base_url=proxy_config.upstream_base_url,
                api_key=proxy_config.upstream_api_key,
                model=proxy_config.upstream_model,
                max_retries=1,
            )
        )
        await server._client.connect()

        # Setup app
        server._app = web.Application(client_max_size=proxy_config.max_body_size)
        server._app.router.add_post("/v1/messages", server._handle_messages)
        server._app.router.add_get("/health", server._handle_health)

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
        await server.stop()

    async def test_health_check(self, running_proxy):
        """Health endpoint should return ok status."""
        server, base_url = running_proxy

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base_url}/health") as resp:
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

    async def test_request_validation(self, running_proxy):
        """Should validate Anthropic request format."""
        server, base_url = running_proxy

        async with aiohttp.ClientSession() as session:
            # Missing messages field
            async with session.post(
                f"{base_url}/v1/messages",
                json={"max_tokens": 1024},
                headers={"Content-Type": "application/json"},
            ) as resp:
                assert resp.status == 400
                data = await resp.json()
                assert data["error"]["type"] == "invalid_request_error"

    async def test_non_streaming_request(self, running_proxy):
        """Non-streaming request should return complete response."""
        server, base_url = running_proxy

        with aioresponses(passthrough=[base_url]) as m:
            # Mock the upstream OpenAI response
            m.post(
                "https://api.test.openai.com/v1/chat/completions",
                payload={
                    "choices": [
                        {
                            "message": {"content": "Hello from upstream!"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )

            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"{base_url}/v1/messages",
                    json={
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

                assert data["type"] == "message"
                assert data["role"] == "assistant"
                assert len(data["content"]) == 1
                assert data["content"][0]["text"] == "Hello from upstream!"

    async def test_streaming_request(self, running_proxy):
        """Streaming request should return SSE events."""
        server, base_url = running_proxy

        with aioresponses(passthrough=[base_url]) as m:
            # Mock SSE response from upstream
            sse_response = (
                b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":"!"}}]}\n\n'
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                b"data: [DONE]\n\n"
            )
            m.post(
                "https://api.test.openai.com/v1/chat/completions",
                body=sse_response,
                headers={"Content-Type": "text/event-stream"},
            )

            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"{base_url}/v1/messages",
                    json={
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

                # Should have the required Anthropic event types
                assert "message_start" in events
                assert "message_stop" in events

    async def test_tool_use_transformation(self, running_proxy):
        """Tool use should be properly transformed between formats."""
        server, base_url = running_proxy

        with aioresponses(passthrough=[base_url]) as m:
            # Mock upstream returning a tool call
            m.post(
                "https://api.test.openai.com/v1/chat/completions",
                payload={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_abc123",
                                        "type": "function",
                                        "function": {
                                            "name": "get_weather",
                                            "arguments": '{"location":"NYC"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                },
            )

            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"{base_url}/v1/messages",
                    json={
                        "messages": [{"role": "user", "content": "Weather in NYC?"}],
                        "tools": [
                            {
                                "name": "get_weather",
                                "description": "Get weather",
                                "input_schema": {"type": "object"},
                            }
                        ],
                        "max_tokens": 100,
                        "stream": False,
                    },
                    headers={"Content-Type": "application/json"},
                ) as resp,
            ):
                assert resp.status == 200
                data = await resp.json()

                # Should have tool_use block in Anthropic format
                tool_use_blocks = [b for b in data["content"] if b["type"] == "tool_use"]
                assert len(tool_use_blocks) == 1

                tool_block = tool_use_blocks[0]
                assert tool_block["name"] == "get_weather"
                assert tool_block["input"] == {"location": "NYC"}
                # ID should be in Anthropic format
                assert tool_block["id"].startswith("toolu_")

    async def test_error_format_matches_anthropic(self, running_proxy):
        """Errors should be in Anthropic format."""
        server, base_url = running_proxy

        with aioresponses(passthrough=[base_url]) as m:
            # Mock upstream returning 401
            m.post(
                "https://api.test.openai.com/v1/chat/completions",
                status=401,
                body="Unauthorized",
            )

            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"{base_url}/v1/messages",
                    json={
                        "messages": [{"role": "user", "content": "Hello"}],
                        "stream": False,
                    },
                    headers={"Content-Type": "application/json"},
                ) as resp,
            ):
                # Should return the error
                assert resp.status == 401
                data = await resp.json()

                # Anthropic error format
                assert data["type"] == "error"
                assert "error" in data
                assert data["error"]["type"] == "authentication_error"
