# Node Fork Feature - Implementation Plan

## Overview

Add the ability to fork nodes, creating a new node with copied state. This enables:
- Exploring alternative conversation paths with LLM nodes
- A/B testing different prompts from the same context
- Branching workflows that preserve conversation history

---

## Design Principles

1. **Each node owns its fork semantics** - No universal "fork" logic; each node type implements what makes sense for it
2. **Opt-in implementation** - Base class raises `NotImplementedError`; nodes implement as needed
3. **Consistent across interfaces** - SDK, TUI, CLI all use the same underlying mechanism
4. **Workflow-ready** - Fork can be used as a step in workflows/graphs

---

## Phase 1: Core Infrastructure

### 1.1 Base Node Class

**File:** `src/nerve/core/nodes/base.py` (or wherever Node base class lives)

```python
class Node:
    def fork(self, new_id: str) -> "Node":
        """Fork this node with a new ID.

        Creates a new node with copied state. The exact semantics
        depend on the node type:
        - StatefulLLMNode: Deep copies conversation history
        - PTYNode: Respawns same command (fresh terminal)
        - Stateless nodes: Creates new instance with same config

        Args:
            new_id: Unique ID for the forked node.

        Returns:
            New Node instance registered in the same session.

        Raises:
            NotImplementedError: If this node type doesn't support forking.
            ValueError: If new_id already exists in session.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support forking"
        )
```

**Tasks:**
- [x] Add `fork()` method to Node base class (via concrete implementations)
- [x] Add docstring explaining fork semantics

---

### 1.2 StatefulLLMNode Implementation

**File:** `src/nerve/core/nodes/llm/stateful.py`

```python
import copy
from datetime import datetime

class StatefulLLMNode:
    def fork(self, new_id: str) -> "StatefulLLMNode":
        """Fork this node with copied conversation history.

        Creates a new StatefulLLMNode with:
        - Same LLM backend (shared, stateless)
        - Same system prompt
        - Same tools configuration
        - Deep copied message history

        Args:
            new_id: Unique ID for the forked node.

        Returns:
            New StatefulLLMNode with full conversation context.
        """
        # Validate unique ID
        self.session.validate_unique_id(new_id)

        # Create new node with same configuration
        forked = StatefulLLMNode(
            id=new_id,
            session=self.session,
            llm=self.llm,  # Shared reference OK - stateless
            system=self.system,
            tools=copy.deepcopy(self.tools) if self.tools else None,
            tool_executor=self.tool_executor,
            max_tool_rounds=self.max_tool_rounds,
            tool_choice=self.tool_choice,
            parallel_tool_calls=self.parallel_tool_calls,
            metadata={
                **self.metadata,
                "forked_from": self.id,
                "fork_time": datetime.now().isoformat(),
                "fork_message_count": len(self.messages),
            },
        )

        # Deep copy conversation history
        forked.messages = [
            Message(
                role=m.role,
                content=m.content,
                tool_calls=copy.deepcopy(m.tool_calls) if m.tool_calls else None,
                tool_call_id=m.tool_call_id,
                name=m.name,
            )
            for m in self.messages
        ]

        # Log the fork
        if self.session._session_logger:
            self.session._session_logger.log_node_lifecycle(
                node_id=new_id,
                node_type="StatefulLLMNode",
                event="forked",
                details={"forked_from": self.id, "message_count": len(forked.messages)},
            )

        return forked
```

**Tasks:**
- [x] Import `copy` and `datetime` modules
- [x] Implement `fork()` method
- [x] Deep copy messages with all fields (role, content, tool_calls, etc.)
- [x] Set fork metadata (forked_from, fork_timestamp)
- [ ] Add session logging for fork event (deferred)

---

### 1.3 Server Handler

**File:** `src/nerve/server/handlers/node_lifecycle_handler.py`

