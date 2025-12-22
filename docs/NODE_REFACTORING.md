# Node Refactoring PRD

## Product Requirements Document

**Document Version:** 1.0
**Status:** Draft
**Author:** Architecture Team
**Last Updated:** 2025-12-22

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Goals & Non-Goals](#2-goals--non-goals)
3. [Current State](#3-current-state)
4. [Proposed Architecture](#4-proposed-architecture)
5. [Detailed Requirements](#5-detailed-requirements)
6. [Feature Mapping](#6-feature-mapping)
7. [Implementation Phases](#7-implementation-phases)
8. [Testing Strategy](#8-testing-strategy)
9. [Migration Guide](#9-migration-guide)
10. [Design Decisions](#10-design-decisions)

---

## 1. Executive Summary

### Background

The Nerve system currently uses multiple abstractions for orchestrating work: **Channel** (interactive process connections), **Task** (units of work in a DAG), **DAG** (task orchestration), and **Session** (channel grouping). Through architectural exploration, we identified that these abstractions share fundamental similarities and can be unified into a simpler, more powerful model.

### Proposal

Unify Channel and Task into a single **Node** abstraction with a `persistent` flag to distinguish stateful (persistent) from stateless (ephemeral) nodes. Make **Graph** implement Node, enabling composable workflows where graphs can contain other graphs. Clarify **Session** as the lifecycle manager for all registered nodes.

### Benefits

1. **Simpler mental model**: One abstraction (Node) for all work units
2. **Composability**: Graphs containing graphs, enabling modular workflow design
3. **Reusability**: Same node can appear in multiple graph steps with different inputs
4. **Extensibility**: Adding new node types follows a single pattern
5. **Agent support**: Foundation for dynamic, LLM-driven graph construction

### Architectural Approach

This is a **clean break**, not a wrapper layer:

```
BEFORE:  Channel → Backend
AFTER:   Node → Backend (Channel is replaced, not wrapped)
```

- **Node** replaces **Channel** as the abstraction for work units
- **Terminal nodes** (PTYNode, WezTermNode) use **Backend directly** (see Decision D8)
- **Backend** layer (PTYBackend, WezTermBackend) remains unchanged
- **Channel** code becomes deprecated and is eventually removed

### Scope

This PRD covers:
- Refactoring core abstractions (Channel → Node, DAG → Graph)
- Preserving all existing features (no regression)
- Migration utilities and backward compatibility

This PRD does **not** cover:
- P0 agent capabilities (error handling, budgets, cancellation, observability) - see [AGENT_CAPABILITIES.md](./AGENT_CAPABILITIES.md)
- P1+ agent capabilities (memory, human-in-loop)
- Gateway refactoring (LLM proxy layer)
- New transport protocols

### Enabled Capabilities

This refactoring enables patterns not possible with the current architecture:

| Pattern | Description | Enabled By |
|---------|-------------|------------|
| Nested Graphs | Graphs containing graphs for modular workflows | Graph implements Node (D2) |
| Dynamic Composition | Build graphs at runtime based on conditions | Steps reference nodes by ID (D5) |
| Agent Loops | Iterative decide-act-observe patterns | Graph as runtime data structure |
| LLM-Driven Workflows | AI decides graph structure dynamically | Dynamic graph construction |
| Self-Modifying Graphs | Nodes add follow-up steps during execution | Graph execution streaming |
| Node Reuse | Same node in multiple steps with different deps | Dependencies in Step, not Node (D3) |

See [ARCHITECTURE_EXPLORATION.md](./ARCHITECTURE_EXPLORATION.md) Part 9 for detailed examples of these patterns.

---

## 2. Goals & Non-Goals

### Goals

| ID | Goal | Rationale |
|----|------|-----------|
| G1 | Unify Channel and Task into Node | Reduces conceptual overhead, enables consistent patterns |
| G2 | Make Graph a Node | Enables composable, nested workflows |
| G3 | Zero feature regression | All existing functionality must continue to work |
| G4 | Preserve layered architecture | Core remains pure (no networking/events) |
| G5 | Clear migration path | Existing code can migrate incrementally |
| G6 | Maintain test coverage | All refactored code has equivalent test coverage |

### Non-Goals

| ID | Non-Goal | Rationale |
|----|----------|-----------|
| NG1 | Implement long-term memory | P1 priority, separate PRD |
| NG2 | Implement human-in-the-loop | P1 priority, separate PRD |
| NG3 | Implement checkpointing | P2 priority, separate PRD |
| NG4 | Implement security sandboxing | P2 priority, separate PRD |
| NG5 | Refactor Gateway layer | Out of scope, stable subsystem |
| NG6 | Add new transport types | Out of scope |
| NG7 | Change Parser abstraction | Parsers remain unchanged |
| NG8 | Change Backend abstraction | Backends remain unchanged |
| NG9 | Implement HTTPNode | Future work, requires separate design for HTTP semantics |

### 2.3 Success Criteria

| Criteria | Measurement |
|----------|-------------|
| Zero feature regression | All existing tests pass; feature mapping (Section 6) verified |
| Backward compatibility | Deprecated Channel/DAG APIs work without code changes through Phase 2 |
| Performance parity | No >10% degradation in channel operation benchmarks |
| Migration completeness | All Channel/DAG code migrated to Node/Graph by Phase 3 |
| Test coverage maintained | ≥90% coverage on new Node/Graph code |

### 2.4 Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Breaking existing scripts | Medium | High | Deprecation warnings for 2 versions; shim layer in Phase 1-2 |
| Performance regression in terminal ops | Low | Medium | Benchmark PTY/WezTerm operations before/after each phase |
| Incomplete migration | Medium | Medium | Feature mapping checklist (Section 6); coach review at each phase |
| Graph execution bugs | Medium | High | Comprehensive graph tests (Section 8.2) |

---

## 3. Current State

### 3.1 Current Abstractions

```
┌─────────────────────────────────────────────────────────────────────────┐
│ CURRENT ARCHITECTURE                                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Session ─────────────┐                                                  │
│  (groups channels)    │                                                  │
│                       ▼                                                  │
│            ┌──────────────────┐                                          │
│            │ ChannelManager   │                                          │
│            │ (lifecycle)      │                                          │
│            └──────────────────┘                                          │
│                       │                                                  │
│        ┌──────────────┼──────────────┐                                   │
│        ▼              ▼              ▼                                   │
│   PTYChannel    WezTermChannel   Claude...Channel                        │
│   (persistent)  (persistent)     (persistent)                            │
│                                                                          │
│  ═══════════════════════════════════════════════════════════════════    │
│                                                                          │
│  DAG ─────────────────┐                                                  │
│  (orchestrates tasks) │                                                  │
│                       ▼                                                  │
│            ┌──────────────────┐                                          │
│            │     Task A       │ ──depends_on──► Task B                   │
│            │  (ephemeral,     │                (ephemeral,               │
│            │   has deps)      │                 has deps)                │
│            └──────────────────┘                                          │
│                                                                          │
│  Problem: DAG cannot contain DAG. Channels and Tasks are separate.       │
│           Wrapping channels in tasks is boilerplate.                     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Current Feature Inventory

#### Channel Features

| Feature | Location | Description |
|---------|----------|-------------|
| PTYChannel | `core/channels/pty.py` | Owns process via pseudo-terminal, continuous buffer |
| WezTermChannel | `core/channels/wezterm.py` | Attaches to WezTerm panes, queries buffer fresh |
| ClaudeOnWezTermChannel | `core/channels/claude_wezterm.py` | Specialized for Claude Code in WezTerm |
| Channel.send() | Protocol method | Send input, wait for parsed response |
| **Channel.send_stream()** | Implementation method | Send input, stream output chunks as async iterator |
| Channel.run() | Protocol method | Fire-and-forget execution |
| Channel.write() | Protocol method | Low-level raw write |
| Channel.read() | Protocol method | Read current buffer |
| **Channel.read_tail(lines)** | Implementation method | Read last N lines from buffer |
| Channel.interrupt() | Protocol method | Cancel current operation (Ctrl+C) |
| Channel.close() | Protocol method | Release resources |
| Buffer tracking | PTYChannel | Incremental output via `_buffer_start` |
| **clear_buffer()** | Backend method | Clear accumulated buffer |
| Ready detection | Via Parser | Parser determines when channel is ready |
| History logging | `core/channels/history.py` | JSONL audit log per channel |
| **ChannelType enum** | `core/channels/base.py` | TERMINAL, SQL (future), HTTP (future) |

#### Parser Features

| Feature | Location | Description |
|---------|----------|-------------|
| ClaudeParser | `core/parsers/claude.py` | Parses Claude Code output |
| GeminiParser | `core/parsers/gemini.py` | Parses Gemini CLI output |
| NoneParser | `core/parsers/none.py` | No-op, returns raw output |
| is_ready() | Parser protocol | Detects if CLI ready for input |
| parse() | Parser protocol | Converts output to structured response |
| Per-command parsing | Design principle | Parser specified per-send, not per-channel |

#### Backend Features

| Feature | Location | Description |
|---------|----------|-------------|
| PTYBackend | `core/pty/pty_backend.py` | Direct pseudo-terminal via `pty.fork()` |
| WezTermBackend | `core/pty/wezterm_backend.py` | WezTerm CLI interface |
| read_stream() | Backend protocol | Async iterator for output |
| read_buffer() | Backend protocol | Read accumulated buffer |
| read_tail() | Backend protocol | Read last N lines |
| clear_buffer() | Backend protocol | Clear accumulated buffer |

#### DAG Features

| Feature | Location | Description |
|---------|----------|-------------|
| Task definition | `core/dag/task.py` | id, execute callable, depends_on |
| add_task() | DAG method | Add task to graph |
| chain() | DAG method | Set linear dependencies |
| validate() | DAG method | Check for cycles and missing deps |
| execution_order() | DAG method | Topological sort |
| run() | DAG method | Execute with parallel/serial control |
| Parallel execution | DAG.run() | Semaphore-controlled concurrency |
| Task callbacks | DAG.run() | on_task_start, on_task_complete |
| Error capture | DAG.run() | Failed tasks don't stop DAG |

#### Session Features

| Feature | Location | Description |
|---------|----------|-------------|
| Session | `core/session/session.py` | Groups channels with metadata |
| Session.add(name, channel) | Session method | Add channel to session |
| Session.get(name) | Session method | Get channel by name |
| Session.remove(name) | Session method | Remove channel (does NOT close) |
| Session.list_channels() | Session method | List all channel names |
| Session.send(name, ...) | Session method | Convenience method to send to channel |
| Session.close(name) | Session method | Close specific or all channels |
| ChannelManager | `core/session/manager.py` | Creates and manages channel lifecycle |
| ChannelManager.create_terminal() | Manager method | Factory for terminal channels |
| ChannelManager.add() | Manager method | Add existing channel |
| ChannelManager.get() | Manager method | Get channel by ID |
| ChannelManager.list() | Manager method | List all channel IDs |
| ChannelManager.list_open() | Manager method | List open channel IDs |
| ChannelManager.close() | Manager method | Close specific channel |
| ChannelManager.close_all() | Manager method | Close all channels |
| **SessionManager** | `core/session/manager.py` | CRUD for multiple sessions |
| SessionManager.create_session() | Manager method | Create new session with metadata |
| SessionManager.get_session() | Manager method | Get session by ID |
| SessionManager.find_by_name() | Manager method | Find session by name |
| SessionManager.list_sessions() | Manager method | List all session IDs |
| SessionManager.close_session() | Manager method | Close session and its channels |
| SessionManager.close_all() | Manager method | Close all sessions |
| History integration | ChannelManager | Optional per-channel history |

#### Session Persistence Features

| Feature | Location | Description |
|---------|----------|-------------|
| **SessionStore** | `core/session/persistence.py` | Persistent storage for session metadata |
| SessionStore.add() | Store method | Add/update session metadata |
| SessionStore.remove() | Store method | Remove session by ID |
| SessionStore.get() | Store method | Get session by ID |
| SessionStore.find_by_name() | Store method | Find by name |
| SessionStore.find_by_tag() | Store method | Find by tag |
| SessionStore.list() | Store method | List all sessions |
| SessionStore.save() | Store method | Save to JSON file |
| SessionStore.load() | Class method | Load from JSON file |
| **SessionMetadata** | `core/session/persistence.py` | Serializable session metadata |
| get_default_store() | Helper function | Get/create default store at ~/.nerve/sessions.json |

#### Server Features

| Feature | Location | Description |
|---------|----------|-------------|
| NerveEngine | `server/engine.py` | Command handler with event emission |
| EventSink | `server/protocols.py` | Event emission interface |
| **CommandType enum** | `server/protocols.py` | Command types accepted by server |
| CREATE_CHANNEL | CommandType | Create new channel |
| CLOSE_CHANNEL | CommandType | Close channel |
| LIST_CHANNELS | CommandType | List all channels |
| GET_CHANNEL | CommandType | Get channel info |
| RUN_COMMAND | CommandType | Fire and forget execution |
| SEND_INPUT | CommandType | Send and wait for response |
| SEND_INTERRUPT | CommandType | Send interrupt (Ctrl+C) |
| WRITE_DATA | CommandType | Raw write |
| **EXECUTE_DAG** | CommandType | Execute a DAG |
| **CANCEL_DAG** | CommandType | Cancel running DAG |
| GET_BUFFER | CommandType | Get channel buffer |
| GET_HISTORY | CommandType | Get channel history |
| SHUTDOWN | CommandType | Shutdown server |
| PING | CommandType | Health check |
| **EventType enum** | `server/protocols.py` | Event types emitted by server |
| CHANNEL_CREATED | EventType | Channel was created |
| CHANNEL_READY | EventType | Channel ready for input |
| CHANNEL_BUSY | EventType | Channel processing |
| CHANNEL_CLOSED | EventType | Channel was closed |
| OUTPUT_CHUNK | EventType | Raw output chunk |
| OUTPUT_PARSED | EventType | Parsed response |
| **DAG_STARTED** | EventType | DAG execution started |
| **TASK_STARTED** | EventType | Task execution started |
| **TASK_COMPLETED** | EventType | Task execution completed |
| **TASK_FAILED** | EventType | Task execution failed |
| **DAG_COMPLETED** | EventType | DAG execution completed |
| ERROR | EventType | Error occurred |
| SERVER_SHUTDOWN | EventType | Server shutting down |

#### Transport Features

| Feature | Location | Description |
|---------|----------|-------------|
| UnixSocketServer | `transport/unix.py` | Local IPC via Unix socket |
| TCPSocketServer | `transport/tcp.py` | Network-capable TCP server |
| HTTPServer | `transport/http.py` | REST API + WebSocket |
| InProcessTransport | `transport/` | In-memory transport for testing |
| UnixSocketClient | `transport/` | Client for Unix socket |
| HTTPClient | `transport/` | Client for HTTP server |

#### Frontend Features

| Feature | Location | Description |
|---------|----------|-------------|
| CLI | `frontends/cli/` | Full command hierarchy |
| `nerve server start` | CLI command | Start server daemon |
| `nerve server stop` | CLI command | Stop server daemon |
| `nerve server channel` | CLI command | Manage channels |
| **`nerve server dag run`** | CLI command | Execute DAG from file |
| **`nerve repl`** | CLI command | Interactive DAG definition/execution |
| **`nerve server repl`** | CLI command | Interactive REPL connected to server |
| `nerve extract` | CLI command | Parse AI CLI output |
| `nerve wezterm` | CLI command | Manage WezTerm panes |
| **SDK** | `frontends/sdk/` | Python SDK for remote access |
| **NerveClient** | SDK class | High-level client (remote or standalone) |
| **RemoteChannel** | SDK class | Proxy for remote channel |
| RemoteChannel.send() | SDK method | Send and get response |
| RemoteChannel.send_stream() | SDK method | Send and stream output chunks |
| RemoteChannel.interrupt() | SDK method | Send interrupt |
| RemoteChannel.close() | SDK method | Close channel |
| MCP | `frontends/mcp/` | Model Context Protocol server |

#### Compose Helpers

| Feature | Location | Description |
|---------|----------|-------------|
| **create_standalone()** | `compose.py` | Create in-process engine + transport |
| **create_socket_server()** | `compose.py` | Create Unix socket server |
| create_openai_proxy() | `compose.py` | Create OpenAI proxy server |
| create_anthropic_proxy() | `compose.py` | Create Anthropic proxy server |

#### Pattern Features

| Feature | Location | Description |
|---------|----------|-------------|
| DevCoachLoop | `core/patterns/dev_coach.py` | Developer-Coach collaboration |
| DebateLoop | `core/patterns/debate.py` | Two-agent debate |

---

## 4. Proposed Architecture

### 4.1 Core Abstractions

```
┌─────────────────────────────────────────────────────────────────────────┐
│ PROPOSED ARCHITECTURE                                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ NODE (Protocol - Unit of Work)                                    │   │
│  ├──────────────────────────────────────────────────────────────────┤   │
│  │ - id: str                                                         │   │
│  │ - persistent: bool (default: False)                               │   │
│  │ - async execute(context: ExecutionContext) -> Any                 │   │
│  │ - async start() -> None  (optional, for persistent nodes)         │   │
│  │ - async stop() -> None   (optional, for persistent nodes)         │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                              │                                           │
│    ┌─────────────────────────┼─────────────────────────────────┐        │
│    │                         │                                 │        │
│    ▼                         ▼                                 ▼        │
│ ┌─────────────┐      ┌─────────────┐                  ┌─────────────┐   │
│ │ FunctionNode│      │ TerminalNode│                  │    Graph    │   │
│ │ (ephemeral) │      │ (persistent)│                  │  (is Node)  │   │
│ │             │      │             │                  │             │   │
│ │ Pure fn     │      │ PTY/WezTerm │                  │ Contains    │   │
│ │ wrapper     │      │ channels    │                  │ steps with  │   │
│ │             │      │             │                  │ nodes       │   │
│ └─────────────┘      └─────────────┘                  └─────────────┘   │
│                             │                                │          │
│                             │                                │          │
│                      ┌──────┴──────┐                  ┌──────┴──────┐   │
│                      │             │                  │             │   │
│                      ▼             ▼                  ▼             ▼   │
│                  PTYNode     WezTermNode          Graph A       Graph B │
│                  (persistent) (persistent)       (nested)      (nested)│
│                                                                          │
│  ═══════════════════════════════════════════════════════════════════    │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ SESSION (Lifecycle Manager)                                       │   │
│  ├──────────────────────────────────────────────────────────────────┤   │
│  │ - Registers all nodes (persistent, ephemeral, graphs)             │   │
│  │ - Manages lifecycle of persistent nodes (start/stop)             │   │
│  │ - Provides node access by ID                                      │   │
│  │ - Handles scoping/isolation                                       │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ GRAPH (Orchestrator, IS a Node)                                   │   │
│  ├──────────────────────────────────────────────────────────────────┤   │
│  │ - Contains steps (node + input + dependencies)                    │   │
│  │ - Executes in topological order                                   │   │
│  │ - Supports both direct refs and ID-based refs                     │   │
│  │ - Can contain other Graphs (arbitrarily nested)                   │   │
│  │ - Same node can appear in multiple steps                          │   │
│  │ - Supports error policies per step                                │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Key Design Decisions

See [Section 10: Design Decisions](#10-design-decisions) for detailed rationale on all architectural choices (D1-D13).

### 4.3 ExecutionContext

The context passed through graph execution, carrying all runtime state:

```python
@dataclass
class ExecutionContext:
    session: Session
    input: Any = None
    upstream: dict[str, Any] = field(default_factory=dict)

    # P0 Agent Capabilities
    budget: Budget | None = None
    usage: ResourceUsage = field(default_factory=ResourceUsage)
    cancellation: CancellationToken | None = None
    trace: ExecutionTrace | None = None

    def with_input(self, input: Any) -> "ExecutionContext": ...
    def with_upstream(self, upstream: dict) -> "ExecutionContext": ...
    def check_cancelled(self) -> None: ...
    def check_budget(self) -> None: ...
    def record_step(self, ...) -> None: ...
```

**Note:** See [AGENT_CAPABILITIES.md](./AGENT_CAPABILITIES.md) REQ-B4 for full ExecutionContext definition including method implementations.

---

## 5. Detailed Requirements

### 5.1 Node Protocol

**REQ-N0: Core Types**

```python
class NodeState(Enum):
    """Node lifecycle states.

    State transitions:
        CREATED → STARTING → READY ⟷ BUSY → STOPPING → STOPPED

    Mapping from ChannelState:
        ChannelState.CONNECTING → NodeState.STARTING
        ChannelState.OPEN       → NodeState.READY
        ChannelState.BUSY       → NodeState.BUSY
        ChannelState.CLOSED     → NodeState.STOPPED
    """
    CREATED = auto()   # Node instantiated but not started
    STARTING = auto()  # Node is initializing (connecting, spawning process)
    READY = auto()     # Node is ready for input
    BUSY = auto()      # Node is processing
    STOPPING = auto()  # Node is shutting down (cleanup in progress)
    STOPPED = auto()   # Node is stopped and cannot be used


@dataclass
class NodeInfo:
    """Serializable node information.

    Maps from ChannelInfo with renamed fields.
    """
    id: str
    node_type: str           # Was: channel_type.value
    state: NodeState
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "type": self.node_type,
            "state": self.state.name,
            "metadata": self.metadata,
        }


@dataclass
class NodeConfig:
    """Base configuration for nodes.

    Maps directly from ChannelConfig.
    """
    id: str | None = None  # Auto-generated if not provided
    metadata: dict[str, Any] = field(default_factory=dict)
```

**REQ-N1: Node Protocol Definition**

```python
class Node(Protocol):
    """Base protocol for all executable units of work."""

    @property
    def id(self) -> str:
        """Unique identifier for this node."""
        ...

    @property
    def persistent(self) -> bool:
        """Whether this node maintains state across executions."""
        ...

    async def execute(self, context: ExecutionContext) -> Any:
        """Execute this node with the given context."""
        ...
```

**REQ-N2: Persistent Node Lifecycle**

Persistent nodes (nodes with `persistent=True`) must implement optional lifecycle methods:

```python
class PersistentNode(Node):
    persistent = True

    async def start(self) -> None:
        """Initialize resources. Called by Session.start()."""
        ...

    async def stop(self) -> None:
        """Release resources. Called by Session.stop()."""
        ...

    async def reset(self) -> None:
        """Reset state while keeping resources. Optional."""
        ...
```

**REQ-N3: Node Implementations**

| Node Type | Persistent | Description | Replaces |
|-----------|------------|-------------|----------|
| FunctionNode | No | Wraps sync/async callable | Task with pure fn |
| PTYNode | Yes | PTY-based terminal | PTYChannel |
| WezTermNode | Yes | WezTerm pane attachment | WezTermChannel |
| ClaudeWezTermNode | Yes | Claude in WezTerm | ClaudeOnWezTermChannel |
| Graph | No | Contains steps | DAG |

**REQ-N3a: FunctionNode Specification**

FunctionNode wraps a sync or async callable as an ephemeral node:

```python
@dataclass
class FunctionNode:
    """Wraps a sync or async callable as a node.

    FunctionNodes are stateless (ephemeral) - they can be called multiple
    times with different inputs and produce independent results.

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
    """

    id: str
    fn: Callable[[ExecutionContext], Any]
    persistent: bool = field(default=False, init=False)

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
```

**REQ-N4: Terminal Node Streaming**

Terminal nodes must support streaming output via `execute_stream()`:

```python
class TerminalNode(Node):
    """Base class for terminal-based nodes."""

    # Default parser can be set per-node (e.g., ClaudeWezTermNode defaults to CLAUDE)
    _default_parser: ParserType = ParserType.NONE

    async def execute(self, context: ExecutionContext) -> ParsedResponse:
        """Send input and wait for complete response.

        Parser resolution order:
            1. context.parser (if specified)
            2. self._default_parser (node's default)
            3. ParserType.NONE (fallback)

        ClaudeWezTermNode example:
            - _default_parser = ParserType.CLAUDE
            - Caller can override: context.parser = ParserType.NONE
        """
        parser = context.parser or self._default_parser or ParserType.NONE
        ...

    async def execute_stream(self, context: ExecutionContext) -> AsyncIterator[str]:
        """Send input and stream output chunks.

        Parser determines when streaming is complete (via is_ready() check).

        Yields:
            Output chunks as they arrive.

        Example:
            async for chunk in node.execute_stream(context):
                print(chunk, end="", flush=True)
        """
        parser = context.parser or self._default_parser or ParserType.NONE
        ...

    # Additional terminal-specific methods
    async def write(self, data: str) -> None: ...
    async def read(self) -> str: ...
    def read_tail(self, lines: int = 50) -> str: ...
    def clear_buffer(self) -> None: ...
    async def interrupt(self) -> None: ...

    # WezTerm-specific methods (only on WezTermNode, ClaudeWezTermNode)
    async def focus(self) -> None:
        """Focus/activate the WezTerm pane. WezTerm-specific."""
        ...

    async def get_pane_info(self) -> dict | None:
        """Get WezTerm pane metadata. WezTerm-specific."""
        ...
```

**Note:** `focus()` and `get_pane_info()` are WezTerm-specific and not part of the base TerminalNode protocol. They are implementation details of WezTermNode and ClaudeWezTermNode.

**REQ-N5: Streaming History Logging**

When `execute_stream()` is used, history logs the final buffer state after streaming completes, NOT individual chunks:

```python
async def execute_stream(self, context: ExecutionContext) -> AsyncIterator[str]:
    # ... yield chunks ...

    # After streaming completes, log final state
    if self._history_writer:
        self._history_writer.log_send_stream(
            input=context.input,
            final_buffer=self.read_tail(HISTORY_BUFFER_LINES),
            parser=context.parser.value if context.parser else "none",
        )
```

**REQ-N6: Wrapper Node History Ownership**

When a node wraps another node (e.g., ClaudeWezTermNode wrapping WezTermNode), the **wrapper owns the history writer, NOT the inner node**. This prevents double-logging.

```python
class ClaudeWezTermNode(TerminalNode):
    """Wrapper node optimized for Claude CLI on WezTerm.

    HISTORY OWNERSHIP: This wrapper owns the history writer.
    The inner WezTermNode has NO history writer.
    All history logging happens at this level.
    """

    _inner: WezTermNode
    _history_writer: HistoryWriter | None

    @classmethod
    async def create(cls, node_id: str, ..., history_writer: HistoryWriter | None = None):
        # Create inner node WITHOUT history writer - wrapper owns history
        inner = await WezTermNode.create(
            node_id=node_id,
            ...,
            history_writer=None,  # Inner has NO history
        )

        return cls(
            id=node_id,
            _inner=inner,
            _history_writer=history_writer,  # Wrapper owns history
        )
```

**REQ-N7: Buffer Management Semantics**

Different terminal node implementations have different buffer semantics:

| Node Type | Buffer Pattern | Notes |
|-----------|----------------|-------|
| `PTYNode` | Continuous accumulation | Buffer grows, use `_buffer_start` for incremental reads |
| `WezTermNode` | Always-fresh query | WezTerm maintains content, every read is fresh |

Implementations must document their buffer semantics:

```python
class PTYNode(TerminalNode):
    """PTY-based terminal node.

    BUFFER SEMANTICS: Continuous accumulation.
    - Buffer grows continuously as output is received
    - Use buffer_start position for incremental parsing
    - Background reader task captures output
    - Polling interval: 0.3 seconds for ready detection
    """
    ...

class WezTermNode(TerminalNode):
    """WezTerm-based terminal node.

    BUFFER SEMANTICS: Always-fresh query.
    - WezTerm maintains pane content internally
    - Every buffer read queries WezTerm directly
    - No background reader needed
    - Polling interval: 2.0 seconds for ready detection
    """
    ...
```

### 5.2 Graph Requirements

**REQ-G1: Graph as Node**

Graph must implement the Node protocol:

```python
class Graph(Node):
    id: str
    persistent: bool = False  # Graphs are ephemeral by default

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Execute all steps in topological order."""
        ...
```

**REQ-G2: Step Definition**

A step combines a node with input and dependencies:

```python
@dataclass
class Step:
    node: Node | None = None         # Direct reference
    node_ref: str | None = None      # ID-based reference
    input: Any = None                # Static input value
    input_fn: Callable[[dict[str, Any]], Any] | None = None  # Dynamic input from upstream
    depends_on: list[str] = field(default_factory=list)
    error_policy: ErrorPolicy | None = None
    parser: ParserType | None = None  # Override default parser for this step
```

**REQ-G2a: Input Resolution**

Step input is resolved in priority order:
1. `input_fn(upstream_results)` if provided - dynamic transformation
2. `input` if provided - static value
3. `None` if neither provided

```python
def _resolve_input(self, step: Step, upstream: dict[str, Any]) -> Any:
    """Resolve step input from static value or dynamic function."""
    if step.input_fn is not None:
        return step.input_fn(upstream)
    return step.input
```

**Example usage:**

```python
# Static input
graph.add_step(node_a, step_id="fetch", input="https://api.example.com")

# Dynamic input - transform upstream results
graph.add_step(
    node_b,
    step_id="process",
    depends_on=["fetch"],
    input_fn=lambda upstream: upstream["fetch"]["data"].upper()
)

# Dynamic input - combine multiple upstream results
graph.add_step(
    node_c,
    step_id="merge",
    depends_on=["step1", "step2"],
    input_fn=lambda u: {"a": u["step1"], "b": u["step2"]}
)
```

**REQ-G3: Graph API**

```python
class Graph(Node):
    def add_step(
        self,
        node: Node,
        step_id: str,
        input: Any = None,
        input_fn: Callable[[dict[str, Any]], Any] | None = None,
        depends_on: list[str] | None = None,
        error_policy: ErrorPolicy | None = None,
        parser: ParserType | None = None,
    ) -> "Graph":
        """Add step with direct node reference.

        Args:
            node: The node to execute.
            step_id: Unique identifier for this step.
            input: Static input value (mutually exclusive with input_fn).
            input_fn: Dynamic input function that receives upstream results.
            depends_on: List of step IDs this step depends on.
            error_policy: How to handle errors in this step.
            parser: Parser to use for this step (overrides node default).
        """
        ...

    def add_step_ref(
        self,
        node_id: str,
        step_id: str,
        input: Any = None,
        input_fn: Callable[[dict[str, Any]], Any] | None = None,
        depends_on: list[str] | None = None,
        error_policy: ErrorPolicy | None = None,
        parser: ParserType | None = None,
    ) -> "Graph":
        """Add step with node ID (resolved from session at execution)."""
        ...

    def chain(self, *step_ids: str) -> "Graph":
        """Set linear dependencies between steps."""
        ...

    def validate(self) -> list[str]:
        """Validate graph structure and configuration.

        Checks for:
        - Empty or whitespace-only step IDs
        - Duplicate step IDs (caught by add_step)
        - Self-dependencies
        - Mutually exclusive input/input_fn
        - Missing dependencies
        - Cycles

        Returns:
            List of error messages (empty if valid).
        """
        errors = []

        for step_id, step in self._steps.items():
            # Check for empty step IDs
            if not step_id or not step_id.strip():
                errors.append("Empty step_id not allowed")

            # Check for self-dependencies
            if step_id in step.depends_on:
                errors.append(f"Step '{step_id}' depends on itself")

            # Check for mutually exclusive input/input_fn
            if step.input is not None and step.input_fn is not None:
                errors.append(f"Step '{step_id}': input and input_fn are mutually exclusive")

            # Check for missing dependencies
            for dep_id in step.depends_on:
                if dep_id not in self._steps:
                    errors.append(f"Step '{step_id}' depends on unknown step '{dep_id}'")

        # Check for cycles (only if no other errors)
        if not errors:
            try:
                graph = {sid: set(s.depends_on) for sid, s in self._steps.items()}
                list(TopologicalSorter(graph).static_order())
            except Exception as e:
                errors.append(f"Cycle detected: {e}")

        return errors

    def execution_order(self) -> list[str]:
        """Return topological order of step IDs."""
        ...

    def get_step(self, step_id: str) -> Step | None:
        """Get a step by ID."""
        ...

    def list_steps(self) -> list[str]:
        """List all step IDs."""
        ...
```

**REQ-G4: Nested Graphs**

Graphs can contain other graphs as steps:

```python
subgraph = Graph(id="sub")
subgraph.add_step(node_a, step_id="a")
subgraph.add_step(node_b, step_id="b", depends_on=["a"])

main = Graph(id="main")
main.add_step(subgraph, step_id="setup")  # Graph as step
main.add_step(node_c, step_id="work", depends_on=["setup"])
```

**REQ-G5: Graph Execution**

```python
async def execute(self, context: ExecutionContext) -> dict[str, Any]:
    """
    Execute graph steps in topological order.

    Returns:
        Dict mapping step_id to step result
    """
    results = {}

    for step_id in self.execution_order():
        context.check_cancelled()
        context.check_budget()

        step = self._steps[step_id]
        node = self._resolve_node(step, context.session)

        # Resolve input: input_fn takes priority over static input
        step_input = self._resolve_input(step, results)
        step_context = context.with_input(step_input).with_upstream(results)

        result = await self._execute_with_policy(step, node, step_context)
        results[step_id] = result

        context.record_step(step_id, node, step_input, result)

    return results
```

**REQ-G6: Graph Streaming Execution**

Graph supports streaming execution for agent loops and real-time feedback:

```python
@dataclass
class StepEvent:
    """Event emitted during streaming graph execution."""
    event_type: Literal["step_start", "step_chunk", "step_complete", "step_error"]
    step_id: str
    node_id: str
    data: Any = None  # chunk content, result, or error
    timestamp: datetime = field(default_factory=datetime.now)


class Graph(Node):
    async def execute_stream(
        self, context: ExecutionContext
    ) -> AsyncIterator[StepEvent]:
        """
        Execute graph steps and stream events as they occur.

        Yields:
            StepEvent for each step lifecycle event.

        Note:
            This method does NOT return final results. Callers should collect
            results from step_complete events if needed:

                results = {}
                async for event in graph.execute_stream(context):
                    if event.event_type == "step_complete":
                        results[event.step_id] = event.data

        Example:
            async for event in graph.execute_stream(context):
                if event.event_type == "step_chunk":
                    print(event.data, end="", flush=True)
                elif event.event_type == "step_complete":
                    print(f"\\n[{event.step_id} done]")
        """
        results = {}

        for step_id in self.execution_order():
            context.check_cancelled()
            context.check_budget()

            step = self._steps[step_id]
            node = self._resolve_node(step, context.session)

            # Resolve input: input_fn takes priority over static input
            step_input = self._resolve_input(step, results)
            step_context = context.with_input(step_input).with_upstream(results)

            yield StepEvent("step_start", step_id, node.id)

            try:
                # If terminal node, stream chunks
                if hasattr(node, "execute_stream"):
                    chunks = []
                    async for chunk in node.execute_stream(step_context):
                        chunks.append(chunk)
                        yield StepEvent("step_chunk", step_id, node.id, chunk)
                    result = "".join(chunks)  # Or parsed result
                else:
                    result = await self._execute_with_policy(step, node, step_context)

                results[step_id] = result
                yield StepEvent("step_complete", step_id, node.id, result)

            except Exception as e:
                yield StepEvent("step_error", step_id, node.id, str(e))
                raise

        # Note: Async generators cannot return values. Results are
        # available via step_complete events.
```

**Note:** `execute_stream()` enables:
- Real-time progress for long-running steps
- Agent loops with intermediate feedback
- UI updates during graph execution

### 5.3 Session Requirements

**REQ-S1: Session as Registry**

Session stores all nodes (persistent, ephemeral, graphs):

```python
class Session:
    def __init__(self, id: str | None = None):
        self.id = id or str(uuid4())
        self._registry: dict[str, Node] = {}

    def register(self, node: Node, name: str | None = None) -> None:
        """Register a node with an optional custom name.

        Args:
            node: The node to register.
            name: Optional name for lookup (defaults to node.id).
                  Allows the same node to be referenced by a different name
                  than its internal ID.

        Raises:
            ValueError: If name already exists in registry.

        Example:
            # Register with node's ID
            session.register(node)  # Lookup key = node.id

            # Register with custom name
            session.register(node, name="dev")  # Lookup key = "dev"
        """
        key = name or node.id
        if key in self._registry:
            raise ValueError(f"Name '{key}' already exists in session")
        self._registry[key] = node

    def unregister(self, name: str) -> Node | None:
        """Remove a node from registry (does NOT stop it).

        Args:
            name: The name used when registering the node.

        Returns:
            The removed node, or None if not found.
        """
        return self._registry.pop(name, None)

    def get(self, name: str) -> Node | None:
        """Get node by name.

        Args:
            name: The name used when registering the node.

        Returns:
            The node, or None if not found.
        """
        return self._registry.get(name)

    def list_nodes(self) -> list[str]:
        """List all registered node names."""
        return list(self._registry.keys())

    def list_ready_nodes(self) -> list[str]:
        """List names of nodes in READY or BUSY state (non-stopped).

        Maps from ChannelManager.list_open() - returns active nodes only.
        """
        return [
            name for name, node in self._registry.items()
            if hasattr(node, 'state') and node.state not in (
                NodeState.STOPPED, NodeState.CREATED, NodeState.STOPPING
            )
        ]
```

**REQ-S2: Lifecycle Management**

Session manages lifecycle of persistent nodes:

```python
class Session:
    async def start(self) -> None:
        """Start all persistent nodes (including those inside graphs)."""
        for node in self._collect_persistent_nodes():
            await node.start()

    async def stop(self) -> None:
        """Stop all persistent nodes."""
        for node in self._collect_persistent_nodes():
            await node.stop()

    def _collect_persistent_nodes(self) -> list[Node]:
        """Recursively find all persistent nodes."""
        persistent = []
        for node in self._registry.values():
            if node.persistent:
                persistent.append(node)
            if isinstance(node, Graph):
                persistent.extend(node.collect_persistent_nodes())
        return persistent
```

**REQ-S3: Backward Compatibility**

Session must maintain backward-compatible methods for channel operations:

```python
class Session:
    # New API
    def register(self, node: Node, name: str | None = None) -> None: ...
    def get(self, name: str) -> Node | None: ...
    def unregister(self, name: str) -> Node | None: ...
    def list_nodes(self) -> list[str]: ...

    # Backward-compatible API (delegates to new methods)
    def add(self, name: str, channel: Channel) -> None:
        """Deprecated: Use register(node, name) instead.

        Preserves current behavior where name can differ from channel.id.
        """
        warnings.warn(
            "Session.add() is deprecated, use Session.register(node, name)",
            DeprecationWarning,
            stacklevel=2,
        )
        self.register(channel, name=name)

    def get_channel(self, name: str) -> Channel | None:
        """Deprecated: Use get() instead."""
        return self.get(name)

    def list_channels(self) -> list[str]:
        """Deprecated: Use list_nodes() instead."""
        return self.list_nodes()

    async def send(
        self,
        name: str,
        input: str,
        parser: ParserType | None = None,
        timeout: float | None = None,
    ) -> ParsedResponse:
        """Backward-compatible send. Translates to node.execute().

        Args:
            name: Node name.
            input: Input to send.
            parser: Parser type.
            timeout: Response timeout.

        Returns:
            Parsed response.
        """
        node = self.get(name)
        if not node:
            raise KeyError(f"Node '{name}' not found in session")

        # Build context from legacy parameters
        context = ExecutionContext(
            session=self,
            input=input,
            parser=parser,
            timeout=timeout,
        )

        return await node.execute(context)
```

### 5.4 NodeFactory Requirements

**REQ-F1: NodeFactory**

NodeFactory is a **standalone factory** that replaces ChannelManager for creating nodes. Session does NOT require a NodeFactory - it's a separate concern.

```python
class NodeFactory:
    """Factory for creating different node types.

    NodeFactory creates nodes but does NOT register them.
    Registration is a separate step via Session.register().

    Attributes:
        server_name: Name used for history file paths.
        history_base_dir: Base directory for history files.
    """

    _server_name: str = "default"
    _history_base_dir: Path | None = None

    async def create_terminal(
        self,
        node_id: str,
        command: str | list[str] | None = None,
        backend: BackendType = BackendType.PTY,
        cwd: str | None = None,
        pane_id: str | None = None,
        history: bool = True,
    ) -> TerminalNode:
        """Create a terminal node (PTY or WezTerm).

        The returned node is already started and ready for use.
        This matches current ChannelManager.create_terminal() behavior.

        Returns:
            A started TerminalNode (PTYNode or WezTermNode).
        """
        ...

    def create_function(
        self,
        node_id: str,
        fn: Callable[[ExecutionContext], Any],
    ) -> FunctionNode:
        """Create a function node wrapping a callable."""
        return FunctionNode(id=node_id, fn=fn)
```

**Usage Patterns:**

```python
# Pattern 1: Standalone factory (recommended)
factory = NodeFactory()
node = await factory.create_terminal("my-node", command="bash")  # Already started
session = Session()
session.register(node)  # Register for lookup/lifecycle
result = await node.execute(ExecutionContext(session=session, input="ls"))

# Pattern 2: Session with optional factory reference (convenience)
session = Session()
session.node_factory = NodeFactory()  # Optional assignment
node = await session.node_factory.create_terminal("my-node", command="bash")
session.register(node)
```

**Note:** NodeFactory creates nodes but does NOT auto-register them. Registration is always explicit via `session.register(node)`.

**Note:** P0 agent capabilities (error handling, budgets, cancellation, observability, parallelism) are covered in [AGENT_CAPABILITIES.md](./AGENT_CAPABILITIES.md).

---

## 6. Feature Mapping

This section ensures no feature regression by mapping every current feature to its equivalent in the new architecture.

### 6.1 Channel → Node Mapping

| Current (Channel) | New (Node) | Notes |
|-------------------|------------|-------|
| `Channel.id` | `Node.id` | Direct mapping |
| `Channel.channel_type` | Type-specific node class | PTYNode, WezTermNode |
| `Channel.state` | Internal to node impl | Node manages own state |
| `Channel.send(input, parser, timeout)` | `Node.execute(context)` | Parser in context or step config |
| **`Channel.send_stream(input, parser)`** | **`TerminalNode.execute_stream(context)`** | Returns async iterator of chunks |
| `Channel.run(command)` | `Node.execute(context)` with fire-and-forget | Step error_policy skip on error |
| `Channel.write(data)` | Terminal node method | `TerminalNode.write(data)` |
| `Channel.read()` | Terminal node method | `TerminalNode.read()` |
| **`Channel.read_tail(lines)`** | **`TerminalNode.read_tail(lines)`** | Read last N lines |
| `Channel.interrupt()` | Terminal node method | `TerminalNode.interrupt()` |
| `Channel.close()` | `PersistentNode.stop()` | Called by Session |
| `Channel.is_open` | Node internal state | Implementation detail |
| Buffer tracking | Terminal node internal | PTYNode maintains buffer |
| **`clear_buffer()`** | **`TerminalNode.clear_buffer()`** | Clear accumulated buffer |
| **`ChannelType.TERMINAL`** | `PTYNode`, `WezTermNode` | Specific node classes |
| **`ChannelType.SQL`** | `SQLNode` (future) | Out of scope for this PRD |
| **`ChannelType.HTTP`** | Future `HTTPNode` | Out of scope (NG9) |

### 6.2 DAG → Graph Mapping

**Note:** The `Task` class is fully replaced by the combination of `FunctionNode` (for the execution logic) and `Step` (for graph positioning and dependencies). The Task class will be removed in Phase 3.

| Current (DAG) | New (Graph) | Notes |
|---------------|-------------|-------|
| `DAG.add_task(task)` | `Graph.add_step(node, step_id, ...)` | Deps in step, not task |
| `DAG.add_tasks(*tasks)` | Multiple `add_step()` calls | Or builder pattern |
| `DAG.chain(*task_ids)` | `Graph.chain(*step_ids)` | Same semantics |
| `DAG.get_task(task_id)` | `Graph.get_step(step_id)` | Same semantics |
| `DAG.list_tasks()` | `Graph.list_steps()` | Same semantics |
| `DAG.validate()` | `Graph.validate()` | Same semantics |
| `DAG.execution_order()` | `Graph.execution_order()` | Same semantics |
| `DAG.run(parallel, max_workers)` | `Graph.execute(context)` | Parallel via `max_parallel` |
| `Task.depends_on` | `Step.depends_on` | Moved to step |
| `Task.execute(ctx)` | `Node.execute(context)` | Same pattern |
| on_task_start callback | Trace via context | Record in ExecutionTrace |
| on_task_complete callback | Trace via context | Record in ExecutionTrace |

**Migration Note: TaskResult Metadata**

`DAG.run()` returns `dict[str, TaskResult]` where TaskResult includes:
- `status` (COMPLETED/FAILED)
- `duration_ms`
- `error`
- `output`

`Graph.execute()` returns `dict[str, Any]` (raw outputs only).

To get execution metadata, use ExecutionTrace:

```python
# Old way
results = await dag.run()
task_result = results["fetch"]  # TaskResult with status, duration_ms, error, output

# New way
trace = ExecutionTrace(graph_id="pipeline", start_time=datetime.now())
results = await graph.execute(ExecutionContext(session=session, trace=trace))
output = results["fetch"]  # Raw output only

# Get metadata from trace
step_trace = next(s for s in trace.steps if s.step_id == "fetch")
duration_ms = step_trace.duration_ms
error = step_trace.error
```

### 6.3 Session Mapping

| Current (Session) | New (Session) | Notes |
|-------------------|---------------|-------|
| `Session.add(name, channel)` | `Session.register(node, name)` | name parameter preserved |
| `Session.get(name)` | `Session.get(node_id)` | Same semantics |
| `Session.remove(name)` | `Session.unregister(node_id)` | New method name |
| `Session.list_channels()` | `Session.list_nodes()` | Renamed |
| `Session.get_channel_info()` | `Session.get_node_info()` | Renamed |
| `Session.send(name, ...)` | Backward compatible | Delegates to `node.execute()` |
| `Session.close(name)` | `Session.stop()` for all | Or stop single node |
| `Session.to_dict()` | `Session.to_dict()` | **Unchanged** |
| `Session.__len__`, `__contains__` | Same | **Unchanged** - standard methods |

### 6.4 ChannelManager Mapping

| Current (ChannelManager) | New | Notes |
|--------------------------|-----|-------|
| `create_terminal(...)` | `NodeFactory.create_terminal(...)` | New factory class |
| `get(channel_id)` | `Session.get(node_id)` | Session is registry |
| `list()` | `Session.list_nodes()` | Session is registry |
| `list_open()` | `Session.list_ready_nodes()` | Returns only READY/BUSY nodes |
| `close_channel(id)` | `node.stop()` | Direct node method |
| `close_all()` | `Session.stop()` | Session lifecycle |

### 6.5 Type Mapping

| Current | New | Notes |
|---------|-----|-------|
| `ChannelInfo` | `NodeInfo` | Renamed, same structure |
| `ChannelConfig` | `NodeConfig` | Renamed, same structure |
| `ChannelState.CONNECTING` | `NodeState.STARTING` | Renamed |
| `ChannelState.OPEN` | `NodeState.READY` | Renamed |
| `ChannelState.BUSY` | `NodeState.BUSY` | **Unchanged** |
| `ChannelState.CLOSED` | `NodeState.STOPPED` | Renamed |
| N/A | `NodeState.CREATED` | New state (before STARTING) |
| N/A | `NodeState.STOPPING` | New state (between BUSY and STOPPED) |

### 6.6 History Mapping

| Current | New | Notes |
|---------|-----|-------|
| HistoryWriter per channel | HistoryWriter per node | Same mechanism |
| HistoryReader | HistoryReader | **Unchanged** |
| JSONL format | JSONL format | **Unchanged** |

**History vs Trace Distinction:**

History and Traces serve different purposes and **coexist**:

| Aspect | History (HistoryWriter) | Trace (ExecutionTrace) |
|--------|-------------------------|------------------------|
| **Scope** | Per-node operations | Per-graph execution |
| **What's logged** | Raw operations: send, write, read, interrupt, close | Step execution: inputs, outputs, timing, errors |
| **Methods** | `log_send()`, `log_write()`, `log_run()`, `log_interrupt()`, `log_close()` | `record_step()`, `record_error()` |
| **Format** | JSONL file per node | In-memory trace returned by Graph.execute() |
| **Purpose** | Debugging, replay, audit | Graph execution observability |

Both mechanisms are preserved. History logs raw terminal operations at the node level; traces record graph-level step execution.

**History Method Names Unchanged:**

History method names describe the **operation being performed**, not the abstraction name. They remain unchanged for backward compatibility:

| Method | Status | Rationale |
|--------|--------|-----------|
| `log_send()` | **Unchanged** | Describes "send input" operation |
| `log_send_stream()` | **Unchanged** | Describes "stream output" operation |
| `log_write()` | **Unchanged** | Describes "write data" operation |
| `log_read()` | **Unchanged** | Describes "read buffer" operation |
| `log_run()` | **Unchanged** | Describes "run command" operation |
| `log_interrupt()` | **Unchanged** | Describes "interrupt" operation |
| `log_close()` | **Unchanged** | Describes "close/stop" operation |

These method names are stable - they log what the operation *does*, not what abstraction it's called from.

**History File Structure:**

| Aspect | Value |
|--------|-------|
| Path | `.nerve/history/[server_name]/[node_id].jsonl` |
| Migration | Unchanged (node_id = channel_id for existing nodes) |
| Existing files | Remain valid and readable |

**History Scope:**

| Node Type | Has History | Notes |
|-----------|-------------|-------|
| PTYNode | Yes | All terminal operations logged |
| WezTermNode | Yes | All terminal operations logged |
| ClaudeWezTermNode | Yes | Wrapper owns history (REQ-N6) |
| FunctionNode | No | Pure computation, no I/O to log |
| Graph | No | Uses ExecutionTrace instead |
**Trace-History Correlation:**

ExecutionTrace and node history are **independent but correlatable**:

| To find... | Use... |
|------------|--------|
| History file for a step | `StepTrace.node_id` → `.nerve/history/[server]/[node_id].jsonl` |
| History entries for a step | Filter by `StepTrace.start_time` to `StepTrace.end_time` |

No automatic cross-referencing. Correlation is manual via node_id + timestamp.

### 6.7 Unchanged Components

The following components require NO changes:

| Component | Location | Notes |
|-----------|----------|-------|
| Parser protocol | `core/parsers/` | ClaudeParser, GeminiParser, NoneParser |
| Backend protocol | `core/pty/` | PTYBackend, WezTermBackend, BackendConfig |
| SessionStore | `core/session/persistence.py` | JSON persistence, SessionMetadata |
| Compose helpers | `compose.py` | create_standalone, create_socket_server, etc. |
| Transport layer | `transport/` | Unix, TCP, HTTP transports (neutral to abstraction changes) |
| Validation | `core/validation.py` | validate_name(), is_valid_name() |

**Breaking changes (require migration):**

| Component | Change | Migration |
|-----------|--------|-----------|
| SessionManager.`channels` | Renamed to `node_factory` | Update property access |
| Per-command parsing | Now per-step parsing | Same pattern, different location |

**Note:** SessionManager.`channels` → `node_factory` is a **breaking change** for code that directly accesses this property. The deprecation shim will emit warnings during Phase 1-2.

### 6.8 SDK/RemoteChannel Mapping

| Current (SDK) | New | Notes |
|---------------|-----|-------|
| `NerveClient` | `NerveClient` | **Unchanged** |
| `NerveClient.connect()` | Same | Connects via Unix socket |
| `NerveClient.connect_http()` | Same | Connects via HTTP |
| `NerveClient.standalone()` | Same | Uses core directly |
| `NerveClient.create_channel()` | `NerveClient.create_node()` | Returns RemoteNode |
| `NerveClient.get_channel()` | `NerveClient.get_node()` | Returns RemoteNode |
| `NerveClient.list_channels()` | `NerveClient.list_nodes()` | Same semantics |
| `RemoteChannel` | `RemoteNode` | Renamed |
| `RemoteChannel.send()` | `RemoteNode.execute()` | Same semantics |
| `RemoteChannel.send_stream()` | `RemoteNode.execute_stream()` | Same semantics |
| `RemoteChannel.interrupt()` | `RemoteNode.interrupt()` | Same |
| `RemoteChannel.close()` | `RemoteNode.stop()` | Renamed |

**RemoteNode Convenience Methods:**

RemoteNode provides convenience method signatures that differ from core `Node.execute(context)`:

```python
class RemoteNode:
    """Proxy for a node on a remote server.

    RemoteNode provides convenience signatures for remote calls
    that construct ExecutionContext internally over the wire.
    """

    async def execute(
        self,
        input: str,
        parser: str | ParserType | None = None,
        timeout: float | None = None,
    ) -> ParsedResponse:
        """Send input and wait for response.

        This is a convenience method. The server constructs
        ExecutionContext from these parameters.

        Args:
            input: Input to send.
            parser: Parser type (string or enum).
            timeout: Response timeout in seconds.

        Returns:
            Parsed response from the node.
        """
        ...

    async def execute_stream(
        self,
        input: str,
        parser: str | ParserType | None = None,
    ) -> AsyncIterator[str]:
        """Send input and stream output chunks.

        Args:
            input: Input to send.
            parser: Parser type.

        Yields:
            Output chunks as they arrive.
        """
        ...
```

**Note:** This differs from core `Node.execute(context: ExecutionContext)` because RemoteNode handles context construction over the wire. The SDK convenience signatures match the old `RemoteChannel.send()` API for ease of migration.

### 6.9 Server Command/Event Mapping

**Command Types:**

| Current | New | Notes |
|---------|-----|-------|
| `CREATE_CHANNEL` | `CREATE_NODE` | Renamed |
| `CLOSE_CHANNEL` | `STOP_NODE` | Renamed (close→stop) |
| `LIST_CHANNELS` | `LIST_NODES` | Renamed |
| `GET_CHANNEL` | `GET_NODE` | Renamed |
| `EXECUTE_DAG` | `EXECUTE_GRAPH` | Renamed |
| `CANCEL_DAG` | `CANCEL_GRAPH` | Renamed |
| `RUN_COMMAND` | `RUN_COMMAND` | **Unchanged** |
| `SEND_INPUT` | `EXECUTE_INPUT` | Renamed (send→execute) |
| `SEND_INTERRUPT` | `SEND_INTERRUPT` | **Unchanged** |
| `WRITE_DATA` | `WRITE_DATA` | **Unchanged** |
| `GET_BUFFER` | `GET_BUFFER` | **Unchanged** |
| `GET_HISTORY` | `GET_HISTORY` | **Unchanged** |
| `SHUTDOWN` | `SHUTDOWN` | **Unchanged** |
| `PING` | `PING` | **Unchanged** |

**Event Types:**

| Current | New | Notes |
|---------|-----|-------|
| `CHANNEL_CREATED` | `NODE_CREATED` | Renamed |
| `CHANNEL_READY` | `NODE_READY` | Renamed |
| `CHANNEL_BUSY` | `NODE_BUSY` | Renamed |
| `CHANNEL_CLOSED` | `NODE_STOPPED` | Renamed (closed→stopped) |
| `DAG_STARTED` | `GRAPH_STARTED` | Renamed |
| `TASK_STARTED` | `STEP_STARTED` | Renamed (Task → Step) |
| `TASK_COMPLETED` | `STEP_COMPLETED` | Renamed |
| `TASK_FAILED` | `STEP_FAILED` | Renamed |
| `DAG_COMPLETED` | `GRAPH_COMPLETED` | Renamed |
| `OUTPUT_CHUNK` | `OUTPUT_CHUNK` | **Unchanged** |
| `OUTPUT_PARSED` | `OUTPUT_PARSED` | **Unchanged** |
| `ERROR` | `ERROR` | **Unchanged** |
| `SERVER_SHUTDOWN` | `SERVER_SHUTDOWN` | **Unchanged** |

**Backward Compatibility:** Old command/event types will be accepted/emitted with deprecation warnings for 2 versions, then removed.

### 6.10 CLI Command Mapping

| Current | New | Notes |
|---------|-----|-------|
| `nerve server dag run FILE` | `nerve server graph run FILE` | Renamed |
| `nerve repl` | `nerve repl` | **Unchanged** - uses Graph internally |
| `nerve server repl` | `nerve server repl` | **Unchanged** |
| `nerve server start` | `nerve server start` | **Unchanged** |
| `nerve server stop` | `nerve server stop` | **Unchanged** |
| `nerve server status` | `nerve server status` | **Unchanged** |
| `nerve server channel create` | `nerve server node create` | Renamed |
| `nerve server channel list` | `nerve server node list` | Renamed |
| `nerve server channel run` | `nerve server node run` | Renamed |
| `nerve server channel read` | `nerve server node read` | Renamed |
| `nerve server channel send` | `nerve server node execute` | Renamed (send→execute) |
| `nerve server channel write` | `nerve server node write` | Renamed |
| `nerve server channel interrupt` | `nerve server node interrupt` | Renamed |
| `nerve server channel history` | `nerve server node history` | Renamed |
| `nerve extract` | `nerve extract` | **Unchanged** |
| `nerve wezterm list` | `nerve wezterm list` | **Unchanged** |
| `nerve wezterm spawn` | `nerve wezterm spawn` | **Unchanged** |
| `nerve wezterm send` | `nerve wezterm send` | **Unchanged** |
| `nerve wezterm read` | `nerve wezterm read` | **Unchanged** |
| `nerve wezterm kill` | `nerve wezterm kill` | **Unchanged** |
| DAG commands in REPL | Graph commands in REPL | `dag load` → `graph load`, etc. |

**Backward Compatibility:** Old `channel` and `dag` commands will emit deprecation warnings and delegate to new commands.

### 6.11 MCP Frontend Mapping

| Current | New | Notes |
|---------|-----|-------|
| `NerveMCPServer` | `NerveMCPServer` | **Unchanged** - wrapper class |
| `nerve_create_channel` tool | `nerve_create_node` tool | Renamed |
| `nerve_send` tool | `nerve_execute` tool | Renamed |
| `nerve_list_channels` tool | `nerve_list_nodes` tool | Renamed |
| `nerve_close_channel` tool | `nerve_stop_node` tool | Renamed |

**Note:** MCP tools are renamed to match new terminology. The MCP server continues to use NerveEngine commands internally, which handle the mapping.

### 6.12 Pattern Migration

| Current | New | Notes |
|---------|-----|-------|
| `DevCoachLoop` | `DevCoachLoop` | Uses Session (which now contains Nodes) |
| `DevCoachConfig` | `DevCoachConfig` | **Unchanged** |
| `DevCoachResult` | `DevCoachResult` | **Unchanged** |
| `DebateLoop` | `DebateLoop` | Uses Session (which now contains Nodes) |

**Migration Details:**

Patterns like `DevCoachLoop` use `Session.send()` which internally delegates to channels. After refactoring:

```python
# Current implementation (in DevCoachLoop)
dev_response = await self.developer.send(dev_prompt)

# After refactoring - Session.send() still works
# It delegates to node.execute() internally
dev_response = await self.developer.send(dev_prompt)
```

Patterns require **no code changes** because:
1. Session maintains backward-compatible `send()` method
2. Session internally calls `node.execute()` instead of `channel.send()`
3. Response format (ParsedResponse) remains unchanged

---

## 7. Implementation Phases

### Phase 1: Core Abstractions

**Goal:** Implement Node protocol, Graph, and updated Session without breaking existing code.

**Deliverables:**

1. **Node Protocol** (`core/nodes/base.py`)
   - Node protocol definition
   - PersistentNode base class with lifecycle methods
   - FunctionNode implementation

2. **Terminal Nodes** (`core/nodes/terminal.py`)
   - PTYNode (uses PTYBackend directly, replaces PTYChannel)
   - WezTermNode (uses WezTermBackend directly, replaces WezTermChannel)
   - ClaudeWezTermNode (extends WezTermNode with Claude-specific parsing)

3. **Graph** (`core/nodes/graph.py`)
   - Graph class implementing Node
   - Step dataclass
   - Topological ordering
   - Sequential execution

4. **ExecutionContext** (`core/nodes/context.py`)
   - Basic context with session, input, upstream
   - with_input(), with_upstream() methods

5. **Updated Session** (`core/session/session.py`)
   - Add register(), get(), list_nodes()
   - Keep backward-compatible add(), get_channel()

**Tests:**
- Unit tests for each new class
- Integration tests for Graph execution
- Backward compatibility tests

**Note:** P0 agent capabilities (error handling, budgets, cancellation, observability, parallelism) are implemented separately in [AGENT_CAPABILITIES.md](./AGENT_CAPABILITIES.md) after Phase 1 is complete.

### Phase 2: Integration & Migration

**Goal:** Integrate with server layer and provide migration utilities.

**Deliverables:**

1. **NodeFactory** (`core/nodes/factory.py`)
   - create_terminal() replacing ChannelManager factory
   - create_function()
   - create_graph()

2. **Server Integration** (`server/protocols.py`, `server/engine.py`)

   **New CommandTypes:**
   ```python
   class CommandType(Enum):
       # Node management (renamed from CHANNEL_*)
       CREATE_NODE = auto()      # Was: CREATE_CHANNEL
       STOP_NODE = auto()        # Was: CLOSE_CHANNEL
       LIST_NODES = auto()       # Was: LIST_CHANNELS
       GET_NODE = auto()         # Was: GET_CHANNEL

       # Interaction (mostly unchanged)
       RUN_COMMAND = auto()
       EXECUTE_INPUT = auto()    # Was: SEND_INPUT
       SEND_INTERRUPT = auto()
       WRITE_DATA = auto()

       # Graph operations (renamed from DAG)
       EXECUTE_GRAPH = auto()    # Was: EXECUTE_DAG
       CANCEL_GRAPH = auto()     # Was: CANCEL_DAG

       # Query (unchanged)
       GET_BUFFER = auto()
       GET_HISTORY = auto()

       # Server control (unchanged)
       SHUTDOWN = auto()
       PING = auto()

       # Deprecated aliases (emit warnings, delegate to new)
       CREATE_CHANNEL = auto()   # -> CREATE_NODE
       CLOSE_CHANNEL = auto()    # -> STOP_NODE
       LIST_CHANNELS = auto()    # -> LIST_NODES
       GET_CHANNEL = auto()      # -> GET_NODE
       SEND_INPUT = auto()       # -> EXECUTE_INPUT
       EXECUTE_DAG = auto()      # -> EXECUTE_GRAPH
       CANCEL_DAG = auto()       # -> CANCEL_GRAPH
   ```

   **New EventTypes:**
   ```python
   class EventType(Enum):
       # Node lifecycle (renamed from CHANNEL_*)
       NODE_CREATED = auto()       # Was: CHANNEL_CREATED
       NODE_READY = auto()         # Was: CHANNEL_READY
       NODE_BUSY = auto()          # Was: CHANNEL_BUSY
       NODE_STOPPED = auto()       # Was: CHANNEL_CLOSED

       # Output (unchanged)
       OUTPUT_CHUNK = auto()
       OUTPUT_PARSED = auto()

       # Graph execution (renamed from DAG/TASK_*)
       GRAPH_STARTED = auto()      # Was: DAG_STARTED
       STEP_STARTED = auto()       # Was: TASK_STARTED
       STEP_COMPLETED = auto()     # Was: TASK_COMPLETED
       STEP_FAILED = auto()        # Was: TASK_FAILED
       GRAPH_COMPLETED = auto()    # Was: DAG_COMPLETED

       # Errors and Server (unchanged)
       ERROR = auto()
       SERVER_SHUTDOWN = auto()

       # Deprecated aliases (emit warnings, delegate to new)
       CHANNEL_CREATED = auto()    # -> NODE_CREATED
       CHANNEL_READY = auto()      # -> NODE_READY
       CHANNEL_BUSY = auto()       # -> NODE_BUSY
       CHANNEL_CLOSED = auto()     # -> NODE_STOPPED
       DAG_STARTED = auto()        # -> GRAPH_STARTED
       TASK_STARTED = auto()       # -> STEP_STARTED
       TASK_COMPLETED = auto()     # -> STEP_COMPLETED
       TASK_FAILED = auto()        # -> STEP_FAILED
       DAG_COMPLETED = auto()      # -> GRAPH_COMPLETED
   ```

3. **CLI Updates** (`frontends/cli/main.py`)
   - Add `nerve server graph run FILE` command
   - `nerve server dag run` emits deprecation warning, delegates to `graph run`
   - Update REPL to use Graph terminology
   - Update help text

4. **SDK Updates** (`frontends/sdk/client.py`)
   - Add `RemoteNode` class (new name for RemoteChannel)
   - Add `execute_stream()` method
   - `RemoteChannel` becomes alias for `RemoteNode` (deprecated)
   - `NerveClient.create_node()` (new), `create_channel()` deprecated

5. **Migration Utilities**
   - Adapter: Channel → Node wrapper
   - Adapter: DAG → Graph converter
   - Deprecation warnings on old APIs

6. **HTTP Transport Updates** (`transport/http.py`)
   - Update message format: `channel_id` → `node_id`
   - Update event names per Section 6.9

7. **MCP Frontend Updates** (`frontends/mcp/`)
   - Rename tools per Section 6.11
   - Add deprecation warnings for old tool names (2 version period)

8. **Compose Helpers Review** (`compose.py`)
   - Verify `create_standalone()` works with new Session/NodeFactory
   - No breaking changes expected (internal implementation update)

9. **SessionManager Deprecation Shim**
   - Add `SessionManager.channels` property that returns `node_factory` with deprecation warning
   - Emit warnings for 2 versions before removal

10. **Documentation**
    - Updated API docs
    - Migration guide
    - Examples

**Tests:**
- Server integration tests
- Migration adapter tests
- End-to-end tests
- CLI command tests
- SDK client tests
- HTTP transport message format tests
- MCP tool rename tests

### Phase 3: Cleanup & Optimization

**Goal:** Remove deprecated code and optimize.

**Deliverables:**

1. **Deprecation Removal** (after migration period)
   - Remove Channel protocol (replaced by Node)
   - Remove DAG class (replaced by Graph)
   - Remove Task class (replaced by FunctionNode + Step)
   - Remove ChannelManager (replaced by Session + NodeFactory)

2. **Optimization**
   - Profile graph execution
   - Optimize hot paths
   - Memory optimization for large graphs

3. **Polish**
   - Complete test coverage
   - Performance benchmarks
   - Final documentation

---

## 8. Testing Strategy

### 8.1 Test Categories

| Category | Purpose | Coverage Target |
|----------|---------|-----------------|
| Unit Tests | Individual class behavior | 100% of new code |
| Integration Tests | Component interaction | All integration points |
| Backward Compat Tests | Old API still works | All deprecated methods |
| Regression Tests | No feature loss | All features in Section 3 |
| Performance Tests | No performance degradation | Critical paths |

### 8.2 Test Files

| File | Tests |
|------|-------|
| `tests/core/nodes/test_base.py` | Node protocol, FunctionNode |
| `tests/core/nodes/test_terminal.py` | PTYNode, WezTermNode |
| `tests/core/nodes/test_graph.py` | Graph execution, nesting |
| `tests/core/nodes/test_context.py` | ExecutionContext |
| `tests/core/nodes/test_policies.py` | ErrorPolicy, retry, fallback |
| `tests/core/nodes/test_budget.py` | Budget, ResourceUsage |
| `tests/core/nodes/test_cancellation.py` | CancellationToken |
| `tests/core/nodes/test_trace.py` | StepTrace, ExecutionTrace |
| `tests/core/nodes/test_parallel.py` | Parallel execution |
| `tests/core/session/test_session_nodes.py` | Session with nodes |
| `tests/core/test_migration.py` | Backward compatibility |

### 8.3 Regression Test Matrix

Every feature from Section 3.2 must have a corresponding test proving it works in the new architecture:

| Feature | Current Test | New Test |
|---------|--------------|----------|
| **Channel Features** | | |
| PTYChannel.send() | test_channels.py | test_terminal.py::test_pty_node_execute |
| PTYChannel.send_stream() | test_channels.py | test_terminal.py::test_pty_node_execute_stream |
| WezTermChannel.send() | test_channels.py | test_terminal.py::test_wezterm_node_execute |
| Channel.run() | test_channels.py | test_terminal.py::test_node_run |
| Channel.write() | test_channels.py | test_terminal.py::test_node_write |
| Channel.read() | test_channels.py | test_terminal.py::test_node_read |
| Channel.read_tail() | test_channels.py | test_terminal.py::test_node_read_tail |
| Channel.interrupt() | test_channels.py | test_terminal.py::test_node_interrupt |
| Channel.close() | test_channels.py | test_terminal.py::test_node_stop |
| **DAG Features** | | |
| DAG.run(parallel=True) | test_dag.py | test_graph.py::test_parallel_execution |
| DAG.run(parallel=False) | test_dag.py | test_graph.py::test_sequential_execution |
| DAG.chain() | test_dag.py | test_graph.py::test_chain |
| DAG.validate() | test_dag.py | test_graph.py::test_validate |
| DAG.execution_order() | test_dag.py | test_graph.py::test_execution_order |
| Task callbacks | test_dag.py | test_graph.py::test_trace_records_steps |
| **Session Features** | | |
| Session.add() | test_managers.py | test_migration.py::test_session_add_compat |
| Session.get() | test_managers.py | test_session.py::test_session_get |
| Session.send() | test_managers.py | test_migration.py::test_session_send_compat |
| SessionManager.create_session() | test_managers.py | test_managers.py (unchanged) |
| SessionManager.list_sessions() | test_managers.py | test_managers.py (unchanged) |
| **Persistence Features** | | |
| SessionStore.save/load | test_persistence.py | test_persistence.py (unchanged) |
| SessionMetadata | test_persistence.py | test_persistence.py (unchanged) |
| **History Features** | | |
| History logging | test_history.py | test_terminal.py::test_node_history |
| History streaming | test_history.py | test_terminal.py::test_node_history_streaming |
| **Server Features** | | |
| EXECUTE_DAG command | test_engine.py | test_engine.py::test_execute_graph |
| CANCEL_DAG command | test_engine.py | test_engine.py::test_cancel_graph |
| DAG events | test_engine.py | test_engine.py::test_graph_events |
| **SDK Features** | | |
| RemoteChannel.send() | test_client.py | test_client.py::test_remote_node_execute |
| RemoteChannel.send_stream() | test_client.py | test_client.py::test_remote_node_execute_stream |
| **Pattern Features** | | |
| DevCoachLoop | test_patterns.py | test_patterns.py::test_dev_coach_with_nodes |
| DebateLoop | test_patterns.py | test_patterns.py::test_debate_with_nodes |

---

## 9. Migration Guide

### 9.1 Channel → Node Migration

**Before:**
```python
from nerve.core.channels import PTYChannel

channel = await PTYChannel.create("my-channel", command="bash")
result = await channel.send("ls", parser=none_parser)
await channel.close()
```

**After:**
```python
from nerve.core.nodes import PTYNode, ExecutionContext, NodeFactory

# Option 1: Using NodeFactory (recommended, matches current behavior)
factory = NodeFactory()
node = await factory.create_terminal("my-channel", command="bash")  # Already started
session = Session()
session.register(node)

result = await node.execute(ExecutionContext(session=session, input="ls"))
await node.stop()  # Or session.stop()

# Option 2: Direct instantiation (requires manual start)
node = PTYNode(id="my-channel", command="bash")
await node.start()  # Must call start() explicitly
session = Session()
session.register(node)

result = await node.execute(ExecutionContext(session=session, input="ls"))
await node.stop()
```

**Note:** `NodeFactory.create_terminal()` returns an already-started node, matching the current `PTYChannel.create()` behavior. Direct instantiation via `PTYNode(...)` creates an unstarted node that requires `await node.start()` or `await session.start()`.

### 9.2 DAG → Graph Migration

**Before:**
```python
from nerve.core.dag import DAG, Task

async def fetch(ctx):
    return await ctx["channel"].send("curl api.example.com")

async def process(ctx):
    return transform(ctx["fetch"])

dag = DAG()
dag.add_task(Task(id="fetch", execute=fetch))
dag.add_task(Task(id="process", execute=process, depends_on=["fetch"]))
results = await dag.run()
```

**After:**
```python
from nerve.core.nodes import Graph, FunctionNode, ExecutionContext

fetch_node = FunctionNode(id="fetch", fn=lambda ctx: ...)
process_node = FunctionNode(id="process", fn=lambda ctx: transform(ctx.upstream["fetch"]))

graph = Graph(id="pipeline")
graph.add_step(fetch_node, step_id="fetch", input="curl api.example.com")
graph.add_step(process_node, step_id="process", depends_on=["fetch"])

session = Session()
results = await graph.execute(ExecutionContext(session=session))
```

### 9.3 Nested Graphs

**New capability (no equivalent before):**
```python
setup_graph = Graph(id="setup")
setup_graph.add_step(bash_node, step_id="init", input="echo 'setup'")

main_graph = Graph(id="main")
main_graph.add_step(setup_graph, step_id="setup")  # Graph as step!
main_graph.add_step(work_node, step_id="work", depends_on=["setup"])

results = await main_graph.execute(context)
print(results["setup"])  # Nested graph results
print(results["work"])   # Main graph step result
```

### 9.4 SDK Migration

**Before:**
```python
from nerve.frontends.sdk import NerveClient

async with NerveClient.connect("/tmp/nerve.sock") as client:
    channel = await client.create_channel("my-claude", command="claude")
    response = await channel.send("Hello!", parser="claude")

    # Streaming
    async for chunk in channel.send_stream("Hello!"):
        print(chunk, end="")

    await channel.close()
```

**After:**
```python
from nerve.frontends.sdk import NerveClient

async with NerveClient.connect("/tmp/nerve.sock") as client:
    node = await client.create_node("my-claude", command="claude")
    response = await node.execute(input="Hello!", parser="claude")

    # Streaming
    async for chunk in node.execute_stream(input="Hello!"):
        print(chunk, end="")

    await node.stop()
```

**Note:** Old API (`create_channel`, `RemoteChannel.send`) continues to work with deprecation warnings.

### 9.5 Pattern Migration (DevCoachLoop)

Patterns require **no code changes**:

```python
# Current code - continues to work unchanged
config = DevCoachConfig(task="Implement feature X")
loop = DevCoachLoop(developer=dev_session, coach=coach_session, config=config)
result = await loop.run()
```

The Session class maintains backward compatibility, so patterns that use `Session.send()` work without modification.

### 9.6 Deprecation Timeline

| Phase | Duration | Action |
|-------|----------|--------|
| Phase 1-2 | Implementation | Old APIs work, emit deprecation warnings |
| Post-Phase 2 | 1 release cycle | Old APIs emit louder warnings |
| Phase 3 | Final | Old APIs removed |

---

## 10. Design Decisions

This section documents the resolved design decisions for this PRD.

### Decision D1: Unify Channel and Task into Node

**Decision:** Replace Channel and Task with a single Node protocol using a `persistent` flag.

```python
class Node(Protocol):
    id: str
    persistent: bool  # True = stateful (like Channel), False = stateless (like Task)
    async def execute(self, context: ExecutionContext) -> Any: ...
```

**Rationale:** Channel and Task share the same fundamental pattern: receive input, produce output. The only real difference is statefulness:
- Channels maintain state (terminal buffer, process connection)
- Tasks are stateless (compute something, return result)

A single abstraction with an explicit `persistent` flag reduces cognitive overhead. Developers learn one pattern instead of two. The flag makes the distinction explicit rather than implicit in the type name.

**Alternatives Considered:** Keep Channel and Task separate. Rejected because it requires learning two APIs that are 90% identical.

---

### Decision D2: Graph Implements Node

**Decision:** Graph implements the Node protocol, enabling graphs as steps in other graphs.

```python
class Graph(Node):
    persistent = False  # Graphs are stateless containers

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        # Execute steps in topological order
        return results
```

**Rationale:** This enables composable, modular workflows:
- Break large workflows into smaller, testable graphs
- Reuse common patterns (e.g., "setup" graph used in multiple workflows)
- Arbitrary nesting depth for complex orchestration

Without this, users would need separate mechanisms for "run a graph" vs "run a node", complicating the API.

**Alternatives Considered:** Keep Graph as a separate abstraction that doesn't implement Node. Rejected because it prevents composability and requires special handling.

---

### Decision D3: Dependencies in Step, not Node

**Decision:** Dependencies are defined per-step in the graph, not on the node itself.

```python
# Dependencies are in the Step, not the Node
graph.add_step(node_a, step_id="a")
graph.add_step(node_b, step_id="b", depends_on=["a"])  # b depends on a

# Same node can have different dependencies in different graphs
graph2.add_step(node_b, step_id="b", depends_on=["x", "y"])
```

**Rationale:** This enables node reusability. The same node can be used in multiple graphs with different dependency relationships. If dependencies were on the node, you'd need to create new node instances for each graph.

**Alternatives Considered:** Put dependencies on Node. Rejected because it prevents reusing nodes across graphs with different structures.

---

### Decision D4: Session Stores All Nodes

**Decision:** Session is the single registry for all nodes, including graphs.

```python
session.register(claude_node)    # Terminal node
session.register(worker_node)    # Task node
session.register(setup_graph)    # Graph (also a node)

# All accessible the same way
session.get("claude")
session.get("setup")
```

**Rationale:** Single registry simplifies the mental model. Users don't need to think about "where do I store graphs vs channels vs tasks?" Everything is a node, everything goes in the session.

**Alternatives Considered:** Separate registries for different node types. Rejected because it complicates the API and breaks the "everything is a node" abstraction.

---

### Decision D5: Support Both Direct and ID References

**Decision:** Graph steps can reference nodes directly or by ID.

```python
# Direct reference (early binding)
graph.add_step(claude_node, step_id="ask")

# ID reference (late binding)
graph.add_step(node_ref="claude", step_id="ask")  # Resolved from session at runtime
```

**Rationale:** Both patterns are useful:
- Direct references: Type-safe, IDE completion, fail-fast
- ID references: Dynamic graphs, serializable workflows, runtime flexibility

Supporting both gives users the right tool for each situation.

**Alternatives Considered:** Only support direct references. Rejected because it prevents dynamic graph construction and serialization.

---

### Decision D6: Statefulness is Explicit

**Decision:** Nodes declare statefulness via `persistent=True/False`.

```python
class PTYNode(Node):
    persistent = True   # Has terminal state, buffer, process

class ComputeNode(Node):
    persistent = False  # Stateless, can be called multiple times
```

**Rationale:** Explicit declaration sets clear expectations:
- Persistent nodes: Can't be rerun idempotently, have cleanup requirements
- Non-persistent nodes: Can be retried, parallelized, cached

This affects error handling, caching, and concurrency decisions. Making it explicit prevents subtle bugs.

**Alternatives Considered:** Infer statefulness from type. Rejected because it's implicit and error-prone.

---

### Decision D7: Keep Parser Unchanged

**Decision:** Parser abstraction remains per-operation, not per-node.

```python
# Parsers are still specified per-operation
response = await node.execute(context)  # Uses default parser
response = await node.send("hello", parser=ParserType.CLAUDE)  # Override

# Parser is NOT baked into the node definition
```

**Rationale:** The existing parser pattern works well:
- Proven in production
- Flexible (same node can use different parsers)
- No regression risk

Changing parsers would require migrating existing code for no clear benefit.

**Alternatives Considered:** Integrate parser into Node protocol. Rejected because it adds complexity and risks regression.

---

### Decision D8: Keep Backend Unchanged

**Decision:** Backend abstraction (PTYBackend, WezTermBackend) remains unchanged.

```python
# Backends are still low-level, separate from Node
class PTYNode(Node):
    def __init__(self):
        self.backend = PTYBackend(...)  # Composition, not integration
```

**Rationale:** Backends are low-level, stable abstractions:
- Handle OS-specific PTY details
- Handle WezTerm CLI integration
- Proven, well-tested code

Merging them into Node would complicate the abstraction and risk breaking stable code.

**Alternatives Considered:** Merge Backend into Node. Rejected because it mixes abstraction levels and risks regression.

---

### Decision D9: Parser Configuration

**Decision:** Default parser on node, override per-step.

```python
# Default parser set on node
claude_node = PTYNode(id="claude", default_parser=ParserType.CLAUDE)

# Override per-step if needed
graph.add_step(claude_node, step_id="ask", parser=ParserType.NONE)  # Override

# In ExecutionContext
context.parser  # Falls back to node default if not specified
```

**Rationale:** This maintains flexibility while reducing boilerplate. Most uses of a node will use the same parser, but overrides are possible for edge cases.

### Decision D10: Terminal Node API Surface

**Decision:** Keep Node protocol minimal. Terminal nodes have additional methods not part of the protocol.

```python
class Node(Protocol):
    """Minimal protocol - just execute()."""
    id: str
    persistent: bool
    async def execute(self, context: ExecutionContext) -> Any: ...

class TerminalNode(Node):
    """Terminal nodes have extra methods."""
    # Core Node interface
    async def execute(self, context) -> ParsedResponse: ...

    # Terminal-specific methods (NOT part of Node protocol)
    async def execute_stream(self, context) -> AsyncIterator[str]: ...
    async def write(self, data: str) -> None: ...
    async def read(self) -> str: ...
    def read_tail(self, lines: int = 50) -> str: ...
    def clear_buffer(self) -> None: ...
    async def interrupt(self) -> None: ...
```

**Rationale:** This keeps the Node protocol pure and simple while allowing terminal-specific functionality. Graph execution only uses `execute()`, but direct users of terminal nodes can access low-level methods.

### Decision D11: Graph Result Format

**Decision:** Nested dict for subgraphs. Deeply nested results (3+ levels) remain nested.

```python
# For nested graphs:
main_graph.add_step(setup_graph, step_id="setup")  # setup_graph has steps "init", "check"
main_graph.add_step(work_node, step_id="work")

results = await main_graph.execute(context)
# Returns:
# {
#     "setup": {
#         "init": <result>,
#         "check": <result>
#     },
#     "work": <result>
# }

# For 3+ levels:
# {
#     "outer": {
#         "middle": {
#             "inner": <result>
#         }
#     }
# }
```

**Rationale:** Nested format preserves graph structure and makes results easier to understand. The nesting level matches the graph structure, which is intuitive.

---

**Note:** Design decisions D12 (Trace Storage) and D13 (History vs Trace) are documented in [AGENT_CAPABILITIES.md](./AGENT_CAPABILITIES.md) as they relate to observability features.

---

**End of PRD**
