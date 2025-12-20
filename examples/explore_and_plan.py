#!/usr/bin/env python3
"""Multi-agent exploration DAG - Senior Dev + Coach collaborate on a plan.

Two agents explore a codebase and build a plan together:
- Senior Developer: Technical deep-dive, architecture analysis
- Coach: Strategic guidance, asks clarifying questions, ensures completeness

Output: A markdown file with the exploration findings and implementation plan.

Usage:
    python examples/explore_and_plan.py [server_name] [target_repo] [output_file]
    python examples/explore_and_plan.py explore-plan /path/to/repo /tmp/plan.md
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from nerve.server.protocols import Command, CommandType


def extract_text_response(response_data: dict) -> str:
    """Extract text content from response."""
    sections = response_data.get("sections", [])
    text_parts = []
    for section in sections:
        if section.get("type") == "text":
            content = section.get("content", "").strip()
            if content:
                text_parts.append(content)
    return "\n".join(text_parts) if text_parts else response_data.get("raw", "")[:500]


def log_to_file(log_file: str, label: str, content: str) -> None:
    """Append content to log file."""
    with open(log_file, "a") as f:
        f.write(f"\n{'=' * 60}\n")
        f.write(f"[{datetime.now().isoformat()}] {label}\n")
        f.write(f"{'=' * 60}\n")
        f.write(content)
        f.write("\n")


async def run_explore_and_plan(
    server_name: str = "explore-plan",
    target_repo: str = "/Users/pb/projects/claude-code-reverse",
    output_file: str = "/tmp/nerve-proxy-plan.md",
    transport: str = "unix",
    cwd: str = "/Users/pb/agentic-curve/projects/nerve",
):
    """Run the exploration and planning DAG."""

    # Configure transport
    if transport == "tcp":
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
    proc = await asyncio.create_subprocess_exec(
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

    # Create two Claude channels
    print("\n" + "=" * 70)
    print("CREATING AGENTS")
    print("=" * 70)

    print("\nCreating Senior Developer agent...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_CHANNEL,
            params={
                "channel_id": "senior-dev",
                "command": "claude",
                "cwd": target_repo,  # Dev works in target repo
                "backend": "claude-wezterm",
            },
        )
    )
    if not result.success:
        print(f"Failed to create senior-dev: {result.error}")
        return
    print("  Created: senior-dev (working in target repo)")

    print("Creating Coach agent...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_CHANNEL,
            params={
                "channel_id": "coach",
                "command": "claude",
                "cwd": cwd,  # Coach works in nerve repo
                "backend": "claude-wezterm",
            },
        )
    )
    if not result.success:
        print(f"Failed to create coach: {result.error}")
        return
    print("  Created: coach (working in nerve repo)")

    # Wait for Claude instances to initialize
    print("\nWaiting for agents to initialize...")
    await asyncio.sleep(5)

    # Initialize output file
    with open(output_file, "w") as f:
        f.write(f"# Exploration Plan: API Proxy for Nerve\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Target Repository: `{target_repo}`\n")
        f.write(f"Output Repository: `{cwd}`\n\n")
        f.write("---\n\n")

    log_file = f"/tmp/nerve-{server_name}-conversation.log"
    Path(log_file).unlink(missing_ok=True)
    print(f"Conversation log: {log_file}")
    print(f"Output plan: {output_file}")

    print("\n" + "=" * 70)
    print("PHASE 1: INITIAL EXPLORATION")
    print("=" * 70)

    # Task 1: Senior Dev explores the codebase
    dev_prompt_1 = """You are a Senior Software Developer. Your task is to explore this codebase thoroughly.

This is an API proxy project that intercepts Claude Code requests. I need you to:

1. Read the README.md to understand the project purpose
2. Examine the main entry point (index.mjs)
3. Look at the router implementation (router.mjs)
4. Understand the configuration and environment variables

After exploring, provide a TECHNICAL SUMMARY with:
- Architecture overview
- Key components and their responsibilities
- Data flow (how requests are intercepted and processed)
- Configuration options

