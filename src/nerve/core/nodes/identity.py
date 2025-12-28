"""IdentityNode - ephemeral node that echoes input as output.

IdentityNode is the simplest possible node - it returns whatever input it receives.
Like the Identity Matrix in mathematics: I × x = x

Key features:
- Stateless and ephemeral (no resources, no lifecycle)
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
    """Ephemeral node that echoes input back as output.

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

    def __post_init__(self) -> None:
        """Validate and register with session."""
        from nerve.core.validation import validate_name

        # Validate node ID
        validate_name(self.id, "node")

        # Check for duplicates
        if self.id in self.session.nodes:
            raise ValueError(f"Node '{self.id}' already exists in session '{self.session.name}'")

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
            Dict with 'output' containing the echoed input.
            Format matches BashNode for consistency.
        """
        output = str(context.input) if context.input else ""
        return {
            "success": True,
            "output": output,
            "input": output,  # For compatibility with :::N['input'] in Commander
            "error": None,
        }

    async def interrupt(self) -> None:
        """No-op for IdentityNode.

        IdentityNode execution is instantaneous, so interrupt does nothing.
        This method exists to satisfy the Node protocol.
        """
        pass

    def to_info(self) -> NodeInfo:
        """Get node information.

        Returns:
            NodeInfo for this node.
        """
        return NodeInfo(
            id=self.id,
            node_type="identity",
            state=NodeState.READY,  # Ephemeral nodes are always ready
            persistent=self.persistent,
            metadata=self.metadata,
        )

    def __repr__(self) -> str:
        return f"IdentityNode(id={self.id!r})"
