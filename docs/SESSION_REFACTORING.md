# Session Refactoring PRD

## Overview

Refactor the session module to become the central workspace abstraction, absorbing NodeFactory functionality and becoming the single source of truth for nodes and graphs. NerveEngine becomes a thin command dispatcher and event emitter.

**Clean Break**: No backward compatibility. All phases implemented in a single pass. No migration period, no deprecation warnings, no compatibility shims.

---

## Problem Statement

### Current Architecture Issues

**1. Duplicate Node Registry**

NerveEngine maintains `_nodes: dict[str, TerminalNode]` while also holding a Session that has its own `_nodes: dict[str, Node]`. Both are updated in sync manually:

```python
# engine.py - redundant tracking
self._session.register(node)    # Session tracks it
self._nodes[node_id] = node     # Engine ALSO tracks it
```

**2. NodeFactory is Stateless**

NodeFactory is just factory methods + config with no state. It doesn't track what it creates:

```python
factory = NodeFactory()
node = await factory.create_terminal(...)  # Created but not tracked
session.register(node)                      # Manual registration required
```

**3. Session is Underutilized**

Session is a thin dict wrapper that doesn't:
- Create nodes (NodeFactory does)
- Track graphs (nothing does)
- Provide shared context for nodes

**4. No Graph Storage**

Graphs are created ad-hoc in NerveEngine, executed, and discarded. No way to:
- Store graph definitions
- Reuse graphs across executions
- List available graphs

**5. NerveEngine Does Too Much**

Engine handles command dispatch, event emission, AND node registry - the latter is redundant with Session.

---

## Proposed Solution

### Session as Central Workspace

Session becomes:
- **The node registry** (single source of truth)
- **The graph registry** (new capability)
- **The factory** (absorbs NodeFactory methods)
- **The shared context provider** (for future node communication)

### NerveEngine as Thin Wrapper

Engine becomes:
- **Command dispatcher** (routes commands to Session)
- **Event emitter** (emits events for state changes)
- **Session manager** (manages multiple sessions for multi-workspace)

### Components Removed

- `NodeFactory` class - absorbed into Session
- `engine._nodes` dict - use Session.nodes instead
- `engine._node_factory` - Session handles creation
- `session.register()` / `session.unregister()` - auto-registration on create

---

## Phase 1: Session Absorbs NodeFactory

### Goal

Session becomes the factory and registry. NodeFactory is removed. NerveEngine delegates to Session.

### New Session API

```python
@dataclass
class Session:
    """Workspace containing nodes and graphs.

    Session is the central abstraction for managing executable units.
    It creates, registers, and manages the lifecycle of nodes and graphs.

    Example:
        session = Session(name="my-project")

        # Create nodes (auto-registered)
        claude = await session.create_node("claude", command="claude")
        shell = await session.create_node("shell", command="bash")

        # Create graphs (auto-registered)
        workflow = session.create_graph("workflow")
        workflow.add_step(claude, step_id="step1", input="Hello")

        # Execute
        context = ExecutionContext(session=session, input="...")
        result = await claude.execute(context)

        # Cleanup
        await session.stop()
    """

    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    # Registries
    nodes: dict[str, Node] = field(default_factory=dict)
    graphs: dict[str, Graph] = field(default_factory=dict)

    # Configuration (from NodeFactory)
    server_name: str = "default"
    history_enabled: bool = True
    history_base_dir: Path | None = None

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
        default_parser: ParserType = ParserType.NONE,
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
        ...

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
            ValueError: If node_id already exists.
        """
        ...

    def create_graph(
        self,
        graph_id: str,
    ) -> Graph:
        """Create and register a graph.

        Args:
            graph_id: Unique identifier for the graph.

        Returns:
            Empty Graph ready to have steps added.

        Raises:
            ValueError: If graph_id already exists.
        """
        ...

    # =========================================================================
    # Registry Access
    # =========================================================================

    def get_node(self, node_id: str) -> Node | None:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def get_graph(self, graph_id: str) -> Graph | None:
        """Get a graph by ID."""
        return self.graphs.get(graph_id)

    def list_nodes(self) -> list[str]:
        """List all node IDs."""
        return list(self.nodes.keys())

    def list_graphs(self) -> list[str]:
        """List all graph IDs."""
        return list(self.graphs.keys())

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
        ...

    def delete_graph(self, graph_id: str) -> bool:
        """Remove a graph.

        Args:
            graph_id: ID of graph to delete.

        Returns:
            True if deleted, False if not found.
        """
        ...

    async def stop(self) -> None:
        """Stop all nodes and clear registries."""
        ...
```

### New NerveEngine (Thin)

```python
@dataclass
class NerveEngine:
    """Command dispatcher and event emitter.

    NerveEngine is the server-layer adapter that:
    - Dispatches commands to Session methods
    - Emits events for state changes
    - Manages multiple sessions (multi-workspace)

    Example:
        engine = NerveEngine(event_sink=transport)

        result = await engine.execute(Command(
            type=CommandType.CREATE_NODE,
            params={"node_id": "claude", "command": "claude"},
        ))
    """

    event_sink: EventSink
    default_session: Session = field(default_factory=Session)
    sessions: dict[str, Session] = field(default_factory=dict)
    _running_graphs: dict[str, asyncio.Task] = field(default_factory=dict)
    _shutdown_requested: bool = False

    def __post_init__(self):
        self.sessions[self.default_session.id] = self.default_session

    async def execute(self, command: Command) -> CommandResult:
        """Execute a command."""
        ...

    # Command handlers delegate to Session
    async def _create_node(self, params: dict) -> dict:
        session = self._get_session(params)
        node = await session.create_node(...)
        await self._emit(EventType.NODE_CREATED, node_id=node.id)
        return {"node_id": node.id}
```

