#!/usr/bin/env python3
"""Dev + Coach collaboration DAG template.

Two Claude agents collaborate on a task:
- Developer: Does the technical work, explores code, proposes solutions
- Coach: Reviews, critiques, guides, and accepts when satisfied

The loop continues until the coach accepts or MAX_ROUNDS is reached.

Usage:
    python examples/dev_coach_architecture.py [server_name] [transport] [context_file]
    python examples/dev_coach_architecture.py my-task unix
    python examples/dev_coach_architecture.py my-task unix /path/to/context.md
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from nerve.server.protocols import Command, CommandType

# =============================================================================
# CONFIGURATION - Edit these to customize the collaboration
# =============================================================================

# Termination
ACCEPTANCE_PHRASE = "I ACCEPT AND I HAVE NO MORE CHANGES TO SUGGEST."
MAX_ROUNDS = 50

# Paths
DEV_CWD = "/Users/pb/agentic-curve/projects/nerve"  # Developer's working directory
COACH_CWD = "/Users/pb/agentic-curve/projects/nerve"  # Coach's working directory
OUTPUT_FILE = "/tmp/architecture-review/dev-coach-output.md"
LOG_FILE = "/tmp/architecture-review/dev-coach-conversation.log"

# =============================================================================
# ADDITIONAL CONTEXT - Loaded from file at runtime (use {additional_context} in prompts)
# =============================================================================

ADDITIONAL_CONTEXT = ""  # Populated from CLI argument if provided

# =============================================================================
# WARMUP - Optional system-like instructions sent once before task begins
# =============================================================================

DEV_WARMUP = ""  # Leave empty to skip warmup
# Example:
# DEV_WARMUP = """You are an expert Python developer. You write clean, tested code.
# Always run tests before claiming something works."""

COACH_WARMUP = ""  # Leave empty to skip warmup
# Example:
# COACH_WARMUP = """You are a strict but fair technical coach. You don't accept
# work without tests. You make decisions quickly when the developer is stuck."""

# =============================================================================
# TASK - Define what the agents are working on
# =============================================================================

INITIAL_TASK = """
Check and discuss if our PRD is ready for implementation. DONT implement anything yet.

The PRD is named: NODE_REFACTORING.md and AGENT_CAPABILITIES.md within docs/
"""

TASK_REFRESHER = """
Check and discuss if our PRD is ready for implementation. DONT implement anything yet.

The PRD is named: NODE_REFACTORING.md and AGENT_CAPABILITIES.md within docs/
"""

# =============================================================================
# PROMPTS - Edit these to customize agent behavior
# =============================================================================

# --- Initial prompts (priming) ---

DEV_INITIAL_PROMPT = """You are a Senior Software Developer.

{initial_task}

You are working with a Coach who will review your work and guide you toward a complete solution.

You are the ONLY one who can write and make changes to the PRD.
You can ask coach for decisions if you're stuck.
"""

COACH_INITIAL_PROMPT_TEMPLATE = """You are a Technical Coach. A Developer is working on a task:

{initial_task}

The Developer just provided their initial analysis:

\"\"\"
{dev_response}
\"\"\"

Your role:
1. Critically evaluate the work
2. Identify gaps, risks, or issues
3. Ask probing questions or suggest improvements
4. Guide toward a complete, high-quality solution
5. You cannot make any changes.
6. You need to make design decisions that developer is stuck with.
7. You are the final authority.
8. You can read and review any file but you cannot make changes to any file.
9. Ensure developer doesn't add anything irrelevant to the PRD.
10. ENSURE THE DEVELOPER DOES NOT SUGGEST ANYTHING WITHIN THE PRD THAT WILL BREAK ANY EXISTING FUNCTIONALITY.
11. Make sure the developer doesn't start coding or implementing anything yet.

If you are FULLY SATISFIED and the work is complete, respond with EXACTLY:
"{acceptance_phrase}".

Note, use that phrase ONLY when you've NO MORE FEEDBACK at all.

Otherwise, provide your feedback for the next iteration. Catch bugs and feature regressions."""

# --- Loop prompts (iterations) ---

DEV_LOOP_PROMPT_TEMPLATE = """The Coach reviewed your work and provided feedback:

\"\"\"
{coach_response}
\"\"\"

{task_refresher}

Please:
1. Address each point the coach raised
2. Explore further if needed
3. Provide an updated, complete response
4. Update the document (if needed) REFACTORED_DIR_ARCHITECTURE.md

The coach will accept when satisfied."""

COACH_LOOP_PROMPT_TEMPLATE = """The Developer addressed your feedback:

\"\"\"
{dev_response}
\"\"\"

{task_refresher}

Dev has this bad habit of jumping ahead and writing unwanted things in PRD.
Make sure the developer doesn't start coding or implementing anything yet.

Give grades to dev on their work an clearly tell them what's missing.

Review their updated work. If you are FULLY SATISFIED, respond with EXACTLY:
"{acceptance_phrase}"

If it is your first review then most likely reject it and give feedback. Because no one gets it right the first time.

Otherwise, provide your next round of feedback."""

