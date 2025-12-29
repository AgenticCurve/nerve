# Node Output Schema - Unified Standard

## Design Principles

1. **All nodes return dicts** - No exceptions are raised for execution errors
2. **Common base fields** - Every node returns `success`, `error`, and `error_type`
3. **Node-specific fields** - Each node type can add additional fields
4. **Structured errors** - Errors are categorized with `error_type`
5. **Tool-friendly** - JSON-serializable for logging, tools, and APIs

---

## Base Schema (All Nodes)

Every node's `execute()` method returns a dict with these base fields:

```python
{
    "success": bool,           # True if execution succeeded, False otherwise
    "error": str | None,       # Error message if failed, None if success
    "error_type": str | None,  # Error classification (see Error Types below)
}
```

---

## Error Types (Standardized)

All nodes use consistent `error_type` values:

| error_type | Description | Example Scenario |
|------------|-------------|-----------------|
| `"node_stopped"` | Node is in STOPPED state | Node was stopped before execution |
| `"timeout"` | Execution exceeded timeout | Command/request took too long |
| `"interrupted"` | Execution was interrupted | User sent Ctrl+C |
| `"invalid_request_error"` | Invalid input/parameters | Missing required input |
| `"authentication_error"` | API authentication failed | Invalid API key |
| `"permission_error"` | Permission denied | Insufficient permissions |
| `"rate_limit_error"` | API rate limit exceeded | Too many requests |
| `"api_error"` | Upstream API error (5xx) | Server error from API |
| `"network_error"` | Network connectivity issue | Connection failed |
| `"process_error"` | Process execution failed | Command returned non-zero exit code |
| `"internal_error"` | Unexpected internal error | Uncaught exception |
| `null` | No error (success) | - |

---

## Node-Specific Schemas

### 1. BashNode

**Purpose:** Execute shell commands in subprocess

```python
{
    # Base fields
    "success": bool,
    "error": str | None,
    "error_type": str | None,

    # BashNode-specific fields
    "stdout": str,              # Standard output from command
    "stderr": str,              # Standard error from command
    "exit_code": int | None,    # Process exit code (None if not started)
    "command": str,             # The command that was executed
    "interrupted": bool,        # Whether execution was interrupted (Ctrl+C)
}
```

**Examples:**

```python
# Success
{
    "success": True,
    "error": None,
    "error_type": None,
    "stdout": "Hello, World!\n",
    "stderr": "",
    "exit_code": 0,
    "command": "echo 'Hello, World!'",
    "interrupted": False,
}

# Command failed (non-zero exit)
{
    "success": False,
    "error": "Command exited with code 1",
    "error_type": "process_error",
    "stdout": "",
    "stderr": "bash: notfound: command not found\n",
    "exit_code": 1,
    "command": "notfound",
    "interrupted": False,
}

# Timeout
{
    "success": False,
    "error": "Command timed out after 30.0s",
    "error_type": "timeout",
    "stdout": "",
    "stderr": "",
    "exit_code": None,
    "command": "sleep 60",
    "interrupted": False,
}

# Interrupted
{
    "success": False,
    "error": "Command interrupted (Ctrl+C)",
    "error_type": "interrupted",
    "stdout": "partial output...",
    "stderr": "",
    "exit_code": -2,
    "command": "long-running-command",
    "interrupted": True,
}
```

---

### 2. IdentityNode

**Purpose:** Echo input unchanged (for testing/debugging)

```python
{
    # Base fields
    "success": bool,
    "error": str | None,
    "error_type": str | None,

    # IdentityNode-specific fields
    "output": str,    # The echoed output (same as input)
    "input": str,     # The original input
}
```

**Examples:**

```python
# Success
{
    "success": True,
    "error": None,
    "error_type": None,
    "output": "hello world",
    "input": "hello world",
}

# Node stopped
{
    "success": False,
    "error": "Node is stopped",
    "error_type": "node_stopped",
    "output": "",
    "input": "",
}
```

---

### 3. PTYNode (Terminal Node)

**Purpose:** Interactive PTY-based terminal with persistent state

