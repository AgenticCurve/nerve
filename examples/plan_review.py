#!/usr/bin/env python3
"""Plan Review DAG - Two agents collaborate to refine an integration plan.

Two agents review and refine the nerve-proxy-plan.md:
- Senior Developer: Proposes refinements based on actual codebase
- Coach: Critiques and guides, accepts when satisfied

Termination conditions:
1. Coach says exactly: "I ACCEPT YOUR PLAN AND DONT NEED ANY MORE IMPROVEMENTS."
2. Hard stop after 50 rounds

Usage:
    python examples/plan_review.py [server_name] [transport]
    python examples/plan_review.py plan-review unix
    python examples/plan_review.py plan-review tcp
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from nerve.server.protocols import Command, CommandType

# Termination phrase - must be exact match
ACCEPTANCE_PHRASE = "I ACCEPT YOUR PLAN AND DONT NEED ANY MORE IMPROVEMENTS."
MAX_ROUNDS = 50


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
        f.write(f"\n{'=' * 80}\n")
        f.write(f"[{datetime.now().isoformat()}] {label}\n")
        f.write(f"{'=' * 80}\n")
        f.write(content)
        f.write("\n")


def check_acceptance(response: str) -> bool:
    """Check if coach accepted the plan."""
    return ACCEPTANCE_PHRASE in response


async def run_plan_review(
    server_name: str = "plan-review",
    transport: str = "unix",
    input_plan: str = "/tmp/nerve-proxy-plan.md",
    output_plan: str = "/tmp/nerve-proxy-plan-v2.md",
    cwd: str = "/Users/pb/agentic-curve/projects/nerve",
):
    """Run the plan review DAG."""

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

    # Create two Claude channels - both in nerve codebase
    print("\n" + "=" * 80)
    print("CREATING AGENTS")
    print("=" * 80)

    print("\nCreating Senior Developer agent...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_CHANNEL,
            params={
                "channel_id": "senior-dev",
                "command": "claude",
                "cwd": cwd,
                "backend": "claude-wezterm",
            },
        )
    )
    if not result.success:
        print(f"Failed to create senior-dev: {result.error}")
        return
    print("  Created: senior-dev (working in nerve codebase)")

    print("Creating Coach agent...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_CHANNEL,
            params={
                "channel_id": "coach",
                "command": "claude",
                "cwd": cwd,
                "backend": "claude-wezterm",
            },
        )
    )
    if not result.success:
        print(f"Failed to create coach: {result.error}")
        return
    print("  Created: coach (working in nerve codebase)")

    # Wait for Claude instances to initialize
    print("\nWaiting for agents to initialize...")
    await asyncio.sleep(5)

    # Setup logging
    log_file = f"/tmp/nerve-{server_name}-conversation.log"
    Path(log_file).unlink(missing_ok=True)
    print(f"Conversation log: {log_file}")
    print(f"Input plan: {input_plan}")
    print(f"Output plan: {output_plan}")

    # Initialize output file
    with open(output_plan, "w") as f:
        f.write(f"# Nerve Proxy Integration Plan v2\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Based on: `{input_plan}`\n")
        f.write(f"Target Codebase: `{cwd}`\n\n")
        f.write("---\n\n")

    print("\n" + "=" * 80)
    print("PHASE 1: INITIAL REVIEW")
    print("=" * 80)

    # Task 1: Senior Dev reads existing plan and codebase, proposes initial refinements
    dev_initial_prompt = f"""You are a Senior Software Developer working on the Nerve project.

Your task is to review an existing implementation plan and adapt it for the actual Nerve codebase.

IMPORTANT FILES TO READ:
1. First, read the existing plan: {input_plan}
2. Then explore the Nerve codebase to understand:
   - Current project structure
   - Existing patterns (channels, transports, protocols)
   - How new code should integrate

DO NOT WRITE ANY CODE. Your job is to:
1. Understand the existing plan's proposals
2. Identify what needs to change for Nerve's actual architecture
3. Propose a REALISTIC integration plan

After your analysis, provide:
1. Key differences between the plan and actual Nerve architecture
2. What can be reused vs what needs to change
3. A prioritized list of integration tasks

Be specific and reference actual files in the codebase. You are discussing this
plan with a senior Coach who will help you solve any queries and make any
confusing decisions. You can ask him for feedback."""

    print("\n[SENIOR DEV: Reading plan and exploring codebase...]")
    print("-" * 80)

    result = await client.send_command(
        Command(
            type=CommandType.SEND_INPUT,
            params={
                "channel_id": "senior-dev",
                "text": dev_initial_prompt,
                "parser": "claude",
            },
        ),
        timeout=300.0,
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    dev_response = extract_text_response(result.data.get("response", {}))
    print(dev_response[:2000] + "..." if len(dev_response) > 2000 else dev_response)
    log_to_file(log_file, "Senior Dev - Initial Review", dev_response)

    # Append to output plan
    with open(output_plan, "a") as f:
        f.write("## Initial Analysis\n\n")
        f.write("### Senior Developer's Review\n\n")
        f.write(dev_response)
        f.write("\n\n---\n\n")

    print("\n" + "=" * 80)
    print("PHASE 2: COLLABORATIVE REFINEMENT")
    print("=" * 80)

    # Main collaboration loop
    round_num = 0
    accepted = False

    while round_num < MAX_ROUNDS and not accepted:
        round_num += 1
        print(f"\n{'=' * 80}")
        print(f"ROUND {round_num}/{MAX_ROUNDS}")
        print("=" * 80)

        # Coach reviews and critiques
        coach_prompt = f"""You are a Technical Coach reviewing a plan for integrating an API proxy into the Nerve project.

