"""ValidationHelpers - Shared validation logic for command handlers.

This module eliminates duplication of common validation patterns:
- require_param: Used everywhere (~20 times)
- Node lookup + validation pattern (~10 times)
- Graph lookup + validation pattern (~4 times)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.nodes import Node
    from nerve.core.nodes.graph import Graph
    from nerve.core.session import Session


class ValidationHelpers:
    """Shared validation helpers for command handlers.

    Stateless class - handlers pass Session directly when calling methods.

    Example:
        >>> validation = ValidationHelpers()
        >>> node_id = validation.require_param(params, "node_id")
        >>> node = validation.get_node(session, node_id)
    """

    @staticmethod
    def require_param(params: dict[str, Any], key: str) -> Any:
        """Extract required parameter or raise ValueError.

        Args:
            params: Command parameters dict.
            key: Required parameter key.

        Returns:
            The parameter value.

        Raises:
            ValueError: If parameter is missing or None.
        """
        value = params.get(key)
        if value is None:
            raise ValueError(f"{key} is required")
        return value

    @staticmethod
    def get_node(
        session: Session,
        node_id: str,
        require_terminal: bool = False,
    ) -> Node:
        """Get node from session with validation.

        Args:
            session: Session to look up node in.
            node_id: Node identifier.
            require_terminal: If True, validate node has terminal capabilities.

        Returns:
            The node.

        Raises:
            ValueError: If node not found or doesn't have required capabilities.
        """
        node = session.get_node(str(node_id))
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        if require_terminal and not hasattr(node, "write"):
            raise ValueError(f"Node {node_id} is not a terminal node")

        return node

    @staticmethod
    def get_graph(session: Session, graph_id: str) -> Graph:
        """Get graph from session with validation.

        Args:
            session: Session to look up graph in.
            graph_id: Graph identifier.

        Returns:
            The graph.

        Raises:
            ValueError: If graph not found.
        """
        graph = session.get_graph(graph_id)
        if graph is None:
            raise ValueError(f"Graph not found: {graph_id}")
        return graph
