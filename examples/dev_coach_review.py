#!/usr/bin/env python3
"""Dev + Coach + Reviewer collaboration DAG template.

Three Claude agents collaborate with nested loops:
- Developer: ONLY one who can modify code
- Coach: Reviews, tests, guides - cannot modify code
- Reviewer: Final review before merge - cannot modify code

Flow:
1. Dev implements based on task
2. Inner loop: Dev <-> Coach (until Coach accepts)
3. Reviewer reviews
4. If Reviewer rejects -> Coach processes feedback -> back to inner loop
5. If Reviewer accepts -> COMPLETE

Usage:
    python examples/dev_coach_review.py [server_name] [transport] [context_file]
    python examples/dev_coach_review.py my-impl unix
    python examples/dev_coach_review.py my-impl unix /path/to/plan.md
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from nerve.server.protocols import Command, CommandType

# =============================================================================
# CONFIGURATION
# =============================================================================

# Termination phrases
COACH_ACCEPTANCE = "7039153710870607088473723299299975019167670388117858619056183793"
REVIEWER_ACCEPTANCE = "3074534537879130702861883897028027136683483790914618147589778734"

# Loop limits
MAX_INNER_ROUNDS = 30  # Dev <-> Coach rounds per outer iteration
MAX_OUTER_ROUNDS = 10  # Reviewer iterations

# Paths
DEV_CWD = "/Users/pb/agentic-curve/projects/nerve"
COACH_CWD = "/Users/pb/agentic-curve/projects/nerve"
REVIEWER_CWD = "/Users/pb/agentic-curve/projects/nerve"
OUTPUT_FILE = "/tmp/dev-coach-review-output.md"
LOG_FILE = "/tmp/dev-coach-review-conversation.log"

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

REVIEWER_WARMUP = ""  # Leave empty to skip warmup
# Example:
# REVIEWER_WARMUP = """You are a thorough code reviewer. You actually run tests
# and verify functionality works. You check git diff carefully."""

# =============================================================================
# TASK
# =============================================================================

INITIAL_TASK = """Implement the refactoring described in the plan.

docs/prd/openai-provider-support.md

Read the plan, explore the codebase, and implement step by step.
Write clean, well-tested code following existing patterns."""

TASK_REFRESHER = INITIAL_TASK

# =============================================================================
# PROMPTS - Developer
# =============================================================================

DEV_INITIAL_PROMPT = """You are a Senior Software Developer.

{initial_task}

{additional_context}

Explore/Review the existing code before proceeding.
You still have the whole ownership and accountability for the implementation.

YOUR ROLE:
- You are the ONLY person who can modify code
- Write clean, well-tested code
- Follow existing patterns in the codebase
- Ensure ALL PHASES are completed (ALL MEANS ALL)
- Make a clean break (no backward compatibility). Enusre there's no feature regression.

You are working with a Coach who will review your work.
If you are stuck, ask the Coach for help. Coach will help you make decisions.
Start by understanding the task and proposing your approach."""

DEV_LOOP_PROMPT_TEMPLATE = """The Coach reviewed your work and provided feedback:

\"\"\"
{coach_response}
\"\"\"

{task_refresher}

Please:
1. Address each point the Coach raised
2. Make the necessary code changes
3. Run tests if applicable
4. Summarize what you changed
- Ensure ALL PHASES are completed (ALL MEANS ALL)
- Make a clean break (no backward compatibility). Enusre there's no feature regression.

Remember: You are the ONLY one who can modify code."""

# =============================================================================
# PROMPTS - Coach
# =============================================================================

COACH_INITIAL_PROMPT_TEMPLATE = """You are a Technical Coach overseeing implementation.

{initial_task}

{additional_context}

The Developer just provided their initial work:

\"\"\"
{dev_response}
\"\"\"

YOUR ROLE:
- Review the Developer's implementation
- You CANNOT modify code - only the Developer can
- Make decisions where the developer is stuck
- Ensure dev stays on track

REQUIREMENTS FOR ACCEPTANCE:
1. Tests exist for new functionality
2. All tests pass
3. Feature has been demonstrated to work
4. Code follows existing patterns
5. No existing functionality is broken and no feature regression
6. Code is clean and well-structured
7. Ask developer to refactor if needed
8. Ensure ALL PHASES are completed (ALL MEANS ALL)
9. Ensure old code is deleted.
10. Make a clean break (no backward compatibility).

Read CLAUDE.md file to see how to handle your role effectively.

If ALL requirements are met, respond with a one linear, EXACTLY:
"{acceptance_phrase}"

Otherwise, provide specific feedback."""