### Files to Modify

#### Core Session Module

| File | Changes |
|------|---------|
| `src/nerve/core/session/session.py` | Add factory methods, graph registry, delete methods |
| `src/nerve/core/session/manager.py` | Simplify - sessions create their own nodes |
| `src/nerve/core/session/__init__.py` | Update exports |

#### Core Nodes Module

| File | Changes |
|------|---------|
| `src/nerve/core/nodes/factory.py` | **DELETE** |
| `src/nerve/core/nodes/__init__.py` | Remove NodeFactory, BackendType exports (move to session) |

#### Server Module

| File | Changes |
|------|---------|
| `src/nerve/server/engine.py` | Remove `_nodes`, `_node_factory`. Delegate to Session. Add session_id to commands. |
| `src/nerve/server/protocols.py` | Add session commands: CREATE_SESSION, DELETE_SESSION, LIST_SESSIONS, GET_SESSION |

#### Frontends Module

| File | Changes |
|------|---------|
| `src/nerve/frontends/cli/repl.py` | Remove NodeFactory imports/usage, update docstrings, remove from REPL namespace |
| `src/nerve/frontends/sdk/client.py` | Remove NodeFactory, use Session.create_node(), remove session.register() |

#### Examples

| File | Changes |
|------|---------|
| `examples/core_only/simple_session.py` | `factory.create_terminal()` → `session.create_node()`, remove `session.register()` |
| `examples/core_only/graph_execution.py` | Same migration |
| `examples/core_only/multi_session.py` | Same migration |
| `examples/core_only/streaming.py` | Same migration |
| `examples/agents/debate.py` | Same migration |

#### Tests (Phase 1)

| File | Action | Changes |
|------|--------|---------|
| `tests/core/nodes/test_factory.py` | **DELETE** | All tests moved to test_session_factory.py |
| `tests/core/test_managers.py` | MODIFY | Remove NodeFactory usage, update to session.create_node() |
| `tests/server/test_engine.py` | MODIFY | Remove `engine._nodes` checks, use `session.nodes` |

### Detailed Code Changes

#### session.py - Add Factory Methods

```python
# NEW IMPORTS
from nerve.core.nodes.base import FunctionNode, Node
from nerve.core.nodes.terminal import (
    ClaudeWezTermNode,
    PTYNode,
    TerminalNode,
    WezTermNode,
)
from nerve.core.nodes.graph import Graph
from nerve.core.nodes.history import HistoryWriter, HistoryError
from nerve.core.types import ParserType


class BackendType(Enum):
    """Terminal backend types."""
    PTY = "pty"
    WEZTERM = "wezterm"
    CLAUDE_WEZTERM = "claude-wezterm"


@dataclass
class Session:
    # ... existing fields ...

    # NEW: Configuration
    server_name: str = "default"
    history_enabled: bool = True
    history_base_dir: Path | None = None

    # NEW: Graph registry
    graphs: dict[str, Graph] = field(default_factory=dict)

    # NEW: Factory methods
    async def create_node(
        self,
        node_id: str,
        command: str | list[str] | None = None,
        backend: BackendType | str = BackendType.PTY,
        cwd: str | None = None,
        pane_id: str | None = None,
        history: bool | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        default_parser: ParserType = ParserType.NONE,
    ) -> TerminalNode:
        if not node_id:
            raise ValueError("node_id is required")
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
                    base_dir=self.history_base_dir,
                )
            except HistoryError as e:
                logger.warning(f"Failed to create history writer: {e}")

        try:
            # Create based on backend
            if backend == BackendType.PTY:
                node = await PTYNode.create(
                    node_id=node_id,
                    command=command,
                    cwd=cwd,
                    ready_timeout=ready_timeout,
                    response_timeout=response_timeout,
                    default_parser=default_parser,
                    history_writer=history_writer,
                )
            elif backend == BackendType.WEZTERM:
                if pane_id:
                    node = await WezTermNode.attach(
                        node_id=node_id,
                        pane_id=pane_id,
                        ready_timeout=ready_timeout,
                        response_timeout=response_timeout,
                        default_parser=default_parser,
                        history_writer=history_writer,
                    )
                else:
                    node = await WezTermNode.create(
                        node_id=node_id,
                        command=command,
                        cwd=cwd,
                        ready_timeout=ready_timeout,
                        response_timeout=response_timeout,
                        default_parser=default_parser,
                        history_writer=history_writer,
                    )
            elif backend == BackendType.CLAUDE_WEZTERM:
                if not command:
                    raise ValueError("command required for claude-wezterm backend")
                node = await ClaudeWezTermNode.create(
                    node_id=node_id,
                    command=command,
                    cwd=cwd,
                    ready_timeout=ready_timeout,
                    response_timeout=response_timeout,
                    default_parser=ParserType.CLAUDE,
                    history_writer=history_writer,
                )
            else:
                raise ValueError(f"Unknown backend: {backend}")

            # Auto-register
            self.nodes[node_id] = node
            return node

        except Exception:
            if history_writer:
                history_writer.close()
            raise

    def create_function(
        self,
        node_id: str,
        fn: Callable[[ExecutionContext], Any],
    ) -> FunctionNode:
        if not node_id:
            raise ValueError("node_id is required")
        if node_id in self.nodes:
            raise ValueError(f"Node already exists: {node_id}")

        node = FunctionNode(id=node_id, fn=fn)
        self.nodes[node_id] = node
        return node

    def create_graph(self, graph_id: str) -> Graph:
        if not graph_id:
            raise ValueError("graph_id is required")
        if graph_id in self.graphs:
            raise ValueError(f"Graph already exists: {graph_id}")

        graph = Graph(id=graph_id)
        self.graphs[graph_id] = graph
        return graph

    # NEW: Delete methods
    async def delete_node(self, node_id: str) -> bool:
        node = self.nodes.pop(node_id, None)
        if node is None:
            return False
        if hasattr(node, "stop"):
            await node.stop()
        return True

    def delete_graph(self, graph_id: str) -> bool:
        return self.graphs.pop(graph_id, None) is not None

    # REMOVE: register() and unregister() - no longer needed
```

