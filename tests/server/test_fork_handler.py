"""Tests for FORK_NODE command handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nerve.core.nodes.llm import OpenRouterNode, StatefulLLMNode
from nerve.core.nodes.llm.chat import Message
from nerve.server.engine import build_nerve_engine
from nerve.server.protocols import Command, CommandType


class MockEventSink:
    """Mock event sink for testing."""

    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


def get_default_session(engine):
    """Helper to get the default session from the engine's session registry."""
    return engine.session_handler.session_registry.default_session


def create_chat_node(
    session, node_id: str, messages: list[Message] | None = None
) -> StatefulLLMNode:
    """Create a StatefulLLMNode for testing."""
    inner_llm = OpenRouterNode(
        id=f"{node_id}-llm",
        session=session,
        api_key="test-key",
        model="test-model",
    )
    node = StatefulLLMNode(
        id=node_id,
        session=session,
        llm=inner_llm,
        system="You are a test assistant.",
    )
    if messages:
        node.messages.extend(messages)
    return node


def create_mock_node_without_fork(node_id: str):
    """Create a mock node that doesn't support forking."""
    mock_node = MagicMock()
    mock_node.id = node_id
    mock_node.stop = AsyncMock()
    # Explicitly don't add fork method
    if hasattr(mock_node, "fork"):
        delattr(mock_node, "fork")
    return mock_node


class TestForkNodeHandler:
    """Tests for FORK_NODE command handler via engine."""

    @pytest.fixture
    def event_sink(self):
        """Create mock event sink."""
        return MockEventSink()

    @pytest.fixture
    def engine(self, event_sink):
        """Create engine with test configuration."""
        return build_nerve_engine(
            event_sink=event_sink,
            server_name="test-server",
        )

    @pytest.mark.asyncio
    async def test_fork_node_success(self, engine):
        """Test successful node fork."""
        session = get_default_session(engine)

        # Create a chat node with some messages
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
        ]
        create_chat_node(session, "original", messages)

        # Fork the node
        result = await engine.execute(
            Command(
                type=CommandType.FORK_NODE,
                params={
                    "source_id": "original",
                    "target_id": "forked",
                },
            )
        )

        assert result.success is True
        assert result.data["node_id"] == "forked"
        assert result.data["forked_from"] == "original"

        # Verify forked node exists in session
        assert "forked" in session.nodes
        forked_node = session.nodes["forked"]
        assert isinstance(forked_node, StatefulLLMNode)
        assert len(forked_node.messages) == 2

    @pytest.mark.asyncio
    async def test_fork_node_source_not_found(self, engine):
        """Test fork fails when source node doesn't exist."""
        result = await engine.execute(
            Command(
                type=CommandType.FORK_NODE,
                params={
                    "source_id": "nonexistent",
                    "target_id": "forked",
                },
            )
        )

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fork_node_target_exists(self, engine):
        """Test fork fails when target ID already exists."""
        session = get_default_session(engine)

        # Create source node
        create_chat_node(session, "source")

        # Create target node (will conflict)
        create_chat_node(session, "target")

        result = await engine.execute(
            Command(
                type=CommandType.FORK_NODE,
                params={
                    "source_id": "source",
                    "target_id": "target",
                },
            )
        )

        assert result.success is False
        assert "already exists" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fork_node_not_supported(self, engine):
        """Test fork fails for nodes that don't support forking."""
        session = get_default_session(engine)

        # Create a mock node without fork support
        mock_node = create_mock_node_without_fork("mock-node")
        session.nodes["mock-node"] = mock_node

        result = await engine.execute(
            Command(
                type=CommandType.FORK_NODE,
                params={
                    "source_id": "mock-node",
                    "target_id": "forked",
                },
            )
        )

        assert result.success is False
        assert "does not support forking" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fork_node_missing_source_id(self, engine):
        """Test fork fails when source_id is missing."""
        result = await engine.execute(
            Command(
                type=CommandType.FORK_NODE,
                params={
                    "target_id": "forked",
                },
            )
        )

        assert result.success is False
        assert "source_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fork_node_missing_target_id(self, engine):
        """Test fork fails when target_id is missing."""
        session = get_default_session(engine)
        create_chat_node(session, "source")

        result = await engine.execute(
            Command(
                type=CommandType.FORK_NODE,
                params={
                    "source_id": "source",
                },
            )
        )

        assert result.success is False
        assert "target_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fork_preserves_conversation_history(self, engine):
        """Test that fork preserves full conversation history."""
        session = get_default_session(engine)

        # Create node with substantial conversation
        messages = [
            Message(role="user", content="What is Python?"),
            Message(role="assistant", content="Python is a programming language."),
            Message(role="user", content="What can I do with it?"),
            Message(role="assistant", content="You can build web apps, scripts, and more."),
            Message(role="user", content="Show me an example"),
            Message(role="assistant", content="Here's a simple example: print('Hello')"),
        ]
        create_chat_node(session, "python-chat", messages)

        # Fork the node
        result = await engine.execute(
            Command(
                type=CommandType.FORK_NODE,
                params={
                    "source_id": "python-chat",
                    "target_id": "python-fork",
                },
            )
        )

        assert result.success is True

        # Verify forked node has all messages
        forked = session.nodes["python-fork"]
        assert len(forked.messages) == 6
        assert forked.messages[0].content == "What is Python?"
        assert forked.messages[-1].content == "Here's a simple example: print('Hello')"

    @pytest.mark.asyncio
    async def test_fork_emits_node_created_event(self, engine, event_sink):
        """Test that fork emits a NODE_CREATED event."""
        session = get_default_session(engine)
        create_chat_node(session, "source")

        await engine.execute(
            Command(
                type=CommandType.FORK_NODE,
                params={
                    "source_id": "source",
                    "target_id": "forked",
                },
            )
        )

        # Check that NODE_CREATED event was emitted
        created_events = [e for e in event_sink.events if e.type.name == "NODE_CREATED"]
        assert len(created_events) >= 1

        # Find the event for our forked node
        fork_event = next((e for e in created_events if e.node_id == "forked"), None)
        assert fork_event is not None
        assert fork_event.data.get("forked_from") == "source"

    @pytest.mark.asyncio
    async def test_fork_with_session_id(self, engine):
        """Test fork works with explicit session_id parameter."""
        session = get_default_session(engine)
        session_id = session.id

        create_chat_node(session, "source")

        result = await engine.execute(
            Command(
                type=CommandType.FORK_NODE,
                params={
                    "source_id": "source",
                    "target_id": "forked",
                    "session_id": session_id,
                },
            )
        )

        assert result.success is True
        assert "forked" in session.nodes


