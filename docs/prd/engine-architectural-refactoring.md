# PRD: Engine.py Architectural Refactoring

**Status**: Draft
**Version**: 2.3
**Author**: Architecture Team
**Created**: 2025-12-26
**Updated**: 2025-12-26
**Target Release**: TBD

**v2.3 Changes**:
- Fixed command count: 28 → 25 (verified against protocols.py)
- Fixed SessionHandler encapsulation: added `has_session()` method to SessionRegistry
- Fixed ServerHandler type bug: `list_sessions()` now returns Session objects via `get_all_sessions()`
- Added missing OUTPUT_PARSED event to NodeInteractionHandler.execute_input
- Added missing proxy cleanup to NodeLifecycleHandler.delete_node
- Added default session initialization to builder pattern
- Fixed validation pattern consistency: use ValidationHelpers.get_node() everywhere
- Fixed ServerHandler coupling: added `cancel_all_graphs()` to GraphHandler
- Fixed confusing node_id reassignment in delete_node

**v2.2 Changes**:
- Fixed CommandType names to match actual codebase (GET_GRAPH, GET_SESSION not GET_GRAPH_INFO, GET_SESSION_INFO)
- Removed non-existent SWITCH_SESSION command from handler map
- Added shutdown_requested property to NerveEngine specification
- Fixed ValidationHelpers interface to use SessionRegistry pattern
- Added _cleanup_on_stop implementation details to ServerHandler
- Updated NodeInteractionHandler code samples to use session_registry
- Added _emit helper method clarification

**v2.1 Changes**:
- Added SessionRegistry pattern to fix shared mutable state
- Removed backward compatibility (clean break)
- Removed handlers/base.py (not needed)
- Fixed encapsulation violations

---

## Executive Summary

Refactor `src/nerve/server/engine.py` from a 1421-line God class into a modular, domain-driven architecture. The refactoring will extract **6 domain-specific handler classes**, introduce factory patterns, and establish clear architectural boundaries while preserving 100% of existing functionality.

**Key Metrics**:
- Current: 1 file, 1421 lines, 25 command handlers, 0 architectural boundaries
- Target: 9 files, ~200 lines avg, 6 domain handlers, clear separation of concerns
- Line reduction: ~300 lines through deduplication
- Engine reduction: 1421 lines → 200-250 lines (dispatcher only)
- Functionality changes: 0 (behavior-preserving refactoring)

---

## Goals

### Primary Goals

1. **Eliminate God Class Anti-Pattern**
   - Split `NerveEngine` into 6 focused domain handlers
   - Each handler responsible for one specific concern
   - Clear separation: lifecycle vs interaction, execution vs meta-commands

2. **Introduce Proper Abstraction Layers**
   - Extract `NodeFactory` for backend dispatch (Open/Closed Principle)
   - Extract `PythonExecutor` for code execution (security boundary)
   - Extract `ReplCommandHandler` for REPL meta-commands
   - Extract `ValidationHelpers` for consistent validation

3. **Enable Dependency Injection**
   - Make all dependencies explicit via constructor parameters
   - Remove hidden dependencies (deferred imports, field access)
   - Enable testability through mock injection
   - Clear state ownership per handler

4. **Preserve All Functionality**
   - Zero breaking changes to external API
   - All tests pass without modification
   - Behavior byte-for-byte identical

5. **Improve Maintainability**
   - Reduce cognitive load (smaller, focused files)
   - Enable parallel development (separate domains)
   - Clear architectural boundaries
   - Each handler independently testable

### Secondary Goals

1. **Reduce Code Duplication**
   - Extract validation patterns (node lookup ×10, graph lookup ×4)
   - Extract graph streaming helper (×2 duplication)
   - Extract serialization helpers
   - Consistent error messages

2. **Improve Type Safety**
   - Add TypedDicts for command parameters
   - Add Protocols for node capabilities (TerminalNode)
   - Remove `# type: ignore` comments (9 occurrences)

3. **Better Error Handling**
   - Structured exception handling by type
   - Consistent error messages across handlers
   - Proper cleanup on failures

4. **Security Isolation**
   - Python code execution isolated in dedicated component
   - Clear security boundary for auditing
   - Namespace isolation per session

---

## Non-Goals

1. **API Changes**: External API (Command types, result formats) remains unchanged
2. **New Features**: No new functionality, pure refactoring
3. **Performance Optimization**: Not focused on performance (though may improve as side effect)
4. **Complete Rewrite**: Incremental refactoring, not greenfield rebuild
5. **Database/Storage Changes**: Session/persistence layer untouched

---

## Background

### Current Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      NerveEngine                         │
│                      (1421 lines)                        │
│                                                          │
│  • 25 command handlers in one class                     │
│  • 6 distinct domains mixed together:                   │
│    - Node lifecycle (create, delete, monitor)           │
│    - Node I/O (run, execute, interrupt, buffers)        │
│    - Python execution (security-sensitive)              │
│    - Graph execution & management                       │
│    - Session management                                 │
│    - Server control                                     │
│  • Directly imports concrete node types                 │
│  • Inline validation, serialization, event emission     │
│  • Hidden dependencies via field access                 │
│  • Complex state management scattered throughout        │
└─────────────────────────────────────────────────────────┘
```

### Problems Identified

| Problem | Impact | Evidence |
|---------|--------|----------|
| God Class | Hard to understand, modify | 1421 lines, 25 methods, 6 domains |
| No Domain Boundaries | Changes affect unrelated code | Node creation in same class as REPL |
| Lifecycle/Interaction Mixed | Unclear responsibilities | CRUD operations mixed with I/O |
| Tight Coupling | Hard to test, extend | Direct imports of PTYNode, WezTermNode, etc. |
| Code Duplication | Maintenance burden | Node validation ×10, graph streaming ×2 |
| Implicit Dependencies | Hard to test | Deferred imports, ProxyManager field |
| Missing Abstractions | Violates Open/Closed | Adding backend requires modifying engine |
| Security Concerns | No isolation | Python execution mixed with everything else |

### Analysis Summary

Five refactoring agents analyzed the codebase and identified:
- **58 total refactoring opportunities**
- **12 high-impact changes** (score > 8/10)
- **~300 lines** can be eliminated through deduplication
- **6 distinct domains** should be separated

**Key Findings**:
- `_create_node`: 165 lines (should be extracted with factory)
- `_execute_python`: 127 lines (security boundary, needs isolation)
- `_execute_repl_command`: 129 lines (switch statement, needs command pattern)
- `_execute_input`: 90 lines (streaming/parsing complexity)
- Node validation pattern repeated 10+ times
- Graph streaming pattern duplicated in 2 methods

---

## Detailed Design

### Target Architecture

```
                     ┌───────────────────────┐
                     │   CommandDispatcher   │
                     │    (NerveEngine)      │
                     │   (200-250 lines)     │
                     └───────────┬───────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
    ┌────▼─────┐          ┌─────▼──────┐        ┌──────▼──────┐
    │  Node    │          │   Node     │        │   Graph     │
    │Lifecycle │          │Interaction │        │   Handler   │
    │ Handler  │          │  Handler   │        │ (~250 ln)   │
    │(~200 ln) │          │ (~250 ln)  │        └─────────────┘
    └────┬─────┘          └─────┬──────┘
         │                      │               ┌──────────────┐
    ┌────▼─────┐                │               │   Session    │
    │   Node   │                │               │   Handler    │
    │ Factory  │                │               │  (~150 ln)   │
    │(~150 ln) │                │               └──────────────┘
    └──────────┘         ┌──────▼──────┐
                         │   Python    │        ┌──────────────┐
                         │  Executor   │        │    Server    │
                         │ (~200 ln)   │        │   Handler    │
                         │ [SECURITY]  │        │  (~100 ln)   │
                         └──────┬──────┘        └──────────────┘
                                │
                         ┌──────▼──────┐
                         │    REPL     │
                         │  Commands   │
                         │ (~150 ln)   │
                         └─────────────┘

                         ┌─────────────┐
                         │ Validation  │
                         │   Helpers   │
                         │ (~100 ln)   │
                         └─────────────┘
