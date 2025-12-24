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
    python examples/dev_coach_consultants.py [server_name] [transport] [context_file]
    python examples/dev_coach_consultants.py my-task unix
    python examples/dev_coach_consultants.py my-task unix /path/to/context.md
"""

# =============================================================================
# CONFIGURATION
# =============================================================================

ACCEPTANCE_PHRASE = "I ACCEPT AND WE ARE DONE."
MAX_ROUNDS = 50

# Paths
DEV_CWD = "/Users/pb/agentic-curve/projects/nerve"
COACH_CWD = "/Users/pb/agentic-curve/projects/nerve"
CONSULTANT_CWD = "/Users/pb/agentic-curve/projects/nerve"
OUTPUT_FILE = "/tmp/dev-coach-consultants-output.md"
LOG_FILE = "/tmp/dev-coach-consultants-conversation.log"

# =============================================================================
# ADDITIONAL CONTEXT - Loaded from file at runtime (use {additional_context} in prompts)
# =============================================================================

ADDITIONAL_CONTEXT = ""  # Populated from CLI argument if provided

# =============================================================================
# WARMUP - Optional system-like instructions sent once before task begins
# =============================================================================

DEV_WARMUP = ""
COACH_WARMUP = ""
CONSULTANT_1_WARMUP = ""
CONSULTANT_2_WARMUP = ""
CONSULTANT_3_WARMUP = ""

# =============================================================================
# TASK
# =============================================================================

INITIAL_TASK = """Explore this codebase and understand its architecture.

Please:
1. Read the README and key source files
2. Understand the project structure
3. Identify the main components and how they interact

Provide a summary of your findings."""

TASK_REFRESHER = """Remember: We are exploring the codebase architecture."""

# =============================================================================
# PROMPTS - Developer (Dev only talks to Coach)
# =============================================================================

DEV_INITIAL_PROMPT = """You are a Senior Software Developer.

{initial_task}

{additional_context}

You are working with a Coach who will review your work and guide you.
Start by understanding the task and providing your initial work."""

DEV_LOOP_PROMPT_TEMPLATE = """The Coach reviewed your work and provided feedback:

\"\"\"
{coach_response}
\"\"\"

{task_refresher}

Please:
1. Address each point raised
2. Explore further if needed
3. Provide an updated, complete response

The coach will accept when satisfied."""

# =============================================================================
# PROMPTS - Coach (coordinates everything, Dev doesn't know about consultants)
# =============================================================================

# --- Coach initial thoughts (first round) ---

COACH_INITIAL_THOUGHTS_TEMPLATE = """You are a Technical Coach reviewing a developer's work.

{initial_task}

{additional_context}

The Developer just provided their initial work:

\"\"\"
{dev_response}
\"\"\"

Please review this work and share your initial thoughts:
1. What's good about this work?
2. What concerns or gaps do you see?
3. What questions do you have?

Be thorough - your thoughts will inform further review."""

# --- Coach loop thoughts (subsequent rounds) ---

COACH_LOOP_THOUGHTS_TEMPLATE = """You are a Technical Coach reviewing updated work from the developer.

The Developer addressed your previous feedback:

\"\"\"
{dev_response}
\"\"\"

{task_refresher}

Please review this updated work and share your thoughts:
1. Did they address your previous concerns?
2. What's improved?
3. What still needs work?

Be thorough - your thoughts will inform further review."""

# --- Coach synthesize (combines own thoughts + consultant advice) ---

COACH_SYNTHESIZE_TEMPLATE = """You are a Technical Coach. You've reviewed the developer's work and consulted with experts.

DEVELOPER'S WORK:
\"\"\"
{dev_response}
\"\"\"

YOUR INITIAL THOUGHTS:
\"\"\"
{coach_thoughts}
\"\"\"

CONSULTANT 1's ADVICE:
\"\"\"
{consultant_1_advice}
\"\"\"

CONSULTANT 2's ADVICE:
\"\"\"
{consultant_2_advice}
\"\"\"

CONSULTANT 3's ADVICE:
\"\"\"
{consultant_3_advice}
\"\"\"

{task_refresher}

Now synthesize all of this into clear, actionable feedback for the developer.
Do NOT mention the consultants - the developer doesn't know about them.
Present the feedback as your own coaching guidance.

If the work is FULLY SATISFACTORY and ready, respond with EXACTLY:
"{acceptance_phrase}"

Otherwise, provide your synthesized feedback."""

# =============================================================================
# PROMPTS - Consultants (provide independent advice to Coach)
# =============================================================================

CONSULTANT_1_PROMPT_TEMPLATE = """You are a Technical Consultant (Expert #1) advising a Coach.

The Coach is reviewing a developer's work and wants your perspective.

DEVELOPER'S WORK:
\"\"\"
{dev_response}
\"\"\"

COACH'S INITIAL THOUGHTS:
\"\"\"
{coach_thoughts}
\"\"\"

{task_refresher}

{additional_context}

Please provide your expert advice:
- What do you notice that the Coach might have missed?
- Any concerns or suggestions?
- What would you recommend?

Be concise and actionable."""

CONSULTANT_2_PROMPT_TEMPLATE = """You are a Technical Consultant (Expert #2) advising a Coach.

The Coach is reviewing a developer's work and wants your perspective.

DEVELOPER'S WORK:
\"\"\"
{dev_response}
\"\"\"

COACH'S INITIAL THOUGHTS:
\"\"\"
{coach_thoughts}
\"\"\"

{task_refresher}

{additional_context}

Please provide your expert advice:
- What do you notice that the Coach might have missed?
- Any concerns or suggestions?
- What would you recommend?

Be concise and actionable."""

CONSULTANT_3_PROMPT_TEMPLATE = """You are a Technical Consultant (Expert #3) advising a Coach.

The Coach is reviewing a developer's work and wants your perspective.

DEVELOPER'S WORK:
\"\"\"
{dev_response}
\"\"\"

COACH'S INITIAL THOUGHTS:
\"\"\"
{coach_thoughts}
\"\"\"

{task_refresher}

{additional_context}

Please provide your expert advice:
- What do you notice that the Coach might have missed?
- Any concerns or suggestions?
- What would you recommend?

Be concise and actionable."""

# =============================================================================
# SCRIPT
# =============================================================================

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
        async def get_consultant_advice(agent_id: str, prompt_template: str):
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
