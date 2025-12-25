# PRD: Refactor graph.py into Modular Package

## Overview

**Type:** Refactoring
**Status:** Draft
**Target File:** `src/nerve/core/nodes/graph.py` (898 lines)
**Output:** `src/nerve/core/nodes/graph/` package

### Problem Statement

The `graph.py` file has grown to 898 lines and contains multiple cohesive components that would benefit from separation:
- `Step` dataclass (step configuration)
- `StepEvent` dataclass (streaming events)
- `GraphStep` class (fluent builder wrapper)
- `GraphStepList` class (parallel dependency list)
- `Graph` class (main orchestrator)

This refactoring will improve:
- **Maintainability**: Smaller, focused modules are easier to understand and modify
- **Testability**: Individual components can be tested in isolation
- **Discoverability**: Clear module names indicate component purposes

### Success Criteria

1. All existing tests pass without modification
2. All existing imports continue to work (via `__init__.py` re-exports)
3. No feature regression - identical runtime behavior
4. Smaller, focused modules with logical separation of concerns (dataclasses, builders, orchestrator)
5. Clean break - no backward compatibility shims

---

## Module Design

### Target Structure

```
src/nerve/core/nodes/graph/
├── __init__.py           # Re-exports all public symbols
├── step.py               # Step dataclass
├── events.py             # StepEvent dataclass
├── builder.py            # GraphStep, GraphStepList
└── graph.py              # Graph class
```

### Module Breakdown

#### 1. `graph/step.py` (~30 lines)

Contains the `Step` dataclass that defines step configuration.

**Exports:**
- `Step`

**Dependencies:**
- `typing` (TYPE_CHECKING, Any, Callable)
- `dataclasses` (dataclass, field)

**Code:**

```python
"""Step - configuration for a single step in a graph.

A step combines a node reference with execution configuration,
including input, dependencies, and error handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from nerve.core.nodes.base import Node
    from nerve.core.nodes.policies import ErrorPolicy
    from nerve.core.types import ParserType


@dataclass
class Step:
    """A step in a graph execution.

    Steps combine a node with execution configuration.
    Dependencies are on the step, not the node, allowing
    the same node to appear in multiple steps.

    Attributes:
        node: Direct reference to the node to execute.
        node_ref: ID-based reference (resolved from session at execution).
        input: Static input value for the step.
        input_fn: Dynamic input function that receives upstream results.
        depends_on: List of step IDs this step depends on.
        error_policy: How to handle errors in this step.
        parser: Parser to use for terminal nodes (overrides node default).

    Note:
        Either node or node_ref must be provided, not both.
        Either input or input_fn can be provided, not both.
    """

    node: Node | None = None
    node_ref: str | None = None
    input: Any = None
    input_fn: Callable[[dict[str, Any]], Any] | None = None
    depends_on: list[str] = field(default_factory=list)
    error_policy: ErrorPolicy | None = None
    parser: ParserType | None = None
```

---

#### 2. `graph/events.py` (~30 lines)

Contains the `StepEvent` dataclass for streaming execution events.

**Exports:**
- `StepEvent`

**Dependencies:**
- `typing` (Any, Literal)
- `dataclasses` (dataclass, field)
- `datetime` (datetime)

**Code:**

```python
"""StepEvent - events emitted during streaming graph execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class StepEvent:
    """Event emitted during streaming graph execution.

    Used by Graph.execute_stream() to provide real-time
    feedback on execution progress.

    Attributes:
        event_type: Type of event.
        step_id: The step this event relates to.
        node_id: The node being executed.
        data: Event-specific data (chunk content, result, or error).
        timestamp: When the event occurred.
    """

    event_type: Literal["step_start", "step_chunk", "step_complete", "step_error"]
    step_id: str
    node_id: str
    data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
```

---

#### 3. `graph/builder.py` (~130 lines)

Contains fluent builder classes for graph construction.

**Exports:**
- `GraphStep`
- `GraphStepList`

**Dependencies:**
- `typing` (TYPE_CHECKING, Any, Callable)

**TYPE_CHECKING Imports:**
- `Node` from `nerve.core.nodes.base`
- `Graph` from `nerve.core.nodes.graph.graph`
- `ErrorPolicy` from `nerve.core.nodes.policies`
- `ParserType` from `nerve.core.types`

