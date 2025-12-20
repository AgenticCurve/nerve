#!/usr/bin/env python3
"""Run the Anthropic passthrough proxy.

This proxy forwards Anthropic API requests to an Anthropic-compatible upstream
(like api.z.ai) while logging all requests and responses for debugging.

Environment variables:
    ANTHROPIC_UPSTREAM_URL: Upstream base URL (default: https://api.anthropic.com)
    ANTHROPIC_UPSTREAM_KEY: API key for upstream
    ANTHROPIC_UPSTREAM_MODEL: Optional model override
    NERVE_DEBUG_DIR: Directory for debug logs (default: /tmp/nerve-passthrough-debug)

Example:
    ANTHROPIC_UPSTREAM_URL=https://api.z.ai/api/anthropic \
    ANTHROPIC_UPSTREAM_KEY=your-key \
    uv run python scripts/run_anthropic_passthrough.py
"""

import asyncio
import logging
import os
import signal
import sys

# Add src to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nerve.transport.anthropic_passthrough import (
    AnthropicPassthroughConfig,
    AnthropicPassthroughServer,
)

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


async def main():
    api_key = os.environ.get("ANTHROPIC_UPSTREAM_KEY")
    if not api_key:
        print("Error: ANTHROPIC_UPSTREAM_KEY environment variable is required")
        sys.exit(1)

    base_url = os.environ.get("ANTHROPIC_UPSTREAM_URL", "https://api.anthropic.com")
    model = os.environ.get("ANTHROPIC_UPSTREAM_MODEL")  # Optional
    debug_dir = os.environ.get("NERVE_DEBUG_DIR", ".nerve")  # Stores in .nerve/logs/{session}/

    config = AnthropicPassthroughConfig(
        host="127.0.0.1",
        port=3456,
        upstream_base_url=base_url,
        upstream_api_key=api_key,
        upstream_model=model,
        debug_dir=debug_dir,
    )

    print(f"Starting Anthropic passthrough proxy on http://{config.host}:{config.port}")
    print(f"Forwarding to: {base_url}")
    if model:
        print(f"Model override: {model}")
    print(f"Debug logs will be saved to: {debug_dir}/logs/{{session_id}}/")
    print()
    print("Configure Claude Code to use this proxy:")
    print(f"  export ANTHROPIC_BASE_URL=http://{config.host}:{config.port}")
    print()

    server = AnthropicPassthroughServer(config=config)

    # Handle shutdown signals
    loop = asyncio.get_event_loop()

    def handle_signal():
        print("\nShutting down...")
        asyncio.create_task(server.shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
