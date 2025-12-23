"""Node abstraction - unified interface for executable units of work.

A Node represents any executable unit:
- FunctionNode: Wraps sync/async callables (ephemeral)
- PTYNode: PTY-based terminal (persistent)
- WezTermNode: WezTerm pane attachment (persistent)
- Graph: Contains steps with nodes (can be nested)

Persistent nodes maintain state across executions; ephemeral nodes are stateless.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext


class NodeState(Enum):
    """Node lifecycle states.

    State transitions:
        CREATED -> STARTING -> READY <-> BUSY -> STOPPING -> STOPPED
    """

    CREATED = auto()  # Node instantiated but not started
    STARTING = auto()  # Node is initializing (connecting, spawning process)
    READY = auto()  # Node is ready for input
    BUSY = auto()  # Node is processing
    STOPPING = auto()  # Node is shutting down (cleanup in progress)
    STOPPED = auto()  # Node is stopped and cannot be used


@dataclass
class NodeInfo:
    """Serializable node information."""

    id: str
    node_type: str
    state: NodeState
    persistent: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "type": self.node_type,
            "state": self.state.name,
            "persistent": self.persistent,
            "metadata": self.metadata,
        }


@dataclass
class NodeConfig:
    """Base configuration for nodes."""

    id: str | None = None  # Auto-generated if not provided
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Node(Protocol):
    """Protocol for all executable units of work.

    A node is the fundamental abstraction for anything that can be executed:
    - Pure functions (FunctionNode)
    - Terminal interactions (PTYNode, WezTermNode)
    - Workflows (Graph)

    Nodes have two key properties:
    - id: Unique identifier
    - persistent: Whether state is maintained across executions

    Example:
        >>> node = FunctionNode(id="transform", fn=lambda ctx: ctx.input.upper())
        >>> context = ExecutionContext(session=session, input="hello")
        >>> result = await node.execute(context)
        >>> print(result)  # "HELLO"
    """

    @property
    def id(self) -> str:
        """Unique identifier for this node."""
        ...

    @property
    def persistent(self) -> bool:
        """Whether this node maintains state across executions.

        Persistent nodes:
        - Maintain state between execute() calls
        - Must implement start() and stop()
        - Examples: PTYNode, WezTermNode

        Ephemeral nodes:
        - Stateless, can be executed multiple times independently
        - No lifecycle management needed
        - Examples: FunctionNode, Graph
        """
        ...

    async def execute(self, context: ExecutionContext) -> Any:
        """Execute this node with the given context.

        Args:
            context: Execution context with session, input, and upstream results.

        Returns:
            The result of execution. Type depends on node implementation.
        """
        ...


class PersistentNode(Node, Protocol):
    """Protocol extension for nodes that maintain state.

    Persistent nodes have additional lifecycle methods for
    initialization and cleanup. They should be started before
    use and stopped when no longer needed.

    The Session manages lifecycle of registered persistent nodes.
    """

    async def start(self) -> None:
        """Initialize resources.

        Called by Session.start() for all registered persistent nodes.
        After this call, the node should be in READY state.
        """
        ...

    async def stop(self) -> None:
        """Release resources.

        Called by Session.stop() for all registered persistent nodes.
        After this call, the node should be in STOPPED state.
        """
        ...


@dataclass
class FunctionNode:
    """Wraps a sync or async callable as an ephemeral node.

    FunctionNodes are stateless - they can be called multiple times
    with different inputs and produce independent results.

    The wrapped function receives an ExecutionContext and should return
    a result. Both sync and async functions are supported.

    Example:
        # Sync function
        def transform(ctx: ExecutionContext) -> str:
            return ctx.input.upper()

        node = FunctionNode(id="transform", fn=transform)

        # Async function
        async def fetch(ctx: ExecutionContext) -> dict:
            return await http_client.get(ctx.input)

        node = FunctionNode(id="fetch", fn=fetch)

        # Lambda
        node = FunctionNode(id="add", fn=lambda ctx: ctx.input + 1)
    """

    id: str
    fn: Callable[[ExecutionContext], Any]
    persistent: bool = field(default=False, init=False)
    metadata: dict[str, Any] = field(default_factory=dict)

    async def execute(self, context: ExecutionContext) -> Any:
        """Execute the wrapped function.

        Handles both sync and async functions automatically.

        Args:
            context: Execution context with input and upstream results.

        Returns:
            The function's return value.
        """
        result = self.fn(context)
        if asyncio.iscoroutine(result):
            return await result
        return result

    def to_info(self) -> NodeInfo:
        """Get node information.

        Returns:
            NodeInfo for this node.
        """
        return NodeInfo(
            id=self.id,
            node_type="function",
            state=NodeState.READY,  # FunctionNodes are always ready
            persistent=self.persistent,
            metadata=self.metadata,
        )

    def __repr__(self) -> str:
        return f"FunctionNode(id={self.id!r})"