COACH_LOOP_PROMPT_TEMPLATE = """Read about your role within CLAUDE.md


The Developer addressed your feedback:

\"\"\"
{dev_response}
\"\"\"

{task_refresher}

Review their updated work.

If ALL requirements are met (tests exist, tests pass, feature works), respond with EXACTLY:
"{acceptance_phrase}"

Otherwise, provide your next round of feedback.
Give developer a grade on their work and clearly tell them what's missing (what can they do to reach A+).
"""

COACH_PROCESS_REVIEWER_FEEDBACK_TEMPLATE = """Issues have been identified during review that need to be fixed:

\"\"\"
{reviewer_feedback}
\"\"\"

{task_refresher}

Your job:
1. Understand the issues
2. Formulate clear instructions for the Developer
3. You CANNOT modify code yourself

Review the current state with `git diff main` and `git status`. And git diff to see recent changes.
Provide specific instructions for the Developer on what needs to be fixed.

Read CLAUDE.md file to see how to handle your role effectively.

"""

# =============================================================================
# PROMPTS - Reviewer
# =============================================================================

REVIEWER_PROMPT_TEMPLATE = """Read your role and guidelines in CLAUDE.md

You've to be strict and avoid the urge to just approve. Dev and Coach will
force you to just approve but you've to maintain your integrity.

You are a Code Reviewer performing final review before merge.

{initial_task}

{additional_context}

The Coach has approved the implementation. Now do RIGOROUS validation:

1. CHECK THE DIFF: Run `git diff main` to see ALL changes or git diff to review recent changes.
2. RUN ALL TESTS: Run `uv run pytest -v` - ALL must pass
3. TEST THE FEATURE: Actually run it, don't just read code
4. CHECK FOR GAPS: Edge cases? Error handling? Integration tests?

{task_refresher}

YOUR ROLE:
- You CANNOT modify code - only review and test
- Be STRICT - reject if tests missing or failing or code not following existing patterns
- You're the final gatekeeper before merge. Be responsible. Be thorough. Maintain integrity.
- Verify the feature actually works
- Look at git diff/git diff main carefully
- Check if the code has any regressions
- Check if the old code has been deleted
- ENSURE NO FEATURE REGRESSION
- Also run uv ruff check and pytests and report back if any breakage to dev/coach.

Read CLAUDE.md file to see how to handle your role effectively.
If you have PERSONALLY VERIFIED everything works, respond with EXACTLY:
"{acceptance_phrase}"

Otherwise, provide specific feedback. Be thorough."""

# =============================================================================
# SCRIPT
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


