"""Nerve Gateway - API Gateway for LLM requests.

Independent system that accepts LLM API requests and forwards to upstream APIs.
Completely separate from PTY orchestration system.

Components:
- Proxy servers: Forward and transform API requests
- Transforms: API format conversion utilities
- Clients: Resilient HTTP clients for upstream APIs

Usage (via compose.py convenience functions):
    from nerve.compose import create_openai_proxy
    import asyncio

    asyncio.run(create_openai_proxy(
        upstream_base_url="https://api.openai.com/v1",
        upstream_api_key="sk-...",
        upstream_model="gpt-4o",
    ))

Usage (direct):
    from nerve.gateway.openai_proxy import OpenAIProxyConfig, OpenAIProxyServer
    import asyncio

    async def main():
        config = OpenAIProxyConfig(
            upstream_base_url="https://api.openai.com/v1",
            upstream_api_key="sk-...",
            upstream_model="gpt-4o",
        )
        server = OpenAIProxyServer(config=config)
        await server.serve()

    asyncio.run(main())
"""

from nerve.gateway.errors import ERROR_TYPE_MAP
from nerve.gateway.tracing import RequestTracer

__all__ = [
    "ERROR_TYPE_MAP",
    "RequestTracer",
]