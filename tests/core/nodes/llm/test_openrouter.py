"""Tests for OpenRouterNode."""

import pytest
from aioresponses import aioresponses

from nerve.core.nodes import ExecutionContext, NodeState
from nerve.core.nodes.llm import OpenRouterNode
from nerve.core.session import Session


@pytest.fixture
def session():
    """Create a test session."""
    return Session(name="test-session")


@pytest.fixture
def openrouter_node(session):
    """Create an OpenRouterNode for testing."""
    return OpenRouterNode(
        id="test-llm",
        session=session,
        api_key="test-api-key",
        model="anthropic/claude-3-haiku",
        timeout=5.0,
        max_retries=2,
        retry_base_delay=0.1,  # Fast retries for tests
    )


def make_success_response(content: str = "Hello!", model: str = "anthropic/claude-3-haiku"):
    """Create a mock successful response."""
    return {
        "id": "gen-test123",
        "object": "chat.completion",
        "created": 1234567890,
        "model": model,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": content,
                },
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }


def make_error_response(message: str = "Invalid request"):
    """Create a mock error response."""
    return {"error": {"message": message, "type": "invalid_request_error"}}


class TestOpenRouterNodeBasic:
    """Basic execution tests."""

    @pytest.mark.asyncio
    async def test_string_input(self, session, openrouter_node):
        """Test simple string prompt."""
        with aioresponses() as m:
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                payload=make_success_response("2 + 2 equals 4."),
            )

            context = ExecutionContext(session=session, input="What is 2+2?")
            result = await openrouter_node.execute(context)

            assert result["success"] is True
            assert result["attributes"]["content"] == "2 + 2 equals 4."
            assert result["attributes"]["model"] == "anthropic/claude-3-haiku"
            assert result["attributes"]["finish_reason"] == "stop"
            assert result["error"] is None
            assert result["attributes"]["retries"] == 0

        await openrouter_node.close()

    @pytest.mark.asyncio
    async def test_messages_list_input(self, session, openrouter_node):
        """Test messages array input."""
        with aioresponses() as m:
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                payload=make_success_response("Hello there!"),
            )

            context = ExecutionContext(
                session=session,
                input=[
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "Hi!"},
                ],
            )
            result = await openrouter_node.execute(context)

            assert result["success"] is True
            assert result["attributes"]["content"] == "Hello there!"

        await openrouter_node.close()

    @pytest.mark.asyncio
    async def test_dict_input_with_options(self, session, openrouter_node):
        """Test dict input with messages and extra params."""
        with aioresponses() as m:
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                payload=make_success_response(),
            )

            context = ExecutionContext(
                session=session,
                input={
                    "messages": [{"role": "user", "content": "Test"}],
                    "temperature": 0.5,
                    "max_tokens": 100,
                },
            )
            result = await openrouter_node.execute(context)

            assert result["success"] is True

        await openrouter_node.close()

    @pytest.mark.asyncio
    async def test_empty_input(self, session, openrouter_node):
        """Test handling of empty input."""
        context = ExecutionContext(session=session, input=None)
        result = await openrouter_node.execute(context)

        assert result["success"] is False
        assert "No messages provided" in result["error"]
        assert result["error_type"] == "invalid_request_error"

        await openrouter_node.close()


class TestOpenRouterNodeResponses:
    """Response parsing tests."""

    @pytest.mark.asyncio
    async def test_usage_parsing(self, session, openrouter_node):
        """Test token usage is extracted."""
        with aioresponses() as m:
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                payload=make_success_response(),
            )

            context = ExecutionContext(session=session, input="Test")
            result = await openrouter_node.execute(context)

            assert result["attributes"]["usage"] is not None
            assert result["attributes"]["usage"]["prompt_tokens"] == 10
            assert result["attributes"]["usage"]["completion_tokens"] == 5
            assert result["attributes"]["usage"]["total_tokens"] == 15

        await openrouter_node.close()

    @pytest.mark.asyncio
    async def test_request_echo(self, session, openrouter_node):
        """Test request info is echoed back."""
        with aioresponses() as m:
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                payload=make_success_response(),
            )

            context = ExecutionContext(session=session, input="Hello!")
            result = await openrouter_node.execute(context)

            assert result["attributes"]["request"]["model"] == "anthropic/claude-3-haiku"
            assert len(result["attributes"]["request"]["messages"]) == 1

        await openrouter_node.close()


