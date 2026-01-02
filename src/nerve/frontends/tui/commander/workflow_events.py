"""Workflow event processing for TUI.

Handles processing of server events to update workflow step state.
Pure data transformation - no UI dependencies.

This module extracts event-processing logic from workflow_runner.py for better
separation of concerns and testability.
"""

from __future__ import annotations

from typing import Any

from nerve.frontends.tui.commander.workflow_state import StepInfo


def process_events(steps: list[StepInfo], events: list[dict[str, Any]]) -> None:
    """Process server events and update steps list in-place.

    Handles the following event types:
    - node_started, node_completed, node_error
    - graph_started, graph_completed, graph_error
    - nested_workflow_started, nested_workflow_completed, nested_workflow_error

    Args:
        steps: List of StepInfo objects to update (mutated in-place).
        events: List of server event dicts with 'event_type' and 'data' keys.

    Example:
        >>> steps = []
        >>> events = [{"event_type": "node_started", "data": {"node_id": "foo", "input": "hi"}}]
        >>> process_events(steps, events)
        >>> steps[0].node_id
        'foo'
    """
    for event in events:
        event_type = event.get("event_type", "")
        data = event.get("data", {})

        if event_type == "node_started":
            _handle_node_started(steps, data)

        elif event_type == "node_completed":
            _handle_node_completed(steps, data)

        elif event_type == "node_error":
            _handle_node_error(steps, data)

        elif event_type == "graph_started":
            _handle_graph_started(steps, data)

        elif event_type == "graph_completed":
            _handle_graph_completed(steps, data)

        elif event_type == "graph_error":
            _handle_graph_error(steps, data)

        elif event_type == "nested_workflow_started":
            _handle_nested_workflow_started(steps, data)

        elif event_type == "nested_workflow_completed":
            _handle_nested_workflow_completed(steps, data)

        elif event_type == "nested_workflow_error":
            _handle_nested_workflow_error(steps, data)


def _handle_node_started(steps: list[StepInfo], data: dict[str, Any]) -> None:
    """Handle node_started event."""
    node_id = data.get("node_id", "unknown")
    input_text = data.get("input", "")
    # Avoid duplicate if already tracking this node as running
    if any(s.node_id == node_id and s.status == "running" for s in steps):
        return
    steps.append(
        StepInfo(
            node_id=node_id,
            input_text=input_text,
            status="running",
        )
    )


def _handle_node_completed(steps: list[StepInfo], data: dict[str, Any]) -> None:
    """Handle node_completed event."""
    node_id = data.get("node_id", "")
    output_text = data.get("output", "")
    for step in reversed(steps):
        if step.node_id == node_id and step.status == "running":
            step.status = "completed"
            step.output_text = output_text
            break


def _handle_node_error(steps: list[StepInfo], data: dict[str, Any]) -> None:
    """Handle node_error event."""
    node_id = data.get("node_id", "")
    error = data.get("error", "Unknown error")
    for step in reversed(steps):
        if step.node_id == node_id and step.status == "running":
            step.status = "error"
            step.error = error
            break


def _handle_graph_started(steps: list[StepInfo], data: dict[str, Any]) -> None:
    """Handle graph_started event."""
    graph_id = data.get("graph_id", "unknown")
    input_text = data.get("input", "")
    # Avoid duplicate if already tracking this graph as running
    if any(s.node_id == graph_id and s.status == "running" for s in steps):
        return
    steps.append(
        StepInfo(
            node_id=f"[graph] {graph_id}",
            input_text=input_text,
            status="running",
        )
    )


def _handle_graph_completed(steps: list[StepInfo], data: dict[str, Any]) -> None:
    """Handle graph_completed event."""
    graph_id = data.get("graph_id", "")
    output_text = data.get("output", "")
    for step in reversed(steps):
        if step.node_id == f"[graph] {graph_id}" and step.status == "running":
            step.status = "completed"
            step.output_text = output_text
            break


def _handle_graph_error(steps: list[StepInfo], data: dict[str, Any]) -> None:
    """Handle graph_error event."""
    graph_id = data.get("graph_id", "")
    error = data.get("error", "Unknown error")
    for step in reversed(steps):
        if step.node_id == f"[graph] {graph_id}" and step.status == "running":
            step.status = "error"
            step.error = error
            break


def _handle_nested_workflow_started(steps: list[StepInfo], data: dict[str, Any]) -> None:
    """Handle nested_workflow_started event."""
    workflow_id = data.get("workflow_id", "unknown")
    input_text = data.get("input", "")
    # Avoid duplicate if already tracking this workflow as running
    if any(s.node_id == f"[workflow] {workflow_id}" and s.status == "running" for s in steps):
        return
    steps.append(
        StepInfo(
            node_id=f"[workflow] {workflow_id}",
            input_text=input_text,
            status="running",
        )
    )


def _handle_nested_workflow_completed(steps: list[StepInfo], data: dict[str, Any]) -> None:
    """Handle nested_workflow_completed event."""
    workflow_id = data.get("workflow_id", "")
    for step in reversed(steps):
        if step.node_id == f"[workflow] {workflow_id}" and step.status == "running":
            step.status = "completed"
            step.output_text = "(completed)"
            break


def _handle_nested_workflow_error(steps: list[StepInfo], data: dict[str, Any]) -> None:
    """Handle nested_workflow_error event."""
    workflow_id = data.get("workflow_id", "")
    error = data.get("error", "Unknown error")
    for step in reversed(steps):
        if step.node_id == f"[workflow] {workflow_id}" and step.status == "running":
            step.status = "error"
            step.error = error
            break
