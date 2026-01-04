# PRD: MCP Integration for Nerve

## Problem Statement

Nerve currently has various node types (BashNode, ClaudeWezTermNode, LLM nodes, etc.) that can be used as tools by LLM agents. However, there's no way to integrate external MCP (Model Context Protocol) servers into this ecosystem.

Users need to:
1. **Use MCP servers as nodes** - Connect to filesystem, GitHub, Slack, or custom MCP servers
2. **Give LLM agents access to MCP tools** - So agents can call MCP tools alongside existing node tools
3. **Call MCP tools directly from Commander** - Without going through an LLM
4. **Give ClaudeWezTerm access to MCPs** - Pass MCP config so Claude Code can use them natively

---

## High-Level Design

### 1. MCPNode: MCP Servers as Nodes

**Core concept:** 1 MCPNode = 1 MCP server connection

```
Session
├── fs-mcp (MCPNode)        → connects to filesystem MCP server
├── github-mcp (MCPNode)    → connects to GitHub MCP server
├── slack-mcp (MCPNode)     → connects to Slack MCP server
├── bash-1 (BashNode)       → existing single-tool node
└── claude-1 (ClaudeWezTerm)→ existing single-tool node
```

Each MCPNode:
- Maintains connection to its MCP server (persistent/stateful)
- Exposes all tools from that server
- Can be accessed directly from Commander
- Can provide tools to LLM agents

### 2. Unified Tool Protocol

**Breaking change:** The current `ToolCapable` protocol assumes 1 node = 1 tool. This changes to:

**Every node provides a list of tools** (plural covers singular)

| Node | Tools |
|------|-------|
| BashNode | `[bash]` - list of 1 |
| IdentityNode | `[identity]` - list of 1 |
| fs-mcp (MCPNode) | `[read_file, write_file, list_dir]` - list of N |
| github-mcp (MCPNode) | `[create_issue, list_prs, get_repo]` - list of N |

Single-tool nodes are the special case where N=1. No separate protocols.

### 3. Commander UX

**Single-tool nodes** (existing behavior unchanged):
```
@bash-1 ls -la
@claude-1 help me write a function
```

**Multi-tool nodes** (MCP nodes):
```
@fs-mcp read_file {"path": "/tmp/foo.txt"}
@github-mcp create_issue {"title": "Bug", "body": "Details"}
```

**Tool discovery:**
```
@fs-mcp ?                    # List all tools
@fs-mcp read_file ?          # Show tool details
```

### 4. ClaudeWezTerm MCP Passthrough

Claude Code has native MCP support via `--mcp-config`. Nerve passes config at node creation:

```python
ClaudeWezTermNode.create(
    id="claude-with-mcp",
    session=session,
    command="claude --dangerously-skip-permissions",
    mcp_config={
        "filesystem": {
            "command": "npx",
            "args": ["@modelcontextprotocol/server-filesystem", "/tmp"]
        }
    }
)
```

---

## Detailed Requirements

### Part 1: Tool Protocol Changes

#### 1.1 Replace ToolCapable Protocol

**File:** `src/nerve/core/nodes/tools.py`

**Current protocol (to be replaced):**
```python
@runtime_checkable
class ToolCapable(Protocol):
    id: str

    async def execute(self, context: ExecutionContext) -> Any: ...

    def tool_description(self) -> str: ...
    def tool_parameters(self) -> dict[str, Any]: ...
    def tool_input(self, args: dict[str, Any]) -> Any: ...
    def tool_result(self, result: Any) -> str: ...
```

**New protocol:**
```python
@runtime_checkable
class ToolCapable(Protocol):
    """Protocol for nodes that provide tools to LLMs."""

    id: str

    async def execute(self, context: ExecutionContext) -> Any: ...

    def list_tools(self) -> list[ToolDefinition]:
        """Return all tools this node provides.

        Returns:
            List of tool definitions. Single-tool nodes return list of 1.
        """
        ...

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        """Execute a specific tool by name.

        Args:
            name: Tool name (without node prefix).
            args: Tool arguments as dict.

        Returns:
            Tool result as string (for LLM consumption).
        """
        ...
```

#### 1.2 Update ToolDefinition

**File:** `src/nerve/core/nodes/tools.py` (modify existing)

`ToolDefinition` already exists in `tools.py`. Update it to include `node_id`:

```python
@dataclass
class ToolDefinition:
    """Definition of a tool for LLM consumption."""

    name: str                           # Tool name (e.g., "read_file")
    description: str                    # Human-readable description
    parameters: dict[str, Any]          # JSON Schema for parameters
    node_id: str                        # Owning node ID (for routing) - NEW FIELD
```

#### 1.3 Update tools_from_nodes()

**Current behavior:** Extracts single tool per node using old protocol methods.

**New behavior:**
```python
def tools_from_nodes(nodes: list[Node]) -> tuple[list[ToolDefinition], ToolExecutor]:
    """Extract tools from nodes and create executor.

    Args:
        nodes: List of nodes implementing ToolCapable.

    Returns:
        Tuple of (tool definitions for LLM, executor for routing calls).
    """
    tools = []
    node_map = {}  # tool_name -> node

    for node in nodes:
        if not isinstance(node, ToolCapable):
            continue

        for tool in node.list_tools():
            # Prefix tool name with node ID to avoid collisions
            prefixed_name = f"{node.id}.{tool.name}"

            prefixed_tool = ToolDefinition(
                name=prefixed_name,
                description=tool.description,
                parameters=tool.parameters,
                node_id=node.id,
            )
            tools.append(prefixed_tool)
            node_map[prefixed_name] = (node, tool.name)

    async def executor(tool_name: str, args: dict[str, Any]) -> str:
        node, original_name = node_map[tool_name]
        return await node.call_tool(original_name, args)

    return tools, executor
```

#### 1.4 Update Existing Nodes

All nodes implementing the old `ToolCapable` must be updated:

**BashNode** (`src/nerve/core/nodes/bash.py`):
```python
def list_tools(self) -> list[ToolDefinition]:
    return [ToolDefinition(
        name="bash",
        description="Execute a bash command",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute"
                }
            },
            "required": ["command"]
        },
        node_id=self.id,
    )]

async def call_tool(self, name: str, args: dict[str, Any]) -> str:
    # name is "bash", args has "command"
    command = args.get("command", "")
    context = ExecutionContext(input=command)
    result = await self.execute(context)

    if result.get("success"):
        return result.get("output", "")
    else:
        return f"Error: {result.get('error', 'Unknown error')}"
```

**ClaudeWezTermNode** (`src/nerve/core/nodes/terminal/claude_wezterm_node.py`):
```python
def list_tools(self) -> list[ToolDefinition]:
    return [ToolDefinition(
        name="ask_claude",
        description="Ask Claude (another AI assistant) for help, opinions, or to perform tasks",
        parameters={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message or question to send to Claude"
                }
            },
            "required": ["message"]
        },
        node_id=self.id,
    )]

async def call_tool(self, name: str, args: dict[str, Any]) -> str:
    # name is "ask_claude", args has "message"
    message = args.get("message", "")
    context = ExecutionContext(input=message)
    result = await self.execute(context)

    # Return last text section (filters thinking blocks)
    sections = result.get("attributes", {}).get("sections", [])
    text_sections = [s for s in sections if s.get("type") == "text"]
    if text_sections:
        return text_sections[-1].get("content", "")
    return "(no response)"
```

**Other nodes to update:**
- `IdentityNode` (if ToolCapable)
- Any other nodes implementing old ToolCapable

**Remove old methods** from all updated nodes:
- `tool_description()`
- `tool_parameters()`
- `tool_input()`
- `tool_result()`

#### 1.5 Add ERROR State to NodeState Enum

**File:** `src/nerve/core/nodes/base.py`

Add `ERROR` to the `NodeState` enum:

```python
class NodeState(Enum):
    """Lifecycle states for nodes."""
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    BUSY = "busy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"      # NEW: Unrecoverable error state
```

**Semantics:**
- `ERROR` indicates an unrecoverable failure (MCP server crashed, connection lost)
- Node cannot transition out of `ERROR` except via `stop()` → `STOPPED`
- User must delete and recreate the node to recover
- `to_info()` should include error details in metadata when in ERROR state

**Transition diagram update:**
```
CREATED → STARTING → READY ↔ BUSY → STOPPING → STOPPED
                ↓                        ↑
              ERROR ─────────────────────┘
                     (via stop() only)
```

---

### Part 2: MCPNode Implementation

#### 2.1 MCPNode Class