```

### Handler Responsibilities & State Ownership

**Note**: All handlers receive `SessionRegistry` for session access. SessionRegistry owns `_sessions` and `_default_session_name`.

| Handler | Responsibility | Owns State | Key Methods |
|---------|---------------|------------|-------------|
| **NodeLifecycleHandler** | Node CRUD & monitoring | _(none)_ | create, delete, list, get, monitor |
| **NodeInteractionHandler** | Node I/O operations | _(none)_ | run, execute, interrupt, write, buffer, history |
| **PythonExecutor** | Code execution | `_namespaces` | execute, async/sync execution |
| **GraphHandler** | Graph execution | `_running_graphs` | create, execute, run, cancel, list, get |
| **SessionHandler** | Session management | _(manages registry)_ | create, delete, list, get_info |
| **ReplCommandHandler** | REPL meta-commands | _(none)_ | show, dry, validate, list, read |
| **ServerHandler** | Server control | `_shutdown_requested` | stop, ping, cleanup |

**State Isolation Benefits**:
- Each handler owns its state explicitly
- No hidden state sharing
- Clear lifecycle management
- Independent testing

### New File Structure

```
src/nerve/server/
├── engine.py                          # NerveEngine (dispatcher, 200-250 lines)
├── session_registry.py                # SessionRegistry (~100 lines)
├── handlers/
│   ├── __init__.py
│   ├── node_lifecycle_handler.py     # Node CRUD & monitoring (~200 lines)
│   ├── node_interaction_handler.py   # Terminal I/O (~250 lines)
│   ├── graph_handler.py              # Graph execution (~250 lines)
│   ├── session_handler.py            # Session management (~150 lines)
│   ├── python_executor.py            # Python REPL [SECURITY] (~200 lines)
│   ├── repl_command_handler.py       # REPL meta-commands (~150 lines)
│   └── server_handler.py             # Server control (~100 lines)
├── factories/
│   ├── __init__.py
│   └── node_factory.py               # Node creation dispatch (~150 lines)
└── validation.py                     # Shared validation helpers (~100 lines)
```

**Key Changes from v1.0**:
1. Split NodeHandler → NodeLifecycleHandler + NodeInteractionHandler
2. Renamed PythonREPL → PythonExecutor (emphasizes security boundary)
3. Moved REPL components from `repl/` to `handlers/` (flatter structure)
4. Engine target: 200-250 lines (more realistic than 100)

**Key Changes from v2.0**:
1. Added SessionRegistry for shared state management (fixes mutable state bug)
2. Removed handlers/base.py (not needed - handlers aren't polymorphic)
3. All handlers use registry pattern instead of direct dict access
4. Clean break: no backward compatibility or feature flags

---

## Component Specifications

### 0. SessionRegistry (Critical Design Pattern)

**Responsibility**: Central registry for session state with thread-safe access

**File**: `src/nerve/server/session_registry.py`

**Problem Solved**:
In Python, passing `_default_session` as a reference to multiple handlers creates a **shared mutable state bug**. When `SessionHandler` reassigns `self._default_session = new_session`, other handlers still have the old reference. Python doesn't share references across assignments - each handler gets a **copy** of the reference.

**Solution**:
Use a registry class with dynamic property lookup instead of passing raw state.

**Core Pattern**:
```python
@dataclass
class SessionRegistry:
    """Central registry for session state with dynamic lookup."""

    _sessions: dict[str, Session] = field(default_factory=dict)
    _default_session_name: str | None = None

    @property
    def default_session(self) -> Session | None:
        """Get current default session (dynamic lookup)."""
        if not self._default_session_name:
            return None
        return self._sessions.get(self._default_session_name)

    def set_default(self, session_name: str) -> None:
        """Set default session by name."""
        if session_name not in self._sessions:
            raise ValueError(f"Cannot set default: session '{session_name}' not found")
        self._default_session_name = session_name

    def get_session(self, session_id: str | None) -> Session:
        """Get session by ID or return default."""
        if session_id:
            session = self._sessions.get(session_id)
            if not session:
                raise ValueError(f"Session not found: {session_id}")
            return session

        default = self.default_session
        if not default:
            raise ValueError("No default session")
        return default

    def has_session(self, name: str) -> bool:
        """Check if session exists (for duplicate detection)."""
        return name in self._sessions

    def add_session(self, name: str, session: Session) -> None:
        """Register new session."""
        self._sessions[name] = session

    def remove_session(self, name: str) -> Session | None:
        """Unregister session, returns the removed session or None."""
        return self._sessions.pop(name, None)

    def list_session_names(self) -> list[str]:
        """List all session names."""
        return list(self._sessions.keys())

    def get_all_sessions(self) -> list[Session]:
        """Get all Session objects (for cleanup iteration)."""
        return list(self._sessions.values())
