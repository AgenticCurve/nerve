"""OpenAI Chat Completions API transformer.

Converts internal format to OpenAI API format for upstream requests,
and parses OpenAI streaming responses into internal StreamChunk format.

OpenAI API Reference:
- Request: POST /chat/completions with {model, messages, tools, stream, max_tokens, temperature}
- Messages: [{role, content, tool_calls?, tool_call_id?}]
- Streaming: SSE with data: {"choices": [{"delta": {...}}]}
"""

import json
from dataclasses import dataclass, field
from typing import Any

from .tool_id_mapper import ToolIDMapper
from .types import (
    InternalRequest,
    InternalResponse,
    StreamChunk,
    TokenUsage,
    ToolCall,
)


@dataclass
class OpenAITransformer:
    """Transforms internal format to/from OpenAI API format."""

    # Track state for parsing streaming responses
    _current_tool_calls: dict[int, dict[str, Any]] = field(default_factory=dict)
    _current_block_index: int = 0

    def to_upstream(
        self,
        request: InternalRequest,
        model: str,
        tool_id_mapper: ToolIDMapper,
    ) -> dict[str, Any]:
        """Convert internal request to OpenAI Chat Completions format.

        Args:
            request: Internal request format
            model: Model name to use (overrides request.model)
            tool_id_mapper: Mapper for tool call IDs (for tool_result messages)

        Returns:
            OpenAI-format request dict ready for /chat/completions
        """
        messages: list[dict[str, Any]] = []

        # Add system message if present
        if request.system:
            messages.append({"role": "system", "content": request.system})

        # Convert messages
        for msg in request.messages:
            if msg.role == "tool_result":
                # Tool result -> OpenAI "tool" role message
                openai_id = tool_id_mapper.to_openai_id(msg.tool_call_id or "")
                messages.append(
                    {
                        "role": "tool",
                        "content": msg.content if isinstance(msg.content, str) else "",
                        "tool_call_id": openai_id,
                    }
                )
            elif msg.role == "assistant" and msg.tool_calls:
                # Assistant message with tool calls
                tool_calls = []
                for tc in msg.tool_calls:
                    # Use existing mapping or create new one
                    if tool_id_mapper.has_anthropic_id(tc.id):
                        openai_id = tool_id_mapper.to_openai_id(tc.id)
                    else:
                        # This is an Anthropic ID from original request, register it
                        openai_id = f"call_{tc.id.replace('toolu_', '')}"
                        tool_id_mapper.register_mapping(openai_id, tc.id)

                    tool_calls.append(
                        {
                            "id": openai_id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                    )
                msg_dict: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content if isinstance(msg.content, str) else None,
                    "tool_calls": tool_calls,
                }
                messages.append(msg_dict)
            else:
                # Regular user/assistant message
                content: str | list[dict[str, Any]]
                if isinstance(msg.content, list):
                    # Convert content blocks to OpenAI format
                    openai_content: list[dict[str, Any]] = []
                    for block in msg.content:
                        if block.type == "text" and block.text:
                            openai_content.append({"type": "text", "text": block.text})
                        elif block.type == "image" and block.image_url:
                            openai_content.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": block.image_url},
                                }
                            )
                    # OpenAI rejects empty content arrays - convert to empty string
                    content = openai_content if openai_content else ""
                else:
                    content = msg.content if msg.content else ""

                # Ensure content is never an empty list (OpenAI rejects this)
                if content == [] or content is None:
                    content = ""

                messages.append(
                    {
                        "role": msg.role,
                        "content": content,
                    }
                )

        # Build request
        result: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": request.stream,
        }

        # Add tools if present
        if request.tools:
            result["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]

        # Request stream_options for usage in streaming mode
        if request.stream:
            result["stream_options"] = {"include_usage": True}

        return result

    def from_upstream(
        self,
        response: dict[str, Any],
        tool_id_mapper: ToolIDMapper,
    ) -> InternalResponse:
        """Convert OpenAI non-streaming response to internal format.

        Args:
            response: OpenAI response dict
            tool_id_mapper: Mapper for tool call IDs

        Returns:
            InternalResponse with parsed content
        """
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})

        content = message.get("content", "") or ""
        tool_calls: list[ToolCall] = []

        # Parse tool calls
        for tc in message.get("tool_calls", []):
            function = tc.get("function", {})
            try:
                arguments = json.loads(function.get("arguments", "{}"))
            except json.JSONDecodeError:
                arguments = {}

            tool_calls.append(
                ToolCall(
                    id=tc["id"],
                    name=function.get("name", ""),
                    arguments=arguments,
                )
            )

        # Map finish reason
        finish_reason_map = {
            "stop": "stop",
            "tool_calls": "tool_use",
            "length": "length",
            "content_filter": "stop",
        }
        finish_reason = finish_reason_map.get(choice.get("finish_reason", "stop"), "stop")

        # Parse usage
        usage = None
        if "usage" in response:
            usage = TokenUsage(
                input_tokens=response["usage"].get("prompt_tokens", 0),
                output_tokens=response["usage"].get("completion_tokens", 0),
            )

        return InternalResponse(
            content=content,
            tool_calls=tuple(tool_calls),
            finish_reason=finish_reason,  # type: ignore
            usage=usage,
        )

    def parse_sse_chunk(
        self,
        line: str,
        tool_id_mapper: ToolIDMapper,
    ) -> list[StreamChunk]:
        """Parse an SSE data line from OpenAI streaming response.

        Args:
            line: Raw SSE line (should start with "data: ")
            tool_id_mapper: Mapper for tool call IDs

        Returns:
            List of StreamChunk objects (may be empty or multiple)
        """
        chunks: list[StreamChunk] = []

        # Skip non-data lines
        if not line.startswith("data: "):
            return chunks

        data_str = line[6:].strip()

        # Handle [DONE] marker
        if data_str == "[DONE]":
            chunks.append(
                StreamChunk(
                    type="done",
                    usage=None,
                )
            )
            return chunks

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return chunks

        # Check for usage in the chunk (OpenAI sends it in a separate chunk at the end)
        if "usage" in data and data["usage"]:
            usage = TokenUsage(
                input_tokens=data["usage"].get("prompt_tokens", 0),
                output_tokens=data["usage"].get("completion_tokens", 0),
            )
            # If this is a usage-only chunk (no choices), return done with usage
            if not data.get("choices"):
                chunks.append(StreamChunk(type="done", usage=usage))
                return chunks

        choices = data.get("choices", [])
        if not choices:
            return chunks

        choice = choices[0]
        delta = choice.get("delta", {})
        finish_reason = choice.get("finish_reason")

        # Handle content delta
        if "content" in delta and delta["content"]:
            chunks.append(
                StreamChunk(
                    type="text",
                    content=delta["content"],
                    index=self._current_block_index,
                )
            )

        # Handle tool calls
        tool_calls = delta.get("tool_calls", [])
        for tc in tool_calls:
            tc_index = tc.get("index", 0)

            if "id" in tc:
                # Start of a new tool call
                self._current_tool_calls[tc_index] = {
                    "id": tc["id"],
                    "name": tc.get("function", {}).get("name", ""),
                    "arguments": "",
                }
                # Increment block index for tool use (text was index 0)
                self._current_block_index = tc_index + 1

                chunks.append(
                    StreamChunk(
                        type="tool_call_start",
                        tool_call=ToolCall(
                            id=tc["id"],
                            name=tc.get("function", {}).get("name", ""),
                            arguments={},
                        ),
                        tool_call_id=tc["id"],
                        tool_name=tc.get("function", {}).get("name"),
                        index=self._current_block_index,
                    )
                )

            elif tc_index in self._current_tool_calls:
                # Continuation of existing tool call
                args_delta = tc.get("function", {}).get("arguments", "")
                if args_delta:
                    self._current_tool_calls[tc_index]["arguments"] += args_delta
                    chunks.append(
                        StreamChunk(
                            type="tool_call_delta",
                            tool_arguments_delta=args_delta,
                            tool_call_id=self._current_tool_calls[tc_index]["id"],
                            index=tc_index + 1,
                        )
                    )

        # Handle finish reason
        if finish_reason:
            # End any active tool calls
            for tc_index, tc_data in self._current_tool_calls.items():
                try:
                    arguments = json.loads(tc_data["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                chunks.append(
                    StreamChunk(
                        type="tool_call_end",
                        tool_call=ToolCall(
                            id=tc_data["id"],
                            name=tc_data["name"],
                            arguments=arguments,
                        ),
                        tool_call_id=tc_data["id"],
                        index=tc_index + 1,
                    )
                )

            # Clear state
            self._current_tool_calls.clear()
            self._current_block_index = 0

            # Add done chunk with proper finish reason
            chunks.append(
                StreamChunk(
                    type="done",
                )
            )

        return chunks

    def reset(self) -> None:
        """Reset streaming state for a new request."""
        self._current_tool_calls.clear()
        self._current_block_index = 0
