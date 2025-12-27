"""Tests for LLMChatNode."""

import pytest

from nerve.core.nodes.llm import LLMChatNode, OpenRouterNode
from nerve.core.session.session import Session


@pytest.fixture
def session() -> Session:
    """Create a test session."""
    return Session(name="test-session")


class TestLLMChatNodeStop:
    """Tests for LLMChatNode.stop() method."""

    async def test_stop_removes_inner_node_from_session(self, session: Session) -> None:
        """stop() should remove the inner LLM node from session.nodes."""
        # Create inner LLM node (simulating what NodeFactory does)
        inner_llm = OpenRouterNode(
            id="chat-llm",
            session=session,
            api_key="test-key",
            model="test-model",
        )

        # Create chat node wrapping the inner LLM
        chat_node = LLMChatNode(
            id="chat",
            session=session,
            llm=inner_llm,
            system="You are helpful.",
        )

        # Both nodes should be registered
        assert "chat" in session.nodes
        assert "chat-llm" in session.nodes

        # Stop the chat node
        await chat_node.stop()

        # Both nodes should be removed
        assert "chat" not in session.nodes
        assert "chat-llm" not in session.nodes

    async def test_stop_is_idempotent(self, session: Session) -> None:
        """stop() can be called multiple times safely."""
        inner_llm = OpenRouterNode(
            id="chat-llm",
            session=session,
            api_key="test-key",
            model="test-model",
        )
        chat_node = LLMChatNode(
            id="chat",
            session=session,
            llm=inner_llm,
        )

        # Stop multiple times should not raise
        await chat_node.stop()
        await chat_node.stop()

        assert "chat" not in session.nodes
        assert "chat-llm" not in session.nodes

    async def test_session_delete_node_cleans_up_inner_node(self, session: Session) -> None:
        """session.delete_node() should clean up inner node via stop()."""
        inner_llm = OpenRouterNode(
            id="chat-llm",
            session=session,
            api_key="test-key",
            model="test-model",
        )
        LLMChatNode(
            id="chat",
            session=session,
            llm=inner_llm,
        )

        # Both nodes registered
        assert "chat" in session.nodes
        assert "chat-llm" in session.nodes

        # Delete via session (this calls stop() internally)
        deleted = await session.delete_node("chat")

        assert deleted is True
        # Inner node should also be removed
        assert "chat-llm" not in session.nodes


class TestLLMChatNodeBasic:
    """Basic tests for LLMChatNode."""

    async def test_registers_with_session(self, session: Session) -> None:
        """Chat node should register with session on creation."""
        inner_llm = OpenRouterNode(
            id="llm",
            session=session,
            api_key="test-key",
            model="test-model",
        )
        chat_node = LLMChatNode(
            id="chat",
            session=session,
            llm=inner_llm,
        )

        assert "chat" in session.nodes
        assert session.nodes["chat"] is chat_node

    async def test_persistent_is_true(self, session: Session) -> None:
        """Chat nodes should be marked as persistent."""
        inner_llm = OpenRouterNode(
            id="llm",
            session=session,
            api_key="test-key",
            model="test-model",
        )
        chat_node = LLMChatNode(
            id="chat",
            session=session,
            llm=inner_llm,
        )

        assert chat_node.persistent is True
        assert chat_node.to_info().persistent is True

    async def test_clear_messages(self, session: Session) -> None:
        """clear() should empty the message history."""
        inner_llm = OpenRouterNode(
            id="llm",
            session=session,
            api_key="test-key",
            model="test-model",
        )
        chat_node = LLMChatNode(
            id="chat",
            session=session,
            llm=inner_llm,
        )

        # Add some messages manually
        from nerve.core.nodes.llm.chat import Message

        chat_node.messages.append(Message(role="user", content="Hello"))
        chat_node.messages.append(Message(role="assistant", content="Hi!"))

        assert len(chat_node.messages) == 2

        chat_node.clear()

        assert len(chat_node.messages) == 0

    async def test_get_messages_includes_system(self, session: Session) -> None:
        """get_messages() should include system prompt."""
        inner_llm = OpenRouterNode(
            id="llm",
            session=session,
            api_key="test-key",
            model="test-model",
        )
        chat_node = LLMChatNode(
            id="chat",
            session=session,
            llm=inner_llm,
            system="You are a helpful assistant.",
        )

        messages = chat_node.get_messages()

        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant."