```

**Key Methods**:
- `get_session(session_id)`: Get by ID or default (main handler interface)
- `add_session(name, session)`: Register new session
- `remove_session(name)`: Unregister session (returns Session or None)
- `set_default(name)`: Change default (propagates to ALL handlers)
- `has_session(name)`: Check if session exists (for duplicate detection)
- `list_session_names()`: List all session names (returns list[str])
- `get_all_sessions()`: Get all Session objects (for cleanup iteration)

**Benefits**:
- ✅ All handlers always see current default session (dynamic lookup)
- ✅ SessionHandler controls all session access
- ✅ Proper encapsulation (no direct dict access)
- ✅ Thread-safe (can add locks later if needed)
- ✅ Single source of truth

---

### 1. NerveEngine (Dispatcher)

**Responsibility**: Route commands to appropriate handlers

**File**: `src/nerve/server/engine.py`

**Target Size**: 200-250 lines (was unrealistic at ~100)

**Interface**:
```python
@dataclass
class NerveEngine:
    """Command dispatcher for the Nerve server.

    Responsibilities:
    - Route commands to appropriate domain handlers
    - Structured exception handling
    - Error event emission
    - Handler map construction
    - Expose shutdown_requested property for server loop
    """

    event_sink: EventSink
    node_lifecycle_handler: NodeLifecycleHandler
    node_interaction_handler: NodeInteractionHandler
    graph_handler: GraphHandler
    session_handler: SessionHandler
    python_executor: PythonExecutor
    repl_command_handler: ReplCommandHandler
    server_handler: ServerHandler

    def __post_init__(self) -> None:
        self._handlers = self._build_handler_map()

    @property
    def shutdown_requested(self) -> bool:
        """Whether shutdown has been requested (delegates to ServerHandler)."""
        return self.server_handler.shutdown_requested

    async def execute(self, command: Command) -> CommandResult:
        """Dispatch command to appropriate handler.

        Error Handling Strategy:
        - ValueError: User/validation errors (expected)
        - ProxyError: Infrastructure errors (emit event)
        - CancelledError: Propagate (don't swallow)
        - Exception: Internal errors (log + emit event)
        """
        handler = self._handlers.get(command.type)
        if not handler:
            return CommandResult(
                success=False,
                error=f"Unknown command: {command.type}",
                request_id=command.request_id,
            )

        try:
            data = await handler(command.params)
            return CommandResult(
                success=True,
                data=data,
                request_id=command.request_id,
            )
        except ValueError as e:
            # Validation/user errors - expected, no event
            return CommandResult(
                success=False,
                error=str(e),
                request_id=command.request_id,
            )
        except (ProxyStartError, ProxyHealthError) as e:
            # Infrastructure errors - emit event
            await self.event_sink.emit(Event(
                type=EventType.ERROR,
                data={"error": str(e), "type": "infrastructure"},
            ))
            return CommandResult(
                success=False,
                error=str(e),
                request_id=command.request_id,
            )
        except asyncio.CancelledError:
            # Cancellation should propagate
            raise
        except Exception as e:
            # Unexpected internal errors - log with trace
            logger.exception(f"Command {command.type.name} failed")
            await self.event_sink.emit(Event(
                type=EventType.ERROR,
                data={"error": str(e), "type": "internal"},
            ))
            return CommandResult(
                success=False,
                error=f"Internal error: {type(e).__name__}: {e}",
                request_id=command.request_id,
            )

    def _build_handler_map(self) -> dict[CommandType, Callable]:
        """Build command type → handler method mapping."""
        return {
            # Node lifecycle
            CommandType.CREATE_NODE: self.node_lifecycle_handler.create_node,
            CommandType.DELETE_NODE: self.node_lifecycle_handler.delete_node,
            CommandType.LIST_NODES: self.node_lifecycle_handler.list_nodes,
            CommandType.GET_NODE: self.node_lifecycle_handler.get_node,

            # Node interaction
            CommandType.RUN_COMMAND: self.node_interaction_handler.run_command,
            CommandType.EXECUTE_INPUT: self.node_interaction_handler.execute_input,
            CommandType.SEND_INTERRUPT: self.node_interaction_handler.send_interrupt,
            CommandType.WRITE_DATA: self.node_interaction_handler.write_data,
            CommandType.GET_BUFFER: self.node_interaction_handler.get_buffer,
            CommandType.GET_HISTORY: self.node_interaction_handler.get_history,

            # Python execution
            CommandType.EXECUTE_PYTHON: self.python_executor.execute_python,

            # REPL commands
            CommandType.EXECUTE_REPL_COMMAND: self.repl_command_handler.execute_repl_command,

            # Graph execution
            CommandType.CREATE_GRAPH: self.graph_handler.create_graph,
            CommandType.DELETE_GRAPH: self.graph_handler.delete_graph,
            CommandType.EXECUTE_GRAPH: self.graph_handler.execute_graph,
            CommandType.RUN_GRAPH: self.graph_handler.run_graph,
            CommandType.CANCEL_GRAPH: self.graph_handler.cancel_graph,
            CommandType.LIST_GRAPHS: self.graph_handler.list_graphs,
            CommandType.GET_GRAPH: self.graph_handler.get_graph_info,

            # Session management
            CommandType.CREATE_SESSION: self.session_handler.create_session,
            CommandType.DELETE_SESSION: self.session_handler.delete_session,
            CommandType.LIST_SESSIONS: self.session_handler.list_sessions,
            CommandType.GET_SESSION: self.session_handler.get_session_info,

            # Server control
            CommandType.STOP: self.server_handler.stop,
            CommandType.PING: self.server_handler.ping,
        }