```python
{
    # Base fields
    "success": bool,
    "error": str | None,
    "error_type": str | None,

    # PTYNode-specific fields
    "raw": str,                          # Raw terminal output
    "sections": list[dict],              # Parsed sections (if parser enabled)
    "is_ready": bool,                    # Terminal is ready for new input
    "is_complete": bool,                 # Response is complete
    "tokens": int | None,                # Token count (if available from parser)
    "parser": str,                       # Parser type used ("CLAUDE", "NONE", etc.)
}
```

**Section format** (when parser is enabled):

```python
{
    "type": str,           # "thinking", "tool_call", "text", etc.
    "content": str,        # Section content
    "metadata": dict,      # Additional data (tool name, args, etc.)
}
```

**Examples:**

```python
# Success (no parser)
{
    "success": True,
    "error": None,
    "error_type": None,
    "raw": "$ ls\nfile1.txt  file2.txt\n$ ",
    "sections": [],
    "is_ready": True,
    "is_complete": True,
    "tokens": None,
    "parser": "NONE",
}

# Success (with Claude parser)
{
    "success": True,
    "error": None,
    "error_type": None,
    "raw": "∴ Thinking…\n  Let me help.\n⏺ Result\n-- INSERT --",
    "sections": [
        {
            "type": "thinking",
            "content": "Let me help.",
            "metadata": {}
        },
        {
            "type": "text",
            "content": "Result",
            "metadata": {}
        }
    ],
    "is_ready": True,
    "is_complete": True,
    "tokens": 1523,
    "parser": "CLAUDE",
}

# Timeout
{
    "success": False,
    "error": "Terminal did not become ready within 60s",
    "error_type": "timeout",
    "raw": "partial output...",
    "sections": [],
    "is_ready": False,
    "is_complete": False,
    "tokens": None,
    "parser": "NONE",
}

# Node stopped
{
    "success": False,
    "error": "Node is stopped",
    "error_type": "node_stopped",
    "raw": "",
    "sections": [],
    "is_ready": False,
    "is_complete": False,
    "tokens": None,
    "parser": "NONE",
}
```

---

### 4. WezTermNode (Terminal Node)

**Purpose:** WezTerm pane attachment with query-based buffer

Same schema as PTYNode (terminal nodes share schema):

```python
{
    # Base fields
    "success": bool,
    "error": str | None,
    "error_type": str | None,

    # WezTermNode-specific fields (same as PTYNode)
    "raw": str,
    "sections": list[dict],
    "is_ready": bool,
    "is_complete": bool,
    "tokens": int | None,
    "parser": str,
}
```

---

### 5. StatelessLLMNode (OpenRouterNode, GLMNode)

**Purpose:** Single LLM API call (stateless)

```python
{
    # Base fields
    "success": bool,
    "error": str | None,
    "error_type": str | None,

    # StatelessLLMNode-specific fields
    "content": str | None,               # Text response from LLM
    "tool_calls": list[dict] | None,     # Tool calls requested by LLM
    "model": str | None,                 # Model used for generation
    "finish_reason": str | None,         # Why generation stopped ("stop", "length", "tool_calls")
    "usage": dict | None,                # Token usage stats
    "request": dict,                     # Request params (truncated for logging)
    "retries": int,                      # Number of retries performed
}
```

**Usage format:**

```python
{
    "prompt_tokens": int,
    "completion_tokens": int,
    "total_tokens": int,
}
```

**Tool call format:**

```python
{
    "id": str,
    "type": "function",
    "function": {
        "name": str,
        "arguments": dict,
    }
}
```

**Examples:**