Be concise but thorough. Focus on implementation details that would help us build something similar."""

    print("\n[SENIOR DEV: Exploring codebase...]")
    print("-" * 70)

    result = await client.send_command(
        Command(
            type=CommandType.SEND_INPUT,
            params={
                "channel_id": "senior-dev",
                "text": dev_prompt_1,
                "parser": "claude",
            },
        ),
        timeout=300.0,
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    dev_response_1 = extract_text_response(result.data.get("response", {}))
    print(dev_response_1[:1000] + "..." if len(dev_response_1) > 1000 else dev_response_1)
    log_to_file(log_file, "Senior Dev - Initial Exploration", dev_response_1)

    # Append to plan
    with open(output_file, "a") as f:
        f.write("## Phase 1: Technical Analysis\n\n")
        f.write("### Senior Developer's Exploration\n\n")
        f.write(dev_response_1)
        f.write("\n\n---\n\n")

    print("\n" + "=" * 70)
    print("PHASE 2: COACH REVIEW & QUESTIONS")
    print("=" * 70)

    # Task 2: Coach reviews and asks clarifying questions
    coach_prompt_1 = f"""You are a Technical Coach helping to plan a new feature for the Nerve project.

A Senior Developer just explored an API proxy codebase and provided this summary:

\"\"\"
{dev_response_1}
\"\"\"

Your role is to:
1. Identify any gaps in the analysis
2. Ask 3-5 clarifying questions that would help us implement something similar in Nerve
3. Suggest what additional details we need

Focus on:
- How could we adapt this for Nerve's architecture?
- What logging/monitoring capabilities should we add?
- How should we handle the message format transformations?

Be strategic and think about the implementation roadmap."""

    print("\n[COACH: Reviewing and asking questions...]")
    print("-" * 70)

    result = await client.send_command(
        Command(
            type=CommandType.SEND_INPUT,
            params={
                "channel_id": "coach",
                "text": coach_prompt_1,
                "parser": "claude",
            },
        ),
        timeout=300.0,
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    coach_response_1 = extract_text_response(result.data.get("response", {}))
    print(coach_response_1[:1000] + "..." if len(coach_response_1) > 1000 else coach_response_1)
    log_to_file(log_file, "Coach - Review & Questions", coach_response_1)

    # Append to plan
    with open(output_file, "a") as f:
        f.write("## Phase 2: Coach Review\n\n")
        f.write("### Questions and Gaps Identified\n\n")
        f.write(coach_response_1)
        f.write("\n\n---\n\n")

    print("\n" + "=" * 70)
    print("PHASE 3: DEEP DIVE ON SPECIFICS")
    print("=" * 70)

    # Task 3: Senior Dev addresses coach's questions
    dev_prompt_2 = f"""The Coach reviewed your analysis and has these questions/concerns:

\"\"\"
{coach_response_1}
\"\"\"

Please address these points by:
1. Diving deeper into the specific areas mentioned
2. Looking at relevant code sections
3. Providing concrete implementation details

