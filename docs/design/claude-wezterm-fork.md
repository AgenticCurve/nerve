# ClaudeWezTerm Node Fork - Implementation Plan

## Overview

Add fork support to ClaudeWezTermNode by leveraging Claude Code CLI's native session forking mechanism. This enables branching conversations in Claude Code terminals, allowing users to explore alternative paths from a specific point in a conversation.

---

## Background

### How Claude Code Session Forking Works

Claude Code CLI manages conversation history via session IDs. It provides native fork support:

```bash
# Original session
claude --dangerously-skip-permissions --session-id <original-uuid>

# Fork from existing session
claude --dangerously-skip-permissions \
  --resume <original-uuid> \
  --fork-session \
  --session-id <new-uuid>
```

**Key CLI flags:**
- `--session-id <uuid>` - Specify session ID (controls where history is stored)
- `--resume <uuid>` - Resume from an existing session's history
- `--fork-session` - Create a branch rather than continuing in-place

### Current State

ClaudeWezTermNode currently:
- Takes a user-provided command like `"claude --dangerously-skip-permissions"`
- Does NOT inject `--session-id` - Claude auto-generates one
- Has no way to track or reference the Claude session ID
- Cannot fork because we don't know which session to fork from

---

## Design Principles

1. **Leverage Claude's native fork** - Use `--resume --fork-session`, don't reinvent
2. **Backward compatible** - Existing nodes without session tracking gracefully fail fork
3. **Consistent interface** - `fork()` method matches StatefulLLMNode pattern
4. **Async by nature** - ClaudeWezTermNode.fork() is async (spawns process)

---

## Phase 1: Session ID Tracking

### 1.1 Add Session ID Field

**File:** `src/nerve/core/nodes/terminal/claude_wezterm_node.py`

Add field to track the Claude session ID:

```python
@dataclass
class ClaudeWezTermNode:
    # ... existing fields ...

    # Claude Code session tracking (for fork support)
    _claude_session_id: str | None = field(default=None, init=False, repr=False)
```

**Tasks:**
- [ ] Add `_claude_session_id` field to ClaudeWezTermNode dataclass

---

### 1.2 Update `create()` to Generate/Inject Session ID

**File:** `src/nerve/core/nodes/terminal/claude_wezterm_node.py`

Modify `create()` to:
1. Accept optional `claude_session_id` parameter
2. Generate UUID if not provided
3. Inject `--session-id` into command

```python
@classmethod
async def create(
    cls,
    id: str,
    session: Session,
    command: str,
    cwd: str | None = None,
    history: bool | None = None,
    parser: ParserType = ParserType.CLAUDE,
    ready_timeout: float = 60.0,
    response_timeout: float = 1800.0,
    proxy_url: str | None = None,
    claude_session_id: str | None = None,  # NEW
) -> ClaudeWezTermNode:
    """Create a new ClaudeWezTerm node.

    Args:
        # ... existing args ...
        claude_session_id: Claude Code session ID. If not provided, a UUID
                          is generated. Used for fork support.
    """
    import uuid

    # ... existing validation ...

    # Generate Claude session ID if not provided
    if claude_session_id is None:
        claude_session_id = str(uuid.uuid4())

    # Inject --session-id into command if not already present
    if "--session-id" not in command:
        command = f"{command} --session-id {claude_session_id}"

    # ... rest of create() ...

    # Store session ID on wrapper
    wrapper._claude_session_id = claude_session_id

    return wrapper
```

**Tasks:**
- [ ] Add `claude_session_id` parameter to `create()`
- [ ] Generate UUID if not provided
- [ ] Inject `--session-id` into command string
- [ ] Store session ID on the wrapper instance

---

### 1.3 Expose Session ID in `to_info()`

**File:** `src/nerve/core/nodes/terminal/claude_wezterm_node.py`

```python
def to_info(self) -> NodeInfo:
    """Get node information."""
    metadata = {
        "pane_id": self.pane_id,
        "command": self.command,
        "default_parser": self._default_parser.value,
        "last_input": self._last_input,
    }
    if self._proxy_url:
        metadata["proxy_url"] = self._proxy_url
    if self._claude_session_id:
        metadata["claude_session_id"] = self._claude_session_id

    return NodeInfo(
        id=self.id,
        node_type="claude-wezterm",
        state=self.state,
        persistent=self.persistent,
        metadata=metadata,
    )
```

