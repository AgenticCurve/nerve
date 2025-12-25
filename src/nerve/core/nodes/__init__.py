"""Node abstraction - unified interface for executable units of work.

Nodes are executable units that can be:
- Ephemeral (stateless): FunctionNode, BashNode, Graph
- Persistent (stateful): PTYNode, WezTermNode, ClaudeWezTermNode

Core abstractions:
    Node: Protocol for all executable units
    NodeState: Lifecycle states (CREATED, STARTING, READY, BUSY, STOPPING, STOPPED)
    NodeInfo: Serializable node information
    NodeConfig: Base configuration for nodes
    FunctionNode: Wraps sync/async callables
    BashNode: Runs bash commands via subprocess

Graph abstractions:
    Graph: Orchestrates node execution with dependencies
    Step: Combines node + input + dependencies
    StepEvent: Event emitted during streaming execution

Execution context:
    ExecutionContext: Runtime context passed through execution

Terminal nodes:
    PTYNode: PTY-based terminal
    WezTermNode: WezTerm pane attachment
    ClaudeWezTermNode: WezTerm optimized for Claude CLI

Agent capabilities:
    ErrorPolicy: Error handling policy (retry, skip, fallback)
    Budget: Resource limits
    ResourceUsage: Resource consumption tracking
    BudgetExceededError: Raised when budget exceeded
    CancellationToken: Cooperative cancellation
    CancelledError: Raised when execution cancelled
    StepTrace: Per-step execution trace
    ExecutionTrace: Full graph execution trace

Example:
    >>> from nerve.core.nodes import (
    ...     FunctionNode, Graph, ExecutionContext, PTYNode
    ... )
    >>>
    >>> # Create session and function nodes
    >>> from nerve.core.session import Session
    >>> session = Session(name="my-session")
    >>> fetch = FunctionNode(id="fetch", fn=lambda ctx: fetch_data(ctx.input))
    >>> process = FunctionNode(id="process", fn=lambda ctx: process_data(ctx.upstream["fetch"]))
    >>>
    >>> # Build graph
    >>> graph = session.create_graph("pipeline")
    >>> graph.add_step(fetch, step_id="fetch", input="http://api")
    >>> graph.add_step(process, step_id="process", depends_on=["fetch"])
    >>>
    >>> # Execute
    >>> context = ExecutionContext(session=session)
    >>> results = await graph.execute(context)
"""

# Base abstractions
from nerve.core.nodes.base import (
    FunctionNode,
    Node,
    NodeConfig,
    NodeInfo,
    NodeState,
    PersistentNode,
)

# Bash node
from nerve.core.nodes.bash import BashNode

# Agent capabilities: Budgets
from nerve.core.nodes.budget import Budget, BudgetExceededError, ResourceUsage

# Agent capabilities: Cancellation
from nerve.core.nodes.cancellation import CancellationToken, CancelledError

# Execution context
from nerve.core.nodes.context import ExecutionContext

# Graph
from nerve.core.nodes.graph import Graph, GraphStep, GraphStepList, Step, StepEvent

# History
from nerve.core.nodes.history import (
    HISTORY_BUFFER_LINES,
    HistoryError,
    HistoryReader,
    HistoryWriter,
)

# Agent capabilities: Error handling
from nerve.core.nodes.policies import ErrorPolicy

# Terminal nodes
from nerve.core.nodes.terminal import ClaudeWezTermNode, PTYNode, WezTermNode

# Agent capabilities: Tracing
from nerve.core.nodes.trace import ExecutionTrace, StepTrace

# Terminal node type alias
TerminalNode = PTYNode | WezTermNode | ClaudeWezTermNode

__all__ = [
    # Base
    "Node",
    "NodeState",
    "NodeInfo",
    "NodeConfig",
    "PersistentNode",
    "FunctionNode",
    "BashNode",
    # Context
    "ExecutionContext",
    # Graph
    "Graph",
    "GraphStep",
    "GraphStepList",
    "Step",
    "StepEvent",
    # Terminal
    "PTYNode",
    "WezTermNode",
    "ClaudeWezTermNode",
    "TerminalNode",
    # Policies
    "ErrorPolicy",
    # Budget
    "Budget",
    "ResourceUsage",
    "BudgetExceededError",
    # Cancellation
    "CancellationToken",
    "CancelledError",
    # Tracing
    "StepTrace",
    "ExecutionTrace",
    # History
    "HistoryWriter",
    "HistoryReader",
    "HistoryError",
    "HISTORY_BUFFER_LINES",
]
