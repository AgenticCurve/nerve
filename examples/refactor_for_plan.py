#!/usr/bin/env python3
"""Refactoring DAG - Prepare codebase for plan implementation.

Three agents collaborate to refactor the codebase:
- Senior Developer: Proposes and implements refactoring changes
- Coach: Reviews changes, ensures no feature degradation
- Reviewer: Final validation using git diff

CRITICAL: Refactoring only - NO feature changes, NO new functionality.

Termination conditions:
1. Coach says exactly: "I ACCEPT YOUR REFACTORING AND DONT NEED ANY MORE CHANGES."
2. Hard stop after 50 rounds

After Dev/Coach loop completes, Reviewer validates all changes.

Usage:
    python examples/refactor_for_plan.py [server_name] [transport]
    python examples/refactor_for_plan.py refactor-prep unix
    python examples/refactor_for_plan.py refactor-prep tcp
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from nerve.server.protocols import Command, CommandType

# Termination phrase - must be exact match
ACCEPTANCE_PHRASE = "I ACCEPT YOUR REFACTORING AND DONT NEED ANY MORE CHANGES."
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
    """Check if coach accepted the refactoring."""
    return ACCEPTANCE_PHRASE in response


async def run_refactoring(
    server_name: str = "refactor-prep",
    transport: str = "unix",
    input_plan: str = "/tmp/nerve-proxy-plan-v2.md",
    feedback_file: str = "REFACTORING_FEEDBACK.md",
    cwd: str = "/Users/pb/agentic-curve/projects/nerve",
):
    """Run the refactoring DAG."""

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

    # Full path for feedback file
    feedback_path = Path(cwd) / feedback_file

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

    # Create three Claude channels
    print("\n" + "=" * 80)
    print("CREATING AGENTS")
    print("=" * 80)

    print("\nCreating Senior Developer agent...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_CHANNEL,
            params={
                "channel_id": "senior-dev",
                "command": "claude --dangerously-skip-permissions",
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
                "command": "claude --dangerously-skip-permissions",
                "cwd": cwd,
                "backend": "claude-wezterm",
            },
        )
    )
    if not result.success:
        print(f"Failed to create coach: {result.error}")
        return
    print("  Created: coach (working in nerve codebase)")

    print("Creating Reviewer agent...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_CHANNEL,
            params={
                "channel_id": "reviewer",
                "command": "claude --dangerously-skip-permissions",
                "cwd": cwd,
                "backend": "claude-wezterm",
            },
        )
    )
    if not result.success:
        print(f"Failed to create reviewer: {result.error}")
        return
    print("  Created: reviewer (working in nerve codebase)")

    # Wait for Claude instances to initialize
    print("\nWaiting for agents to initialize...")
    await asyncio.sleep(5)

    # Setup logging
    log_file = f"/tmp/nerve-{server_name}-conversation.log"
    Path(log_file).unlink(missing_ok=True)
    print(f"Conversation log: {log_file}")
    print(f"Input plan: {input_plan}")
    print(f"Feedback file: {feedback_path}")

    print("\n" + "=" * 80)
    print("PHASE 1: INITIAL REFACTORING ANALYSIS")
    print("=" * 80)

    # Task 1: Senior Dev reads plan and identifies refactoring opportunities
    dev_initial_prompt = f"""You are a Senior Software Developer working on the Nerve project.

Your task is to REFACTOR the existing codebase to make it easier to implement an upcoming feature.

IMPORTANT FILES TO READ:
1. First, read the integration plan: {input_plan}
2. Then explore the current Nerve codebase structure

YOUR MISSION - REFACTORING ONLY:
- Identify code that needs restructuring to accommodate the plan
- Propose refactoring changes that will make implementation easier
- YOU MAY WRITE CODE for refactoring purposes

CRITICAL CONSTRAINTS:
⚠️  NO NEW FEATURES - only restructure existing code
⚠️  NO FUNCTIONALITY CHANGES - all existing behavior must be preserved
⚠️  NO BREAKING CHANGES - all existing tests and usage must still work

Good refactoring examples:
- Moving files/modules to better locations
- Extracting base classes or protocols
- Splitting large files into smaller ones
- Adding __init__.py exports for easier imports
- Renaming for consistency
- Adding type hints to existing code

BAD (not allowed):
- Adding new features
- Changing existing behavior
- Adding new dependencies
- Modifying public APIs in breaking ways

After your analysis, provide:
1. List of refactoring tasks needed
2. Priority order (what to do first)
3. Risk assessment for each change

