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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.nodes.base import Node, NodeInfo
    from nerve.core.nodes.graph import Graph

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
        >>> # Create ephemeral nodes (sync)
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

    # Node creation configuration
    server_name: str = "default"
    history_enabled: bool = True
    history_base_dir: Path | None = None

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

    async def delete_node(self, node_id: str) -> bool:
        """Stop and remove a node.

        Args:
            node_id: ID of node to delete.

        Returns:
            True if deleted, False if not found.
        """
        node = self.nodes.pop(node_id, None)
        if node is None:
            return False
        if hasattr(node, "stop"):
            await node.stop()
        return True

    def delete_graph(self, graph_id: str) -> bool:
        """Remove a graph.

        Args:
            graph_id: ID of graph to delete.

        Returns:
            True if deleted, False if not found.
        """
        return self.graphs.pop(graph_id, None) is not None

    async def start(self) -> None:
        """Start all persistent nodes (including those inside graphs).

        Persistent nodes (PTYNode, WezTermNode, etc.) need to be started
        before they can execute. This method starts all persistent nodes
        registered in the session.
        """
        for node in self._collect_persistent_nodes():
            if hasattr(node, "start"):
                await node.start()

    async def stop(self) -> None:
        """Stop all nodes and clear registries."""
        for node in self._collect_persistent_nodes():
            if hasattr(node, "stop"):
                await node.stop()
        self.nodes.clear()
        self.graphs.clear()

    def _collect_persistent_nodes(self) -> list[Node]:
        """Recursively find all persistent nodes.

        Returns:
            List of persistent nodes (including nested in graphs).
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
        return (
            f"Session(id={self.id!r}, name={self.name!r}, "
            f"nodes=[{node_names}], graphs=[{graph_names}])"
        )