class TestForkNodeIndependence:
    """Tests verifying fork creates independent node."""

    @pytest.fixture
    def event_sink(self):
        return MockEventSink()

    @pytest.fixture
    def engine(self, event_sink):
        return build_nerve_engine(
            event_sink=event_sink,
            server_name="test-server",
        )

    @pytest.mark.asyncio
    async def test_forked_node_is_independent(self, engine):
        """Test that changes to forked node don't affect original."""
        session = get_default_session(engine)

        # Create and fork
        messages = [Message(role="user", content="Hello")]
        create_chat_node(session, "original", messages)

        await engine.execute(
            Command(
                type=CommandType.FORK_NODE,
                params={"source_id": "original", "target_id": "forked"},
            )
        )

        # Modify the forked node
        forked = session.nodes["forked"]
        forked.messages.append(Message(role="assistant", content="New message"))

        # Original should be unchanged
        original = session.nodes["original"]
        assert len(original.messages) == 1
        assert len(forked.messages) == 2

    @pytest.mark.asyncio
    async def test_multiple_forks_are_independent(self, engine):
        """Test that multiple forks are all independent."""
        session = get_default_session(engine)

        messages = [Message(role="user", content="Start")]
        create_chat_node(session, "source", messages)

        # Create multiple forks
        for i in range(3):
            await engine.execute(
                Command(
                    type=CommandType.FORK_NODE,
                    params={"source_id": "source", "target_id": f"fork{i}"},
                )
            )

        # Modify each fork differently
        session.nodes["fork0"].messages.append(Message(role="user", content="Fork 0"))
        session.nodes["fork1"].messages.append(Message(role="user", content="Fork 1"))
        session.nodes["fork1"].messages.append(Message(role="user", content="Fork 1 again"))

        # Verify independence
        assert len(session.nodes["source"].messages) == 1
        assert len(session.nodes["fork0"].messages) == 2
        assert len(session.nodes["fork1"].messages) == 3
        assert len(session.nodes["fork2"].messages) == 1
