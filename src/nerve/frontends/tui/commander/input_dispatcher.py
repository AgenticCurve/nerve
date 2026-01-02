"""Input dispatching for Commander TUI.

Handles routing user input to appropriate handlers (entities, workflows, Python).
Validates variable references and manages block creation and execution.

This module extracts input-handling logic from commander.py for better
separation of concerns and testability.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.frontends.tui.commander.blocks import Block, BlockType
    from nerve.frontends.tui.commander.commander import Commander


@dataclass
class InputDispatcher:
    """Dispatches user input to appropriate handlers.

    Routes input based on prefix (@, %, >>>, :) and current world state.
    Handles validation, block creation, and execution coordination.

    Uses a back-reference to Commander for access to shared state and delegates.

    Example:
        >>> dispatcher = InputDispatcher(commander)
        >>> await dispatcher.dispatch("@claude Hello!")
    """

    commander: Commander

    def _validate_and_create_error_block(
        self, text: str, block_type: BlockType, node_id: str | None
    ) -> Block | None:
        """Validate variable references and return error block if invalid.

        Checks for unresolvable references (:::nav when nav has no blocks, etc.)
        and creates an error block if validation fails.

        Args:
            text: Text with potential variable references.
            block_type: Type for the error block if created.
            node_id: Node ID for the error block if created.

        Returns:
            None if validation passes, otherwise the error block
            (already added to timeline and rendered).
        """
        from nerve.frontends.tui.commander.blocks import Block
        from nerve.frontends.tui.commander.rendering import print_block
        from nerve.frontends.tui.commander.variables import validate_variable_references

        cmd = self.commander
        errors = validate_variable_references(text, cmd.timeline, cmd._entities.get_nodes_by_type())
        if not errors:
            return None

        block = Block(
            block_type=block_type,
            node_id=node_id,
            input_text=text,
            status="error",
            error=errors[0],
        )
        cmd.timeline.add(block)
        print_block(cmd.console, block)
        return block

    async def dispatch(self, user_input: str) -> None:
        """Handle user input and dispatch to appropriate handler.

        Routes based on input prefix:
        - ":" → command dispatch
        - "@" → entity message (node/graph)
        - "%" → workflow execution
        - ">>>" → Python code
        - (in world) → route to current world

        Note: Suggestion refresh is triggered via on_block_complete callback
        for commands that create blocks. Only : commands need explicit trigger.

        Args:
            user_input: The trimmed user input string.
        """
        from nerve.frontends.tui.commander.commands import dispatch_command

        cmd = self.commander

        # Commands always start with : (works in any world)
        if user_input.startswith(":"):
            await dispatch_command(cmd, user_input[1:])
            # : commands don't create blocks, so trigger suggestions manually
            cmd._suggestions.trigger_fetch()

        # If in a world, route directly to that node
        elif cmd._current_world:
            if cmd._current_world == "python":
                await self.handle_python(user_input)
            else:
                await self.handle_entity_message(f"{cmd._current_world} {user_input}")

        # Node/graph messages start with @
        elif user_input.startswith("@"):
            await self.handle_entity_message(user_input[1:])

        # Workflow execution starts with %
        elif user_input.startswith("%"):
            await self.handle_workflow(user_input[1:])

        # Python code starts with >>>
        elif user_input.startswith(">>>"):
            await self.handle_python(user_input[3:].strip())

        # Default: show help
        else:
            cmd.console.print(
                "[dim]Prefix with @node to send to a node, "
                "%workflow for workflows, >>> for Python, or :help[/]"
            )

    async def handle_entity_message(self, message: str) -> None:
        """Handle @entity_name message syntax for both nodes and graphs.

        Args:
            message: The message after the @ prefix (e.g., "claude Hello!").
        """
        from nerve.frontends.tui.commander.blocks import Block
        from nerve.frontends.tui.commander.executor import (
            execute_graph_command,
            execute_node_command,
            get_block_type,
        )
        from nerve.frontends.tui.commander.variables import (
            expand_variables,
            extract_block_dependencies,
        )

        cmd = self.commander

        if cmd._adapter is None:
            cmd.console.print("[error]Not connected to server[/]")
            return

        parts = message.split(maxsplit=1)
        if not parts:
            cmd.console.print("[warning]Usage: @entity_name message[/]")
            return

        entity_id = parts[0]
        text = parts[1] if len(parts) > 1 else ""

        # Special handling for @suggestions - auto-gather context
        if entity_id == "suggestions" and not text:
            context = cmd._suggestions._gather_context()
            text = json.dumps(context)

        if not text:
            cmd.console.print(f"[warning]No message provided for @{entity_id}[/]")
            return

        if entity_id not in cmd.entities:
            await cmd._entities.sync()
            if entity_id not in cmd.entities:
                cmd.console.print(f"[error]Entity not found: {entity_id}[/]")
                cmd.console.print(f"[dim]Available: {', '.join(cmd.entities.keys()) or 'none'}[/]")
                return

        entity = cmd.entities[entity_id]
        block_type = get_block_type(entity.node_type)

        # Validate variable references before proceeding (fail fast on unresolvable refs)
        if self._validate_and_create_error_block(text, block_type, entity_id):
            return

        # DON'T expand variables yet - detect dependencies first
        dependencies = extract_block_dependencies(
            text, cmd.timeline, cmd._entities.get_nodes_by_type()
        )

        # Create block with dependency info (input_text stores RAW text)
        block = Block(
            block_type=block_type,
            node_id=entity_id,  # Works for both nodes and graphs
            input_text=text,
            depends_on=dependencies,
        )
        cmd.timeline.add(block)

        # Execute with threshold handling
        start_time = time.monotonic()

        # IMPORTANT: Variable expansion happens INSIDE execute function
        # This ensures dependencies are completed before expansion
        async def execute() -> None:
            # By this point, execute_with_threshold has waited for dependencies
            # Pass block.number to exclude current block from negative index resolution
            expanded_text = expand_variables(
                cmd.timeline,
                text,
                cmd._entities.get_nodes_by_type(),
                exclude_block_from=block.number,
            )

            # Route based on entity type
            if entity.type == "graph":
                await execute_graph_command(
                    cmd._adapter,  # type: ignore[arg-type]
                    block,
                    entity_id,
                    expanded_text,
                    start_time,
                )
            else:
                await execute_node_command(
                    cmd._adapter,  # type: ignore[arg-type]
                    block,
                    expanded_text,
                    start_time,
                    cmd._set_active_node,
                )

        await cmd._executor.execute_with_threshold(block, execute)

    async def handle_python(self, code: str) -> None:
        """Handle Python code execution with threshold-based async.

        Args:
            code: Python code to execute.
        """
        from nerve.frontends.tui.commander.blocks import Block
        from nerve.frontends.tui.commander.executor import execute_python_command
        from nerve.frontends.tui.commander.variables import extract_block_dependencies

        cmd = self.commander

        if not code:
            cmd.console.print("[dim]Enter Python code after >>>[/]")
            return

        if cmd._adapter is None:
            cmd.console.print("[error]Not connected to server[/]")
            return

        # Validate variable references before proceeding (fail fast on unresolvable refs)
        if self._validate_and_create_error_block(code, "python", None):
            return

        # Detect dependencies (Python code can reference blocks and nodes)
        dependencies = extract_block_dependencies(
            code, cmd.timeline, cmd._entities.get_nodes_by_type()
        )

        # Create block with dependency info
        block = Block(
            block_type="python",
            node_id=None,
            input_text=code,
            depends_on=dependencies,
        )
        cmd.timeline.add(block)

        # Execute with threshold handling
        start_time = time.monotonic()

        async def execute() -> None:
            await execute_python_command(
                cmd._adapter,  # type: ignore[arg-type]
                block,
                code,
                start_time,
            )

        await cmd._executor.execute_with_threshold(block, execute)

    async def handle_workflow(self, message: str) -> None:
        """Handle %workflow_id input syntax for workflow execution.

        Workflows run in a dedicated full-screen TUI that:
        - Shows workflow state, events, and progress
        - Handles gates with interactive prompts
        - Returns result to store in the block

        NOTE: The workflow TUI is a separate prompt_toolkit Application that
        takes over the terminal, but does NOT stop the Commander's background
        executor. Any in-progress blocks continue executing while workflow runs.

        Args:
            message: The message after the % prefix (e.g., "my_workflow input").
        """
        from nerve.frontends.tui.commander.blocks import Block
        from nerve.frontends.tui.commander.rendering import print_block
        from nerve.frontends.tui.commander.variables import (
            expand_variables,
            extract_block_dependencies,
        )
        from nerve.frontends.tui.commander.workflow_runner import run_workflow_tui

        cmd = self.commander

        if cmd._adapter is None:
            cmd.console.print("[error]Not connected to server[/]")
            return

        parts = message.split(maxsplit=1)
        if not parts:
            cmd.console.print("[warning]Usage: %workflow_id input[/]")
            return

        workflow_id = parts[0]
        input_text = parts[1] if len(parts) > 1 else ""

        # Check if workflow exists
        if workflow_id not in cmd.entities:
            await cmd._entities.sync()
            if workflow_id not in cmd.entities:
                cmd.console.print(f"[error]Workflow not found: {workflow_id}[/]")
                # List available workflows
                workflows = [e.id for e in cmd.entities.values() if e.type == "workflow"]
                if workflows:
                    cmd.console.print(f"[dim]Available workflows: {', '.join(workflows)}[/]")
                else:
                    cmd.console.print("[dim]No workflows registered[/]")
                return

        entity = cmd.entities[workflow_id]
        if entity.type != "workflow":
            cmd.console.print(f"[error]'{workflow_id}' is a {entity.type}, not a workflow[/]")
            cmd.console.print("[dim]Use @ for nodes/graphs, % for workflows[/]")
            return

        # Validate variable references before proceeding (fail fast on unresolvable refs)
        if self._validate_and_create_error_block(input_text, "workflow", workflow_id):
            return

        # Extract dependencies from input (for :::N references)
        dependencies = extract_block_dependencies(
            input_text, cmd.timeline, cmd._entities.get_nodes_by_type()
        )

        # Create block for workflow (stores raw input)
        block = Block(
            block_type="workflow",
            node_id=workflow_id,
            input_text=input_text,
            depends_on=dependencies,
        )
        cmd.timeline.add(block)

        # Wait for dependencies before expanding variables
        # This ensures :::N references see completed block data
        if dependencies:
            block.status = "waiting"
            print_block(cmd.console, block)
            dependencies_ready = await cmd._executor.wait_for_dependencies(block)

            # If dependency wait failed (returned False), stop here
            if not dependencies_ready:
                print_block(cmd.console, block)
                return

        # NOW expand variables - dependencies are complete
        expanded_input = expand_variables(
            cmd.timeline,
            input_text,
            cmd._entities.get_nodes_by_type(),
            exclude_block_from=block.number,
        )

        # Launch full-screen workflow TUI
        # This takes over the screen until workflow completes
        result = await run_workflow_tui(
            cmd._adapter,
            workflow_id,
            expanded_input,
        )

        # Update block with result
        block.duration_ms = result.get("duration_ms", 0)

        if result.get("backgrounded"):
            # Workflow was backgrounded - track it for resume
            block.status = "pending"  # Mark as pending since still running
            block.output_text = "(backgrounded - use :wf to resume)"
            block.raw = result
            run_id = result.get("run_id", "")
            if run_id:
                cmd._workflows.track(
                    run_id=run_id,
                    workflow_id=workflow_id,
                    block_number=block.number,
                    events=result.get("events", []),
                    pending_gate=result.get("pending_gate"),
                    start_time=result.get("start_time", 0),
                    steps=result.get("steps", []),
                )
            cmd.console.print(
                f"[dim]Workflow backgrounded. Use :world to list or :world {run_id[:8]} to resume[/]"
            )
            # Start background polling for status updates
            cmd._workflows.start_polling()
        else:
            # Handle completed, cancelled, or failed states
            if result.get("state") == "completed":
                block.status = "completed"
                block.output_text = str(result.get("result", ""))
                block.raw = result
            elif result.get("state") == "cancelled":
                block.status = "error"
                block.error = "Workflow cancelled"
                block.raw = result
            else:
                block.status = "error"
                block.error = result.get("error", "Workflow failed")
                block.raw = result

            print_block(cmd.console, block)
