#!/usr/bin/env python3
"""Two-agent debate/discussion.

Creates two Claude instances that discuss topics:
- Default: Python vs JavaScript debate
- AEC: Architecture/Engineering/Construction industry opportunities

Messages flow: A → B → A → B → A → B ...

Usage:
    python examples/debate.py [server_name] [rounds] [transport] [topic]
    python examples/debate.py debate-test 3                              # Default debate
    python examples/debate.py debate-test 3 http                         # HTTP transport
    python examples/debate.py debate-test 3 tcp                          # TCP transport
    python examples/debate.py aec-test 50 tcp aec                        # AEC discussion, 50 rounds
"""

import asyncio
import sys

from nerve.server.protocols import Command, CommandType


def extract_text_response(response_data: dict) -> str:
    """Extract the text content from a parsed response."""
    sections = response_data.get("attributes", {}).get("sections", [])

    # Collect all text sections
    text_parts = []
    for section in sections:
        if section.get("type") == "text":
            content = section.get("content", "").strip()
            if content:
                text_parts.append(content)

    if text_parts:
        return "\n".join(text_parts)

    # Fallback to raw (truncated)
    return response_data.get("attributes", {}).get("raw", "")[:500]


async def run_debate(
    server_name: str = "debate-test",
    rounds: int = 3,
    transport: str = "unix",
    topic: str = "python-vs-javascript",
    cwd: str = "/Users/pb/agentic-curve/projects/nerve",
):
    """Run a debate between two Claude agents."""

    # Configure transport
    if transport == "http":
        from nerve.transport import HTTPClient

        host, port = "127.0.0.1", 8765
        connection_str = f"http://{host}:{port}"
        server_args = ["--http", "--host", host, "--port", str(port)]
        client = HTTPClient(f"http://{host}:{port}")
    elif transport == "tcp":
        from nerve.transport import TCPSocketClient

        host, port = "127.0.0.1", 9876
        connection_str = f"tcp://{host}:{port}"
        server_args = ["--tcp", "--host", host, "--port", str(port)]
        client = TCPSocketClient(host, port)
    else:
        from nerve.transport import UnixSocketClient

        connection_str = f"/tmp/nerve-{server_name}.sock"
        server_args = []
        client = UnixSocketClient(connection_str)

    # Start server
    print(f"Starting server '{server_name}' ({transport})...")
    cmd = ["uv", "run", "nerve", "server", "start", server_name] + server_args
    await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.sleep(2)

    # Connect
    print(f"Connecting to {connection_str}...")

    try:
        await client.connect()
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    # Create two nodes
    print("\nCreating Agent A (Python advocate)...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_NODE,
            params={
                "node_id": "agent-a",
                "command": "claude",
                "cwd": cwd,
                "backend": "claude-wezterm",
            },
        )
    )
    if not result.success:
        print(f"Failed to create agent-a: {result.error}")
        return
    print("  Created: agent-a")

    print("Creating Agent B (JavaScript advocate)...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_NODE,
            params={
                "node_id": "agent-b",
                "command": "claude",
                "cwd": cwd,
                "backend": "claude-wezterm",
            },
        )
    )
    if not result.success:
        print(f"Failed to create agent-b: {result.error}")
        return
    print("  Created: agent-b")

    # Wait for Claude instances to be ready
    print("\nWaiting for Claude instances to initialize...")
    await asyncio.sleep(5)

    # Topic-specific prompts
    if topic == "aec":
        topic_title = "AEC Industry: Upcoming Opportunities & Future"
        agent_a_system = """You are an AEC (Architecture, Engineering, Construction) industry expert focused on TECHNOLOGY opportunities.
You believe the biggest opportunities lie in: AI/ML, digital twins, BIM, automation, robotics, and software platforms.
Keep your responses concise (2-3 paragraphs max).
Build on previous points, introduce new ideas, and engage with your colleague's perspective.
End with a thought-provoking insight or question."""

        agent_b_system = """You are an AEC (Architecture, Engineering, Construction) industry expert focused on SUSTAINABILITY opportunities.
You believe the biggest opportunities lie in: green building, carbon reduction, circular economy, renewable materials, and ESG compliance.
Keep your responses concise (2-3 paragraphs max).
Build on previous points, introduce new ideas, and engage with your colleague's perspective.
End with a thought-provoking insight or question."""

        opening_prompt = f"""{agent_a_system}

Start the discussion by sharing your view on the most exciting technology opportunities in the AEC industry over the next 5-10 years.
What innovations do you see transforming how we design, build, and operate buildings and infrastructure?"""

    else:  # Default: python-vs-javascript
        topic_title = "Python vs JavaScript"
        agent_a_system = """You are debating in favor of Python as the best programming language.
Keep your responses concise (2-3 paragraphs max).
Be passionate but respectful. Address your opponent's points directly.
End with a strong argument or question for your opponent."""

        agent_b_system = """You are debating in favor of JavaScript as the best programming language.
Keep your responses concise (2-3 paragraphs max).
Be passionate but respectful. Address your opponent's points directly.
End with a strong argument or question for your opponent."""

        opening_prompt = f"""{agent_a_system}

Start the debate by making your opening argument for why Python is the best programming language.
Address a JavaScript developer who disagrees with you."""

    print("\n" + "=" * 70)
    print(f"DEBATE: {topic_title}")
    print("=" * 70)

    # Agent labels based on topic
    if topic == "aec":
        label_a = "AGENT A - Technology Expert"
        label_b = "AGENT B - Sustainability Expert"
    else:
        label_a = "AGENT A - Python Advocate"
        label_b = "AGENT B - JavaScript Advocate"

    print(f"\n[{label_a}]")
    print("-" * 70)

    result = await client.send_command(
        Command(
            type=CommandType.EXECUTE_INPUT,
            params={
                "node_id": "agent-a",
                "text": opening_prompt,
                "parser": "claude",
            },
        ),
        timeout=300.0,  # 5 minutes for long responses / compaction
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    response_a = extract_text_response(result.data.get("response", {}))
    print(response_a)

    # Now run the debate loop
    for round_num in range(rounds):
        print(f"\n{'=' * 70}")
        print(f"ROUND {round_num + 1}/{rounds}")
        print("=" * 70)

        # Agent B responds to Agent A
        if topic == "aec":
            prompt_b = f"""{agent_b_system}

Your colleague (focused on technology) just shared:

\"\"\"{response_a}\"\"\"

Respond to their points and share your perspective on sustainability opportunities in AEC."""
        else:
            prompt_b = f"""{agent_b_system}

Your opponent (a Python advocate) just said:

\"\"\"{response_a}\"\"\"

Respond to their arguments and make your case for JavaScript."""

        print(f"\n[{label_b}]")
        print("-" * 70)

        result = await client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params={
                    "node_id": "agent-b",
                    "text": prompt_b,
                    "parser": "claude",
                },
            ),
            timeout=300.0,  # 5 minutes for long responses / compaction
        )

        if not result.success:
            print(f"Error: {result.error}")
            break

        response_b = extract_text_response(result.data.get("response", {}))
        print(response_b)

        # Agent A responds to Agent B
        if topic == "aec":
            prompt_a = f"""Your colleague (focused on sustainability) just shared:

\"\"\"{response_b}\"\"\"

Build on their points and share more technology perspectives. What synergies do you see?"""
        else:
            prompt_a = f"""Your opponent (a JavaScript advocate) just responded:

\"\"\"{response_b}\"\"\"

Counter their arguments and reinforce why Python is better."""

        print(f"\n[{label_a}]")
        print("-" * 70)

        result = await client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params={
                    "node_id": "agent-a",
                    "text": prompt_a,
                    "parser": "claude",
                },
            ),
            timeout=300.0,  # 5 minutes for long responses / compaction
        )

        if not result.success:
            print(f"Error: {result.error}")
            break

        response_a = extract_text_response(result.data.get("response", {}))
        print(response_a)

    print("\n" + "=" * 70)
    print("DEBATE CONCLUDED")
    print("=" * 70)

    # Cleanup
    await client.disconnect()

    print("\nStopping server...")
    stop_proc = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "nerve",
        "server",
        "stop",
        server_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await stop_proc.communicate()
    print("Done!")


if __name__ == "__main__":
    server = sys.argv[1] if len(sys.argv) > 1 else "debate-test"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    transport = sys.argv[3] if len(sys.argv) > 3 else "unix"
    topic = sys.argv[4] if len(sys.argv) > 4 else "python-vs-javascript"
    asyncio.run(run_debate(server, rounds, transport, topic))