Focus on answering the coach's questions with specific code references and technical details."""

    print("\n[SENIOR DEV: Addressing questions...]")
    print("-" * 70)

    result = await client.send_command(
        Command(
            type=CommandType.SEND_INPUT,
            params={
                "channel_id": "senior-dev",
                "text": dev_prompt_2,
                "parser": "claude",
            },
        ),
        timeout=300.0,
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    dev_response_2 = extract_text_response(result.data.get("response", {}))
    print(dev_response_2[:1000] + "..." if len(dev_response_2) > 1000 else dev_response_2)
    log_to_file(log_file, "Senior Dev - Deep Dive", dev_response_2)

    # Append to plan
    with open(output_file, "a") as f:
        f.write("## Phase 3: Deep Dive\n\n")
        f.write("### Technical Details and Code References\n\n")
        f.write(dev_response_2)
        f.write("\n\n---\n\n")

    print("\n" + "=" * 70)
    print("PHASE 4: IMPLEMENTATION PLAN")
    print("=" * 70)

    # Task 4: Coach synthesizes into implementation plan
    coach_prompt_2 = f"""Based on the Senior Developer's deep dive:

\"\"\"
{dev_response_2}
\"\"\"

Now synthesize everything into a concrete IMPLEMENTATION PLAN for Nerve.

Create a structured plan with:

## Implementation Plan

### 1. Overview
(What we're building and why)

### 2. Architecture
(How it fits into Nerve's existing structure)

### 3. Components to Build
(List each module/file with its responsibility)

### 4. Implementation Steps
(Ordered steps with dependencies)

### 5. Configuration
(Environment variables, settings)

### 6. Testing Strategy
(How to verify it works)

### 7. Future Enhancements
(Nice-to-haves for later)

Be specific and actionable. This plan should be something a developer can pick up and start implementing."""

    print("\n[COACH: Building implementation plan...]")
    print("-" * 70)

    result = await client.send_command(
        Command(
            type=CommandType.SEND_INPUT,
            params={
                "channel_id": "coach",
                "text": coach_prompt_2,
                "parser": "claude",
            },
        ),
        timeout=300.0,
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    coach_response_2 = extract_text_response(result.data.get("response", {}))
    print(coach_response_2[:1000] + "..." if len(coach_response_2) > 1000 else coach_response_2)
    log_to_file(log_file, "Coach - Implementation Plan", coach_response_2)

    # Append to plan
    with open(output_file, "a") as f:
        f.write("## Phase 4: Implementation Plan\n\n")
        f.write(coach_response_2)
        f.write("\n\n---\n\n")

    print("\n" + "=" * 70)
    print("PHASE 5: SENIOR DEV VALIDATION")
    print("=" * 70)

    # Task 5: Senior Dev validates and adds technical notes
    dev_prompt_3 = f"""The Coach has created this implementation plan:

\"\"\"
{coach_response_2}
\"\"\"

As the Senior Developer, please:
1. Validate the technical feasibility
2. Add any missing technical considerations
3. Identify potential challenges or risks
4. Suggest specific libraries or tools to use

Provide your TECHNICAL VALIDATION with concrete recommendations."""

    print("\n[SENIOR DEV: Validating plan...]")
    print("-" * 70)

    result = await client.send_command(
        Command(
            type=CommandType.SEND_INPUT,
            params={
                "channel_id": "senior-dev",
                "text": dev_prompt_3,
                "parser": "claude",
            },
        ),
        timeout=300.0,
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    dev_response_3 = extract_text_response(result.data.get("response", {}))
    print(dev_response_3[:1000] + "..." if len(dev_response_3) > 1000 else dev_response_3)
    log_to_file(log_file, "Senior Dev - Technical Validation", dev_response_3)

    # Append to plan
    with open(output_file, "a") as f:
        f.write("## Phase 5: Technical Validation\n\n")
        f.write("### Senior Developer's Review\n\n")
        f.write(dev_response_3)
        f.write("\n\n---\n\n")
        f.write(f"*Plan generated by multi-agent DAG on {datetime.now().isoformat()}*\n")

    print("\n" + "=" * 70)
    print("DAG COMPLETED")
    print("=" * 70)
    print(f"\nOutput files:")
    print(f"  Plan: {output_file}")
    print(f"  Conversation log: {log_file}")

    # Cleanup
    await client.disconnect()

    print("\nStopping server...")
    stop_proc = await asyncio.create_subprocess_exec(
        "uv", "run", "nerve", "server", "stop", server_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await stop_proc.communicate()
    print("Done!")


if __name__ == "__main__":
    server = sys.argv[1] if len(sys.argv) > 1 else "explore-plan"
    target_repo = sys.argv[2] if len(sys.argv) > 2 else "/Users/pb/projects/claude-code-reverse"
    output_file = sys.argv[3] if len(sys.argv) > 3 else "/tmp/nerve-proxy-plan.md"
    asyncio.run(run_explore_and_plan(server, target_repo, output_file))