The Senior Developer just provided this analysis:

\"\"\"
{dev_response}
\"\"\"

Your role is to:
1. Critically evaluate the proposed approach
2. Identify gaps, risks, or unrealistic assumptions
3. Ask probing questions or suggest improvements
4. Guide toward a practical, implementable plan
5. Make decisions that Senior Dev is afraid to take or avoid taking

IMPORTANT: You have access to the same codebase. Feel free to read files to verify claims.

Reference the original plan at {input_plan} if needed.

If you are FULLY SATISFIED with the plan and believe it is:
- Realistic and implementable
- Well-integrated with Nerve's architecture
- Properly prioritized
- Ready for implementation

Then respond with EXACTLY this phrase (copy it exactly):
"{ACCEPTANCE_PHRASE}"

Please use the acceptance phrase verbatum to be accepted.
Otherwise, provide your critique and suggestions for the next iteration."""

        print(f"\n[COACH: Reviewing round {round_num}...]")
        print("-" * 80)

        result = await client.send_command(
            Command(
                type=CommandType.SEND_INPUT,
                params={
                    "channel_id": "coach",
                    "text": coach_prompt,
                    "parser": "claude",
                },
            ),
            timeout=300.0,
        )

        if not result.success:
            print(f"Error: {result.error}")
            break

        coach_response = extract_text_response(result.data.get("response", {}))
        print(coach_response[:2000] + "..." if len(coach_response) > 2000 else coach_response)
        log_to_file(log_file, f"Coach - Round {round_num}", coach_response)

        # Check for acceptance
        if check_acceptance(coach_response):
            print("\n" + "=" * 80)
            print("🎉 PLAN ACCEPTED BY COACH!")
            print("=" * 80)
            accepted = True

            # Append final acceptance to plan
            with open(output_plan, "a") as f:
                f.write(f"## Final Acceptance (Round {round_num})\n\n")
                f.write("### Coach's Final Review\n\n")
                f.write(coach_response)
                f.write("\n\n---\n\n")
                f.write("## Final Plan\n\n")
                f.write(dev_response)
                f.write("\n\n---\n\n")
                f.write(f"*Plan accepted after {round_num} rounds on {datetime.now().isoformat()}*\n")

            break

        # Append round to output plan
        with open(output_plan, "a") as f:
            f.write(f"## Round {round_num}\n\n")
            f.write("### Coach's Feedback\n\n")
            f.write(coach_response)
            f.write("\n\n")

        # Senior Dev responds to critique
        dev_prompt = f"""The Coach reviewed your plan and provided this feedback:

\"\"\"
{coach_response}
\"\"\"

Please:
1. Address each point the coach raised
2. Explore the codebase further if needed to verify your proposals
3. Refine your plan based on the feedback
4. Provide an UPDATED, COMPLETE integration plan

Remember: NO CODING. Focus on making the plan realistic and actionable.

Be thorough but concise. The coach will accept when satisfied."""

        print(f"\n[SENIOR DEV: Addressing feedback round {round_num}...]")
        print("-" * 80)

        result = await client.send_command(
            Command(
                type=CommandType.SEND_INPUT,
                params={
                    "channel_id": "senior-dev",
                    "text": dev_prompt,
                    "parser": "claude",
                },
            ),
            timeout=300.0,
        )

        if not result.success:
            print(f"Error: {result.error}")
            break

        dev_response = extract_text_response(result.data.get("response", {}))
        print(dev_response[:2000] + "..." if len(dev_response) > 2000 else dev_response)
        log_to_file(log_file, f"Senior Dev - Round {round_num}", dev_response)

        # Append to output plan
        with open(output_plan, "a") as f:
            f.write("### Developer's Refined Plan\n\n")
            f.write(dev_response)
            f.write("\n\n---\n\n")

    # Termination
    if not accepted:
        print("\n" + "=" * 80)
        print(f"⚠️  MAX ROUNDS ({MAX_ROUNDS}) REACHED - STOPPING")
        print("=" * 80)

        with open(output_plan, "a") as f:
            f.write(f"\n## Terminated\n\n")
            f.write(f"Reached maximum rounds ({MAX_ROUNDS}) without coach acceptance.\n")
            f.write(f"Last developer proposal is above.\n\n")
            f.write(f"*Terminated on {datetime.now().isoformat()}*\n")

    print("\n" + "=" * 80)
    print("DAG COMPLETED")
    print("=" * 80)
    print(f"\nResults:")
    print(f"  Rounds completed: {round_num}")
    print(f"  Accepted: {accepted}")
    print(f"  Output plan: {output_plan}")
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
    server = sys.argv[1] if len(sys.argv) > 1 else "plan-review"
    transport = sys.argv[2] if len(sys.argv) > 2 else "unix"
    asyncio.run(run_plan_review(server, transport))
