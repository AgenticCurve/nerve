"""NodeFactory - factory for creating different node types.

NodeFactory replaces ChannelManager as the factory for creating nodes.
It creates nodes but does NOT register them - registration is a separate
step via Session.register().

Example:
    >>> factory = NodeFactory()
    >>> node = await factory.create_terminal("my-node", command="bash")
    >>> session = Session()
    >>> session.register(node)
    >>> result = await node.execute(ExecutionContext(session=session, input="ls"))
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nerve.core.channels.history import HistoryError, HistoryWriter
from nerve.core.nodes.base import FunctionNode
from nerve.core.nodes.terminal import ClaudeWezTermNode, PTYNode, WezTermNode
from nerve.core.types import ParserType

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.nodes.graph import Graph

logger = logging.getLogger(__name__)


class BackendType(Enum):
    """Terminal backend types."""

    PTY = "pty"
    WEZTERM = "wezterm"
    CLAUDE_WEZTERM = "claude-wezterm"


# Type alias for terminal nodes
TerminalNode = PTYNode | WezTermNode | ClaudeWezTermNode


@dataclass
class NodeFactory:
    """Factory for creating different node types.

    NodeFactory creates nodes but does NOT register them.
    Registration is a separate step via Session.register().

    Attributes:
        server_name: Name used for history file paths.
        history_base_dir: Base directory for history files.
    """

    server_name: str = "default"
    history_base_dir: Path | None = None

    async def create_terminal(
        self,
        node_id: str,
        command: str | list[str] | None = None,
        backend: BackendType | str = BackendType.PTY,
        cwd: str | None = None,
        pane_id: str | None = None,
        history: bool = True,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        default_parser: ParserType = ParserType.NONE,
    ) -> TerminalNode:
        """Create a terminal node (PTY, WezTerm, or ClaudeWezTerm).

        The returned node is already started and ready for use.
        This matches current ChannelManager.create_terminal() behavior.

        Args:
            node_id: Unique node identifier (required).
            command: Command to run (e.g., "claude" or ["bash"]).
            backend: Backend type (pty, wezterm, or claude-wezterm).
            cwd: Working directory.
            pane_id: For WezTerm, attach to existing pane instead of creating new.
            history: Enable history logging (default: True).
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            default_parser: Default parser for execute() calls.

        Returns:
            A started TerminalNode (PTYNode, WezTermNode, or ClaudeWezTermNode).

        Raises:
            ValueError: If node_id is not provided or invalid backend.
        """
        if not node_id:
            raise ValueError("node_id is required")

        # Normalize backend to enum
        if isinstance(backend, str):
            backend = BackendType(backend)

        # Create history writer if enabled
        history_writer = None
        if history:
            try:
                history_writer = HistoryWriter.create(
                    channel_id=node_id,  # Uses channel_id for compatibility
                    server_name=self.server_name,
                    base_dir=self.history_base_dir,
                    enabled=True,
                )
            except (HistoryError, ValueError) as e:
                logger.warning(f"Failed to create history writer for {node_id}: {e}")
                history_writer = None

        try:
            if backend == BackendType.CLAUDE_WEZTERM:
                if not command:
                    raise ValueError("command is required for claude-wezterm backend")
                # ClaudeWezTermNode defaults to CLAUDE parser
                actual_parser = default_parser if default_parser != ParserType.NONE else ParserType.CLAUDE
                return await ClaudeWezTermNode.create(
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
                    return await WezTermNode.attach(
                        node_id=node_id,
                        pane_id=pane_id,
                        ready_timeout=ready_timeout,
                        response_timeout=response_timeout,
                        history_writer=history_writer,
                        default_parser=default_parser,
                    )
                else:
                    # Spawn new WezTerm pane
                    return await WezTermNode.create(
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
                return await PTYNode.create(
                    node_id=node_id,
                    command=command,
                    cwd=cwd,
                    ready_timeout=ready_timeout,
                    response_timeout=response_timeout,
                    history_writer=history_writer,
                    default_parser=default_parser,
                )

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
        """Create a function node wrapping a callable.

        Args:
            node_id: Unique node identifier.
            fn: The function to wrap (sync or async).

        Returns:
            A FunctionNode wrapping the callable.
        """
        return FunctionNode(id=node_id, fn=fn)

    def create_graph(self, graph_id: str) -> Graph:
        """Create an empty graph node.

        Args:
            graph_id: Unique graph identifier.

        Returns:
            An empty Graph ready to have steps added.
        """
        from nerve.core.nodes.graph import Graph

        return Graph(id=graph_id)

    async def stop_node(self, node: TerminalNode) -> None:
        """Stop a terminal node and release its resources.

        Args:
            node: The terminal node to stop.
        """
        await node.stop()
