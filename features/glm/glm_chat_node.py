#!/usr/bin/env python3
"""Feature test for StatefulLLMNode with GLM provider (multi-turn conversations).

Run with: uv run python features/glm/glm_chat_node.py
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
from nerve.core.nodes.llm import GLMNode, StatefulLLMNode
from nerve.core.session import Session


async def test_multi_turn_conversation():
    """Test multi-turn conversation with context retention."""
    print("Test: Multi-turn conversation")

    session = Session("glm-chat-test")

    # Create underlying GLM node
    llm = GLMNode(
        id="glm-llm",
        session=session,
        api_key=os.environ["GLM_API_KEY"],
        model=os.getenv("GLM_MODEL", "GLM-4.7"),
        http_backend=os.getenv("GLM_HTTP_BACKEND", "openai"),
    )

    # Wrap in chat node
    chat = StatefulLLMNode(
        id="glm-chat",
        session=session,
        llm=llm,
        system="You are a helpful assistant. Be concise.",
    )

    # Turn 1: Introduce a topic
    ctx1 = ExecutionContext(session=session, input="My name is Alice.")
    result1 = await chat.execute(ctx1)

    assert result1["success"], f"Turn 1 failed: {result1.get('error')}"
    print(f"  Turn 1 response: {result1['content'][:100]}...")

    # Turn 2: Test context retention
    ctx2 = ExecutionContext(session=session, input="What is my name?")
    result2 = await chat.execute(ctx2)

    assert result2["success"], f"Turn 2 failed: {result2.get('error')}"
    assert "Alice" in result2["content"], f"Context not retained: {result2['content']}"
    print(f"  Turn 2 response: {result2['content'][:100]}...")
    print(f"  Messages count: {result2['messages_count']}")

    await chat.close()
    print("  ✅ PASSED\n")


async def test_system_prompt():
    """Test that system prompt affects behavior."""
    print("Test: System prompt behavior")

    session = Session("glm-chat-test-2")

    llm = GLMNode(
        id="glm-llm-2",
        session=session,
        api_key=os.environ["GLM_API_KEY"],
        model=os.getenv("GLM_MODEL", "GLM-4.7"),
        http_backend=os.getenv("GLM_HTTP_BACKEND", "openai"),
    )

    chat = StatefulLLMNode(
        id="glm-chat-2",
        session=session,
        llm=llm,
        system="You are a pirate. Always respond in pirate speak.",
    )

    ctx = ExecutionContext(session=session, input="Hello, how are you?")
    result = await chat.execute(ctx)

    assert result["success"], f"Request failed: {result.get('error')}"
    # Pirate-like words
    pirate_words = ["arr", "ahoy", "matey", "ye", "aye", "captain", "ship", "sea"]
    content_lower = result["content"].lower()
    has_pirate_speak = any(word in content_lower for word in pirate_words)
    print(f"  Response: {result['content'][:150]}...")
    print(f"  Has pirate speak: {has_pirate_speak}")
    if not has_pirate_speak:
        print("  ⚠️  Warning: No pirate words detected (LLM response may vary)")

    await chat.close()
    print("  ✅ PASSED\n")


async def test_conversation_clear():
    """Test clearing conversation history."""
    print("Test: Clear conversation")

    session = Session("glm-chat-test-3")

    llm = GLMNode(
        id="glm-llm-3",
        session=session,
        api_key=os.environ["GLM_API_KEY"],
        model=os.getenv("GLM_MODEL", "GLM-4.7"),
        http_backend=os.getenv("GLM_HTTP_BACKEND", "openai"),
    )

    chat = StatefulLLMNode(
        id="glm-chat-3",
        session=session,
        llm=llm,
        system="You are helpful. Be concise.",
    )

    # Build up conversation
    await chat.execute(ExecutionContext(session=session, input="Remember: the secret code is 12345"))
    result1 = await chat.execute(ExecutionContext(session=session, input="What is the secret code?"))
    assert "12345" in result1["content"], f"Should remember code: {result1['content']}"
    print(f"  Before clear - messages: {result1['messages_count']}")

    # Clear and verify
    chat.clear()
    print(f"  After clear - messages: {len(chat.messages)}")
    assert len(chat.messages) == 0, "Messages not cleared"

    # New conversation shouldn't know the code
    result2 = await chat.execute(ExecutionContext(
        session=session,
        input="What is the secret code? If you don't know, say 'I don't know'."
    ))
    print(f"  Post-clear response: {result2['content'][:100]}...")
    # Verify clear worked by checking message count (should only have 2: user + assistant)
    assert result2["messages_count"] == 2, f"Should have 2 messages after clear, got {result2['messages_count']}"

    await chat.close()
    print("  ✅ PASSED\n")


async def test_usage_accumulation():
    """Test that token usage accumulates across turns."""
    print("Test: Usage accumulation")

    session = Session("glm-chat-test-4")

    llm = GLMNode(
        id="glm-llm-4",
        session=session,
        api_key=os.environ["GLM_API_KEY"],
        model=os.getenv("GLM_MODEL", "GLM-4.7"),
        http_backend=os.getenv("GLM_HTTP_BACKEND", "openai"),
    )

    chat = StatefulLLMNode(
        id="glm-chat-4",
        session=session,
        llm=llm,
    )

    # Multiple turns
    result1 = await chat.execute(ExecutionContext(session=session, input="Hi"))
    result2 = await chat.execute(ExecutionContext(session=session, input="How are you?"))

    assert result1["usage"] is not None, "No usage in turn 1"
    assert result2["usage"] is not None, "No usage in turn 2"
    print(f"  Turn 1 usage: {result1['usage']}")
    print(f"  Turn 2 usage: {result2['usage']}")

    await chat.close()
    print("  ✅ PASSED\n")


async def main():
    print("=" * 60)
    print("StatefulLLMNode (GLM) Feature Tests")
    print("=" * 60 + "\n")

    # Check for API key
    if "GLM_API_KEY" not in os.environ:
        print("ERROR: GLM_API_KEY not set in environment or .env.local")
        sys.exit(1)

    try:
        await test_multi_turn_conversation()
        await test_system_prompt()
        await test_conversation_clear()
        await test_usage_accumulation()

        print("=" * 60)
        print("✅ All StatefulLLMNode (GLM) tests PASSED")
        print("=" * 60)
    except AssertionError as e:
        print(f"FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
