"""Session - registry and lifecycle manager for nodes.

A Session is a registry and lifecycle manager for nodes.
Sessions provide:

- Named registration and lookup of nodes
- Lifecycle management (start/stop persistent nodes)

This is a clean break from the Channel-based API. Use nodes directly.

Example:
    >>> session = Session(name="my-project")
    >>>
    >>> # Register nodes
    >>> shell = await PTYNode.create("shell", command="bash")
    >>> session.register(shell)  # Uses node.id as name
    >>> session.register(shell, name="dev")  # Custom name
    >>>
    >>> # Use nodes
    >>> node = session.get("shell")
    >>> context = ExecutionContext(session=session, input="ls -la")
    >>> result = await node.execute(context)
    >>>
    >>> # Stop all persistent nodes
    >>> await session.stop()
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.nodes.base import Node, NodeInfo


@dataclass
class Session:
    """Registry and lifecycle manager for nodes.

    Sessions provide:
    - Named registration and lookup of nodes
    - Lifecycle management (start/stop persistent nodes)

    Nodes are registered with a name (defaulting to node.id) and can be
    looked up by that name. Persistent nodes have their lifecycle managed
    by the session's start() and stop() methods.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    _nodes: dict[str, Node] = field(default_factory=dict)

    def __post_init__(self):
        if not self.name:
            self.name = self.id

    def register(self, node: Node, name: str | None = None) -> None:
        """Register a node with an optional custom name.

        Args:
            node: The node to register.
            name: Optional name for lookup (defaults to node.id).
                  Allows the same node to be referenced by a different name
                  than its internal ID.

        Raises:
            ValueError: If name already exists in registry.

        Example:
            # Register with node's ID
            session.register(node)  # Lookup key = node.id

            # Register with custom name
            session.register(node, name="dev")  # Lookup key = "dev"
        """
        key = name or node.id
        if key in self._nodes:
            raise ValueError(f"Name '{key}' already exists in session")
        self._nodes[key] = node

    def unregister(self, name: str) -> Node | None:
        """Remove a node from registry (does NOT stop it).

        Args:
            name: The name used when registering the node.

        Returns:
            The removed node, or None if not found.
        """
        return self._nodes.pop(name, None)

    def get(self, name: str) -> Node | None:
        """Get a node by name.

        Args:
            name: Node name.

        Returns:
            The node, or None if not found.
        """
        return self._nodes.get(name)

    def list_nodes(self) -> list[str]:
        """List all registered node names.

        Returns:
            List of node names.
        """
        return list(self._nodes.keys())

    def list_ready_nodes(self) -> list[str]:
        """List names of nodes in READY or BUSY state (non-stopped).

        Returns:
            List of active node names.
        """
        from nerve.core.nodes.base import NodeState

        ready_states = (NodeState.READY, NodeState.BUSY, NodeState.STARTING)
        result = []

        for name, node in self._nodes.items():
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
        for name, node in self._nodes.items():
            if hasattr(node, "to_info"):
                result[name] = node.to_info()
        return result

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
        """Stop all persistent nodes.

        Stops all persistent nodes registered in the session.
        After this, the nodes cannot be used until started again.
        """
        for node in self._collect_persistent_nodes():
            if hasattr(node, "stop"):
                await node.stop()

    def _collect_persistent_nodes(self) -> list[Node]:
        """Recursively find all persistent nodes.

        Returns:
            List of persistent nodes (including nested in graphs).
        """
        from nerve.core.nodes.graph import Graph

        persistent: list[Any] = []
        for node in self._nodes.values():
            if hasattr(node, "persistent") and node.persistent:
                persistent.append(node)
            if isinstance(node, Graph):
                persistent.extend(node.collect_persistent_nodes())
        return persistent

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict.

        Returns:
            Dict representation of session.
        """
        nodes_dict = {}
        for name, node in self._nodes.items():
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
        }

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, name: str) -> bool:
        return name in self._nodes

    def __repr__(self) -> str:
        names = ", ".join(self._nodes.keys())
        return f"Session(id={self.id!r}, name={self.name!r}, nodes=[{names}])"
