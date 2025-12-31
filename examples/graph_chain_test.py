#!/usr/bin/env python3
"""Graph chain test - sequential math operations with extraction.

Tests the full end-to-end flow:
1. Connect to server
2. Send first prompt: "What is 2+2? Reply with just the number"
3. Extract the number from the text section
4. Send second prompt: "{number} + {number} is what?"
5. Extract and chain to third prompt

Usage:
    # First start server and create node:
    nerve server start graph-test
    nerve server node create claude --server graph-test --type ClaudeWezTermNode --command claude

    # Then run this script:
    python examples/graph_chain_test.py

    # Or use the Graph file format:
    nerve server graph run examples/graph_chain_test.py --server graph-test
"""

import asyncio
import sys

# Graph definition for nerve server graph run
# This is the dict-based format that the server understands
graph = {
    "steps": [
        {
            "id": "step1",
            "node": "claude",
            "prompt": "What is 2+2? Reply with just the number, nothing else.",
            "depends_on": [],
        },
        {
            "id": "step2",
            "node": "claude",
            "prompt": "{step1} + {step1} is what? Reply with just the number, nothing else.",
            "depends_on": ["step1"],
        },
        {
            "id": "step3",
            "node": "claude",
            "prompt": "{step2} + {step2} is what? Reply with just the number, nothing else.",
            "depends_on": ["step2"],
        },
    ]
}


def extract_number_from_response(response_data: dict) -> str:
    """Extract the number from a parsed response.

    Looks for the text section and extracts the number.
    """
    sections = response_data.get("attributes", {}).get("sections", [])

    # Find text sections
    for section in sections:
        if section.get("type") == "text":
            content = section.get("content", "").strip()
            # Extract just the number (first word/number in content)
            for word in content.split():
                # Try to parse as int
                try:
                    num = int(word.replace(".", "").replace(",", ""))
                    return str(num)
                except ValueError:
                    continue
            # If no number found, return the full content
            return content

    # Fallback: try to find number in raw response
    raw = response_data.get("attributes", {}).get("raw", "")
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("\u23fa") and "(" not in stripped:
            # This is likely a text response line
            content = stripped[1:].strip()
            try:
                return str(int(content))
            except ValueError:
                pass

    return response_data.get("attributes", {}).get("raw", "")[:100]


async def run_chain_test(server_name: str = "graph-test", node_name: str = "claude"):
    """Run the chained math test manually with extraction."""
    from nerve.server.protocols import Command, CommandType
    from nerve.transport import UnixSocketClient

    socket_path = f"/tmp/nerve-{server_name}.sock"

    print(f"Connecting to {socket_path}...")
    client = UnixSocketClient(socket_path)

    try:
        await client.connect()
        print("Connected!")
    except Exception as e:
        print(f"Failed to connect: {e}")
        print(f"Make sure server is running: nerve server start {server_name}")
        return

    results = {}
    prompts = [
        ("step1", "What is 2+2? Reply with just the number, nothing else."),
        ("step2", "{step1} + {step1} is what? Reply with just the number, nothing else."),
        ("step3", "{step2} + {step2} is what? Reply with just the number, nothing else."),
    ]

    print("\n" + "=" * 60)
    print("Running chained math Graph")
    print("=" * 60)

    for step_id, prompt_template in prompts:
        # Substitute previous results
        prompt = prompt_template.format(**results)

        print(f"\n[{step_id}] Sending: {prompt}")

        result = await client.send_command(
            Command(
                type=CommandType.EXECUTE_INPUT,
                params={
                    "node_id": node_name,
                    "text": prompt,
                    "parser": "claude",
                },
            )
        )

        if not result.success:
            print(f"  ERROR: {result.error}")
            break

        response = result.data.get("response", {})

        # Extract the number from the response
        extracted = extract_number_from_response(response)
        results[step_id] = extracted

        print(f"  Response sections: {len(response.get('attributes', {}).get('sections', []))}")
        for i, section in enumerate(response.get("attributes", {}).get("sections", [])):
            sect_type = section.get("type", "?")
            content = section.get("content", "")[:80]
            print(f"    [{i}] {sect_type}: {content}...")
        print(f"  Extracted: {extracted}")

    await client.disconnect()

    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)
    for step_id, value in results.items():
        print(f"  {step_id}: {value}")

    # Verify the chain
    expected = {"step1": "4", "step2": "8", "step3": "16"}
    success = all(results.get(k) == v for k, v in expected.items())

    print("\n" + "=" * 60)
    if success:
        print("SUCCESS: Chain completed correctly!")
        print("  2+2=4, 4+4=8, 8+8=16")
    else:
        print("PARTIAL: Chain completed but values differ from expected")
        print(f"  Expected: {expected}")
        print(f"  Got: {results}")
    print("=" * 60)

    return results


if __name__ == "__main__":
    server = sys.argv[1] if len(sys.argv) > 1 else "graph-test"
    node = sys.argv[2] if len(sys.argv) > 2 else "claude"
    asyncio.run(run_chain_test(server, node))
