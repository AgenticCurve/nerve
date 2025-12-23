"""Nerve - Programmatic control layer for AI CLI agents.

Nerve provides a layered architecture for controlling AI CLI tools like
Claude Code and Gemini CLI programmatically.

Layers:
    core/       Pure business logic (nodes, parsers, graphs, sessions)
    server/     Stateful wrapper with event emission
    transport/  Communication adapters (socket, HTTP, in-process)
    frontends/  User interfaces (CLI, SDK, MCP)

Key Concepts:
    Node:       Executable unit (terminal, function, graph)
    Graph:      Orchestrates node execution with dependencies
    Parser:     How to interpret output (specified per-command)
    Session:    Optional grouping of nodes with metadata

Quick Start (create a terminal node):
    >>> from nerve.core.nodes import NodeFactory, ExecutionContext
    >>> from nerve.core.session import Session
    >>>
    >>> factory = NodeFactory()
    >>> node = await factory.create_terminal("my-node", command="claude")
    >>> session = Session()
    >>> session.register(node)
    >>> context = ExecutionContext(session=session, input="Hello!")
    >>> response = await node.execute(context)
    >>> print(response.sections)
    >>> await node.stop()

With Graph execution:
    >>> from nerve.core.nodes import Graph, FunctionNode, ExecutionContext
    >>>
    >>> graph = Graph(id="pipeline")
    >>> fetch = FunctionNode(id="fetch", fn=lambda ctx: fetch_data())
    >>> graph.add_step(fetch, step_id="fetch")
    >>> results = await graph.execute(ExecutionContext(session=session))

With server:
    >>> from nerve.server import NerveEngine
    >>> from nerve.transport import InProcessTransport
    >>> engine = NerveEngine(event_sink=transport)
"""

from nerve.__version__ import __version__

# Re-export core for convenience
from nerve.core import (
    BackendType,
    ClaudeWezTermNode,
    ExecutionContext,
    FunctionNode,
    Graph,
    Node,
    NodeFactory,
    NodeState,
    ParsedResponse,
    ParserType,
    PTYNode,
    Section,
    Session,
    SessionManager,
    SessionState,
    Step,
    WezTermNode,
)

__all__ = [
    "__version__",
    # Nodes
    "Node",
    "NodeState",
    "PTYNode",
    "WezTermNode",
    "ClaudeWezTermNode",
    "FunctionNode",
    "NodeFactory",
    # Graph
    "Graph",
    "Step",
    # Context
    "ExecutionContext",
    # Session
    "Session",
    "SessionManager",
    "SessionState",
    # Types
    "BackendType",
    "ParserType",
    "ParsedResponse",
    "Section",
]