#### cli/repl.py - Remove NodeFactory

```python
# BEFORE (lines 34-46):
from nerve.core import NodeFactory, ParserType

factory = NodeFactory()
claude = await factory.create_terminal("claude", command="claude")
gemini = await factory.create_terminal("gemini", command="gemini")

session = Session()
session.register(claude)
session.register(gemini)

# AFTER:
from nerve.core.session import Session
from nerve.core import ParserType

session = Session()
claude = await session.create_node("claude", command="claude")
gemini = await session.create_node("gemini", command="gemini")
```

```python
# BEFORE (REPL namespace, lines 151-163):
NodeFactory,
...
"NodeFactory": NodeFactory,

# AFTER:
# DELETE NodeFactory from imports and namespace
# Session is already available
```

```python
# BEFORE (help text, line 180):
print("Use NodeFactory to create terminal nodes")

# AFTER:
print("Use session.create_node() to create terminal nodes")
```

#### sdk/client.py - Remove NodeFactory

```python
# BEFORE (lines 186-249):
from nerve.core.nodes import NodeFactory

factory = NodeFactory()
...
node = await self._standalone_factory.create_terminal(
    node_id=node_id,
    command=command,
)
self._standalone_session.register(node)

# AFTER:
# No NodeFactory import needed

node = await self._standalone_session.create_node(
    node_id=node_id,
    command=command,
)
# No register() call needed - auto-registered
```

#### engine.py - Thin Wrapper

```python
@dataclass
class NerveEngine:
    event_sink: EventSink
    _server_name: str = "default"
    _default_session: Session | None = field(default=None, repr=False)
    _sessions: dict[str, Session] = field(default_factory=dict, repr=False)
    _running_graphs: dict[str, asyncio.Task] = field(default_factory=dict)
    _shutdown_requested: bool = field(default=False, repr=False)

    # REMOVED: _node_factory
    # REMOVED: _nodes

    def __post_init__(self):
        if self._default_session is None:
            self._default_session = Session(
                server_name=self._server_name,
            )
        self._sessions[self._default_session.id] = self._default_session

    def _get_session(self, params: dict) -> Session:
        """Get session from params or return default."""
        session_id = params.get("session_id")
        if session_id:
            session = self._sessions.get(session_id)
            if not session:
                raise ValueError(f"Session not found: {session_id}")
            return session
        return self._default_session

    async def _create_node(self, params: dict) -> dict:
        session = self._get_session(params)

        node = await session.create_node(
            node_id=params.get("node_id"),
            command=params.get("command"),
            backend=params.get("backend", "pty"),
            cwd=params.get("cwd"),
            pane_id=params.get("pane_id"),
            history=params.get("history", True),
        )

        await self._emit(
            EventType.NODE_CREATED,
            data={"command": params.get("command")},
            node_id=node.id,
        )

        asyncio.create_task(self._monitor_node(node))

        return {"node_id": node.id}

    async def _delete_node(self, params: dict) -> dict:
        session = self._get_session(params)
        node_id = params.get("node_id")

        deleted = await session.delete_node(node_id)
        if not deleted:
            raise ValueError(f"Node not found: {node_id}")

        await self._emit(EventType.NODE_DELETED, node_id=node_id)
        return {"deleted": True}

    async def _list_nodes(self, params: dict) -> dict:
        session = self._get_session(params)

        nodes_info = []
        for node_id in session.list_nodes():
            node = session.get_node(node_id)
            if node and hasattr(node, "to_info"):
                info = node.to_info()
                nodes_info.append({
                    "id": node_id,
                    "type": info.node_type,
                    "state": info.state.name,
                    **info.metadata,
                })

        return {
            "nodes": session.list_nodes(),
            "nodes_info": nodes_info,
        }

    async def _get_node(self, params: dict) -> dict:
        session = self._get_session(params)
        node_id = params.get("node_id")

        node = session.get_node(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        info = node.to_info()
        return {
            "node_id": node.id,
            "type": info.node_type,
            "state": info.state.name,
        }

    # ... other handlers similarly updated to use session ...
```

---

## Phase 2: Session CLI and Multi-Workspace

### Goal

Add CLI commands for session management and enable multi-workspace support in server.

### New CLI Commands

```
nerve session list                    # List all sessions
nerve session create <name>           # Create new session
nerve session delete <id>             # Delete session
nerve session info <id>               # Show session details
nerve session switch <id>             # Switch active session (for REPL)

nerve node list [--session <id>]      # List nodes (in session)
nerve node create <id> [--session]    # Create node in session
nerve node delete <id> [--session]    # Delete node from session

nerve graph list [--session <id>]     # List graphs
nerve graph create <id> [--session]   # Create graph in session
nerve graph delete <id> [--session]   # Delete graph
nerve graph run <id> [--session]      # Execute graph
```