class TestOpenRouterNodeErrors:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_authentication_error(self, session, openrouter_node):
        """Test 401 response handling."""
        with aioresponses() as m:
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                status=401,
                payload=make_error_response("Invalid API key"),
            )

            context = ExecutionContext(session=session, input="Test")
            result = await openrouter_node.execute(context)

            assert result["success"] is False
            assert "401" in result["error"]
            assert result["error_type"] == "authentication_error"

        await openrouter_node.close()

    @pytest.mark.asyncio
    async def test_invalid_request_error(self, session, openrouter_node):
        """Test 400 response handling."""
        with aioresponses() as m:
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                status=400,
                payload=make_error_response("Invalid model"),
            )

            context = ExecutionContext(session=session, input="Test")
            result = await openrouter_node.execute(context)

            assert result["success"] is False
            assert result["error_type"] == "invalid_request_error"

        await openrouter_node.close()

    @pytest.mark.asyncio
    async def test_rate_limit_error_exhausts_retries(self, session, openrouter_node):
        """Test 429 response triggers retries and eventually fails."""
        with aioresponses() as m:
            # Return 429 three times (initial + 2 retries)
            for _ in range(3):
                m.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    status=429,
                    payload=make_error_response("Rate limited"),
                )

            context = ExecutionContext(session=session, input="Test")
            result = await openrouter_node.execute(context)

            assert result["success"] is False
            assert result["error_type"] == "rate_limit_error"
            assert result["attributes"]["retries"] == 2  # max_retries

        await openrouter_node.close()

    @pytest.mark.asyncio
    async def test_server_error(self, session, openrouter_node):
        """Test 500 response handling."""
        with aioresponses() as m:
            # Return 500 three times
            for _ in range(3):
                m.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    status=500,
                    payload=make_error_response("Internal server error"),
                )

            context = ExecutionContext(session=session, input="Test")
            result = await openrouter_node.execute(context)

            assert result["success"] is False
            assert result["error_type"] == "api_error"

        await openrouter_node.close()


class TestOpenRouterNodeRetry:
    """Retry logic tests."""

    @pytest.mark.asyncio
    async def test_retry_on_429_succeeds(self, session, openrouter_node):
        """Test that 429 triggers retry and eventually succeeds."""
        with aioresponses() as m:
            # First two requests return 429, third succeeds
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                status=429,
                payload=make_error_response("Rate limited"),
            )
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                status=429,
                payload=make_error_response("Rate limited"),
            )
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                payload=make_success_response("Success after retry!"),
            )

            context = ExecutionContext(session=session, input="Test")
            result = await openrouter_node.execute(context)

            assert result["success"] is True
            assert result["attributes"]["content"] == "Success after retry!"
            assert result["attributes"]["retries"] == 2

        await openrouter_node.close()

    @pytest.mark.asyncio
    async def test_retry_on_500_succeeds(self, session, openrouter_node):
        """Test that 500 triggers retry and eventually succeeds."""
        with aioresponses() as m:
            # First request returns 500, second succeeds
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                status=500,
                payload=make_error_response("Server error"),
            )
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                payload=make_success_response("Success!"),
            )

            context = ExecutionContext(session=session, input="Test")
            result = await openrouter_node.execute(context)

            assert result["success"] is True
            assert result["attributes"]["retries"] == 1

        await openrouter_node.close()

    @pytest.mark.asyncio
    async def test_no_retry_on_400(self, session, openrouter_node):
        """Test that 400 does not trigger retry."""
        with aioresponses() as m:
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                status=400,
                payload=make_error_response("Bad request"),
            )

            context = ExecutionContext(session=session, input="Test")
            result = await openrouter_node.execute(context)

            assert result["success"] is False
            assert result["attributes"]["retries"] == 0  # No retries for 400

        await openrouter_node.close()


