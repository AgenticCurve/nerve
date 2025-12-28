#!/usr/bin/env python3
"""Feature test for LLMChatNode with ClaudeWezTermNode as a tool.

This test demonstrates an LLM agent that can ask Claude (another AI)
for help, opinions, or to perform tasks.

REQUIREMENTS:
- WezTerm must be running
- Claude CLI must be installed and authenticated
- OpenRouter API key in .env.local

Run with: uv run python features/tools/claude_tool_test.py
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
from nerve.core.nodes.terminal import ClaudeWezTermNode
from nerve.core.session import Session


async def test_claude_tool():
    """Test LLMChatNode using ClaudeWezTermNode as a tool."""
    print("=" * 60)
    print("Test: LLMChatNode with ClaudeWezTerm Tool")
    print("=" * 60)

    session = Session("claude-tool-test")

    # Create ClaudeWezTermNode (persistent node)
    print("\nCreating ClaudeWezTermNode...")
    try:
        claude_node = await ClaudeWezTermNode.create(
            id="claude-friend",
            session=session,
            command="claude --dangerously-skip-permissions",
            response_timeout=120.0,
        )
        print(f"  Created: {claude_node}")
    except Exception as e:
        print(f"ERROR: Failed to create ClaudeWezTermNode: {e}")
        print("Make sure WezTerm is running and Claude CLI is installed.")
        return False

    # Also create BashNode for comparison
    bash = BashNode(id="bash", session=session, timeout=30.0)

    # Create tools from both nodes
    tools, executor = tools_from_nodes([claude_node, bash])
    print(f"Registered tools: {[t.name for t in tools]}")

    # Create underlying LLM (the "manager" agent)
    llm = OpenRouterNode(
        id="llm",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku"),
        http_backend=os.getenv("OPENROUTER_HTTP_BACKEND", "aiohttp"),
    )

    # Create chat node with tools
    chat = LLMChatNode(
        id="manager",
        session=session,
        llm=llm,
        system="""You are a manager agent with access to two tools:

1. claude-friend: Another AI assistant (Claude) you can ask for help, opinions, or complex tasks.
   Use this when you need a second opinion, want to delegate a task, or need help thinking through something.

2. bash: Execute shell commands to interact with the system.

When asked to consult Claude, you MUST use the claude-friend tool.
Be concise in your responses.""",
        tools=tools,
        tool_executor=executor,
    )

    try:
        # Turn 1: Simple greeting (no tool needed)
        print("\n" + "-" * 40)
        print("Turn 1: Simple greeting")
        print("-" * 40)
        ctx1 = ExecutionContext(session=session, input="Hello! What tools do you have available?")
        result1 = await chat.execute(ctx1)

        if result1["success"]:
            print(f"User: Hello! What tools do you have available?")
            print(f"Manager: {result1['content'][:300]}...")
        else:
            print(f"ERROR: {result1.get('error')}")
            return False

        # Turn 2: Ask the manager to consult Claude
        print("\n" + "-" * 40)
        print("Turn 2: Ask manager to consult Claude for an opinion")
        print("-" * 40)
        ctx2 = ExecutionContext(
            session=session,
            input="Ask your friend Claude what they think is the most important programming concept for beginners to learn. Keep it brief."
        )
        result2 = await chat.execute(ctx2)

        if result2["success"]:
            print(f"User: Ask your friend Claude...")
            print(f"Manager: {result2['content']}")

            # Show conversation to see tool usage
            print("\n  Recent conversation:")
            for msg in chat.messages[-4:]:
                role = msg.role
                if role == "tool":
                    content = msg.content[:150] + "..." if len(msg.content or "") > 150 else msg.content
                    print(f"    [{role}] ({msg.name}): {content}")
                elif msg.tool_calls:
                    print(f"    [{role}]: [tool_calls: {[tc.get('function', {}).get('name') for tc in msg.tool_calls]}]")
                else:
                    content = msg.content[:100] + "..." if len(msg.content or "") > 100 else msg.content
                    print(f"    [{role}]: {content}")
        else:
            print(f"ERROR: {result2.get('error')}")
            return False

        # Summary
        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        print(f"Total messages in conversation: {result2['messages_count']}")

        return True

    finally:
        # Cleanup
        print("\nCleaning up...")
        await chat.close()
        await claude_node.stop()


async def main():
    # Check for API key
    if "OPENROUTER_API_KEY" not in os.environ:
        print("ERROR: OPENROUTER_API_KEY not set in environment or .env.local")
        sys.exit(1)

    try:
        success = await test_claude_tool()
        if success:
            print("\n" + "=" * 60)
            print("PASSED: LLMChatNode successfully used ClaudeWezTermNode as a tool")
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