### New Command Types

```python
class CommandType(Enum):
    # Existing node commands...

    # NEW: Session management
    CREATE_SESSION = auto()
    DELETE_SESSION = auto()
    LIST_SESSIONS = auto()
    GET_SESSION = auto()

    # NEW: Graph management
    CREATE_GRAPH = auto()
    DELETE_GRAPH = auto()
    LIST_GRAPHS = auto()
    GET_GRAPH = auto()
    RUN_GRAPH = auto()  # Renamed from EXECUTE_GRAPH for consistency
```

### New Event Types

```python
class EventType(Enum):
    # Existing...

    # NEW: Session lifecycle
    SESSION_CREATED = auto()
    SESSION_DELETED = auto()

    # NEW: Graph lifecycle
    GRAPH_CREATED = auto()
    GRAPH_DELETED = auto()
```

### Files to Modify

#### Server Module

| File | Changes |
|------|---------|
| `src/nerve/server/protocols.py` | Add session/graph command and event types |
| `src/nerve/server/engine.py` | Add session/graph command handlers |

#### CLI Module

| File | Changes |
|------|---------|
| `src/nerve/frontends/cli/main.py` | Add session subcommand group |
| `src/nerve/frontends/cli/commands/session.py` | **NEW** - Session CLI commands |
| `src/nerve/frontends/cli/commands/graph.py` | **NEW** - Graph CLI commands |
| `src/nerve/frontends/cli/repl.py` | Add session switching, show active session |

### CLI Implementation

#### commands/session.py (NEW)

```python
"""Session management commands."""

import click

from nerve.client import NerveClient


@click.group()
def session():
    """Manage sessions."""
    pass


@session.command("list")
@click.pass_context
def list_sessions(ctx):
    """List all sessions."""
    client: NerveClient = ctx.obj["client"]
    result = client.send_command("LIST_SESSIONS")

    if not result.success:
        click.echo(f"Error: {result.error}", err=True)
        return

    sessions = result.data.get("sessions", [])
    if not sessions:
        click.echo("No sessions.")
        return

    click.echo(f"{'ID':<12} {'Name':<20} {'Nodes':<8} {'Graphs':<8}")
    click.echo("-" * 50)
    for s in sessions:
        click.echo(f"{s['id']:<12} {s['name']:<20} {s['node_count']:<8} {s['graph_count']:<8}")


@session.command("create")
@click.argument("name")
@click.option("--description", "-d", default="", help="Session description")
@click.pass_context
def create_session(ctx, name: str, description: str):
    """Create a new session."""
    client: NerveClient = ctx.obj["client"]
    result = client.send_command("CREATE_SESSION", {
        "name": name,
        "description": description,
    })

    if result.success:
        click.echo(f"Created session: {result.data['session_id']}")
    else:
        click.echo(f"Error: {result.error}", err=True)


@session.command("delete")
@click.argument("session_id")
@click.option("--force", "-f", is_flag=True, help="Delete even if nodes exist")
@click.pass_context
def delete_session(ctx, session_id: str, force: bool):
    """Delete a session."""
    client: NerveClient = ctx.obj["client"]
    result = client.send_command("DELETE_SESSION", {
        "session_id": session_id,
        "force": force,
    })

    if result.success:
        click.echo(f"Deleted session: {session_id}")
    else:
        click.echo(f"Error: {result.error}", err=True)


@session.command("info")
@click.argument("session_id")
@click.pass_context
def session_info(ctx, session_id: str):
    """Show session details."""
    client: NerveClient = ctx.obj["client"]
    result = client.send_command("GET_SESSION", {"session_id": session_id})

    if not result.success:
        click.echo(f"Error: {result.error}", err=True)
        return

    s = result.data
    click.echo(f"ID:          {s['id']}")
    click.echo(f"Name:        {s['name']}")
    click.echo(f"Description: {s.get('description', '')}")
    click.echo(f"Created:     {s['created_at']}")
    click.echo(f"Nodes:       {', '.join(s['nodes']) or 'none'}")
    click.echo(f"Graphs:      {', '.join(s['graphs']) or 'none'}")
```

#### commands/graph.py (NEW)

```python
"""Graph management commands."""

import click

from nerve.client import NerveClient


@click.group()
def graph():
    """Manage graphs."""
    pass


@graph.command("list")
@click.option("--session", "-s", "session_id", help="Session ID")
@click.pass_context
def list_graphs(ctx, session_id: str | None):
    """List all graphs."""
    client: NerveClient = ctx.obj["client"]
    params = {}
    if session_id:
        params["session_id"] = session_id

    result = client.send_command("LIST_GRAPHS", params)

    if not result.success:
        click.echo(f"Error: {result.error}", err=True)
        return

    graphs = result.data.get("graphs", [])
    if not graphs:
        click.echo("No graphs.")
        return

    for g in graphs:
        click.echo(f"  {g['id']} ({g['step_count']} steps)")


@graph.command("create")
@click.argument("graph_id")
@click.option("--session", "-s", "session_id", help="Session ID")
@click.pass_context
def create_graph(ctx, graph_id: str, session_id: str | None):
    """Create a new graph."""
    client: NerveClient = ctx.obj["client"]
    params = {"graph_id": graph_id}
    if session_id:
        params["session_id"] = session_id

    result = client.send_command("CREATE_GRAPH", params)

    if result.success:
        click.echo(f"Created graph: {graph_id}")
    else:
        click.echo(f"Error: {result.error}", err=True)


@graph.command("delete")
@click.argument("graph_id")
@click.option("--session", "-s", "session_id", help="Session ID")
@click.pass_context
def delete_graph(ctx, graph_id: str, session_id: str | None):
    """Delete a graph."""
    client: NerveClient = ctx.obj["client"]
    params = {"graph_id": graph_id}
    if session_id:
        params["session_id"] = session_id

    result = client.send_command("DELETE_GRAPH", params)

    if result.success:
        click.echo(f"Deleted graph: {graph_id}")
    else:
        click.echo(f"Error: {result.error}", err=True)


@graph.command("run")
@click.argument("graph_id")
@click.option("--session", "-s", "session_id", help="Session ID")
@click.option("--input", "-i", "input_data", help="Input data (JSON)")
@click.pass_context
def run_graph(ctx, graph_id: str, session_id: str | None, input_data: str | None):
    """Execute a graph."""
    client: NerveClient = ctx.obj["client"]
    params = {"graph_id": graph_id}
    if session_id:
        params["session_id"] = session_id
    if input_data:
        import json
        params["input"] = json.loads(input_data)

    result = client.send_command("RUN_GRAPH", params)

    if result.success:
        click.echo(f"Graph completed: {graph_id}")
        click.echo(f"Results: {result.data.get('results', {})}")
    else:
        click.echo(f"Error: {result.error}", err=True)
```