You are working with a Coach who will review your changes and help you make
decisions. You can ask for guidance on anything you're unsure about. The Coach
will make the tough calls when you're uncertain."""

    print("\n[SENIOR DEV: Analyzing refactoring needs...]")
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
        timeout=1800.0,  # 30 minutes
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    dev_response = extract_text_response(result.data.get("response", {}))
    print(dev_response[:2000] + "..." if len(dev_response) > 2000 else dev_response)
    log_to_file(log_file, "Senior Dev - Initial Analysis", dev_response)

    print("\n" + "=" * 80)
    print("PHASE 2: COLLABORATIVE REFACTORING")
    print("=" * 80)

    # Main collaboration loop
    round_num = 0
    accepted = False

    while round_num < MAX_ROUNDS and not accepted:
        round_num += 1
        print(f"\n{'=' * 80}")
        print(f"ROUND {round_num}/{MAX_ROUNDS}")
        print("=" * 80)

        # Coach reviews and guides
        coach_prompt = f"""You are a Technical Coach overseeing a refactoring effort on the Nerve project.

The Senior Developer just provided this analysis/update:

\"\"\"
{dev_response}
\"\"\"

Your role is to:
1. Critically evaluate the proposed refactoring
2. Verify NO functionality is being changed (only structure)
3. Check that changes won't break existing code
4. Make decisions the Senior Dev is hesitant to make
5. Guide them toward safe, incremental refactoring

VALIDATION CHECKLIST:
□ Are these truly refactoring changes (no new features)?
□ Will existing tests still pass?
□ Are the changes reversible if needed?
□ Is the priority order sensible?

You have access to the codebase. Run `git status` and `git diff` to see what
changes have been made. Verify the changes are safe.

Reference the plan at {input_plan} to understand what we're preparing for.

If you are FULLY SATISFIED that:
- All refactoring is complete and safe
- No functionality has been changed
- The codebase is now better prepared for the plan
- No more refactoring is needed

Then respond with EXACTLY this phrase (copy it verbatim):
"{ACCEPTANCE_PHRASE}"

Otherwise, provide your critique, concerns, or next steps for the developer."""

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
            timeout=1800.0,  # 30 minutes
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
            print("🎉 REFACTORING ACCEPTED BY COACH!")
            print("=" * 80)
            accepted = True
            break

        # Senior Dev responds and implements
        dev_prompt = f"""The Coach reviewed your refactoring and provided this feedback:

\"\"\"
{coach_response}
\"\"\"

Please:
1. Address each point the coach raised
2. IMPLEMENT the refactoring changes (you may write code now)
3. Run `git status` to show what you've changed
4. Explain what each change does and why it's safe

REMEMBER:
⚠️  NO NEW FEATURES - only restructure
⚠️  NO FUNCTIONALITY CHANGES - preserve all behavior
⚠️  Run tests if available to verify nothing broke

After making changes, summarize:
1. What files were modified/moved/created
2. Why each change is safe
3. What remains to be done (if anything)

The Coach will accept when all refactoring is complete and verified safe."""

        print(f"\n[SENIOR DEV: Implementing round {round_num}...]")
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
            timeout=1800.0,  # 30 minutes
        )

        if not result.success:
            print(f"Error: {result.error}")
            break

        dev_response = extract_text_response(result.data.get("response", {}))
        print(dev_response[:2000] + "..." if len(dev_response) > 2000 else dev_response)
        log_to_file(log_file, f"Senior Dev - Round {round_num}", dev_response)

    # Handle max rounds
    if not accepted:
        print("\n" + "=" * 80)
        print(f"⚠️  MAX ROUNDS ({MAX_ROUNDS}) REACHED - PROCEEDING TO REVIEW")
        print("=" * 80)

    # =========================================================================
    # PHASE 3: REVIEWER VALIDATION
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 3: FINAL REVIEW")
    print("=" * 80)

    reviewer_prompt = f"""You are a Code Reviewer performing a FINAL VALIDATION of refactoring changes.

ORIGINAL TASK:
The team was asked to refactor the Nerve codebase to prepare for implementing
the plan at {input_plan}. The key constraint was:
- REFACTORING ONLY - no new features, no functionality changes

YOUR JOB:
1. Run `git status` to see all modified files
2. Run `git diff` to see the actual changes (or `git diff <file>` for specific files)
3. For each change, verify:
   - Is this truly refactoring (restructuring, not new behavior)?
   - Does it preserve existing functionality?
   - Is it a safe change?

WRITE YOUR FINDINGS:
After your review, create a file called {feedback_file} with your assessment.

Use this format:
```markdown
# Refactoring Review

## Summary
[Overall assessment: APPROVED / NEEDS_CHANGES / REJECTED]

## Files Reviewed
[List each file and your assessment]

## Concerns
[Any issues found]

## Recommendations
[Suggestions for improvement]

## Verdict
[Final decision with reasoning]
```

Be thorough. Check every change. The integrity of the codebase depends on this review."""

    print("\n[REVIEWER: Validating all changes...]")
    print("-" * 80)

    result = await client.send_command(
        Command(
            type=CommandType.SEND_INPUT,
            params={
                "channel_id": "reviewer",
                "text": reviewer_prompt,
                "parser": "claude",
            },
        ),
        timeout=1800.0,  # 30 minutes
    )

    if not result.success:
        print(f"Error: {result.error}")
    else:
        reviewer_response = extract_text_response(result.data.get("response", {}))
        print(reviewer_response[:2000] + "..." if len(reviewer_response) > 2000 else reviewer_response)
        log_to_file(log_file, "Reviewer - Final Validation", reviewer_response)

    # =========================================================================
    # COMPLETION
    # =========================================================================
    print("\n" + "=" * 80)
    print("DAG COMPLETED")
    print("=" * 80)
    print(f"\nResults:")
    print(f"  Dev/Coach rounds: {round_num}")
    print(f"  Coach accepted: {accepted}")
    print(f"  Feedback file: {feedback_path}")
    print(f"  Conversation log: {log_file}")

    # Check if feedback file was created
    if feedback_path.exists():
        print(f"\n✅ Feedback file created: {feedback_path}")
    else:
        print(f"\n⚠️  Feedback file not found at {feedback_path}")
        print("    The reviewer may not have created it. Check the conversation log.")

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
    server = sys.argv[1] if len(sys.argv) > 1 else "refactor-prep"
    transport = sys.argv[2] if len(sys.argv) > 2 else "unix"
    asyncio.run(run_refactoring(server, transport))
