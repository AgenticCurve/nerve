"""SuggestionNode - generates contextual command suggestions via LLM.

SuggestionNode learns from the conversation history (block inputs/outputs)
to predict what command the user might want to run next. It uses pattern
recognition: given previous outputs and the commands that followed, predict
the next command.

Key features:
- Builds message history from blocks (output→user, input→assistant)
- Only predicts @node, @graph, or %workflow commands (never ":" commands)
- Includes project directory tree for context
- Reminds AI of available entities in system prompt AND last message

Example:
    >>> node = SuggestionNode(
    ...     id="suggestions",
    ...     session=session,
    ...     api_key="sk-or-...",
    ...     model="anthropic/claude-3-haiku",
    ... )
    >>> ctx = ExecutionContext(session=session, input={
    ...     "nodes": ["claude", "bash"],
    ...     "graphs": ["pipeline"],
    ...     "workflows": ["deploy"],
    ...     "blocks": [
    ...         {"input": "@claude Hello", "output": "Hi there!", "success": True},
    ...         {"input": "@bash ls", "output": "file1.txt file2.txt", "success": True},
    ...     ],
    ...     "cwd": "/path/to/project",
    ... })
    >>> result = await node.execute(ctx)
    >>> print(result["output"])
    ['@claude Analyze the files in this directory', '@bash cat file1.txt']
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from nerve.core.nodes.llm.openrouter import OpenRouterNode

logger = logging.getLogger(__name__)


def _build_directory_tree(root_path: str, max_depth: int = 3) -> list[str]:
    """Build a directory tree structure using os.walk.

    Args:
        root_path: Root directory path to walk.
        max_depth: Maximum directory depth to traverse (default: 3).

    Returns:
        List of formatted tree lines.
    """
    lines: list[str] = []
    root = Path(root_path)

    if not root.exists() or not root.is_dir():
        return [f"{root_path} (not found or not a directory)"]

    # Collect all entries with their relative paths for sorting
    entries: list[tuple[Path, bool]] = []  # (path, is_dir)

    # Use onerror to skip directories we can't access (PermissionError, etc.)
    def on_error(err: OSError) -> None:
        logger.debug("Skipping directory due to error: %s", err)

    for dirpath, dirnames, filenames in os.walk(root, onerror=on_error):
        current = Path(dirpath)
        rel_path = current.relative_to(root)

        # Enforce depth limit to avoid performance issues on large repos
        depth = len(rel_path.parts)
        if depth >= max_depth:
            dirnames.clear()  # Don't descend further
            continue

        # Skip hidden directories and common non-essential directories
        dirnames[:] = [
            d
            for d in sorted(dirnames)
            if not d.startswith(".")
            and d
            not in {
                "__pycache__",
                "node_modules",
                ".git",
                ".venv",
                "venv",
                "dist",
                "build",
                ".pytest_cache",
                ".mypy_cache",
                "egg-info",
            }
        ]

        # Add directories
        for dirname in dirnames:
            dir_rel = rel_path / dirname if str(rel_path) != "." else Path(dirname)
            entries.append((dir_rel, True))

        # Add files (skip hidden files)
        for filename in sorted(filenames):
            if not filename.startswith("."):
                file_rel = rel_path / filename if str(rel_path) != "." else Path(filename)
                entries.append((file_rel, False))

    # Sort by path to get proper tree order
    entries.sort(key=lambda x: (str(x[0]).count("/"), str(x[0])))

    # Build tree with proper indentation
    def get_indent(path: Path) -> str:
        depth = len(path.parts) - 1
        if depth <= 0:
            return ""
        return "    " * depth

    for path, is_dir in entries:
        indent = get_indent(path)
        name = path.name
        if is_dir:
            lines.append(f"{indent}{name}/")
        else:
            lines.append(f"{indent}{name}")

    return lines if lines else ["(empty directory)"]


def _format_directory_tree(root_path: str) -> str:
    """Format directory tree as a string.

    Args:
        root_path: Root directory path.

    Returns:
        Formatted tree string.
    """
    lines = _build_directory_tree(root_path)
    root_name = Path(root_path).name
    return f"{root_name}/\n" + "\n".join(lines)


# System prompt - only predicts @node, @graph, %workflow commands
SUGGESTION_SYSTEM_PROMPT = """\
You are a command prediction assistant for "nerve", a terminal-based AI orchestration tool.

Your task: Predict the next command the user will likely run, based on the conversation history.

## Command Syntax (ONLY use these formats)

- @node_name <message>    Send a message to a node
- @graph_name <input>     Execute a graph
- %workflow_name          Run a workflow

## Available Entities

{entities}

## Rules

