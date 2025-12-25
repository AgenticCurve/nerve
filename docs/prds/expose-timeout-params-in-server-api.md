# PRD: Expose Timeout Parameters in Server API

## Problem Statement

When using the nerve server via the transport layer (Unix socket, TCP, HTTP), there is no way to configure timeout parameters for node execution. This causes premature timeout errors when running long operations.

### Current Behavior

The `dev_coach_review.py` example demonstrates the issue:

```python
# Client-side timeout (transport layer) - 40 minutes
result = await client.send_command(
    Command(type=CommandType.EXECUTE_INPUT, params={...}),
    timeout=2400.0,  # 40 minutes
)
```

**Error received:**
```
Error: Terminal did not become ready within 1800.0s
```

The 40-minute client timeout is ineffective because the node's internal `_response_timeout` (30 minutes) fires first.

### Root Cause

There are **two independent timeout systems** that don't communicate:

1. **Transport timeout** (`send_command(timeout=...)`) - How long the client waits for a response from the server
2. **Node response_timeout** (`_response_timeout`) - How long the node waits for the terminal to become ready after sending input

The node's timeout is hardcoded to 1800.0s (30 min) and cannot be configured through the server API.

## Goals

1. Allow configuring `response_timeout` when creating nodes via `CREATE_NODE`
2. Allow configuring `timeout` when executing input via `EXECUTE_INPUT`
3. Maintain backward compatibility (existing code works unchanged)
4. Provide consistent timeout configuration across all node types

## Non-Goals

- Changing default timeout values
- Adding timeout to BashNode creation (BashNode uses a different `timeout` field for command execution, already configurable)
- Transport-layer timeout changes (already configurable)

## Technical Analysis

### Timeout Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT                                         │
│  send_command(..., timeout=2400.0)                                          │
│  └── Transport timeout: 40 min (waits for server response)                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SERVER                                         │
│  _execute_input()                                                           │
│  └── Creates ExecutionContext(timeout=None)  ← NOT CONFIGURABLE             │
│      └── node.execute(context)                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              NODE                                           │
│  PTYNode/WezTermNode/ClaudeWezTermNode                                      │
│  └── _response_timeout = 1800.0  ← HARDCODED (30 min)                       │
│      └── timeout = context.timeout or self._response_timeout                │
│          └── _wait_for_ready(timeout=...)                                   │
│              └── TimeoutError after 30 min!                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Affected Node Types

| Node Type | Has `response_timeout`? | Has `ready_timeout`? | Used in `CREATE_NODE`? |
|-----------|-------------------------|----------------------|------------------------|
| PTYNode | Yes (line 99) | Yes (line 98) | Yes |
| WezTermNode | Yes (line 664, 782) | Yes (line 663, 781) | Yes |
| ClaudeWezTermNode | Yes (line 1314) | Yes (line 1313) | Yes |
| BashNode | No (uses `timeout` for cmd execution) | No | No |

### Key Code Locations

1. **Node creation defaults** (`terminal.py`):
   - PTYNode.create: lines 98-99
   - WezTermNode.create: lines 663-664
   - WezTermNode.attach: lines 781-782
   - ClaudeWezTermNode.create: lines 1313-1314

2. **Server command handlers** (`engine.py`):
   - `_create_node`: lines 192-269
   - `_execute_input`: lines 361-420

3. **Timeout resolution** (`terminal.py`):
   - PTYNode.execute: line 259: `timeout = context.timeout or self._response_timeout`
   - WezTermNode.execute: line 984: `timeout = context.timeout or self._response_timeout`

## Proposed Solution

### Phase 1: Expose `response_timeout` in CREATE_NODE

Add `response_timeout` parameter to `CREATE_NODE` command.

**File: `src/nerve/server/engine.py`**