**File:** `src/nerve/core/nodes/mcp/mcp_node.py` (new file)

```python
@dataclass
class MCPNode:
    """Node that wraps an MCP server connection.

    IMPORTANT: Cannot be instantiated directly. Use MCPNode.create() instead.

    Each MCPNode maintains a connection to one MCP server and exposes
    all tools from that server. Tools can be called directly from Commander
    or provided to LLM agents.

    Example:
        >>> node = await MCPNode.create(
        ...     id="fs-mcp",
        ...     session=session,
        ...     command="npx",
        ...     args=["@modelcontextprotocol/server-filesystem", "/tmp"],
        ... )
        >>> result = await node.call_tool("read_file", {"path": "/tmp/foo.txt"})
    """

    # Required fields
    id: str
    session: Session

    # MCP connection config
    _command: str                                    # Command to launch MCP server
    _args: list[str]                                 # Command arguments
    _env: dict[str, str] | None                      # Environment variables
    _cwd: str | None                                 # Working directory

    # Internal state
    persistent: bool = field(default=True, init=False)
    state: NodeState = field(default=NodeState.CREATED, init=False)
    _tools: list[ToolDefinition] = field(default_factory=list, init=False)
    _client: MCPClient | None = field(default=None, init=False)
    _created_via_create: bool = field(default=False, init=False)
    _error_message: str | None = field(default=None, init=False)  # Set when state=ERROR
```

#### 2.2 MCPNode.create() Factory

```python
@classmethod
async def create(
    cls,
    id: str,
    session: Session,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> MCPNode:
    """Create and connect an MCP node.

    Args:
        id: Unique node identifier.
        session: Session to register with.
        command: Command to launch MCP server (e.g., "npx", "python").
        args: Command arguments (e.g., ["@modelcontextprotocol/server-filesystem", "/tmp"]).
        env: Environment variables for MCP server process.
        cwd: Working directory for MCP server process.

    Returns:
        Connected MCPNode with tools discovered.

    Raises:
        ValueError: If id already exists or is invalid.
        MCPConnectionError: If connection to MCP server fails.
    """
    # 1. Validate
    validate_name(id, "node")
    session.validate_unique_id(id, "node")

    # 2. Create instance
    node = object.__new__(cls)
    node._created_via_create = True
    node.id = id
    node.session = session
    node._command = command
    node._args = args or []
    node._env = env
    node._cwd = cwd
    node.persistent = True
    node.state = NodeState.STARTING
    node._tools = []
    node._client = None

    # 3. Connect to MCP server
    try:
        node._client = await MCPClient.connect(
            command=command,
            args=args or [],
            env=env,
            cwd=cwd,
        )

        # 4. Discover tools
        mcp_tools = await node._client.list_tools()
        node._tools = [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters=tool.input_schema,
                node_id=id,
            )
            for tool in mcp_tools
        ]

        node.state = NodeState.READY
        session.nodes[id] = node
        return node

    except Exception:
        if node._client:
            await node._client.close()
        raise
```

#### 2.3 MCPNode Lifecycle Methods

```python
async def start(self) -> None:
    """Start the node (reconnect if disconnected)."""
    if self.state == NodeState.READY:
        return

    if self._client is None:
        self._client = await MCPClient.connect(
            command=self._command,
            args=self._args,
            env=self._env,
            cwd=self._cwd,
        )

        # Re-discover tools
        mcp_tools = await self._client.list_tools()
        self._tools = [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters=tool.input_schema,
                node_id=self.id,
            )
            for tool in mcp_tools
        ]

    self.state = NodeState.READY

async def stop(self) -> None:
    """Stop the node and close MCP connection."""
    if self._client:
        await self._client.close()
        self._client = None
    self.state = NodeState.STOPPED

async def interrupt(self) -> None:
    """Interrupt any running operation."""
    # MCP doesn't have interrupt - operations complete or timeout
    pass
```

#### 2.4 MCPNode Tool Interface