class TestOpenRouterNodeInfo:
    """Node info tests."""

    def test_to_info(self, openrouter_node):
        """Test to_info returns correct NodeInfo."""
        info = openrouter_node.to_info()

        assert info.id == "test-llm"
        assert info.node_type == "openrouter"
        assert info.state == NodeState.READY
        assert info.persistent is False
        assert info.metadata["model"] == "anthropic/claude-3-haiku"
        assert info.metadata["timeout"] == 5.0

    def test_metadata_included(self, session):
        """Test custom metadata is included."""
        node = OpenRouterNode(
            id="test-meta",
            session=session,
            api_key="key",
            model="model",
            metadata={"custom": "value"},
        )
        info = node.to_info()

        assert info.metadata["custom"] == "value"

    def test_persistent_is_false(self, openrouter_node):
        """Test that persistent property is False."""
        assert openrouter_node.persistent is False

    def test_repr(self, openrouter_node):
        """Test __repr__ returns expected format."""
        assert (
            repr(openrouter_node)
            == "OpenRouterNode(id='test-llm', model='anthropic/claude-3-haiku')"
        )


class TestOpenRouterNodeValidation:
    """Validation tests."""

    def test_duplicate_id_raises(self, session):
        """Test that duplicate ID raises ValueError."""
        OpenRouterNode(id="node1", session=session, api_key="key", model="model")

        with pytest.raises(ValueError, match="already exists"):
            OpenRouterNode(id="node1", session=session, api_key="key", model="model")

    def test_invalid_id_raises(self, session):
        """Test that invalid ID raises ValueError."""
        with pytest.raises(ValueError):
            OpenRouterNode(id="INVALID_ID!", session=session, api_key="key", model="model")

    def test_registers_with_session(self, session):
        """Test that node is registered with session."""
        node = OpenRouterNode(id="registered", session=session, api_key="key", model="model")
        assert "registered" in session.nodes
        assert session.nodes["registered"] is node


class TestOpenRouterNodeSession:
    """HTTP session management tests."""

    @pytest.mark.asyncio
    async def test_session_created_lazily(self, openrouter_node):
        """Test that HTTP session is created on first request."""
        assert openrouter_node._session_holder is None

        with aioresponses() as m:
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                payload=make_success_response(),
            )

            context = ExecutionContext(session=openrouter_node.session, input="Test")
            await openrouter_node.execute(context)

            assert openrouter_node._session_holder is not None

        await openrouter_node.close()

    @pytest.mark.asyncio
    async def test_close_cleans_up_session(self, openrouter_node):
        """Test that close() releases HTTP session."""
        with aioresponses() as m:
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                payload=make_success_response(),
            )

            context = ExecutionContext(session=openrouter_node.session, input="Test")
            await openrouter_node.execute(context)

        await openrouter_node.close()
        assert openrouter_node._session_holder is None

    @pytest.mark.asyncio
    async def test_interrupt_is_noop(self, openrouter_node):
        """Test that interrupt() does nothing (HTTP can't be interrupted)."""
        # Should not raise
        await openrouter_node.interrupt()


class TestOpenRouterNodeCustomConfig:
    """Custom configuration tests."""

    @pytest.mark.asyncio
    async def test_custom_base_url(self, session):
        """Test custom base URL is used."""
        node = OpenRouterNode(
            id="custom-url",
            session=session,
            api_key="key",
            model="model",
            base_url="https://custom.api.com/v1",
        )

        with aioresponses() as m:
            m.post(
                "https://custom.api.com/v1/chat/completions",
                payload=make_success_response(),
            )

            context = ExecutionContext(session=session, input="Test")
            result = await node.execute(context)

            assert result["success"] is True

        await node.close()

    @pytest.mark.asyncio
    async def test_optional_headers(self, session):
        """Test optional HTTP-Referer and X-Title headers."""
        node = OpenRouterNode(
            id="with-headers",
            session=session,
            api_key="key",
            model="model",
            http_referer="https://mysite.com",
            x_title="My App",
        )

        with aioresponses() as m:
            m.post(
                "https://openrouter.ai/api/v1/chat/completions",
                payload=make_success_response(),
            )

            context = ExecutionContext(session=session, input="Test")
            result = await node.execute(context)

            assert result["success"] is True

        await node.close()