```python
async def _create_node(self, params: dict[str, Any]) -> dict[str, Any]:
    # ... existing code ...

    # ADD: Extract timeout parameters
    response_timeout = params.get("response_timeout", 1800.0)
    ready_timeout = params.get("ready_timeout", 60.0)

    # Dispatch to appropriate node class based on backend
    if backend == "pty":
        node = await PTYNode.create(
            id=str(node_id),
            session=session,
            command=command,
            cwd=cwd,
            history=history,
            response_timeout=response_timeout,  # ADD
            ready_timeout=ready_timeout,         # ADD
        )
    elif backend == "wezterm":
        if pane_id:
            node = await WezTermNode.attach(
                id=str(node_id),
                session=session,
                pane_id=pane_id,
                history=history,
                response_timeout=response_timeout,  # ADD
                ready_timeout=ready_timeout,         # ADD
            )
        else:
            node = await WezTermNode.create(
                id=str(node_id),
                session=session,
                command=command,
                cwd=cwd,
                history=history,
                response_timeout=response_timeout,  # ADD
                ready_timeout=ready_timeout,         # ADD
            )
    elif backend == "claude-wezterm":
        if not command:
            raise ValueError("command is required for claude-wezterm backend")
        node = await ClaudeWezTermNode.create(
            id=str(node_id),
            session=session,
            command=command,
            cwd=cwd,
            history=history,
            response_timeout=response_timeout,  # ADD
            ready_timeout=ready_timeout,         # ADD
        )
    # ... rest of method ...
```

**Usage:**
```python
result = await client.send_command(
    Command(
        type=CommandType.CREATE_NODE,
        params={
            "node_id": "dev",
            "command": "claude --dangerously-skip-permissions",
            "cwd": cwd,
            "backend": "claude-wezterm",
            "response_timeout": 2400.0,  # 40 minutes
        },
    )
)
```

### Phase 2: Expose `timeout` in EXECUTE_INPUT

Add `timeout` parameter to `EXECUTE_INPUT` command. This allows per-execution timeout override.

**File: `src/nerve/server/engine.py`**

```python
async def _execute_input(self, params: dict[str, Any]) -> dict[str, Any]:
    """Execute input on a node and wait for response."""
    session = self._get_session(params)
    node_id = params.get("node_id")
    if not node_id:
        raise ValueError("node_id is required")
    text = params["text"]
    parser_str = params.get("parser")
    stream = params.get("stream", False)
    timeout = params.get("timeout")  # ADD: Optional per-execution timeout

    node = session.get_node(str(node_id))
    if not node:
        raise ValueError(f"Node not found: {node_id}")

    parser_type = ParserType(parser_str) if parser_str else None

    await self._emit(EventType.NODE_BUSY, node_id=node_id)

    # Create execution context with optional timeout
    context = ExecutionContext(
        session=session,
        input=text,
        timeout=timeout,  # ADD: Pass timeout to context
    )

    # ... rest of method unchanged ...
```

**Usage:**
```python
result = await client.send_command(
    Command(
        type=CommandType.EXECUTE_INPUT,
        params={
            "node_id": "dev",
            "text": "Implement the feature...",
            "parser": "claude",
            "timeout": 2400.0,  # 40 minutes for this specific execution
        },
    ),
    timeout=2500.0,  # Transport timeout slightly higher
)
```

### Phase 3: Update SDK Client (Optional Enhancement)

Update `NerveClient.create_node()` to expose timeout parameters.

**File: `src/nerve/frontends/sdk/client.py`**

```python
async def create_node(
    self,
    name: str,
    command: str | list[str] | None = None,
    cwd: str | None = None,
    backend: str = "pty",
    response_timeout: float = 1800.0,  # ADD
    ready_timeout: float = 60.0,        # ADD
) -> RemoteNode:
    # ... update both standalone and transport paths ...
```

## API Reference

### CREATE_NODE Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| node_id | str | required | Unique node identifier |
| command | str \| list | None | Command to run |
| cwd | str | None | Working directory |
| backend | str | "pty" | Node backend: "pty", "wezterm", "claude-wezterm" |
| pane_id | str | None | WezTerm pane ID (for attach) |
| history | bool | True | Enable history logging |
| **response_timeout** | float | 1800.0 | **NEW:** Max wait time for terminal response (seconds) |
| **ready_timeout** | float | 60.0 | **NEW:** Max wait time for terminal to become ready initially (seconds) |