```python
def list_tools(self) -> list[ToolDefinition]:
    """Return all tools from this MCP server."""
    return self._tools.copy()

async def call_tool(self, name: str, args: dict[str, Any]) -> str:
    """Call a specific tool on the MCP server.

    Args:
        name: Tool name (e.g., "read_file").
        args: Tool arguments.

    Returns:
        Tool result as string.

    Raises:
        ValueError: If tool not found.
        MCPError: If tool execution fails.
        RuntimeError: If node is in ERROR state.
    """
    if self.state == NodeState.ERROR:
        raise RuntimeError(f"Node {self.id} is in ERROR state. Delete and recreate.")

    if self.state != NodeState.READY:
        raise RuntimeError(f"Node {self.id} is not ready (state: {self.state})")

    if not any(t.name == name for t in self._tools):
        available = [t.name for t in self._tools]
        raise ValueError(f"Tool '{name}' not found. Available: {available}")

    self.state = NodeState.BUSY
    try:
        result = await self._client.call_tool(name, args)
        return self._format_result(result)
    except MCPConnectionError as e:
        # Connection lost - transition to ERROR state
        self.state = NodeState.ERROR
        self._error_message = str(e)
        raise
    finally:
        if self.state == NodeState.BUSY:
            self.state = NodeState.READY

def _format_result(self, result: Any) -> str:
    """Format MCP tool result as string for LLM consumption."""
    if isinstance(result, str):
        return result
    elif isinstance(result, dict):
        return json.dumps(result, indent=2)
    elif isinstance(result, list):
        return json.dumps(result, indent=2)
    else:
        return str(result)
```

#### 2.5 MCPNode Execute (for Commander)

```python
async def execute(self, context: ExecutionContext) -> dict[str, Any]:
    """Execute a tool call from Commander.

    context.input should be a dict with:
    - tool: str - Tool name
    - args: dict - Tool arguments

    Or for simple single-arg tools, context.input can be the arg directly.
    """
    input_data = context.input

    if isinstance(input_data, dict):
        tool_name = input_data.get("tool")
        tool_args = input_data.get("args", {})
    else:
        # Shouldn't happen with proper Commander parsing
        return {
            "success": False,
            "error": "Input must be dict with 'tool' and 'args'",
            "error_type": "invalid_input",
            "node_type": "mcp",
            "node_id": self.id,
            "input": str(input_data),
            "output": None,
        }

    try:
        result = await self.call_tool(tool_name, tool_args)
        return {
            "success": True,
            "error": None,
            "error_type": None,
            "node_type": "mcp",
            "node_id": self.id,
            "input": input_data,
            "output": result,
            "attributes": {
                "tool": tool_name,
                "args": tool_args,
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "node_type": "mcp",
            "node_id": self.id,
            "input": input_data,
            "output": None,
        }
```

#### 2.6 MCPClient (Low-Level MCP Protocol)

**File:** `src/nerve/core/mcp/client.py` (new file)

This handles the actual MCP protocol communication. For V1, support **stdio transport only**.

**Implementation Notes:**

1. **Message Framing:** MCP over stdio uses newline-delimited JSON (one JSON object per line).
   This is the standard for most MCP server implementations. If issues arise with specific
   servers using content-length headers (LSP-style), this can be addressed in a future version.

2. **Request ID Management:** V1 uses a simple incrementing counter for request IDs.
   Operations are serialized (one at a time), so concurrent ID collision is not a concern.
   For future concurrent operations, use `asyncio.Lock` or atomic counter.

```python
@dataclass
class MCPClient:
    """Low-level MCP protocol client.

    Handles stdio transport to MCP servers.
    """

    _process: asyncio.subprocess.Process
    _reader: asyncio.StreamReader
    _writer: asyncio.StreamWriter
    _request_id: int = field(default=0, init=False)  # Incrementing request ID

    def _next_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    @classmethod
    async def connect(
        cls,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> MCPClient:
        """Launch MCP server process and establish connection."""
        # Launch subprocess with stdio
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **(env or {})},
            cwd=cwd,
        )

        client = cls(
            _process=process,
            _reader=process.stdout,
            _writer=process.stdin,
        )

        # Initialize MCP handshake
        await client._initialize()

        return client

    async def _initialize(self) -> None:
        """Perform MCP initialization handshake."""
        # Send initialize request
        await self._send({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "nerve",
                    "version": "0.1.0"
                }
            }
        })

        # Wait for response
        response = await self._receive()

        # Send initialized notification
        await self._send({
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        })

    async def list_tools(self) -> list[MCPToolInfo]:
        """Get list of available tools from server."""
        await self._send({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {}
        })

        response = await self._receive()
        tools = response.get("result", {}).get("tools", [])

        return [
            MCPToolInfo(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call a tool on the MCP server."""
        await self._send({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": args
            }
        })

        response = await self._receive()

        if "error" in response:
            raise MCPError(response["error"].get("message", "Unknown error"))

        # Extract content from result
        content = response.get("result", {}).get("content", [])
        if content and len(content) > 0:
            return content[0].get("text", "")
        return ""

    async def close(self) -> None:
        """Close the MCP connection."""
        self._writer.close()
        self._process.terminate()
        await self._process.wait()

    async def _send(self, message: dict) -> None:
        """Send JSON-RPC message."""
        data = json.dumps(message)
        self._writer.write(f"{data}\n".encode())
        await self._writer.drain()

    async def _receive(self) -> dict:
        """Receive JSON-RPC message."""
        line = await self._reader.readline()
        return json.loads(line.decode())


@dataclass
class MCPToolInfo:
    """Tool information from MCP server."""
    name: str
    description: str
    input_schema: dict[str, Any]


class MCPError(Exception):
    """Error from MCP server (tool execution failed)."""
    pass


class MCPConnectionError(MCPError):
    """Error connecting to or communicating with MCP server."""
    pass
```

