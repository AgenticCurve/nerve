#!/usr/bin/env python3
"""Implementation DAG - Implement the plan with Dev/Coach/Reviewer collaboration.

Nested loop structure:
- INNER LOOP A: Dev <-> Coach (until Coach accepts)
- OUTER LOOP B: Dev/Coach <-> Reviewer (until Reviewer accepts)

Roles:
- Dev: ONLY person who can modify code
- Coach: Reviews, runs tests, guides - but CANNOT modify code
- Reviewer: Final review, runs tests, checks git diff - but CANNOT modify code

Flow:
1. Dev implements based on plan
2. Coach reviews, provides feedback
3. When Coach accepts -> Reviewer reviews
4. If Reviewer has issues -> feedback to Coach -> Coach coordinates with Dev
5. When Reviewer accepts -> PROGRAM COMPLETE

Usage:
    python examples/implement_plan.py [server_name] [transport]
    python examples/implement_plan.py impl-plan unix
    python examples/implement_plan.py impl-plan tcp
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from nerve.server.protocols import Command, CommandType

# =============================================================================
# CONFIGURATION
# =============================================================================

# Termination phrases - must be exact match
COACH_ACCEPTANCE = "I ACCEPT YOUR IMPLEMENTATION AND DONT NEED ANY MORE CHANGES."
REVIEWER_ACCEPTANCE = "I ACCEPT THE IMPLEMENTATION AND APPROVE FOR MERGE."

MAX_INNER_ROUNDS = 30  # Max Dev <-> Coach rounds per outer iteration
MAX_OUTER_ROUNDS = 10  # Max Reviewer iterations

# =============================================================================
# PROMPT TEMPLATES
# =============================================================================

# Initial prompt for Developer to start implementing
DEV_INITIAL_PROMPT = """You are a Senior Software Developer implementing a feature for the Nerve project.

READ THE PLAN FIRST:
{input_plan}

YOUR ROLE:
- You are the ONLY person who can modify code in this project
- Implement the plan step by step
- Write clean, well-tested code
- Follow existing patterns in the codebase

PRE-EXISTING CODE:
- There's already some code implemented in the last run. Feel free to
modify the code. But you've the complete ownership of the code. So when talking
to coach, present as if you had written it.

WORKFLOW:
1. Read and understand the plan
2. Explore the codebase to understand existing patterns
3. Start implementing - you CAN and SHOULD write code
4. After each significant change, summarize what you did

You are working with a Coach who will review your work and guide you.
The Coach cannot write code - only you can make changes. Ask coach for decisions
if you are confused or stuck.

Start by reading the plan and proposing your implementation approach.
Then begin implementing. Show your progress as you go."""

# Coach processes reviewer feedback (without revealing source to Dev)
COACH_PROCESS_FEEDBACK_PROMPT = """You are a Technical Coach overseeing implementation of a feature for Nerve.

IMPORTANT: During the review process, issues have been identified that need to be fixed.

FEEDBACK TO ADDRESS:
\"\"\"
{reviewer_feedback}
\"\"\"

Your job is to:
1. Understand the issues identified
2. Formulate clear, actionable instructions for the Developer
3. You CANNOT modify code yourself - only the Developer can

Review the current state of the code using `git diff main` and `git status`.
Then provide specific instructions for the Developer on what needs to be fixed.

DO NOT mention where this feedback came from. Just tell the Developer what needs to be fixed."""

# Dev receives Coach's instructions after Coach processed feedback
DEV_ADDRESS_COACH_INSTRUCTIONS_PROMPT = """The Coach has identified some issues that need to be addressed:

\"\"\"
{coach_response}
\"\"\"

Please:
1. Address each point the Coach raised
2. Make the necessary code changes
3. Run tests if applicable
4. Summarize what you changed

Remember: You are the ONLY one who can modify code. Make the changes now."""

# Normal Coach review prompt during Dev <-> Coach loop
COACH_REVIEW_PROMPT = """You are a Technical Coach overseeing implementation of a feature for Nerve.