```python
# Success (text response)
{
    "success": True,
    "error": None,
    "error_type": None,
    "content": "The answer is 42.",
    "tool_calls": None,
    "model": "anthropic/claude-3.5-sonnet",
    "finish_reason": "stop",
    "usage": {
        "prompt_tokens": 15,
        "completion_tokens": 8,
        "total_tokens": 23
    },
    "request": {"model": "...", "messages": "...(truncated)"},
    "retries": 0,
}

# Success (with tool calls)
{
    "success": True,
    "error": None,
    "error_type": None,
    "content": None,
    "tool_calls": [
        {
            "id": "call_abc123",
            "type": "function",
            "function": {
                "name": "search",
                "arguments": {"query": "Python tutorials"}
            }
        }
    ],
    "model": "anthropic/claude-3.5-sonnet",
    "finish_reason": "tool_calls",
    "usage": {"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
    "request": {"model": "...", "messages": "...(truncated)"},
    "retries": 0,
}

# Rate limit error (with retries)
{
    "success": False,
    "error": "API error (429): Rate limit exceeded",
    "error_type": "rate_limit_error",
    "content": None,
    "tool_calls": None,
    "model": None,
    "finish_reason": None,
    "usage": None,
    "request": {"model": "...", "messages": "...(truncated)"},
    "retries": 3,
}

# Authentication error
{
    "success": False,
    "error": "API error (401): Invalid API key",
    "error_type": "authentication_error",
    "content": None,
    "tool_calls": None,
    "model": None,
    "finish_reason": None,
    "usage": None,
    "request": {"model": "...", "messages": "...(truncated)"},
    "retries": 0,
}

# Timeout
{
    "success": False,
    "error": "Request timed out after 120.0s",
    "error_type": "timeout",
    "content": None,
    "tool_calls": None,
    "model": None,
    "finish_reason": None,
    "usage": None,
    "request": {"model": "...", "messages": "...(truncated)"},
    "retries": 0,
}
```

---

### 6. StatefulLLMNode (Conversational LLM)

**Purpose:** Multi-turn conversation with tool execution

```python
{
    # Base fields
    "success": bool,
    "error": str | None,
    "error_type": str | None,

    # StatefulLLMNode-specific fields
    "content": str | None,           # Text response from LLM
    "tool_calls": list[dict] | None, # Tool calls from final turn
    "usage": dict,                   # Cumulative token usage
    "messages_count": int,           # Total messages in conversation history
    "tool_rounds": int,              # Number of tool execution rounds
}
```

**Examples:**

```python
# Success (text response, no tools)
{
    "success": True,
    "error": None,
    "error_type": None,
    "content": "I've analyzed the data and here are the results...",
    "tool_calls": None,
    "usage": {
        "prompt_tokens": 450,
        "completion_tokens": 125,
        "total_tokens": 575
    },
    "messages_count": 5,
    "tool_rounds": 0,
}

# Success (after tool execution)
{
    "success": True,
    "error": None,
    "error_type": None,
    "content": "Based on the search results, I found 3 relevant papers.",
    "tool_calls": None,
    "usage": {
        "prompt_tokens": 1200,
        "completion_tokens": 320,
        "total_tokens": 1520
    },
    "messages_count": 8,
    "tool_rounds": 2,
}

# Max tool rounds reached
{
    "success": False,
    "error": "Max tool rounds (10) reached",
    "error_type": "internal_error",
    "content": None,
    "tool_calls": [
        {"id": "call_xyz", "type": "function", "function": {"name": "search", "arguments": {...}}}
    ],
    "usage": {
        "prompt_tokens": 5000,
        "completion_tokens": 1500,
        "total_tokens": 6500
    },
    "messages_count": 25,
    "tool_rounds": 10,
}

# Underlying LLM error
{
    "success": False,
    "error": "API error (503): Service temporarily unavailable",
    "error_type": "api_error",
    "content": None,
    "tool_calls": None,
    "usage": {
        "prompt_tokens": 200,
        "completion_tokens": 0,
        "total_tokens": 200
    },
    "messages_count": 3,
    "tool_rounds": 0,
}
```

---

### 7. FunctionNode

**Purpose:** Wrap arbitrary sync/async functions

```python
{
    # Base fields
    "success": bool,
    "error": str | None,
    "error_type": str | None,

    # FunctionNode-specific fields
    "input": str,     # The input provided to the function
    "output": Any,    # The return value from the function (can be any type)
}
```

**Examples:**

```python
# Success (function returned a string)
{
    "success": True,
    "error": None,
    "error_type": None,
    "input": "hello",
    "output": "processed result",
}

# Success (function returned a dict)
{
    "success": True,
    "error": None,
    "error_type": None,
    "input": "test input",
    "output": {"key": "value", "count": 42},
}

# Function raised exception
{
    "success": False,
    "error": "ValueError: invalid input",
    "error_type": "internal_error",
    "input": "invalid data",
    "output": None,
}
```

---

## Implementation Guidelines

### For Node Implementers

All node `execute()` methods should follow this pattern:

