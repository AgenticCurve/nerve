#!/usr/bin/env python3
"""Number loop Graph - Claude picks numbers, Python generates sequences.

Flow:
1. Ask Claude for a number between 3 and 10
2. Log task (tee) - logs to file, passes through
3. Python function generates sequence [1, 2, ..., N]
4. Send sequence back to Claude, ask for another number
5. Repeat for N iterations

Usage:
    python examples/number_loop.py [server_name] [iterations] [transport]
    python examples/number_loop.py loop-test 3            # 3 iterations, unix socket
    python examples/number_loop.py loop-test 5 tcp        # 5 iterations, TCP
"""

import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

from nerve.server.protocols import Command, CommandType

# =============================================================================
# TASK DEFINITIONS
# =============================================================================


def tee_task(data: any, log_file: str, label: str = "") -> any:
    """Tee task - logs data to file and passes through unchanged.

    Like Unix `tee` command: logs to file, returns input unchanged.

    Args:
        data: Any data to log and pass through
        log_file: Path to log file
        label: Optional label for the log entry

    Returns:
        The same data, unchanged
    """
    timestamp = datetime.now().isoformat()
    log_path = Path(log_file)

    # Ensure parent directory exists
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Append to log file
    with open(log_path, "a") as f:
        f.write(f"\n{'=' * 60}\n")
        f.write(f"[{timestamp}] {label}\n")
        f.write(f"{'=' * 60}\n")
        if isinstance(data, dict):
            import json

            f.write(json.dumps(data, indent=2, default=str))
        else:
            f.write(str(data))
        f.write("\n")

    # Pass through unchanged
    return data


def generate_sequence(n: int) -> str:
    """Generate a sequence of numbers from 1 to n."""
    numbers = list(range(1, n + 1))
    return f"Sequence: {numbers}\nSum: {sum(numbers)}"


def extract_number(response_data: dict) -> int | None:
    """Extract a number between 3-10 from Claude's response."""
    sections = response_data.get("attributes", {}).get("sections", [])

    for section in sections:
        if section.get("type") == "text":
            content = section.get("content", "")
            # Look for numbers 3-10 in the text
            numbers = re.findall(r"\b([3-9]|10)\b", content)
            if numbers:
                return int(numbers[0])

    # Fallback: search in raw
    raw = response_data.get("attributes", {}).get("raw", "")
    numbers = re.findall(r"\b([3-9]|10)\b", raw)
    if numbers:
        return int(numbers[0])

    return None


def extract_text_response(response_data: dict) -> str:
    """Extract text content from response."""
    sections = response_data.get("attributes", {}).get("sections", [])
    text_parts = []
    for section in sections:
        if section.get("type") == "text":
            content = section.get("content", "").strip()
            if content:
                text_parts.append(content)
    return (
        "\n".join(text_parts)
        if text_parts
        else response_data.get("attributes", {}).get("raw", "")[:300]
    )


async def run_number_loop(
    server_name: str = "loop-test",
    iterations: int = 3,
    transport: str = "unix",
    cwd: str = "/Users/pb/agentic-curve/projects/nerve",
):
    """Run the number loop Graph."""

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

    # Create Claude node
    print("\nCreating Claude node...")
    result = await client.send_command(
        Command(
            type=CommandType.CREATE_NODE,
            params={
                "node_id": "claude-loop",
                "command": "claude",
                "cwd": cwd,
                "backend": "claude-wezterm",
            },
        )
    )
    if not result.success:
        print(f"Failed to create node: {result.error}")
        return
    print("  Created: claude-loop")

    # Wait for Claude to initialize
    print("\nWaiting for Claude to initialize...")
    await asyncio.sleep(5)

    print("\n" + "=" * 70)
    print("NUMBER LOOP GRAPH")
    print("=" * 70)

    # Initial prompt
    initial_prompt = """I'm going to ask you to pick numbers, and I'll show you sequences.

Please pick a number between 3 and 10. Just give me the number with a brief explanation of why you chose it.

For example: "I choose 7 because it's a lucky number."

What number do you pick?"""

    print("\n[TASK 1: Ask Claude for initial number]")
    print("-" * 70)

    result = await client.send_command(
        Command(
            type=CommandType.EXECUTE_INPUT,
            params={
                "node_id": "claude-loop",
                "text": initial_prompt,
                "parser": "claude",
            },
        ),
        timeout=120.0,
    )

    if not result.success:
        print(f"Error: {result.error}")
        return

    response = result.data.get("response", {})

    # Log file path (set up before first tee)
    log_file = f"/tmp/nerve-{server_name}-graph.log"
    print(f"\nLogging to: {log_file}")

    # Clear log file at start
    Path(log_file).unlink(missing_ok=True)

    # TEE TASK: Log initial response (passthrough)
    print("\n[TEE TASK: Logging initial response to file]")
    response = tee_task(response, log_file, "Initial - Claude picks first number")
    print(f"  -> Logged to {log_file}")

    text = extract_text_response(response)
    print(f"Claude: {text}")

    number = extract_number(response)
    if not number:
        print("Could not extract number from response!")
        number = 5  # Default fallback

    print(f"\nExtracted number: {number}")

    # Loop iterations
    for i in range(iterations):
        print(f"\n{'=' * 70}")
        print(f"ITERATION {i + 1}/{iterations}")
        print("=" * 70)

        # Task: Python function generates sequence
        print(f"\n[PYTHON TASK: Generate sequence for {number}]")
        print("-" * 70)
        sequence_output = generate_sequence(number)
        print(sequence_output)

        # TEE TASK: Log sequence output (passthrough)
        print("\n[TEE TASK: Logging sequence to file]")
        sequence_output = tee_task(
            sequence_output, log_file, f"Iteration {i + 1} - Python sequence for {number}"
        )
        print(f"  -> Logged to {log_file}")

        # Task: Send back to Claude
        follow_up = f"""Here's what I computed for your number {number}:

{sequence_output}

Interesting, right? Now pick another number between 3 and 10.
Pick a different number than {number} this time. What's your choice?"""

        print("\n[CLAUDE TASK: Process sequence and pick new number]")
        print("-" * 70)

        result = await client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params={
                    "node_id": "claude-loop",
                    "text": follow_up,
                    "parser": "claude",
                },
            ),
            timeout=120.0,
        )

        if not result.success:
            print(f"Error: {result.error}")
            break

        response = result.data.get("response", {})

        # TEE TASK: Log Claude's raw response (passthrough)
        print("\n[TEE TASK: Logging Claude response to file]")
        response = tee_task(response, log_file, f"Iteration {i + 1} - Claude response")
        print(f"  -> Logged to {log_file}")

        text = extract_text_response(response)
        print(f"Claude: {text}")

        new_number = extract_number(response)
        if not new_number:
            print("Could not extract number, using fallback")
            # Pick a random different number
            import random

            new_number = random.choice([n for n in range(3, 11) if n != number])

        print(f"\nExtracted number: {new_number}")
        number = new_number

    print("\n" + "=" * 70)
    print("LOOP COMPLETED")
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
    server = sys.argv[1] if len(sys.argv) > 1 else "loop-test"
    iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    transport = sys.argv[3] if len(sys.argv) > 3 else "unix"
    asyncio.run(run_number_loop(server, iterations, transport))