```python
async def fork_node(self, params: dict[str, Any]) -> dict[str, Any]:
    """Fork an existing node.

    Creates a new node with copied state from the source node.
    The exact fork semantics depend on the node type.

    Params:
        source_id: ID of node to fork
        target_id: ID for the new forked node

    Returns:
        {
            "success": True,
            "node_id": target_id,
            "forked_from": source_id,
            "node_type": "StatefulLLMNode",
            "message_count": 5,  # For LLM nodes
        }

    Raises:
        ValueError: If source node not found or target ID exists
        NotImplementedError: If node type doesn't support forking
    """
    source_id = params.get("source_id")
    target_id = params.get("target_id")

    if not source_id or not target_id:
        raise ValueError("source_id and target_id are required")

    session = self._get_session()
    source_node = session.nodes.get(source_id)

    if not source_node:
        raise ValueError(f"Node '{source_id}' not found")

    # Let the node handle its own fork logic
    try:
        forked = source_node.fork(target_id)
    except NotImplementedError as e:
        raise ValueError(str(e))

    # Build response
    result = {
        "success": True,
        "node_id": forked.id,
        "forked_from": source_id,
        "node_type": type(forked).__name__,
    }

    # Add message count for LLM nodes
    if hasattr(forked, "messages"):
        result["message_count"] = len(forked.messages)

    return result
```

**Tasks:**
- [x] Add `fork_node()` method to NodeLifecycleHandler
- [x] Register handler in the dispatcher/router (FORK_NODE CommandType)
- [x] Handle NotImplementedError gracefully with user-friendly message
- [x] Return appropriate metadata (node_id, forked_from)

---

### 1.4 Client Adapter

**File:** `src/nerve/frontends/cli/repl/adapters.py` (or similar)

```python
class RemoteSessionAdapter:
    async def fork_node(self, source_id: str, target_id: str) -> dict[str, Any]:
        """Fork a node.

        Args:
            source_id: ID of node to fork.
            target_id: ID for the new forked node.

        Returns:
            Response dict with node_id, forked_from, etc.

        Raises:
            ValueError: If fork fails.
        """
        return await self._call("fork_node", {
            "source_id": source_id,
            "target_id": target_id,
        })
```

**Tasks:**
- [x] Add `fork_node()` method to RemoteSessionAdapter
- [x] Add `fork_node()` method to LocalSessionAdapter
- [x] Add `fork_node()` method to SessionAdapter Protocol
- [x] Ensure error handling propagates server errors

---

## Phase 2: User Interfaces

### 2.1 TUI Command

**File:** `src/nerve/frontends/tui/commander/commands.py`

```python
import time

async def handle_fork(cmd: Commander, args: str) -> None:
    """Fork a node or graph.

    Usage:
        :fork @node [new_name]
        :fork %graph [new_name]  (Phase 3)

    Examples:
        :fork @claude              → claude_fork_7234
        :fork @claude experiment   → experiment
    """
    args = args.strip()

    if not args:
        cmd.console.print("[error]Usage: :fork @node [new_name][/error]")
        return

    parts = args.split(maxsplit=1)
    source = parts[0]

    # Determine if node or graph
    if source.startswith("@"):
        source_id = source[1:]
        entity_type = "node"
    elif source.startswith("%"):
        source_id = source[1:]
        entity_type = "graph"
        cmd.console.print("[error]Graph forking not yet supported[/error]")
        return
    else:
        cmd.console.print("[error]Specify @node or %graph to fork[/error]")
        return

    # Validate source exists
    if source_id not in cmd._entities.entities:
        cmd.console.print(f"[error]Node '@{source_id}' not found[/error]")
        return

    # Generate or use provided target name
    if len(parts) > 1:
        target_id = parts[1].lstrip("@").lstrip("%")
    else:
        # Auto-generate: claude_fork_7234
        target_id = f"{source_id}_fork_{int(time.time()) % 10000}"

    # Check target doesn't exist
    if target_id in cmd._entities.entities:
        cmd.console.print(f"[error]Node '@{target_id}' already exists[/error]")
        return

    try:
        result = await cmd.adapter.fork_node(source_id, target_id)

        # Refresh entity list
        await cmd._entities.sync()

        # Success message
        msg_info = ""
        if "message_count" in result:
            msg_info = f" ({result['message_count']} messages copied)"

        cmd.console.print(f"[green]Forked @{source_id} → @{target_id}[/green]{msg_info}")

    except Exception as e:
        cmd.console.print(f"[error]Fork failed: {e}[/error]")


# Register in COMMAND_HANDLERS
COMMAND_HANDLERS["fork"] = handle_fork
```

