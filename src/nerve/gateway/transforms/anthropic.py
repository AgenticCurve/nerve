"""Anthropic Messages API transformer.

Converts between Anthropic Messages API format and the internal
provider-agnostic format. Handles both request and response transformation,
including streaming SSE events.

Anthropic API Reference:
- Request: POST /v1/messages with {messages, max_tokens, model, stream, tools, system}
- Response: {id, type, role, content, model, stop_reason, usage}
- Streaming: SSE events (message_start, content_block_start/delta/stop, message_delta, message_stop)
"""

import json
import time
from dataclasses import dataclass
from typing import Any, Literal, cast

from .tool_id_mapper import ToolIDMapper
from .types import (
    ContentBlock,
    InternalMessage,
    InternalRequest,
    InternalResponse,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)

RoleType = Literal["system", "user", "assistant", "tool_result"]


def _generate_message_id() -> str:
    """Generate a unique message ID in Anthropic format."""
    return f"msg_{int(time.time() * 1000)}"


@dataclass
class AnthropicTransformer:
    """Transforms Anthropic API format to/from internal format."""

    def to_internal(self, body: dict[str, Any]) -> InternalRequest:
        """Convert Anthropic Messages API request to internal format.

        Args:
            body: Anthropic request body with messages, max_tokens, etc.

        Returns:
            InternalRequest with provider-agnostic format
        """
        messages: list[InternalMessage] = []

        for msg in body.get("messages", []):
            role = cast(RoleType, msg["role"])
            content = msg.get("content")

            if content is None or content == "":
                # Empty or missing content
                messages.append(
                    InternalMessage(
                        role=role,
                        content="",
                    )
                )
            elif isinstance(content, str):
                # Simple text message
                messages.append(
                    InternalMessage(
                        role=role,
                        content=content,
                    )
                )
            elif isinstance(content, list):
                if not content:
                    # Empty content array - treat as empty string
                    messages.append(
                        InternalMessage(
                            role=role,
                            content="",
                        )
                    )
                else:
                    # Array of content blocks
                    self._process_content_blocks(messages, role, content)

        # Convert tools
        tools: list[ToolDefinition] = []
        for tool in body.get("tools", []):
            tools.append(
                ToolDefinition(
                    name=tool["name"],
                    description=tool.get("description", ""),
                    parameters=tool.get("input_schema", {}),
                )
            )

        # Handle system message - Anthropic sends it separately
        system = body.get("system")
        if isinstance(system, list):
            # System can be an array of blocks too
            system = " ".join(
                block.get("text", "") for block in system if block.get("type") == "text"
            )

        return InternalRequest(
            messages=tuple(messages),
            tools=tuple(tools),
            max_tokens=body.get("max_tokens", 4096),
            temperature=body.get("temperature", 1.0),
            stream=body.get("stream", True),
            model=body.get("model"),
            system=system,
        )

    def _process_content_blocks(
        self,
        messages: list[InternalMessage],
        role: RoleType,
        blocks: list[dict[str, Any]],
    ) -> None:
        """Process an array of content blocks from an Anthropic message.

        Handles text, thinking, tool_use, tool_result, and image blocks.
        Unknown block types are silently skipped.
        """
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in blocks:
            block_type = block.get("type")

            if block_type == "text":
                text_parts.append(block.get("text", ""))

            elif block_type in ("thinking", "redacted_thinking"):
                # Thinking blocks contain model reasoning - include as text
                # (OpenAI doesn't have equivalent, but we preserve the content)
                thinking_text = block.get("thinking", block.get("text", ""))
                if thinking_text:
                    text_parts.append(f"[thinking: {thinking_text}]")

            elif block_type == "tool_use":
                # Assistant is calling a tool
                tool_calls.append(
                    ToolCall(
                        id=block["id"],
                        name=block["name"],
                        arguments=block.get("input", {}),
                    )
                )

            elif block_type == "tool_result":
                # User is providing tool result - each becomes a separate message
                result_content = block.get("content", "")
                if isinstance(result_content, list):
                    # Tool result content can also be an array
                    result_content = " ".join(
                        c.get("text", "") for c in result_content if c.get("type") == "text"
                    )
                messages.append(
                    InternalMessage(
                        role="tool_result",
                        content=result_content,
                        tool_call_id=block.get("tool_use_id"),
                    )
                )

            elif block_type == "image":
                # Handle image blocks - pass through source info
                messages.append(
                    InternalMessage(
                        role=role,
                        content=[
                            ContentBlock(
                                type="image",
                                image_url=block.get("source", {}).get("data"),
                            )
                        ],
                    )
                )

        # Add combined text/tool_use message if we have any
        if text_parts or tool_calls:
            content: str | list[ContentBlock] = " ".join(text_parts) if text_parts else ""
            messages.append(
                InternalMessage(
                    role=role,
                    content=content,
                    tool_calls=tuple(tool_calls),
                )
            )

    def from_internal(
        self,
        response: InternalResponse,
        tool_id_mapper: ToolIDMapper,
        model: str,
    ) -> dict[str, Any]:
        """Convert internal response to Anthropic Messages API format.

        Args:
            response: Internal response format
            tool_id_mapper: Mapper for tool call IDs
            model: Model name to include in response

        Returns:
            Anthropic-format response dict
        """
        content: list[dict[str, Any]] = []

        # Add text content if present
        if response.content:
            content.append({"type": "text", "text": response.content})

        # Add tool calls
        for tool_call in response.tool_calls:
            anthropic_id = tool_id_mapper.to_anthropic_id(tool_call.id)
            content.append(
                {
                    "type": "tool_use",
                    "id": anthropic_id,
                    "name": tool_call.name,
                    "input": tool_call.arguments,
                }
            )

        # Map finish reason
        stop_reason_map = {
            "stop": "end_turn",
            "tool_use": "tool_use",
            "length": "max_tokens",
        }
        stop_reason = stop_reason_map.get(response.finish_reason, "end_turn")

        result: dict[str, Any] = {
            "id": _generate_message_id(),
            "type": "message",
            "role": "assistant",
            "content": content,
            "model": model,
            "stop_reason": stop_reason,
            "stop_sequence": None,
        }

        if response.usage:
            result["usage"] = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }

        return result

    def chunk_to_sse(
        self,
        chunk: StreamChunk,
        tool_id_mapper: ToolIDMapper,
        model: str,
    ) -> bytes:
        """Convert a streaming chunk to Anthropic SSE format.

        Args:
            chunk: Internal streaming chunk
            tool_id_mapper: Mapper for tool call IDs
            model: Model name to include in events

        Returns:
            SSE-formatted bytes ready to write to response
        """
        events: list[str] = []

        if chunk.type == "message_start":
            # First event of a streaming response
            event_data: dict[str, Any] = {
                "type": "message_start",
                "message": {
                    "id": _generate_message_id(),
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": model,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            }
            if chunk.usage:
                event_data["message"]["usage"] = {
                    "input_tokens": chunk.usage.input_tokens,
                    "output_tokens": chunk.usage.output_tokens,
                }
            events.append(self._format_sse_event("message_start", event_data))

        elif chunk.type == "content_block_start":
            # Start of a new content block (text or tool_use)
            if chunk.tool_name:
                # Tool use block
                anthropic_id = tool_id_mapper.to_anthropic_id(chunk.tool_call_id or "")
                event_data = {
                    "type": "content_block_start",
                    "index": chunk.index,
                    "content_block": {
                        "type": "tool_use",
                        "id": anthropic_id,
                        "name": chunk.tool_name,
                        "input": {},
                    },
                }
            else:
                # Text block
                event_data = {
                    "type": "content_block_start",
                    "index": chunk.index,
                    "content_block": {"type": "text", "text": ""},
                }
            events.append(self._format_sse_event("content_block_start", event_data))

        elif chunk.type == "content_block_delta":
            # Delta for content block
            if chunk.tool_arguments_delta:
                # Tool input delta (JSON string fragment)
                event_data = {
                    "type": "content_block_delta",
                    "index": chunk.index,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": chunk.tool_arguments_delta,
                    },
                }
            else:
                # Text delta
                event_data = {
                    "type": "content_block_delta",
                    "index": chunk.index,
                    "delta": {"type": "text_delta", "text": chunk.content},
                }
            events.append(self._format_sse_event("content_block_delta", event_data))

        elif chunk.type == "content_block_stop":
            # End of a content block
            event_data = {
                "type": "content_block_stop",
                "index": chunk.index,
            }
            events.append(self._format_sse_event("content_block_stop", event_data))

        elif chunk.type == "message_delta":
            # Message-level delta (typically stop_reason and usage)
            event_data = {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            }
            if chunk.usage:
                event_data["usage"] = {"output_tokens": chunk.usage.output_tokens}
            events.append(self._format_sse_event("message_delta", event_data))

        elif chunk.type == "message_stop":
            # Final event
            event_data = {"type": "message_stop"}
            events.append(self._format_sse_event("message_stop", event_data))

        elif chunk.type == "text":
            # Simple text chunk - convert to content_block_delta
            event_data = {
                "type": "content_block_delta",
                "index": chunk.index,
                "delta": {"type": "text_delta", "text": chunk.content},
            }
            events.append(self._format_sse_event("content_block_delta", event_data))

        elif chunk.type == "tool_call_start":
            # Start of tool call - emit content_block_start
            if chunk.tool_call:
                anthropic_id = tool_id_mapper.to_anthropic_id(chunk.tool_call.id)
                event_data = {
                    "type": "content_block_start",
                    "index": chunk.index,
                    "content_block": {
                        "type": "tool_use",
                        "id": anthropic_id,
                        "name": chunk.tool_call.name,
                        "input": {},
                    },
                }
                events.append(self._format_sse_event("content_block_start", event_data))

        elif chunk.type == "tool_call_delta":
            # Tool call argument delta
            event_data = {
                "type": "content_block_delta",
                "index": chunk.index,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": chunk.tool_arguments_delta,
                },
            }
            events.append(self._format_sse_event("content_block_delta", event_data))

        elif chunk.type == "tool_call_end":
            # End of tool call
            event_data = {
                "type": "content_block_stop",
                "index": chunk.index,
            }
            events.append(self._format_sse_event("content_block_stop", event_data))

        elif chunk.type == "done":
            # Final done event - emit message_delta and message_stop
            delta_data: dict[str, Any] = {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            }
            if chunk.usage:
                delta_data["usage"] = {"output_tokens": chunk.usage.output_tokens}
            events.append(self._format_sse_event("message_delta", delta_data))
            events.append(self._format_sse_event("message_stop", {"type": "message_stop"}))

        return "".join(events).encode("utf-8")

    def _format_sse_event(self, event_type: str, data: dict[str, Any]) -> str:
        """Format data as an SSE event.

        Args:
            event_type: The SSE event type
            data: The event data to serialize

        Returns:
            SSE-formatted string with event and data lines
        """
        json_data = json.dumps(data, separators=(",", ":"))
        return f"event: {event_type}\ndata: {json_data}\n\n"
