"""Tests for StatefulLLMNode.fork() functionality."""

from __future__ import annotations

import copy

import pytest

from nerve.core.nodes.llm import OpenRouterNode, StatefulLLMNode
from nerve.core.nodes.llm.chat import Message
from nerve.core.session.session import Session


@pytest.fixture
def session() -> Session:
    """Create a test session."""
    return Session(name="test-session")


@pytest.fixture
def inner_llm(session: Session) -> OpenRouterNode:
    """Create an inner LLM node for chat nodes."""
    return OpenRouterNode(
        id="test-llm",
        session=session,
        api_key="test-key",
        model="test-model",
    )


@pytest.fixture
def chat_node(session: Session, inner_llm: OpenRouterNode) -> StatefulLLMNode:
    """Create a chat node with some messages."""
    node = StatefulLLMNode(
        id="original",
        session=session,
        llm=inner_llm,
        system="You are a helpful assistant.",
    )
    # Add some conversation history
    node.messages.append(Message(role="user", content="Hello!"))
    node.messages.append(Message(role="assistant", content="Hi there! How can I help?"))
    node.messages.append(Message(role="user", content="What is 2+2?"))
    node.messages.append(Message(role="assistant", content="2+2 equals 4."))
    return node


class TestStatefulLLMNodeFork:
    """Tests for StatefulLLMNode.fork() method."""

    async def test_fork_creates_new_node(
        self, session: Session, chat_node: StatefulLLMNode
    ) -> None:
        """fork() should create a new node with the given ID."""
        forked = chat_node.fork("forked")

        assert forked.id == "forked"
        assert forked is not chat_node
        assert "forked" in session.nodes
        assert session.nodes["forked"] is forked

    async def test_fork_copies_messages(self, session: Session, chat_node: StatefulLLMNode) -> None:
        """fork() should deep copy all messages."""
        forked = chat_node.fork("forked")

        # Same number of messages
        assert len(forked.messages) == len(chat_node.messages)

        # Same content
        for orig, copied in zip(chat_node.messages, forked.messages, strict=True):
            assert orig.role == copied.role
            assert orig.content == copied.content

    async def test_fork_messages_are_independent(
        self, session: Session, chat_node: StatefulLLMNode
    ) -> None:
        """Changes to forked messages should not affect original."""
        original_count = len(chat_node.messages)
        forked = chat_node.fork("forked")

        # Add message to forked node
        forked.messages.append(Message(role="user", content="New message"))

        # Original should be unchanged
        assert len(chat_node.messages) == original_count
        assert len(forked.messages) == original_count + 1

    async def test_fork_copies_system_prompt(
        self, session: Session, chat_node: StatefulLLMNode
    ) -> None:
        """fork() should copy the system prompt."""
        forked = chat_node.fork("forked")

        assert forked.system == chat_node.system
        assert forked.system == "You are a helpful assistant."

    async def test_fork_sets_metadata(self, session: Session, chat_node: StatefulLLMNode) -> None:
        """fork() should set fork-related metadata."""
        forked = chat_node.fork("forked")

        assert "forked_from" in forked.metadata
        assert forked.metadata["forked_from"] == "original"
        assert "fork_timestamp" in forked.metadata
        assert isinstance(forked.metadata["fork_timestamp"], float)

    async def test_fork_creates_new_inner_llm(
        self, session: Session, chat_node: StatefulLLMNode
    ) -> None:
        """fork() should create a new inner LLM node."""
        original_llm_id = chat_node.llm.id
        forked = chat_node.fork("forked")

        # New inner LLM should have different ID
        assert forked.llm.id != original_llm_id
        assert forked.llm.id == "forked-llm"

        # But same configuration
        assert forked.llm.model == chat_node.llm.model
        assert forked.llm.api_key == chat_node.llm.api_key

    async def test_fork_validates_unique_id(
        self, session: Session, chat_node: StatefulLLMNode
    ) -> None:
        """fork() should raise ValueError if target ID already exists."""
        # Create another node with the target ID
        OpenRouterNode(
            id="existing",
            session=session,
            api_key="test-key",
            model="test-model",
        )

        with pytest.raises(ValueError, match="conflicts"):
            chat_node.fork("existing")

    async def test_fork_empty_messages(self, session: Session, inner_llm: OpenRouterNode) -> None:
        """fork() should work with empty message history."""
        node = StatefulLLMNode(
            id="empty",
            session=session,
            llm=inner_llm,
            system="Test system prompt",
        )

        forked = node.fork("forked")

        assert len(forked.messages) == 0
        assert forked.system == "Test system prompt"

    async def test_fork_preserves_tools_config(
        self, session: Session, inner_llm: OpenRouterNode
    ) -> None:
        """fork() should preserve tool configuration."""
        # Create node with tool configuration
        node = StatefulLLMNode(
            id="with-tools",
            session=session,
            llm=inner_llm,
            tools=[{"type": "function", "function": {"name": "test_tool"}}],
            tool_choice="auto",
            parallel_tool_calls=True,
            max_tool_rounds=5,
        )

        forked = node.fork("forked")

        assert forked.tools == node.tools
        assert forked.tool_choice == "auto"
        assert forked.parallel_tool_calls is True
        assert forked.max_tool_rounds == 5

    async def test_fork_deep_copies_tool_calls_in_messages(
        self, session: Session, inner_llm: OpenRouterNode
    ) -> None:
        """fork() should deep copy tool_calls in messages."""
        node = StatefulLLMNode(
            id="with-tool-calls",
            session=session,
            llm=inner_llm,
        )

        # Add message with tool calls
        tool_calls = [
            {"id": "call_1", "type": "function", "function": {"name": "test", "arguments": "{}"}}
        ]
        node.messages.append(
            Message(role="assistant", content=None, tool_calls=copy.deepcopy(tool_calls))
        )
        node.messages.append(
            Message(role="tool", content="result", tool_call_id="call_1", name="test")
        )

        forked = node.fork("forked")

        # Verify tool_calls are copied
        assert forked.messages[0].tool_calls is not None
        assert forked.messages[0].tool_calls[0]["id"] == "call_1"

        # Verify independence - mutate original
        node.messages[0].tool_calls[0]["id"] = "mutated"
        assert forked.messages[0].tool_calls[0]["id"] == "call_1"

    async def test_fork_preserves_original_metadata(
        self, session: Session, inner_llm: OpenRouterNode
    ) -> None:
        """fork() should preserve original metadata and add fork metadata."""
        node = StatefulLLMNode(
            id="with-metadata",
            session=session,
            llm=inner_llm,
            metadata={"custom_key": "custom_value", "another": 123},
        )

        forked = node.fork("forked")

        # Original metadata should be preserved
        assert forked.metadata["custom_key"] == "custom_value"
        assert forked.metadata["another"] == 123

        # Fork metadata should be added
        assert forked.metadata["forked_from"] == "with-metadata"
        assert "fork_timestamp" in forked.metadata

    async def test_multiple_forks_from_same_source(
        self, session: Session, chat_node: StatefulLLMNode
    ) -> None:
        """Multiple forks from the same source should all be independent."""
        fork1 = chat_node.fork("fork1")
        fork2 = chat_node.fork("fork2")
        fork3 = chat_node.fork("fork3")

        # All should exist independently
        assert "fork1" in session.nodes
        assert "fork2" in session.nodes
        assert "fork3" in session.nodes

        # Add different messages to each
        fork1.messages.append(Message(role="user", content="Fork 1 message"))
        fork2.messages.append(Message(role="user", content="Fork 2 message"))

        # Each should have different message counts
        original_count = len(chat_node.messages)
        assert len(fork1.messages) == original_count + 1
        assert len(fork2.messages) == original_count + 1
        assert len(fork3.messages) == original_count

    async def test_fork_chain(self, session: Session, chat_node: StatefulLLMNode) -> None:
        """Should be able to fork a forked node."""
        fork1 = chat_node.fork("fork1")
        fork1.messages.append(Message(role="user", content="Fork 1 addition"))

        fork2 = fork1.fork("fork2")

        # fork2 should have fork1's messages
        assert len(fork2.messages) == len(fork1.messages)
        assert fork2.messages[-1].content == "Fork 1 addition"

        # fork2's metadata should reference fork1
        assert fork2.metadata["forked_from"] == "fork1"


class TestForkEdgeCases:
    """Edge case tests for fork functionality."""

    async def test_fork_with_none_system_prompt(
        self, session: Session, inner_llm: OpenRouterNode
    ) -> None:
        """fork() should handle None system prompt."""
        node = StatefulLLMNode(
            id="no-system",
            session=session,
            llm=inner_llm,
            system=None,
        )

        forked = node.fork("forked")

        assert forked.system is None

    async def test_fork_with_empty_string_system_prompt(
        self, session: Session, inner_llm: OpenRouterNode
    ) -> None:
        """fork() should handle empty string system prompt."""
        node = StatefulLLMNode(
            id="empty-system",
            session=session,
            llm=inner_llm,
            system="",
        )

        forked = node.fork("forked")

        assert forked.system == ""

    async def test_fork_preserves_tool_executor(
        self, session: Session, inner_llm: OpenRouterNode
    ) -> None:
        """fork() should preserve tool_executor reference."""

        async def mock_executor(tool_name, args):
            return {"result": "test"}

        node = StatefulLLMNode(
            id="with-executor",
            session=session,
            llm=inner_llm,
            tool_executor=mock_executor,
        )

        forked = node.fork("forked")

        # Should share the same executor reference
        assert forked.tool_executor is mock_executor