**Tasks:**
- [x] Add `cmd_fork()` function
- [x] Register in COMMANDS dict
- [x] Handle @ prefix for nodes
- [ ] Add to help text (consider for future)

---

### 2.2 CLI Command

**File:** `src/nerve/frontends/cli/commands/node.py` (or similar)

```python
@node_group.command("fork")
@click.argument("source")
@click.argument("target")
@click.option("--session", "-s", help="Session name")
@click.option("--execute", "-e", help="Execute message on forked node")
async def fork_node(source: str, target: str, session: str, execute: str | None):
    """Fork a node with copied state.

    Examples:
        nerve node fork claude claude_experiment
        nerve node fork claude alt --execute "Try a different approach"
    """
    async with get_session(session) as adapter:
        result = await adapter.fork_node(source, target)

        click.echo(f"Forked '{source}' → '{target}'")

        if "message_count" in result:
            click.echo(f"  Copied {result['message_count']} messages")

        # Optionally execute on the fork
        if execute:
            response = await adapter.execute_on_node(target, execute)
            click.echo(f"\nResponse:\n{response.get('output', '')}")
```

**Tasks:**
- [x] Add `fork` subcommand to node command group (`nerve server node fork`)
- [x] Add --session option for multi-session support
- [x] Add --execute option for fork-and-run pattern
- [x] Add --json option for JSON output
- [x] Auto-generate target name if not provided
- [x] Format output consistently with other commands

---

### 2.3 SDK Interface

**File:** `src/nerve/frontends/sdk/nodes.py` (or wherever SDK Node class is)

The `fork()` method is already on the Node class from Phase 1.1.

For SDK usage, ensure the session's node wrapper exposes it:

```python
class NodeHandle:
    """SDK wrapper for remote node operations."""

    def fork(self, new_id: str) -> "NodeHandle":
        """Fork this node with a new ID.

        Returns:
            NodeHandle for the forked node.
        """
        result = self._session.adapter.fork_node(self.id, new_id)
        return self._session.get_node(result["node_id"])
```

**Tasks:**
- [x] Ensure SDK RemoteNode exposes fork()
- [x] Return a new RemoteNode for the forked node
- [x] Add docstring with usage examples
- [ ] Add to SDK documentation/examples (consider for future)

---

## Phase 3: Workflow Integration

### 3.1 Fork as Workflow Step

**Goal:** Allow workflows to fork nodes as part of their execution.

