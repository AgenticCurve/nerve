"""Session - central workspace abstraction for nodes and graphs.

Session is the central workspace that:
- Registers and manages nodes
- Stores and manages graphs
- Manages lifecycle (start/stop)

Example:
    >>> from nerve.core.nodes import PTYNode, BashNode, Graph, FunctionNode
    >>> session = Session(name="my-project")
    >>>
    >>> # Create nodes (auto-registered on creation)
    >>> claude = await PTYNode.create(id="claude", session=session, command="claude")
    >>> bash = BashNode(id="shell", session=session)
    >>>
    >>> # Create graphs (auto-registered on creation)
    >>> workflow = Graph(id="workflow", session=session)
    >>> workflow.add_step(claude, step_id="step1", input="Hello")
    >>>
    >>> # Execute
    >>> context = ExecutionContext(session=session, input="...")
    >>> result = await claude.execute(context)
    >>>
    >>> # Cleanup
    >>> await session.stop()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.nodes.base import Node, NodeInfo
    from nerve.core.nodes.graph import Graph
    from nerve.core.nodes.session_logging import SessionLogger
    from nerve.core.workflow import Workflow, WorkflowRun, WorkflowRunInfo, WorkflowState

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Central workspace abstraction for nodes and graphs.

    Session is the central abstraction for managing nodes and graphs.
    All nodes and graphs take a session parameter and auto-register on creation.

    Attributes:
        name: Unique session name (used as identifier).
        description: Session description.
        tags: Session tags for categorization.
        created_at: Session creation timestamp.
        metadata: Additional session metadata.
        nodes: Registry of nodes (name -> Node).
        graphs: Registry of graphs (name -> Graph).
        server_name: Name used for history file paths.
        history_enabled: Whether to enable history by default.
        history_base_dir: Base directory for history files.

    Example:
        >>> from nerve.core.session import Session
        >>> from nerve.core.nodes.terminal import PTYNode
        >>> from nerve.core.nodes.bash import BashNode
        >>> from nerve.core.nodes.base import FunctionNode
        >>> from nerve.core.nodes.graph import Graph
        >>>
        >>> session = Session(name="my-session")
        >>>
        >>> # Create terminal node (async)
        >>> node = await PTYNode.create(id="shell", session=session, command="bash")
        >>>
        >>> # Create stateless nodes (sync)
        >>> bash = BashNode(id="runner", session=session, cwd="/tmp")
        >>> fn = FunctionNode(id="transform", session=session, fn=lambda ctx: ctx.input)
        >>> graph = Graph(id="pipeline", session=session)
        >>>
        >>> # All nodes are registered automatically
        >>> assert "shell" in session.nodes
        >>> assert "runner" in session.nodes
        >>> assert "pipeline" in session.graphs
    """

    # Identity - name is the unique identifier
    name: str = "default"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Registries (renamed from _nodes to nodes for public access)
    nodes: dict[str, Node] = field(default_factory=dict)
    graphs: dict[str, Graph] = field(default_factory=dict)
    workflows: dict[str, Workflow] = field(default_factory=dict)

    # Workflow runs (internal)
    _workflow_runs: dict[str, WorkflowRun] = field(default_factory=dict, repr=False)

    # Node creation configuration
    server_name: str = "default"
    history_enabled: bool = True
    history_base_dir: Path | None = None

    # Logging configuration
    file_logging: bool = True
    console_logging: bool = False

    # Session logging (internal)
    _session_logger: SessionLogger | None = field(default=None, repr=False)
    _start_time: float | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Initialize session logger and auto-create identity node."""
        from nerve.core.nodes.session_logging import SessionLogger

        self._session_logger = SessionLogger.create(
            session_name=self.name,
            server_name=self.server_name,
            file_logging=self.file_logging,
            console_logging=self.console_logging,
        )

        # Auto-create built-in identity node - lifecycle tied to session
        from nerve.core.nodes.identity import IdentityNode

        IdentityNode(id="identity", session=self)

    @property
    def session_logger(self) -> SessionLogger | None:
        """Get the session logger for this session."""
        return self._session_logger

    @property
    def id(self) -> str:
        """Session ID (same as name for compatibility)."""
        return self.name

    # =========================================================================
    # Registry Access
    # =========================================================================

    def get_node(self, node_id: str) -> Node | None:
        """Get a node by ID.

        Args:
            node_id: Node identifier.

        Returns:
            The node, or None if not found.
        """
        return self.nodes.get(node_id)

    def get_graph(self, graph_id: str) -> Graph | None:
        """Get a graph by ID.

        Args:
            graph_id: Graph identifier.

        Returns:
            The graph, or None if not found.
        """
        return self.graphs.get(graph_id)

    def list_nodes(self) -> list[str]:
        """List all node IDs.

        Returns:
            List of node IDs.
        """
        return list(self.nodes.keys())

    def list_graphs(self) -> list[str]:
        """List all graph IDs.

        Returns:
            List of graph IDs.
        """
        return list(self.graphs.keys())

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        """Get a workflow by ID.

        Args:
            workflow_id: Workflow identifier.

        Returns:
            The workflow, or None if not found.
        """
        return self.workflows.get(workflow_id)

    def list_workflows(self) -> list[str]:
        """List all workflow IDs.

        Returns:
            List of workflow IDs.
        """
        return list(self.workflows.keys())

    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow.

        Args:
            workflow_id: ID of workflow to delete.

        Returns:
            True if deleted, False if not found.
        """
        deleted = self.workflows.pop(workflow_id, None) is not None
        logger.debug(
            "[%s] delete_workflow: workflow_id=%s, found=%s",
            self.name,
            workflow_id,
            deleted,
        )
        return deleted

    def get_workflow_run(self, run_id: str) -> WorkflowRun | None:
        """Get a workflow run by ID.

        Args:
            run_id: Run identifier.

        Returns:
            The workflow run, or None if not found.
        """
        return self._workflow_runs.get(run_id)

    def list_workflow_runs(
        self,
        workflow_id: str | None = None,
        state: WorkflowState | None = None,
    ) -> list[WorkflowRunInfo]:
        """List workflow runs with optional filters.

        Args:
            workflow_id: Optional filter by workflow ID.
            state: Optional filter by state.

        Returns:
            List of workflow run info objects.
        """
        runs = []
        for run in self._workflow_runs.values():
            if workflow_id and run.workflow_id != workflow_id:
                continue
            if state and run.state != state:
                continue
            runs.append(run.to_info())
        return runs

    def register_workflow_run(self, run: WorkflowRun) -> None:
        """Register a workflow run (internal use).

        Args:
            run: The workflow run to register.
        """
        self._workflow_runs[run.run_id] = run
        logger.debug(
            "[%s] register_workflow_run: run_id=%s, workflow_id=%s",
            self.name,
            run.run_id,
            run.workflow_id,
        )

    def unregister_workflow_run(self, run_id: str) -> bool:
        """Unregister a workflow run (internal use).

        Args:
            run_id: The run ID to unregister.

        Returns:
            True if unregistered, False if not found.
        """
        removed = self._workflow_runs.pop(run_id, None) is not None
        if removed:
            logger.debug(
                "[%s] unregister_workflow_run: run_id=%s",
                self.name,
                run_id,
            )
        return removed

    def list_ready_nodes(self) -> list[str]:
        """List names of nodes in READY or BUSY state (non-stopped).

        Returns:
            List of active node names.
        """
        from nerve.core.nodes.base import NodeState

        ready_states = (NodeState.READY, NodeState.BUSY, NodeState.STARTING)
        result = []

        for name, node in self.nodes.items():
            if hasattr(node, "state"):
                if node.state in ready_states:
                    result.append(name)
            else:
                # FunctionNode or similar without state - always ready
                result.append(name)

        return result

    def validate_unique_id(self, entity_id: str, entity_type: str) -> None:
        """Validate that an ID is unique across nodes, graphs, and workflows.

        Args:
            entity_id: The ID to validate.
            entity_type: Either "node", "graph", or "workflow" (for error message).

        Raises:
            ValueError: If ID already exists as a node, graph, or workflow.
        """
        if entity_id in self.nodes:
            raise ValueError(
                f"{entity_type.capitalize()} '{entity_id}' conflicts with existing node "
                f"in session '{self.name}'"
            )
        if entity_id in self.graphs:
            raise ValueError(
                f"{entity_type.capitalize()} '{entity_id}' conflicts with existing graph "
                f"in session '{self.name}'"
            )
        if entity_id in self.workflows:
            raise ValueError(
                f"{entity_type.capitalize()} '{entity_id}' conflicts with existing workflow "
                f"in session '{self.name}'"
            )

    def get_node_info(self) -> dict[str, NodeInfo]:
        """Get info for all nodes.

        Returns:
            Dict of node name -> NodeInfo.
        """
        result = {}
        for name, node in self.nodes.items():
            if hasattr(node, "to_info"):
                result[name] = node.to_info()
        return result

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def delete_node(self, node_id: str, reason: str = "deleted") -> bool:
        """Stop and remove a node.

        Args:
            node_id: ID of node to delete.
            reason: Reason for deletion.

        Returns:
            True if deleted, False if not found.
        """
        node = self.nodes.pop(node_id, None)
        if node is None:
            logger.debug("[%s] delete_node: node_id=%s, found=False", self.name, node_id)
            return False
        if hasattr(node, "stop"):
            await node.stop()
        logger.debug("[%s] delete_node: node_id=%s, found=True", self.name, node_id)

        # Log to session logger
        if self._session_logger:
            self._session_logger.log_node_deregistered(node_id, reason=reason)
            self._session_logger.log_node_deleted(node_id, reason=reason)

        return True

    def delete_graph(self, graph_id: str) -> bool:
        """Remove a graph.

        Args:
            graph_id: ID of graph to delete.

        Returns:
            True if deleted, False if not found.
        """
        deleted = self.graphs.pop(graph_id, None) is not None
        logger.debug("[%s] delete_graph: graph_id=%s, found=%s", self.name, graph_id, deleted)

        # Log to session logger
        if deleted and self._session_logger:
            self._session_logger.log_graph_deregistered(graph_id)

        return deleted

    async def start(self) -> None:
        """Start all stateful nodes (including those inside graphs).

        Stateful nodes (PTYNode, WezTermNode, etc.) need to be started
        before they can execute. This method starts all stateful nodes
        registered in the session.
        """
        self._start_time = time.time()
        persistent_nodes = self._collect_persistent_nodes()
        node_ids = [getattr(n, "id", "?") for n in persistent_nodes]

        logger.debug(
            "[%s] session_start: persistent_nodes=%d, node_ids=%s",
            self.name,
            len(persistent_nodes),
            node_ids,
        )

        # Log to session logger
        if self._session_logger:
            self._session_logger.log_session_start(
                persistent_nodes=len(persistent_nodes),
                node_ids=node_ids,
            )

        for node in persistent_nodes:
            if hasattr(node, "start"):
                await node.start()
        logger.debug("[%s] session_started: persistent_nodes=%d", self.name, len(persistent_nodes))

    async def stop(self) -> None:
        """Stop all nodes, cancel workflows, and clear registries."""
        node_count = len(self.nodes)
        graph_count = len(self.graphs)
        workflow_run_count = len(self._workflow_runs)
        duration_s = None
        if self._start_time:
            duration_s = time.time() - self._start_time

        logger.debug(
            "[%s] session_stop: nodes=%d, graphs=%d, workflow_runs=%d",
            self.name,
            node_count,
            graph_count,
            workflow_run_count,
        )

        # Cancel any running workflows
        for run in self._workflow_runs.values():
            if not run.is_complete:
                try:
                    await run.cancel()
                except Exception as e:
                    # Best effort - log but don't fail stop on cancel errors
                    logger.debug(
                        "[%s] workflow cancel error during stop: run_id=%s, error=%s",
                        self.name,
                        run.run_id,
                        e,
                    )

        for node in self._collect_persistent_nodes():
            if hasattr(node, "stop"):
                await node.stop()
        self.nodes.clear()
        self.graphs.clear()
        self._workflow_runs.clear()
        logger.debug(
            "[%s] session_stopped: nodes=%d, graphs=%d, workflow_runs=%d",
            self.name,
            node_count,
            graph_count,
            workflow_run_count,
        )

        # Log to session logger and close it
        if self._session_logger:
            self._session_logger.log_session_stop(
                nodes=node_count,
                graphs=graph_count,
                duration_s=duration_s,
            )
            self._session_logger.close()
            self._session_logger = None

    def _collect_persistent_nodes(self) -> list[Node]:
        """Recursively find all stateful nodes.

        Returns:
            List of stateful nodes (including nested in graphs).
        """
        from nerve.core.nodes.graph import Graph

        persistent: list[Any] = []
        for node in self.nodes.values():
            if hasattr(node, "persistent") and node.persistent:
                persistent.append(node)
            if isinstance(node, Graph):
                persistent.extend(node.collect_persistent_nodes())
        return persistent

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict.

        Returns:
            Dict representation of session.
        """
        nodes_dict = {}
        for name, node in self.nodes.items():
            if hasattr(node, "to_info"):
                nodes_dict[name] = node.to_info().to_dict()

        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
            "nodes": nodes_dict,
            "graphs": list(self.graphs.keys()),
            "workflows": list(self.workflows.keys()),
        }

    # =========================================================================
    # Dunder methods
    # =========================================================================

    def __len__(self) -> int:
        return len(self.nodes)

    def __contains__(self, name: str) -> bool:
        return name in self.nodes

    def __repr__(self) -> str:
        node_names = ", ".join(self.nodes.keys())
        graph_names = ", ".join(self.graphs.keys())
        workflow_names = ", ".join(self.workflows.keys())
        return (
            f"Session(id={self.id!r}, name={self.name!r}, "
            f"nodes=[{node_names}], graphs=[{graph_names}], "
            f"workflows=[{workflow_names}])"
        )
