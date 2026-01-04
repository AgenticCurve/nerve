"""Node-as-Tool adapter - expose tool-capable nodes to StatefulLLMNode.

This module provides utilities to expose nodes as tools that StatefulLLMNode
can use. Nodes opt-in to being tools by implementing the ToolCapable protocol.

A node becomes tool-capable by defining two methods:
- list_tools(): Return list of ToolDefinition objects
- call_tool(name, args): Execute a specific tool and return result string

This design supports both single-tool nodes (N=1) and multi-tool nodes (N>1)
like MCP servers which expose multiple tools from a single connection.

Example:
    >>> bash = BashNode(id="bash", session=session)
    >>> terminal = PTYNode.create(id="term", session=session, command="zsh")
    >>>
    >>> # Only tool-capable nodes are included
    >>> tools, executor = tools_from_nodes([bash, terminal])
    >>>
    >>> agent = StatefulLLMNode(
    ...     id="agent",
    ...     session=session,
    ...     llm=llm,
    ...     system="You can run commands using the bash tool.",
    ...     tools=tools,
    ...     tool_executor=executor,
    ... )
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from nerve.core.nodes.context import ExecutionContext
from nerve.core.nodes.run_logging import log_complete, log_error, log_start

if TYPE_CHECKING:
    from nerve.core.nodes.llm.chat import ToolExecutor


# ---------------------------------------------------------------------------
# Tool Definition
# ---------------------------------------------------------------------------


@dataclass
class ToolDefinition:
    """Definition of a tool for LLM consumption.

    Used by both single-tool nodes (like BashNode) and multi-tool nodes
    (like MCPNode) to describe their available tools.

    Attributes:
        name: Tool name (e.g., "read_file", "bash").
        description: Human-readable description for LLM.
        parameters: JSON Schema for tool parameters.
        node_id: Owning node ID for routing tool calls.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    node_id: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to API-compatible dict (OpenAI format)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ---------------------------------------------------------------------------
# Protocol Definition
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolCapable(Protocol):
    """Protocol for nodes that provide tools to LLMs.

    Nodes implement this protocol to opt-in to being available as tools
    for StatefulLLMNode. The protocol requires two methods:
    - list_tools(): Return all tools this node provides
    - call_tool(name, args): Execute a specific tool by name

    This design supports both single-tool nodes (N=1) and multi-tool nodes
    (N>1, like MCP servers).

    Example implementation (single-tool node):
        class BashNode:
            def list_tools(self) -> list[ToolDefinition]:
                return [ToolDefinition(
                    name="bash",
                    description="Execute bash/shell commands",
                    parameters={
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "The command"},
                        },
                        "required": ["command"],
                    },
                    node_id=self.id,
                )]

            async def call_tool(self, name: str, args: dict[str, Any]) -> str:
                result = await self.execute(ExecutionContext(input=args["command"]))
                return result.get("output", "")

    Example implementation (multi-tool node like MCPNode):
        class MCPNode:
            def list_tools(self) -> list[ToolDefinition]:
                return self._tools  # Multiple tools from MCP server

            async def call_tool(self, name: str, args: dict[str, Any]) -> str:
                return await self._mcp_client.call_tool(name, args)
    """

    id: str

    def list_tools(self) -> list[ToolDefinition]:
        """Return all tools this node provides.

        Single-tool nodes return a list of 1. Multi-tool nodes (like MCP)
        return multiple tools.

        Returns:
            List of ToolDefinition objects describing available tools.
        """
        ...

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        """Execute a specific tool by name.

        Args:
            name: Tool name (without node prefix).
            args: Tool arguments as dict.

        Returns:
            Tool result as string (for LLM consumption).

        Raises:
            ValueError: If tool name not found.
        """
        ...


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------


def is_tool_capable(node: Any) -> bool:
    """Check if a node implements the ToolCapable protocol.

    Args:
        node: Any object to check.

    Returns:
        True if node has list_tools() and call_tool() methods.
    """
    return isinstance(node, ToolCapable)


def is_multi_tool_node(node: Any) -> bool:
    """Check if a node has multiple tools.

    Useful for Commander to determine parsing behavior:
    - Single-tool nodes: entire input goes to the tool
    - Multi-tool nodes: first token is tool name, rest is JSON args

    Args:
        node: Any node object.

    Returns:
        True if node is tool-capable and has more than one tool.
    """
    if not is_tool_capable(node):
        return False
    return len(node.list_tools()) > 1


