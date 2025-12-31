#!/usr/bin/env python3
"""Feature test for OpenRouterNode (single-shot LLM calls).

Run with: uv run python features/openrouter/openrouter_node.py
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env.local from project root
project_root = Path(__file__).parents[2]
env_local = project_root / ".env.local"
if env_local.exists():
    load_dotenv(env_local)
else:
    print(f"Warning: {env_local} not found")

from nerve.core.nodes.context import ExecutionContext
from nerve.core.nodes.llm import OpenRouterNode
from nerve.core.session import Session


async def test_basic_prompt():
    """Test basic string prompt."""
    print("Test: Basic string prompt")

    session = Session("openrouter-node-test")
    node = OpenRouterNode(
        id="openrouter-basic",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku"),
        http_backend=os.getenv("OPENROUTER_HTTP_BACKEND", "aiohttp"),
    )

    ctx = ExecutionContext(session=session, input="What is 2+2? Answer with just the number.")
    result = await node.execute(ctx)

    await node.close()

    assert result["success"], f"Request failed: {result.get('error')}"
    assert result["attributes"]["content"] is not None, "No content in response"
    print(f"  Response: {result['attributes']['content']}")
    print(f"  Model: {result['attributes']['model']}")
    print("  ✅ PASSED\n")


async def test_messages_array():
    """Test messages array input."""
    print("Test: Messages array input")

    session = Session("openrouter-node-test-2")
    node = OpenRouterNode(
        id="openrouter-messages",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku"),
        http_backend=os.getenv("OPENROUTER_HTTP_BACKEND", "aiohttp"),
    )

    messages = [
        {"role": "system", "content": "You are a helpful assistant. Be concise."},
        {"role": "user", "content": "What is the capital of France?"},
    ]

    ctx = ExecutionContext(session=session, input=messages)
    result = await node.execute(ctx)

    await node.close()

    assert result["success"], f"Request failed: {result.get('error')}"
    assert "Paris" in result["attributes"]["content"], f"Expected 'Paris' in response: {result['attributes']['content']}"
    print(f"  Response: {result['attributes']['content']}")
    print("  ✅ PASSED\n")


async def test_usage_tracking():
    """Test that token usage is tracked."""
    print("Test: Usage tracking")

    session = Session("openrouter-node-test-3")
    node = OpenRouterNode(
        id="openrouter-usage",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku"),
        http_backend=os.getenv("OPENROUTER_HTTP_BACKEND", "aiohttp"),
    )

    ctx = ExecutionContext(session=session, input="Say hello.")
    result = await node.execute(ctx)

    await node.close()

    assert result["success"], f"Request failed: {result.get('error')}"
    assert result["attributes"]["usage"] is not None, "No usage data"
    assert result["attributes"]["usage"]["total_tokens"] > 0, "No tokens counted"
    print(f"  Usage: {result['attributes']['usage']}")
    print("  ✅ PASSED\n")


async def test_different_models():
    """Test with a different model."""
    print("Test: Different model")

    session = Session("openrouter-node-test-4")

    # Use a different model (if available)
    alt_model = os.getenv("OPENROUTER_ALT_MODEL", "google/gemini-3-flash-preview")

    node = OpenRouterNode(
        id="openrouter-alt",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=alt_model,
        http_backend=os.getenv("OPENROUTER_HTTP_BACKEND", "aiohttp"),
    )

    ctx = ExecutionContext(session=session, input="What is 3+3? Answer with just the number.")
    result = await node.execute(ctx)

    await node.close()

    assert result["success"], f"Request failed: {result.get('error')}"
    print(f"  Model used: {result['model']}")
    print(f"  Response: {result['content']}")
    print("  ✅ PASSED\n")


async def main():
    print("=" * 60)
    print("OpenRouterNode Feature Tests")
    print("=" * 60 + "\n")

    # Check for API key
    if "OPENROUTER_API_KEY" not in os.environ:
        print("ERROR: OPENROUTER_API_KEY not set in environment or .env.local")
        sys.exit(1)

    try:
        await test_basic_prompt()
        await test_messages_array()
        await test_usage_tracking()
        await test_different_models()

        print("=" * 60)
        print("✅ All OpenRouterNode tests PASSED")
        print("=" * 60)
    except AssertionError as e:
        print(f"FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
