"""Session - central workspace abstraction for nodes and graphs.

Session is the central workspace that:
- Creates and registers nodes
- Stores and manages graphs
- Manages lifecycle (start/stop)

Example:
    >>> session = Session(name="my-project")
    >>>
    >>> # Create nodes (auto-registered)
    >>> claude = await session.create_node("claude", command="claude")
    >>> shell = await session.create_node("shell", command="bash")
    >>>
    >>> # Create graphs (auto-registered)
    >>> workflow = session.create_graph("workflow")
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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.nodes.base import FunctionNode, Node, NodeInfo
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.nodes.graph import Graph
    from nerve.core.nodes.terminal import ClaudeWezTermNode, PTYNode, WezTermNode
    from nerve.core.types import ParserType

logger = logging.getLogger(__name__)


class BackendType(Enum):
    """Terminal backend types."""

    PTY = "pty"
    WEZTERM = "wezterm"
    CLAUDE_WEZTERM = "claude-wezterm"


# Type alias for terminal nodes
type TerminalNode = "PTYNode | WezTermNode | ClaudeWezTermNode"


@dataclass
class Session:
    """Central workspace abstraction for nodes and graphs.

    Session is the central abstraction for managing executable units.
    It creates, registers, and manages the lifecycle of nodes and graphs.

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
    # Node Factory Methods
    # =========================================================================

    async def create_node(
        self,
        node_id: str,
        command: str | list[str] | None = None,
        backend: BackendType | str = BackendType.PTY,
        cwd: str | None = None,
        pane_id: str | None = None,
        history: bool | None = None,  # None = use session default
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        default_parser: ParserType | None = None,
    ) -> TerminalNode:
        """Create and register a terminal node.

        Args:
            node_id: Unique identifier for the node.
            command: Command to run (e.g., "claude" or ["bash", "-i"]).
            backend: Backend type (pty, wezterm, claude-wezterm).
            cwd: Working directory.
            pane_id: For wezterm, attach to existing pane.
            history: Enable history logging (default: session.history_enabled).
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            default_parser: Default parser for execute() calls.

        Returns:
            Started TerminalNode, ready for use.

        Raises:
            ValueError: If node_id already exists or is invalid.
        """
        from nerve.core.nodes.history import HistoryError, HistoryWriter
        from nerve.core.nodes.terminal import (
            ClaudeWezTermNode,
            PTYNode,
            WezTermNode,
        )
        from nerve.core.types import ParserType
        from nerve.core.validation import validate_name

        if not node_id:
            raise ValueError("node_id is required")
        validate_name(node_id, "node")
        if node_id in self.nodes:
            raise ValueError(f"Node already exists: {node_id}")

        # Normalize backend
        if isinstance(backend, str):
            backend = BackendType(backend.lower())

        # History setup
        use_history = history if history is not None else self.history_enabled
        history_writer = None
        if use_history:
            try:
                history_writer = HistoryWriter.create(
                    node_id=node_id,
                    server_name=self.server_name,
                    session_name=self.name,
                    base_dir=self.history_base_dir,
                    enabled=True,
                )
            except (HistoryError, ValueError) as e:
                logger.warning(f"Failed to create history writer for {node_id}: {e}")
                history_writer = None

        # Default parser
        if default_parser is None:
            default_parser = ParserType.NONE

        try:
            # Create based on backend (using internal _create methods)
            node: TerminalNode
            if backend == BackendType.CLAUDE_WEZTERM:
                if not command:
                    raise ValueError("command is required for claude-wezterm backend")
                actual_parser = (
                    default_parser if default_parser != ParserType.NONE else ParserType.CLAUDE
                )
                node = await ClaudeWezTermNode._create(
                    node_id=node_id,
                    command=command if isinstance(command, str) else " ".join(command),
                    cwd=cwd,
                    ready_timeout=ready_timeout,
                    response_timeout=response_timeout,
                    history_writer=history_writer,
                    parser=actual_parser,
                )

            elif backend == BackendType.WEZTERM or pane_id is not None:
                if pane_id:
                    # Attach to existing WezTerm pane
                    node = await WezTermNode._attach(
                        node_id=node_id,
                        pane_id=pane_id,
                        ready_timeout=ready_timeout,
                        response_timeout=response_timeout,
                        history_writer=history_writer,
                        default_parser=default_parser,
                    )
                else:
                    # Spawn new WezTerm pane
                    node = await WezTermNode._create(
                        node_id=node_id,
                        command=command,
                        cwd=cwd,
                        ready_timeout=ready_timeout,
                        response_timeout=response_timeout,
                        history_writer=history_writer,
                        default_parser=default_parser,
                    )

            else:
                # Default to PTY
                node = await PTYNode._create(
                    node_id=node_id,
                    command=command,
                    cwd=cwd,
                    ready_timeout=ready_timeout,
                    response_timeout=response_timeout,
                    history_writer=history_writer,
                    default_parser=default_parser,
                )

            # Auto-register
            self.nodes[node_id] = node
            return node

        except Exception:
            # Clean up history writer on node creation failure
            if history_writer is not None:
                history_writer.close()
            raise

    def create_function(
        self,
        node_id: str,
        fn: Callable[[ExecutionContext], Any],
    ) -> FunctionNode:
        """Create and register a function node.

        Args:
            node_id: Unique identifier for the node.
            fn: Sync or async callable accepting ExecutionContext.

        Returns:
            FunctionNode wrapping the callable.

        Raises:
            ValueError: If node_id already exists or is invalid.
        """
        from nerve.core.nodes.base import FunctionNode
        from nerve.core.validation import validate_name

        if not node_id:
            raise ValueError("node_id is required")
        validate_name(node_id, "node")
        if node_id in self.nodes:
            raise ValueError(f"Node already exists: {node_id}")

        node = FunctionNode(id=node_id, fn=fn)
        self.nodes[node_id] = node
        return node

    def create_graph(self, graph_id: str) -> Graph:
        """Create and register a graph.

        Args:
            graph_id: Unique identifier for the graph.

        Returns:
            Empty Graph ready to have steps added.

        Raises:
            ValueError: If graph_id already exists.
        """
        from nerve.core.nodes.graph import Graph

        # Graph constructor now requires session and auto-registers
        graph = Graph(id=graph_id, session=self)
        return graph

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