The Developer just provided this update:

\"\"\"
{dev_response}
\"\"\"

YOUR ROLE:
- Review the Developer's implementation
- You CANNOT modify code - only the Developer can do that
- You NEED to make decisions and gut calls where developer is stuck
- Ensure dev remains on track and there's no feature bloat

CRITICAL REQUIREMENTS - DO NOT ACCEPT WITHOUT THESE:
1. NEW TESTS MUST EXIST - The developer MUST write tests for new functionality
   - Check: Are there test files for the new code?
   - Run: `uv run pytest tests/ -v` to verify tests exist and pass
   - If no new tests, REJECT and ask developer to write them

2. FUNCTIONALITY MUST BE VERIFIED - Don't just read code, TEST IT
   - Ask developer to demonstrate the feature works
   - For a proxy: start it, make a request, show it works
   - For an API: call it, show the response

3. INTEGRATION MUST WORK - Run the full test suite
   - Run: `uv run pytest` - ALL tests must pass
   - If tests fail, REJECT

REVIEW CHECKLIST:
□ New tests written for new functionality?
□ All tests pass (old AND new)?
□ Developer demonstrated it actually works?
□ Code follows existing patterns?
□ No obvious bugs?

DO NOT ACCEPT if:
- No new tests were written
- Tests are failing
- Developer hasn't demonstrated functionality works

If ALL requirements are met, respond with EXACTLY:
"{coach_acceptance}"

Otherwise, be specific about what's missing."""

# Dev addresses Coach's feedback during normal loop
DEV_ADDRESS_FEEDBACK_PROMPT = """The Coach reviewed your implementation and provided this feedback:

\"\"\"
{coach_response}
\"\"\"

Please:
1. Address each point the Coach raised
2. Make the necessary code changes
3. Run tests if applicable
4. Summarize what you changed

Remember: You are the ONLY one who can modify code. Make the changes now."""

# Reviewer's final review prompt
REVIEWER_PROMPT = """You are a Code Reviewer performing final review before merge.

THE TASK:
The team has implemented a feature based on the plan at {input_plan}.
The Coach has approved the implementation. Now you need to do RIGOROUS final validation.

YOUR REVIEW PROCESS - DO ALL OF THESE:

1. CHECK THE DIFF:
   - Run `git diff main` to see ALL changes
   - Verify changes match the plan
   - Look for any unintended modifications

2. RUN ALL TESTS:
   - Run `uv run pytest -v` to see all test results
   - ALL tests must pass
   - Verify NEW tests exist for new functionality

3. ACTUALLY TEST THE FEATURE:
   - Don't just read code - RUN IT
   - For a server/proxy: start it, make real requests
   - For a library: write a quick script to use it
   - Show the actual output/behavior

4. CHECK FOR MISSING PIECES:
   - Are there tests for edge cases?
   - Is error handling tested?
   - Are there integration tests?

YOUR ROLE:
- You CANNOT modify code - only review and test
- Be STRICT - if tests are missing or failing, REJECT
- If you can't verify the feature works, REJECT

DO NOT ACCEPT if:
- Any tests are failing
- New functionality lacks tests
- You haven't actually run and verified the feature
- The diff shows unrelated changes

If you have PERSONALLY VERIFIED everything works, respond with EXACTLY:
"{reviewer_acceptance}"

Otherwise, provide specific feedback. Be harsh - better to catch issues now."""


# =============================================================================
# HELPER FUNCTIONS
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


def check_coach_acceptance(response: str) -> bool:
    """Check if coach accepted the implementation."""
    return COACH_ACCEPTANCE in response


def check_reviewer_acceptance(response: str) -> bool:
    """Check if reviewer accepted the implementation."""
    return REVIEWER_ACCEPTANCE in response


# =============================================================================
# MAIN DAG
# =============================================================================