### Engine Session Handlers

```python
# In engine.py

async def _create_session(self, params: dict) -> dict:
    """Create a new session."""
    name = params.get("name", "")
    description = params.get("description", "")

    session = Session(
        name=name,
        description=description,
        server_name=self._server_name,
    )
    self._sessions[session.id] = session

    await self._emit(
        EventType.SESSION_CREATED,
        data={"name": name},
        session_id=session.id,
    )

    return {"session_id": session.id}


async def _delete_session(self, params: dict) -> dict:
    """Delete a session."""
    session_id = params["session_id"]
    force = params.get("force", False)

    if session_id == self._default_session.id:
        raise ValueError("Cannot delete default session")

    session = self._sessions.get(session_id)
    if not session:
        raise ValueError(f"Session not found: {session_id}")

    if session.nodes and not force:
        raise ValueError(f"Session has {len(session.nodes)} nodes. Use --force to delete.")

    await session.stop()
    del self._sessions[session_id]

    await self._emit(EventType.SESSION_DELETED, session_id=session_id)

    return {"deleted": True}


async def _list_sessions(self, params: dict) -> dict:
    """List all sessions."""
    sessions = []
    for session in self._sessions.values():
        sessions.append({
            "id": session.id,
            "name": session.name,
            "description": session.description,
            "node_count": len(session.nodes),
            "graph_count": len(session.graphs),
            "created_at": session.created_at.isoformat(),
        })
    return {"sessions": sessions}


async def _get_session(self, params: dict) -> dict:
    """Get session info."""
    session_id = params["session_id"]
    session = self._sessions.get(session_id)

    if not session:
        raise ValueError(f"Session not found: {session_id}")

    return {
        "id": session.id,
        "name": session.name,
        "description": session.description,
        "nodes": session.list_nodes(),
        "graphs": session.list_graphs(),
        "created_at": session.created_at.isoformat(),
    }


async def _create_graph(self, params: dict) -> dict:
    """Create a graph."""
    session = self._get_session(params)
    graph_id = params["graph_id"]

    graph = session.create_graph(graph_id)

    await self._emit(
        EventType.GRAPH_CREATED,
        data={"graph_id": graph_id},
    )

    return {"graph_id": graph.id}


async def _delete_graph(self, params: dict) -> dict:
    """Delete a graph."""
    session = self._get_session(params)
    graph_id = params["graph_id"]

    deleted = session.delete_graph(graph_id)
    if not deleted:
        raise ValueError(f"Graph not found: {graph_id}")

    await self._emit(EventType.GRAPH_DELETED, data={"graph_id": graph_id})

    return {"deleted": True}


async def _list_graphs(self, params: dict) -> dict:
    """List graphs in session."""
    session = self._get_session(params)

    graphs = []
    for graph_id in session.list_graphs():
        graph = session.get_graph(graph_id)
        if graph:
            graphs.append({
                "id": graph_id,
                "step_count": len(graph.list_steps()),
            })

    return {"graphs": graphs}
```

---

## Phase 3: Cleanup and Deletion

### Goal

Remove all deprecated code, duplicate registries, and unused modules. Verify clean break.

### Files to DELETE

| File | Reason |
|------|--------|
| `src/nerve/core/nodes/factory.py` | Absorbed into Session |
| `tests/core/nodes/test_factory.py` | Tests moved to test_session.py |

### Code to REMOVE from Existing Files

#### `src/nerve/core/nodes/__init__.py`

Remove exports:
```python
# DELETE these lines
from nerve.core.nodes.factory import BackendType, NodeFactory
# DELETE from __all__
"NodeFactory",
"BackendType",
```

#### `src/nerve/core/__init__.py`

Remove exports:
```python
# DELETE these lines
from nerve.core.nodes import BackendType, NodeFactory
# DELETE from __all__
"NodeFactory",
"BackendType",
```

#### `src/nerve/__init__.py`

Remove exports (if present):
```python
# DELETE any NodeFactory, BackendType exports
```

#### `src/nerve/core/session/session.py`

