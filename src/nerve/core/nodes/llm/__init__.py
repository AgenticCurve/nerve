"""LLM provider nodes for direct API calls.

Two types of LLM nodes:

**Stateless nodes** (persistent=False):
    StatelessLLMNode: Abstract base class for stateless LLM API calls
    OpenRouterNode: OpenRouter API (OpenAI-compatible, supports 100+ models)
    GLMNode: Z.AI GLM API (supports thinking mode)

**Stateful nodes** (persistent=True):
    StatefulLLMNode: Multi-turn conversations with tool support

Example (stateless):
    >>> from nerve.core.nodes.llm import OpenRouterNode, GLMNode
    >>> from nerve.core.nodes import ExecutionContext
    >>> from nerve.core.session import Session
    >>>
    >>> session = Session(name="my-session")
    >>>
    >>> # OpenRouter - single request
    >>> llm = OpenRouterNode(
    ...     id="llm",
    ...     session=session,
    ...     api_key="sk-or-...",
    ...     model="anthropic/claude-3-haiku",
    ... )
    >>> result = await llm.execute(ExecutionContext(session=session, input="Hello!"))
    >>>
    >>> # GLM with thinking mode
    >>> glm = GLMNode(
    ...     id="glm",
    ...     session=session,
    ...     api_key="your-api-key",
    ...     model="glm-4.7",
    ...     thinking=True,
    ... )
    >>> result = await glm.execute(ExecutionContext(session=session, input="Solve: 15 * 23"))

Example (chat with history):
    >>> from nerve.core.nodes.llm import StatefulLLMNode, OpenRouterNode
    >>>
    >>> # Create chat node wrapping an LLM provider
    >>> llm = OpenRouterNode(id="llm", session=session, api_key="...", model="...")
    >>> chat = StatefulLLMNode(
    ...     id="chat",
    ...     session=session,
    ...     llm=llm,
    ...     system="You are a helpful assistant.",
    ... )
    >>>
    >>> # Multi-turn conversation - state accumulates
    >>> await chat.execute(ctx(input="What is 2+2?"))
    >>> await chat.execute(ctx(input="Double that"))  # Remembers previous context
"""

from nerve.core.nodes.llm.base import StatelessLLMNode
from nerve.core.nodes.llm.chat import Message, StatefulLLMNode, ToolDefinition
from nerve.core.nodes.llm.glm import GLMNode
from nerve.core.nodes.llm.openrouter import OpenRouterNode

__all__ = [
    "GLMNode",
    "Message",
    "OpenRouterNode",
    "StatefulLLMNode",
    "StatelessLLMNode",
    "ToolDefinition",
]
