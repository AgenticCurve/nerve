"""API proxy transformers for format conversion.

This module provides transformers for converting between different
LLM API formats (Anthropic, OpenAI) using a provider-agnostic
internal representation.
"""

from .anthropic import AnthropicTransformer
from .openai import OpenAITransformer
from .tool_id_mapper import ToolIDMapper
from .types import (
    ContentBlock,
    InternalMessage,
    InternalRequest,
    InternalResponse,
    RoutingHint,
    StreamChunk,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)
from .validation import MessagesRequest, validate_request

__all__ = [
    # Transformers
    "AnthropicTransformer",
    "OpenAITransformer",
    "ToolIDMapper",
    # Types
    "ContentBlock",
    "InternalMessage",
    "InternalRequest",
    "InternalResponse",
    "RoutingHint",
    "StreamChunk",
    "TokenUsage",
    "ToolCall",
    "ToolDefinition",
    # Validation
    "MessagesRequest",
    "validate_request",
]
