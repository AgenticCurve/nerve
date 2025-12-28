"""Node abstraction - unified interface for executable units of work.

A Node represents any executable unit:
- FunctionNode: Wraps sync/async callables (stateless)
- PTYNode: PTY-based terminal (stateful)
- WezTermNode: WezTerm pane attachment (stateful)
- Graph: Contains steps with nodes (can be nested)

Stateful nodes maintain state across executions; stateless nodes do not.
All nodes persist in the session until explicitly deleted.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session


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

        Stateful nodes (persistent=True):
        - Maintain state between execute() calls (e.g., terminal buffer, conversation history)
        - Must implement start() and stop() lifecycle methods
        - Examples: PTYNode, WezTermNode, LLMChatNode

        Stateless nodes (persistent=False):
        - No state between execute() calls - each execution is independent
        - No lifecycle management needed
        - Examples: FunctionNode, BashNode, IdentityNode, OpenRouterNode

        Note: All nodes persist in the session until explicitly deleted.
        The 'persistent' flag only indicates whether state is maintained between calls.
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

    async def interrupt(self) -> None:
        """Request interruption of current execution.

        For stateless nodes (persistent=False):
            Best-effort cancellation. May cancel the current async task.
            No guarantee for sync operations.

        For stateful nodes (persistent=True):
            Should stop the current operation (e.g., send Ctrl+C to process).
            Resources remain allocated; use stop() to release them.

        This method should be safe to call:
            - Multiple times
            - When no execution is in progress
            - From a different task/thread than execute()
        """
        ...


class PersistentNode(Node, Protocol):
    """Protocol extension for stateful nodes that maintain state.

    Stateful nodes (persistent=True) have additional lifecycle methods for
    initialization and cleanup. They should be started before use and
    stopped when no longer needed.

    Examples: PTYNode, WezTermNode, LLMChatNode

    The Session manages lifecycle of registered stateful nodes.
    """

    async def start(self) -> None:
        """Initialize resources.

        Called by Session.start() for all registered stateful nodes.
        After this call, the node should be in READY state.
        """
        ...

    async def stop(self) -> None:
        """Release resources.

        Called by Session.stop() for all registered stateful nodes.
        After this call, the node should be in STOPPED state.
        """
        ...


@dataclass
class FunctionNode:
    """Wraps a sync or async callable as a stateless node.

    FunctionNodes are stateless (persistent=False) - they can be called
    multiple times with different inputs and produce independent results.

    The wrapped function receives an ExecutionContext and should return
    a result. Both sync and async functions are supported.

    Auto-registers with session on creation.

    Args:
        id: Unique identifier for this node.
        session: Session to register this node with.
        fn: Sync or async callable accepting ExecutionContext.

    Example:
        >>> session = Session("my-session")
        >>> def transform(ctx: ExecutionContext) -> str:
        ...     return ctx.input.upper()
        >>> node = FunctionNode(id="transform", session=session, fn=transform)

        # Async function
        >>> async def fetch(ctx: ExecutionContext) -> dict:
        ...     return await http_client.get(ctx.input)
        >>> node = FunctionNode(id="fetch", session=session, fn=fetch)

        # Lambda
        >>> node = FunctionNode(id="add", session=session, fn=lambda ctx: ctx.input + 1)
    """

    # Required fields (no defaults)
    id: str
    session: Session
    fn: Callable[[ExecutionContext], Any]

    # Optional fields (with defaults)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Internal fields (not in __init__)
    persistent: bool = field(default=False, init=False)
    state: NodeState = field(default=NodeState.READY, init=False)
    _current_task: asyncio.Task[Any] | None = field(default=None, init=False, repr=False)

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
                self.id, "FunctionNode", persistent=self.persistent
            )

    async def execute(self, context: ExecutionContext) -> Any:
        """Execute the wrapped function.

        Handles both sync and async functions automatically.

        Args:
            context: Execution context with input and upstream results.

        Returns:
            The function's return value.
        """
        from nerve.core.nodes.run_logging import log_complete, log_error, log_start
        from nerve.core.nodes.session_logging import get_execution_logger

        # Check if node is stopped
        if self.state == NodeState.STOPPED:
            raise RuntimeError("Node is stopped")

        # Get logger and exec_id
        log_ctx = get_execution_logger(self.id, context, self.session)
        exec_id = log_ctx.exec_id or context.exec_id

        # Get function name for logging
        fn_name = getattr(self.fn, "__name__", repr(self.fn))

        log_start(log_ctx.logger, self.id, "function_start", exec_id=exec_id, fn=fn_name)

        start_mono = time.monotonic()
        self._current_task = asyncio.current_task()
        try:
            result = self.fn(context)
            if asyncio.iscoroutine(result):
                result = await result

            duration = time.monotonic() - start_mono
            log_complete(log_ctx.logger, self.id, "function_complete", duration, exec_id=exec_id)

            return result
        except Exception as e:
            duration = time.monotonic() - start_mono
            log_error(
                log_ctx.logger,
                self.id,
                "function_failed",
                e,
                exec_id=exec_id,
                duration_s=f"{duration:.1f}",
            )
            raise
        finally:
            self._current_task = None

    async def interrupt(self) -> None:
        """Request interruption of current execution.

        Cancels the current async task if one is running.
        For sync functions, this is best-effort - the function
        will complete before cancellation takes effect.
        """
        if self._current_task is not None:
            self._current_task.cancel()

    async def stop(self) -> None:
        """Stop the node and mark as unusable.

        Sets state to STOPPED. Future execute() calls will raise RuntimeError.
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
            node_type="function",
            state=self.state,
            persistent=self.persistent,
            metadata=self.metadata,
        )

    def __repr__(self) -> str:
        return f"FunctionNode(id={self.id!r})"