```

**Key Changes from v1.0**:
- Improved error handling (separate ValueError, ProxyError, etc.)
- More realistic line count (200-250 vs 100)
- 6 handlers instead of 5
- Better error categorization

---

### 2. NodeLifecycleHandler

**Responsibility**: Node existence management (CRUD + monitoring)

**File**: `src/nerve/server/handlers/node_lifecycle_handler.py`

**State Ownership**: None (reads from shared session registry)

**Interface**:
```python
@dataclass
class NodeLifecycleHandler:
    """Handles node lifecycle: creation, deletion, listing, monitoring.

    Domain: Node existence (CRUD operations)
    Distinction: Manages WHETHER nodes exist, not HOW to interact with them

    State: None (uses session registry for access)
    """

    event_sink: EventSink
    node_factory: NodeFactory
    proxy_manager: ProxyManager
    validation: ValidationHelpers
    session_registry: SessionRegistry
    _server_name: str

    async def create_node(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new node (165 lines in original engine).

        Steps:
        1. Validate parameters
        2. Setup proxy if provider specified
        3. Delegate to NodeFactory for creation
        4. Emit NODE_CREATED event
        5. Start monitoring task

        Returns:
            {"node_id": str, "proxy_url": str|None}
        """
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        backend = params.get("backend", "pty")

        # Setup proxy if needed
        proxy_url = None
        if provider_dict := params.get("provider"):
            provider_config = ProviderConfig.from_dict(provider_dict)
            proxy_url = await self._setup_proxy(
                session, node_id, provider_config, params
            )

        # Create node via factory
        try:
            node = await self.node_factory.create(
                backend=backend,
                session=session,
                node_id=str(node_id),
                command=params.get("command"),
                cwd=params.get("cwd"),
                pane_id=params.get("pane_id"),
                history=params.get("history", True),
                response_timeout=params.get("response_timeout", 1800.0),
                ready_timeout=params.get("ready_timeout", 60.0),
                proxy_url=proxy_url,
            )
        except Exception:
            # Cleanup proxy on failure
            if proxy_url:
                await self.proxy_manager.stop_proxy(str(node_id))
            raise

        # Emit event
        await self.event_sink.emit(Event(
            type=EventType.NODE_CREATED,
            node_id=node.id,
            data={"backend": backend, "proxy_url": proxy_url},
        ))

        # Start monitoring
        asyncio.create_task(self._monitor_node(node))

        return {"node_id": node.id, "proxy_url": proxy_url}

    async def delete_node(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete a node from session."""
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        node = self.validation.get_node(session, node_id)  # Use ValidationHelpers

        # Stop proxy if one was created for this node
        await self.proxy_manager.stop_proxy(str(node_id))

        # Delete node from session
        await session.delete_node(node_id)

        await self.event_sink.emit(Event(
            type=EventType.NODE_DELETED,
            node_id=node_id,
        ))

        return {"deleted": True}

    async def list_nodes(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all nodes in session."""
        session = self.session_registry.get_session(params.get("session_id"))
        node_ids = session.list_nodes()
        nodes_info = self._gather_nodes_info(session, node_ids)

        return {"nodes": node_ids, "nodes_info": nodes_info}

    async def get_node(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get node information."""
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        node = self.validation.get_node(session, node_id)

        info = node.to_info()
        return {
            "id": node.id,
            "type": info.node_type,
            "state": info.state.name,
            **info.metadata,
        }

    # Private helpers

    async def _setup_proxy(
        self, session: Session, node_id: str, config: ProviderConfig, params: dict[str, Any]
    ) -> str:
        """Setup proxy and return URL."""
        # ... (proxy setup logic from engine)

    def _gather_nodes_info(
        self, session: Session, node_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Gather info dicts for nodes."""
        # ... (node info gathering from engine)

    async def _monitor_node(self, node: Any) -> None:
        """Monitor node state changes and emit events."""
        # ... (monitoring logic from engine)
```

**Key Points**:
- Focused on node existence (create/delete/list/get)
- Does NOT handle I/O operations (run/execute/write)
- ~200 lines (down from 165 just for create_node)
- Uses NodeFactory for backend dispatch

---

### 3. NodeInteractionHandler

**Responsibility**: Terminal I/O operations with existing nodes

**File**: `src/nerve/server/handlers/node_interaction_handler.py`

**State Ownership**: None (operates on existing nodes from session)

**Interface**:
```python
@dataclass
class NodeInteractionHandler:
    """Handles node I/O: commands, execution, streaming, buffers.

    Domain: Node communication (I/O operations)
    Distinction: Manages HOW to interact with nodes, not their existence

    State: None (uses session registry for access)
    """

    event_sink: EventSink
    validation: ValidationHelpers
    session_registry: SessionRegistry
    _server_name: str  # Needed for history command

    async def run_command(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run command in terminal (fire and forget)."""
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        node = self.validation.get_node(session, node_id, require_terminal=True)

        command = self.validation.require_param(params, "command")
        await node.run(command)
        return {"executed": True}

    async def execute_input(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute input with parser and get response (90 lines in original).

        Handles:
        - Parser resolution
        - Streaming vs non-streaming
        - Event emission (OUTPUT_CHUNK, OUTPUT_PARSED, NODE_READY)
        - Response serialization
        """
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        node = self.validation.get_node(session, node_id)  # Use ValidationHelpers

        text = self.validation.require_param(params, "text")
        parser_str = params.get("parser")
        stream = params.get("stream", False)
        timeout = params.get("timeout")

        # Parse parser type
        parser_type = None
        if parser_str:
            try:
                parser_type = ParserType(parser_str)
            except ValueError:
                valid = [p.value for p in ParserType]
                raise ValueError(f"Invalid parser: '{parser_str}'. Valid: {valid}")

        # Create execution context
        context = ExecutionContext(
            session=session,
            input=text,
            parser=parser_type,
            timeout=timeout,
        )

        # Execute with streaming or wait for response
        if stream:
            response = await self._execute_with_streaming(node, context, node.id)
        else:
            response = await node.execute(context)

        # Emit OUTPUT_PARSED event (critical for clients expecting parsed output)
        await self.event_sink.emit(Event(
            type=EventType.OUTPUT_PARSED,
            node_id=node.id,
            data={"response": self._serialize_response(response)},
        ))

        # Emit NODE_READY
        await self.event_sink.emit(Event(
            type=EventType.NODE_READY,
            node_id=node.id,
        ))

        return {"response": self._serialize_response(response)}

    async def send_interrupt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send interrupt signal to node."""
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        node = self.validation.get_node(session, node_id)

        await node.interrupt()
        return {"interrupted": True}

    async def write_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write raw data to terminal."""
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        node = self.validation.get_node(session, node_id, require_terminal=True)

        data = self.validation.require_param(params, "data")
        await node.write(data)
        return {"written": len(data)}

    async def get_buffer(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get terminal buffer contents."""
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        node = self.validation.get_node(session, node_id, require_terminal=True)

        lines = params.get("lines")
        if lines is not None:
            buffer = node.read_tail(int(lines))
        else:
            buffer = await node.read()

        return {"buffer": buffer}

    async def get_history(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get command history (reads JSONL history file)."""
        session = self.session_registry.get_session(params.get("session_id"))
        node_id = self.validation.require_param(params, "node_id")
        # Note: get_history doesn't require node object, just validates it exists
        _node = self.validation.get_node(session, node_id)

        server_name = params.get("server_name", self._server_name)
        last = params.get("last")
        op = params.get("op")
        inputs_only = params.get("inputs_only", False)

        # ... (history reader logic from engine._get_history)
        return {"node_id": node_id, "entries": [], "total": 0}

    # Private helpers

    async def _execute_with_streaming(
        self, node: Node, context: ExecutionContext, node_id: str
    ) -> ParsedResponse:
        """Execute node with streaming output."""
        async for chunk in node.execute_stream(context):
            await self.event_sink.emit(Event(
                type=EventType.OUTPUT_CHUNK,
                data={"chunk": chunk},
                node_id=node_id,
            ))

        parser = get_parser(context.parser or ParserType.NONE)
        return parser.parse(node.buffer)

    def _serialize_response(self, response: ParsedResponse) -> dict[str, Any]:
        """Serialize ParsedResponse to dict."""
        return {
            "raw": response.raw,
            "sections": [
                {"type": s.type, "content": s.content, "metadata": s.metadata}
                for s in response.sections
            ],
            "tokens": response.tokens,
            "is_complete": response.is_complete,
            "is_ready": response.is_ready,
        }
```

**Key Points**:
- Focused on I/O with existing nodes
- Does NOT create or delete nodes
- Streaming, parsing, buffers, history
- ~250 lines

---

### 4. PythonExecutor (Security Boundary)

**Responsibility**: Execute Python code in isolated namespaces

**File**: `src/nerve/server/handlers/python_executor.py`

**State Ownership**: `_namespaces` (per-session namespace dict)

**Security Notes**:
- Isolated component for code execution
- Clear audit point for security reviews
- Future: add sandboxing, permissions, resource limits
- Namespace isolation prevents cross-session data leaks

**Interface**:
```python
@dataclass
class PythonExecutor:
    """Executes Python code in isolated namespaces.

    SECURITY BOUNDARY:
    - Isolates arbitrary code execution
    - Per-session namespace isolation
    - Clear audit point for security reviews
    - Future: sandboxing, resource limits, permissions

    State: _namespaces (session → namespace dict)
    """

    validation: ValidationHelpers
    session_registry: SessionRegistry

    # Owned state
    _namespaces: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def execute_python(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute Python code in session namespace (command interface).

        This is the command handler entry point. Delegates to execute().
        """
        session = self.session_registry.get_session(params.get("session_id"))
        code = self.validation.require_param(params, "code")
        return await self.execute(code, session)

    async def execute(self, code: str, session: Session) -> dict[str, Any]:
        """Execute Python code in session namespace (core logic).

        Returns:
            {"output": str, "error": str|None}
        """
        if not code.strip():
            return {"output": "", "error": None}

        namespace = self._get_or_create_namespace(session)

        # Detect async code
        if "await " in code:
            return await self._execute_async(code, namespace)
        else:
            return await self._execute_sync(code, namespace)

    def _get_or_create_namespace(self, session: Session) -> dict[str, Any]:
        """Get or initialize namespace for session."""
        session_id = session.name
        if session_id not in self._namespaces:
            self._namespaces[session_id] = self._create_default_namespace(session)
        return self._namespaces[session_id]

    def _create_default_namespace(self, session: Session) -> dict[str, Any]:
        """Create default namespace with nerve imports."""
        import asyncio
        from nerve.core import ParserType
        from nerve.core.nodes import ExecutionContext, FunctionNode
        from nerve.core.nodes.bash import BashNode
        from nerve.core.nodes.graph import Graph
        from nerve.core.nodes.terminal import (
            ClaudeWezTermNode,
            PTYNode,
            WezTermNode,
        )

        return {
            "asyncio": asyncio,
            "BashNode": BashNode,
            "ClaudeWezTermNode": ClaudeWezTermNode,
            "ExecutionContext": ExecutionContext,
            "FunctionNode": FunctionNode,
            "Graph": Graph,
            "ParserType": ParserType,
            "PTYNode": PTYNode,
            "WezTermNode": WezTermNode,
            "session": session,
        }

    async def _execute_async(
        self, code: str, namespace: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute async code (contains 'await')."""
        # ... (async execution logic from engine)

    async def _execute_sync(
        self, code: str, namespace: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute synchronous code."""
        # ... (sync execution logic from engine)

    @staticmethod
    def _pretty_print(value: Any) -> str:
        """Pretty-print a value for REPL display."""
        # ... (pretty print logic from engine)
```

**Key Points**:
- **Security boundary** - isolated component
- Owns `_namespaces` state
- Async/sync code detection
- ~200 lines

---

### 5. ReplCommandHandler

**Responsibility**: REPL meta-commands (show, dry, validate, list, read)

**File**: `src/nerve/server/handlers/repl_command_handler.py`

**State Ownership**: None (operates on session data)

**Interface**:
```python
@dataclass
class ReplCommandHandler:
    """Handles REPL meta-commands: show, dry, validate, list, read.

    Domain: REPL introspection and graph visualization
    Distinction: Meta-commands vs Python execution

    State: None (uses session registry for access)
    """

    validation: ValidationHelpers
    session_registry: SessionRegistry

    async def execute_repl_command(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute REPL command (command interface, 129 lines in original).

        Commands:
        - show <graph_id>: Display graph structure
        - dry <graph_id>: Show execution order
        - validate <graph_id>: Validate graph
        - list [nodes|graphs]: List nodes or graphs
        - read <node_id>: Read node buffer
        """
        session = self.session_registry.get_session(params.get("session_id"))
        command = self.validation.require_param(params, "command")
        args = params.get("args", [])

        handlers = {
            "show": self._show,
            "dry": self._dry,
            "validate": self._validate,
            "list": self._list,
            "read": self._read,
        }

        handler = handlers.get(command)
        if not handler:
            return {"output": "", "error": f"Unknown REPL command: {command}"}

        try:
            output = await handler(session, args)
            return {"output": output, "error": None}
        except Exception as e:
            return {"output": "", "error": f"{type(e).__name__}: {e}"}

    async def _show(self, session: Session, args: list[str]) -> str:
        """Show graph structure."""
        # ... (show logic from engine._execute_repl_command)

    async def _dry(self, session: Session, args: list[str]) -> str:
        """Show dry-run execution order."""
        # ... (dry logic from engine)

    async def _validate(self, session: Session, args: list[str]) -> str:
        """Validate graph."""
        # ... (validate logic from engine)

    async def _list(self, session: Session, args: list[str]) -> str:
        """List nodes or graphs."""
        # ... (list logic from engine)

    async def _read(self, session: Session, args: list[str]) -> str:
        """Read node buffer."""
        # ... (read logic from engine)
```

**Key Points**:
- Command pattern (extensible)
- Separated from Python execution
- ~150 lines (down from 129-line switch statement)

---

### 6. GraphHandler

**Responsibility**: Graph execution and management

**File**: `src/nerve/server/handlers/graph_handler.py`

**State Ownership**: `_running_graphs` (graph_id → asyncio.Task)

**Interface**:
```python
@dataclass
class GraphHandler:
    """Handles graph execution and management.

    Domain: Graph lifecycle and execution

    State: _running_graphs (graph_id → task mapping)
    """

    event_sink: EventSink
    validation: ValidationHelpers
    session_registry: SessionRegistry

    # Owned state
    _running_graphs: dict[str, asyncio.Task[Any]] = field(default_factory=dict)

    async def create_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new graph in session."""
        # ... (from engine._create_graph)

    async def delete_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete a graph from session."""
        # ... (from engine._delete_graph)

    async def execute_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a graph from step definitions."""
        # Uses _stream_graph_execution helper

    async def run_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run an existing graph."""
        # Uses _stream_graph_execution helper

    async def cancel_graph(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cancel a running graph."""
        # ... (from engine._cancel_graph)

    async def list_graphs(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all graphs in session."""
        # ... (from engine._list_graphs)

    async def get_graph_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get graph metadata."""
        # ... (from engine._get_graph_info)

    # Methods for ServerHandler coordination

    @property
    def running_graph_count(self) -> int:
        """Number of currently running graphs."""
        return len(self._running_graphs)

    async def cancel_all_graphs(self) -> None:
        """Cancel all running graphs (used during server shutdown).

        Encapsulates _running_graphs access for ServerHandler.
        """
        for _graph_id, task in list(self._running_graphs.items()):
            task.cancel()
        self._running_graphs.clear()

    # Private helper

    async def _stream_graph_execution(
        self, graph: Graph, context: ExecutionContext, graph_id: str
    ) -> dict[str, Any]:
        """Execute graph with streaming events.

        Eliminates duplication between execute_graph and run_graph.
        """
        # ... (streaming logic, ~40 lines)
```

**Key Points**:
- Owns `_running_graphs` state
- Eliminates duplication via `_stream_graph_execution`
- ~250 lines

---

### 7. SessionHandler & ServerHandler

**Files**:
- `src/nerve/server/handlers/session_handler.py`
- `src/nerve/server/handlers/server_handler.py`

**SessionHandler**:
```python
@dataclass
class SessionHandler:
    """Manages session lifecycle.

    Commands: CREATE_SESSION, DELETE_SESSION, LIST_SESSIONS, GET_SESSION

    State: Manages SessionRegistry (add/remove sessions)
    Note: There is no SWITCH_SESSION command in the current API.
    """

    event_sink: EventSink
    validation: ValidationHelpers
    session_registry: SessionRegistry  # Manages the registry
    _server_name: str

    async def create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create new session and register it."""
        name = self.validation.require_param(params, "name")
        description = params.get("description", "")
        tags = params.get("tags", [])

        # Check for duplicate (uses proper encapsulation)
        if self.session_registry.has_session(name):
            raise ValueError(f"Session with name '{name}' already exists")

        session = Session(
            name=name,
            description=description,
            tags=tags,
            server_name=self._server_name,
        )
        self.session_registry.add_session(name, session)

        await self.event_sink.emit(Event(
            type=EventType.SESSION_CREATED,
            data={"session_id": name, "name": name},
        ))

        return {"session_id": name, "name": name}

    async def delete_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete a session."""
        session_id = self.validation.require_param(params, "session_id")

        # Cannot delete default session
        default = self.session_registry.default_session
        if default and session_id == default.name:
            raise ValueError("Cannot delete the default session")

        session = self.session_registry.remove_session(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        await session.stop()

        await self.event_sink.emit(Event(
            type=EventType.SESSION_DELETED,
            data={"session_id": session_id},
        ))

        return {"deleted": True}

    async def list_sessions(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all sessions."""
        # ... (from engine._list_sessions)

    async def get_session_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get session info including nodes and graphs."""
        # ... (from engine._get_session_info)
```

**ServerHandler**:
```python
@dataclass
class ServerHandler:
    """Server control and cleanup coordination.

    Commands: STOP, PING

    State:
    - shutdown_requested: bool (exposed via property)
    - Coordinates cleanup across all handlers

    Design Note: Uses graph_handler.cancel_all_graphs() instead of accessing
    _running_graphs directly to avoid coupling to GraphHandler internals.
    """

    event_sink: EventSink
    proxy_manager: ProxyManager
    session_registry: SessionRegistry
    graph_handler: GraphHandler  # Reference to call cancel_all_graphs()
    _shutdown_requested: bool = field(default=False)

    @property
    def shutdown_requested(self) -> bool:
        """Whether shutdown has been requested."""
        return self._shutdown_requested

    async def stop(self, params: dict[str, Any]) -> dict[str, Any]:
        """Stop the server.

        Returns immediately after initiating stop. Cleanup happens async.
        """
        self._shutdown_requested = True

        await self.event_sink.emit(Event(type=EventType.SERVER_STOPPED))

        # Schedule cleanup in background
        asyncio.create_task(self._cleanup_on_stop())

        return {"stopped": True}

    async def _cleanup_on_stop(self) -> None:
        """Background cleanup during stop.

        1. Cancel all running graphs (via GraphHandler)
        2. Stop all sessions (which stops all nodes)
        3. Stop all proxies
        """
        # Cancel running graphs via GraphHandler (proper encapsulation)
        await self.graph_handler.cancel_all_graphs()

        # Stop all sessions (get_all_sessions returns Session objects)
        for session in self.session_registry.get_all_sessions():
            try:
                await session.stop()
            except Exception:
                pass  # Best effort

        # Stop all proxies
        try:
            await self.proxy_manager.stop_all()
        except Exception:
            pass  # Best effort

    async def ping(self, params: dict[str, Any]) -> dict[str, Any]:
        """Ping server to check if alive."""
        sessions = self.session_registry.get_all_sessions()
        total_nodes = sum(len(s.nodes) for s in sessions)
        return {
            "pong": True,
            "nodes": total_nodes,
            "graphs": self.graph_handler.running_graph_count,
            "sessions": len(sessions),
        }
```

---

### 8. NodeFactory

**Responsibility**: Create nodes based on backend type

**File**: `src/nerve/server/factories/node_factory.py`

**Interface**:
```python
class NodeFactory:
    """Factory for creating nodes by backend type.

    Implements Open/Closed Principle:
    - Open for extension (add new backends)
    - Closed for modification (via registry pattern in future)
    """

    @staticmethod
    async def create(
        backend: str,
        session: Session,
        node_id: str,
        command: str | list[str] | None = None,
        cwd: str | None = None,
        pane_id: str | None = None,
        history: bool = True,
        response_timeout: float = 1800.0,
        ready_timeout: float = 60.0,
        proxy_url: str | None = None,
    ) -> Node:
        """Create a node of the specified backend type."""
        from nerve.core.nodes.terminal import (
            ClaudeWezTermNode,
            PTYNode,
            WezTermNode,
        )

        if backend == "pty":
            return await PTYNode.create(...)
        elif backend == "wezterm":
            if pane_id:
                return await WezTermNode.attach(...)
            else:
                return await WezTermNode.create(...)
        elif backend == "claude-wezterm":
            if not command:
                raise ValueError("command is required for claude-wezterm backend")
            return await ClaudeWezTermNode.create(...)
        else:
            valid_backends = ["pty", "wezterm", "claude-wezterm"]
            raise ValueError(
                f"Unknown backend: '{backend}'. Valid backends: {valid_backends}"
            )
```

**Key Points**:
- Encapsulates backend dispatch
- ~150 lines
- Future: registry pattern for extensibility

---

### 9. ValidationHelpers

**Responsibility**: Shared validation logic

**File**: `src/nerve/server/validation.py`

**Note**: ValidationHelpers is stateless and uses SessionRegistry for session access. Each handler passes their session_registry reference when calling validation methods.

**Interface**:
```python
class ValidationHelpers:
    """Shared validation helpers for command handlers.

    Eliminates duplication:
    - require_param: Used everywhere (~20 times)
    - Node lookup + validation pattern (~10 times)
    - Graph lookup + validation pattern (~4 times)

    Stateless - handlers pass SessionRegistry as needed.
    """

    @staticmethod
    def require_param(params: dict[str, Any], key: str) -> Any:
        """Extract required parameter or raise ValueError.

        Args:
            params: Command parameters dict
            key: Required parameter key

        Returns:
            The parameter value

        Raises:
            ValueError: If parameter is missing or None
        """
        value = params.get(key)
        if value is None:
            raise ValueError(f"{key} is required")
        return value

    @staticmethod
    def get_node(
        session: Session,
        node_id: str,
        require_terminal: bool = False,
    ) -> Node:
        """Get node from session with validation.

        Args:
            session: Session to look up node in
            node_id: Node identifier
            require_terminal: If True, validate node has terminal capabilities

        Returns:
            The node

        Raises:
            ValueError: If node not found or doesn't have required capabilities
        """
        node = session.get_node(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")

        if require_terminal and not hasattr(node, "write"):
            raise ValueError(f"Node {node_id} is not a terminal node")

        return node

    @staticmethod
    def get_graph(session: Session, graph_id: str) -> Graph:
        """Get graph from session with validation.

        Args:
            session: Session to look up graph in
            graph_id: Graph identifier

        Returns:
            The graph

        Raises:
            ValueError: If graph not found
        """
        graph = session.get_graph(graph_id)
        if graph is None:
            raise ValueError(f"Graph not found: {graph_id}")
        return graph
```

**Key Points**:
- Eliminates 60+ lines of duplication
- Consistent error messages
- Stateless (no SessionRegistry reference - handlers pass Session directly)
- ~100 lines

---

## Implementation Plan

### Phase 1: Low-Risk Foundation (Week 1)

**Goal**: Create support components without touching engine

**Steps**:
1. Create directory structure
   ```bash
   mkdir -p src/nerve/server/handlers
   mkdir -p src/nerve/server/factories
   ```

2. **Create `SessionRegistry`** (Day 1, 2 hours)
   - Implement registry with dynamic property lookup
   - Add comprehensive unit tests
   - **Deliverable**: session_registry.py with >95% coverage

3. **Create `ValidationHelpers`** (Day 1-2, 2 hours)
   - Implement `require_param`, `require_node`, `require_graph`
   - Add comprehensive tests
   - **Deliverable**: validation.py with >90% coverage

4. **Create `NodeFactory`** (Day 2, 3 hours)
   - Extract backend dispatch logic
   - Add tests with mock nodes
   - **Deliverable**: factories/node_factory.py with tests

5. **Create `PythonExecutor`** (Day 3-4, 4 hours)
   - Extract Python execution logic (127 lines)
   - Extract `_pretty_print_value`
   - Add tests for async/sync execution
   - **Deliverable**: handlers/python_executor.py with security docs

6. **Create `ReplCommandHandler`** (Day 4-5, 3 hours)
   - Extract REPL meta-commands (129 lines)
   - Add tests for each command
   - **Deliverable**: handlers/repl_command_handler.py

**Success Criteria**:
- [ ] All new files have >80% test coverage
- [ ] Original `engine.py` unchanged
- [ ] All existing tests pass
- [ ] No behavioral changes

**Rationale**: Start with low-risk, clearly isolated components. SessionRegistry is critical for fixing shared state bug. ValidationHelpers and PythonExecutor have the clearest boundaries and minimal coupling to other systems.

---

### Phase 2: High-Value Handler Extraction (Week 2)

**Goal**: Extract lifecycle and graph handlers

**Steps**:
1. **Create `NodeLifecycleHandler`** (Day 1-2, 6 hours)
   - Extract create_node (165 lines), delete, list, get, monitor
   - Inject NodeFactory, ValidationHelpers
   - Add comprehensive tests
   - **Deliverable**: handlers/node_lifecycle_handler.py

2. **Create `GraphHandler`** (Day 3-4, 6 hours)
   - Extract graph methods
   - Extract `_stream_graph_execution` helper (eliminates 40-line duplication)
   - Add tests for execution, cancellation
   - **Deliverable**: handlers/graph_handler.py

3. **Create `SessionHandler`** (Day 5, 3 hours)
   - Extract session CRUD
   - Straightforward extraction
   - **Deliverable**: handlers/session_handler.py

**Success Criteria**:
- [ ] Handlers independently tested
- [ ] Original engine still exists (for comparison)
- [ ] All handler tests pass

**Rationale**: NodeLifecycleHandler is the highest-value extraction (165-line create_node method). GraphHandler eliminates significant duplication.

---

### Phase 3: Interaction & Server Handlers (Week 3)

**Goal**: Complete handler extraction

**Steps**:
1. **Create `NodeInteractionHandler`** (Day 1-2, 6 hours)
   - Extract I/O operations (run, execute, interrupt, write, buffer)
   - Extract `_execute_with_streaming` helper
   - Add tests
   - **Deliverable**: handlers/node_interaction_handler.py

2. **Create `ServerHandler`** (Day 3, 2 hours)
   - Extract stop, ping, cleanup logic
   - Simple extraction
   - **Deliverable**: handlers/server_handler.py

3. **Create `NerveEngine` v2** (Day 4-5, 8 hours)
   - Create `engine_v2.py` with dispatcher pattern
   - Inject all 7 handlers
   - Build handler map
   - **Deliverable**: engine_v2.py (200-250 lines)

**Success Criteria**:
- [ ] All handlers extracted
- [ ] Engine v2 complete
- [ ] Handler map correct

---

### Phase 4: Integration & Cutover (Week 4)

**Goal**: Switch to new architecture

**Steps**:
1. **Create Builder Pattern** (Day 1, 4 hours)
   - `build_nerve_engine()` function
   - Wire all dependencies
   - Explicit state sharing
   - **Deliverable**: engine_builder.py

2. **Parallel Testing** (Day 2-3, 12 hours)
   - Run behavioral equivalence tests
   - Compare old vs new on 50+ commands
   - Fix any discrepancies
   - **Deliverable**: Equivalence test suite passes

3. **Cutover** (Day 4, 4 hours)
   - **Clean Break**: Replace `engine.py` with new implementation
   - Move old `engine.py` to `engine_old.py` temporarily (for reference during testing)
   - Rename `engine_v2.py` → `engine.py`
   - Update all imports
   - Run full test suite
   - **Deliverable**: New engine in production

4. **Cleanup** (Day 5, 2 hours)
   - Delete `engine_old.py` (old reference copy)
   - Update documentation
   - Performance benchmarks
   - **Deliverable**: Clean production code, no legacy files

**Success Criteria**:
- [ ] All existing tests pass
- [ ] Behavioral equivalence verified
- [ ] Performance unchanged (±5%)
- [ ] Documentation updated

---

## Testing Strategy

### Unit Tests

**For Each Handler**:
```python
# Example: test_node_lifecycle_handler.py
async def test_create_node_success():
    # Arrange
    mock_factory = MockNodeFactory()
    mock_events = MockEventSink()
    mock_validation = ValidationHelpers()

    # Create session registry with test session
    session_registry = SessionRegistry()
    session = Session(name="default", server_name="test")
    session_registry.add_session("default", session)
    session_registry.set_default("default")

    handler = NodeLifecycleHandler(
        event_sink=mock_events,
        node_factory=mock_factory,
        proxy_manager=MockProxyManager(),
        validation=mock_validation,
        session_registry=session_registry,  # ← Uses registry
        _server_name="test",
    )

    # Act
    result = await handler.create_node({
        "node_id": "test-node",
        "backend": "pty",
    })

    # Assert
    assert result["node_id"] == "test-node"
    assert mock_factory.create_called
    assert mock_events.emitted(EventType.NODE_CREATED)
```

### Integration Tests

**End-to-End**:
```python
async def test_create_node_integration():
    engine = build_nerve_engine(event_sink)

    result = await engine.execute(Command(
        type=CommandType.CREATE_NODE,
        params={"node_id": "test", "backend": "pty"},
    ))

    assert result.success
    assert result.data["node_id"] == "test"
```

### Behavioral Equivalence Tests

**Critical for Migration**:
```python
async def test_behavioral_equivalence():
    """Verify new architecture produces identical results to old."""
    old_engine = OldNerveEngine(...)
    new_engine = build_nerve_engine(...)

    commands = load_test_commands()  # 50+ real commands

    for cmd in commands:
        old_result = await old_engine.execute(cmd)
        new_result = await new_engine.execute(cmd)

        assert old_result.success == new_result.success
        assert old_result.data == new_result.data
        assert old_result.error == new_result.error
```

---

## Migration Path

**Clean Break Strategy**:
- This is a **pure refactoring** - external API unchanged
- No backward compatibility layer needed
- No feature flags or environment variable switches
- Direct replacement of old engine with new implementation
- Behavioral equivalence verified through comprehensive testing

**External API Stability**:
- Command types unchanged
- CommandResult format unchanged
- Event types unchanged
- All public interfaces identical

**Testing Ensures Safety**:
- Behavioral equivalence tests validate byte-for-byte identical behavior
- Comprehensive test suite runs before cutover
- If issues found, fix in new implementation (not rollback)

---

## Success Criteria

### Functional Requirements

- [ ] All existing tests pass without modification
- [ ] Behavioral equivalence tests pass (old vs new)
- [ ] Integration tests pass
- [ ] No regressions in functionality

### Architectural Requirements

- [ ] `NerveEngine` 200-250 lines (dispatcher only)
- [ ] No handler > 300 lines
- [ ] 6 domain handlers with clear responsibilities
- [ ] Each handler has single responsibility
- [ ] All dependencies injected via constructor
- [ ] No deferred imports in handlers (except factories)
- [ ] Explicit state ownership per handler

### Code Quality Requirements

- [ ] No code duplication (validation, graph streaming)
- [ ] All handlers have >80% test coverage
- [ ] Type safety: no `# type: ignore` in handlers
- [ ] Validation helpers used consistently
- [ ] Security boundary clearly documented (PythonExecutor)

### Performance Requirements

- [ ] Command latency unchanged (±5%)
- [ ] Memory usage unchanged (±10%)
- [ ] No new resource leaks

---

## Risks and Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Behavioral regression | HIGH | MEDIUM | Comprehensive equivalence tests, phased approach, extensive testing |
| Performance degradation | MEDIUM | LOW | Benchmark before/after, fix performance issues before cutover |
| Incomplete migration | HIGH | LOW | Phased approach, parallel testing in Phase 4 |
| Dependency injection complexity | MEDIUM | MEDIUM | Clear builder pattern, comprehensive docs |
| Test maintenance burden | MEDIUM | MEDIUM | Reuse fixtures, mock helpers, clear patterns |
| Security regression | HIGH | LOW | PythonExecutor isolated, clear boundary, audit |
| SessionRegistry bugs | MEDIUM | LOW | Comprehensive unit tests, dynamic lookup thoroughly tested |

---

## Appendix A: File Line Count Comparison

### Before

| File | Lines | Domains |
|------|-------|---------|
| `engine.py` | 1421 | 6 mixed |

### After

| File | Lines | Domain |
|------|-------|--------|
| `engine.py` | 200-250 | Dispatcher |
| `session_registry.py` | ~100 | Session state |
| `handlers/node_lifecycle_handler.py` | ~200 | Node CRUD |
| `handlers/node_interaction_handler.py` | ~250 | Node I/O |
| `handlers/graph_handler.py` | ~250 | Graph exec |
| `handlers/session_handler.py` | ~150 | Sessions |
| `handlers/python_executor.py` | ~200 | Python [SEC] |
| `handlers/repl_command_handler.py` | ~150 | REPL cmds |
| `handlers/server_handler.py` | ~100 | Server |
| `factories/node_factory.py` | ~150 | Factory |
| `validation.py` | ~100 | Validation |
| **Total** | **~1900** | **Clear** |

**Analysis**:
- Longest file: 1421 → 250 (82% reduction)
- Average file size: ~173 lines (readable)
- Total increase: ~480 lines (docs, structure, types, SessionRegistry)
- Duplication eliminated: ~300 lines
- Net increase: ~180 lines for better architecture (includes SessionRegistry fix)

---

## Appendix B: State Ownership Matrix

| Component | Owned State | Shared State Access |
|-----------|-------------|---------------------|
| **SessionRegistry** | `_sessions`, `_default_session_name` | None (owns state) |
| NerveEngine | None | None (delegates) |
| NodeLifecycleHandler | None | Via `registry.get_session()` |
| NodeInteractionHandler | None | Via `registry.get_session()` |
| PythonExecutor | `_namespaces` | Via `registry.get_session()` |
| GraphHandler | `_running_graphs` | Via `registry.get_session()` |
| SessionHandler | None | Via registry methods (add/remove/set_default) |
| ReplCommandHandler | None | Via `registry.get_session()` |
| ServerHandler | None | Via `registry.list_sessions()` |

**Key Changes from v2.0**:
- ✅ SessionRegistry owns all session state
- ✅ No handler has direct dict access
- ✅ All access goes through registry methods
- ✅ Proper encapsulation

**Benefits**:
- Clear ownership prevents bugs
- Independent testing possible
- No hidden state sharing
- Dynamic property lookup solves shared mutable state bug

---

## Appendix C: Builder Pattern

```python
def build_nerve_engine(
    event_sink: EventSink,
    server_name: str = "default",
) -> NerveEngine:
    """Build fully-wired NerveEngine with all handlers.

    Uses SessionRegistry pattern to solve shared mutable state problem.
    Creates default session on initialization (matching original engine behavior).
    """

    # Create session registry (solves shared state problem)
    session_registry = SessionRegistry()

    # Create and register default session (matching engine.__post_init__ behavior)
    default_session = Session(name="default", server_name=server_name)
    session_registry.add_session("default", default_session)
    session_registry.set_default("default")

    # Shared dependencies
    proxy_manager = ProxyManager()
    validation = ValidationHelpers()

    # Factories
    node_factory = NodeFactory()

    # Handlers (ALL take session_registry, not raw state)
    node_lifecycle_handler = NodeLifecycleHandler(
        event_sink=event_sink,
        node_factory=node_factory,
        proxy_manager=proxy_manager,
        validation=validation,
        session_registry=session_registry,  # ← Registry
        _server_name=server_name,
    )

    node_interaction_handler = NodeInteractionHandler(
        event_sink=event_sink,
        validation=validation,
        session_registry=session_registry,  # ← Registry
        _server_name=server_name,
    )

    python_executor = PythonExecutor(
        validation=validation,
        session_registry=session_registry,  # ← Registry
    )

    repl_command_handler = ReplCommandHandler(
        validation=validation,
        session_registry=session_registry,  # ← Registry
    )

    graph_handler = GraphHandler(
        event_sink=event_sink,
        validation=validation,
        session_registry=session_registry,  # ← Registry
    )

    session_handler = SessionHandler(
        event_sink=event_sink,
        validation=validation,
        session_registry=session_registry,  # ← Manages registry
        _server_name=server_name,
    )

    server_handler = ServerHandler(
        event_sink=event_sink,
        proxy_manager=proxy_manager,
        session_registry=session_registry,  # ← Registry
        graph_handler=graph_handler,  # ← Reference to handler (not internals)
    )

    # Engine (dispatcher)
    return NerveEngine(
        event_sink=event_sink,
        node_lifecycle_handler=node_lifecycle_handler,
        node_interaction_handler=node_interaction_handler,
        graph_handler=graph_handler,
        session_handler=session_handler,
        python_executor=python_executor,
        repl_command_handler=repl_command_handler,
        server_handler=server_handler,
    )
```

**Key Changes from v2.0**:
- ✅ Single `SessionRegistry` instance created and shared
- ✅ All handlers receive `session_registry` parameter
- ✅ No raw `_sessions` or `_default_session` passed around
- ✅ SessionHandler manages registry via methods (add/remove/set_default)
- ✅ Other handlers access via `registry.get_session()`
- ✅ Default session created on initialization (matching original behavior)
- ✅ ServerHandler uses `graph_handler` reference (not internal `_running_graphs`)

---

**End of PRD v2.3**
