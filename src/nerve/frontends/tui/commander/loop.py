"""Loop execution for Commander TUI.

Handles the :loop command for multi-node conversation chains.
Supports round-robin conversation between nodes with customizable
prompts, stop conditions, and per-node templates.
"""

from __future__ import annotations

import shlex
import time
from typing import TYPE_CHECKING

from nerve.frontends.tui.commander.blocks import Block
from nerve.frontends.tui.commander.executor import get_block_type
from nerve.frontends.tui.commander.rendering import print_block
from nerve.frontends.tui.commander.variables import expand_variables

if TYPE_CHECKING:
    from nerve.frontends.tui.commander.commander import Commander


async def handle_loop(commander: Commander, args: str) -> None:
    """Handle :loop command for multi-node conversation chains.

    Syntax:
        :loop @node1 @node2 [@node3...] "start prompt" [options]

    Options:
        --until "phrase"     Stop when output contains phrase
        --max N              Maximum rounds (default: 10)
        --<node> "template"  Per-node prompt template ({prev} = previous output)

    Pattern: Chain (round-robin)
        A → B → C → A → B → C → ...

    Example:
        :loop @claude @gemini "implement fibonacci" --until "LGTM" --max 5
        :loop @dev @reviewer "write a parser" --dev "Feedback: {prev}" --reviewer "Review: {prev}"

    Args:
        commander: Commander instance.
        args: Loop command arguments.
    """
    if not args.strip():
        commander.console.print(
            '[warning]Usage: :loop @node1 @node2 "start prompt" [--until phrase] [--max N][/]'
        )
        commander.console.print('[dim]Example: :loop @claude @gemini "discuss AI" --max 5[/]')
        return

    # Parse the loop arguments
    parsed = parse_loop_args(commander, args)
    if parsed is None:
        return  # Error already printed

    nodes, start_prompt, until_phrase, max_rounds, templates = parsed

    # Validate nodes exist
    await commander._sync_nodes()
    for node_id in nodes:
        if node_id not in commander.nodes:
            commander.console.print(f"[error]Node not found: {node_id}[/]")
            return

    if len(nodes) < 2:
        commander.console.print("[error]Loop requires at least 2 nodes[/]")
        return

    # Print loop start info
    commander.console.print()
    commander.console.print(f"[bold]Starting loop:[/] {' → '.join('@' + n for n in nodes)}")
    commander.console.print(
        f"[dim]Max rounds: {max_rounds}"
        + (f', until: "{until_phrase}"' if until_phrase else "")
        + "[/]"
    )
    commander.console.print()

    # Execute the loop
    await _execute_loop(commander, nodes, start_prompt, until_phrase, max_rounds, templates)


def parse_loop_args(
    commander: Commander, args: str
) -> tuple[list[str], str, str | None, int, dict[str, str]] | None:
    """Parse :loop command arguments.

    Args:
        commander: Commander instance (for error output).
        args: Raw argument string.

    Returns:
        Tuple of (nodes, start_prompt, until_phrase, max_rounds, templates)
        or None if parsing failed.
    """
    # Default values
    max_rounds = 10
    until_phrase: str | None = None
    templates: dict[str, str] = {}
    nodes: list[str] = []
    start_prompt: str | None = None

    try:
        # Use shlex to handle quoted strings properly
        tokens = shlex.split(args)
    except ValueError as e:
        commander.console.print(f"[error]Parse error: {e}[/]")
        return None

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token.startswith("@"):
            # Node reference
            nodes.append(token[1:])
            i += 1

        elif token == "--until":
            # Until phrase
            if i + 1 >= len(tokens):
                commander.console.print("[error]--until requires a value[/]")
                return None
            until_phrase = tokens[i + 1]
            i += 2

        elif token == "--max":
            # Max rounds
            if i + 1 >= len(tokens):
                commander.console.print("[error]--max requires a number[/]")
                return None
            try:
                max_rounds = int(tokens[i + 1])
            except ValueError:
                commander.console.print(f"[error]--max must be a number, got: {tokens[i + 1]}[/]")
                return None
            i += 2

        elif token.startswith("--"):
            # Per-node template: --nodename "template"
            node_name = token[2:]
            if i + 1 >= len(tokens):
                commander.console.print(f"[error]{token} requires a template value[/]")
                return None
            templates[node_name] = tokens[i + 1]
            i += 2

        elif start_prompt is None:
            # First non-option, non-node token is the start prompt
            start_prompt = token
            i += 1

        else:
            commander.console.print(f"[error]Unexpected argument: {token}[/]")
            return None

    # Validate
    if not nodes:
        commander.console.print("[error]No nodes specified. Use @node1 @node2 ...[/]")
        return None

    if start_prompt is None:
        commander.console.print("[error]No start prompt specified[/]")
        return None

    return nodes, start_prompt, until_phrase, max_rounds, templates


