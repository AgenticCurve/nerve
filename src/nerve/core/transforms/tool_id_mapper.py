"""Tool ID translation between Anthropic and OpenAI formats.

IMPORTANT: This must be request-scoped (created per /v1/messages call).
Multi-turn tool conversations require consistent ID mapping within a request.

Anthropic uses: toolu_XXXXX format
OpenAI uses: call_XXXXX format

The mapper maintains bidirectional mappings so that:
1. When we receive an OpenAI response with call_XXX, we translate to toolu_XXX for Anthropic
2. When we receive tool_result from Anthropic with toolu_XXX, we translate back to call_XXX
"""

import time
from dataclasses import dataclass, field


@dataclass
class ToolIDMapper:
    """Bidirectional mapping of tool call IDs.

    Must be created fresh for each request and passed through
    the transformer chain.

    Example usage:
        mapper = ToolIDMapper()

        # When receiving OpenAI tool call response:
        anthropic_id = mapper.to_anthropic_id(openai_id)

        # When sending tool result back to OpenAI:
        openai_id = mapper.to_openai_id(anthropic_id)
    """

    _to_anthropic: dict[str, str] = field(default_factory=dict)
    _to_openai: dict[str, str] = field(default_factory=dict)
    _counter: int = 0

    def to_anthropic_id(self, openai_id: str) -> str:
        """Convert OpenAI tool call ID to Anthropic format.

        Creates a new mapping if one doesn't exist.

        Args:
            openai_id: OpenAI-format tool call ID (e.g., "call_abc123")

        Returns:
            Anthropic-format tool call ID (e.g., "toolu_1734567890123_1")
        """
        if openai_id not in self._to_anthropic:
            self._counter += 1
            anthropic_id = f"toolu_{int(time.time() * 1000)}_{self._counter}"
            self._to_anthropic[openai_id] = anthropic_id
            self._to_openai[anthropic_id] = openai_id
        return self._to_anthropic[openai_id]

    def to_openai_id(self, anthropic_id: str) -> str:
        """Convert Anthropic tool call ID to OpenAI format.

        Args:
            anthropic_id: Anthropic-format tool call ID (e.g., "toolu_xxx")

        Returns:
            OpenAI-format tool call ID (e.g., "call_abc123")

        Raises:
            KeyError: If the ID was not previously mapped via to_anthropic_id().
                This indicates a bug where a tool_result references an ID
                that was never returned in a tool_use block.
        """
        if anthropic_id not in self._to_openai:
            raise KeyError(
                f"Unknown Anthropic tool ID: {anthropic_id}. "
                "Tool result references an ID that was never mapped. "
                "Ensure tool_use responses are processed before tool_results."
            )
        return self._to_openai[anthropic_id]

    def register_mapping(self, openai_id: str, anthropic_id: str) -> None:
        """Explicitly register a bidirectional mapping.

        Useful when receiving tool results that reference IDs from
        previous turns in a multi-turn conversation.

        Args:
            openai_id: OpenAI-format tool call ID
            anthropic_id: Anthropic-format tool call ID
        """
        self._to_anthropic[openai_id] = anthropic_id
        self._to_openai[anthropic_id] = openai_id

    def has_anthropic_id(self, anthropic_id: str) -> bool:
        """Check if an Anthropic ID has a known mapping."""
        return anthropic_id in self._to_openai

    def has_openai_id(self, openai_id: str) -> bool:
        """Check if an OpenAI ID has a known mapping."""
        return openai_id in self._to_anthropic
