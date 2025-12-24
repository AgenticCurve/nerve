"""Tests for LLMClient."""

import pytest
from aioresponses import aioresponses

from nerve.gateway.clients.llm_client import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    LLMClient,
    LLMClientConfig,
    UpstreamError,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state_is_closed(self):
        """Circuit breaker should start in CLOSED state."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True

    def test_failures_accumulate(self):
        """Failures should accumulate but not open until threshold."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failures(self):
        """Success should reset failure count."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

        cb.record_failure()
        cb.record_failure()
        cb.record_success()

        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_open_state_rejects_requests(self):
        """Open circuit should reject requests."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30.0)

        cb.record_failure()

        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_half_open_after_timeout(self):
        """Circuit should enter HALF_OPEN after recovery timeout."""
        import time

        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.15)

        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        """Success in HALF_OPEN should close the circuit."""
        import time

        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)

        cb.record_failure()
        time.sleep(0.15)
        cb.can_execute()  # Enters HALF_OPEN

        cb.record_success()

        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_opens_circuit(self):
        """Failure in HALF_OPEN should open the circuit again."""
        import time

        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)

        cb.record_failure()
        time.sleep(0.15)
        cb.can_execute()  # Enters HALF_OPEN

        cb.record_failure()

        assert cb.state == CircuitState.OPEN


class TestLLMClientConfig:
    """Tests for LLMClientConfig defaults."""

    def test_default_values(self):
        """Config should have sensible defaults."""
        config = LLMClientConfig(
            base_url="https://api.example.com",
            api_key="test-key",
            model="gpt-4",
        )

        assert config.connect_timeout == 10.0
        assert config.read_timeout == 300.0
        assert config.max_retries == 3
        assert 429 in config.retryable_status_codes
        assert 500 in config.retryable_status_codes


class TestLLMClientSend:
    """Tests for LLMClient.send() non-streaming method."""

    @pytest.fixture
    def client_config(self):
        return LLMClientConfig(
            base_url="https://api.test.com/v1",
            api_key="test-key",
            model="gpt-4",
            max_retries=2,
            retry_base_delay=0.01,  # Fast retries for testing
        )

    async def test_successful_request(self, client_config):
        """Successful request should return parsed response."""
        client = LLMClient(config=client_config)
        await client.connect()

        try:
            with aioresponses() as m:
                m.post(
                    "https://api.test.com/v1/chat/completions",
                    payload={
                        "choices": [
                            {
                                "message": {"content": "Hello!"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    },
                )

                response = await client.send({"messages": []}, trace_id="test")

                assert response.content == "Hello!"
                assert response.finish_reason == "stop"
        finally:
            await client.close()

    async def test_retry_on_429(self, client_config):
        """Should retry on 429 rate limit."""
        client = LLMClient(config=client_config)
        await client.connect()

        try:
            with aioresponses() as m:
                # First call: 429
                m.post(
                    "https://api.test.com/v1/chat/completions",
                    status=429,
                    body="Rate limited",
                )
                # Second call: success
                m.post(
                    "https://api.test.com/v1/chat/completions",
                    payload={"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]},
                )

                response = await client.send({})

                assert response.content == "OK"
        finally:
            await client.close()

    async def test_non_retryable_error(self, client_config):
        """Non-retryable errors should raise immediately."""
        client = LLMClient(config=client_config)
        await client.connect()

        try:
            with aioresponses() as m:
                m.post(
                    "https://api.test.com/v1/chat/completions",
                    status=401,
                    body="Unauthorized",
                )

                with pytest.raises(UpstreamError) as exc_info:
                    await client.send({})

                assert exc_info.value.status_code == 401
        finally:
            await client.close()

    async def test_circuit_breaker_opens(self, client_config):
        """Circuit breaker should open after repeated failures."""
        client_config.circuit_failure_threshold = 2
        client = LLMClient(config=client_config)
        await client.connect()

        try:
            with aioresponses() as m:
                # Return 500 for all requests
                for _ in range(10):
                    m.post(
                        "https://api.test.com/v1/chat/completions",
                        status=500,
                        body="Server error",
                    )

                # First request fails
                with pytest.raises(UpstreamError):
                    await client.send({})

                # Second request fails and should open circuit
                with pytest.raises(UpstreamError):
                    await client.send({})

                # Third request should be rejected by circuit breaker
                with pytest.raises(CircuitOpenError):
                    await client.send({})
        finally:
            await client.close()

    async def test_client_not_connected_raises(self, client_config):
        """Sending without connecting should raise RuntimeError."""
        client = LLMClient(config=client_config)

        with pytest.raises(RuntimeError, match="not connected"):
            await client.send({})


class TestLLMClientStream:
    """Tests for LLMClient.stream() streaming method."""

    @pytest.fixture
    def client_config(self):
        return LLMClientConfig(
            base_url="https://api.test.com/v1",
            api_key="test-key",
            model="gpt-4",
            max_retries=2,
            retry_base_delay=0.01,
        )

    async def test_successful_stream(self, client_config):
        """Successful stream should yield chunks."""
        client = LLMClient(config=client_config)
        await client.connect()

        try:
            with aioresponses() as m:
                # Simulate SSE response
                sse_response = (
                    b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
                    b'data: {"choices":[{"delta":{"content":" World"}}]}\n\n'
                    b"data: [DONE]\n\n"
                )
                m.post(
                    "https://api.test.com/v1/chat/completions",
                    body=sse_response,
                    headers={"Content-Type": "text/event-stream"},
                )

                chunks = []
                async for chunk in client.stream({}):
                    chunks.append(chunk)

                # Should have at least text chunks and done
                text_chunks = [c for c in chunks if c.type == "text"]
                done_chunks = [c for c in chunks if c.type == "done"]

                assert len(text_chunks) >= 1
                assert len(done_chunks) >= 1
        finally:
            await client.close()

    async def test_stream_retry_on_connection_error(self, client_config):
        """Stream should retry on initial connection failure."""
        client = LLMClient(config=client_config)
        await client.connect()

        try:
            with aioresponses() as m:
                # First call: 503
                m.post(
                    "https://api.test.com/v1/chat/completions",
                    status=503,
                    body="Service unavailable",
                )
                # Second call: success
                m.post(
                    "https://api.test.com/v1/chat/completions",
                    body=b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n',
                )

                chunks = []
                async for chunk in client.stream({}):
                    chunks.append(chunk)

                # Should have gotten the response after retry
                assert any(c.type == "text" for c in chunks)
        finally:
            await client.close()

    async def test_stream_circuit_breaker(self, client_config):
        """Stream should respect circuit breaker."""
        client_config.circuit_failure_threshold = 1
        client = LLMClient(config=client_config)
        await client.connect()

        try:
            with aioresponses() as m:
                for _ in range(5):
                    m.post(
                        "https://api.test.com/v1/chat/completions",
                        status=500,
                        body="Error",
                    )

                # First stream fails and opens circuit
                with pytest.raises(UpstreamError):
                    async for _ in client.stream({}):
                        pass

                # Second stream should be rejected by circuit
                with pytest.raises(CircuitOpenError):
                    async for _ in client.stream({}):
                        pass
        finally:
            await client.close()
