"""StatefulLLMNode - stateful conversation node with tool support.

StatefulLLMNode wraps a StatelessLLMNode (OpenRouterNode, GLMNode, etc.) and adds:
- Conversation history (messages array persists across execute() calls)
- System prompt support
- Tool definitions and automatic tool call handling
- Conversation persistence (save/load)

This is the node to use for multi-turn conversations, agents, and tool use.
For simple single-shot queries, use OpenRouterNode or GLMNode directly.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from nerve.core.nodes.base import NodeInfo, NodeState
from nerve.core.nodes.context import ExecutionContext
from nerve.core.nodes.llm.base import StatelessLLMNode
from nerve.core.nodes.run_logging import log_complete, log_error, log_start, log_warning

if TYPE_CHECKING:
    from nerve.core.session.session import Session


@dataclass
class Message:
    """A message in the conversation."""

    role: str  # "system", "user", "assistant", "tool"
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None  # For assistant messages
    tool_call_id: str | None = None  # For tool result messages
    name: str | None = None  # Tool name for tool results

    def to_dict(self) -> dict[str, Any]:
        """Convert to API-compatible dict."""
        msg: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            msg["content"] = self.content
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name:
            msg["name"] = self.name
        return msg


@dataclass
class ToolDefinition:
    """Definition of an available tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema

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


# Type alias for tool executor function
ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[str]]