async def run_implementation(
    server_name: str = "impl-plan",
    transport: str = "unix",
    input_plan: str = "/tmp/nerve-proxy-plan-v2.md",
    cwd: str = "/Users/pb/agentic-curve/projects/nerve",
):
    """Run the implementation DAG."""

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

    # Create three Claude channels
    print("\n" + "=" * 80)
    print("CREATING AGENTS")
    print("=" * 80)

    print("\nCreating Developer agent...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_CHANNEL,
            params={
                "channel_id": "dev",
                "command": "claude --dangerously-skip-permissions",
                "cwd": cwd,
                "backend": "claude-wezterm",
            },
        )
    )
    if not result.success:
        print(f"Failed to create dev: {result.error}")
        return
    print("  Created: dev (CAN modify code)")

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
    print("  Created: coach (can read, test - CANNOT modify code)")

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
    print("  Created: reviewer (can read, test, git diff - CANNOT modify code)")

    # Wait for Claude instances to initialize
    print("\nWaiting for agents to initialize...")
    await asyncio.sleep(5)

    # Setup logging
    log_file = f"/tmp/nerve-{server_name}-conversation.log"
    Path(log_file).unlink(missing_ok=True)
    print(f"Conversation log: {log_file}")
    print(f"Input plan: {input_plan}")

    # =========================================================================
    # INITIAL DEV PROMPT
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 1: INITIAL IMPLEMENTATION")
    print("=" * 80)

    prompt = DEV_INITIAL_PROMPT.format(input_plan=input_plan)

    print("\n[DEV: Starting implementation...]")
    print("-" * 80)

    result = await client.send_command(
        Command(
            type=CommandType.SEND_INPUT,
            params={
                "channel_id": "dev",
                "text": prompt,
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
    log_to_file(log_file, "Dev - Initial Implementation", dev_response)

    # =========================================================================
    # OUTER LOOP B: Reviewer Loop
    # =========================================================================
    outer_round = 0
    reviewer_accepted = False
    reviewer_feedback = None  # Will be set after first reviewer round

    while outer_round < MAX_OUTER_ROUNDS and not reviewer_accepted:
        outer_round += 1
        print(f"\n{'#' * 80}")
        print(f"OUTER LOOP - ITERATION {outer_round}/{MAX_OUTER_ROUNDS}")
        print("#" * 80)

        # =====================================================================
        # INNER LOOP A: Dev <-> Coach Loop
        # =====================================================================
        inner_round = 0
        coach_accepted = False

        # If we have reviewer feedback, Coach needs to process it first
        # and formulate instructions for Dev (without mentioning "Reviewer")
        if reviewer_feedback:
            print(f"\n{'=' * 80}")
            print(f"COACH PROCESSING FEEDBACK (Outer: {outer_round})")
            print("=" * 80)

            prompt = COACH_PROCESS_FEEDBACK_PROMPT.format(
                reviewer_feedback=reviewer_feedback
            )

            print("\n[COACH: Processing feedback...]")
            print("-" * 80)

            result = await client.send_command(
                Command(
                    type=CommandType.SEND_INPUT,
                    params={
                        "channel_id": "coach",
                        "text": prompt,
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
            log_to_file(log_file, f"Coach - Processing Reviewer Feedback (Outer {outer_round})", coach_response)

            # Now send Coach's instructions to Dev
            prompt = DEV_ADDRESS_COACH_INSTRUCTIONS_PROMPT.format(
                coach_response=coach_response
            )

            print(f"\n[DEV: Addressing Coach's instructions...]")
            print("-" * 80)

            result = await client.send_command(
                Command(
                    type=CommandType.SEND_INPUT,
                    params={
                        "channel_id": "dev",
                        "text": prompt,
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
            log_to_file(log_file, f"Dev - Addressing Feedback (Outer {outer_round})", dev_response)

            # Clear reviewer feedback since we've processed it
            reviewer_feedback = None

        # Normal Dev <-> Coach loop
        while inner_round < MAX_INNER_ROUNDS and not coach_accepted:
            inner_round += 1
            print(f"\n{'=' * 80}")
            print(f"INNER LOOP - Dev/Coach Round {inner_round}/{MAX_INNER_ROUNDS} (Outer: {outer_round})")
            print("=" * 80)

            prompt = COACH_REVIEW_PROMPT.format(
                dev_response=dev_response,
                coach_acceptance=COACH_ACCEPTANCE,
            )

            print(f"\n[COACH: Reviewing round {inner_round}...]")
            print("-" * 80)

            result = await client.send_command(
                Command(
                    type=CommandType.SEND_INPUT,
                    params={
                        "channel_id": "coach",
                        "text": prompt,
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
            log_to_file(log_file, f"Coach - Outer {outer_round} Inner {inner_round}", coach_response)

            # Check for coach acceptance
            if check_coach_acceptance(coach_response):
                print("\n" + "=" * 80)
                print("✅ COACH ACCEPTED - Moving to Reviewer")
                print("=" * 80)
                coach_accepted = True
                break

            # Dev addresses coach feedback
            prompt = DEV_ADDRESS_FEEDBACK_PROMPT.format(
                coach_response=coach_response
            )

            print(f"\n[DEV: Addressing feedback round {inner_round}...]")
            print("-" * 80)

            result = await client.send_command(
                Command(
                    type=CommandType.SEND_INPUT,
                    params={
                        "channel_id": "dev",
                        "text": prompt,
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
            log_to_file(log_file, f"Dev - Outer {outer_round} Inner {inner_round}", dev_response)

        # Check if inner loop hit max rounds
        if not coach_accepted:
            print(f"\n⚠️  Inner loop hit max rounds ({MAX_INNER_ROUNDS}) - proceeding to reviewer anyway")

        # =====================================================================
        # REVIEWER REVIEW
        # =====================================================================
        print(f"\n{'=' * 80}")
        print(f"REVIEWER REVIEW - Outer Round {outer_round}")
        print("=" * 80)

        prompt = REVIEWER_PROMPT.format(
            input_plan=input_plan,
            reviewer_acceptance=REVIEWER_ACCEPTANCE,
        )

        print("\n[REVIEWER: Final review...]")
        print("-" * 80)

        result = await client.send_command(
            Command(
                type=CommandType.SEND_INPUT,
                params={
                    "channel_id": "reviewer",
                    "text": prompt,
                    "parser": "claude",
                },
            ),
            timeout=1800.0,  # 30 minutes
        )

        if not result.success:
            print(f"Error: {result.error}")
            break

        reviewer_response = extract_text_response(result.data.get("response", {}))
        print(reviewer_response[:2000] + "..." if len(reviewer_response) > 2000 else reviewer_response)
        log_to_file(log_file, f"Reviewer - Outer {outer_round}", reviewer_response)

        # Check for reviewer acceptance
        if check_reviewer_acceptance(reviewer_response):
            print("\n" + "#" * 80)
            print("🎉 REVIEWER ACCEPTED - IMPLEMENTATION COMPLETE!")
            print("#" * 80)
            reviewer_accepted = True
            break

        # Store reviewer feedback for next inner loop iteration
        reviewer_feedback = reviewer_response
        print("\n⚠️  Reviewer has concerns - sending feedback to Coach for next iteration")

    # =========================================================================
    # COMPLETION
    # =========================================================================
    print("\n" + "=" * 80)
    print("DAG COMPLETED")
    print("=" * 80)
    print(f"\nResults:")
    print(f"  Outer rounds (Reviewer): {outer_round}")
    print(f"  Reviewer accepted: {reviewer_accepted}")
    print(f"  Conversation log: {log_file}")

    if reviewer_accepted:
        print("\n✅ Implementation approved! Ready to merge.")
    else:
        print(f"\n⚠️  Max outer rounds ({MAX_OUTER_ROUNDS}) reached without reviewer approval.")

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
    server = sys.argv[1] if len(sys.argv) > 1 else "impl-plan"
    transport = sys.argv[2] if len(sys.argv) > 2 else "unix"
    asyncio.run(run_implementation(server, transport))