Remove old methods:
```python
# DELETE these methods entirely
def register(self, node: Node, name: str | None = None) -> None:
    ...

def unregister(self, name: str) -> Node | None:
    ...

def get(self, name: str) -> Node | None:  # Renamed to get_node()
    ...

def list_ready_nodes(self) -> list[str]:  # Remove if unused
    ...

def get_node_info(self) -> dict[str, NodeInfo]:  # Simplify or remove
    ...

def _collect_persistent_nodes(self) -> list[Node]:  # Internalize into stop()
    ...
```

#### `src/nerve/core/session/manager.py`

Simplify or remove:
```python
# EVALUATE: SessionManager may be redundant if NerveEngine manages sessions
# If kept, remove any NodeFactory references
```

#### `src/nerve/server/engine.py`

Remove:
```python
# DELETE these fields
_node_factory: NodeFactory | None = field(default=None, repr=False)
_nodes: dict[str, TerminalNode] = field(default_factory=dict, repr=False)

# DELETE from __post_init__
if self._node_factory is None:
    self._node_factory = NodeFactory(server_name=self._server_name)

# DELETE any direct _nodes access - use session.nodes instead
```

### Imports to REMOVE

Search and remove all occurrences:
```python
# Remove from ALL files
from nerve.core.nodes import NodeFactory
from nerve.core.nodes import BackendType
from nerve.core.nodes.factory import NodeFactory, BackendType
```

### Verification Commands

Run after cleanup to verify no references remain:

```bash
# Verify NodeFactory is gone from src/
grep -r "NodeFactory" src/ --include="*.py"
# Should return: nothing

# Verify NodeFactory is gone from tests/
grep -r "NodeFactory" tests/ --include="*.py"
# Should return: nothing

# Verify BackendType moved to session
grep -r "from nerve.core.nodes import.*BackendType" src/ --include="*.py"
# Should return: nothing (BackendType now in session)

# Verify no register/unregister calls (excluding atexit.register)
grep -r "session\.register\(" src/ --include="*.py"
grep -r "\.unregister\(" src/ --include="*.py"
# Should return: nothing

# Verify no register/unregister in tests
grep -r "session\.register\(" tests/ --include="*.py"
# Should return: nothing

# Verify factory.create_ pattern is gone
grep -r "factory\.create_" src/ --include="*.py"
grep -r "factory\.create_" tests/ --include="*.py"
grep -r "factory\.create_" examples/ --include="*.py"
# Should return: nothing

# Verify factory.py deleted
ls src/nerve/core/nodes/factory.py
# Should return: No such file or directory

# Verify test_factory.py deleted
ls tests/core/nodes/test_factory.py
# Should return: No such file or directory

# Verify CLI REPL doesn't expose NodeFactory
grep -r "NodeFactory" src/nerve/frontends/ --include="*.py"
# Should return: nothing
```

---

## Test Specification

### Tests to DELETE

| File | Reason |
|------|--------|
| `tests/core/nodes/test_factory.py` | NodeFactory removed; tests migrated to test_session.py |

### Tests to ADD

#### `tests/core/session/test_session_factory.py` (NEW)

```python
"""Tests for Session factory methods."""

import pytest
from nerve.core.session import Session, BackendType


class TestSessionCreateNode:
    """Tests for Session.create_node()."""

    async def test_create_node_pty_backend(self):
        """Create node with PTY backend."""
        ...

    async def test_create_node_wezterm_backend(self):
        """Create node with WezTerm backend."""
        ...

    async def test_create_node_claude_wezterm_backend(self):
        """Create node with ClaudeWezTerm backend."""
        ...

    async def test_create_node_auto_registers(self):
        """Node is automatically registered in session.nodes."""
        ...

    async def test_create_node_duplicate_id_raises(self):
        """Duplicate node_id raises ValueError."""
        ...

    async def test_create_node_empty_id_raises(self):
        """Empty node_id raises ValueError."""
        ...

    async def test_create_node_string_backend(self):
        """Backend can be string or BackendType enum."""
        ...

    async def test_create_node_history_enabled(self):
        """History writer created when history=True."""
        ...

    async def test_create_node_history_disabled(self):
        """No history writer when history=False."""
        ...

    async def test_create_node_inherits_session_history_setting(self):
        """Node inherits session.history_enabled when history=None."""
        ...


class TestSessionCreateFunction:
    """Tests for Session.create_function()."""

    def test_create_function_sync(self):
        """Create function node with sync callable."""
        ...

    def test_create_function_async(self):
        """Create function node with async callable."""
        ...

    def test_create_function_auto_registers(self):
        """Function node is auto-registered."""
        ...

    def test_create_function_duplicate_id_raises(self):
        """Duplicate node_id raises ValueError."""
        ...


class TestSessionCreateGraph:
    """Tests for Session.create_graph()."""

    def test_create_graph(self):
        """Create empty graph."""
        ...

    def test_create_graph_auto_registers(self):
        """Graph is registered in session.graphs."""
        ...

    def test_create_graph_duplicate_id_raises(self):
        """Duplicate graph_id raises ValueError."""
        ...


class TestSessionDeleteNode:
    """Tests for Session.delete_node()."""

    async def test_delete_node_stops_and_removes(self):
        """Delete stops node and removes from registry."""
        ...

    async def test_delete_node_not_found_returns_false(self):
        """Delete returns False if node not found."""
        ...


class TestSessionDeleteGraph:
    """Tests for Session.delete_graph()."""

    def test_delete_graph_removes(self):
        """Delete removes graph from registry."""
        ...

    def test_delete_graph_not_found_returns_false(self):
        """Delete returns False if graph not found."""
        ...


class TestSessionLifecycle:
    """Tests for Session lifecycle methods."""

    async def test_stop_stops_all_nodes(self):
        """Session.stop() stops all persistent nodes."""
        ...

    async def test_stop_clears_registries(self):
        """Session.stop() clears nodes and graphs."""
        ...
```

