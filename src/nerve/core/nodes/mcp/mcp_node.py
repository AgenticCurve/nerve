"""MCPNode - node that wraps an MCP server connection.

MCPNode connects to an MCP server via stdio and exposes all tools
from that server. Tools can be called directly from Commander or
provided to LLM agents via the ToolCapable protocol.

Key features:
- Multi-tool node: exposes all tools from MCP server
- Stateful: maintains persistent connection to MCP server
- Factory pattern: use MCPNode.create() to instantiate
- Error recovery: transitions to ERROR state on connection loss
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.core.mcp import MCPClient, MCPConnectionError
from nerve.core.nodes.base import NodeInfo, NodeState

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.nodes.tools import ToolDefinition
    from nerve.core.session.session import Session


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
        >>> tools = node.list_tools()  # Multiple tools!
        >>> result = await node.call_tool("read_file", {"path": "/tmp/foo.txt"})
        >>> await node.stop()
    """

    # Required fields (set during .create())
    id: str
    session: Session

    # MCP connection config
    _command: str = ""
    _args: list[str] = field(default_factory=list)
    _env: dict[str, str] | None = None
    _cwd: str | None = None
    _timeout: float = 30.0

    # Internal state
    persistent: bool = field(default=True, init=False)
    state: NodeState = field(default=NodeState.CREATED, init=False)
    _tools: list[ToolDefinition] = field(default_factory=list, init=False)
    _client: MCPClient | None = field(default=None, init=False, repr=False)
    _created_via_create: bool = field(default=False, init=False, repr=False)
    _error_message: str | None = field(default=None, init=False)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Prevent direct instantiation."""
        if not self._created_via_create:
            raise TypeError(
                f"Cannot instantiate {self.__class__.__name__} directly. "
                f"Use: await {self.__class__.__name__}.create(id, session, command, ...)"
            )

    @classmethod
    async def create(
        cls,
        id: str,
        session: Session,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = 30.0,
    ) -> MCPNode:
        """Create and connect an MCP node.

        Args:
            id: Unique node identifier.
            session: Session to register with.
            command: Command to launch MCP server (e.g., "npx", "python").
            args: Command arguments (e.g., ["@modelcontextprotocol/server-filesystem", "/tmp"]).
            env: Environment variables for MCP server process.
            cwd: Working directory for MCP server process.
            timeout: Timeout for MCP operations in seconds.

        Returns:
            Connected MCPNode with tools discovered.

        Raises:
            ValueError: If id already exists or is invalid.
            MCPConnectionError: If connection to MCP server fails.
        """
        from nerve.core.nodes.tools import ToolDefinition
        from nerve.core.validation import validate_name

        # Validate
        validate_name(id, "node")
        session.validate_unique_id(id, "node")

        # Create instance (bypass __post_init__ check)
        node = object.__new__(cls)
        node._created_via_create = True
        node.id = id
        node.session = session
        node._command = command
        node._args = args or []
        node._env = env
        node._cwd = cwd
        node._timeout = timeout
        node.persistent = True
        node.state = NodeState.STARTING
        node._tools = []
        node._client = None
        node._error_message = None
        node.metadata = {}

        # Connect to MCP server
        try:
            node._client = await MCPClient.connect(
                command=command,
                args=args,
                env=env,
                cwd=cwd,
                timeout=timeout,
            )

            # Discover tools
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

            # Register with session
            session.nodes[id] = node

            # Log node registration
            if session.session_logger:
                session.session_logger.log_node_lifecycle(
                    id,
                    "MCPNode",
                    persistent=True,
                    started=True,
                    command=command,
                )

            return node

        except Exception:
            # Cleanup on failure
            if node._client:
                await node._client.close()
            raise

    # -------------------------------------------------------------------------
    # Lifecycle methods
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the node (reconnect if disconnected).

        If already in READY state, does nothing.
        If in ERROR or STOPPED state, attempts to reconnect.

        Raises:
            MCPConnectionError: If connection fails (node transitions to ERROR state).
        """
        from nerve.core.nodes.tools import ToolDefinition

        if self.state == NodeState.READY:
            return

        try:
            if self._client is None:
                self.state = NodeState.STARTING
                self._client = await MCPClient.connect(
                    command=self._command,
                    args=self._args,
                    env=self._env,
                    cwd=self._cwd,
                    timeout=self._timeout,
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
            self._error_message = None
        except Exception as e:
            self.state = NodeState.ERROR
            self._error_message = str(e)
            if self._client:
                await self._client.close()
                self._client = None
            raise

    async def stop(self) -> None:
        """Stop the node and close MCP connection."""
        if self._client:
            await self._client.close()
            self._client = None
        self.state = NodeState.STOPPED

        # Log node stopped
        if self.session and self.session.session_logger:
            self.session.session_logger.log_node_stopped(self.id, reason="stopped")

    async def interrupt(self) -> None:
        """Interrupt any running operation.

        MCP doesn't have interrupt - operations complete or timeout.
        """

    # -------------------------------------------------------------------------
    # Tool interface (ToolCapable protocol)
    # -------------------------------------------------------------------------

    def list_tools(self) -> list[ToolDefinition]:
        """Return all tools from this MCP server.

        Returns:
            List of ToolDefinition objects for all discovered tools.
        """
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
            RuntimeError: If node is in ERROR state or not ready.
            MCPConnectionError: If connection to server is lost.
        """
        if self.state == NodeState.ERROR:
            raise RuntimeError(
                f"Node '{self.id}' is in ERROR state: {self._error_message}. "
                "Delete and recreate the node to recover."
            )

        if self.state != NodeState.READY:
            raise RuntimeError(f"Node '{self.id}' is not ready (state: {self.state.name})")

        if not any(t.name == name for t in self._tools):
            available = [t.name for t in self._tools]
            raise ValueError(f"Tool '{name}' not found. Available: {available}")

        if self._client is None:
            raise RuntimeError(f"Node '{self.id}' has no MCP connection")

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
        """Format MCP tool result as string for LLM consumption.

        Args:
            result: Raw result from MCP server.

        Returns:
            String representation of result.
        """
        if isinstance(result, str):
            return result
        elif isinstance(result, (dict, list)):
            return json.dumps(result, indent=2)
        else:
            return str(result)

    # -------------------------------------------------------------------------
    # Execute (for Commander)
    # -------------------------------------------------------------------------

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Execute a tool call from Commander.

        context.input should be either:
        - A dict with 'tool' and 'args' keys
        - A JSON string that parses to such a dict

        Args:
            context: Execution context with tool call in input.

        Returns:
            Dict with standardized result fields.
        """
        input_data = context.input

        # Parse JSON string to dict if needed
        if isinstance(input_data, str):
            try:
                input_data = json.loads(input_data)
            except json.JSONDecodeError as e:
                return {
                    "success": False,
                    "error": f"Invalid JSON input: {e}",
                    "error_type": "invalid_input",
                    "node_type": "mcp",
                    "node_id": self.id,
                    "input": context.input,
                    "output": None,
                    "attributes": {},
                }

        # Validate input format
        if not isinstance(input_data, dict):
            return {
                "success": False,
                "error": "Input must be dict with 'tool' and 'args' keys",
                "error_type": "invalid_input",
                "node_type": "mcp",
                "node_id": self.id,
                "input": str(context.input),
                "output": None,
                "attributes": {},
            }

        tool_name = input_data.get("tool")
        tool_args = input_data.get("args", {})

        if not tool_name:
            return {
                "success": False,
                "error": "Missing 'tool' key in input",
                "error_type": "invalid_input",
                "node_type": "mcp",
                "node_id": self.id,
                "input": input_data,
                "output": None,
                "attributes": {},
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
                },
            }
        except ValueError as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": "tool_not_found",
                "node_type": "mcp",
                "node_id": self.id,
                "input": input_data,
                "output": None,
                "attributes": {"tool": tool_name},
            }
        except RuntimeError as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": "node_error",
                "node_type": "mcp",
                "node_id": self.id,
                "input": input_data,
                "output": None,
                "attributes": {"tool": tool_name},
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
                "attributes": {"tool": tool_name},
            }

    # -------------------------------------------------------------------------
    # Node info
    # -------------------------------------------------------------------------

    def to_info(self) -> NodeInfo:
        """Get node information.

        Returns:
            NodeInfo for this node.
        """
        metadata: dict[str, Any] = {
            "command": self._command,
            "args": self._args,
            "tool_count": len(self._tools),
            "tools": [t.name for t in self._tools],
            **self.metadata,
        }

        if self._cwd:
            metadata["cwd"] = self._cwd

        if self._error_message:
            metadata["error"] = self._error_message

        return NodeInfo(
            id=self.id,
            node_type="mcp",
            state=self.state,
            persistent=self.persistent,
            metadata=metadata,
        )

    def __repr__(self) -> str:
        tool_count = len(self._tools)
        return f"MCPNode(id={self.id!r}, state={self.state.name}, tools={tool_count})"
