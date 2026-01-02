"""Entity management for Commander TUI.

Handles tracking and syncing of nodes, graphs, and workflows from the server.
Provides unified access to all executable entities in the session.

This module extracts entity-related logic from commander.py for better
separation of concerns and testability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.console import Console

    from nerve.frontends.cli.repl.adapters import RemoteSessionAdapter

logger = logging.getLogger(__name__)


@dataclass
class EntityInfo:
    """Information about an executable entity (node, graph, or workflow).

    Provides unified tracking of nodes, graphs, and workflows in commander.

    Attributes:
        id: Unique identifier for the entity.
        type: Entity type - "node", "graph", or "workflow".
        node_type: The specific type (e.g., "BashNode", "LLMChatNode", "graph", "workflow").
        metadata: Additional metadata fields from the server.
    """

    id: str
    type: str  # "node", "graph", or "workflow"
    node_type: str  # "BashNode", "LLMChatNode", "graph", "workflow", etc.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EntityManager:
    """Manages entities (nodes, graphs, workflows) for the Commander TUI.

    Fetches entity information from the server and provides access methods.
    Maintains a unified view of all executable entities in the session.

    Example:
        >>> manager = EntityManager()
        >>> manager.adapter = adapter  # Set after connection
        >>> await manager.sync()  # Fetch from server
        >>> print(manager.nodes)  # Get node dict
    """

    # Entity storage
    entities: dict[str, EntityInfo] = field(default_factory=dict)

    # Server connection (set after connection established)
    adapter: RemoteSessionAdapter | None = field(default=None)

    # Console for error output (set after initialization)
    console: Console | None = field(default=None)

    @property
    def nodes(self) -> dict[str, str]:
        """Get nodes dict (filters entities to nodes only).

        Returns:
            Dict mapping node_id -> node_type for all entities of type "node".
        """
        return {
            entity_id: entity.node_type
            for entity_id, entity in self.entities.items()
            if entity.type == "node"
        }

    def get_nodes_by_type(self) -> dict[str, str]:
        """Build reverse mapping from node type to node ID.

        Returns:
            Dictionary mapping node_type/name -> node_id.
            E.g., {"claude": "1", "bash": "2"}

        Note:
            If multiple nodes have the same type, only the first one is kept.
        """
        result: dict[str, str] = {}
        for node_id, node_type in self.nodes.items():
            if node_type not in result:
                result[node_type] = node_id
        return result

    def get(self, entity_id: str) -> EntityInfo | None:
        """Get an entity by ID.

        Args:
            entity_id: The entity identifier.

        Returns:
            EntityInfo if found, None otherwise.
        """
        return self.entities.get(entity_id)

    def exists(self, entity_id: str) -> bool:
        """Check if an entity exists.

        Args:
            entity_id: The entity identifier.

        Returns:
            True if entity exists, False otherwise.
        """
        return entity_id in self.entities

    async def sync(self) -> None:
        """Fetch nodes, graphs, and workflows from server session.

        Clears existing entities and repopulates from server.
        Handles network errors gracefully with warning messages.
        """
        if self.adapter is None:
            return

        try:
            # Fetch nodes with full metadata (includes command, backend, etc.)
            await self.adapter.list_nodes()  # Populates cache
            nodes_info = await self.adapter.get_nodes_info()
            self.entities.clear()
            for info in nodes_info:
                node_id = info.get("id", "")
                node_type = info.get("type", "unknown")
                # Extract all metadata fields except id, type, state
                metadata = {k: v for k, v in info.items() if k not in ("id", "type", "state")}
                self.entities[node_id] = EntityInfo(
                    id=node_id,
                    type="node",
                    node_type=node_type,
                    metadata=metadata,
                )

            # Fetch graphs
            graph_ids = await self.adapter.list_graphs()
            for graph_id in graph_ids:
                self.entities[graph_id] = EntityInfo(
                    id=graph_id,
                    type="graph",
                    node_type="graph",
                )

            # Fetch workflows
            workflows = await self.adapter.list_workflows()
            for wf in workflows:
                wf_id = wf.get("id", "")
                if wf_id:
                    self.entities[wf_id] = EntityInfo(
                        id=wf_id,
                        type="workflow",
                        node_type="workflow",
                        metadata={"description": wf.get("description", "")},
                    )
        except (ConnectionError, TimeoutError, RuntimeError, OSError) as e:
            # Handle known network/transport errors gracefully
            if self.console is not None:
                self.console.print(f"[warning]Failed to fetch entities: {e}[/]")
            logger.warning("Entity sync failed: %s", e, exc_info=True)