#### `tests/server/test_engine_sessions.py` (NEW)

```python
"""Tests for NerveEngine session management."""

import pytest
from nerve.server import NerveEngine, Command, CommandType


class TestEngineSessionCommands:
    """Tests for session management commands."""

    async def test_create_session(self):
        """CREATE_SESSION creates new session."""
        ...

    async def test_delete_session(self):
        """DELETE_SESSION removes session."""
        ...

    async def test_delete_default_session_raises(self):
        """Cannot delete default session."""
        ...

    async def test_delete_session_with_nodes_requires_force(self):
        """DELETE_SESSION with nodes requires force=True."""
        ...

    async def test_list_sessions(self):
        """LIST_SESSIONS returns all sessions."""
        ...

    async def test_get_session(self):
        """GET_SESSION returns session info."""
        ...


class TestEngineGraphCommands:
    """Tests for graph management commands."""

    async def test_create_graph(self):
        """CREATE_GRAPH creates new graph."""
        ...

    async def test_delete_graph(self):
        """DELETE_GRAPH removes graph."""
        ...

    async def test_list_graphs(self):
        """LIST_GRAPHS returns graphs in session."""
        ...

    async def test_run_graph(self):
        """RUN_GRAPH executes graph."""
        ...


class TestEngineSessionRouting:
    """Tests for session_id parameter routing."""

    async def test_create_node_in_specific_session(self):
        """CREATE_NODE with session_id creates in that session."""
        ...

    async def test_create_node_default_session(self):
        """CREATE_NODE without session_id uses default."""
        ...

    async def test_invalid_session_id_raises(self):
        """Invalid session_id raises error."""
        ...
```

#### `tests/cli/test_session_commands.py` (NEW)

```python
"""Tests for session CLI commands."""

from click.testing import CliRunner


class TestSessionCLI:
    """Tests for nerve session commands."""

    def test_session_list(self):
        """nerve session list shows sessions."""
        ...

    def test_session_create(self):
        """nerve session create creates session."""
        ...

    def test_session_delete(self):
        """nerve session delete removes session."""
        ...

    def test_session_info(self):
        """nerve session info shows details."""
        ...
```

#### `tests/cli/test_graph_commands.py` (NEW)

```python
"""Tests for graph CLI commands."""

from click.testing import CliRunner


class TestGraphCLI:
    """Tests for nerve graph commands."""

    def test_graph_list(self):
        """nerve graph list shows graphs."""
        ...

    def test_graph_create(self):
        """nerve graph create creates graph."""
        ...

    def test_graph_delete(self):
        """nerve graph delete removes graph."""
        ...

    def test_graph_run(self):
        """nerve graph run executes graph."""
        ...
```

### Tests to MODIFY

#### `tests/core/session/test_session.py`

Changes:
- Remove tests for `register()`, `unregister()`, `get()`
- Add tests for `get_node()`, `get_graph()`
- Update any tests using old API

#### `tests/core/test_managers.py`

Changes:
- Remove any NodeFactory usage
- Update to use `session.create_node()` API
- Remove tests for SessionManager if it's removed

#### `tests/core/nodes/test_graph.py`

Changes:
- Remove any NodeFactory usage
- Update to use `session.create_node()` API
- Remove `session.register()` calls

#### `tests/server/test_engine.py`

Changes:
- Remove tests that check `engine._nodes` directly
- Update to verify via `session.nodes` instead
- Remove NodeFactory instantiation
- Add session_id parameter to relevant tests

#### `tests/frontends/sdk/test_client.py`

Changes:
- Remove any NodeFactory references
- Update to use `session.create_node()` API
- Remove `session.register()` calls

#### `tests/integration/*.py` (if any)

Changes:
- Update all `factory.create_terminal()` → `session.create_node()`
- Remove `session.register()` calls
- Update imports

### Test Migration Summary

| Action | Count | Files |
|--------|-------|-------|
| DELETE | 1 | `test_factory.py` |
| ADD | 4 | `test_session_factory.py`, `test_engine_sessions.py`, `test_session_commands.py`, `test_graph_commands.py` |
| MODIFY | 6 | `test_session.py`, `test_managers.py`, `test_graph.py`, `test_engine.py`, `test_client.py`, integration tests |

---

## Deliverables

### Phase 1: Session Absorbs NodeFactory

1. Session with factory methods (`create_node`, `create_function`, `create_graph`)
2. Session with graph registry (`graphs: dict[str, Graph]`)
3. Session with delete methods (`delete_node`, `delete_graph`)
4. BackendType enum moved to session module
5. NerveEngine delegates to Session (no `_nodes`, no `_node_factory`)
6. All examples migrated to new API

### Phase 2: Session CLI and Multi-Workspace

1. New CommandTypes: `CREATE_SESSION`, `DELETE_SESSION`, `LIST_SESSIONS`, `GET_SESSION`, `CREATE_GRAPH`, `DELETE_GRAPH`, `LIST_GRAPHS`, `RUN_GRAPH`
2. New EventTypes: `SESSION_CREATED`, `SESSION_DELETED`, `GRAPH_CREATED`, `GRAPH_DELETED`
3. Engine handlers for all new commands
4. CLI commands: `nerve session list|create|delete|info`
5. CLI commands: `nerve graph list|create|delete|run`
6. REPL session switching

### Phase 3: Cleanup and Deletion

