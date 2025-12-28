#!/usr/bin/env python3
"""Feature test for LLMChatNode tool calling with OpenRouter.

Tests all tool calling features:
- BashNode as tool
- ClaudeWezTermNode as tool
- tool_choice parameter (none, auto, force specific)
- parallel_tool_calls parameter

REQUIREMENTS:
- OpenRouter API key in .env.local
- WezTerm must be running
- Claude CLI must be installed and authenticated

Run with: uv run python features/openrouter/tool_calling.py
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


def get_model():
    return os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku")


def get_http_backend():
    return os.getenv("OPENROUTER_HTTP_BACKEND", "aiohttp")


async def test_bash_tool():
    """Test basic tool calling with BashNode."""
    print("Test 1: BashNode as tool")
    print("-" * 50)

    session = Session("tool-test-1")
    bash = BashNode(id="bash", session=session, timeout=30.0)
    tools, executor = tools_from_nodes([bash])

    llm = OpenRouterNode(
        id="llm",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=get_model(),
        http_backend=get_http_backend(),
    )

    chat = LLMChatNode(
        id="agent",
        session=session,
        llm=llm,
        system="You have access to bash. Use it when asked about system info.",
        tools=tools,
        tool_executor=executor,
    )

    ctx = ExecutionContext(session=session, input="What is today's date? Use bash to find out.")
    result = await chat.execute(ctx)

    assert result["success"], f"Failed: {result.get('error')}"
    tool_used = any(m.role == "tool" for m in chat.messages)
    assert tool_used, "Bash tool was not used"

    print(f"  Response: {result['content'][:100]}...")
    print("  ✅ PASSED\n")

    await chat.close()


async def test_claude_tool():
    """Test ClaudeWezTermNode as tool."""
    print("Test 2: ClaudeWezTermNode as tool")
    print("-" * 50)

    session = Session("tool-test-2")

    # Create ClaudeWezTermNode
    print("  Creating ClaudeWezTermNode...")
    claude_node = await ClaudeWezTermNode.create(
        id="claude",
        session=session,
        command="claude --dangerously-skip-permissions",
        response_timeout=120.0,
    )

    tools, executor = tools_from_nodes([claude_node])

    llm = OpenRouterNode(
        id="llm",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=get_model(),
        http_backend=get_http_backend(),
    )

    chat = LLMChatNode(
        id="agent",
        session=session,
        llm=llm,
        system="You have access to Claude (another AI). Use it when asked to consult Claude.",
        tools=tools,
        tool_executor=executor,
    )

    ctx = ExecutionContext(
        session=session,
        input="Ask Claude what 2+2 is. Keep it brief."
    )
    result = await chat.execute(ctx)

    assert result["success"], f"Failed: {result.get('error')}"
    tool_used = any(m.role == "tool" for m in chat.messages)
    assert tool_used, "Claude tool was not used"

    print(f"  Response: {result['content'][:150]}...")
    print("  ✅ PASSED\n")

    await chat.close()
    await claude_node.stop()


async def test_multiple_tools():
    """Test multiple tools available (bash + claude)."""
    print("Test 3: Multiple tools (bash + claude)")
    print("-" * 50)

    session = Session("tool-test-3")

    bash = BashNode(id="bash", session=session, timeout=30.0)
    claude_node = await ClaudeWezTermNode.create(
        id="claude",
        session=session,
        command="claude --dangerously-skip-permissions",
        response_timeout=120.0,
    )

    tools, executor = tools_from_nodes([bash, claude_node])
    print(f"  Registered tools: {[t.name for t in tools]}")

    llm = OpenRouterNode(
        id="llm",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=get_model(),
        http_backend=get_http_backend(),
    )

    chat = LLMChatNode(
        id="agent",
        session=session,
        llm=llm,
        system="You have bash and claude tools. Use bash for system commands, claude for AI help.",
        tools=tools,
        tool_executor=executor,
    )

    # First use bash
    ctx1 = ExecutionContext(session=session, input="Use bash to show current directory with pwd.")
    result1 = await chat.execute(ctx1)
    assert result1["success"], f"Failed: {result1.get('error')}"
    print(f"  Bash response: {result1['content'][:80]}...")

    # Then use claude
    ctx2 = ExecutionContext(session=session, input="Now ask Claude to say hello briefly.")
    result2 = await chat.execute(ctx2)
    assert result2["success"], f"Failed: {result2.get('error')}"
    print(f"  Claude response: {result2['content'][:80]}...")

    # Verify both tools were used
    tool_names_used = [m.name for m in chat.messages if m.role == "tool"]
    assert "bash" in tool_names_used, "Bash was not used"
    assert "claude" in tool_names_used, "Claude was not used"

    print("  ✅ PASSED\n")

    await chat.close()
    await claude_node.stop()


async def test_tool_choice_none():
    """Test tool_choice='none' prevents tool usage."""
    print("Test 4: tool_choice='none' (disable tools)")
    print("-" * 50)

    session = Session("tool-test-4")
    bash = BashNode(id="bash", session=session, timeout=30.0)
    tools, executor = tools_from_nodes([bash])

    llm = OpenRouterNode(
        id="llm",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=get_model(),
        http_backend=get_http_backend(),
    )

    chat = LLMChatNode(
        id="agent",
        session=session,
        llm=llm,
        system="You have bash. Use it when asked about system info.",
        tools=tools,
        tool_executor=executor,
        tool_choice="none",  # Disable tools
    )

    ctx = ExecutionContext(session=session, input="What is today's date? Use bash.")
    result = await chat.execute(ctx)

    assert result["success"], f"Failed: {result.get('error')}"
    tool_used = any(m.role == "tool" for m in chat.messages)
    assert not tool_used, "Tool was used despite tool_choice='none'"

    print(f"  Response: {result['content'][:100]}...")
    print("  Tool calls: None (as expected)")
    print("  ✅ PASSED\n")

    await chat.close()


async def test_tool_choice_force():
    """Test forcing a specific tool."""
    print("Test 5: tool_choice=force specific tool")
    print("-" * 50)

    session = Session("tool-test-5")
    bash = BashNode(id="bash", session=session, timeout=30.0)
    tools, executor = tools_from_nodes([bash])

    llm = OpenRouterNode(
        id="llm",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=get_model(),
        http_backend=get_http_backend(),
    )

    chat = LLMChatNode(
        id="agent",
        session=session,
        llm=llm,
        system="You are helpful. After using a tool once, provide a final response.",
        tools=tools,
        tool_executor=executor,
        tool_choice={"type": "function", "function": {"name": "bash"}},
        max_tool_rounds=2,  # Limit rounds since forcing creates loops
    )

    # Simple greeting that normally wouldn't need a tool
    ctx = ExecutionContext(session=session, input="Hello!")
    result = await chat.execute(ctx)

    # With forced tool, either it succeeds or hits max rounds (both prove forcing worked)
    tool_used = any(m.role == "tool" for m in chat.messages)
    assert tool_used, "Tool was not forced"

    print(f"  Response: {result['content'][:100] if result['content'] else '(hit max rounds)'}...")
    print("  Tool was forced for simple greeting")
    print("  ✅ PASSED\n")

    await chat.close()


async def test_parallel_tool_calls_false():
    """Test parallel_tool_calls=False for sequential execution."""
    print("Test 6: parallel_tool_calls=False")
    print("-" * 50)

    session = Session("tool-test-6")
    bash = BashNode(id="bash", session=session, timeout=30.0)
    tools, executor = tools_from_nodes([bash])

    llm = OpenRouterNode(
        id="llm",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=get_model(),
        http_backend=get_http_backend(),
    )

    chat = LLMChatNode(
        id="agent",
        session=session,
        llm=llm,
        system="You have bash. Be concise.",
        tools=tools,
        tool_executor=executor,
        parallel_tool_calls=False,  # Force sequential
    )

    ctx = ExecutionContext(session=session, input="Run 'echo hello' with bash.")
    result = await chat.execute(ctx)

    assert result["success"], f"Failed: {result.get('error')}"

    print(f"  Response: {result['content'][:100]}...")
    print("  parallel_tool_calls=False applied")
    print("  ✅ PASSED\n")

    await chat.close()


async def test_tool_choice_auto():
    """Test tool_choice='auto' (default behavior, explicit)."""
    print("Test 7: tool_choice='auto' (explicit)")
    print("-" * 50)

    session = Session("tool-test-7")
    bash = BashNode(id="bash", session=session, timeout=30.0)
    tools, executor = tools_from_nodes([bash])

    llm = OpenRouterNode(
        id="llm",
        session=session,
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=get_model(),
        http_backend=get_http_backend(),
    )

    chat = LLMChatNode(
        id="agent",
        session=session,
        llm=llm,
        system="You have bash. Use it only when necessary.",
        tools=tools,
        tool_executor=executor,
        tool_choice="auto",  # Explicit auto
    )

    # Ask something that needs bash
    ctx = ExecutionContext(session=session, input="What user am I? Use whoami.")
    result = await chat.execute(ctx)

    assert result["success"], f"Failed: {result.get('error')}"
    tool_used = any(m.role == "tool" for m in chat.messages)
    assert tool_used, "Tool should be used with tool_choice='auto'"

    print(f"  Response: {result['content'][:100]}...")
    print("  ✅ PASSED\n")

    await chat.close()


async def main():
    print("=" * 60)
    print("OpenRouter Tool Calling Feature Tests")
    print("=" * 60)
    print(f"Model: {get_model()}")
    print(f"HTTP Backend: {get_http_backend()}")
    print("=" * 60 + "\n")

    # Check for API key
    if "OPENROUTER_API_KEY" not in os.environ:
        print("ERROR: OPENROUTER_API_KEY not set in environment or .env.local")
        sys.exit(1)

    passed = 0
    failed = 0
    errors = []

    tests = [
        ("BashNode as tool", test_bash_tool),
        ("ClaudeWezTermNode as tool", test_claude_tool),
        ("Multiple tools", test_multiple_tools),
        ("tool_choice='none'", test_tool_choice_none),
        ("tool_choice=force", test_tool_choice_force),
        ("parallel_tool_calls=False", test_parallel_tool_calls_false),
        ("tool_choice='auto'", test_tool_choice_auto),
    ]

    for name, test_fn in tests:
        try:
            await test_fn()
            passed += 1
        except AssertionError as e:
            failed += 1
            errors.append(f"{name}: ASSERTION FAILED - {e}")
            print(f"  ❌ FAILED: {e}\n")
        except Exception as e:
            failed += 1
            errors.append(f"{name}: ERROR - {type(e).__name__}: {e}")
            print(f"  ❌ ERROR: {type(e).__name__}: {e}\n")

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if errors:
        print("\nFailures:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("\n✅ All tool calling tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
