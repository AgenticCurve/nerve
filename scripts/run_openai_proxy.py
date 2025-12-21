#!/usr/bin/env python
"""Run Anthropic-to-OpenAI proxy with logging.

Usage:
    export OPENAI_API_KEY="sk-..."
    uv run python examples/run_openai_proxy.py

Then configure Claude Code:
    export ANTHROPIC_BASE_URL="http://127.0.0.1:3456"
    claude
"""
import asyncio
import logging
import os
import sys

# Enable logging (use DEBUG to see full request payloads)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
# Quiet noisy loggers
logging.getLogger("aiohttp").setLevel(logging.WARNING)

from nerve.gateway.openai_proxy import OpenAIProxyServer, OpenAIProxyConfig


async def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable is required")
        sys.exit(1)

    model = os.environ.get("OPENAI_MODEL", "gpt-4.1")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    debug_dir = os.environ.get("NERVE_DEBUG_DIR", ".nerve")

    config = OpenAIProxyConfig(
        host="127.0.0.1",
        port=3456,
        upstream_base_url=base_url,
        upstream_api_key=api_key,
        upstream_model=model,
        debug_dir=debug_dir,
    )

    print(f"Starting OpenAI proxy on http://{config.host}:{config.port}")
    print(f"Upstream: {base_url} (model: {model})")
    print(f"Debug logs: {debug_dir}/logs/{{session_id}}/")
    print()
    print("Configure Claude Code:")
    print(f"  export ANTHROPIC_BASE_URL=http://{config.host}:{config.port}")
    print()

    server = OpenAIProxyServer(config=config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