---

### Part 3: NodeFactory Integration

**File:** `src/nerve/server/factories/node_factory.py`

#### 3.1 Add MCP to Valid Backends

```python
VALID_BACKENDS = (
    "pty", "wezterm", "claude-wezterm",
    "bash", "identity",
    "openrouter", "glm", "llm-chat", "suggestion",
    "mcp",  # NEW
)
```

#### 3.2 Add MCP Creation Logic

In `create()` method, add new elif branch:

```python
elif backend == "mcp":
    if not command:
        raise ValueError("MCP backend requires 'command' parameter")

    from nerve.core.nodes.mcp.mcp_node import MCPNode

    return await MCPNode.create(
        id=node_id,
        session=session,
        command=command,
        args=mcp_args,      # New parameter
        env=mcp_env,        # New parameter
        cwd=cwd,
    )
```

#### 3.3 Add Factory Parameters

Add new parameters to `create()` signature:

```python
async def create(
    backend: str,
    session: Session,
    node_id: str,
    command: str | list[str] | None = None,
    # ... existing params ...
    mcp_args: list[str] | None = None,      # NEW: MCP server args
    mcp_env: dict[str, str] | None = None,  # NEW: MCP server env vars
) -> Node:
```

---

### Part 4: Commander Integration

#### 4.1 Multi-Tool Node Detection

Commander needs to detect whether a node has multiple tools to choose correct parsing:

```python
def is_multi_tool_node(node: Node) -> bool:
    """Check if node has multiple tools."""
    if isinstance(node, ToolCapable):
        return len(node.list_tools()) > 1
    return False
```

#### 4.2 Help Command Handling

**IMPORTANT:** Help is handled in the **Commander dispatcher**, BEFORE calling `node.execute()`.

The flow for help commands:
```
@fs-mcp ?           → Commander detects "?"
                    → Commander calls node.list_tools()
                    → Commander renders help output
                    → NEVER calls node.execute()

@fs-mcp read_file ? → Commander detects "tool ?" pattern
                    → Commander finds tool in node.list_tools()
                    → Commander renders tool-specific help
                    → NEVER calls node.execute()

@fs-mcp read_file {"path": "..."} → Commander parses JSON
                                  → Commander calls node.execute() or node.call_tool()
```

**Commander dispatcher logic:**
```python
def handle_node_command(node: Node, raw_input: str) -> str | None:
    """Handle @ command for a node. Returns help text or None to continue."""

    raw_input = raw_input.strip()

    # Check for help on multi-tool nodes
    if is_multi_tool_node(node):
        if raw_input == "?":
            return render_node_tools_help(node)

        parts = raw_input.split(None, 1)
        if len(parts) == 2 and parts[1].strip() == "?":
            tool_name = parts[0]
            return render_tool_help(node, tool_name)

    # Not a help command - continue to execution
    return None
```

#### 4.3 Command Parsing (for execution)

**Single-tool nodes:**
```
@bash-1 ls -la
         ^^^^^^ entire string is input
```

**Multi-tool nodes:**
```
@fs-mcp read_file {"path": "/tmp/foo.txt"}
        ^^^^^^^^^ ^^^^^^^^^^^^^^^^^^^^^^^^
        tool name  JSON args
```

