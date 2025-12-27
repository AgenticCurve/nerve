#!/usr/bin/env python3
"""PRD Creation collaboration DAG template.

Three Claude agents collaborate with nested loops to create a PRD:
- Writer: ONLY one who can create/modify the PRD document
- Coach: Reviews for completeness, clarity, feasibility - cannot modify
- Reviewer: Final approval before PRD is ready for implementation

Flow:
1. Writer creates initial PRD draft
2. Inner loop: Writer <-> Coach (until Coach accepts)
3. Reviewer reviews
4. If Reviewer rejects -> Coach processes feedback -> back to inner loop
5. If Reviewer accepts -> PRD COMPLETE

Usage:
    python -m examples.agents.dev_coach_review_prd.main [options]

Options:
    --server NAME       Server name (default: prd-creation)
    --transport TYPE    Transport type: unix or tcp (default: unix)
    --context FILE      Path to additional context file
    --prd-cwd DIR       Working directory for agents (default: current directory)
    --output-file PATH  Output file path (default: /tmp/prd-creation-output.md)
    --log-file PATH     Log file path (default: /tmp/prd-creation-conversation.log)

Environment Variables:
    PRD_CWD             Working directory for agents
    PRD_OUTPUT_FILE     Output file path
    PRD_LOG_FILE        Log file path

Examples:
    python -m examples.agents.dev_coach_review_prd.main
    python -m examples.agents.dev_coach_review_prd.main --prd-cwd /path/to/project
    python -m examples.agents.dev_coach_review_prd.main --server my-prd --transport tcp
    PRD_CWD=/my/project python -m examples.agents.dev_coach_review_prd.main
"""

import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path

from nerve.server.protocols import Command, CommandType

from .prompts import (
    COACH_ACCEPTANCE,
    COACH_INITIAL_PROMPT_TEMPLATE,
    COACH_LOOP_PROMPT_TEMPLATE,
    COACH_PROCESS_REVIEWER_FEEDBACK_TEMPLATE,
    COACH_WARMUP,
    DEFAULT_LOG_FILE,
    DEFAULT_OUTPUT_FILE,
    DEV_INITIAL_PROMPT,
    DEV_LOOP_PROMPT_TEMPLATE,
    INITIAL_TASK,
    MAX_INNER_ROUNDS,
    MAX_OUTER_ROUNDS,
    PRD_OUTPUT_PATH,
    REVIEWER_ACCEPTANCE,
    REVIEWER_PROMPT_TEMPLATE,
    REVIEWER_WARMUP,
    TASK_REFRESHER,
    WRITER_WARMUP,
)

# Additional context loaded from file at runtime
ADDITIONAL_CONTEXT = ""


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


