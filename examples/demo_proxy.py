#!/usr/bin/env python3
"""Live demonstration of the Anthropic-to-OpenAI proxy.

This script:
1. Starts a mock OpenAI-compatible server
2. Starts the Anthropic proxy pointing to it
3. Makes requests in Anthropic format through the proxy
4. Shows the transformed responses

Usage:
    python examples/demo_proxy.py
"""

import asyncio
import json

import aiohttp
from aiohttp import web

# ============================================================================
# Mock OpenAI Server
# ============================================================================


async def mock_openai_chat_completions(request: web.Request) -> web.Response:
    """Mock OpenAI /chat/completions endpoint."""
    body = await request.json()

    print("\n[Mock OpenAI] Received request:")
    print(f"  Model: {body.get('model')}")
    print(f"  Messages: {len(body.get('messages', []))} messages")
    print(f"  Stream: {body.get('stream', False)}")

    if body.get("stream"):
        # Return streaming SSE response
        response = web.StreamResponse(
            status=200,
            headers={"Content-Type": "text/event-stream"},
        )
        await response.prepare(request)

        # Send some chunks
        chunks = [
            {"choices": [{"delta": {"role": "assistant"}, "index": 0}]},
            {"choices": [{"delta": {"content": "Hello"}, "index": 0}]},
            {"choices": [{"delta": {"content": " from"}, "index": 0}]},
            {"choices": [{"delta": {"content": " the"}, "index": 0}]},
            {"choices": [{"delta": {"content": " mock"}, "index": 0}]},
            {"choices": [{"delta": {"content": " server!"}, "index": 0}]},
            {"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]},
        ]

        for chunk in chunks:
            await response.write(f"data: {json.dumps(chunk)}\n\n".encode())
            await asyncio.sleep(0.05)  # Simulate streaming delay

        # Send usage
        await response.write(b'data: {"usage": {"prompt_tokens": 10, "completion_tokens": 6}}\n\n')
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response
    else:
        # Non-streaming response
        return web.json_response(
            {
                "id": "chatcmpl-mock123",
                "object": "chat.completion",
                "created": 1234567890,
                "model": body.get("model", "gpt-4"),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello from the mock server! I received your message.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 8,
                },
            }
        )


async def start_mock_openai(port: int) -> web.AppRunner:
    """Start mock OpenAI server."""
    app = web.Application()
    app.router.add_post("/v1/chat/completions", mock_openai_chat_completions)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner


# ============================================================================
# Demo Runner
# ============================================================================


async def make_anthropic_request(proxy_url: str, stream: bool = False) -> None:
    """Make a request to the proxy in Anthropic format."""
    request_body = {
        "model": "claude-3-opus-20240229",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "Hello! Please greet me."}],
        "stream": stream,
    }

    print(f"\n{'=' * 60}")
    print(f"Making {'streaming' if stream else 'non-streaming'} request to proxy...")
    print(f"{'=' * 60}")
    print("Request (Anthropic format):")
    print(json.dumps(request_body, indent=2))

    async with (
        aiohttp.ClientSession() as session,
        session.post(
            f"{proxy_url}/v1/messages",
            json=request_body,
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2024-01-01",
            },
        ) as resp,
    ):
        print(f"\nResponse status: {resp.status}")
        print(f"Content-Type: {resp.headers.get('Content-Type')}")

        if stream:
            print("\nStreaming response (Anthropic SSE format):")
            print("-" * 40)
            async for line in resp.content:
                line_str = line.decode("utf-8").strip()
                if line_str:
                    print(line_str)
        else:
            data = await resp.json()
            print("\nResponse (Anthropic format):")
            print(json.dumps(data, indent=2))


async def main():
    """Run the demo."""
    mock_openai_port = 18080
    proxy_port = 18081

    print("=" * 60)
    print("Anthropic-to-OpenAI Proxy Demo")
    print("=" * 60)

    # Start mock OpenAI server
    print(f"\n1. Starting mock OpenAI server on port {mock_openai_port}...")
    mock_runner = await start_mock_openai(mock_openai_port)
    print(f"   Mock OpenAI server running at http://127.0.0.1:{mock_openai_port}")

    # Start the OpenAI proxy (accepts Anthropic format, forwards to OpenAI)
    print(f"\n2. Starting OpenAI proxy on port {proxy_port}...")
    from nerve.gateway.openai_proxy import OpenAIProxyConfig, OpenAIProxyServer

    proxy_config = OpenAIProxyConfig(
        host="127.0.0.1",
        port=proxy_port,
        upstream_base_url=f"http://127.0.0.1:{mock_openai_port}/v1",
        upstream_api_key="mock-api-key",
        upstream_model="gpt-4-mock",
    )

    proxy_server = OpenAIProxyServer(config=proxy_config)

    # Start proxy in background
    from nerve.gateway.clients.llm_client import LLMClient, LLMClientConfig

    proxy_server._client = LLMClient(
        config=LLMClientConfig(
            base_url=proxy_config.upstream_base_url,
            api_key=proxy_config.upstream_api_key,
            model=proxy_config.upstream_model,
        )
    )
    await proxy_server._client.connect()

    proxy_server._app = web.Application(client_max_size=proxy_config.max_body_size)
    proxy_server._app.router.add_post("/v1/messages", proxy_server._handle_messages)
    proxy_server._app.router.add_get("/health", proxy_server._handle_health)

    proxy_runner = web.AppRunner(proxy_server._app)
    await proxy_runner.setup()
    proxy_site = web.TCPSite(proxy_runner, proxy_config.host, proxy_config.port)
    await proxy_site.start()

    print(f"   Proxy running at http://127.0.0.1:{proxy_port}")
    print(f"   Proxying to: {proxy_config.upstream_base_url}")

    proxy_url = f"http://127.0.0.1:{proxy_port}"

    try:
        # Check health
        print("\n3. Checking proxy health...")
        async with (
            aiohttp.ClientSession() as session,
            session.get(f"{proxy_url}/health") as resp,
        ):
            health = await resp.json()
            print(f"   Health: {health}")

        # Make non-streaming request
        print("\n4. Testing non-streaming request...")
        await make_anthropic_request(proxy_url, stream=False)

        # Make streaming request
        print("\n5. Testing streaming request...")
        await make_anthropic_request(proxy_url, stream=True)

        print("\n" + "=" * 60)
        print("Demo completed successfully!")
        print("=" * 60)
        print("\nThe proxy correctly:")
        print("  - Accepted Anthropic Messages API format")
        print("  - Transformed to OpenAI Chat Completions format")
        print("  - Forwarded to upstream (mock) server")
        print("  - Transformed response back to Anthropic format")
        print("  - Handled both streaming and non-streaming modes")

    finally:
        # Cleanup
        await proxy_server._client.close()
        await proxy_runner.cleanup()
        await mock_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