1. `src/nerve/core/nodes/factory.py` deleted
2. `tests/core/nodes/test_factory.py` deleted
3. All NodeFactory imports removed
4. All `register()`/`unregister()` methods removed
5. All `engine._nodes` references removed
6. Verification commands pass (no stale references)

---

## Success Criteria

### Code Verification

- [ ] `grep -r "NodeFactory" src/` returns nothing
- [ ] `grep -r "\.register\(" src/` returns nothing (session-related)
- [ ] `grep -r "\.unregister\(" src/` returns nothing
- [ ] `ls src/nerve/core/nodes/factory.py` returns "No such file"
- [ ] `ls tests/core/nodes/test_factory.py` returns "No such file"

### Functional Verification

- [ ] `session.create_node()` works for PTY backend
- [ ] `session.create_node()` works for WezTerm backend
- [ ] `session.create_node()` works for ClaudeWezTerm backend
- [ ] `session.create_graph()` creates and registers graph
- [ ] `session.delete_node()` stops and removes node
- [ ] `session.delete_graph()` removes graph
- [ ] `session.stop()` stops all nodes

### Server Verification

- [ ] Engine creates nodes via Session
- [ ] Engine supports `session_id` parameter routing
- [ ] Engine manages multiple sessions
- [ ] All node/graph commands work with session_id

### CLI Verification

- [ ] `nerve session list` shows sessions
- [ ] `nerve session create <name>` creates session
- [ ] `nerve session delete <id>` deletes session
- [ ] `nerve session info <id>` shows details
- [ ] `nerve graph list` shows graphs
- [ ] `nerve graph create <id>` creates graph
- [ ] `nerve graph delete <id>` deletes graph
- [ ] `nerve graph run <id>` executes graph

### Test Verification

- [ ] All tests pass
- [ ] No tests reference NodeFactory
- [ ] No tests call `session.register()`
- [ ] New session factory tests exist
- [ ] New CLI tests exist

---

## Appendix: Complete File Change Summary

### Files to DELETE

| File | Phase |
|------|-------|
| `src/nerve/core/nodes/factory.py` | 3 |
| `tests/core/nodes/test_factory.py` | 3 |

### Files to CREATE

| File | Phase | Purpose |
|------|-------|---------|
| `src/nerve/frontends/cli/commands/session.py` | 2 | Session CLI commands |
| `src/nerve/frontends/cli/commands/graph.py` | 2 | Graph CLI commands |
| `tests/core/session/test_session_factory.py` | 1 | Session factory method tests |
| `tests/server/test_engine_sessions.py` | 2 | Engine session/graph command tests |
| `tests/cli/test_session_commands.py` | 2 | Session CLI tests |
| `tests/cli/test_graph_commands.py` | 2 | Graph CLI tests |

### Files to MODIFY

| File | Phase | Changes |
|------|-------|---------|
| `src/nerve/core/session/session.py` | 1 | Add factory methods, graph registry, delete methods, remove register/unregister |
| `src/nerve/core/session/__init__.py` | 1 | Export BackendType, update exports |
| `src/nerve/core/session/manager.py` | 1 | Simplify or evaluate for removal |
| `src/nerve/core/nodes/__init__.py` | 3 | Remove NodeFactory, BackendType exports |
| `src/nerve/core/__init__.py` | 3 | Remove NodeFactory, BackendType exports |
| `src/nerve/server/engine.py` | 1 | Remove _nodes, _node_factory, delegate to Session, add session handlers |
| `src/nerve/server/protocols.py` | 2 | Add session/graph CommandTypes and EventTypes |
| `src/nerve/frontends/cli/main.py` | 2 | Add session and graph command groups |
| `src/nerve/frontends/cli/repl.py` | 1,2 | Remove NodeFactory from namespace, update docstrings, add session switching |
| `src/nerve/frontends/sdk/client.py` | 1 | Remove NodeFactory, use Session.create_node(), remove session.register() |
| `examples/core_only/simple_session.py` | 1 | Migrate to session.create_node() |
| `examples/core_only/graph_execution.py` | 1 | Migrate to session.create_node() |
| `examples/core_only/multi_session.py` | 1 | Migrate to session.create_node() |
| `examples/core_only/streaming.py` | 1 | Migrate to session.create_node() |
| `examples/agents/debate.py` | 1 | Migrate to session.create_node() |
| `tests/core/test_managers.py` | 1 | Remove NodeFactory, update to new API |
| `tests/core/nodes/test_graph.py` | 1 | Remove NodeFactory, remove session.register() |
| `tests/server/test_engine.py` | 1 | Remove _nodes checks, update to session API |
| `tests/frontends/sdk/test_client.py` | 1 | Remove NodeFactory, update to session API |

### Import Changes Required

Remove from all files:
```python
from nerve.core.nodes import NodeFactory
from nerve.core.nodes import BackendType
from nerve.core.nodes.factory import NodeFactory, BackendType
```

Replace with:
```python
from nerve.core.session import Session, BackendType
```

### Method Renames/Removals

| Old | New | Notes |
|-----|-----|-------|
| `session.register(node)` | Auto-registered by `session.create_node()` | Remove all calls |
| `session.unregister(id)` | `session.delete_node(id)` | Also stops node |
| `session.get(id)` | `session.get_node(id)` | Renamed for clarity |
| `factory.create_terminal()` | `session.create_node()` | Same parameters |
| `factory.create_function()` | `session.create_function()` | Same parameters |
| `factory.create_graph()` | `session.create_graph()` | Same parameters |
| `factory.stop_node(node)` | `session.delete_node(id)` | By ID, not node object |
