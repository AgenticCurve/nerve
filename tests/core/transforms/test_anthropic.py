"""Tests for AnthropicTransformer."""

import pytest

from nerve.core.transforms.anthropic import AnthropicTransformer
from nerve.core.transforms.tool_id_mapper import ToolIDMapper
from nerve.core.transforms.types import (
    InternalResponse,
    StreamChunk,
    TokenUsage,
    ToolCall,
)


class TestAnthropicTransformerToInternal:
    """Tests for converting Anthropic format to internal format."""

    def test_simple_text_message(self):
        """Simple text message should be converted correctly."""
        transformer = AnthropicTransformer()
        body = {
            "messages": [{"role": "user", "content": "Hello, world!"}],
            "max_tokens": 1024,
        }

        request = transformer.to_internal(body)

        assert len(request.messages) == 1
        assert request.messages[0].role == "user"
        assert request.messages[0].content == "Hello, world!"
        assert request.max_tokens == 1024

    def test_message_with_content_blocks(self):
        """Message with array of content blocks should be parsed."""
        transformer = AnthropicTransformer()
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Hello"},
                        {"type": "text", "text": "World"},
                    ],
                }
            ],
        }

        request = transformer.to_internal(body)

        assert len(request.messages) == 1
        # Text blocks are combined
        assert request.messages[0].content == "Hello World"

    def test_tool_use_message(self):
        """Assistant message with tool_use should be parsed."""
        transformer = AnthropicTransformer()
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Let me check that for you."},
                        {
                            "type": "tool_use",
                            "id": "toolu_123",
                            "name": "get_weather",
                            "input": {"location": "San Francisco"},
                        },
                    ],
                }
            ],
        }

        request = transformer.to_internal(body)

        assert len(request.messages) == 1
        msg = request.messages[0]
        assert msg.role == "assistant"
        assert msg.content == "Let me check that for you."
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].id == "toolu_123"
        assert msg.tool_calls[0].name == "get_weather"
        assert msg.tool_calls[0].arguments == {"location": "San Francisco"}

    def test_tool_result_message(self):
        """User message with tool_result should be parsed."""
        transformer = AnthropicTransformer()
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_123",
                            "content": "72 degrees and sunny",
                        }
                    ],
                }
            ],
        }

        request = transformer.to_internal(body)

        assert len(request.messages) == 1
        msg = request.messages[0]
        assert msg.role == "tool_result"
        assert msg.content == "72 degrees and sunny"
        assert msg.tool_call_id == "toolu_123"

    def test_multiple_tool_results_in_one_message(self):
        """Multiple tool_result blocks in one message should each become a message."""
        transformer = AnthropicTransformer()
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "Result 1",
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_2",
                            "content": "Result 2",
                        },
                    ],
                }
            ],
        }

        request = transformer.to_internal(body)

        assert len(request.messages) == 2
        assert request.messages[0].tool_call_id == "toolu_1"
        assert request.messages[0].content == "Result 1"
        assert request.messages[1].tool_call_id == "toolu_2"
        assert request.messages[1].content == "Result 2"

    def test_system_message_as_string(self):
        """System message as string should be captured."""
        transformer = AnthropicTransformer()
        body = {
            "messages": [{"role": "user", "content": "Hello"}],
            "system": "You are a helpful assistant.",
        }

        request = transformer.to_internal(body)

        assert request.system == "You are a helpful assistant."

    def test_system_message_as_blocks(self):
        """System message as array of blocks should be combined."""
        transformer = AnthropicTransformer()
        body = {
            "messages": [{"role": "user", "content": "Hello"}],
            "system": [
                {"type": "text", "text": "You are helpful."},
                {"type": "text", "text": "Be concise."},
            ],
        }

        request = transformer.to_internal(body)

        assert request.system == "You are helpful. Be concise."

    def test_tools_are_converted(self):
        """Tool definitions should be converted."""
        transformer = AnthropicTransformer()
        body = {
            "messages": [{"role": "user", "content": "What's the weather?"}],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get weather for a location",
                    "input_schema": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                }
            ],
        }

        request = transformer.to_internal(body)

        assert len(request.tools) == 1
        assert request.tools[0].name == "get_weather"
        assert request.tools[0].description == "Get weather for a location"

    def test_stream_and_temperature(self):
        """Stream and temperature should be captured."""
        transformer = AnthropicTransformer()
        body = {
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
            "temperature": 0.7,
        }

        request = transformer.to_internal(body)

        assert request.stream is False
        assert request.temperature == 0.7


