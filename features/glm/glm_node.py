#!/usr/bin/env python3
"""Feature test for GLMNode (single-shot LLM calls).

Run with: uv run python features/glm/glm_node.py
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
from nerve.core.nodes.llm import GLMNode
from nerve.core.session import Session


async def test_basic_prompt():
    """Test basic string prompt."""
    print("Test: Basic string prompt")

    session = Session("glm-node-test")
    node = GLMNode(
        id="glm-basic",
        session=session,
        api_key=os.environ["GLM_API_KEY"],
        model=os.getenv("GLM_MODEL", "GLM-4.7"),
        http_backend=os.getenv("GLM_HTTP_BACKEND", "openai"),
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

    session = Session("glm-node-test-2")
    node = GLMNode(
        id="glm-messages",
        session=session,
        api_key=os.environ["GLM_API_KEY"],
        model=os.getenv("GLM_MODEL", "GLM-4.7"),
        http_backend=os.getenv("GLM_HTTP_BACKEND", "openai"),
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

    session = Session("glm-node-test-3")
    node = GLMNode(
        id="glm-usage",
        session=session,
        api_key=os.environ["GLM_API_KEY"],
        model=os.getenv("GLM_MODEL", "GLM-4.7"),
        http_backend=os.getenv("GLM_HTTP_BACKEND", "openai"),
    )

    ctx = ExecutionContext(session=session, input="Say hello.")
    result = await node.execute(ctx)

    await node.close()

    assert result["success"], f"Request failed: {result.get('error')}"
    assert result["attributes"]["usage"] is not None, "No usage data"
    assert result["attributes"]["usage"]["total_tokens"] > 0, "No tokens counted"
    print(f"  Usage: {result['attributes']['usage']}")
    print("  ✅ PASSED\n")


async def main():
    print("=" * 60)
    print("GLMNode Feature Tests")
    print("=" * 60 + "\n")

    # Check for API key
    if "GLM_API_KEY" not in os.environ:
        print("ERROR: GLM_API_KEY not set in environment or .env.local")
        sys.exit(1)

    try:
        await test_basic_prompt()
        await test_messages_array()
        await test_usage_tracking()

        print("=" * 60)
        print("✅ All GLMNode tests PASSED")
        print("=" * 60)
    except AssertionError as e:
        print(f"FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