### EXECUTE_INPUT Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| node_id | str | required | Node to execute on |
| text | str | required | Input to send |
| parser | str | None | Parser type: "claude", "gemini", "none" |
| stream | bool | False | Stream output as events |
| **timeout** | float | None | **NEW:** Override node's response_timeout for this execution |

## Testing Requirements

### Unit Tests

1. **CREATE_NODE with response_timeout**
   - Test PTYNode creation with custom response_timeout
   - Test WezTermNode creation with custom response_timeout
   - Test WezTermNode attach with custom response_timeout
   - Test ClaudeWezTermNode creation with custom response_timeout
   - Test default values are preserved when not specified

2. **EXECUTE_INPUT with timeout**
   - Test timeout is passed to ExecutionContext
   - Test timeout overrides node's _response_timeout
   - Test None timeout uses node default

### Integration Tests

1. **Long-running execution**
   - Create node with 5-second response_timeout
   - Execute command that takes 3 seconds (should succeed)
   - Execute command that takes 10 seconds (should timeout)

2. **Per-execution override**
   - Create node with 5-second response_timeout
   - Execute with 10-second timeout, command takes 7 seconds (should succeed)

## Migration Guide

### Existing Code (No Changes Required)

```python
# This continues to work - uses defaults
result = await client.send_command(
    Command(
        type=CommandType.CREATE_NODE,
        params={
            "node_id": "dev",
            "command": "claude",
            "backend": "claude-wezterm",
        },
    )
)
```

### Updated Code (For Long Operations)

```python
# Recommended: Set at node creation for consistent behavior
result = await client.send_command(
    Command(
        type=CommandType.CREATE_NODE,
        params={
            "node_id": "dev",
            "command": "claude --dangerously-skip-permissions",
            "backend": "claude-wezterm",
            "response_timeout": 3600.0,  # 1 hour
        },
    )
)

# Or: Override per-execution for specific long operations
result = await client.send_command(
    Command(
        type=CommandType.EXECUTE_INPUT,
        params={
            "node_id": "dev",
            "text": "Implement complex feature...",
            "parser": "claude",
            "timeout": 3600.0,  # 1 hour for this specific call
        },
    ),
    timeout=3700.0,  # Transport timeout must be >= execution timeout
)
```

## Implementation Checklist

### Phase 1: CREATE_NODE Enhancement
- [ ] Extract `response_timeout` from params in `_create_node()`
- [ ] Extract `ready_timeout` from params in `_create_node()`
- [ ] Pass to `PTYNode.create()`
- [ ] Pass to `WezTermNode.create()`
- [ ] Pass to `WezTermNode.attach()`
- [ ] Pass to `ClaudeWezTermNode.create()`
- [ ] Add unit tests for each node type
- [ ] Update docstring in `_create_node()`

### Phase 2: EXECUTE_INPUT Enhancement
- [ ] Extract `timeout` from params in `_execute_input()`
- [ ] Pass to `ExecutionContext`
- [ ] Add unit tests
- [ ] Update docstring in `_execute_input()`

### Phase 3: SDK Enhancement (Optional)
- [ ] Add parameters to `NerveClient.create_node()`
- [ ] Update standalone path
- [ ] Update transport path
- [ ] Add `timeout` parameter to `RemoteNode.send()`
- [ ] Update docstrings

### Documentation
- [ ] Update API documentation
- [ ] Update examples (dev_coach_review.py, etc.)

## Files to Modify

| File | Changes |
|------|---------|
| `src/nerve/server/engine.py` | Add timeout params to `_create_node()` and `_execute_input()` |
| `src/nerve/frontends/sdk/client.py` | (Optional) Add timeout params to SDK |
| `tests/server/test_engine.py` | Add unit tests |
| `examples/dev_coach_review.py` | Update to use new params |
| `examples/dev_coach.py` | Update to use new params |
| `examples/dev_coach_architecture.py` | Update to use new params |

## Success Criteria

1. `dev_coach_review.py` runs without "Terminal did not become ready within 1800.0s" errors when configured with 40-minute timeout
2. All existing tests pass
3. New timeout parameters are documented
4. Backward compatibility maintained (no breaking changes)
