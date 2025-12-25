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
    Session:    Groups nodes and graphs with metadata

Quick Start (create a terminal node):
    >>> from nerve.core.nodes import ExecutionContext
    >>> from nerve.core.nodes.terminal import PTYNode
    >>> from nerve.core.session import Session
    >>>
    >>> session = Session(name="my-session")
    >>> node = await PTYNode.create(id="my-node", session=session, command="claude")
    >>> context = ExecutionContext(session=session, input="Hello!")
    >>> response = await node.execute(context)
    >>> print(response.sections)
    >>> await node.stop()

With Graph execution:
    >>> from nerve.core.nodes import FunctionNode, ExecutionContext
    >>> from nerve.core.nodes.graph import Graph
    >>> from nerve.core.session import Session
    >>>
    >>> session = Session(name="my-session")
    >>> graph = Graph(id="pipeline", session=session)
    >>> fetch = FunctionNode(id="fetch", session=session, fn=lambda ctx: fetch_data())
    >>> graph.add_step(fetch, step_id="fetch")
    >>> results = await graph.execute(ExecutionContext(session=session))

With server:
    >>> from nerve.server import build_nerve_engine
    >>> from nerve.transport import InProcessTransport
    >>> engine = build_nerve_engine(event_sink=transport)
"""

from nerve.__version__ import __version__

# Re-export core for convenience
from nerve.core import (
    ClaudeWezTermNode,
    ExecutionContext,
    FunctionNode,
    Graph,
    Node,
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
    "ParserType",
    "ParsedResponse",
    "Section",
]