```python
async def execute(self, context: ExecutionContext) -> dict[str, Any]:
    """Execute the node - returns dict, never raises exceptions."""

    # Initialize result dict with base fields
    result: dict[str, Any] = {
        "success": False,
        "error": None,
        "error_type": None,
        # ... node-specific fields with default values ...
    }

    # Check if node is stopped
    if self.state == NodeState.STOPPED:
        result["error"] = "Node is stopped"
        result["error_type"] = "node_stopped"
        return result

    try:
        # Execute node logic
        # ...

        # On success
        result["success"] = True
        result["error"] = None
        result["error_type"] = None
        # ... populate node-specific fields ...

    except TimeoutError as e:
        result["error"] = str(e)
        result["error_type"] = "timeout"

    except SpecificException as e:
        result["error"] = str(e)
        result["error_type"] = "specific_error_type"

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["error_type"] = "internal_error"

    return result  # Always return dict, never raise
```

### For Node Callers

```python
# Execute node
result = await node.execute(context)

# Check success
if result["success"]:
    # Handle success - access node-specific fields
    if "stdout" in result:  # BashNode
        print(result["stdout"])
    elif "raw" in result:  # Terminal node
        print(result["raw"])
    elif "content" in result:  # LLM node
        print(result["content"])
else:
    # Handle error
    error_type = result["error_type"]
    error_msg = result["error"]

    if error_type == "timeout":
        print(f"Timed out: {error_msg}")
    elif error_type == "rate_limit_error":
        print(f"Rate limited: {error_msg}")
    else:
        print(f"Error ({error_type}): {error_msg}")
```

---

## Migration Path

### Phase 1: Update Terminal Nodes (PTYNode, WezTermNode)

Convert these nodes to return error dicts instead of raising exceptions:

1. Wrap execute() with try/catch that returns error dict
2. Convert ParsedResponse to dict format
3. Update tests to expect dicts instead of exceptions

### Phase 2: Update Callers

Update code that calls terminal nodes:

1. Commander: Remove try/catch, check `result["success"]` instead
2. Graph execution: Check `result["success"]` for all nodes
3. REPL adapters: Normalize all results to dicts

### Phase 3: Documentation

1. Update API docs with schema
2. Add migration guide for existing code
3. Update examples to use new pattern

---

## Benefits of This Approach

1. **Consistency** - All nodes follow the same pattern
2. **Predictability** - Callers always get a dict
3. **Tool-friendly** - Easy to serialize, log, and pass to tools
4. **Error handling** - Structured errors with types
5. **No surprises** - No hidden exceptions to catch
6. **Composability** - Easy to chain nodes in graphs
7. **Debuggability** - Errors are captured in result for inspection

---

## TypedDict Definitions

For type checking, here are the schemas as TypedDicts:

```python
from typing import TypedDict, Any, Literal

class BaseNodeResult(TypedDict):
    """Base result for all nodes."""
    success: bool
    error: str | None
    error_type: str | None

class BashNodeResult(BaseNodeResult):
    """Result from BashNode execution."""
    stdout: str
    stderr: str
    exit_code: int | None
    command: str
    interrupted: bool

class IdentityNodeResult(BaseNodeResult):
    """Result from IdentityNode execution."""
    output: str
    input: str

class TerminalSection(TypedDict):
    """Parsed section from terminal output."""
    type: str
    content: str
    metadata: dict[str, Any]

class TerminalNodeResult(BaseNodeResult):
    """Result from PTYNode/WezTermNode execution."""
    raw: str
    sections: list[TerminalSection]
    is_ready: bool
    is_complete: bool
    tokens: int | None
    parser: str

class LLMUsage(TypedDict):
    """Token usage from LLM."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class LLMToolCall(TypedDict):
    """Tool call from LLM."""
    id: str
    type: Literal["function"]
    function: dict[str, Any]  # {"name": str, "arguments": dict}

class StatelessLLMResult(BaseNodeResult):
    """Result from StatelessLLMNode execution."""
    content: str | None
    tool_calls: list[LLMToolCall] | None
    model: str | None
    finish_reason: str | None
    usage: LLMUsage | None
    request: dict[str, Any]
    retries: int

class StatefulLLMNodeResult(BaseNodeResult):
    """Result from StatefulLLMNode execution."""
    content: str | None
    tool_calls: list[LLMToolCall] | None
    usage: LLMUsage
    messages_count: int
    tool_rounds: int

class FunctionNodeResult(BaseNodeResult):
    """Result from FunctionNode execution."""
    input: str
    output: Any
```