**Code:**

```python
"""Fluent builder classes for graph construction.

GraphStep and GraphStepList enable intuitive graph building with the >> operator:

    A = graph.step("A", node, input="First")
    B = graph.step("B", node)
    C = graph.step("C", node)
    A >> B >> C  # B depends on A, C depends on B

    A >> [B, C]  # Both B and C depend on A
    [A, B] >> C  # C depends on both A and B
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from nerve.core.nodes.base import Node
    from nerve.core.nodes.graph.graph import Graph
    from nerve.core.nodes.policies import ErrorPolicy
    from nerve.core.types import ParserType


class GraphStep:
    """Wrapper for fluent graph building with >> operator.

    Example:
        >>> A = graph.step("A", node, input="First")
        >>> B = graph.step("B", node, input="Second")
        >>> C = graph.step("C", node, input="Third")
        >>> A >> B >> C  # B depends on A, C depends on B
    """

    def __init__(
        self,
        graph: Graph,
        step_id: str,
        node: Node | None = None,
        node_ref: str | None = None,
        input: Any = None,
        input_fn: Callable[[dict[str, Any]], Any] | None = None,
        depends_on: list[str] | None = None,
        error_policy: ErrorPolicy | None = None,
        parser: ParserType | None = None,
    ):
        self.graph = graph
        self.step_id = step_id
        self.node = node
        self.node_ref = node_ref
        self.input = input
        self.input_fn = input_fn
        self.error_policy = error_policy
        self.parser = parser
        self.depends_on: list[str] = depends_on or []
        self._registered = False

    def _ensure_registered(self) -> None:
        """Add this step to the graph if not already registered."""
        if not self._registered:
            if self.node:
                self.graph.add_step(
                    self.node,
                    self.step_id,
                    input=self.input,
                    input_fn=self.input_fn,
                    depends_on=self.depends_on,
                    error_policy=self.error_policy,
                    parser=self.parser,
                )
            elif self.node_ref:
                self.graph.add_step_ref(
                    self.node_ref,
                    self.step_id,
                    input=self.input,
                    input_fn=self.input_fn,
                    depends_on=self.depends_on,
                    error_policy=self.error_policy,
                    parser=self.parser,
                )
            else:
                raise ValueError(f"Step {self.step_id} has neither node nor node_ref")
            self._registered = True

    def __rshift__(
        self, other: GraphStep | list[GraphStep] | GraphStepList
    ) -> GraphStep | GraphStepList:
        """A >> B makes B depend on A.

        Supports:
            A >> B           # B depends on A
            A >> [B, C]      # Both B and C depend on A
        """
        if isinstance(other, (list, GraphStepList)):
            # A >> [B, C]
            for step in other:
                if isinstance(step, GraphStep):
                    step.depends_on.append(self.step_id)
                    self._ensure_registered()
                    step._ensure_registered()
            return GraphStepList(other)
        elif isinstance(other, GraphStep):
            # A >> B
            other.depends_on.append(self.step_id)
            self._ensure_registered()
            other._ensure_registered()
            return other
        else:
            raise TypeError(f"Cannot use >> with {type(other)}")

    def __repr__(self) -> str:
        return f"GraphStep(id={self.step_id!r}, depends_on={self.depends_on})"


class GraphStepList(list[GraphStep]):
    """List wrapper that supports >> operator for parallel dependencies.

    Example:
        >>> [A, B] >> C  # C depends on both A and B
    """

    def __rshift__(
        self, other: GraphStep | list[GraphStep] | GraphStepList
    ) -> GraphStep | GraphStepList:
        """[A, B] >> C makes C depend on all items in the list.

        Supports:
            [A, B] >> C        # C depends on both A and B
            [A, B] >> [C, D]   # C and D depend on both A and B
        """
        if isinstance(other, (list, GraphStepList)):
            # [A, B] >> [C, D]
            for downstream in other:
                if isinstance(downstream, GraphStep):
                    for upstream in self:
                        if isinstance(upstream, GraphStep):
                            downstream.depends_on.append(upstream.step_id)
                            upstream._ensure_registered()
                    downstream._ensure_registered()
            return GraphStepList(other)
        elif isinstance(other, GraphStep):
            # [A, B] >> C
            for upstream in self:
                if isinstance(upstream, GraphStep):
                    other.depends_on.append(upstream.step_id)
                    upstream._ensure_registered()
            other._ensure_registered()
            return other
        else:
            raise TypeError(f"Cannot use >> with {type(other)}")
```