**File:** `src/nerve/core/workflow/steps.py` (or similar)

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class ForkNodeStep:
    """Workflow step that forks a node.

    Example workflow:
        workflow = Workflow(
            steps=[
                NodeStep(node_id="claude", input="Analyze this data"),
                ForkNodeStep(source="claude", target="claude_branch"),
                NodeStep(node_id="claude_branch", input="Now try a different angle"),
            ]
        )
    """
    source: str  # Node to fork
    target: str  # New node ID (can use {variables})

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Execute the fork operation."""
        session = context.session
        source_node = session.nodes.get(self.source)

        if not source_node:
            raise ValueError(f"Cannot fork: node '{self.source}' not found")

        # Expand target name if it contains variables
        target_id = self._expand_target(self.target, context)

        forked = source_node.fork(target_id)

        return {
            "success": True,
            "node_id": forked.id,
            "forked_from": self.source,
        }

    def _expand_target(self, target: str, context: ExecutionContext) -> str:
        """Expand {variable} placeholders in target name."""
        # e.g., "branch_{run_id}" → "branch_abc123"
        if "{run_id}" in target and context.run_id:
            target = target.replace("{run_id}", context.run_id[:8])
        if "{timestamp}" in target:
            target = target.replace("{timestamp}", str(int(time.time()) % 10000))
        return target
```

### 3.2 Fork in Workflow DSL

```python
from nerve import Workflow, NodeStep, ForkNodeStep

# Example: A/B test different approaches
workflow = Workflow(
    id="ab_test",
    steps=[
        # Build shared context
        NodeStep(node_id="analyst", input="Analyze the sales data"),

        # Fork for parallel exploration
        ForkNodeStep(source="analyst", target="analyst_conservative"),
        ForkNodeStep(source="analyst", target="analyst_aggressive"),

        # Divergent paths
        NodeStep(
            node_id="analyst_conservative",
            input="Recommend safe, incremental changes",
            depends_on=["fork_analyst_conservative"],
        ),
        NodeStep(
            node_id="analyst_aggressive",
            input="Recommend bold, disruptive changes",
            depends_on=["fork_analyst_aggressive"],
        ),

        # Synthesize
        NodeStep(
            node_id="synthesizer",
            input="Compare the two approaches: {analyst_conservative} vs {analyst_aggressive}",
            depends_on=["analyst_conservative", "analyst_aggressive"],
        ),
    ],
)
```

### 3.3 Fork in Graph

```python
from nerve import Graph, GraphStep

# Fork can also be a graph operation
graph = Graph(
    id="exploration",
    steps=[
        GraphStep(node_id="researcher", input_key="topic"),
        # After research, fork to try different synthesis approaches
        GraphStep(
            operation="fork",
            source="researcher",
            target="researcher_detailed",
        ),
        GraphStep(
            operation="fork",
            source="researcher",
            target="researcher_summary",
        ),
        GraphStep(node_id="researcher_detailed", input="Now provide exhaustive detail"),
        GraphStep(node_id="researcher_summary", input="Now summarize in 3 bullets"),
    ],
)
```

**Tasks:**
- [ ] Create ForkNodeStep class
- [ ] Add "fork" as a graph operation type
- [ ] Support variable expansion in target names
- [ ] Add examples to documentation

---

## Phase 4: Additional Node Types (Optional)

### 4.1 BashNode Fork

```python
class BashNode:
    def fork(self, new_id: str) -> "BashNode":
        """Fork this bash node with same configuration.

        Creates a new BashNode with same cwd, env, timeout.
        No state is copied (bash is stateless per-execution).
        """
        self.session.validate_unique_id(new_id)

        forked = BashNode(
            id=new_id,
            session=self.session,
            cwd=self.cwd,
            env=dict(self.env) if self.env else None,
            timeout=self.timeout,
            metadata={
                **self.metadata,
                "forked_from": self.id,
                "fork_time": datetime.now().isoformat(),
            },
        )

        return forked
```

### 4.2 PTYNode Fork

```python
class PTYNode:
    async def fork(self, new_id: str) -> "PTYNode":
        """Fork this PTY node by respawning with same command.

        Creates a new PTYNode with:
        - Same command
        - Same cwd/env configuration
        - Fresh terminal (buffer not copied)

        Note: This is an async operation (process spawn).
        """
        self.session.validate_unique_id(new_id)

        # Respawn with same config
        forked = await PTYNode.create(
            id=new_id,
            session=self.session,
            command=self.backend.command_list[0],  # Original command
            cwd=self.backend.config.cwd,
            env=self.backend.config.env,
            metadata={
                **self.metadata,
                "forked_from": self.id,
                "fork_time": datetime.now().isoformat(),
            },
        )

        return forked
```

**Note:** PTYNode.fork() is async because it spawns a process. Handler needs to await it.

**Tasks:**
- [ ] Implement BashNode.fork() (simple)
- [ ] Implement PTYNode.fork() (async, respawn)
- [ ] Update handler to detect and await async fork()
- [ ] Test process isolation

---

## Testing

### Unit Tests

```python
# test_node_fork.py

class TestStatefulLLMNodeFork:
    async def test_fork_copies_messages(self):
        session = create_test_session()
        node = StatefulLLMNode(id="original", session=session, llm=mock_llm)
        node.messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
        ]

        forked = node.fork("forked")

        assert forked.id == "forked"
        assert len(forked.messages) == 2
        assert forked.messages[0].content == "Hello"
        assert forked.metadata["forked_from"] == "original"

    async def test_fork_is_independent(self):
        # Changes to fork don't affect original
        session = create_test_session()
        node = StatefulLLMNode(id="original", session=session, llm=mock_llm)
        node.messages = [Message(role="user", content="Hello")]

        forked = node.fork("forked")
        forked.messages.append(Message(role="assistant", content="New message"))

        assert len(node.messages) == 1  # Original unchanged
        assert len(forked.messages) == 2

    async def test_fork_validates_unique_id(self):
        session = create_test_session()
        session.nodes["existing"] = mock_node
        node = StatefulLLMNode(id="original", session=session, llm=mock_llm)

        with pytest.raises(ValueError, match="already exists"):
            node.fork("existing")

    async def test_fork_not_implemented(self):
        # Base node raises NotImplementedError
        session = create_test_session()
        node = SomeStatelessNode(id="test", session=session)

        with pytest.raises(NotImplementedError):
            node.fork("forked")


class TestForkHandler:
    async def test_fork_node_success(self):
        handler = NodeLifecycleHandler(registry)
        result = await handler.fork_node({
            "source_id": "claude",
            "target_id": "claude_fork",
        })

        assert result["success"] is True
        assert result["node_id"] == "claude_fork"
        assert result["forked_from"] == "claude"

    async def test_fork_node_not_found(self):
        handler = NodeLifecycleHandler(registry)

        with pytest.raises(ValueError, match="not found"):
            await handler.fork_node({
                "source_id": "nonexistent",
                "target_id": "fork",
            })
```

**Tasks:**
- [x] Test message deep copy independence
- [x] Test tool_calls deep copy
- [x] Test metadata preservation
- [x] Test unique ID validation
- [x] Test NotImplementedError for unsupported nodes
- [x] Test handler error cases
- [x] Test forked node is independent
- [x] Test multiple forks are independent
- [x] Test SDK RemoteNode.fork() success and error cases

---

## Implementation Order

### Phase 1: Core ✅ COMPLETE
1. [x] Add `fork()` to Node base class (via concrete implementations)
2. [x] Implement `StatefulLLMNode.fork()`
3. [x] Add unit tests for StatefulLLMNode.fork() (16 tests in tests/core/nodes/llm/test_fork.py)
4. [x] Add `fork_node()` to NodeLifecycleHandler
5. [x] Add `fork_node()` to RemoteSessionAdapter
6. [x] Add `fork_node()` to LocalSessionAdapter

### Phase 2: Interfaces ✅ COMPLETE
7. [x] Add `:fork` command to TUI
8. [x] Add `nerve server node fork` CLI command
9. [x] Ensure SDK exposes fork() via RemoteNode.fork()
10. [x] Add tests (11 handler tests in tests/server/test_fork_handler.py, 5 SDK tests in tests/frontends/sdk/test_client.py)

### Phase 3: Workflows (Deferred)
11. [ ] Create ForkNodeStep for workflows
12. [ ] Add "fork" operation to Graph
13. [ ] Add workflow examples

### Phase 4: Additional Node Types (Deferred)
14. [ ] Implement BashNode.fork()
15. [ ] Implement PTYNode.fork() (async)
16. [ ] Add `:forks` command to show lineage
17. [ ] Documentation

---

## Open Questions

1. **Cross-session fork?** - Should `fork()` accept a target session? Defer to Phase 2.

2. **Fork at point in history?** - Should we support `node.fork("new", at_message=5)` to truncate? Defer.

3. **Graph deep fork?** - When forking a graph, fork all stateful nodes too? Phase 3.

4. **Async fork for PTYNode?** - Handler needs to detect async fork. Consider `async def fork()` signature.

---

## Success Criteria

1. **SDK:** `node.fork("new_id")` works and returns usable node
2. **TUI:** `:fork @claude experiment` creates independent conversation
3. **CLI:** `nerve node fork claude experiment` works
4. **Workflow:** ForkNodeStep can be used in workflow definitions
5. **Independence:** Changes to forked node don't affect original
6. **Metadata:** Fork lineage tracked in metadata
