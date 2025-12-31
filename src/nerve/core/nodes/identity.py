"""IdentityNode - stateless node that echoes input as output.

IdentityNode is the simplest possible node - it returns whatever input it receives.
Like the Identity Matrix in mathematics: I × x = x

Key features:
- Stateless (persistent=False) - no state between calls, no lifecycle management
- Can be used unlimited times
- Useful for debugging, testing, and seeing expanded variables in Commander
- Auto-created in every session as a built-in utility
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.core.nodes.base import NodeInfo, NodeState

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session


@dataclass
class IdentityNode:
    """Stateless node that echoes input back as output.

    IdentityNode is the "identity function" for nodes - it simply returns
    its input unchanged. This is useful for:
    - Debugging: See what input is being sent (including expanded variables)
    - Testing: Verify node execution pipeline works
    - Composition: Pass data through unchanged in graphs

    Like the Identity Matrix (I × x = x), this node satisfies:
        execute(input) = input

    Args:
        id: Unique identifier for this node.
        session: Session to register this node with.

    Example:
        >>> session = Session("my-session")
        >>> node = IdentityNode(id="identity", session=session)
        >>> ctx = ExecutionContext(session=session, input="hello world")
        >>> result = await node.execute(ctx)
        >>> print(result)
        "hello world"

        # In Commander:
        # ❯ @identity hello world
        # :::1 @identity (14:32:05, 0ms)
        # › hello world
        # hello world
        #
        # ❯ @identity :::1['output']
        # :::2 @identity (14:32:10, 0ms)
        # › hello world
        # hello world
    """

    # Required fields (no defaults)
    id: str
    session: Session

    # Optional fields (with defaults)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Internal fields (not in __init__)
    persistent: bool = field(default=False, init=False)
    state: NodeState = field(default=NodeState.READY, init=False)

    def __post_init__(self) -> None:
        """Validate and register with session."""
        from nerve.core.validation import validate_name

        # Validate node ID
        validate_name(self.id, "node")

        # Validate uniqueness across both nodes and graphs
        self.session.validate_unique_id(self.id, "node")

        # Auto-register with session
        self.session.nodes[self.id] = self

        # Log node registration
        if self.session.session_logger:
            self.session.session_logger.log_node_lifecycle(
                self.id, "IdentityNode", persistent=self.persistent
            )

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Return the input unchanged.

        Args:
            context: Execution context with input to echo.

        Returns:
            Dict with standardized fields:
            - success: bool - Always True (unless node is stopped)
            - error: str | None - Error message if node is stopped, None otherwise
            - error_type: str | None - "node_stopped" or None
            - node_type: str - "identity"
            - node_id: str - ID of this node
            - input: str - The input provided
            - output: str - The echoed output (same as input)
            - attributes: dict - Empty dict (no additional attributes for IdentityNode)
        """
        # Check if node is stopped
        if self.state == NodeState.STOPPED:
            return {
                "success": False,
                "error": "Node is stopped",
                "error_type": "node_stopped",
                "node_type": "identity",
                "node_id": self.id,
                "input": "",
                "output": "",
                "attributes": {},
            }

        output = str(context.input) if context.input else ""
        return {
            "success": True,
            "error": None,
            "error_type": None,
            "node_type": "identity",
            "node_id": self.id,
            "input": output,
            "output": output,
            "attributes": {},
        }

    async def interrupt(self) -> None:
        """No-op for IdentityNode.

        IdentityNode execution is instantaneous, so interrupt does nothing.
        This method exists to satisfy the Node protocol.
        """
        pass

    async def stop(self) -> None:
        """Stop the node and mark as unusable.

        Sets state to STOPPED. Future execute() calls will return an error.
        Does not unregister from session (that's Session.delete_node's job).
        """
        self.state = NodeState.STOPPED

    def to_info(self) -> NodeInfo:
        """Get node information.

        Returns:
            NodeInfo for this node.
        """
        return NodeInfo(
            id=self.id,
            node_type="identity",
            state=self.state,
            persistent=self.persistent,
            metadata=self.metadata,
        )

    def __repr__(self) -> str:
        return f"IdentityNode(id={self.id!r})"