async def run_prd_creation(
    server_name: str = "prd-creation",
    transport: str = "unix",
    context_file: str | None = None,
    prd_cwd: str | None = None,
    output_file: str | None = None,
    log_file: str | None = None,
):
    """Run the PRD creation collaboration DAG."""
    global ADDITIONAL_CONTEXT

    # Use provided paths or fall back to defaults
    prd_cwd = prd_cwd or os.getcwd()
    output_file = output_file or DEFAULT_OUTPUT_FILE
    log_file = log_file or DEFAULT_LOG_FILE

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
    print("CREATING AGENTS FOR PRD CREATION")
    print("=" * 80)

    for agent_id, desc in [
        ("writer", "Creates/modifies PRD - ONLY one who can edit"),
        ("coach", "Reviews PRD - provides feedback"),
        ("reviewer", "Final approval - gatekeeps quality"),
    ]:
        print(f"\nCreating {agent_id} agent...")
        result = await client.send_command(
            Command(
                type=CommandType.CREATE_NODE,
                params={
                    "node_id": agent_id,
                    "command": "claude --dangerously-skip-permissions",
                    "cwd": prd_cwd,
                    "backend": "claude-wezterm",
                    "response_timeout": 1800.0,  # 30 minutes (PRD work is less intensive)
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
    Path(log_file).unlink(missing_ok=True)
    with open(output_file, "w") as f:
        f.write("# PRD Creation Collaboration\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        f.write(f"PRD Output: {PRD_OUTPUT_PATH}\n\n")
        f.write("---\n\n")

    print(f"Output: {output_file}")
    print(f"Log: {log_file}")
    print(f"PRD will be written to: {PRD_OUTPUT_PATH}")

    # Warmup prompts (optional)
    for agent_id, warmup in [
        ("writer", WRITER_WARMUP),
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
                    log_file,
                    f"{agent_id.title()} - Warmup",
                    extract_text_response(result.data.get("response", {})),
                )
                print(f"  {agent_id.title()} warmed up")

    # =========================================================================
    # INITIAL WRITER WORK
    # =========================================================================
    print("\n" + "=" * 80)
    print("INITIAL PHASE - WRITER CREATES DRAFT")
    print("=" * 80)

    writer_prompt = DEV_INITIAL_PROMPT.format(
        initial_task=INITIAL_TASK,
        additional_context=ADDITIONAL_CONTEXT,
    )

    print("\n[WRITER: Creating initial PRD draft...]")
    print("-" * 80)

    result = await client.send_command(
        Command(
            type=CommandType.EXECUTE_INPUT,
            params={
                "node_id": "writer",
                "text": writer_prompt,
                "parser": "claude",
            },
        ),
        timeout=1800.0,  # 30 minutes
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    writer_response = extract_text_response(result.data.get("response", {}))
    print(writer_response[:2000] + "..." if len(writer_response) > 2000 else writer_response)
    log_to_file(log_file, "Writer - Initial", writer_response)

    with open(output_file, "a") as f:
        f.write("## Initial Draft\n\n")
        f.write(writer_response)
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
                timeout=1800.0,
            )

            if not result.success:
                print(f"Error: {result.error}")
                break

            coach_response = extract_text_response(result.data.get("response", {}))
            print(coach_response[:2000] + "..." if len(coach_response) > 2000 else coach_response)
            log_to_file(
                log_file,
                f"Coach - Processing Feedback (Outer {outer_round})",
                coach_response,
            )

            # Writer addresses Coach's instructions
            writer_prompt = DEV_LOOP_PROMPT_TEMPLATE.format(
                coach_response=coach_response,
                task_refresher=TASK_REFRESHER,
                additional_context=ADDITIONAL_CONTEXT,
            )

            print("\n[WRITER: Addressing feedback...]")
            print("-" * 80)

            result = await client.send_command(
                Command(
                    type=CommandType.EXECUTE_INPUT,
                    params={
                        "node_id": "writer",
                        "text": writer_prompt,
                        "parser": "claude",
                    },
                ),
                timeout=1800.0,
            )

            if not result.success:
                print(f"Error: {result.error}")
                break

            writer_response = extract_text_response(result.data.get("response", {}))
            print(
                writer_response[:2000] + "..." if len(writer_response) > 2000 else writer_response
            )
            log_to_file(
                log_file,
                f"Writer - Addressing Feedback (Outer {outer_round})",
                writer_response,
            )

            reviewer_feedback = None  # Clear after processing

        # =====================================================================
        # INNER LOOP: Writer <-> Coach
        # =====================================================================
        inner_round = 0
        coach_accepted = False

        # First coach review (initial or after processing reviewer feedback)
        coach_prompt = (
            COACH_INITIAL_PROMPT_TEMPLATE.format(
                initial_task=INITIAL_TASK,
                dev_response=writer_response,
                acceptance_phrase=COACH_ACCEPTANCE,
                additional_context=ADDITIONAL_CONTEXT,
            )
            if outer_round == 1 and not reviewer_feedback
            else COACH_LOOP_PROMPT_TEMPLATE.format(
                dev_response=writer_response,
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

            print("\n[COACH: Reviewing PRD...]")
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
            log_to_file(
                log_file,
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

            # Writer addresses feedback
            writer_prompt = DEV_LOOP_PROMPT_TEMPLATE.format(
                coach_response=coach_response,
                task_refresher=TASK_REFRESHER,
                additional_context=ADDITIONAL_CONTEXT,
            )

            print("\n[WRITER: Addressing feedback...]")
            print("-" * 80)

            result = await client.send_command(
                Command(
                    type=CommandType.EXECUTE_INPUT,
                    params={
                        "node_id": "writer",
                        "text": writer_prompt,
                        "parser": "claude",
                    },
                ),
                timeout=1800.0,
            )

            if not result.success:
                print(f"Error: {result.error}")
                break

            writer_response = extract_text_response(result.data.get("response", {}))
            print(
                writer_response[:2000] + "..." if len(writer_response) > 2000 else writer_response
            )
            log_to_file(
                log_file,
                f"Writer - Outer {outer_round} Inner {inner_round}",
                writer_response,
            )

            # Prepare next coach prompt
            coach_prompt = COACH_LOOP_PROMPT_TEMPLATE.format(
                dev_response=writer_response,
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

        print("\n[REVIEWER: Final PRD review...]")
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
            timeout=1800.0,
        )

        if not result.success:
            print(f"Error: {result.error}")
            break

        reviewer_response = extract_text_response(result.data.get("response", {}))
        print(
            reviewer_response[:2000] + "..." if len(reviewer_response) > 2000 else reviewer_response
        )
        log_to_file(log_file, f"Reviewer - Outer {outer_round}", reviewer_response)

        # Check reviewer acceptance
        if REVIEWER_ACCEPTANCE in reviewer_response:
            print("\n" + "#" * 80)
            print("REVIEWER ACCEPTED - PRD COMPLETE!")
            print("#" * 80)
            reviewer_accepted = True

            with open(output_file, "a") as f:
                f.write(f"## Accepted (Outer Round {outer_round})\n\n")
                f.write("### Reviewer's Final Assessment\n\n")
                f.write(reviewer_response)
                f.write("\n\n---\n\n")
                f.write(f"*PRD Completed on {datetime.now().isoformat()}*\n")
                f.write(f"*PRD Location: {PRD_OUTPUT_PATH}*\n")
            break

        # Store feedback for next iteration
        reviewer_feedback = reviewer_response
        print("\nReviewer has concerns - feeding back to Coach")

        with open(output_file, "a") as f:
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

        with open(output_file, "a") as f:
            f.write("\n## Terminated\n\n")
            f.write(f"Reached max rounds ({MAX_OUTER_ROUNDS}) without approval.\n\n")
            f.write(f"*Terminated on {datetime.now().isoformat()}*\n")

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)
    print(f"\nOuter rounds: {outer_round}")
    print(f"Approved: {reviewer_accepted}")
    print(f"Output: {output_file}")
    print(f"Log: {log_file}")
    if reviewer_accepted:
        print(f"PRD Location: {PRD_OUTPUT_PATH}")

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


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="PRD Creation collaboration DAG with three Claude agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--server",
        default="prd-creation",
        help="Server name (default: prd-creation)",
    )
    parser.add_argument(
        "--transport",
        choices=["unix", "tcp"],
        default="unix",
        help="Transport type (default: unix)",
    )
    parser.add_argument(
        "--context",
        dest="context_file",
        help="Path to additional context file",
    )
    parser.add_argument(
        "--prd-cwd",
        dest="prd_cwd",
        default=os.environ.get("PRD_CWD"),
        help="Working directory for agents (env: PRD_CWD, default: current directory)",
    )
    parser.add_argument(
        "--output-file",
        dest="output_file",
        default=os.environ.get("PRD_OUTPUT_FILE"),
        help="Output file path (env: PRD_OUTPUT_FILE, default: /tmp/prd-creation-output.md)",
    )
    parser.add_argument(
        "--log-file",
        dest="log_file",
        default=os.environ.get("PRD_LOG_FILE"),
        help="Log file path (env: PRD_LOG_FILE, default: /tmp/prd-creation-conversation.log)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # Determine paths from CLI args, env vars, or defaults
    # Priority: CLI arg > env var > hardcoded default (for prd_cwd: current directory)
    # Note: argparse already handles env var fallback via default=os.environ.get(...)
    prd_cwd = args.prd_cwd if args.prd_cwd else os.getcwd()
    output_file = args.output_file if args.output_file else DEFAULT_OUTPUT_FILE
    log_file = args.log_file if args.log_file else DEFAULT_LOG_FILE

    asyncio.run(
        run_prd_creation(
            server_name=args.server,
            transport=args.transport,
            context_file=args.context_file,
            prd_cwd=prd_cwd,
            output_file=output_file,
            log_file=log_file,
        )
    )
