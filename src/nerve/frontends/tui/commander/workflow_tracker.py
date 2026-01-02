"""Workflow tracking for Commander TUI.

Handles tracking and polling of backgrounded workflow runs.
Updates block status when workflows complete and provides status info.

This module extracts workflow-tracking logic from commander.py for better
separation of concerns and testability.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.frontends.cli.repl.adapters import RemoteSessionAdapter
    from nerve.frontends.tui.commander.blocks import Timeline

logger = logging.getLogger(__name__)


@dataclass
class WorkflowTracker:
    """Tracks backgrounded workflow runs and polls for status updates.

    Manages a collection of active workflow runs, polling the server
    periodically to update their status. When workflows complete,
    updates the associated blocks in the timeline.

    Example:
        >>> tracker = WorkflowTracker(timeline=timeline)
        >>> tracker.adapter = adapter  # Set after connection
        >>> tracker.track(run_id, {"workflow_id": "wf1", "block_number": 1, ...})
        >>> tracker.start_polling()
    """

    # Timeline reference for updating blocks
    timeline: Timeline

    # Server connection (set after connection established)
    adapter: RemoteSessionAdapter | None = field(default=None)

    # Active workflow runs: run_id -> workflow info dict
    active: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Background polling task
    _poll_task: asyncio.Task[None] | None = field(default=None, init=False)

    # Polling interval in seconds
    poll_interval: float = field(default=3.0, init=False)

    def track(
        self,
        run_id: str,
        workflow_id: str,
        block_number: int,
        events: list[Any] | None = None,
        pending_gate: dict[str, Any] | None = None,
        start_time: float = 0,
        steps: list[Any] | None = None,
    ) -> None:
        """Add a workflow run to tracking.

        Args:
            run_id: Unique identifier for the workflow run.
            workflow_id: The workflow definition ID.
            block_number: Block number in timeline associated with this run.
            events: Initial events from the workflow.
            pending_gate: Any pending gate information.
            start_time: When the workflow started.
            steps: Workflow steps information.
        """
        self.active[run_id] = {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "block_number": block_number,
            "events": events or [],
            "pending_gate": pending_gate,
            "start_time": start_time,
            "steps": steps or [],
        }

    def untrack(self, run_id: str) -> None:
        """Remove a workflow run from tracking.

        Args:
            run_id: The workflow run ID to stop tracking.
        """
        if run_id in self.active:
            del self.active[run_id]

    def get_active_count(self) -> int:
        """Get the number of active workflow runs.

        Returns:
            Count of currently tracked workflows.
        """
        return len(self.active)

    def get_waiting_gates_count(self) -> int:
        """Get the number of workflows with pending gates.

        Returns:
            Count of workflows that have a pending gate.
        """
        return sum(1 for wf in self.active.values() if wf.get("pending_gate") is not None)

    def start_polling(self) -> None:
        """Start background polling for active workflows if not already running.

        Polling fetches fresh workflow state from the server periodically,
        updating active workflows so the status bar shows accurate info.
        """
        if self._poll_task is not None and not self._poll_task.done():
            return  # Already polling

        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        """Background task that polls workflow status periodically.

        Updates active workflows with fresh state and pending_gate info.
        Removes completed/failed workflows from tracking.
        Stops when no more active workflows.
        """
        while self.active and self.adapter is not None:
            try:
                # Poll each active workflow
                completed_runs: list[str] = []

                for run_id, wf_info in list(self.active.items()):
                    try:
                        status = await self.adapter.get_workflow_run(run_id)

                        if status:
                            state = status.get("state", "unknown")

                            # Update workflow info with fresh data
                            wf_info["state"] = state
                            wf_info["pending_gate"] = status.get("pending_gate")
                            wf_info["events"] = status.get("events", [])

                            # If workflow completed, update block and remove from active
                            if state in ("completed", "failed", "cancelled"):
                                completed_runs.append(run_id)

                                # Update the associated block
                                block_num = wf_info.get("block_number")
                                if block_num is not None:
                                    block = self.timeline.get(block_num)
                                    if block:
                                        if state == "completed":
                                            block.status = "completed"
                                            block.output_text = str(status.get("result", ""))
                                        else:
                                            block.status = "error"
                                            block.error = status.get("error", f"Workflow {state}")
                                        block.raw = status

                    except Exception as e:
                        logger.debug("Failed to poll workflow %s: %s", run_id, e)

                # Remove completed workflows from tracking
                for run_id in completed_runs:
                    del self.active[run_id]

                # Sleep before next poll
                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Workflow polling error: %s", e)
                await asyncio.sleep(self.poll_interval)

    async def stop_polling(self) -> None:
        """Stop the background polling task."""
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

    async def cleanup(self) -> None:
        """Cleanup: stop polling and cancel all active workflows.

        Should be called when Commander is shutting down.
        Cancels all tracked workflows on the server.
        """
        # Stop polling first
        await self.stop_polling()

        # Cancel any active (backgrounded) workflows
        if self.active and self.adapter is not None:
            for run_id in list(self.active.keys()):
                try:
                    await self.adapter.cancel_workflow(run_id)
                    logger.debug("Cancelled workflow %s on exit", run_id)
                except Exception as e:
                    logger.debug("Failed to cancel workflow %s: %s", run_id, e)
            self.active.clear()