1. ONLY suggest commands starting with @ or %
2. NEVER suggest ":" commands (like :help, :nodes) - those are meta-commands for users only
3. Learn from the conversation pattern: "given this output, what command came next?"
4. Make predictions contextually relevant to the last output and project structure

## OUTPUT FORMAT (CRITICAL)

You MUST output valid JSON in this exact format:

{{"suggestions": ["@node command here", "@other command", "%workflow"]}}

Example outputs:

{{"suggestions": ["@claude Analyze the error in the output above", "@bash cat src/main.py"]}}

{{"suggestions": ["@claude What files are in this project?", "@bash ls -la", "%deploy"]}}

Output ONLY the JSON object. No markdown, no explanation, no other text.
"""


@dataclass(repr=False)
class SuggestionNode(OpenRouterNode):
    """Generates contextual command suggestions via LLM.

    Learns from block history to predict next commands. Only predicts
    @node, @graph, or %workflow commands - never ":" meta-commands.

    Input format (dict):
        {
            "nodes": ["claude", "bash", ...],
            "graphs": ["pipeline", ...],
            "workflows": ["deploy", ...],
            "blocks": [
                {"input": "@claude Hi", "output": "Hello!", "success": True},
                ...
            ],
            "cwd": "/path/to/project",
        }

    Output format:
        {
            "success": True,
            "output": ["@claude ...", "@bash ...", ...],
            "attributes": { "raw_response": "..." }
        }
    """

    node_type: ClassVar[str] = "suggestion"

    # Number of suggestions to request
    num_suggestions: int = 5

    def _format_entities(self, context: dict[str, Any]) -> str:
        """Format available entities for system prompt.

        Args:
            context: Context dict with nodes, graphs, workflows.

        Returns:
            Formatted string listing available entities.
        """
        parts = []

        nodes = context.get("nodes", [])
        if nodes:
            parts.append(f"Nodes: {', '.join(f'@{n}' for n in nodes)}")

        graphs = context.get("graphs", [])
        if graphs:
            parts.append(f"Graphs: {', '.join(f'@{g}' for g in graphs)}")

        workflows = context.get("workflows", [])
        if workflows:
            parts.append(f"Workflows: {', '.join(f'%{w}' for w in workflows)}")

        if not parts:
            return "No entities available yet."

        return "\n".join(parts)

    def _build_message_history(self, blocks: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Build message history from blocks.

        Pattern: block output → user message, next block input → assistant message.
        This teaches the AI: "given this output, this command was run next".

        Args:
            blocks: List of block dicts with 'input', 'output', 'success' keys.

        Returns:
            List of message dicts for LLM.
        """
        messages: list[dict[str, str]] = []

        for i, block in enumerate(blocks):
            output = block.get("output", "")
            success = block.get("success", True)

            # Format output with status if failed
            if not success:
                error = block.get("error", "Unknown error")
                output_content = f"[FAILED] {error}\n{output}" if output else f"[FAILED] {error}"
            else:
                output_content = output if output else "(no output)"

            # Block output becomes user message
            messages.append({"role": "user", "content": output_content})

            # Next block's input becomes assistant message (what was predicted/run)
            if i + 1 < len(blocks):
                next_input = blocks[i + 1].get("input", "")
                if next_input:
                    messages.append({"role": "assistant", "content": next_input})

        return messages

    def _format_final_context(self, context: dict[str, Any]) -> str:
        """Format the final user message with full context.

        Includes:
        - Last block output (if any)
        - Directory tree
        - Reminder of available entities

        Args:
            context: Full context dict.

        Returns:
            Formatted final user message.
        """
        parts = []

        # Last block output
        blocks = context.get("blocks", [])
        if blocks:
            last_block = blocks[-1]
            output = last_block.get("output", "")
            success = last_block.get("success", True)

            if not success:
                error = last_block.get("error", "Unknown error")
                parts.append(
                    f"Last output [FAILED]:\n{error}\n{output}"
                    if output
                    else f"Last output [FAILED]:\n{error}"
                )
            else:
                parts.append(f"Last output:\n{output}" if output else "Last output: (no output)")
        else:
            parts.append("No commands run yet - this is a fresh session.")

        # Directory tree
        cwd = context.get("cwd")
        if cwd:
            tree = _format_directory_tree(cwd)
            parts.append(f"\nProject structure:\n{tree}")

        # Reminder of available entities and output format
        parts.append(f"\n---\nAvailable to use:\n{self._format_entities(context)}")
        parts.append(f"\nPredict {self.num_suggestions} commands the user might run next.")
        parts.append('Respond with JSON only: {"suggestions": ["@...", "@...", "%..."]}')

        return "\n".join(parts)

    def _parse_input(self, input_data: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Parse input and build full message history.

        Overrides parent to:
        1. Build system prompt with available entities
        2. Build message history from blocks
        3. Add final context message

        Args:
            input_data: Context dict with blocks, nodes, etc.

        Returns:
            Tuple of (messages, extra_params)
        """
        if not isinstance(input_data, dict):
            logger.debug("SuggestionNode: non-dict input, using fallback")
            return [
                {
                    "role": "system",
                    "content": SUGGESTION_SYSTEM_PROMPT.format(entities="(none provided)"),
                },
                {
                    "role": "user",
                    "content": str(input_data) if input_data else "Suggest some commands",
                },
            ], {}

        # Log context summary
        nodes = input_data.get("nodes", [])
        graphs = input_data.get("graphs", [])
        workflows = input_data.get("workflows", [])
        blocks = input_data.get("blocks", [])
        cwd = input_data.get("cwd", "(none)")

        logger.debug(
            "SuggestionNode context: %d nodes, %d graphs, %d workflows, %d blocks, cwd=%s",
            len(nodes),
            len(graphs),
            len(workflows),
            len(blocks),
            cwd,
        )

        # Build system prompt with entities
        entities_str = self._format_entities(input_data)
        system_prompt = SUGGESTION_SYSTEM_PROMPT.format(entities=entities_str)

        # Start with system message
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # Build message history from blocks
        if blocks:
            history = self._build_message_history(blocks)
            messages.extend(history)
            logger.debug(
                "SuggestionNode: built %d messages from %d blocks", len(history), len(blocks)
            )

            # If there's history, the last message was a user message (output).
            # We need to add assistant prediction request, but actually
            # the last user message should be enriched with context.
            # Remove the last user message and replace with enriched version.
            if history and messages[-1]["role"] == "user":
                messages.pop()

        # Add final enriched context message
        final_message = self._format_final_context(input_data)
        messages.append({"role": "user", "content": final_message})

        logger.debug("SuggestionNode: total %d messages for LLM request", len(messages))

        return messages, {}

    def _parse_suggestions(self, content: str) -> list[str]:
        """Parse LLM response (JSON) into list of suggestions.

        Expected format: {"suggestions": ["@cmd1", "@cmd2", "%workflow"]}

        Falls back to line-by-line parsing if JSON fails.

        Args:
            content: Raw LLM response text (should be JSON).

        Returns:
            List of valid suggestion strings.
        """
        content = content.strip()

        # Try to extract JSON from markdown code blocks if present
        if "```" in content:
            # Extract content between ``` markers
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
            if match:
                content = match.group(1).strip()

        # Try JSON parsing
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "suggestions" in data:
                suggestions = data["suggestions"]
                if isinstance(suggestions, list):
                    # Filter to only @ and % commands
                    valid = [
                        s for s in suggestions if isinstance(s, str) and s.startswith(("@", "%"))
                    ]
                    logger.debug("SuggestionNode: parsed %d suggestions from JSON", len(valid))
                    return valid[: self.num_suggestions]
        except json.JSONDecodeError:
            logger.debug("SuggestionNode: JSON parse failed, falling back to line parsing")

        # Fallback: line-by-line parsing
        suggestions = []
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Remove common numbering patterns: "1.", "10.", "1)", "- ", "* "
            number_match = re.match(r"^\d+[.):\s]+", line)
            if number_match:
                line = line[number_match.end() :].strip()
            elif line and line[0] in "-*":
                line = line[1:].strip()

            # Only keep @ and % commands
            if line and line.startswith(("@", "%")):
                suggestions.append(line)

        logger.debug("SuggestionNode: parsed %d suggestions from fallback", len(suggestions))
        return suggestions[: self.num_suggestions]

    async def execute(self, context: Any) -> dict[str, Any]:
        """Execute suggestion generation.

        Calls parent execute() then parses suggestions from response.

        Args:
            context: ExecutionContext with input.

        Returns:
            Result dict with 'output' as list of suggestions.
        """
        logger.debug("SuggestionNode: executing suggestion request")

        # Call parent to get LLM response
        result = await super().execute(context)

        # Parse suggestions from output
        if result.get("success") and result.get("output"):
            raw_output = result["output"]
            suggestions = self._parse_suggestions(raw_output)
            result["output"] = suggestions
            # Defensive: ensure attributes dict exists (parent should always set it)
            if "attributes" not in result:
                result["attributes"] = {}
            result["attributes"]["raw_response"] = raw_output

            logger.debug("SuggestionNode: parsed %d suggestions from response", len(suggestions))
            for i, suggestion in enumerate(suggestions, 1):
                logger.debug("  Suggestion %d: %s", i, suggestion)
        else:
            error = result.get("error", "unknown error")
            logger.warning("SuggestionNode: request failed - %s", error)

        return result