**Tasks:**
- [ ] Add `claude_session_id` to metadata in `to_info()`

---

## Phase 2: Implement `fork()` Method

### 2.1 Add `fork()` Method

**File:** `src/nerve/core/nodes/terminal/claude_wezterm_node.py`

```python
async def fork(self, new_id: str) -> ClaudeWezTermNode:
    """Fork this node by creating a new Claude session branched from this one.

    Uses Claude Code's native fork mechanism:
    - --resume <original-session-id>: Resume from existing session
    - --fork-session: Create a branch instead of continuing
    - --session-id <new-session-id>: ID for the new forked session

    The forked node is completely independent - it has its own WezTerm pane,
    its own Claude process, and its own conversation history branched from
    the fork point.

    Args:
        new_id: Unique ID for the forked node.

    Returns:
        New ClaudeWezTermNode with forked conversation.

    Raises:
        ValueError: If new_id already exists or session ID not tracked.

    Example:
        >>> node = await ClaudeWezTermNode.create(
        ...     id="claude", session=session,
        ...     command="claude --dangerously-skip-permissions"
        ... )
        >>> await node.send("What is Python?")
        >>> # Fork to explore alternative direction
        >>> researcher = await node.fork("researcher")
        >>> await researcher.send("Now focus on security aspects")
        >>> # Original continues independently
        >>> await node.send("Tell me about web frameworks")
    """
    import uuid

    # Validate new_id is unique
    self.session.validate_unique_id(new_id, "node")

    # Validate we have session ID to fork from
    if not self._claude_session_id:
        raise ValueError(
            f"Cannot fork node '{self.id}': Claude session ID not tracked. "
            "This node may have been created before session tracking was added."
        )

    # Generate new session ID for the fork
    new_claude_session_id = str(uuid.uuid4())

    # Build fork command using Claude's native fork mechanism
    base_command = self._extract_base_command()
    fork_command = (
        f"{base_command} "
        f"--resume {self._claude_session_id} "
        f"--fork-session "
        f"--session-id {new_claude_session_id}"
    )

    # Get cwd from inner node's backend
    cwd = self._inner.backend.config.cwd if self._inner.backend.config else None

    # Create new node with fork command
    # Note: We pass claude_session_id explicitly to avoid re-generation
    forked = await ClaudeWezTermNode.create(
        id=new_id,
        session=self.session,
        command=fork_command,
        cwd=cwd,
        history=self._history_writer is not None and self._history_writer.enabled,
        parser=self._default_parser,
        ready_timeout=60.0,
        response_timeout=1800.0,
        proxy_url=self._proxy_url,
        claude_session_id=new_claude_session_id,
    )

    return forked
```

**Tasks:**
- [ ] Implement `fork()` method
- [ ] Validate session ID exists before forking
- [ ] Build fork command with `--resume`, `--fork-session`, `--session-id`
- [ ] Extract cwd from inner node's backend config
- [ ] Propagate proxy_url to forked node

---

### 2.2 Add `_extract_base_command()` Helper

**File:** `src/nerve/core/nodes/terminal/claude_wezterm_node.py`

```python
def _extract_base_command(self) -> str:
    """Extract base command without session/resume/fork flags.

    Strips these flags and their arguments from the stored command:
    - --session-id <value>
    - --resume <value>
    - --fork-session

    Returns:
        Command string without session-related flags.

    Example:
        >>> node._command = "claude --dangerously-skip-permissions --session-id abc123"
        >>> node._extract_base_command()
        'claude --dangerously-skip-permissions'
    """
    import shlex

    try:
        parts = shlex.split(self._command)
    except ValueError:
        # If shlex fails, fall back to simple split
        parts = self._command.split()

    filtered = []
    skip_next = False

    for part in parts:
        if skip_next:
            skip_next = False
            continue

        # Skip flags that take an argument
        if part in ("--session-id", "--resume"):
            skip_next = True
            continue

        # Skip standalone flags
        if part == "--fork-session":
            continue

        filtered.append(part)

    return shlex.join(filtered)
```

