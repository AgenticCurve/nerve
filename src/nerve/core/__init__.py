"""Core - Pure business logic for AI CLI control.

This module contains no knowledge of:
- Servers, clients, or networking
- Event systems or callbacks
- How it will be used

It's just pure Python primitives that can be used anywhere:
- In scripts
- In Jupyter notebooks
- Embedded in applications
- As building blocks for servers

Architecture:
    nodes/      Node abstraction (PTYNode, WezTermNode, FunctionNode, Graph, History)
    pty/        PTY/WezTerm backends for terminal nodes
    parsers/    Output parsers (Claude, Gemini, None)
    session/    Session grouping and management
    types       Pure data types

Key Concepts:
    Node:       Executable unit (terminal, function, graph)
    Graph:      Orchestrates node execution with dependencies
    Parser:     How to interpret output (specified per-command)
    Session:    Groups nodes and graphs with metadata

Example (PTY node - you own the process):
    >>> from nerve.core.nodes import ExecutionContext
    >>> from nerve.core.nodes.terminal import PTYNode
    >>> from nerve.core.session import Session
    >>>
    >>> async def main():
    ...     session = Session(name="my-session")
    ...     node = await PTYNode.create(id="my-node", session=session, command="claude")
    ...     context = ExecutionContext(session=session, input="Hello!")
    ...     response = await node.execute(context)
    ...     print(response.sections)
    ...     await node.stop()

Example (Graph execution):
    >>> from nerve.core.nodes import FunctionNode, ExecutionContext
    >>> from nerve.core.nodes.graph import Graph
    >>> from nerve.core.session import Session
    >>>
    >>> async def main():
    ...     session = Session(name="my-session")
    ...     graph = Graph(id="my-pipeline", session=session)
    ...     fetch = FunctionNode(id="fetch", session=session, fn=lambda ctx: fetch_data())
    ...     graph.add_step(fetch, step_id="fetch")
    ...     results = await graph.execute(ExecutionContext(session=session))
"""

# Nodes
# Logging
from nerve.core.logging_config import (
    JsonFormatter,
    LogConfig,
    add_file_handler,
    configure_logging,
    get_logger,
    set_level,
)
from nerve.core.nodes import (
    Budget,
    BudgetExceededError,
    CancellationToken,
    CancelledError,
    ClaudeWezTermNode,
    ErrorPolicy,
    ExecutionContext,
    ExecutionTrace,
    FunctionNode,
    Graph,
    Node,
    NodeConfig,
    NodeInfo,
    NodeState,
    PersistentNode,
    PTYNode,
    ResourceUsage,
    Step,
    StepEvent,
    StepTrace,
    TerminalNode,
    WezTermNode,
)

# History
from nerve.core.nodes.history import (
    HISTORY_BUFFER_LINES,
    HistoryError,
    HistoryReader,
    HistoryWriter,
)

# Parsers
from nerve.core.parsers import ClaudeParser, GeminiParser, NoneParser, get_parser

# PTY backends
from nerve.core.pty import (
    Backend,
    BackendConfig,
    PTYBackend,
    PTYConfig,
    PTYManager,
    PTYProcess,
    WezTermBackend,
    is_wezterm_available,
)

# Session
from nerve.core.session import (
    Session,
    SessionManager,
    SessionMetadata,
    SessionStore,
    get_default_store,
)

# Types
from nerve.core.types import (
    ParsedResponse,
    ParserType,
    Section,
    SessionState,
)

# Workflow
from nerve.core.workflow import (
    GateInfo,
    Workflow,
    WorkflowContext,
    WorkflowEvent,
    WorkflowInfo,
    WorkflowRun,
    WorkflowRunInfo,
    WorkflowState,
)

__all__ = [
    # Node abstraction
    "Node",
    "NodeState",
    "NodeConfig",
    "NodeInfo",
    "PersistentNode",
    "FunctionNode",
    # Graph
    "Graph",
    "Step",
    "StepEvent",
    # Terminal nodes
    "PTYNode",
    "WezTermNode",
    "ClaudeWezTermNode",
    "TerminalNode",
    # Context
    "ExecutionContext",
    # Agent capabilities
    "ErrorPolicy",
    "Budget",
    "ResourceUsage",
    "BudgetExceededError",
    "CancellationToken",
    "CancelledError",
    "StepTrace",
    "ExecutionTrace",
    # History
    "HistoryWriter",
    "HistoryReader",
    "HistoryError",
    "HISTORY_BUFFER_LINES",
    # Types
    "ParserType",
    "SessionState",
    "Section",
    "ParsedResponse",
    # Session
    "Session",
    "SessionManager",
    "SessionMetadata",
    "SessionStore",
    "get_default_store",
    # Workflow
    "Workflow",
    "WorkflowContext",
    "WorkflowRun",
    "WorkflowInfo",
    "WorkflowRunInfo",
    "GateInfo",
    "WorkflowEvent",
    "WorkflowState",
    # Backends
    "Backend",
    "BackendConfig",
    "PTYBackend",
    "WezTermBackend",
    "is_wezterm_available",
    # PTY (legacy)
    "PTYProcess",
    "PTYConfig",
    "PTYManager",
    # Parsers
    "ClaudeParser",
    "GeminiParser",
    "NoneParser",
    "get_parser",
    # Logging
    "configure_logging",
    "get_logger",
    "set_level",
    "add_file_handler",
    "LogConfig",
    "JsonFormatter",
]
