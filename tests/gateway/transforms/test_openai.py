"""Tests for OpenAITransformer."""

import pytest

from nerve.gateway.transforms.openai import OpenAITransformer
from nerve.gateway.transforms.tool_id_mapper import ToolIDMapper
from nerve.gateway.transforms.types import (
    ContentBlock,
    InternalMessage,
    InternalRequest,
    ToolCall,
    ToolDefinition,
)


class TestOpenAITransformerToUpstream:
    """Tests for converting internal format to OpenAI format."""

    def test_simple_message(self):
        """Simple user message should be converted correctly."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        request = InternalRequest(
            messages=(InternalMessage(role="user", content="Hello!"),),
            max_tokens=1024,
        )

        result = transformer.to_upstream(request, "gpt-4o", mapper)

        assert result["model"] == "gpt-4o"
        assert result["max_tokens"] == 1024
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "Hello!"

    def test_system_message(self):
        """System message should be added as first message."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        request = InternalRequest(
            messages=(InternalMessage(role="user", content="Hello!"),),
            system="You are helpful.",
        )

        result = transformer.to_upstream(request, "gpt-4o", mapper)

        assert len(result["messages"]) == 2
        assert result["messages"][0]["role"] == "system"
        assert result["messages"][0]["content"] == "You are helpful."
        assert result["messages"][1]["role"] == "user"

    def test_tool_result_message(self):
        """tool_result should be converted to OpenAI 'tool' role."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        # First map the tool ID (simulating a prior response)
        mapper.register_mapping("call_abc123", "toolu_xyz789")

        request = InternalRequest(
            messages=(
                InternalMessage(
                    role="tool_result",
                    content="72 degrees",
                    tool_call_id="toolu_xyz789",
                ),
            ),
        )

        result = transformer.to_upstream(request, "gpt-4o", mapper)

        assert result["messages"][0]["role"] == "tool"
        assert result["messages"][0]["content"] == "72 degrees"
        assert result["messages"][0]["tool_call_id"] == "call_abc123"

    def test_assistant_with_tool_calls(self):
        """Assistant message with tool_calls should be formatted correctly."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        request = InternalRequest(
            messages=(
                InternalMessage(
                    role="assistant",
                    content="Let me check.",
                    tool_calls=(
                        ToolCall(
                            id="toolu_123",
                            name="get_weather",
                            arguments={"location": "NYC"},
                        ),
                    ),
                ),
            ),
        )

        result = transformer.to_upstream(request, "gpt-4o", mapper)

        msg = result["messages"][0]
        assert msg["role"] == "assistant"
        assert msg["content"] == "Let me check."
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["type"] == "function"
        assert msg["tool_calls"][0]["function"]["name"] == "get_weather"
        # Arguments should be JSON-encoded
        assert '"location"' in msg["tool_calls"][0]["function"]["arguments"]

    def test_tools_definition(self):
        """Tool definitions should be converted to OpenAI format."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        request = InternalRequest(
            messages=(InternalMessage(role="user", content="Weather?"),),
            tools=(
                ToolDefinition(
                    name="get_weather",
                    description="Get weather for a location",
                    parameters={
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                ),
            ),
        )

        result = transformer.to_upstream(request, "gpt-4o", mapper)

        assert "tools" in result
        assert len(result["tools"]) == 1
        tool = result["tools"][0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "get_weather"
        assert tool["function"]["description"] == "Get weather for a location"

    def test_stream_options(self):
        """Streaming requests should include stream_options."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        request = InternalRequest(
            messages=(InternalMessage(role="user", content="Hello"),),
            stream=True,
        )

        result = transformer.to_upstream(request, "gpt-4o", mapper)

        assert result["stream"] is True
        assert result["stream_options"] == {"include_usage": True}

    def test_image_content_blocks(self):
        """Image content blocks should be converted to OpenAI format."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        request = InternalRequest(
            messages=(
                InternalMessage(
                    role="user",
                    content=[
                        ContentBlock(type="text", text="What's in this image?"),
                        ContentBlock(type="image", image_url="data:image/png;base64,abc123"),
                    ],
                ),
            ),
        )

        result = transformer.to_upstream(request, "gpt-4o", mapper)

        content = result["messages"][0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"


class TestOpenAITransformerFromUpstream:
    """Tests for converting OpenAI response to internal format."""

    def test_simple_response(self):
        """Simple text response should be parsed correctly."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        response = {
            "choices": [
                {
                    "message": {"content": "Hello there!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        result = transformer.from_upstream(response, mapper)

        assert result.content == "Hello there!"
        assert result.finish_reason == "stop"
        assert result.usage is not None
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 5

    def test_response_with_tool_calls(self):
        """Response with tool_calls should be parsed correctly."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        response = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_abc123",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "NYC"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }

        result = transformer.from_upstream(response, mapper)

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_abc123"
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].arguments == {"location": "NYC"}
        assert result.finish_reason == "tool_use"

    def test_malformed_tool_arguments(self):
        """Malformed JSON in tool arguments should not crash."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "test",
                                    "arguments": "not json at all",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }

        result = transformer.from_upstream(response, mapper)

        # Should not crash, arguments should be empty dict
        assert result.tool_calls[0].arguments == {}


class TestOpenAITransformerSSEParsing:
    """Tests for parsing OpenAI SSE streaming response."""

    def test_text_delta(self):
        """Text delta should be parsed correctly."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        line = 'data: {"choices":[{"delta":{"content":"Hello"}}]}'

        chunks = transformer.parse_sse_chunk(line, mapper)

        assert len(chunks) == 1
        assert chunks[0].type == "text"
        assert chunks[0].content == "Hello"

    def test_done_marker(self):
        """[DONE] marker should produce done chunk."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        line = "data: [DONE]"

        chunks = transformer.parse_sse_chunk(line, mapper)

        assert len(chunks) == 1
        assert chunks[0].type == "done"

    def test_tool_call_start(self):
        """Tool call start should be parsed."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        line = 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_abc","function":{"name":"get_weather"}}]}}]}'

        chunks = transformer.parse_sse_chunk(line, mapper)

        assert any(c.type == "tool_call_start" for c in chunks)
        start_chunk = next(c for c in chunks if c.type == "tool_call_start")
        assert start_chunk.tool_name == "get_weather"

    def test_tool_call_delta(self):
        """Tool call argument delta should be parsed."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        # First start the tool call
        start_line = 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_abc","function":{"name":"test"}}]}}]}'
        transformer.parse_sse_chunk(start_line, mapper)

        # Then send delta
        delta_line = 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"loc"}}]}}]}'

        chunks = transformer.parse_sse_chunk(delta_line, mapper)

        assert any(c.type == "tool_call_delta" for c in chunks)

    def test_finish_reason_ends_tool_calls(self):
        """Finish reason should end active tool calls."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        # Start a tool call
        start_line = 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_abc","function":{"name":"test","arguments":""}}]}}]}'
        transformer.parse_sse_chunk(start_line, mapper)

        # Add some arguments
        delta_line = 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{}"}}]}}]}'
        transformer.parse_sse_chunk(delta_line, mapper)

        # Finish
        finish_line = 'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}'
        chunks = transformer.parse_sse_chunk(finish_line, mapper)

        assert any(c.type == "tool_call_end" for c in chunks)
        assert any(c.type == "done" for c in chunks)

    def test_usage_chunk(self):
        """Usage-only chunk should produce done with usage."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        line = 'data: {"usage":{"prompt_tokens":50,"completion_tokens":25}}'

        chunks = transformer.parse_sse_chunk(line, mapper)

        assert len(chunks) == 1
        assert chunks[0].type == "done"
        assert chunks[0].usage is not None
        assert chunks[0].usage.input_tokens == 50
        assert chunks[0].usage.output_tokens == 25

    def test_non_data_lines_ignored(self):
        """Lines not starting with 'data: ' should be ignored."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        chunks = transformer.parse_sse_chunk("", mapper)
        assert len(chunks) == 0

        chunks = transformer.parse_sse_chunk("event: message", mapper)
        assert len(chunks) == 0

        chunks = transformer.parse_sse_chunk(": keep-alive", mapper)
        assert len(chunks) == 0

    def test_reset_clears_state(self):
        """reset() should clear internal state."""
        transformer = OpenAITransformer()
        mapper = ToolIDMapper()

        # Build up some state
        start_line = 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_abc","function":{"name":"test"}}]}}]}'
        transformer.parse_sse_chunk(start_line, mapper)

        # Reset
        transformer.reset()

        # Internal state should be cleared
        assert len(transformer._current_tool_calls) == 0
        assert transformer._current_block_index == 0