**Tasks:**
- [ ] Implement `_extract_base_command()` helper
- [ ] Handle `--session-id`, `--resume` (with arguments)
- [ ] Handle `--fork-session` (standalone flag)
- [ ] Use shlex for proper quoting

---

### 2.3 Handle Initialization Wait

The `create()` method already waits for Claude to start (line 210: `await asyncio.sleep(2)`).

For forked nodes, Claude needs to:
1. Load the forked session history
2. Initialize the conversation context

The existing 2-second wait should be sufficient, but we may need to increase it for large conversation histories. The `ready_timeout` parameter already handles waiting for Claude to be ready.

**Tasks:**
- [ ] Verify 2-second initialization wait is sufficient for fork
- [ ] Consider adding `fork_init_delay` parameter if needed

---

## Phase 3: Update Server Handler for Async Fork

### 3.1 Modify `fork_node()` Handler

**File:** `src/nerve/server/handlers/node_lifecycle_handler.py`

The current handler calls `source.fork(target_id)` synchronously. ClaudeWezTermNode.fork() is async.

```python
async def fork_node(self, params: dict[str, Any]) -> dict[str, Any]:
    """Fork an existing node with a new ID.

    Creates a new node by copying state from the source node.
    Supports both sync fork (StatefulLLMNode) and async fork (ClaudeWezTermNode).

    # ... existing docstring ...
    """
    session = self.session_registry.get_session(params.get("session_id"))

    source_id = self.validation.require_param(params, "source_id")
    target_id = self.validation.require_param(params, "target_id")

    # Get source node
    source = self.validation.get_node(session, source_id)

    # Validate target_id is unique
    if target_id in session.nodes:
        raise ValueError(f"Node '{target_id}' already exists")

    # Try to fork - let the node decide if it supports forking
    try:
        fork_method = getattr(source, "fork", None)
        if fork_method is None:
            raise ValueError(
                f"Node type '{type(source).__name__}' does not support forking"
            )

        # Call fork - handle both sync and async
        result = fork_method(target_id)
        if asyncio.iscoroutine(result):
            forked = await result
        else:
            forked = result

    except NotImplementedError as e:
        raise ValueError(str(e)) from None

    logger.debug(
        "node_forked: source_id=%s, target_id=%s, type=%s",
        source_id,
        target_id,
        type(source).__name__,
    )

    # Emit event
    await self.event_sink.emit(
        Event(
            type=EventType.NODE_CREATED,
            node_id=forked.id,
            data={
                "forked_from": str(source_id),
                "persistent": forked.persistent,
            },
        )
    )

    return {"node_id": forked.id, "forked_from": str(source_id)}
```

**Tasks:**
- [ ] Import `asyncio` in handler file
- [ ] Check if fork result is coroutine
- [ ] Await async fork methods
- [ ] Keep sync fork working (StatefulLLMNode)

---

## Phase 4: Update Node Factory

### 4.1 Pass `claude_session_id` Through Factory

**File:** `src/nerve/server/factories/node_factory.py`

```python
# In the claude-wezterm backend section of create()
if backend == "claude-wezterm":
    # ... existing code ...

    node = await ClaudeWezTermNode.create(
        id=str(node_id),
        session=session,
        command=command_str,
        cwd=cwd,
        history=history,
        ready_timeout=ready_timeout,
        response_timeout=response_timeout,
        proxy_url=proxy_url,
        claude_session_id=kwargs.get("claude_session_id"),  # NEW
    )
```

**Tasks:**
- [ ] Pass `claude_session_id` kwarg to ClaudeWezTermNode.create()

---

## Phase 5: Tests

### 5.1 Unit Tests

**File:** `tests/core/nodes/terminal/test_claude_wezterm_fork.py`