Parsing logic (called after help handling):
```python
def parse_node_command(node: Node, raw_input: str) -> ExecutionContext:
    """Parse command for node execution.

    Note: Help commands (?) are already handled by dispatcher before this.
    """

    if not is_multi_tool_node(node):
        # Single-tool: entire input goes to the tool
        return ExecutionContext(input=raw_input)

    # Multi-tool: first token is tool name, rest is JSON args
    parts = raw_input.strip().split(None, 1)

    if len(parts) == 0:
        raise ValueError("No tool specified. Use: @{node.id} ? to list tools")

    tool_name = parts[0]

    if len(parts) == 1:
        # No args provided
        raise ValueError(f"No arguments for tool '{tool_name}'. Use: @{node.id} {tool_name} {{...}}")

    args_str = parts[1]

    # Parse JSON args
    try:
        args = json.loads(args_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON arguments: {e}")

    return ExecutionContext(input={"tool": tool_name, "args": args})
```

#### 4.4 Help Display Rendering

**List all tools (`@fs-mcp ?`):**
```
fs-mcp tools:
  read_file    - Read contents of a file
  write_file   - Write contents to a file
  list_dir     - List directory contents

Usage: @fs-mcp <tool> {"arg": "value"}
```

**Tool details (`@fs-mcp read_file ?`):**
```
read_file - Read contents of a file

Parameters:
  path (string, required) - Path to the file to read
  encoding (string, optional) - File encoding, default: utf-8

Example: @fs-mcp read_file {"path": "/tmp/foo.txt"}
```

---

### Part 5: ClaudeWezTermNode MCP Passthrough

**File:** `src/nerve/core/nodes/terminal/claude_wezterm_node.py`

#### 5.1 Add MCP Parameters to create()

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
    claude_session_id: str | None = None,
    mcp_config: dict[str, Any] | None = None,      # NEW
    strict_mcp_config: bool = False,                # NEW
) -> ClaudeWezTermNode:
```

#### 5.2 Add Instance Fields

```python
_mcp_config: dict[str, Any] | None = field(default=None, init=False)
_mcp_config_path: Path | None = field(default=None, init=False)
```

#### 5.3 MCP Config Handling in create()

After session ID handling (around line 200), add:

```python
# Handle MCP config
mcp_config_path = None
if mcp_config:
    import tempfile
    import uuid as uuid_module

    # Write config to temp file
    config_filename = f"nerve-mcp-{id}-{uuid_module.uuid4().hex[:8]}.json"
    mcp_config_path = Path(tempfile.gettempdir()) / config_filename

    # Wrap in mcpServers format
    full_config = {"mcpServers": mcp_config}

    with open(mcp_config_path, "w") as f:
        json.dump(full_config, f, indent=2)

    # Append to command
    command = f"{command} --mcp-config {mcp_config_path}"

    if strict_mcp_config:
        command = f"{command} --strict-mcp-config"

    logger.debug(f"MCP config written to {mcp_config_path} for node '{id}'")
```

#### 5.4 Store Fields on Wrapper

```python
wrapper._mcp_config = mcp_config
wrapper._mcp_config_path = mcp_config_path
```

#### 5.5 Cleanup in stop()

```python
async def stop(self) -> None:
    """Stop the node and release resources."""
    # ... existing cleanup ...

    # Clean up MCP config temp file
    if self._mcp_config_path and self._mcp_config_path.exists():
        try:
            self._mcp_config_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete MCP config file {self._mcp_config_path}: {e}")

    # ... rest of stop() ...
```

#### 5.6 Include in to_info()

```python
def to_info(self) -> NodeInfo:
    metadata: dict[str, str | float | None] = {
        # ... existing fields ...
    }
    if self._mcp_config:
        metadata["mcp_servers"] = list(self._mcp_config.keys())
    # ...
```

---

### Part 6: File Structure

New files to create:
```
src/nerve/core/mcp/
├── __init__.py
├── client.py           # MCPClient - low-level protocol
└── errors.py           # MCPError, MCPConnectionError