# ---------------------------------------------------------------------------
# Result Truncation
# ---------------------------------------------------------------------------

DEFAULT_MAX_RESULT_LENGTH = 50_000  # 50KB max result size


def truncate_result(result: str, max_length: int = DEFAULT_MAX_RESULT_LENGTH) -> str:
    """Truncate result string if too long.

    Args:
        result: Result string to potentially truncate.
        max_length: Maximum allowed length.

    Returns:
        Original or truncated string with indicator.
    """
    if len(result) <= max_length:
        return result
    return (
        result[:max_length]
        + f"\n\n... [TRUNCATED - {len(result)} chars total, showing first {max_length}]"
    )


def _truncate_for_log(s: str, max_length: int = 200) -> str:
    """Truncate a string for logging purposes."""
    if len(s) <= max_length:
        return s
    return s[:max_length] + "..."


# ---------------------------------------------------------------------------
# Tool Executor Creation
# ---------------------------------------------------------------------------


def tools_from_nodes(
    nodes: list[Any],
    *,
    max_result_length: int = DEFAULT_MAX_RESULT_LENGTH,
) -> tuple[list[ToolDefinition], ToolExecutor]:
    """Create tool definitions and executor from a list of nodes.

    Only nodes that implement the ToolCapable protocol are included.
    Nodes without tool methods are silently skipped.

    Tool names are prefixed with node ID to avoid collisions when multiple
    nodes provide tools with the same name (e.g., "bash.bash", "fs-mcp.read_file").

    Args:
        nodes: List of nodes. Only tool-capable ones are included.
        max_result_length: Maximum result length before truncation.

    Returns:
        Tuple of (list of ToolDefinitions, ToolExecutor function).

    Example:
        >>> bash = BashNode(id="bash", session=session)
        >>> llm = OpenRouterNode(id="helper", session=session, ...)
        >>>
        >>> # Only bash is tool-capable, llm is skipped
        >>> tools, executor = tools_from_nodes([bash, llm])
        >>>
        >>> agent = StatefulLLMNode(
        ...     id="agent",
        ...     session=session,
        ...     llm=main_llm,
        ...     system="You have access to bash.",
        ...     tools=tools,
        ...     tool_executor=executor,
        ... )
    """
    # Build tool definitions and routing map
    # Map: prefixed_name -> (node, original_tool_name)
    definitions: list[ToolDefinition] = []
    tool_map: dict[str, tuple[ToolCapable, str]] = {}

    for node in nodes:
        if not is_tool_capable(node):
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
            definitions.append(prefixed_tool)
            tool_map[prefixed_name] = (node, tool.name)

    # Create executor
    async def executor(
        name: str,
        args: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> str:
        """Execute a tool by name with given arguments.

        Args:
            name: Tool name (prefixed with node id, e.g., "bash.bash").
            args: Arguments from LLM's tool call.
            context: Optional parent context for logging inheritance.

        Returns:
            String result for the LLM.
        """
        # Find the node and original tool name
        if name not in tool_map:
            available = list(tool_map.keys())
            return f"Error: Unknown tool '{name}'. Available tools: {available}"

        node, original_tool_name = tool_map[name]

        # Get logger from node's session if available
        logger = None
        session = getattr(node, "session", None)
        if session:
            session_logger = getattr(session, "session_logger", None)
            if session_logger:
                logger = session_logger.get_node_logger(node.id)

        # Get exec_id for logging
        exec_id = context.exec_id if context else None

        # Log tool start
        log_start(
            logger,
            node.id,
            "tool_start",
            exec_id=exec_id,
            tool=original_tool_name,
            tool_args=_truncate_for_log(str(args)),
        )

        start_time = time.monotonic()

        try:
            # Call the tool directly via call_tool()
            result = await node.call_tool(original_tool_name, args)

            # Truncate if needed
            result = truncate_result(result, max_result_length)

            # Log completion
            duration = time.monotonic() - start_time
            log_complete(
                logger,
                node.id,
                "tool_complete",
                duration,
                exec_id=exec_id,
                tool=original_tool_name,
                result_length=len(result),
            )

            return result

        except Exception as e:
            duration = time.monotonic() - start_time
            error_msg = f"Error executing tool '{name}': {type(e).__name__}: {e}"
            log_error(
                logger,
                node.id,
                "tool_error",
                e,
                exec_id=exec_id,
                tool=original_tool_name,
                duration_s=f"{duration:.1f}",
            )
            return error_msg

    return definitions, executor
