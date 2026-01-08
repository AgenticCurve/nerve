"""Async execution engine for Commander TUI.

Provides unified threshold-based async execution pattern:
- Fast operations (< threshold): Execute synchronously, render immediately
- Slow operations (>= threshold): Show pending state, execute in background

This eliminates code duplication between node and Python execution handlers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rich.console import Console

from nerve.frontends.tui.commander.blocks import Block, BlockType, Timeline
from nerve.frontends.tui.commander.rendering import print_block
from nerve.frontends.tui.commander.result_handler import update_block_from_result

if TYPE_CHECKING:
    from nerve.frontends.cli.repl.adapters import RemoteSessionAdapter

logger = logging.getLogger(__name__)


@dataclass
class CommandExecutor:
    """Manages async command execution with threshold-based background queueing.

    Provides a unified pattern for executing commands with a time threshold:
    - Fast operations (< threshold): Execute synchronously, render immediately
    - Slow operations (>= threshold): Show pending state, queue for background

    Example:
        executor = CommandExecutor(timeline, console)
        await executor.start()

        # Execute with threshold
        await executor.execute_with_threshold(
            block=block,
            execute_fn=lambda: adapter.execute_on_node(node_id, text),
            result_handler=lambda result: update_block(block, result),
        )

        await executor.stop()
    """

    timeline: Timeline
    console: Console
    async_threshold_ms: float = 200
    on_block_complete: Callable[[Block], None] | None = None  # Callback when any block completes

    # Internal queue for background tasks
    # Items: (block, task, start_time) where task is already running
    # start_time is None for dependency-wait tasks (execution hasn't started yet)
    _command_queue: asyncio.Queue[tuple[Block, asyncio.Task[None], float | None]] = field(
        init=False
    )
    _executor_task: asyncio.Task[None] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Initialize command queue."""
        self._command_queue = asyncio.Queue()

    async def start(self) -> None:
        """Start the background executor task."""
        self._executor_task = asyncio.create_task(self._background_executor())

    async def stop(self) -> None:
        """Stop the background executor."""
        if self._executor_task:
            self._executor_task.cancel()
            try:
                await self._executor_task
            except asyncio.CancelledError:
                pass
            self._executor_task = None

    async def execute_with_threshold(
        self,
        block: Block,
        execute_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """Execute a command with async threshold handling.

        The execute_fn should:
        1. Perform the actual execution
        2. Update block.status, block.output_text, block.error, block.duration_ms

        Args:
            block: The block to update (must already be added to timeline).
            execute_fn: Async function that executes the command and updates block.
        """
        threshold_seconds = self.async_threshold_ms / 1000

        # If block has dependencies, check if they're already ready
        if block.depends_on:
            # Check if dependencies are already complete
            all_ready = True
            for dep_num in block.depends_on:
                # Bounds check
                if dep_num >= len(self.timeline.blocks):
                    all_ready = False
                    break

                dep_block = self.timeline.blocks[dep_num]
                if dep_block.status not in ("completed", "error"):
                    all_ready = False
                    break

            # If dependencies are NOT ready, queue for background waiting
            if not all_ready:
                block.status = "waiting"
                # Don't render here - wait_for_dependencies will render when it starts

                # Create wrapper that waits for dependencies then executes
                async def wait_and_execute() -> None:
                    dependencies_ready = await self.wait_for_dependencies(block)

                    # If dependency wait failed (returned False), stop here
                    if not dependencies_ready:
                        return

                    # Dependencies ready - now execute
                    await execute_fn()

                # Queue the wait+execute task for background processing
                # start_time=None because execution hasn't started yet (execute_fn handles timing)
                wait_task: asyncio.Task[None] = asyncio.create_task(wait_and_execute())
                await self._command_queue.put((block, wait_task, None))
                return  # Return immediately - don't block main loop!

            # Dependencies ARE ready - fall through to normal execution below

        # No dependencies (or dependencies already ready) - use threshold-based execution (fast path or background queue)
        # Capture start_time before task creation for accurate duration on error fallback
        exec_start_time = time.monotonic()
        try:
            exec_task: asyncio.Task[None] = asyncio.create_task(execute_fn())

            await asyncio.wait_for(
                asyncio.shield(exec_task),  # shield so we can continue if timeout
                timeout=threshold_seconds,
            )

            # Fast path: completed within threshold, render result
            self.timeline.render_last(self.console)

            # Notify callback if set (defensive - catch exceptions to prevent crash)
            if self.on_block_complete is not None:
                try:
                    self.on_block_complete(block)
                except Exception:
                    logger.exception("Error in on_block_complete callback")

        except TimeoutError:
            # Slow path: show pending and queue for background completion
            block.status = "pending"
            block.was_async = True  # Mark as async for visual indicator on completion
            self.timeline.render_last(self.console)

            # Queue the ongoing task for the executor to monitor (with start_time for error fallback)
            await self._command_queue.put((block, exec_task, exec_start_time))

    async def wait_for_dependencies(self, block: Block) -> bool:
        """Wait for all dependency blocks to complete.

        Polls every 100ms until all referenced blocks are in 'completed'
        or 'error' state. Sets block status to 'waiting' while waiting.

        Fails with timeout error if dependencies don't complete within 5 minutes.

        Args:
            block: The block waiting for dependencies.

        Returns:
            True if dependencies are ready (status set to "pending"),
            False if an error occurred (status set to "error").
        """
        # Validate dependencies: no self-reference or forward references
        invalid_refs = [dep for dep in block.depends_on if dep >= block.number]
        if invalid_refs:
            block.status = "error"
            block.error = (
                f"Invalid block reference(s): {invalid_refs}. "
                f"Block :::{block.number} cannot reference itself or future blocks "
                f"(valid range: :::0 to :::{block.number - 1})"
            )
            self.timeline.render_last(self.console)
            return False

        # Check if dependencies are already ready BEFORE showing waiting status
        all_ready = True
        for dep_num in block.depends_on:
            # Bounds check
            if dep_num >= len(self.timeline.blocks):
                all_ready = False
                break

            dep_block = self.timeline.blocks[dep_num]

            # Wait for completed or error (both mean "done")
            if dep_block.status not in ("completed", "error"):
                all_ready = False
                break

        # If already ready, just set to pending and return (no render needed)
        if all_ready:
            block.status = "pending"
            return True

        # Show waiting status ONLY if we actually need to wait
        block.status = "waiting"
        self.timeline.render_last(self.console)

        # Timeout after 40 minutes to prevent infinite wait
        timeout_seconds = 2400  # 40 minutes
        start_time = time.monotonic()

        while True:
            # Check timeout
            elapsed = time.monotonic() - start_time
            if elapsed > timeout_seconds:
                block.status = "error"
                block.error = (
                    f"Timeout waiting for dependencies {list(block.depends_on)}. "
                    f"Waited {timeout_seconds}s but dependencies did not complete."
                )
                self.timeline.render_last(self.console)
                return False

            all_ready = True
            for dep_num in block.depends_on:
                # Bounds check (defensive - should not trigger after validation)
                if dep_num >= len(self.timeline.blocks):
                    all_ready = False
                    break

                dep_block = self.timeline.blocks[dep_num]

                # Wait for completed or error (both mean "done")
                if dep_block.status not in ("completed", "error"):
                    all_ready = False
                    break

            if all_ready:
                # All dependencies ready - reset to pending for execution
                block.status = "pending"
                return True

            # Wait 100ms before checking again
            await asyncio.sleep(0.1)

    async def _background_executor(self) -> None:
        """Background task that processes commands from the queue.

        Spawns concurrent monitoring tasks for each command, allowing
        multiple nodes to execute in parallel without blocking each other.
        """
        monitoring_tasks: set[asyncio.Task[None]] = set()

        while True:
            try:
                # Wait for next item (block, task, start_time)
                block, task, start_time = await self._command_queue.get()

                # Spawn a monitoring task for this command (allows concurrent execution)
                monitor = asyncio.create_task(self._monitor_task(block, task, start_time))
                monitoring_tasks.add(monitor)

                # Clean up completed monitoring tasks
                monitoring_tasks = {t for t in monitoring_tasks if not t.done()}

                self._command_queue.task_done()

            except asyncio.CancelledError:
                # Cancel all monitoring tasks
                for t in monitoring_tasks:
                    t.cancel()
                break

    async def _monitor_task(
        self, block: Block, task: asyncio.Task[None], start_time: float | None
    ) -> None:
        """Monitor a single command task and render when complete.

        Args:
            block: The block to update and render.
            task: The already-running execution task.
            start_time: When execution started (for error duration fallback).
                None for dependency-wait tasks where execute_fn handles timing.
        """
        try:
            # Ongoing task - wait for it to complete
            # The task is already running and will update the block
            await task

        except Exception as e:
            # Handle unexpected errors
            block.status = "error"
            block.error = f"{type(e).__name__}: {e}"
            # Ensure duration is set even for unexpected exceptions
            # Only use start_time fallback if provided (not for dependency-wait tasks)
            if block.duration_ms is None and start_time is not None:
                block.duration_ms = (time.monotonic() - start_time) * 1000

        # Render the completed block (only render once at the end)
        print_block(self.console, block)

        # Notify callback if set (defensive - catch exceptions to prevent crash)
        if self.on_block_complete is not None:
            try:
                self.on_block_complete(block)
            except Exception:
                logger.exception("Error in on_block_complete callback")


def get_block_type(node_type: str) -> BlockType:
    """Determine block type from node/graph/workflow type string.

    Args:
        node_type: Node, graph, or workflow type name
            (e.g., "BashNode", "LLMChatNode", "graph", "workflow").

    Returns:
        Block type for rendering ("bash", "llm", "graph", "workflow", or "node").
    """
    node_type_lower = node_type.lower()
    if node_type_lower == "graph":
        return "graph"
    elif node_type_lower == "workflow":
        return "workflow"
    elif "bash" in node_type_lower:
        return "bash"
    elif "llm" in node_type_lower or "chat" in node_type_lower:
        return "llm"
    else:
        return "node"


async def execute_node_command(
    adapter: RemoteSessionAdapter,
    block: Block,
    input_data: str | dict[str, Any],
    start_time: float,
    set_active_node: Callable[[str | None], None],
) -> None:
    """Execute a node command and update the block with results.

    Args:
        adapter: Session adapter for server communication.
        block: The block to update with results.
        input_data: The input (text for regular nodes, dict for multi-tool nodes).
        start_time: When execution started (for duration calculation).
        set_active_node: Callback to set/clear active node ID for interrupt support.
    """
    import json

    node_id = block.node_id
    if not node_id:
        block.status = "error"
        block.error = "No node ID"
        block.duration_ms = (time.monotonic() - start_time) * 1000
        return

    # Serialize dict input to JSON string for transport
    if isinstance(input_data, dict):
        text = json.dumps(input_data)
    else:
        text = input_data

    # Track active node for interrupt support
    set_active_node(node_id)

    try:
        result = await adapter.execute_on_node(node_id, text)
    finally:
        set_active_node(None)

    duration_ms = (time.monotonic() - start_time) * 1000

    # DEFENSIVE: Verify block.node_id hasn't changed (concurrent modification check)
    if block.node_id != node_id:
        block.status = "error"
        block.error = f"Block node_id changed during execution: {node_id} -> {block.node_id}"
        block.duration_ms = duration_ms
        return

    # DEFENSIVE: Verify result came from the correct node (if metadata available)
    executed_on = result.get("_executed_on_node_id")
    if executed_on and executed_on != node_id:
        block.status = "error"
        block.error = (
            f"Result mismatch! Expected from '{node_id}' but got from '{executed_on}'. "
            f"This indicates a serious bug in concurrent execution."
        )
        block.duration_ms = duration_ms
        return

    # Update block with results
    update_block_from_result(
        block,
        result,
        duration_ms,
        metadata={
            "executed_node_id": node_id,
            "executed_pane_id": result.get("_executed_on_pane_id", "unknown"),
        },
    )


async def execute_graph_command(
    adapter: RemoteSessionAdapter,
    block: Block,
    graph_id: str,
    text: str,
    start_time: float,
) -> None:
    """Execute a graph and update the block with results.

    Args:
        adapter: Session adapter for server communication.
        block: The block to update with results.
        graph_id: ID of the graph to execute.
        text: The input text (already expanded by caller).
        start_time: When execution started (for duration calculation).
    """
    if not graph_id:
        block.status = "error"
        block.error = "No graph ID"
        block.duration_ms = (time.monotonic() - start_time) * 1000
        return

    try:
        result = await adapter.execute_graph(graph_id, input=text if text else None)
    except Exception as e:
        block.status = "error"
        block.error = f"{type(e).__name__}: {e}"
        block.duration_ms = (time.monotonic() - start_time) * 1000
        return

    duration_ms = (time.monotonic() - start_time) * 1000

    # Update block with results (identical to node handling for transparency)
    update_block_from_result(
        block,
        result,
        duration_ms,
        metadata={"executed_graph_id": graph_id},
    )


async def execute_python_command(
    adapter: RemoteSessionAdapter,
    block: Block,
    code: str,
    start_time: float,
) -> None:
    """Execute a Python command and update the block with results.

    Args:
        adapter: Session adapter for server communication.
        block: The block to update with results.
        code: The Python code to execute.
        start_time: When execution started (for duration calculation).
    """
    try:
        output, error = await adapter.execute_python(code, {})
    except Exception as e:
        block.status = "error"
        block.error = f"{type(e).__name__}: {e}"
        block.duration_ms = (time.monotonic() - start_time) * 1000
        return

    duration_ms = (time.monotonic() - start_time) * 1000

    if error:
        block.status = "error"
        block.error = error
    else:
        block.status = "completed"
        block.output_text = output.strip() if output else ""

    block.duration_ms = duration_ms