---

#### 4. `graph/graph.py` (~688 lines)

Contains the main `Graph` class that implements the Node protocol.

**Exports:**
- `Graph`

**Dependencies:**
- `asyncio`
- `time`
- `collections.abc` (AsyncIterator, Callable)
- `dataclasses` (dataclass, field)
- `datetime` (datetime)
- `graphlib` (TopologicalSorter)
- `typing` (TYPE_CHECKING, Any, Literal)

**Internal Imports:**
- `Step` from `graph.step`
- `StepEvent` from `graph.events`
- `GraphStep` from `graph.builder`
- `Node`, `FunctionNode`, `NodeInfo`, `NodeState` from `nerve.core.nodes.base`
- `ErrorPolicy` from `nerve.core.nodes.policies`
- `StepTrace` from `nerve.core.nodes.trace`

**Key Implementation Notes:**

1. The `Graph` class remains the same, just imports from sibling modules
2. All internal `_resolve_node`, `_resolve_input`, `_execute_with_policy`, `_handle_error`, `_get_node_type` methods stay intact
3. Interrupt support (`_current_context`, `_current_node`, `_interrupt_lock`) unchanged

---

#### 5. `graph/__init__.py` (~30 lines)

Re-exports all public symbols to maintain API compatibility.

**Code:**

```python
"""Graph - orchestrator of nodes, implements Node protocol.

Graph is a composable workflow that:
- Contains steps (node + input + dependencies)
- Executes in topological order
- Supports nested graphs (Graph implements Node)
- Integrates error policies, budgets, cancellation, and tracing
"""

from nerve.core.nodes.graph.builder import GraphStep, GraphStepList
from nerve.core.nodes.graph.events import StepEvent
from nerve.core.nodes.graph.graph import Graph
from nerve.core.nodes.graph.step import Step

__all__ = [
    "Graph",
    "GraphStep",
    "GraphStepList",
    "Step",
    "StepEvent",
]
```

---

## Import Updates Required

### Files That Import from `graph.py`

The following files import from `nerve.core.nodes.graph`:

| File | Current Import | Action Required |
|------|----------------|-----------------|
| `src/nerve/core/nodes/__init__.py` | `from nerve.core.nodes.graph import Graph, GraphStep, GraphStepList, Step, StepEvent` | **None** - path unchanged |
| `src/nerve/server/engine.py` | `from nerve.core.nodes.graph import Graph` | **None** - path unchanged |
| `src/nerve/core/session/session.py` | `from nerve.core.nodes.graph import Graph` | **None** - path unchanged |
| `src/nerve/frontends/cli/repl/adapters.py` | `from nerve.core.nodes import Graph` | **None** - uses package import |
| `src/nerve/frontends/cli/repl/display.py` | `from nerve.core.nodes import Graph` | **None** - uses package import |
| `tests/core/nodes/test_graph.py` | `from nerve.core.nodes.graph import Graph, Step, StepEvent` | **None** - path unchanged |
| `tests/core/nodes/test_unified_api.py` | `from nerve.core.nodes.graph import Graph` | **None** - path unchanged |
| `tests/core/session/test_session_factory.py` | `from nerve.core.nodes.graph import Graph` | **None** - path unchanged |
| `tests/core/test_managers.py` | `from nerve.core.nodes.graph import Graph` | **None** - path unchanged |
| `examples/core_only/graph_execution.py` | `from nerve.core.nodes import ... Graph ...` | **None** - uses package import |
| `examples/bash_node_example.py` | `from nerve.core.nodes import ... Graph ...` | **None** - uses package import |

**All imports use `nerve.core.nodes.graph` or `nerve.core.nodes` as the import path, which maps to `graph/__init__.py` or `nodes/__init__.py` after conversion.**

---

## Implementation Plan

### Phase 1: Create Package Structure

