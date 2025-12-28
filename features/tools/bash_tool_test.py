#!/usr/bin/env python3
"""Feature test for LLMChatNode with BashNode as a tool.

This test demonstrates an LLM agent that can execute bash commands
to answer questions about the system.

Run with: uv run python features/tools/bash_tool_test.py
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

from nerve.core.nodes import BashNode, ExecutionContext, tools_from_nodes
from nerve.core.nodes.llm import LLMChatNode, OpenRouterNode
from nerve.core.session import Session


async def test_bash_tool():
    """Test LLMChatNode using BashNode as a tool."""
    print("=" * 60)
    print("Test: LLMChatNode with BashNode Tool")
    print("=" * 60)

    session = Session("bash-tool-test")

    # Create BashNode (tool-capable)
    bash = BashNode(id="bash", session=session, timeout=30.0)

    # Create tools from bash node
    tools, executor = tools_from_nodes([bash])
    print(f"\nRegistered tools: {[t.name for t in tools]}")

    # Create underlying LLM
    llm = OpenRouterNode(
        id="llm",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku"),
        http_backend=os.getenv("OPENROUTER_HTTP_BACKEND", "aiohttp"),
    )

    # Create chat node with tools
    chat = LLMChatNode(
        id="agent",
        session=session,
        llm=llm,
        system="""You are a helpful assistant with access to a bash tool for running shell commands.

IMPORTANT: When the user asks about files, directories, system info, or anything that requires
checking the actual system state, you MUST use the bash tool. Do not guess or make up answers.

Be concise in your responses.""",
        tools=tools,
        tool_executor=executor,
    )

    # Turn 1: Simple greeting (no tool needed)
    print("\n" + "-" * 40)
    print("Turn 1: Simple greeting")
    print("-" * 40)
    ctx1 = ExecutionContext(session=session, input="Hello! What can you help me with?")
    result1 = await chat.execute(ctx1)

    if result1["success"]:
        print(f"User: Hello! What can you help me with?")
        print(f"Agent: {result1['content'][:200]}...")
    else:
        print(f"ERROR: {result1.get('error')}")
        return False

    # Turn 2: Ask about current date (should use bash)
    print("\n" + "-" * 40)
    print("Turn 2: Ask about current date (should use bash tool)")
    print("-" * 40)
    ctx2 = ExecutionContext(session=session, input="What is today's date?")
    result2 = await chat.execute(ctx2)

    if result2["success"]:
        print(f"User: What is today's date?")
        print(f"Agent: {result2['content']}")
        if result2.get("tool_calls"):
            print(f"  (Tool calls made in this response)")
    else:
        print(f"ERROR: {result2.get('error')}")
        return False

    # Turn 3: Ask to list files (should use bash)
    print("\n" + "-" * 40)
    print("Turn 3: Ask to list files (should use bash tool)")
    print("-" * 40)
    ctx3 = ExecutionContext(
        session=session,
        input="Use the bash tool to run 'ls -la' and tell me what files you see."
    )
    result3 = await chat.execute(ctx3)

    if result3["success"]:
        print(f"User: Can you list the files in the current directory?")
        print(f"Agent: {result3['content']}")
        # Show conversation history to see tool usage
        print("\n  Conversation history:")
        for i, msg in enumerate(chat.messages[-6:]):  # Last 6 messages
            role = msg.role
            if role == "tool":
                print(f"    [{i}] {role} ({msg.name}): {msg.content[:100]}...")
            elif msg.tool_calls:
                print(f"    [{i}] {role}: [tool_calls: {[tc.get('function', {}).get('name') for tc in msg.tool_calls]}]")
            else:
                content = msg.content or "(empty)"
                print(f"    [{i}] {role}: {content[:80]}...")
    else:
        print(f"ERROR: {result3.get('error')}")
        return False

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total messages in conversation: {result3['messages_count']}")
    print(f"Total usage: {result3.get('usage', {})}")

    await chat.close()
    return True


async def main():
    # Check for API key
    if "OPENROUTER_API_KEY" not in os.environ:
        print("ERROR: OPENROUTER_API_KEY not set in environment or .env.local")
        sys.exit(1)

    try:
        success = await test_bash_tool()
        if success:
            print("\n" + "=" * 60)
            print("PASSED: LLMChatNode successfully used BashNode as a tool")
            print("=" * 60)
        else:
            print("\nFAILED")
            sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