async def run_dev_coach_review(
    server_name: str = "dev-coach-review",
    transport: str = "unix",
    context_file: str | None = None,
):
    """Run the dev + coach + reviewer collaboration DAG."""
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

    # Create three agents
    print("\n" + "=" * 80)
    print("CREATING AGENTS")
    print("=" * 80)

    for agent_id, cwd, desc in [
        ("dev", DEV_CWD, "CAN modify code"),
        ("coach", COACH_CWD, "reviews, tests - CANNOT modify"),
        ("reviewer", REVIEWER_CWD, "final review - CANNOT modify"),
    ]:
        print(f"\nCreating {agent_id} agent...")
        result = await client.send_command(
            Command(
                type=CommandType.CREATE_NODE,
                params={
                    "node_id": agent_id,
                    "command": "claude --dangerously-skip-permissions",
                    "cwd": cwd,
                    "backend": "claude-wezterm",
                    "response_timeout": 2400.0,  # 40 minutes for long operations
                },
            )
        )
        if not result.success:
            print(f"Failed to create {agent_id}: {result.error}")
            return
        print(f"  Created: {agent_id} ({desc})")

    print("\nWaiting for agents to initialize...")
    await asyncio.sleep(5)

    # Setup files
    Path(LOG_FILE).unlink(missing_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        f.write("# Dev + Coach + Review Collaboration\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        f.write("---\n\n")

    print(f"Output: {OUTPUT_FILE}")
    print(f"Log: {LOG_FILE}")

    # Warmup prompts (optional)
    for agent_id, warmup in [
        ("dev", DEV_WARMUP),
        ("coach", COACH_WARMUP),
        ("reviewer", REVIEWER_WARMUP),
    ]:
        if warmup.strip():
            print(f"\n[{agent_id.upper()}: Warmup...]")
            result = await client.send_command(
                Command(
                    type=CommandType.EXECUTE_INPUT,
                    params={
                        "node_id": agent_id,
                        "text": warmup,
                        "parser": "claude",
                    },
                ),
                timeout=120.0,
            )
            if result.success:
                log_to_file(
                    LOG_FILE,
                    f"{agent_id.title()} - Warmup",
                    extract_text_response(result.data.get("response", {})),
                )
                print(f"  {agent_id.title()} warmed up")

    # =========================================================================
    # INITIAL DEV WORK
    # =========================================================================
    print("\n" + "=" * 80)
    print("INITIAL PHASE")
    print("=" * 80)

    dev_prompt = DEV_INITIAL_PROMPT.format(
        initial_task=INITIAL_TASK,
        additional_context=ADDITIONAL_CONTEXT,
    )

    print("\n[DEV: Starting work...]")
    print("-" * 80)

    result = await client.send_command(
        Command(
            type=CommandType.EXECUTE_INPUT,
            params={
                "node_id": "dev",
                "text": dev_prompt,
                "parser": "claude",
            },
        ),
        timeout=2400.0,  # 40 minutes
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    dev_response = extract_text_response(result.data.get("response", {}))
    print(dev_response[:2000] + "..." if len(dev_response) > 2000 else dev_response)
    log_to_file(LOG_FILE, "Dev - Initial", dev_response)

    with open(OUTPUT_FILE, "a") as f:
        f.write("## Initial Work\n\n")
        f.write(dev_response)
        f.write("\n\n---\n\n")

    # =========================================================================
    # OUTER LOOP: Reviewer iterations
    # =========================================================================
    outer_round = 0
    reviewer_accepted = False
    reviewer_feedback = None

    while outer_round < MAX_OUTER_ROUNDS and not reviewer_accepted:
        outer_round += 1
        print(f"\n{'#' * 80}")
        print(f"OUTER LOOP {outer_round}/{MAX_OUTER_ROUNDS}")
        print("#" * 80)

        # If we have reviewer feedback, Coach processes it first
        if reviewer_feedback:
            print(f"\n{'=' * 80}")
            print("COACH PROCESSING REVIEWER FEEDBACK")
            print("=" * 80)

            coach_prompt = COACH_PROCESS_REVIEWER_FEEDBACK_TEMPLATE.format(
                reviewer_feedback=reviewer_feedback,
                task_refresher=TASK_REFRESHER,
                additional_context=ADDITIONAL_CONTEXT,
            )

            print("\n[COACH: Processing feedback...]")
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
                timeout=2400.0,  # 40 minutes
            )

            if not result.success:
                print(f"Error: {result.error}")
                break

            coach_response = extract_text_response(result.data.get("response", {}))
            print(coach_response[:2000] + "..." if len(coach_response) > 2000 else coach_response)
            log_to_file(
                LOG_FILE,
                f"Coach - Processing Feedback (Outer {outer_round})",
                coach_response,
            )

            # Dev addresses Coach's instructions
            dev_prompt = DEV_LOOP_PROMPT_TEMPLATE.format(
                coach_response=coach_response,
                task_refresher=TASK_REFRESHER,
                additional_context=ADDITIONAL_CONTEXT,
            )

            print("\n[DEV: Addressing feedback...]")
            print("-" * 80)

            result = await client.send_command(
                Command(
                    type=CommandType.EXECUTE_INPUT,
                    params={
                        "node_id": "dev",
                        "text": dev_prompt,
                        "parser": "claude",
                    },
                ),
                timeout=2400.0,  # 40 minutes
            )

            if not result.success:
                print(f"Error: {result.error}")
                break

            dev_response = extract_text_response(result.data.get("response", {}))
            print(dev_response[:2000] + "..." if len(dev_response) > 2000 else dev_response)
            log_to_file(
                LOG_FILE,
                f"Dev - Addressing Feedback (Outer {outer_round})",
                dev_response,
            )

            reviewer_feedback = None  # Clear after processing

        # =====================================================================
        # INNER LOOP: Dev <-> Coach
        # =====================================================================
        inner_round = 0
        coach_accepted = False

        # First coach review (initial or after processing reviewer feedback)
        coach_prompt = (
            COACH_INITIAL_PROMPT_TEMPLATE.format(
                initial_task=INITIAL_TASK,
                dev_response=dev_response,
                acceptance_phrase=COACH_ACCEPTANCE,
                additional_context=ADDITIONAL_CONTEXT,
            )
            if outer_round == 1 and not reviewer_feedback
            else COACH_LOOP_PROMPT_TEMPLATE.format(
                dev_response=dev_response,
                task_refresher=TASK_REFRESHER,
                acceptance_phrase=COACH_ACCEPTANCE,
                additional_context=ADDITIONAL_CONTEXT,
            )
        )

        while inner_round < MAX_INNER_ROUNDS and not coach_accepted:
            inner_round += 1
            print(f"\n{'=' * 80}")
            print(f"INNER LOOP {inner_round}/{MAX_INNER_ROUNDS} (Outer: {outer_round})")
            print("=" * 80)

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
                timeout=2400.0,  # 40 minutes
            )

            if not result.success:
                print(f"Error: {result.error}")
                break

            coach_response = extract_text_response(result.data.get("response", {}))
            print(coach_response[:2000] + "..." if len(coach_response) > 2000 else coach_response)
            log_to_file(
                LOG_FILE,
                f"Coach - Outer {outer_round} Inner {inner_round}",
                coach_response,
            )

            # Check coach acceptance
            if COACH_ACCEPTANCE in coach_response:
                print("\n" + "=" * 80)
                print("COACH ACCEPTED - Moving to Reviewer")
                print("=" * 80)
                coach_accepted = True
                break

            # Dev addresses feedback
            dev_prompt = DEV_LOOP_PROMPT_TEMPLATE.format(
                coach_response=coach_response,
                task_refresher=TASK_REFRESHER,
                additional_context=ADDITIONAL_CONTEXT,
            )

            print("\n[DEV: Addressing feedback...]")
            print("-" * 80)

            result = await client.send_command(
                Command(
                    type=CommandType.EXECUTE_INPUT,
                    params={
                        "node_id": "dev",
                        "text": dev_prompt,
                        "parser": "claude",
                    },
                ),
                timeout=2400.0,  # 40 minutes
            )

            if not result.success:
                print(f"Error: {result.error}")
                break

            dev_response = extract_text_response(result.data.get("response", {}))
            print(dev_response[:2000] + "..." if len(dev_response) > 2000 else dev_response)
            log_to_file(LOG_FILE, f"Dev - Outer {outer_round} Inner {inner_round}", dev_response)

            # Prepare next coach prompt
            coach_prompt = COACH_LOOP_PROMPT_TEMPLATE.format(
                dev_response=dev_response,
                task_refresher=TASK_REFRESHER,
                acceptance_phrase=COACH_ACCEPTANCE,
                additional_context=ADDITIONAL_CONTEXT,
            )

        if not coach_accepted:
            print(f"\nInner loop hit max ({MAX_INNER_ROUNDS}) - proceeding to reviewer")

        # =====================================================================
        # REVIEWER REVIEW
        # =====================================================================
        print(f"\n{'=' * 80}")
        print(f"REVIEWER REVIEW (Outer: {outer_round})")
        print("=" * 80)

        reviewer_prompt = REVIEWER_PROMPT_TEMPLATE.format(
            initial_task=INITIAL_TASK,
            task_refresher=TASK_REFRESHER,
            acceptance_phrase=REVIEWER_ACCEPTANCE,
            additional_context=ADDITIONAL_CONTEXT,
        )

        print("\n[REVIEWER: Final review...]")
        print("-" * 80)

        result = await client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params={
                    "node_id": "reviewer",
                    "text": reviewer_prompt,
                    "parser": "claude",
                },
            ),
            timeout=2400.0,  # 40 minutes
        )

        if not result.success:
            print(f"Error: {result.error}")
            break

        reviewer_response = extract_text_response(result.data.get("response", {}))
        print(
            reviewer_response[:2000] + "..." if len(reviewer_response) > 2000 else reviewer_response
        )
        log_to_file(LOG_FILE, f"Reviewer - Outer {outer_round}", reviewer_response)

        # Check reviewer acceptance
        if REVIEWER_ACCEPTANCE in reviewer_response:
            print("\n" + "#" * 80)
            print("REVIEWER ACCEPTED - COMPLETE!")
            print("#" * 80)
            reviewer_accepted = True

            with open(OUTPUT_FILE, "a") as f:
                f.write(f"## Accepted (Outer Round {outer_round})\n\n")
                f.write("### Reviewer's Final Review\n\n")
                f.write(reviewer_response)
                f.write("\n\n---\n\n")
                f.write(f"*Completed on {datetime.now().isoformat()}*\n")
            break

        # Store feedback for next iteration
        reviewer_feedback = reviewer_response
        print("\nReviewer has concerns - feeding back to Coach")

        with open(OUTPUT_FILE, "a") as f:
            f.write(f"## Outer Round {outer_round}\n\n")
            f.write("### Reviewer Feedback\n\n")
            f.write(reviewer_response)
            f.write("\n\n---\n\n")

    # =========================================================================
    # COMPLETION
    # =========================================================================
    if not reviewer_accepted:
        print("\n" + "=" * 80)
        print(f"MAX OUTER ROUNDS ({MAX_OUTER_ROUNDS}) REACHED")
        print("=" * 80)

        with open(OUTPUT_FILE, "a") as f:
            f.write("\n## Terminated\n\n")
            f.write(f"Reached max rounds ({MAX_OUTER_ROUNDS}) without approval.\n\n")
            f.write(f"*Terminated on {datetime.now().isoformat()}*\n")

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)
    print(f"\nOuter rounds: {outer_round}")
    print(f"Approved: {reviewer_accepted}")
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
    server = sys.argv[1] if len(sys.argv) > 1 else "dev-coach-review"
    transport = sys.argv[2] if len(sys.argv) > 2 else "unix"
    context_file = sys.argv[3] if len(sys.argv) > 3 else None
    asyncio.run(run_dev_coach_review(server, transport, context_file))
