# PRD: Unified Node Creation API

**Status**: Draft v2.0
**Created**: 2025-12-25
**Updated**: 2025-12-25
**Author**: System
**Version**: 2.0

---

## Executive Summary

Nerve currently has an inconsistent API for creating nodes. Terminal nodes (PTYNode, WezTermNode, ClaudeWezTermNode) are created via `session.create_node()` factory with a string discriminator (`backend` parameter), while BashNode and FunctionNode use direct instantiation without session awareness. Graph uses yet another pattern.

This PRD proposes **unifying ALL node creation** to use direct instantiation with an explicit `session` parameter, enabling automatic registration while maintaining clarity and avoiding global state.

**This is a BREAKING CHANGE - clean break, no backward compatibility.**

---

## Table of Contents

1. [Background](#background)
2. [Prerequisites](#prerequisites)
3. [Goals and Non-Goals](#goals-and-non-goals)
4. [Proposed Solution](#proposed-solution)
5. [Detailed Design](#detailed-design)
6. [Breaking Changes](#breaking-changes)
7. [Implementation Plan](#implementation-plan)
8. [Testing Strategy](#testing-strategy)
9. [Success Criteria](#success-criteria)
10. [Risks and Mitigations](#risks-and-mitigations)
11. [Appendix](#appendix)

---

## Background

### Current State

Nerve has 6 primary node/graph types with 4 different creation patterns:

#### Pattern 1: Factory Method with String Discriminator (Terminal Nodes)
```python
# PTYNode, WezTermNode, ClaudeWezTermNode
claude = await session.create_node(
    "claude-1",
    command="claude",
    backend="claude-wezterm"  # String discriminator selects class
)
```

**Characteristics**:
- Async creation (uses `await`)
- Auto-registered in `session.nodes`
- Session manages lifecycle (history, cleanup)
- **Backend string discriminates which class to create** (non-obvious)

#### Pattern 2: Direct Instantiation - No Session (BashNode)
```python
# BashNode - NOT registered, NOT session-aware
bash = BashNode(id="bash", cwd=".", timeout=30.0)
```

**Characteristics**:
- Synchronous creation
- **NOT auto-registered**
- **No session lifecycle management**
- Must be manually tracked

#### Pattern 3: Factory Method (FunctionNode)
```python
# FunctionNode
func = session.create_function("func-1", fn=my_function)
```

**Characteristics**:
- Synchronous creation
- Auto-registered in `session.nodes`

#### Pattern 4: Factory Method (Graph)
```python
# Graph
graph = session.create_graph("pipeline")
# Internally: Graph(id="pipeline", session=session)
```

**Characteristics**:
- Takes session in constructor
- Auto-registers in `session.graphs`
- **Inconsistent with stated unification goal**

### Problems with Current State

1. **Inconsistent API**: 4 different patterns for 6 types
2. **String Discriminator**: `backend="claude-wezterm"` is non-obvious, not type-safe
3. **Unclear Registration**: BashNode isn't registered, leading to confusion
4. **Discoverability**: Unregistered nodes don't appear in `session.nodes`
5. **No Unified Documentation**: Can't document "how to create a node"
6. **Manual Tracking**: Users must manually track BashNode instances
7. **Graph Inconsistency**: Uses factory when direct instantiation is the goal

### Why This Matters

**Persistent vs Ephemeral Nodes**:
- **Persistent** (`persistent=True`): PTYNode, WezTermNode, ClaudeWezTermNode
  - Maintain state across executions
  - Need lifecycle management (`stop()` method)
  - Session calls `stop()` on cleanup

- **Ephemeral** (`persistent=False`): BashNode, FunctionNode, Graph
  - Stateless between executions
  - No `stop()` method
  - Session only tracks for discoverability

**However, registration provides value for ALL nodes**:
- Discoverability (`session.nodes`)
- Name uniqueness validation
- Graph integration (reference by ID)
- Serialization support

---

## Prerequisites

### Session Attributes Required

This PRD assumes the following attributes exist on `Session`:

```python
class Session:
    """Session manages nodes and graphs."""

    # Required attributes
    nodes: dict[str, Node]           # Node registry
    graphs: dict[str, Graph]         # Graph registry
    history_enabled: bool            # Whether to enable history logging
    history_base_dir: Path | None    # Base directory for history files
    name: str                        # Session name
    server_name: str | None          # Server name (for history paths)
```

### Verification Checklist

Before implementation, verify:

- [ ] `Session.nodes` is a `dict[str, Node]`
- [ ] `Session.graphs` is a `dict[str, Graph]`
- [ ] `Session.history_enabled` is a `bool`
- [ ] `Session.history_base_dir` exists and is `Path | None`
- [ ] `Session.name` is a `str`
- [ ] `Session.server_name` is `str | None`
- [ ] `Session.stop()` method exists and calls `stop()` on persistent nodes
- [ ] `validate_name(name, entity)` function exists in `nerve.core.validation`

---

## Goals and Non-Goals

### Goals

1. **Unified API**: ALL nodes and graphs created with the same pattern
2. **Explicit Session**: Clear ownership - no global state, no defaults
3. **Auto-Registration**: All entities register themselves on successful creation
4. **Type Safety**: No string discriminators - use concrete classes
5. **Clean Break**: Remove old APIs entirely, no backward compatibility

### Non-Goals

1. **Global Default Session**: We will NOT support creating nodes without a session
2. **Backward Compatibility**: No deprecation period, no old API support
3. **Convenience Aliases**: We will NOT add `session.bash()` shortcuts in this PRD
4. **Changing Persistent/Ephemeral Distinction**: This is a core architectural concept
5. **Data Migration Tools**: Users must migrate manually (documented)

---

## Proposed Solution

### Unified API Pattern

**ALL nodes and graphs** take an explicit `session` parameter and auto-register on successful creation:

```python
from nerve.core.session import Session
from nerve.core.nodes import BashNode, FunctionNode, PTYNode, WezTermNode, ClaudeWezTermNode, Graph

session = Session("my-session")

# Ephemeral nodes - synchronous direct instantiation
bash = BashNode(id="bash", session=session, cwd=".", timeout=30.0)
func = FunctionNode(id="func", session=session, fn=my_function)

# Persistent nodes - asynchronous creation via classmethod
pty = await PTYNode.create(id="pty", session=session, command="bash")
wez = await WezTermNode.create(id="wez", session=session, command="bash")
claude = await ClaudeWezTermNode.create(
    id="claude",
    session=session,
    command="claude --dangerously-skip-permissions"
)

# Graph - synchronous direct instantiation (UNIFIED!)
graph = Graph(id="pipeline", session=session)

# All entities are auto-registered
assert "bash" in session.nodes
assert "func" in session.nodes
assert "pty" in session.nodes
assert "wez" in session.nodes
assert "claude" in session.nodes
assert "pipeline" in session.graphs
```

### Key Design Decisions

#### 1. Explicit Session Parameter (Required, No Default)

**Decision**: `session` is a required parameter - no default, no global session.

**Rationale**:
- Explicit is better than implicit (Zen of Python)
- Avoids global state anti-pattern
- Clear ownership and lifecycle
- Better for testing (each test creates isolated session)
- No initialization order problems
- Thread-safe by design

#### 2. Auto-Registration on Successful Creation

**Decision**:
- **Ephemeral nodes**: Register in `__post_init__` after validation
- **Persistent nodes**: Register in `.create()` after async initialization
- **Graph**: Register in `__post_init__` after validation

**Rationale**:
- Simpler API - no explicit `session.register()` call
- Ensures all entities are discoverable
- Session validates uniqueness at creation time
- Registration happens AFTER successful initialization (not before)

#### 3. Synchronous vs Async Creation

**Decision**:
- **Ephemeral** (BashNode, FunctionNode): Sync `__init__` with session, register in `__post_init__`
- **Persistent** (PTYNode, WezTermNode, ClaudeWezTermNode): Async `.create()` classmethod, register after async init
- **Graph**: Sync `__init__` with session, register in `__post_init__`

**Rationale**:
- Ephemeral nodes have no async initialization - can use `__init__` safely
- Persistent nodes need async setup (spawn process, connect to terminal)
- **Cannot auto-register in `__init__` for async nodes** - would register before ready
- Classmethod `.create()` is standard Python pattern for async construction
- Registration happens ONLY after successful initialization

#### 4. Prevent Direct Terminal Node Instantiation

**Decision**: Persistent nodes raise error if `__init__` called directly.

**Example**:
```python
# THIS WILL FAIL - cannot call __init__ directly
node = PTYNode(id="test", session=session, ...)
# TypeError: Cannot instantiate PTYNode directly. Use: await PTYNode.create(...)

# THIS IS CORRECT
node = await PTYNode.create(id="test", session=session, ...)
```

**Rationale**:
- Prevents nodes in broken state (not async initialized)
- Makes async requirement explicit
- Matches Python best practices (e.g., `asyncio.create_task` vs `Task()`)

#### 5. Remove ALL Old APIs (Clean Break)

**Decision**: Remove factory methods entirely - no backward compatibility.

**Removed APIs**:
- `session.create_node()` - REMOVED
- `session.create_function()` - REMOVED
- `session.create_graph()` - REMOVED
- `BackendType` enum - REMOVED

**Rationale**:
- Clean break preferred by stakeholders
- Simpler codebase (no dual API support)
- Forces migration to consistent pattern
- Removes confusion

---

## Detailed Design

### 1. BashNode (Ephemeral - Synchronous)

#### Complete Specification

```python
from __future__ import annotations
from typing import TYPE_CHECKING, Any
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from nerve.core.session.session import Session

@dataclass
class BashNode:
    """Ephemeral node that runs bash commands and returns JSON results.

    BashNode is stateless - each execute() spawns a fresh subprocess.
    No state is maintained between executions.

    Args:
        id: Unique identifier for this node.
        session: Session to register this node with.
        cwd: Working directory for command execution.
        env: Environment variables for command execution.
        timeout: Default timeout for commands (seconds).

    Example:
        >>> session = Session("my-session")
        >>> bash = BashNode(id="bash", session=session, cwd="/tmp")
        >>> ctx = ExecutionContext(session=session, input="ls -la")
        >>> result = await bash.execute(ctx)
        >>> print(result["stdout"])
    """

    # Required fields (no defaults)
    id: str
    session: Session

    # Optional fields (with defaults)
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout: float = 30.0

    # Internal fields (not in __init__)
    persistent: bool = field(default=False, init=False)
    metadata: dict[str, Any] = field(default_factory=dict)
    _current_proc: asyncio.subprocess.Process | None = field(
        default=None, init=False, repr=False
    )
    _proc_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Validate and register with session."""
        from nerve.core.validation import validate_name

        # Validate node ID
        validate_name(self.id, "node")

        # Check for duplicates
        if self.id in self.session.nodes:
            raise ValueError(
                f"Node '{self.id}' already exists in session '{self.session.name}'"
            )

        # Auto-register with session
        self.session.nodes[self.id] = self

    # ... rest of BashNode implementation (execute, interrupt, etc.)
```

**Key Points**:
- `session` parameter comes immediately after `id` (both required)
- Registration happens in `__post_init__` after validation
- Raises `ValueError` if node ID already exists
- Dataclass field ordering: required fields first, then optional fields

### 2. FunctionNode (Ephemeral - Synchronous)

#### Complete Specification

```python
from __future__ import annotations
from typing import TYPE_CHECKING, Any, Callable
from dataclasses import dataclass, field
import asyncio

if TYPE_CHECKING:
    from nerve.core.session.session import Session
    from nerve.core.nodes.context import ExecutionContext

@dataclass
class FunctionNode:
    """Wraps a sync or async callable as an ephemeral node.

    Args:
        id: Unique identifier for this node.
        session: Session to register this node with.
        fn: Sync or async callable accepting ExecutionContext.

    Example:
        >>> session = Session("my-session")
        >>> def transform(ctx: ExecutionContext) -> str:
        ...     return ctx.input.upper()
        >>> node = FunctionNode(id="transform", session=session, fn=transform)
    """

    # Required fields
    id: str
    session: Session
    fn: Callable[[ExecutionContext], Any]

    # Internal fields
    persistent: bool = field(default=False, init=False)
    metadata: dict[str, Any] = field(default_factory=dict)
    _current_task: asyncio.Task[Any] | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Validate and register with session."""
        from nerve.core.validation import validate_name

        validate_name(self.id, "node")

        if self.id in self.session.nodes:
            raise ValueError(
                f"Node '{self.id}' already exists in session '{self.session.name}'"
            )

        # Auto-register
        self.session.nodes[self.id] = self

    # ... rest of FunctionNode implementation
```

### 3. PTYNode (Persistent - Asynchronous)

#### Complete Specification

```python
from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from nerve.core.session.session import Session
    from nerve.core.types import ParserType
    from nerve.core.nodes.history import HistoryWriter

@dataclass
class PTYNode:
    """Persistent PTY-based terminal node.

    IMPORTANT: Cannot be instantiated directly. Use PTYNode.create() instead.

    Example:
        >>> session = Session("my-session")
        >>> node = await PTYNode.create(
        ...     id="shell",
        ...     session=session,
        ...     command="bash",
        ...     cwd="/tmp"
        ... )
    """

    # Required fields
    id: str
    session: Session

    # Optional fields
    command: str | list[str] | None = None
    cwd: str | None = None
    ready_timeout: float = 60.0
    response_timeout: float = 1800.0

    # Internal fields (set during .create())
    persistent: bool = field(default=True, init=False)
    state: NodeState = field(default=NodeState.CREATED, init=False)
    metadata: dict[str, Any] = field(default_factory=dict)
    _backend: PTYBackend | None = field(default=None, init=False, repr=False)
    _default_parser: ParserType = field(default=ParserType.NONE, init=False)
    _history_writer: HistoryWriter | None = field(default=None, init=False, repr=False)
    _last_input: str = field(default="", init=False)

    def __post_init__(self) -> None:
        """Prevent direct instantiation."""
        # Check if we're being called from .create() by checking if _backend is set
        # If _backend is None and we're not in .create(), this is direct instantiation
        import inspect

        # Walk up the call stack to see if we're being called from .create()
        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_name = frame.f_back.f_code.co_name
            if caller_name != "create":
                raise TypeError(
                    f"Cannot instantiate {self.__class__.__name__} directly. "
                    f"Use: await {self.__class__.__name__}.create(id, session, ...)"
                )

    @classmethod
    async def create(
        cls,
        id: str,
        session: Session,
        command: str | list[str] | None = None,
        cwd: str | None = None,
        history: bool | None = None,
        ready_timeout: float = 60.0,
        response_timeout: float = 1800.0,
        default_parser: ParserType | None = None,
    ) -> PTYNode:
        """Create a new PTY node and register with session.

        This is the ONLY way to create a PTYNode. Direct instantiation via
        __init__ will raise TypeError.

        Args:
            id: Unique identifier for the node.
            session: Session to register this node with.
            command: Command to run (e.g., "bash", ["bash", "-i"]).
            cwd: Working directory.
            history: Enable history logging (default: session.history_enabled).
            ready_timeout: Timeout for terminal to become ready.
            response_timeout: Default timeout for responses.
            default_parser: Default parser for execute() calls.

        Returns:
            A ready PTYNode, registered in the session.

        Raises:
            ValueError: If node_id already exists or is invalid.

        Example:
            >>> session = Session("my-session")
            >>> node = await PTYNode.create(
            ...     id="shell",
            ...     session=session,
            ...     command="bash"
            ... )
            >>> assert "shell" in session.nodes
        """
        from nerve.core.validation import validate_name
        from nerve.core.nodes.history import HistoryWriter, HistoryError
        from nerve.core.pty.pty_backend import PTYBackend

        # Validate
        validate_name(id, "node")
        if id in session.nodes:
            raise ValueError(
                f"Node '{id}' already exists in session '{session.name}'"
            )

        # Setup history
        use_history = history if history is not None else session.history_enabled
        history_writer = None
        if use_history:
            try:
                history_writer = HistoryWriter.create(
                    node_id=id,
                    server_name=session.server_name,
                    session_name=session.name,
                    base_dir=session.history_base_dir,
                    enabled=True,
                )
            except (HistoryError, ValueError) as e:
                logger.warning(f"Failed to create history writer for {id}: {e}")

        # Create instance (NOT registered yet - not ready!)
        node = cls(
            id=id,
            session=session,
            command=command,
            cwd=cwd,
            ready_timeout=ready_timeout,
            response_timeout=response_timeout,
        )

        # Set internal fields
        node._default_parser = default_parser or ParserType.NONE
        node._history_writer = history_writer

        try:
            # Async initialization - spawn PTY process
            node._backend = await PTYBackend.create(
                command=command,
                cwd=cwd,
                ready_timeout=ready_timeout,
            )
            node.state = NodeState.READY

            # NOW register (only after successful async init)
            session.nodes[id] = node

            return node

        except Exception:
            # Cleanup on failure
            if history_writer:
                history_writer.close()
            raise

    # ... rest of PTYNode implementation (execute, stop, etc.)
```

**Key Points**:
- **`__post_init__` prevents direct instantiation** - raises `TypeError`
- **`.create()` is the ONLY way** to create a PTYNode
- **Registration happens AFTER async initialization** - not before
- Node is only added to `session.nodes` after backend is ready
- If async init fails, node is NOT registered (cleanup happens)

### 4. WezTermNode and ClaudeWezTermNode (Persistent - Asynchronous)

**Same pattern as PTYNode**:
- Cannot be instantiated via `__init__` directly
- Must use `.create()` classmethod
- Registration happens after async initialization
- Full specification similar to PTYNode

```python
@dataclass
class WezTermNode:
    """Persistent WezTerm-based terminal node."""
    # Same structure as PTYNode

    @classmethod
    async def create(cls, id: str, session: Session, ...) -> WezTermNode:
        """Create WezTerm node."""
        # Same pattern as PTYNode.create()

@dataclass
class ClaudeWezTermNode:
    """Persistent WezTerm node optimized for Claude CLI."""
    # Same structure as PTYNode

    @classmethod
    async def create(cls, id: str, session: Session, ...) -> ClaudeWezTermNode:
        """Create Claude WezTerm node."""
        # Validates command contains "claude"
        # Same pattern as PTYNode.create()
```

### 5. Graph (Ephemeral - Synchronous) - UNIFIED!

#### Complete Specification

```python
from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from nerve.core.session.session import Session

@dataclass
class Graph:
    """Directed graph of steps that implements Node protocol.

    Args:
        id: Unique identifier for this graph.
        session: Session to register this graph with.
        max_parallel: Maximum concurrent step executions.

    Example:
        >>> session = Session("my-session")
        >>> graph = Graph(id="pipeline", session=session)
        >>> graph.add_step(node, step_id="step1", input="data")
    """

    # Required fields
    id: str
    session: Session

    # Optional fields
    max_parallel: int = 1

    # Internal fields
    persistent: bool = field(default=False, init=False)
    _steps: dict[str, Step] = field(default_factory=dict, init=False)
    _interrupt_requested: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        """Validate and register with session."""
        if not self.id or not self.id.strip():
            raise ValueError("graph_id cannot be empty")

        if self.id in self.session.graphs:
            raise ValueError(
                f"Graph '{self.id}' already exists in session '{self.session.name}'"
            )

        # Auto-register with session.graphs (not session.nodes!)
        self.session.graphs[self.id] = self

    # ... rest of Graph implementation
```

**Key Points**:
- **UNIFIED with other ephemeral nodes** - direct instantiation
- Registers in `session.graphs` (not `session.nodes`)
- Same pattern as BashNode and FunctionNode
- **Removes `session.create_graph()` inconsistency**

---

## Breaking Changes

### API Changes (All Breaking)

#### 1. BashNode Signature Change

**Before**:
```python
bash = BashNode(id="bash", cwd=".")
# NOT registered with session
```

**After**:
```python
bash = BashNode(id="bash", session=session, cwd=".")
# Auto-registered in session.nodes
```

**Migration**:
- Add `session=session` parameter to ALL BashNode instantiations
- Use keyword arguments to avoid positional argument issues

#### 2. FunctionNode Creation Change

**Before**:
```python
func = session.create_function("func", fn=my_function)
```

**After**:
```python
func = FunctionNode(id="func", session=session, fn=my_function)
```

**Migration**:
- Replace all `session.create_function()` calls
- Import `FunctionNode` from `nerve.core.nodes`

#### 3. Terminal Node Creation Change

**Before**:
```python
claude = await session.create_node(
    "claude",
    command="claude",
    backend="claude-wezterm"  # String discriminator
)
```

**After**:
```python
from nerve.core.nodes import ClaudeWezTermNode

claude = await ClaudeWezTermNode.create(
    id="claude",
    session=session,
    command="claude --dangerously-skip-permissions"
)
```

**Migration**:
- Import concrete node classes
- Replace `session.create_node()` with class `.create()` method
- Remove `backend` parameter
- Use explicit class based on desired type:
  - `backend="pty"` → `PTYNode.create()`
  - `backend="wezterm"` → `WezTermNode.create()`
  - `backend="claude-wezterm"` → `ClaudeWezTermNode.create()`

#### 4. Graph Creation Change

**Before**:
```python
graph = session.create_graph("pipeline")
```

**After**:
```python
from nerve.core.nodes import Graph

graph = Graph(id="pipeline", session=session)
```

**Migration**:
- Replace all `session.create_graph()` calls
- Import `Graph` from `nerve.core.nodes`

### Removed APIs

The following APIs are **REMOVED entirely** (no deprecation):

```python
# REMOVED - no longer exists
session.create_node(...)
session.create_function(...)
session.create_graph(...)

# REMOVED - no longer exists
from nerve.core.session import BackendType
```

### Serialization Breaking Changes

#### Problem: Old Serialized Sessions

Old serialized sessions stored `backend` field:

```json
{
  "nodes": {
    "claude": {
      "type": "terminal",
      "backend": "claude-wezterm",
      "command": "claude"
    }
  }
}
```

#### Solution: Manual Migration Required

**We do NOT provide automatic migration.** Users must:

1. **Delete old serialized sessions** - start fresh
2. **Update config files manually** - change backend to explicit class
3. **Re-create sessions** - use new API

**Config file migration example**:

```yaml
# OLD (no longer works)
nodes:
  - id: claude
    backend: claude-wezterm
    command: claude

# NEW (required)
nodes:
  - id: claude
    type: ClaudeWezTermNode
    command: claude
```

### CLI Breaking Changes

#### Problem: `nerve server node create` uses `--backend`

Old CLI:
```bash
nerve server node create claude --backend claude-wezterm --command claude
```

#### Solution: Use `--type` with Class Name

New CLI:
```bash
nerve server node create claude --type ClaudeWezTermNode --command claude
```

**CLI Changes Required**:
- Replace `--backend` flag with `--type`
- Accept class name strings: `PTYNode`, `WezTermNode`, `ClaudeWezTermNode`
- Map to concrete classes internally

---

## Implementation Plan

### Phase 1: Core Changes (Nodes and Graph)

**Dependencies**: Must complete in order listed.

**Step 1: Update Node Classes**
- [ ] Add `session` parameter to BashNode `__init__`
- [ ] Add `session` parameter to FunctionNode `__init__`
- [ ] Add `__post_init__` registration logic to BashNode
- [ ] Add `__post_init__` registration logic to FunctionNode
- [ ] Add `__post_init__` prevention to PTYNode, WezTermNode, ClaudeWezTermNode
- [ ] Add public `.create()` methods to PTYNode, WezTermNode, ClaudeWezTermNode
- [ ] Update Graph to register in `__post_init__` (already has session parameter)

**Step 2: Write Tests for New API FIRST**
- [ ] Write tests for BashNode with session parameter
- [ ] Write tests for FunctionNode with session parameter
- [ ] Write tests for PTYNode.create() with session parameter
- [ ] Write tests for WezTermNode.create() with session parameter
- [ ] Write tests for ClaudeWezTermNode.create() with session parameter
- [ ] Write tests for Graph with session parameter
- [ ] Write tests verifying auto-registration works
- [ ] Write tests verifying direct PTYNode() instantiation fails
- [ ] Run tests - VERIFY THEY PASS

**Step 3: Update Internal Code to Use New API**
- [ ] Update all internal code using BashNode
- [ ] Update all internal code using FunctionNode
- [ ] Update all internal code using terminal nodes
- [ ] Update all internal code using Graph
- [ ] Run all tests - VERIFY NO REGRESSIONS

**Step 4: Remove Old APIs**
- [ ] Remove `session.create_node()` method
- [ ] Remove `session.create_function()` method
- [ ] Remove `session.create_graph()` method
- [ ] Remove `BackendType` enum
- [ ] Remove `._create()` internal methods from terminal nodes
- [ ] Run tests - VERIFY ALL PASS

### Phase 2: Examples and Documentation

**Step 5: Update Examples**
- [ ] Update `examples/bash_node_example.py`
- [ ] Update `examples/core_only/graph_execution.py`
- [ ] Update all other example files (~8 files)
- [ ] Run examples - VERIFY THEY WORK

**Step 6: Update Tests**
- [ ] Update `tests/core/nodes/test_bash.py`
- [ ] Update `tests/core/nodes/test_base.py`
- [ ] Update `tests/core/nodes/test_terminal.py`
- [ ] Update `tests/core/nodes/test_graph.py`
- [ ] Update `tests/core/session/test_session_factory.py`
- [ ] Update all other test files (~15 files)
- [ ] Run full test suite - VERIFY ALL PASS

**Step 7: Update Documentation**
- [ ] Write migration guide: `docs/migration/unified-node-api.md`
- [ ] Update API docs: `docs/api/nodes.md`
- [ ] Update README examples
- [ ] Update quickstart guide

### Phase 3: CLI and Frontends

**Step 8: Update CLI**
- [ ] Change `nerve server node create --backend` to `--type`
- [ ] Update CLI help text
- [ ] Update CLI examples
- [ ] Test CLI commands

**Step 9: Update REPL**
- [ ] Update REPL examples to use new API
- [ ] Update REPL help text
- [ ] Test REPL commands

### Phase 4: Verification

**Step 10: Final Verification**
- [ ] Run full test suite
- [ ] Run all examples
- [ ] Test CLI manually
- [ ] Test REPL manually
- [ ] Verify no old API references remain: `grep -r "create_node\|create_function\|create_graph\|BackendType" src/`
- [ ] Update CHANGELOG.md with breaking changes

**Estimated Effort**: 6-8 days

---

## Testing Strategy

### Unit Tests

#### Test Auto-Registration
```python
def test_bash_node_auto_registers():
    session = Session("test")
    bash = BashNode(id="bash", session=session)
    assert "bash" in session.nodes
    assert session.nodes["bash"] is bash

def test_function_node_auto_registers():
    session = Session("test")
    func = FunctionNode(id="f", session=session, fn=lambda ctx: ctx.input)
    assert "f" in session.nodes

async def test_pty_node_auto_registers():
    session = Session("test")
    pty = await PTYNode.create(id="pty", session=session, command="bash")
    assert "pty" in session.nodes

def test_graph_auto_registers():
    session = Session("test")
    graph = Graph(id="g", session=session)
    assert "g" in session.graphs  # Note: graphs, not nodes!
```

#### Test Duplicate Prevention
```python
def test_bash_node_duplicate_raises():
    session = Session("test")
    BashNode(id="bash", session=session)

    with pytest.raises(ValueError, match="already exists"):
        BashNode(id="bash", session=session)

async def test_pty_node_duplicate_raises():
    session = Session("test")
    await PTYNode.create(id="pty", session=session, command="bash")

    with pytest.raises(ValueError, match="already exists"):
        await PTYNode.create(id="pty", session=session, command="bash")
```

#### Test Direct Instantiation Prevention
```python
def test_pty_node_direct_init_raises():
    session = Session("test")

    with pytest.raises(TypeError, match="Cannot instantiate PTYNode directly"):
        PTYNode(id="pty", session=session, command="bash")

def test_wezterm_node_direct_init_raises():
    session = Session("test")

    with pytest.raises(TypeError, match="Cannot instantiate WezTermNode directly"):
        WezTermNode(id="wez", session=session)
```

#### Test Cross-Session Nodes
```python
def test_same_id_different_sessions_allowed():
    session1 = Session("s1")
    session2 = Session("s2")

    bash1 = BashNode(id="bash", session=session1)
    bash2 = BashNode(id="bash", session=session2)

    assert bash1 in session1.nodes.values()
    assert bash2 in session2.nodes.values()
    assert bash1 is not bash2
```

#### Test Session Parameter Required
```python
def test_bash_node_requires_session():
    # This should fail at type-check time, but test runtime too
    with pytest.raises(TypeError):
        BashNode(id="bash")  # Missing session parameter
```

### Integration Tests

#### Test Graph Integration
```python
async def test_graph_uses_registered_nodes():
    session = Session("test")
    bash = BashNode(id="bash", session=session)
    graph = Graph(id="g", session=session)

    # Can reference by ID since it's registered
    graph.add_step_ref("step1", node_ref="bash", input="echo hello")

    results = await graph.execute(ExecutionContext(session=session))
    assert results["step1"]["success"] is True
```

#### Test Lifecycle Management
```python
async def test_persistent_nodes_cleaned_up():
    session = Session("test")

    # Create mix of persistent and ephemeral
    bash = BashNode(id="bash", session=session)  # ephemeral
    pty = await PTYNode.create(id="pty", session=session, command="bash")  # persistent

    # Stop session
    await session.stop()

    # Persistent node should be stopped
    assert pty.state == NodeState.STOPPED
    # Ephemeral node has no stop() method - just removed from registry
```

---

## Success Criteria

### Must Have

- [ ] All nodes created with explicit `session` parameter
- [ ] All nodes auto-register on creation
- [ ] Terminal nodes cannot be instantiated via `__init__` directly
- [ ] Terminal nodes only register after successful async initialization
- [ ] Graph uses same pattern as other ephemeral nodes
- [ ] Old factory methods removed entirely
- [ ] `BackendType` enum removed
- [ ] No circular import issues
- [ ] All tests pass
- [ ] All examples updated and working

### Should Have

- [ ] Migration guide published
- [ ] API documentation updated
- [ ] CLI updated to use `--type` instead of `--backend`
- [ ] Type hints work correctly (mypy passes)
- [ ] Clear error messages for common mistakes

### Nice to Have

- [ ] IDE auto-completion works well
- [ ] Helpful error message when user tries `PTYNode()` directly
- [ ] REPL auto-completion updated

---

## Risks and Mitigations

### Risk 1: Breaking ALL User Code

**Impact**: Every user must update their code.

**Mitigation**:
- Provide comprehensive migration guide
- Show before/after examples for every pattern
- Document all breaking changes clearly
- Provide grep patterns to find old API usage
- Consider providing codemod script (future)

### Risk 2: Circular Import Issues

**Impact**: Adding `session` parameter could cause circular imports.

**Mitigation**:
- Use `TYPE_CHECKING` pattern (already proven in codebase)
- Import `Session` only for type hints
- Runtime imports in methods (`__post_init__`, `.create()`)
- Verify no import cycles with: `pytest --import-check`

### Risk 3: Users Call `PTYNode()` Directly

**Impact**: Creates broken nodes (not async initialized).

**Mitigation**:
- Raise `TypeError` in `__post_init__` with clear message
- Document that `.create()` is required
- Add type stubs showing `__init__` as private
- Show examples of what NOT to do

### Risk 4: Lost Serialized Sessions

**Impact**: Users lose saved session state.

**Mitigation**:
- Document clearly: "Serialized sessions not compatible"
- Provide example of new serialization format
- Recommend: "Recreate sessions with new API"
- Consider: Provide manual migration instructions (not automated)

### Risk 5: Forgotten Old API References

**Impact**: Internal code still using old patterns.

**Mitigation**:
- Grep entire codebase before removing old APIs
- Use IDE "find references" feature
- Have CI fail if old API imports detected
- Add lint rule (future)

---

## Appendix

### A. Complete API Comparison

| Entity | Old API | New API | Change Type |
|--------|---------|---------|-------------|
| BashNode | `BashNode(id="b")` | `BashNode(id="b", session=s)` | BREAKING - signature change |
| FunctionNode | `session.create_function("f", fn)` | `FunctionNode(id="f", session=s, fn=fn)` | BREAKING - removed factory |
| PTYNode | `await session.create_node("p", backend="pty")` | `await PTYNode.create(id="p", session=s)` | BREAKING - removed factory |
| WezTermNode | `await session.create_node("w", backend="wezterm")` | `await WezTermNode.create(id="w", session=s)` | BREAKING - removed factory |
| ClaudeWezTermNode | `await session.create_node("c", backend="claude-wezterm")` | `await ClaudeWezTermNode.create(id="c", session=s)` | BREAKING - removed factory |
| Graph | `session.create_graph("g")` | `Graph(id="g", session=s)` | BREAKING - removed factory |

### B. Migration Examples

#### Example 1: Simple BashNode

**Before**:
```python
from nerve.core.nodes import BashNode, ExecutionContext

bash = BashNode(id="bash", cwd="/tmp")
ctx = ExecutionContext(session=session, input="ls")
result = await bash.execute(ctx)
```

**After**:
```python
from nerve.core.nodes import BashNode, ExecutionContext

bash = BashNode(id="bash", session=session, cwd="/tmp")  # Added session
ctx = ExecutionContext(session=session, input="ls")
result = await bash.execute(ctx)
```

#### Example 2: Terminal Nodes with Backend

**Before**:
```python
# PTY node
pty = await session.create_node("pty", command="bash", backend="pty")

# WezTerm node
wez = await session.create_node("wez", command="bash", backend="wezterm")

# Claude node
claude = await session.create_node(
    "claude",
    command="claude",
    backend="claude-wezterm"
)
```

**After**:
```python
from nerve.core.nodes import PTYNode, WezTermNode, ClaudeWezTermNode

# PTY node - explicit class
pty = await PTYNode.create(id="pty", session=session, command="bash")

# WezTerm node - explicit class
wez = await WezTermNode.create(id="wez", session=session, command="bash")

# Claude node - explicit class
claude = await ClaudeWezTermNode.create(
    id="claude",
    session=session,
    command="claude --dangerously-skip-permissions"
)
```

#### Example 3: Full Pipeline

**Before**:
```python
from nerve.core.session import Session
from nerve.core.nodes import BashNode, ExecutionContext

session = Session("my-session")

# BashNode - not registered
bash = BashNode(id="bash")

# FunctionNode - factory
func = session.create_function("func", fn=lambda ctx: ctx.input.upper())

# Terminal node - factory with backend
claude = await session.create_node("claude", command="claude", backend="claude-wezterm")

# Graph - factory
graph = session.create_graph("pipeline")
graph.add_step(bash, "step1", input="echo hello")
```

**After**:
```python
from nerve.core.session import Session
from nerve.core.nodes import (
    BashNode,
    FunctionNode,
    ClaudeWezTermNode,
    Graph,
    ExecutionContext
)

session = Session("my-session")

# BashNode - direct with session, auto-registered
bash = BashNode(id="bash", session=session)

# FunctionNode - direct with session, auto-registered
func = FunctionNode(id="func", session=session, fn=lambda ctx: ctx.input.upper())

# Terminal node - explicit class, auto-registered
claude = await ClaudeWezTermNode.create(
    id="claude",
    session=session,
    command="claude --dangerously-skip-permissions"
)

# Graph - direct with session, auto-registered
graph = Graph(id="pipeline", session=session)
graph.add_step(bash, "step1", input="echo hello")
```

#### Example 4: Common Mistakes

**Mistake 1: Forgetting session parameter**
```python
# WRONG - TypeError: missing required argument 'session'
bash = BashNode(id="bash", cwd="/tmp")

# CORRECT
bash = BashNode(id="bash", session=session, cwd="/tmp")
```

**Mistake 2: Direct terminal node instantiation**
```python
# WRONG - TypeError: Cannot instantiate PTYNode directly
node = PTYNode(id="pty", session=session, command="bash")

# CORRECT
node = await PTYNode.create(id="pty", session=session, command="bash")
```

**Mistake 3: Using old factory methods**
```python
# WRONG - AttributeError: 'Session' object has no attribute 'create_node'
claude = await session.create_node("claude", backend="claude-wezterm")

# CORRECT
from nerve.core.nodes import ClaudeWezTermNode
claude = await ClaudeWezTermNode.create(id="claude", session=session)
```

**Mistake 4: Using backend parameter**
```python
# WRONG - TypeError: create() got unexpected keyword argument 'backend'
node = await PTYNode.create(id="p", session=session, backend="pty")

# CORRECT - backend is gone, use concrete class instead
node = await PTYNode.create(id="p", session=session)
```

### C. Grep Patterns for Finding Old API

Use these to find code that needs updating:

```bash
# Find old factory methods
grep -r "session\.create_node" src/ examples/ tests/
grep -r "session\.create_function" src/ examples/ tests/
grep -r "session\.create_graph" src/ examples/ tests/

# Find backend parameter usage
grep -r "backend=" src/ examples/ tests/
grep -r "BackendType" src/ examples/ tests/

# Find BashNode without session parameter (may have false positives)
grep -r "BashNode(id=" src/ examples/ tests/
```

### D. Type Checking Considerations

**MyPy Configuration**:
```ini
# mypy.ini
[mypy]
warn_unused_configs = True
warn_redundant_casts = True
warn_unused_ignores = True
strict_equality = True
check_untyped_defs = True

# Allow TYPE_CHECKING imports
[mypy-nerve.core.nodes.*]
allow_untyped_defs = False
```

**Example Type Stub** (future enhancement):
```python
# nerve/core/nodes/terminal.pyi
class PTYNode:
    def __init__(self, *args, **kwargs) -> NoReturn:
        """Cannot instantiate directly. Use PTYNode.create()."""
        ...

    @classmethod
    async def create(
        cls,
        id: str,
        session: Session,
        command: str | list[str] | None = None,
        ...
    ) -> PTYNode: ...
```

---

## Approval Checklist

Before implementation:

- [ ] Technical Lead Review
- [ ] API Design Review
- [ ] Prerequisites verified (Session attributes exist)
- [ ] Breaking changes acknowledged
- [ ] Migration plan approved
- [ ] Testing strategy approved
- [ ] Documentation plan approved

---

## Changelog

- **2025-12-25 v1.0**: Initial draft
- **2025-12-25 v2.0**:
  - Removed all backward compatibility (clean break)
  - Fixed terminal node auto-registration (register after async init only)
  - Unified Graph API (removed factory method)
  - Added prerequisites section
  - Added complete dataclass specifications
  - Fixed success criteria notation
  - Addressed BackendType removal impact
  - Clarified implementation phase ordering
  - Added prevention of direct terminal node instantiation