class TestAnthropicTransformerFromInternal:
    """Tests for converting internal format back to Anthropic format."""

    def test_simple_response(self):
        """Simple text response should be formatted correctly."""
        transformer = AnthropicTransformer()
        mapper = ToolIDMapper()

        response = InternalResponse(
            content="Hello! How can I help?",
            finish_reason="stop",
        )

        result = transformer.from_internal(response, mapper, "claude-3-opus")

        assert result["type"] == "message"
        assert result["role"] == "assistant"
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Hello! How can I help?"
        assert result["model"] == "claude-3-opus"
        assert result["stop_reason"] == "end_turn"

    def test_response_with_tool_calls(self):
        """Response with tool calls should include tool_use blocks."""
        transformer = AnthropicTransformer()
        mapper = ToolIDMapper()

        response = InternalResponse(
            content="Let me check.",
            tool_calls=(
                ToolCall(
                    id="call_abc",
                    name="get_weather",
                    arguments={"location": "NYC"},
                ),
            ),
            finish_reason="tool_use",
        )

        result = transformer.from_internal(response, mapper, "claude-3-opus")

        assert len(result["content"]) == 2
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "tool_use"
        assert result["content"][1]["name"] == "get_weather"
        assert result["content"][1]["input"] == {"location": "NYC"}
        # ID should be mapped to Anthropic format
        assert result["content"][1]["id"].startswith("toolu_")

    def test_response_with_usage(self):
        """Response with usage should include usage info."""
        transformer = AnthropicTransformer()
        mapper = ToolIDMapper()

        response = InternalResponse(
            content="Hi!",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )

        result = transformer.from_internal(response, mapper, "claude-3-opus")

        assert "usage" in result
        assert result["usage"]["input_tokens"] == 10
        assert result["usage"]["output_tokens"] == 5

    def test_finish_reason_mapping(self):
        """Finish reasons should be mapped to Anthropic format."""
        transformer = AnthropicTransformer()
        mapper = ToolIDMapper()

        # stop -> end_turn
        response = InternalResponse(content="", finish_reason="stop")
        result = transformer.from_internal(response, mapper, "model")
        assert result["stop_reason"] == "end_turn"

        # tool_use -> tool_use
        response = InternalResponse(content="", finish_reason="tool_use")
        result = transformer.from_internal(response, mapper, "model")
        assert result["stop_reason"] == "tool_use"

        # length -> max_tokens
        response = InternalResponse(content="", finish_reason="length")
        result = transformer.from_internal(response, mapper, "model")
        assert result["stop_reason"] == "max_tokens"


class TestAnthropicTransformerSSE:
    """Tests for SSE event generation."""

    def test_message_start_event(self):
        """message_start chunk should generate correct SSE."""
        transformer = AnthropicTransformer()
        mapper = ToolIDMapper()

        chunk = StreamChunk(
            type="message_start",
            usage=TokenUsage(input_tokens=100, output_tokens=0),
        )

        sse = transformer.chunk_to_sse(chunk, mapper, "claude-3-opus")
        sse_str = sse.decode("utf-8")

        assert "event: message_start" in sse_str
        # Check for type field in the JSON (without spaces after colon)
        assert '"type":"message_start"' in sse_str.replace(" ", "").replace("\n", "")

    def test_text_delta_event(self):
        """text chunk should generate content_block_delta SSE."""
        transformer = AnthropicTransformer()
        mapper = ToolIDMapper()

        chunk = StreamChunk(type="text", content="Hello", index=0)

        sse = transformer.chunk_to_sse(chunk, mapper, "claude-3-opus")
        sse_str = sse.decode("utf-8")

        assert "event: content_block_delta" in sse_str
        assert "Hello" in sse_str

    def test_tool_call_start_event(self):
        """tool_call_start chunk should generate content_block_start SSE."""
        transformer = AnthropicTransformer()
        mapper = ToolIDMapper()

        chunk = StreamChunk(
            type="tool_call_start",
            tool_call=ToolCall(id="call_123", name="get_weather", arguments={}),
            index=1,
        )

        sse = transformer.chunk_to_sse(chunk, mapper, "claude-3-opus")
        sse_str = sse.decode("utf-8")

        assert "event: content_block_start" in sse_str
        assert "tool_use" in sse_str
        assert "get_weather" in sse_str

    def test_done_event(self):
        """done chunk should generate message_delta and message_stop SSE."""
        transformer = AnthropicTransformer()
        mapper = ToolIDMapper()

        chunk = StreamChunk(
            type="done",
            usage=TokenUsage(input_tokens=0, output_tokens=50),
        )

        sse = transformer.chunk_to_sse(chunk, mapper, "claude-3-opus")
        sse_str = sse.decode("utf-8")

        assert "event: message_delta" in sse_str
        assert "event: message_stop" in sse_str
