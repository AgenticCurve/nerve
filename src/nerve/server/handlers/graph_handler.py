"""GraphHandler - Handles graph execution and management.

Domain: Graph lifecycle and execution

State: _running_graphs (graph_id → task mapping)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.core.nodes import ExecutionContext
from nerve.server.protocols import Event, EventType

if TYPE_CHECKING:
    from nerve.core.nodes.graph import Graph
    from nerve.server.protocols import EventSink
    from nerve.server.session_registry import SessionRegistry
    from nerve.server.validation import ValidationHelpers


@dataclass
class GraphHandler:
    """Handles graph execution and management.

    Domain: Graph lifecycle and execution

    State: _running_graphs (graph_id → task mapping)
    """

    event_sink: EventSink
    validation: ValidationHelpers
    session_registry: SessionRegistry

    # Owned state: running graphs
    _running_graphs: dict[str, asyncio.Task[Any]] = field(default_factory=dict)

    async def create_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create and register a graph in a session.

        Parameters:
            graph_id: Graph ID (required)
            session_id: Session ID (optional, defaults to default session)

        Returns:
            {"graph_id": str}
        """
        from nerve.core.nodes.graph import Graph

        session = self.session_registry.get_session(params.get("session_id"))
        graph_id = self.validation.require_param(params, "graph_id")

        graph = Graph(id=graph_id, session=session)

        await self.event_sink.emit(
            Event(
                type=EventType.GRAPH_CREATED,
                data={"graph_id": graph_id},
            )
        )

        return {"graph_id": graph.id}

    async def delete_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete a graph from a session.

        Parameters:
            graph_id: Graph ID (required)
            session_id: Session ID (optional, defaults to default session)

        Returns:
            {"deleted": True}
        """
        session = self.session_registry.get_session(params.get("session_id"))
        graph_id = self.validation.require_param(params, "graph_id")

        deleted = session.delete_graph(graph_id)
        if not deleted:
            raise ValueError(f"Graph not found: {graph_id}")

        await self.event_sink.emit(
            Event(
                type=EventType.GRAPH_DELETED,
                data={"graph_id": graph_id},
            )
        )

        return {"deleted": True}

    async def execute_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a graph from step definitions.

        Creates a temporary graph, adds steps, and executes.

        Parameters:
            graph_id: Graph ID (optional, defaults to "graph_0")
            steps: List of step definitions (required)
            session_id: Session ID (optional)

        Returns:
            {"graph_id": str, "results": dict}
        """
        from nerve.core.nodes.graph import Graph

        session = self.session_registry.get_session(params.get("session_id"))
        graph_id = params.get("graph_id", "graph_0")

        # Validate steps parameter
        steps_data = params.get("steps")
        if steps_data is None or not isinstance(steps_data, list):
            raise ValueError(
                "Missing or invalid 'steps' parameter; expected a list of step definitions"
            )

        # Validate each step is a dict with required "id" key
        for i, step_data in enumerate(steps_data):
            if not isinstance(step_data, dict):
                raise ValueError(f"Step at index {i} is not a dict; expected step definition dict")
            if "id" not in step_data:
                raise ValueError(f"Step at index {i} missing required 'id' key")

        # Build Graph from step definitions
        graph = Graph(id=graph_id, session=session)

        for step_data in steps_data:
            step_id = step_data["id"]  # Safe now - validated above
            node_id = step_data.get("node_id")
            text = step_data.get("text", "")
            depends_on = step_data.get("depends_on", [])

            # Get the node for this step
            node = session.get_node(node_id)
            if not node:
                raise ValueError(f"Node not found: {node_id}")

            # Create step with input template
            graph.add_step(
                node=node,
                step_id=step_id,
                input=text,
                depends_on=depends_on,
            )

        # Create context with session
        context = ExecutionContext(session=session)

        return await self._stream_graph_execution(graph, context, graph_id)

    async def run_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run an existing registered graph.

        Parameters:
            graph_id: Graph ID (required)
            session_id: Session ID (optional, defaults to default session)
            input: Initial input for the graph (optional)

        Returns:
            {"graph_id": str, "results": dict}
        """
        session = self.session_registry.get_session(params.get("session_id"))
        graph_id = self.validation.require_param(params, "graph_id")
        initial_input = params.get("input")

        graph = self.validation.get_graph(session, graph_id)

        # Create context with session
        context = ExecutionContext(session=session, input=initial_input)

        return await self._stream_graph_execution(graph, context, graph_id)

    async def cancel_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cancel a running graph.

        Parameters:
            graph_id: Graph ID (required)

        Returns:
            {"cancelled": bool, "error": str|None}
        """
        graph_id = params["graph_id"]

        task = self._running_graphs.get(graph_id)
        if task:
            task.cancel()
            del self._running_graphs[graph_id]
            return {"cancelled": True}

        return {"cancelled": False, "error": "Graph not found"}

    async def list_graphs(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all graphs in a session.

        Parameters:
            session_id: Session ID (optional, defaults to default session)

        Returns:
            {"graphs": list}
        """
        session = self.session_registry.get_session(params.get("session_id"))
        graph_ids = session.list_graphs()

        graphs = []
        for gid in graph_ids:
            graph = session.get_graph(gid)
            if graph is not None:
                graphs.append(
                    {
                        "id": gid,
                        "step_count": len(graph.list_steps()),
                    }
                )

        return {"graphs": graphs}

    async def get_graph_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get graph metadata.

        Parameters:
            graph_id: Graph ID (required)
            session_id: Session ID (optional, defaults to default session)

        Returns:
            {"graph_id": str, "steps": list}
        """
        session = self.session_registry.get_session(params.get("session_id"))
        graph_id = self.validation.require_param(params, "graph_id")

        graph = self.validation.get_graph(session, graph_id)

        steps = []
        for step_id in graph.list_steps():
            step = graph.get_step(step_id)
            if step is not None:
                # Get node ID (from node_ref or from node.id)
                node_id = None
                if step.node_ref:
                    node_id = step.node_ref
                elif step.node:
                    node_id = step.node.id

                steps.append(
                    {
                        "id": step_id,
                        "node_id": node_id,
                        "input": step.input,
                        "depends_on": step.depends_on,
                    }
                )

        return {
            "graph_id": graph_id,
            "steps": steps,
        }

    # Methods for ServerHandler coordination

    @property
    def running_graph_count(self) -> int:
        """Number of currently running graphs."""
        return len(self._running_graphs)

    async def cancel_all_graphs(self) -> None:
        """Cancel all running graphs (used during server shutdown).

        Encapsulates _running_graphs access for ServerHandler.
        """
        for _graph_id, task in list(self._running_graphs.items()):
            task.cancel()
        self._running_graphs.clear()

    # Private helper

    async def _stream_graph_execution(
        self, graph: Graph, context: ExecutionContext, graph_id: str
    ) -> dict[str, Any]:
        """Execute graph with streaming events.

        Eliminates duplication between execute_graph and run_graph.

        Registers the current task so cancel_graph can find and cancel it.

        Args:
            graph: Graph to execute.
            context: Execution context.
            graph_id: Graph identifier for events.

        Returns:
            {"graph_id": str, "results": dict}
        """
        # Register current task for cancellation support
        current_task = asyncio.current_task()
        if current_task:
            self._running_graphs[graph_id] = current_task

        try:
            await self.event_sink.emit(
                Event(
                    type=EventType.GRAPH_STARTED,
                    data={"graph_id": graph_id},
                )
            )

            # Execute graph with streaming
            results = {}
            async for event in graph.execute_stream(context):
                if event.event_type == "step_start":
                    await self.event_sink.emit(
                        Event(
                            type=EventType.STEP_STARTED,
                            data={"step_id": event.step_id},
                        )
                    )
                elif event.event_type == "step_complete":
                    results[event.step_id] = event.data
                    await self.event_sink.emit(
                        Event(
                            type=EventType.STEP_COMPLETED,
                            data={"step_id": event.step_id, "output": str(event.data)[:500]},
                        )
                    )
                elif event.event_type == "step_error":
                    await self.event_sink.emit(
                        Event(
                            type=EventType.STEP_FAILED,
                            data={"step_id": event.step_id, "error": str(event.data)},
                        )
                    )

            await self.event_sink.emit(
                Event(
                    type=EventType.GRAPH_COMPLETED,
                    data={"graph_id": graph_id, "step_count": len(results)},
                )
            )

            return {
                "graph_id": graph_id,
                "results": {
                    step_id: {"output": str(output)[:500]} for step_id, output in results.items()
                },
            }
        finally:
            # Always clean up task registration
            self._running_graphs.pop(graph_id, None)
