#!/usr/bin/env python3
"""Dev + Coach + Consultants collaboration DAG template.

Five Claude agents collaborate:
- Developer: Does the work, talks only to Coach
- Coach: Reviews, consults experts, synthesizes feedback
- Consultant 1/2/3: Provide independent advice to Coach

Flow:
1. Dev does work → sends to Coach
2. Coach reviews, forms own thoughts
3. Coach asks all 3 consultants for advice (they see dev's work + coach's thoughts)
4. Each consultant provides independent advice
5. Coach synthesizes everything → sends feedback to Dev
6. Dev addresses feedback → back to step 2
7. Loop until Coach accepts

Dev never knows about consultants - they only talk to Coach.

Usage:
    python -m examples.agents.dev_coach_consultants.main [server_name] [transport] [context_file]
    python -m examples.agents.dev_coach_consultants.main my-task unix
    python -m examples.agents.dev_coach_consultants.main my-task unix /path/to/context.md
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from nerve.server.protocols import Command, CommandType

from .prompts import (
    ACCEPTANCE_PHRASE,
    COACH_CWD,
    COACH_INITIAL_THOUGHTS_TEMPLATE,
    COACH_LOOP_THOUGHTS_TEMPLATE,
    COACH_SYNTHESIZE_TEMPLATE,
    COACH_WARMUP,
    CONSULTANT_1_PROMPT_TEMPLATE,
    CONSULTANT_1_WARMUP,
    CONSULTANT_2_PROMPT_TEMPLATE,
    CONSULTANT_2_WARMUP,
    CONSULTANT_3_PROMPT_TEMPLATE,
    CONSULTANT_3_WARMUP,
    CONSULTANT_CWD,
    DEV_CWD,
    DEV_INITIAL_PROMPT,
    DEV_LOOP_PROMPT_TEMPLATE,
    DEV_WARMUP,
    INITIAL_TASK,
    LOG_FILE,
    MAX_ROUNDS,
    OUTPUT_FILE,
    TASK_REFRESHER,
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


async def send_prompt(client, node_id: str, text: str, timeout: float = 300.0):
    """Send a prompt and return the response text."""
    result = await client.send_command(
        Command(
            type=CommandType.EXECUTE_INPUT,
            params={
                "node_id": node_id,
                "text": text,
                "parser": "claude",
            },
        ),
        timeout=timeout,
    )
    if not result.success:
        return None, result.error
    return extract_text_response(result.data.get("response", {})), None


async def run_dev_coach_consultants(
    server_name: str = "dev-coach-consultants",
    transport: str = "unix",
    context_file: str | None = None,
):
    """Run the dev + coach + consultants collaboration DAG."""
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

    agents = [
        ("dev", DEV_CWD, "Developer - does the work"),
        ("coach", COACH_CWD, "Coach - reviews and synthesizes"),
        ("consultant-1", CONSULTANT_CWD, "Consultant 1 - expert advice"),
        ("consultant-2", CONSULTANT_CWD, "Consultant 2 - expert advice"),
        ("consultant-3", CONSULTANT_CWD, "Consultant 3 - expert advice"),
    ]

    for agent_id, cwd, desc in agents:
        print(f"\nCreating {agent_id}...")
        result = await client.send_command(
            Command(
                type=CommandType.CREATE_NODE,
                params={
                    "node_id": agent_id,
                    "command": "claude",
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
        f.write("# Dev + Coach + Consultants Collaboration\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        f.write("---\n\n")

    print(f"Output: {OUTPUT_FILE}")
    print(f"Log: {LOG_FILE}")

    # Warmup (optional)
    warmups = [
        ("dev", DEV_WARMUP),
        ("coach", COACH_WARMUP),
        ("consultant-1", CONSULTANT_1_WARMUP),
        ("consultant-2", CONSULTANT_2_WARMUP),
        ("consultant-3", CONSULTANT_3_WARMUP),
    ]
    for agent_id, warmup in warmups:
        if warmup.strip():
            print(f"\n[{agent_id.upper()}: Warmup...]")
            response, err = await send_prompt(client, agent_id, warmup, timeout=120.0)
            if response:
                log_to_file(LOG_FILE, f"{agent_id} - Warmup", response)
                print(f"  {agent_id} warmed up")

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

    dev_response, err = await send_prompt(client, "dev", dev_prompt, timeout=600.0)
    if err:
        print(f"Error: {err}")
        return

    print(dev_response[:2000] + "..." if len(dev_response) > 2000 else dev_response)
    log_to_file(LOG_FILE, "Dev - Initial", dev_response)

    with open(OUTPUT_FILE, "a") as f:
        f.write("## Initial Work\n\n")
        f.write(dev_response)
        f.write("\n\n---\n\n")

    # =========================================================================
    # MAIN LOOP
    # =========================================================================
    round_num = 0
    accepted = False

    while round_num < MAX_ROUNDS and not accepted:
        round_num += 1
        print(f"\n{'=' * 80}")
        print(f"ROUND {round_num}/{MAX_ROUNDS}")
        print("=" * 80)

        # ---------------------------------------------------------------------
        # Step 1: Coach reviews and forms thoughts
        # ---------------------------------------------------------------------
        print("\n[COACH: Reviewing dev's work...]")
        print("-" * 80)

        if round_num == 1:
            coach_review_prompt = COACH_INITIAL_THOUGHTS_TEMPLATE.format(
                initial_task=INITIAL_TASK,
                additional_context=ADDITIONAL_CONTEXT,
                dev_response=dev_response,
            )
        else:
            coach_review_prompt = COACH_LOOP_THOUGHTS_TEMPLATE.format(
                dev_response=dev_response,
                task_refresher=TASK_REFRESHER,
            )

        coach_thoughts, err = await send_prompt(client, "coach", coach_review_prompt, timeout=300.0)
        if err:
            print(f"Error: {err}")
            break

        print(coach_thoughts[:1500] + "..." if len(coach_thoughts) > 1500 else coach_thoughts)
        log_to_file(LOG_FILE, f"Coach - Thoughts (Round {round_num})", coach_thoughts)

        # ---------------------------------------------------------------------
        # Step 2: Ask all consultants for advice (in parallel)
        # ---------------------------------------------------------------------
        print("\n[CONSULTANTS: Providing advice in parallel...]")
        print("-" * 80)

        consultant_configs = [
            ("consultant-1", CONSULTANT_1_PROMPT_TEMPLATE),
            ("consultant-2", CONSULTANT_2_PROMPT_TEMPLATE),
            ("consultant-3", CONSULTANT_3_PROMPT_TEMPLATE),
        ]

        # Build prompts
        async def get_consultant_advice(
            agent_id: str,
            prompt_template: str,
            dev_response: str = dev_response,
            coach_thoughts: str = coach_thoughts,
        ):
            prompt = prompt_template.format(
                dev_response=dev_response,
                coach_thoughts=coach_thoughts,
                task_refresher=TASK_REFRESHER,
                additional_context=ADDITIONAL_CONTEXT,
            )
            advice, err = await send_prompt(client, agent_id, prompt, timeout=300.0)
            if err:
                return agent_id, "(no response)", err
            return agent_id, advice, None

        # Query all consultants in parallel
        results = await asyncio.gather(
            *[
                get_consultant_advice(agent_id, template)
                for agent_id, template in consultant_configs
            ]
        )

        # Collect results
        consultant_advice = {}
        for agent_id, advice, err in results:
            if err:
                print(f"  [{agent_id.upper()}]: Error - {err}")
            else:
                print(f"  [{agent_id.upper()}]: Provided advice")
            consultant_advice[agent_id] = advice
            log_to_file(LOG_FILE, f"{agent_id} - Advice (Round {round_num})", advice)

        # ---------------------------------------------------------------------
        # Step 3: Coach synthesizes everything
        # ---------------------------------------------------------------------
        print("\n[COACH: Synthesizing feedback...]")
        print("-" * 80)

        synthesize_prompt = COACH_SYNTHESIZE_TEMPLATE.format(
            dev_response=dev_response,
            coach_thoughts=coach_thoughts,
            consultant_1_advice=consultant_advice.get("consultant-1", ""),
            consultant_2_advice=consultant_advice.get("consultant-2", ""),
            consultant_3_advice=consultant_advice.get("consultant-3", ""),
            task_refresher=TASK_REFRESHER,
            acceptance_phrase=ACCEPTANCE_PHRASE,
        )

        coach_response, err = await send_prompt(client, "coach", synthesize_prompt, timeout=300.0)
        if err:
            print(f"Error: {err}")
            break

        print(coach_response[:2000] + "..." if len(coach_response) > 2000 else coach_response)
        log_to_file(LOG_FILE, f"Coach - Synthesized Feedback (Round {round_num})", coach_response)

        # ---------------------------------------------------------------------
        # Check acceptance
        # ---------------------------------------------------------------------
        if ACCEPTANCE_PHRASE in coach_response:
            print("\n" + "=" * 80)
            print("ACCEPTED!")
            print("=" * 80)
            accepted = True

            with open(OUTPUT_FILE, "a") as f:
                f.write(f"## Accepted (Round {round_num})\n\n")
                f.write("### Coach's Final Feedback\n\n")
                f.write(coach_response)
                f.write("\n\n---\n\n")
                f.write("## Final Output\n\n")
                f.write(dev_response)
                f.write("\n\n---\n\n")
                f.write(f"*Completed after {round_num} rounds on {datetime.now().isoformat()}*\n")
            break

        with open(OUTPUT_FILE, "a") as f:
            f.write(f"## Round {round_num}\n\n")
            f.write("### Coach Feedback\n\n")
            f.write(coach_response)
            f.write("\n\n")

        # ---------------------------------------------------------------------
        # Step 4: Dev addresses feedback
        # ---------------------------------------------------------------------
        print("\n[DEV: Addressing feedback...]")
        print("-" * 80)

        dev_prompt = DEV_LOOP_PROMPT_TEMPLATE.format(
            coach_response=coach_response,
            task_refresher=TASK_REFRESHER,
        )

        dev_response, err = await send_prompt(client, "dev", dev_prompt, timeout=600.0)
        if err:
            print(f"Error: {err}")
            break

        print(dev_response[:2000] + "..." if len(dev_response) > 2000 else dev_response)
        log_to_file(LOG_FILE, f"Dev - Response (Round {round_num})", dev_response)

        with open(OUTPUT_FILE, "a") as f:
            f.write("### Developer Response\n\n")
            f.write(dev_response)
            f.write("\n\n---\n\n")

    # =========================================================================
    # COMPLETION
    # =========================================================================
    if not accepted:
        print("\n" + "=" * 80)
        print(f"MAX ROUNDS ({MAX_ROUNDS}) REACHED")
        print("=" * 80)

        with open(OUTPUT_FILE, "a") as f:
            f.write("\n## Terminated\n\n")
            f.write(f"Reached max rounds ({MAX_ROUNDS}) without acceptance.\n\n")
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
    server = sys.argv[1] if len(sys.argv) > 1 else "dev-coach-consultants"
    transport = sys.argv[2] if len(sys.argv) > 2 else "unix"
    context_file = sys.argv[3] if len(sys.argv) > 3 else None
    asyncio.run(run_dev_coach_consultants(server, transport, context_file))