```python
"""Tests for ClaudeWezTermNode fork functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSessionIdTracking:
    """Tests for Claude session ID tracking."""

    async def test_create_generates_session_id(self):
        """create() should generate a UUID session ID."""
        # Mock the inner node creation
        with patch.object(WezTermNode, '_create_internal') as mock_create:
            mock_inner = MagicMock()
            mock_inner.backend = MagicMock()
            mock_inner.backend.write = AsyncMock()
            mock_create.return_value = mock_inner

            node = await ClaudeWezTermNode.create(
                id="test",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
            )

            assert node._claude_session_id is not None
            assert len(node._claude_session_id) == 36  # UUID format

    async def test_create_uses_provided_session_id(self):
        """create() should use provided session ID."""
        with patch.object(WezTermNode, '_create_internal') as mock_create:
            # ... setup ...

            node = await ClaudeWezTermNode.create(
                id="test",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
                claude_session_id="custom-session-id",
            )

            assert node._claude_session_id == "custom-session-id"

    async def test_create_injects_session_id_in_command(self):
        """create() should inject --session-id into command."""
        with patch.object(WezTermNode, '_create_internal') as mock_create:
            mock_inner = MagicMock()
            mock_inner.backend = MagicMock()
            mock_inner.backend.write = AsyncMock()
            mock_create.return_value = mock_inner

            node = await ClaudeWezTermNode.create(
                id="test",
                session=mock_session,
                command="claude --dangerously-skip-permissions",
            )

            # Check write was called with command containing --session-id
            write_calls = mock_inner.backend.write.call_args_list
            command_call = [c for c in write_calls if "--session-id" in str(c)]
            assert len(command_call) > 0

    async def test_session_id_in_to_info(self):
        """to_info() should include claude_session_id in metadata."""
        # ... setup node ...

        info = node.to_info()

        assert "claude_session_id" in info.metadata
        assert info.metadata["claude_session_id"] == node._claude_session_id


class TestExtractBaseCommand:
    """Tests for _extract_base_command() helper."""

    def test_strips_session_id(self):
        """Should remove --session-id and its argument."""
        node._command = "claude --dangerously-skip-permissions --session-id abc123"
        result = node._extract_base_command()
        assert "--session-id" not in result
        assert "abc123" not in result
        assert "claude --dangerously-skip-permissions" in result

    def test_strips_resume(self):
        """Should remove --resume and its argument."""
        node._command = "claude --resume old-session --fork-session"
        result = node._extract_base_command()
        assert "--resume" not in result
        assert "old-session" not in result

    def test_strips_fork_session(self):
        """Should remove --fork-session flag."""
        node._command = "claude --fork-session --dangerously-skip-permissions"
        result = node._extract_base_command()
        assert "--fork-session" not in result
        assert "--dangerously-skip-permissions" in result

    def test_preserves_other_flags(self):
        """Should preserve unrelated flags."""
        node._command = "claude --dangerously-skip-permissions --model opus --session-id abc"
        result = node._extract_base_command()
        assert "--dangerously-skip-permissions" in result
        assert "--model" in result
        assert "opus" in result


class TestClaudeWezTermFork:
    """Tests for ClaudeWezTermNode.fork() method."""

    async def test_fork_creates_new_node(self):
        """fork() should create a new node with forked session."""
        # ... setup source node with session ID ...

        forked = await source.fork("forked")

        assert forked.id == "forked"
        assert forked is not source
        assert "forked" in session.nodes

    async def test_fork_uses_resume_and_fork_session_flags(self):
        """fork() should use --resume and --fork-session in command."""
        # ... setup ...

        forked = await source.fork("forked")

        assert f"--resume {source._claude_session_id}" in forked._command
        assert "--fork-session" in forked._command

    async def test_fork_generates_new_session_id(self):
        """fork() should generate new session ID for forked node."""
        # ... setup ...

        forked = await source.fork("forked")

        assert forked._claude_session_id is not None
        assert forked._claude_session_id != source._claude_session_id

    async def test_fork_without_session_id_raises(self):
        """fork() should raise if source has no session ID."""
        source._claude_session_id = None

        with pytest.raises(ValueError, match="session ID not tracked"):
            await source.fork("forked")

    async def test_fork_validates_unique_id(self):
        """fork() should raise if target ID exists."""
        session.nodes["existing"] = MagicMock()

        with pytest.raises(ValueError, match="conflicts"):
            await source.fork("existing")

    async def test_fork_preserves_proxy_url(self):
        """fork() should propagate proxy_url to forked node."""
        source._proxy_url = "http://127.0.0.1:8080"

        forked = await source.fork("forked")

        assert forked._proxy_url == "http://127.0.0.1:8080"

    async def test_fork_extracts_cwd_from_inner(self):
        """fork() should use cwd from inner node's backend."""
        source._inner.backend.config.cwd = "/home/user/project"

        # ... mock create to capture cwd argument ...

        forked = await source.fork("forked")

        # Verify cwd was passed to create()


class TestForkIndependence:
    """Tests verifying forked nodes are independent."""

    async def test_forked_node_has_separate_pane(self):
        """Forked node should have different WezTerm pane."""
        forked = await source.fork("forked")

        assert forked.pane_id != source.pane_id

    async def test_forked_node_has_separate_session_id(self):
        """Forked node should have different Claude session ID."""
        forked = await source.fork("forked")

        assert forked._claude_session_id != source._claude_session_id
```