# =============================================================================
# SCRIPT - Usually no need to edit below this line
# =============================================================================


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
    """Check if coach accepted."""
    return ACCEPTANCE_PHRASE in response


async def run_dev_coach(
    server_name: str = "dev-coach",
    transport: str = "unix",
    context_file: str | None = None,
):
    """Run the dev + coach collaboration DAG."""
    global ADDITIONAL_CONTEXT

    # Load additional context from file if provided
    if context_file:
        try:
            with open(context_file) as f:
                ADDITIONAL_CONTEXT = f.read()
            print(f"Loaded context from: {context_file}")
        except Exception as e:
            print(f"Warning: Could not load context file: {e}")
            ADDITIONAL_CONTEXT = ""

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

    # Create agents
    print("\n" + "=" * 80)
    print("CREATING AGENTS")
    print("=" * 80)

    print("\nCreating Developer agent...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_NODE,
            params={
                "node_id": "developer",
                "command": "claude --dangerously-skip-permissions",
                "cwd": DEV_CWD,
                "backend": "claude-wezterm",
                "response_timeout": 2400.0,  # 40 minutes for long operations
            },
        )
    )
    if not result.success:
        print(f"Failed to create developer: {result.error}")
        return
    print(f"  Created: developer (cwd: {DEV_CWD})")

    print("Creating Coach agent...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_NODE,
            params={
                "node_id": "coach",
                "command": "claude --dangerously-skip-permissions",
                "cwd": COACH_CWD,
                "backend": "claude-wezterm",
                "response_timeout": 2400.0,  # 40 minutes for long operations
            },
        )
    )
    if not result.success:
        print(f"Failed to create coach: {result.error}")
        return
    print(f"  Created: coach (cwd: {COACH_CWD})")

    # Wait for initialization
    print("\nWaiting for agents to initialize...")
    await asyncio.sleep(5)

    # Setup files (create directories if needed)
    Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(LOG_FILE).unlink(missing_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        f.write("# Dev + Coach Collaboration\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        f.write("---\n\n")

    print(f"Output: {OUTPUT_FILE}")
    print(f"Log: {LOG_FILE}")

    # Warmup prompts (optional)
    if DEV_WARMUP.strip():
        print("\n[DEVELOPER: Warmup...]")
        result = await client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params={
                    "node_id": "developer",
                    "text": DEV_WARMUP,
                    "parser": "claude",
                },
            ),
            timeout=120.0,
        )
        if result.success:
            log_to_file(
                LOG_FILE,
                "Developer - Warmup",
                extract_text_response(result.data.get("response", {})),
            )
            print("  Developer warmed up")

    if COACH_WARMUP.strip():
        print("[COACH: Warmup...]")
        result = await client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params={
                    "node_id": "coach",
                    "text": COACH_WARMUP,
                    "parser": "claude",
                },
            ),
            timeout=120.0,
        )
        if result.success:
            log_to_file(
                LOG_FILE,
                "Coach - Warmup",
                extract_text_response(result.data.get("response", {})),
            )
            print("  Coach warmed up")

    # Phase 1: Developer initial work
    print("\n" + "=" * 80)
    print("INITIAL PHASE")
    print("=" * 80)

    print("\n[DEVELOPER: Starting work...]")
    print("-" * 80)

    dev_initial = DEV_INITIAL_PROMPT.format(
        initial_task=INITIAL_TASK,
        additional_context=ADDITIONAL_CONTEXT,
    )

    result = await client.send_command(
        Command(
            type=CommandType.EXECUTE_INPUT,
            params={
                "node_id": "developer",
                "text": dev_initial,
                "parser": "claude",
            },
        ),
        timeout=1800.0,
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    dev_response = extract_text_response(result.data.get("response", {}))
    print(dev_response[:2000] + "..." if len(dev_response) > 2000 else dev_response)
    log_to_file(LOG_FILE, "Developer - Initial", dev_response)

    with open(OUTPUT_FILE, "a") as f:
        f.write("## Initial Work\n\n")
        f.write(dev_response)
        f.write("\n\n---\n\n")

    # Coach initial review
    print("\n" + "=" * 80)
    print("COACH INITIAL REVIEW")
    print("=" * 80)

    coach_prompt = COACH_INITIAL_PROMPT_TEMPLATE.format(
        initial_task=INITIAL_TASK,
        dev_response=dev_response,
        acceptance_phrase=ACCEPTANCE_PHRASE,
        additional_context=ADDITIONAL_CONTEXT,
    )

    print("\n[COACH: Initial review...]")
    print("-" * 80)

    result = await client.send_command(
        Command(
            type=CommandType.EXECUTE_INPUT,
            params={
                "node_id": "coach",
                "text": coach_prompt,
                "parser": "claude",
            },
        ),
        timeout=1800.0,
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    coach_response = extract_text_response(result.data.get("response", {}))
    print(coach_response[:2000] + "..." if len(coach_response) > 2000 else coach_response)
    log_to_file(LOG_FILE, "Coach - Initial", coach_response)

    # Check acceptance after initial review
    accepted = check_acceptance(coach_response)
    round_num = 0

    if accepted:
        print("\n" + "=" * 80)
        print("ACCEPTED!")
        print("=" * 80)

        with open(OUTPUT_FILE, "a") as f:
            f.write("## Accepted (Initial Review)\n\n")
            f.write("### Coach's Review\n\n")
            f.write(coach_response)
            f.write("\n\n---\n\n")
            f.write("## Final Output\n\n")
            f.write(dev_response)
            f.write("\n\n---\n\n")
            f.write(f"*Completed on initial review at {datetime.now().isoformat()}*\n")
    else:
        with open(OUTPUT_FILE, "a") as f:
            f.write("## Initial Coach Review\n\n")
            f.write(coach_response)
            f.write("\n\n---\n\n")

    # Collaboration loop
    while round_num < MAX_ROUNDS and not accepted:
        round_num += 1
        print(f"\n{'=' * 80}")
        print(f"ROUND {round_num}/{MAX_ROUNDS}")
        print("=" * 80)

        # Developer responds to feedback
        dev_prompt = DEV_LOOP_PROMPT_TEMPLATE.format(
            coach_response=coach_response,
            task_refresher=TASK_REFRESHER,
            additional_context=ADDITIONAL_CONTEXT,
        )

        print("\n[DEVELOPER: Addressing feedback...]")
        print("-" * 80)

        result = await client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params={
                    "node_id": "developer",
                    "text": dev_prompt,
                    "parser": "claude",
                },
            ),
            timeout=1800.0,
        )

        if not result.success:
            print(f"Error: {result.error}")
            break

        dev_response = extract_text_response(result.data.get("response", {}))
        print(dev_response[:2000] + "..." if len(dev_response) > 2000 else dev_response)
        log_to_file(LOG_FILE, f"Developer - Round {round_num}", dev_response)

        with open(OUTPUT_FILE, "a") as f:
            f.write(f"## Round {round_num}\n\n")
            f.write("### Developer Response\n\n")
            f.write(dev_response)
            f.write("\n\n")

        # Coach reviews
        coach_prompt = COACH_LOOP_PROMPT_TEMPLATE.format(
            dev_response=dev_response,
            task_refresher=TASK_REFRESHER,
            acceptance_phrase=ACCEPTANCE_PHRASE,
            additional_context=ADDITIONAL_CONTEXT,
        )

        print("\n[COACH: Reviewing...]")
        print("-" * 80)

        result = await client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params={
                    "node_id": "coach",
                    "text": coach_prompt,
                    "parser": "claude",
                },
            ),
            timeout=1800.0,
        )

        if not result.success:
            print(f"Error: {result.error}")
            break

        coach_response = extract_text_response(result.data.get("response", {}))
        print(coach_response[:2000] + "..." if len(coach_response) > 2000 else coach_response)
        log_to_file(LOG_FILE, f"Coach - Round {round_num}", coach_response)

        # Check acceptance
        if check_acceptance(coach_response):
            print("\n" + "=" * 80)
            print("ACCEPTED!")
            print("=" * 80)
            accepted = True

            with open(OUTPUT_FILE, "a") as f:
                f.write("### Coach Feedback\n\n")
                f.write(coach_response)
                f.write("\n\n---\n\n")
                f.write("## Final Output\n\n")
                f.write(dev_response)
                f.write("\n\n---\n\n")
                f.write(f"*Completed after {round_num} rounds on {datetime.now().isoformat()}*\n")
            break

        with open(OUTPUT_FILE, "a") as f:
            f.write("### Coach Feedback\n\n")
            f.write(coach_response)
            f.write("\n\n---\n\n")

    # Termination
    if not accepted:
        print("\n" + "=" * 80)
        print(f"MAX ROUNDS ({MAX_ROUNDS}) REACHED")
        print("=" * 80)

        with open(OUTPUT_FILE, "a") as f:
            f.write("\n## Terminated\n\n")
            f.write(f"Reached maximum rounds ({MAX_ROUNDS}) without acceptance.\n\n")
            f.write(f"*Terminated on {datetime.now().isoformat()}*\n")

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)
    print(f"\nRounds: {round_num}")
    print(f"Accepted: {accepted}")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Log: {LOG_FILE}")

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
    server = sys.argv[1] if len(sys.argv) > 1 else "dev-coach"
    transport = sys.argv[2] if len(sys.argv) > 2 else "unix"
    context_file = sys.argv[3] if len(sys.argv) > 3 else None
    asyncio.run(run_dev_coach(server, transport, context_file))