src/nerve/core/nodes/mcp/
├── __init__.py
└── mcp_node.py         # MCPNode class
```

Files to modify:
```
src/nerve/core/nodes/tools.py              # ToolCapable protocol
src/nerve/core/nodes/bash.py               # Update to new protocol
src/nerve/core/nodes/terminal/claude_wezterm_node.py  # MCP passthrough + update protocol
src/nerve/server/factories/node_factory.py # Add mcp backend
```

---

## Testing Requirements

### Unit Tests

1. **ToolCapable Protocol Tests**
   - Single-tool node returns list of 1
   - Multi-tool node returns list of N
   - call_tool routes correctly
   - tools_from_nodes prefixes correctly

2. **MCPNode Tests**
   - Creation and connection
   - Tool discovery
   - Tool execution
   - Error handling (connection failure, tool not found)
   - Lifecycle (start, stop, reconnect)
   - ERROR state transition on connection failure

3. **MCPClient Tests**
   - Stdio communication
   - JSON-RPC message format
   - Initialize handshake
   - Tool list parsing
   - Tool call and response
   - Request ID incrementing

**Mock MCP Server for Unit Tests:**

Create a simple mock MCP server script for testing (`tests/fixtures/mock_mcp_server.py`):

```python
#!/usr/bin/env python3
"""Mock MCP server for unit testing."""
import json
import sys

MOCK_TOOLS = [
    {"name": "test_tool", "description": "A test tool", "inputSchema": {"type": "object"}},
    {"name": "echo", "description": "Echo input", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
]

def handle_request(request: dict) -> dict | None:
    method = request.get("method")
    req_id = request.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05"}}
    elif method == "notifications/initialized":
        return None  # Notification, no response
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MOCK_TOOLS}}
    elif method == "tools/call":
        name = request.get("params", {}).get("name")
        args = request.get("params", {}).get("arguments", {})
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"Called {name} with {args}"}]}}
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}

if __name__ == "__main__":
    for line in sys.stdin:
        request = json.loads(line)
        response = handle_request(request)
        if response:
            print(json.dumps(response), flush=True)
```

Use in tests:
```python
node = await MCPNode.create(
    id="test-mcp",
    session=session,
    command="python",
    args=["tests/fixtures/mock_mcp_server.py"],
)
```

4. **ClaudeWezTermNode MCP Tests**
   - Config file creation
   - Config file cleanup on stop
   - Command includes --mcp-config flag
   - strict_mcp_config flag

5. **Commander Tests**
   - Multi-tool detection (`is_multi_tool_node()`)
   - JSON argument parsing
   - Help command detection (`@node ?`)
   - Tool-specific help detection (`@node tool ?`)
   - Help rendering for node tools list
   - Help rendering for individual tool details
   - Error handling for invalid JSON
   - Error handling for missing tool name

### Integration Tests

1. **MCP Server Integration**
   - Connect to real MCP server (e.g., filesystem)
   - Call actual tools
   - Handle server crash/restart

2. **LLM + MCP Tools**
   - StatefulLLMNode with MCP tools
   - Tool calls routed correctly
   - Results returned to LLM

---

## Rollout Plan

### Phase 1: Tool Protocol (Breaking Change)
1. Update ToolCapable protocol
2. Update BashNode, ClaudeWezTermNode
3. Update tools_from_nodes()
4. Update any consumers of old protocol

### Phase 2: MCPNode
1. Implement MCPClient (stdio)
2. Implement MCPNode
3. Add to NodeFactory
4. Write tests

### Phase 3: Commander Integration
1. Multi-tool detection
2. JSON argument parsing
3. Help commands
4. Update documentation

### Phase 4: ClaudeWezTermNode MCP
1. Add mcp_config parameter
2. Temp file handling
3. Cleanup on stop
4. Write tests

---

## Open Questions

1. **MCP Server Crash Recovery**: Should MCPNode auto-reconnect? Or require manual restart?
   - **Recommendation**: V1 - no auto-reconnect, go to ERROR state. User must delete and recreate.

2. **Tool Name Conflicts**: What if MCP server has tool named same as node method (e.g., "stop")?
   - **Recommendation**: MCP tools are namespaced by call_tool(), no conflict with node methods.

3. **Async Tool Calls**: Some MCP tools may be slow. Timeout handling?
   - **Recommendation**: Use context.timeout, default 30s for MCP tools.

4. **MCP Resources/Prompts**: Support in V1?
   - **Recommendation**: No. Tools only for V1. Resources/prompts in future version.