1. Create `src/nerve/core/nodes/graph/` directory
2. Create `__init__.py` with docstring and empty `__all__`
3. Move components in order of dependency:
   - `step.py` (no internal deps)
   - `events.py` (no internal deps)
   - `builder.py` (imports Step via TYPE_CHECKING)
   - `graph.py` (imports Step, StepEvent, GraphStep)
4. Update `__init__.py` with re-exports

### Phase 2: Move Step Dataclass

1. Create `graph/step.py`
2. Copy `Step` dataclass with imports
3. Verify: `python -c "from nerve.core.nodes.graph.step import Step"`

### Phase 3: Move StepEvent Dataclass

1. Create `graph/events.py`
2. Copy `StepEvent` dataclass with imports
3. Verify: `python -c "from nerve.core.nodes.graph.events import StepEvent"`

### Phase 4: Move Builder Classes

1. Create `graph/builder.py`
2. Copy `GraphStep` and `GraphStepList` classes
3. Update TYPE_CHECKING imports for Graph
4. Verify: `python -c "from nerve.core.nodes.graph.builder import GraphStep, GraphStepList"`

### Phase 5: Move Graph Class

1. Create `graph/graph.py`
2. Copy `Graph` class
3. Update imports to use sibling modules
4. Verify: `python -c "from nerve.core.nodes.graph.graph import Graph"`

### Phase 6: Finalize Package Init

1. Update `graph/__init__.py` with all exports
2. Verify all symbols accessible:
   ```python
   from nerve.core.nodes.graph import Graph, GraphStep, GraphStepList, Step, StepEvent
   ```

### Phase 7: Delete Old File

1. Delete `src/nerve/core/nodes/graph.py`
2. Run `git rm src/nerve/core/nodes/graph.py`

### Phase 8: Verification

1. Run full test suite: `uv run pytest tests/`
2. Run specific graph tests: `uv run pytest tests/core/nodes/test_graph.py -v`
3. Run import verification:
   ```bash
   python -c "from nerve.core.nodes.graph import Graph, Step, StepEvent, GraphStep, GraphStepList; print('OK')"
   python -c "from nerve.core.nodes import Graph, Step, StepEvent; print('OK')"
   ```
4. Check for any broken imports: `uv run pytest --collect-only`

---

## Verification Checklist

### Pre-Implementation

- [ ] All tests pass: `uv run pytest tests/core/nodes/test_graph.py -v`
- [ ] Record test count for baseline

### Post-Implementation

- [ ] Directory structure matches design:
  ```
  ls src/nerve/core/nodes/graph/
  # Should show: __init__.py  builder.py  events.py  graph.py  step.py
  ```
- [ ] Old file deleted:
  ```
  ls src/nerve/core/nodes/graph.py
  # Should return: No such file or directory
  ```
- [ ] All tests pass (same count as baseline)
- [ ] Import verification passes:
  ```bash
  python -c "from nerve.core.nodes.graph import Graph, Step, StepEvent, GraphStep, GraphStepList"
  python -c "from nerve.core.nodes import Graph, Step, StepEvent"
  ```
- [ ] No backward compatibility shims exist
- [ ] Modules have logical separation (verify file count = 5):
  ```bash
  ls src/nerve/core/nodes/graph/*.py | wc -l
  # Should output: 5
  ```

---

## Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Circular imports | Medium | High | Use TYPE_CHECKING for cross-module type hints |
| Missing exports in `__init__.py` | Low | Medium | Explicit `__all__` list with verification |
| Import path changes break consumers | Low | High | Package `__init__.py` maintains same import path |
| Tests fail after refactoring | Low | High | Run tests after each phase |

---

## Out of Scope

1. **Functional changes** - This is a pure refactoring, no behavior changes
2. **Performance optimization** - Not a goal of this refactoring
3. **API changes** - All public APIs remain identical
4. **Test changes** - Tests should pass unchanged
5. **Documentation updates** - Docstrings are preserved as-is

---

## Definition of Done

1. `src/nerve/core/nodes/graph/` package exists with 5 files
2. `src/nerve/core/nodes/graph.py` (old single file) is deleted
3. All 525+ existing tests pass
4. All existing import paths work unchanged
5. No compatibility shims or re-export wrappers for old paths
6. Code review approved
