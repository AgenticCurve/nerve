"""Node-as-Tool adapter - expose tool-capable nodes to StatefulLLMNode.

This module provides utilities to expose nodes as tools that StatefulLLMNode
can use. Nodes opt-in to being tools by implementing the ToolCapable protocol.

A node becomes tool-capable by defining four methods:
- tool_description(): What does this tool do?
- tool_parameters(): JSON Schema for tool inputs
- tool_input(args): Convert tool args to context.input
- tool_result(result): Convert execute() result to string

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
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from nerve.core.nodes.context import ExecutionContext
from nerve.core.nodes.run_logging import log_complete, log_error, log_start

if TYPE_CHECKING:
    from nerve.core.nodes.llm.chat import ToolDefinition, ToolExecutor


# ---------------------------------------------------------------------------
# Protocol Definition
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolCapable(Protocol):
    """Protocol for nodes that can be used as tools.

    Nodes implement this protocol to opt-in to being available as tools
    for StatefulLLMNode. The protocol requires four methods that define how
    the node presents itself and handles tool interactions.

    Example implementation:
        class BashNode:
            def tool_description(self) -> str:
                return "Execute bash/shell commands"

            def tool_parameters(self) -> dict[str, Any]:
                return {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command"},
                    },
                    "required": ["command"],
                }

            def tool_input(self, args: dict[str, Any]) -> Any:
                return args["command"]

            def tool_result(self, result: dict[str, Any]) -> str:
                return result.get("stdout", "")
    """

    id: str

    async def execute(self, context: ExecutionContext) -> Any:
        """Execute the node with given context.

        This is the standard node execution method that all nodes implement.
        Return type varies by node (dict, ParsedResponse, etc.).
        """
        ...

    def tool_description(self) -> str:
        """Return a description of what this tool does.

        This description is shown to the LLM to help it decide when to use
        this tool. Keep it concise but informative.

        Returns:
            Human-readable description of the tool's purpose.
        """
        ...

    def tool_parameters(self) -> dict[str, Any]:
        """Return JSON Schema for tool parameters.

        This schema defines what arguments the tool accepts. The LLM uses
        this to construct valid tool calls.

        Returns:
            JSON Schema dict with type, properties, and required fields.
        """
        ...

    def tool_input(self, args: dict[str, Any]) -> Any:
        """Convert tool arguments to context.input value.

        When the LLM calls this tool with arguments, this method extracts
        the value to pass as context.input to execute().

        Args:
            args: Arguments from the LLM's tool call.

        Returns:
            Value to use as context.input for execute().
        """
        ...

    def tool_result(self, result: Any) -> str:
        """Convert execute() result to string for LLM.

        After execute() returns, this method formats the result
        into a string that the LLM can understand.

        Args:
            result: Result from execute() (type varies by node).

        Returns:
            String representation of the result for the LLM.
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
        True if node has all required tool methods.
    """
    return isinstance(node, ToolCapable)


def node_to_tool_definition(node: ToolCapable) -> ToolDefinition:
    """Convert a tool-capable node to a ToolDefinition.

    Args:
        node: A node that implements ToolCapable.

    Returns:
        ToolDefinition ready for use with StatefulLLMNode.
    """
    from nerve.core.nodes.llm.chat import ToolDefinition

    return ToolDefinition(
        name=node.id,
        description=node.tool_description(),
        parameters=node.tool_parameters(),
    )


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
    # Filter to only tool-capable nodes
    tool_nodes: dict[str, ToolCapable] = {node.id: node for node in nodes if is_tool_capable(node)}

    # Generate tool definitions
    definitions = [node_to_tool_definition(node) for node in tool_nodes.values()]

    # Create executor
    async def executor(
        name: str,
        args: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> str:
        """Execute a tool by name with given arguments.

        Args:
            name: Tool name (node id).
            args: Arguments from LLM's tool call.
            context: Optional parent context for logging inheritance.

        Returns:
            String result for the LLM.
        """
        # Find the node
        node = tool_nodes.get(name)
        if node is None:
            available = list(tool_nodes.keys())
            return f"Error: Unknown tool '{name}'. Available tools: {available}"

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
            tool_args=_truncate_for_log(str(args)),
        )

        start_time = time.monotonic()

        try:
            # Convert args to input
            input_value = node.tool_input(args)

            # Build execution context
            exec_context = ExecutionContext(
                session=session,
                input=input_value,
                # Inherit logging context from parent
                run_logger=context.run_logger if context else None,
                exec_id=exec_id,
                correlation_id=context.correlation_id if context else None,
            )

            # Execute the node
            result = await node.execute(exec_context)

            # Format result
            formatted = node.tool_result(result)

            # Truncate if needed
            formatted = truncate_result(formatted, max_result_length)

            # Log completion
            duration = time.monotonic() - start_time
            log_complete(
                logger,
                node.id,
                "tool_complete",
                duration,
                exec_id=exec_id,
                result_length=len(formatted),
            )

            return formatted

        except Exception as e:
            duration = time.monotonic() - start_time
            error_msg = f"Error executing tool '{name}': {type(e).__name__}: {e}"
            log_error(
                logger,
                node.id,
                "tool_error",
                e,
                exec_id=exec_id,
                duration_s=f"{duration:.1f}",
            )
            return error_msg

    return definitions, executor