### 5.2 Handler Integration Tests

**File:** `tests/server/test_fork_handler.py` (add to existing)

```python
class TestAsyncFork:
    """Tests for async fork support in handler."""

    @pytest.mark.asyncio
    async def test_fork_async_node(self, engine):
        """Test forking a node with async fork() method."""
        # Create mock node with async fork
        mock_node = MagicMock()
        mock_node.id = "source"
        mock_node.persistent = True

        async def async_fork(new_id):
            forked = MagicMock()
            forked.id = new_id
            forked.persistent = True
            session.nodes[new_id] = forked
            return forked

        mock_node.fork = async_fork
        session.nodes["source"] = mock_node

        result = await engine.execute(
            Command(
                type=CommandType.FORK_NODE,
                params={"source_id": "source", "target_id": "forked"},
            )
        )

        assert result.success is True
        assert result.data["node_id"] == "forked"
```

**Tasks:**
- [ ] Create `tests/core/nodes/terminal/test_claude_wezterm_fork.py`
- [ ] Add session ID tracking tests
- [ ] Add `_extract_base_command()` tests
- [ ] Add fork method tests
- [ ] Add independence tests
- [ ] Add async fork handler tests

---

## Implementation Checklist

### Phase 1: Session ID Tracking
- [ ] Add `_claude_session_id` field to ClaudeWezTermNode
- [ ] Add `claude_session_id` parameter to `create()`
- [ ] Generate UUID if not provided
- [ ] Inject `--session-id` into command
- [ ] Store session ID on wrapper instance
- [ ] Expose in `to_info()` metadata

### Phase 2: Fork Method
- [ ] Implement `fork()` method
- [ ] Implement `_extract_base_command()` helper
- [ ] Validate session ID exists
- [ ] Build fork command with proper flags
- [ ] Extract cwd from inner node
- [ ] Propagate proxy_url

### Phase 3: Handler Update
- [ ] Import asyncio in handler
- [ ] Check if fork result is coroutine
- [ ] Await async fork methods
- [ ] Verify sync fork still works

### Phase 4: Factory Update
- [ ] Pass `claude_session_id` through factory

### Phase 5: Tests
- [ ] Session ID generation tests
- [ ] Session ID injection tests
- [ ] `_extract_base_command()` tests
- [ ] Fork method tests
- [ ] Fork independence tests
- [ ] Async handler tests

---

## Success Criteria

1. **New nodes track session ID:** Every ClaudeWezTermNode created has a `_claude_session_id`
2. **Fork creates branched conversation:** `:fork @claude` creates node with `--resume --fork-session`
3. **Forked nodes are independent:** Separate panes, separate Claude sessions
4. **Backward compatible:** Existing code continues to work
5. **Both sync and async fork:** Handler works with StatefulLLMNode and ClaudeWezTermNode

---

## Open Questions (Resolved)

1. ~~Store cwd explicitly or extract from inner node?~~ → **Extract from inner node**
2. ~~Wait for forked Claude to initialize?~~ → **Yes, use existing ready_timeout mechanism**
3. ~~Fork metadata in to_info() or separate?~~ → **Separate - forked node is independent**