async def _execute_loop(
    commander: Commander,
    nodes: list[str],
    start_prompt: str,
    until_phrase: str | None,
    max_rounds: int,
    templates: dict[str, str],
) -> None:
    """Execute the loop iteration.

    Args:
        commander: Commander instance.
        nodes: List of node IDs to cycle through.
        start_prompt: Initial prompt for first node.
        until_phrase: Stop when output contains this phrase.
        max_rounds: Maximum number of complete rounds.
        templates: Per-node prompt templates.
    """
    prev_output = start_prompt
    node_outputs: dict[str, str] = {}  # Track last output from each node
    exchange_num = 0  # Total exchanges for reporting
    stopped_by_phrase = False
    aborted = False

    try:
        for round_num in range(max_rounds):
            for step, node_id in enumerate(nodes):
                # Build the prompt
                if round_num == 0 and step == 0:
                    # First exchange: use start prompt directly
                    prompt = start_prompt
                else:
                    # Subsequent: use template or raw prev_output
                    template = templates.get(node_id, "{prev}")
                    prompt = template.replace("{prev}", prev_output)
                    # Replace {nodename} references with that node's last output
                    for nid, output in node_outputs.items():
                        prompt = prompt.replace("{" + nid + "}", output)

                # Execute on node (creates block, updates timeline)
                block = await execute_loop_step(commander, node_id, prompt)
                if block is None:
                    commander.console.print("[error]Loop aborted due to execution error[/]")
                    aborted = True
                    break

                # Get output for next iteration
                prev_output = block.output_text or ""
                node_outputs[node_id] = prev_output  # Track this node's output
                exchange_num += 1

                # Check stop condition
                if until_phrase and until_phrase in prev_output:
                    stopped_by_phrase = True
                    break

            # Break outer loop if inner loop broke
            if stopped_by_phrase or aborted:
                break

    except KeyboardInterrupt:
        commander.console.print()
        commander.console.print("[warning]Loop interrupted by user[/]")
        return

    # Print summary
    _print_loop_summary(
        commander,
        exchange_num,
        max_rounds,
        until_phrase,
        stopped_by_phrase=stopped_by_phrase,
        aborted=aborted,
    )


async def execute_loop_step(commander: Commander, node_id: str, prompt: str) -> Block | None:
    """Execute a single step in the loop, creating a block.

    Args:
        commander: Commander instance.
        node_id: Node to execute on.
        prompt: Prompt to send.

    Returns:
        The completed Block, or None on error.
    """
    if commander._adapter is None:
        return None

    node_type = commander.nodes.get(node_id, "node")
    block_type = get_block_type(node_type)

    # Expand variables BEFORE adding block to timeline
    # This ensures :::-1 references the previous block, not the current one
    expanded_prompt = expand_variables(commander.timeline, prompt)

    # Create and add block (input_text stores RAW prompt)
    block = Block(
        block_type=block_type,
        node_id=node_id,
        input_text=prompt,
        status="running",
    )
    commander.timeline.add(block)

    # Render the running block
    commander.timeline.render_last(commander.console)

    # Execute
    start_time = time.monotonic()

    try:
        commander._active_node_id = node_id
        result = await commander._adapter.execute_on_node(node_id, expanded_prompt)
    except Exception as e:
        block.status = "error"
        block.error = f"{type(e).__name__}: {e}"
        block.duration_ms = (time.monotonic() - start_time) * 1000
        print_block(commander.console, block)
        return None
    finally:
        commander._active_node_id = None

    duration_ms = (time.monotonic() - start_time) * 1000

    # Update block with results
    if result.get("success"):
        block.status = "completed"
        block.output_text = str(result.get("output", "")).strip()
        block.raw = result
    else:
        block.status = "error"
        error_msg = result.get("error", "Unknown error")
        error_type = result.get("error_type", "unknown")
        block.error = f"[{error_type}] {error_msg}"
        block.raw = result

    block.duration_ms = duration_ms

    # Print the completed block
    print_block(commander.console, block)

    return block if block.status == "completed" else None


def _print_loop_summary(
    commander: Commander,
    exchange_num: int,
    max_rounds: int,
    until_phrase: str | None,
    *,
    stopped_by_phrase: bool,
    aborted: bool,
) -> None:
    """Print loop completion summary.

    Args:
        commander: Commander instance.
        exchange_num: Total number of exchanges completed.
        max_rounds: Maximum rounds configured.
        until_phrase: Stop phrase if configured.
        stopped_by_phrase: Whether loop stopped due to phrase match.
        aborted: Whether loop was aborted due to error.
    """
    commander.console.print()
    if stopped_by_phrase:
        commander.console.print(
            f'[success]Loop ended: "{until_phrase}" detected after {exchange_num} exchanges[/]'
        )
    elif aborted:
        commander.console.print(f"[error]Loop aborted after {exchange_num} exchanges[/]")
    else:
        commander.console.print(
            f"[dim]Loop completed: {exchange_num} exchanges ({max_rounds} rounds)[/]"
        )