@dataclass
class StatefulLLMNode:
    """Stateful conversation node built on top of stateless LLM node.

    StatefulLLMNode maintains conversation state across execute() calls,
    enabling multi-turn conversations and tool use.

    Features:
    - Automatic message history management
    - System prompt support
    - Tool definitions and automatic tool call loops
    - Conversation persistence (save/load)
    - Works with any StatelessLLMNode (OpenRouterNode, GLMNode, etc.)

    Args:
        id: Unique identifier for this node.
        session: Session to register this node with.
        llm: The underlying stateless LLM node.
        system: Optional system prompt.
        tools: Optional list of tool definitions.
        tool_executor: Optional async function to execute tools.
            Signature: async def executor(name: str, args: dict) -> str
        max_tool_rounds: Maximum tool call rounds before stopping (default: 10).
        tool_choice: Control tool usage. Can be:
            - "auto": Let LLM decide (default behavior)
            - "none": Disable tool usage for this conversation
            - {"type": "function", "function": {"name": "tool_name"}}: Force specific tool
        parallel_tool_calls: Control parallel tool execution.
            - True: Allow multiple tools in one response (default for most models)
            - False: Force sequential tool calls
        metadata: Additional metadata for the node.

    Example:
        >>> # Create underlying LLM node
        >>> llm = OpenRouterNode(
        ...     id="llm",
        ...     session=session,
        ...     api_key="sk-...",
        ...     model="anthropic/claude-3-haiku",
        ... )
        >>>
        >>> # Wrap in chat node
        >>> chat = StatefulLLMNode(
        ...     id="chat",
        ...     session=session,
        ...     llm=llm,
        ...     system="You are a helpful coding assistant.",
        ... )
        >>>
        >>> # Multi-turn conversation
        >>> result1 = await chat.execute(ctx(input="What is Python?"))
        >>> result2 = await chat.execute(ctx(input="Show me an example"))
        >>> # result2 has full context from result1
    """

    node_type: ClassVar[str] = "llm_chat"

    # Required fields
    id: str
    session: Session
    llm: StatelessLLMNode

    # Conversation configuration
    system: str | None = None
    tools: list[ToolDefinition] = field(default_factory=list)
    tool_executor: ToolExecutor | None = None
    max_tool_rounds: int = 10
    tool_choice: str | dict[str, Any] | None = (
        None  # "auto", "none", or {"type": "function", "function": {"name": "..."}}
    )
    parallel_tool_calls: bool | None = None  # Control parallel vs sequential tool execution
    metadata: dict[str, Any] = field(default_factory=dict)

    # Conversation state
    messages: list[Message] = field(default_factory=list)

    # Internal fields
    persistent: bool = field(default=True, init=False)  # Chat nodes are persistent

    def __post_init__(self) -> None:
        """Validate and register with session."""
        from nerve.core.validation import validate_name

        # Validate node ID
        validate_name(self.id, "node")

        # Check for duplicates
        if self.id in self.session.nodes:
            raise ValueError(f"Node '{self.id}' already exists in session '{self.session.name}'")

        # Auto-register with session
        self.session.nodes[self.id] = self

        # Log node registration
        if self.session.session_logger:
            self.session.session_logger.log_node_lifecycle(
                self.id, "StatefulLLMNode", persistent=self.persistent
            )

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Execute a conversation turn.

        Args:
            context: Execution context with input. Input should be a string
                (user message) or can be None to continue after tool calls.

        Returns:
            Result dict with:
            - success (bool): Whether the request succeeded
            - content (str | None): Assistant's response
            - tool_calls (list | None): Any tool calls made
            - usage (dict | None): Token usage
            - messages_count (int): Total messages in conversation
            - error (str | None): Error message if failed
        """
        # Get logger and exec_id
        from nerve.core.nodes.session_logging import get_execution_logger

        log_ctx = get_execution_logger(self.id, context, self.session)
        exec_id = log_ctx.exec_id or context.exec_id

        result: dict[str, Any] = {
            "success": False,
            "error": None,
            "error_type": None,
            "input": str(context.input) if context.input is not None else "",
            "output": None,
            "content": None,
            "tool_calls": None,
            "usage": None,
            "messages_count": 0,
            "tool_rounds": 0,
        }

        start_mono = time.monotonic()

        # Log chat turn start
        log_start(
            log_ctx.logger,
            self.id,
            "chat_turn_start",
            exec_id=exec_id,
            messages=len(self.messages),
            has_input=context.input is not None,
        )

        try:
            # Add user message if input provided
            if context.input is not None:
                user_content = (
                    context.input if isinstance(context.input, str) else str(context.input)
                )
                self.messages.append(Message(role="user", content=user_content))

            # Execute with tool call loop
            total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            rounds = 0

            while rounds < self.max_tool_rounds:
                rounds += 1

                # Build request
                request = self._build_request()

                # Call underlying LLM (pass run_logger for LLM logging)
                llm_context = ExecutionContext(
                    session=context.session or self.session,
                    input=request,
                    run_logger=context.run_logger,
                )
                llm_result = await self.llm.execute(llm_context)

                if not llm_result["success"]:
                    result["error"] = llm_result.get("error")
                    result["error_type"] = llm_result.get("error_type", "internal_error")
                    result["messages_count"] = len(self.messages)
                    # tool_rounds = rounds where we executed tools (current round failed before tool execution)
                    result["tool_rounds"] = max(0, rounds - 1)
                    result["usage"] = total_usage
                    result["output"] = result["error"]  # Set output for consistency with schema
                    duration = time.monotonic() - start_mono
                    log_error(
                        log_ctx.logger,
                        self.id,
                        "chat_llm_error",
                        result["error"] or "Unknown error",
                        exec_id=exec_id,
                        round=rounds,
                        duration_s=f"{duration:.1f}",
                    )
                    return result

                # Accumulate usage
                if llm_result.get("usage"):
                    for key in total_usage:
                        total_usage[key] += llm_result["usage"].get(key, 0)

                # Parse tool calls from response
                tool_calls = self._parse_tool_calls(llm_result)
                content = llm_result.get("content")

                # Add assistant message
                self.messages.append(
                    Message(
                        role="assistant",
                        content=content,
                        tool_calls=tool_calls if tool_calls else None,
                    )
                )

                # If no tool calls or no executor, we're done
                if not tool_calls or not self.tool_executor:
                    result["success"] = True
                    result["content"] = content
                    result["tool_calls"] = tool_calls
                    result["usage"] = total_usage
                    result["messages_count"] = len(self.messages)
                    # tool_rounds = rounds where we executed tools (current round gave final answer)
                    result["tool_rounds"] = max(0, rounds - 1) if tool_calls else 0

                    # Set output field
                    if content:
                        result["output"] = content
                    elif tool_calls:
                        tool_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                        result["output"] = f"[Tool calls: {', '.join(tool_names)}]"
                    else:
                        result["output"] = ""

                    duration = time.monotonic() - start_mono
                    log_complete(
                        log_ctx.logger,
                        self.id,
                        "chat_turn_complete",
                        duration,
                        exec_id=exec_id,
                        rounds=rounds,
                        tokens=total_usage["total_tokens"],
                        messages=len(self.messages),
                    )
                    return result

                # Log tool calls
                tool_round_start = time.monotonic()
                tool_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                log_start(
                    log_ctx.logger,
                    self.id,
                    "chat_tool_round_start",
                    exec_id=exec_id,
                    round=rounds,
                    tools=tool_names,
                    tool_count=len(tool_calls),
                )

                # Execute tool calls and add results
                tools_succeeded = 0
                tools_failed = 0
                for tc in tool_calls:
                    tool_name = tc.get("function", {}).get("name", "")
                    tool_args = tc.get("function", {}).get("arguments", {})
                    tool_id = tc.get("id", "")

                    # Parse arguments if they're a string
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except json.JSONDecodeError:
                            tool_args = {"raw": tool_args}

                    # Execute tool
                    tool_start = time.monotonic()
                    try:
                        tool_result = await self.tool_executor(tool_name, tool_args)
                        tools_succeeded += 1
                        tool_duration = time.monotonic() - tool_start
                        log_complete(
                            log_ctx.logger,
                            self.id,
                            "chat_tool_complete",
                            tool_duration,
                            exec_id=exec_id,
                            tool=tool_name,
                        )
                    except Exception as e:
                        tool_result = f"Error executing tool: {e}"
                        tools_failed += 1
                        tool_duration = time.monotonic() - tool_start
                        log_error(
                            log_ctx.logger,
                            self.id,
                            "chat_tool_error",
                            e,
                            exec_id=exec_id,
                            tool=tool_name,
                            duration_s=f"{tool_duration:.1f}",
                        )

                    # Add tool result message
                    self.messages.append(
                        Message(
                            role="tool",
                            content=tool_result,
                            tool_call_id=tool_id,
                            name=tool_name,
                        )
                    )

                # Log tool round summary
                round_duration = time.monotonic() - tool_round_start
                log_complete(
                    log_ctx.logger,
                    self.id,
                    "chat_tool_round_complete",
                    round_duration,
                    exec_id=exec_id,
                    round=rounds,
                    tools_total=len(tool_calls),
                    tools_succeeded=tools_succeeded,
                    tools_failed=tools_failed,
                )

                # Continue loop to get next response

            # Max rounds reached - include context about last tools
            result["error"] = f"Max tool rounds ({self.max_tool_rounds}) reached"
            result["error_type"] = "internal_error"
            result["messages_count"] = len(self.messages)
            # tool_rounds = rounds where we executed tools (we executed in all rounds including current)
            result["tool_rounds"] = rounds
            result["usage"] = total_usage
            result["tool_calls"] = tool_calls
            result["output"] = result["error"]  # Set output for consistency with schema
            duration = time.monotonic() - start_mono
            # Get last tool names for context
            last_tool_names = (
                [tc.get("function", {}).get("name", "?") for tc in tool_calls] if tool_calls else []
            )
            log_warning(
                log_ctx.logger,
                self.id,
                "chat_max_rounds",
                exec_id=exec_id,
                max_rounds=self.max_tool_rounds,
                last_round=rounds,
                last_tools=last_tool_names,
                total_tokens=total_usage["total_tokens"],
                duration_s=f"{duration:.1f}",
            )

        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
            result["error_type"] = "internal_error"
            result["messages_count"] = len(self.messages)
            duration = time.monotonic() - start_mono
            log_error(
                log_ctx.logger,
                self.id,
                "chat_error",
                e,
                exec_id=exec_id,
                duration_s=f"{duration:.1f}",
            )

        return result

    def _build_request(self) -> dict[str, Any]:
        """Build API request from current conversation state."""
        messages_list = []

        # Add system message if present
        if self.system:
            messages_list.append({"role": "system", "content": self.system})

        # Add conversation messages
        for msg in self.messages:
            messages_list.append(msg.to_dict())

        request: dict[str, Any] = {"messages": messages_list}

        # Add tools if defined
        if self.tools:
            request["tools"] = [t.to_dict() for t in self.tools]

            # Add tool_choice if specified ("auto", "none", or force specific tool)
            if self.tool_choice is not None:
                request["tool_choice"] = self.tool_choice

            # Add parallel_tool_calls if specified
            if self.parallel_tool_calls is not None:
                request["parallel_tool_calls"] = self.parallel_tool_calls

        return request

    def _parse_tool_calls(self, llm_result: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Parse tool calls from LLM response.

        Handles both OpenAI format (tool_calls in response) and
        checking the raw response for tool_calls.
        """
        # Check for tool_calls in result
        if "tool_calls" in llm_result and llm_result["tool_calls"]:
            return cast(list[dict[str, Any]], llm_result["tool_calls"])

        # Check raw response (some providers include it differently)
        # This would need to be extended based on provider-specific formats
        return None

    def clear(self) -> None:
        """Clear conversation history."""
        self.messages.clear()

    def get_messages(self) -> list[dict[str, Any]]:
        """Get conversation messages as list of dicts."""
        result = []
        if self.system:
            result.append({"role": "system", "content": self.system})
        for msg in self.messages:
            result.append(msg.to_dict())
        return result

    def save(self, path: Path | str) -> None:
        """Save conversation to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "id": self.id,
            "system": self.system,
            "messages": [msg.to_dict() for msg in self.messages],
            "tools": [t.to_dict() for t in self.tools],
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load(self, path: Path | str) -> None:
        """Load conversation from JSON file."""
        path = Path(path)

        with open(path) as f:
            data = json.load(f)

        self.system = data.get("system")
        self.messages = [
            Message(
                role=m["role"],
                content=m.get("content"),
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
            )
            for m in data.get("messages", [])
        ]

    async def interrupt(self) -> None:
        """Interrupt is a no-op for chat nodes."""
        pass

    async def stop(self) -> None:
        """Stop the chat node and clean up the inner LLM node.

        This method:
        1. Removes the inner LLM node from the session registry
        2. Closes the inner LLM node's HTTP resources
        3. Removes this chat node from the session registry

        This ensures that when a chat node is deleted, the inner LLM node
        (created by NodeFactory with id "{node_id}-llm") is also properly
        cleaned up and doesn't remain orphaned in session.nodes.
        """
        # Clean up inner LLM node
        inner_id = self.llm.id
        if inner_id in self.session.nodes:
            self.session.nodes.pop(inner_id)

        # Close HTTP resources on inner node
        await self.llm.close()

        # Remove self from session if still registered
        if self.id in self.session.nodes:
            self.session.nodes.pop(self.id)

    async def close(self) -> None:
        """Close the underlying LLM node."""
        await self.llm.close()

    def to_info(self) -> NodeInfo:
        """Get node information."""
        return NodeInfo(
            id=self.id,
            node_type=self.node_type,
            state=NodeState.READY,
            persistent=self.persistent,
            metadata={
                "llm_id": self.llm.id,
                "llm_model": self.llm.model,
                "system": self.system[:50] + "..."
                if self.system and len(self.system) > 50
                else self.system,
                "messages_count": len(self.messages),
                "tools_count": len(self.tools),
                **self.metadata,
            },
        )

    def __repr__(self) -> str:
        return (
            f"StatefulLLMNode(id={self.id!r}, llm={self.llm.id!r}, messages={len(self.messages)})"
        )
