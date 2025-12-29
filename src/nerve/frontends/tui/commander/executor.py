"""Async execution engine for Commander TUI.

Provides unified threshold-based async execution pattern:
- Fast operations (< threshold): Execute synchronously, render immediately
- Slow operations (>= threshold): Show pending state, execute in background

This eliminates code duplication between node and Python execution handlers.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rich.console import Console

from nerve.frontends.tui.commander.blocks import Block, Timeline
from nerve.frontends.tui.commander.rendering import print_block

if TYPE_CHECKING:
    from nerve.frontends.cli.repl.adapters import RemoteSessionAdapter


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

    # Internal queue for background tasks
    # Items: (block, task) where task is already running
    _command_queue: asyncio.Queue[tuple[Block, asyncio.Task[None]]] = field(init=False)
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

        try:
            exec_task: asyncio.Task[None] = asyncio.create_task(execute_fn())

            await asyncio.wait_for(
                asyncio.shield(exec_task),  # shield so we can continue if timeout
                timeout=threshold_seconds,
            )

            # Fast path: completed within threshold, render result
            self.timeline.render_last(self.console)

        except TimeoutError:
            # Slow path: show pending and queue for background completion
            block.status = "pending"
            self.timeline.render_last(self.console)

            # Queue the ongoing task for the executor to monitor
            await self._command_queue.put((block, exec_task))

    async def _background_executor(self) -> None:
        """Background task that processes commands from the queue.

        Waits for ongoing tasks that exceeded the async threshold,
        then renders the completed block.
        """
        while True:
            try:
                # Wait for next item (block, task)
                block, task = await self._command_queue.get()

                try:
                    # Ongoing task - wait for it to complete
                    # The task is already running and will update the block
                    block.status = "running"
                    await task

                except Exception as e:
                    # Handle unexpected errors
                    block.status = "error"
                    block.error = f"{type(e).__name__}: {e}"

                # Render the completed block
                print_block(self.console, block)

                self._command_queue.task_done()

            except asyncio.CancelledError:
                break


def get_block_type(node_type: str) -> str:
    """Determine block type from node type string.

    Args:
        node_type: Node type name from server (e.g., "BashNode", "LLMChatNode").

    Returns:
        Block type for rendering ("bash", "llm", or "node").
    """
    node_type_lower = node_type.lower()
    if "bash" in node_type_lower:
        return "bash"
    elif "llm" in node_type_lower or "chat" in node_type_lower:
        return "llm"
    else:
        return "node"


async def execute_node_command(
    adapter: RemoteSessionAdapter,
    block: Block,
    text: str,
    start_time: float,
    set_active_node: Callable[[str | None], None],
) -> None:
    """Execute a node command and update the block with results.

    Args:
        adapter: Session adapter for server communication.
        block: The block to update with results.
        text: The input text (already expanded by caller).
        start_time: When execution started (for duration calculation).
        set_active_node: Callback to set/clear active node ID for interrupt support.
    """
    node_id = block.node_id
    if not node_id:
        block.status = "error"
        block.error = "No node ID"
        block.duration_ms = (time.monotonic() - start_time) * 1000
        return

    # Track active node for interrupt support
    set_active_node(node_id)

    try:
        result = await adapter.execute_on_node(node_id, text)
    finally:
        set_active_node(None)

    duration_ms = (time.monotonic() - start_time) * 1000

    # Update block with results
    if result.get("success"):
        block.status = "completed"
        block.output_text = str(result.get("output", "")).strip()
        block.raw = result
        block.error = None
    else:
        block.status = "error"
        error_msg = result.get("error", "Unknown error")
        error_type = result.get("error_type", "unknown")
        block.error = f"[{error_type}] {error_msg}"
        block.raw = result

    block.duration_ms = duration_ms


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
