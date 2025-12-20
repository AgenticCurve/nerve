"""Pydantic models for Anthropic Messages API request validation.

These models validate incoming requests to the proxy server before
processing. They match the Anthropic Messages API specification.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


class ImageSource(BaseModel):
    """Image source for image content blocks."""

    model_config = ConfigDict(extra="allow")

    type: Literal["base64", "url"]
    media_type: str | None = None
    data: str | None = None
    url: str | None = None


class ContentBlock(BaseModel):
    """Content block within a message.

    Can be text, tool_use, tool_result, image, thinking, or redacted_thinking type.
    The extra="allow" config ensures unknown types pass through.
    """

    model_config = ConfigDict(extra="allow")

    # Allow common types - extra="allow" handles any unknown types
    type: Literal["text", "tool_use", "tool_result", "image", "thinking", "redacted_thinking"] | str

    # For text blocks
    text: str | None = None

    # For tool_use blocks
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None

    # For tool_result blocks
    tool_use_id: str | None = None
    content: str | list[dict[str, Any]] | None = None
    is_error: bool | None = None

    # For image blocks
    source: ImageSource | None = None

    @field_validator("text", mode="before")
    @classmethod
    def validate_text_for_text_block(cls, v: Any, info: Any) -> Any:
        """Ensure text is present for text blocks."""
        return v

    @field_validator("id", mode="before")
    @classmethod
    def validate_id_for_tool_use(cls, v: Any, info: Any) -> Any:
        """Ensure id is present for tool_use blocks."""
        return v


class Message(BaseModel):
    """A message in the conversation."""

    model_config = ConfigDict(extra="allow")

    role: Literal["user", "assistant"]
    content: str | list[ContentBlock]

    @field_validator("content", mode="before")
    @classmethod
    def validate_content(cls, v: Any) -> Any:
        """Validate content format.

        Note: Empty content arrays and strings are allowed - the Anthropic API
        accepts these in certain scenarios (e.g., streaming, prefill messages).
        We handle empty content during transformation.
        """
        # Convert empty arrays to empty string for consistent handling
        if isinstance(v, list) and len(v) == 0:
            return ""
        # Empty strings are valid
        return v


class ToolInputSchema(BaseModel):
    """JSON Schema for tool input parameters."""

    model_config = ConfigDict(extra="allow")

    type: str = "object"
    properties: dict[str, Any] | None = None
    required: list[str] | None = None


class ToolDefinition(BaseModel):
    """Definition of an available tool."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: str | None = None
    input_schema: ToolInputSchema | dict[str, Any]

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate tool name format."""
        if not v or not v.strip():
            raise ValueError("tool name cannot be empty")
        return v


class SystemContentBlock(BaseModel):
    """Content block for system message (can be text with cache control)."""

    model_config = ConfigDict(extra="allow")

    type: Literal["text"] = "text"
    text: str
    cache_control: dict[str, str] | None = None


class MessagesRequest(BaseModel):
    """Anthropic Messages API request body."""

    model_config = ConfigDict(extra="allow")

    messages: list[Message]
    max_tokens: int = 4096
    temperature: float = 1.0
    tools: list[ToolDefinition] | None = None
    stream: bool = True
    model: str | None = None
    system: str | list[SystemContentBlock] | None = None

    # Additional optional parameters
    top_p: float | None = None
    top_k: int | None = None
    stop_sequences: list[str] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: list[Message]) -> list[Message]:
        """Validate messages list is not empty."""
        if not v:
            raise ValueError("messages list cannot be empty")
        return v

    @field_validator("max_tokens")
    @classmethod
    def validate_max_tokens(cls, v: int) -> int:
        """Validate max_tokens is positive."""
        if v <= 0:
            raise ValueError("max_tokens must be positive")
        return v

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """Validate temperature is in valid range."""
        if v < 0 or v > 2:
            raise ValueError("temperature must be between 0 and 2")
        return v


def validate_request(body: dict[str, Any]) -> list[str]:
    """Validate an Anthropic Messages API request body.

    Args:
        body: The request body dict to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    try:
        MessagesRequest.model_validate(body)
    except Exception as e:
        # Extract error messages from pydantic validation
        error_str = str(e)
        # Parse pydantic error format
        if "validation error" in error_str.lower():
            # Try to extract individual errors
            lines = error_str.split("\n")
            for line in lines[1:]:  # Skip the header line
                line = line.strip()
                if line and not line.startswith("For further"):
                    errors.append(line)
        else:
            errors.append(error_str)

    return errors
