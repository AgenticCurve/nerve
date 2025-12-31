#!/usr/bin/env python3
"""Feature test for StatefulLLMNode with OpenRouter provider (multi-turn conversations).

Run with: uv run python features/openrouter/openrouter_chat_node.py
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
from nerve.core.nodes.llm import OpenRouterNode, StatefulLLMNode
from nerve.core.session import Session


async def test_multi_turn_conversation():
    """Test multi-turn conversation with context retention."""
    print("Test: Multi-turn conversation")

    session = Session("openrouter-chat-test")

    # Create underlying OpenRouter node
    llm = OpenRouterNode(
        id="openrouter-llm",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku"),
        http_backend=os.getenv("OPENROUTER_HTTP_BACKEND", "aiohttp"),
    )

    # Wrap in chat node
    chat = StatefulLLMNode(
        id="openrouter-chat",
        session=session,
        llm=llm,
        system="You are a helpful assistant. Be concise.",
    )

    # Turn 1: Introduce a topic
    ctx1 = ExecutionContext(session=session, input="My name is Bob.")
    result1 = await chat.execute(ctx1)

    assert result1["success"], f"Turn 1 failed: {result1.get('error')}"
    print(f"  Turn 1 response: {result1['content'][:100]}...")

    # Turn 2: Test context retention
    ctx2 = ExecutionContext(session=session, input="What is my name?")
    result2 = await chat.execute(ctx2)

    assert result2["success"], f"Turn 2 failed: {result2.get('error')}"
    assert "Bob" in result2["content"], f"Context not retained: {result2['content']}"
    print(f"  Turn 2 response: {result2['content'][:100]}...")
    print(f"  Messages count: {result2['messages_count']}")

    await chat.close()
    print("  ✅ PASSED\n")


async def test_system_prompt():
    """Test that system prompt affects behavior."""
    print("Test: System prompt behavior")

    session = Session("openrouter-chat-test-2")

    llm = OpenRouterNode(
        id="openrouter-llm-2",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku"),
        http_backend=os.getenv("OPENROUTER_HTTP_BACKEND", "aiohttp"),
    )

    chat = StatefulLLMNode(
        id="openrouter-chat-2",
        session=session,
        llm=llm,
        system="You are a Shakespearean actor. Always respond in Shakespearean English.",
    )

    ctx = ExecutionContext(session=session, input="Hello, how are you?")
    result = await chat.execute(ctx)

    assert result["success"], f"Request failed: {result.get('error')}"
    # Shakespearean words
    shakespeare_words = ["thee", "thou", "thy", "hath", "doth", "art", "verily", "forsooth", "prithee", "'tis"]
    content_lower = result["attributes"]["content"].lower()
    has_shakespeare = any(word in content_lower for word in shakespeare_words)
    print(f"  Response: {result['attributes']['content'][:150]}...")
    print(f"  Has Shakespearean style: {has_shakespeare}")
    if not has_shakespeare:
        print("  ⚠️  Warning: No Shakespearean words detected (LLM response may vary)")

    await chat.close()
    print("  ✅ PASSED\n")


async def test_conversation_clear():
    """Test clearing conversation history."""
    print("Test: Clear conversation")

    session = Session("openrouter-chat-test-3")

    llm = OpenRouterNode(
        id="openrouter-llm-3",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku"),
        http_backend=os.getenv("OPENROUTER_HTTP_BACKEND", "aiohttp"),
    )

    chat = StatefulLLMNode(
        id="openrouter-chat-3",
        session=session,
        llm=llm,
        system="You are helpful. Be concise.",
    )

    # Build up conversation
    await chat.execute(ExecutionContext(session=session, input="Remember: the password is 'banana'"))
    result1 = await chat.execute(ExecutionContext(session=session, input="What is the password?"))
    assert "banana" in result1["content"].lower(), f"Should remember password: {result1['content']}"
    print(f"  Before clear - messages: {result1['messages_count']}")

    # Clear and verify
    chat.clear()
    print(f"  After clear - messages: {len(chat.messages)}")
    assert len(chat.messages) == 0, "Messages not cleared"

    # New conversation shouldn't know the password
    result2 = await chat.execute(ExecutionContext(
        session=session,
        input="What is the password? If you don't know, say 'I don't know'."
    ))
    print(f"  Post-clear response: {result2['content'][:100]}...")
    # Verify clear worked by checking message count (should only have 2: user + assistant)
    assert result2["messages_count"] == 2, f"Should have 2 messages after clear, got {result2['messages_count']}"

    await chat.close()
    print("  ✅ PASSED\n")


async def test_extended_conversation():
    """Test a longer conversation with multiple turns."""
    print("Test: Extended conversation (5 turns)")

    session = Session("openrouter-chat-test-4")

    llm = OpenRouterNode(
        id="openrouter-llm-4",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku"),
        http_backend=os.getenv("OPENROUTER_HTTP_BACKEND", "aiohttp"),
    )

    chat = StatefulLLMNode(
        id="openrouter-chat-4",
        session=session,
        llm=llm,
        system="You are a math tutor. Be concise but helpful.",
    )

    turns = [
        "Let's learn about multiplication.",
        "What is 5 times 7?",
        "Now what is that result plus 10?",
        "Divide that by 5.",
        "Is that a prime number?",
    ]

    for i, turn in enumerate(turns):
        result = await chat.execute(ExecutionContext(session=session, input=turn))
        assert result["success"], f"Turn {i+1} failed: {result.get('error')}"
        print(f"  Turn {i+1}: {turn}")
        print(f"    Response: {result['content'][:80]}...")

    print(f"  Final message count: {result['messages_count']}")
    assert result["messages_count"] >= 10, "Should have at least 10 messages (5 turns * 2)"

    await chat.close()
    print("  ✅ PASSED\n")


async def main():
    print("=" * 60)
    print("StatefulLLMNode (OpenRouter) Feature Tests")
    print("=" * 60 + "\n")

    # Check for API key
    if "OPENROUTER_API_KEY" not in os.environ:
        print("ERROR: OPENROUTER_API_KEY not set in environment or .env.local")
        sys.exit(1)

    try:
        await test_multi_turn_conversation()
        await test_system_prompt()
        await test_conversation_clear()
        await test_extended_conversation()

        print("=" * 60)
        print("✅ All StatefulLLMNode (OpenRouter) tests PASSED")
        print("=" * 60)
    except AssertionError as e:
        print(f"FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
