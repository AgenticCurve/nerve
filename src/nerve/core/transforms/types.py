"""Types for API proxy transformers.

Separate from core/types.py to avoid polluting core types.
These types represent the provider-agnostic internal format used
for translating between Anthropic and OpenAI API formats.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ContentBlock:
    """A content block within a message (text or image)."""

    type: Literal["text", "image"]
    text: str | None = None
    image_url: str | None = None


@dataclass(frozen=True)
class ToolCall:
    """A tool call made by the assistant."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolDefinition:
    """Definition of an available tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass(frozen=True)
class InternalMessage:
    """Provider-agnostic message format."""

    role: Literal["system", "user", "assistant", "tool_result"]
    content: str | list[ContentBlock]
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None  # For tool_result messages


@dataclass(frozen=True)
class RoutingHint:
    """Hint for DAG-based routing (v2).

    This is a placeholder for future multi-model routing support.
    """

    suggested_agent: str | None = None  # "coder", "thinker", "tool-user"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InternalRequest:
    """Provider-agnostic request format."""

    messages: tuple[InternalMessage, ...]
    tools: tuple[ToolDefinition, ...] = ()
    max_tokens: int = 4096
    temperature: float = 1.0
    stream: bool = True
    model: str | None = None
    system: str | None = None  # System message (Anthropic sends separately)
    routing_hint: RoutingHint | None = None  # For future DAG integration


@dataclass(frozen=True)
class TokenUsage:
    """Token usage statistics."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class InternalResponse:
    """Non-streaming response."""

    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: Literal["stop", "tool_use", "length"] = "stop"
    usage: TokenUsage | None = None


@dataclass(frozen=True)
class StreamChunk:
    """Single chunk from streaming response."""

    type: Literal[
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
        "text",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_end",
        "done",
    ]
    content: str = ""
    tool_call: ToolCall | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None  # For tool_call_start
    tool_arguments_delta: str = ""  # For tool_call_delta
    usage: TokenUsage | None = None
    index: int = 0  # Block index for Anthropic SSE
