"""Tests for nerve.core.nodes.policies module."""

import pytest

from nerve.core.nodes.base import FunctionNode
from nerve.core.nodes.policies import ErrorPolicy
from nerve.core.session.session import Session


class TestErrorPolicy:
    """Tests for ErrorPolicy dataclass."""

    @pytest.fixture
    def session(self):
        """Create a test session."""
        return Session(name="test-session")

    def test_default_values(self):
        """Test default values."""
        policy = ErrorPolicy()

        assert policy.on_error == "fail"
        assert policy.retry_count == 0
        assert policy.retry_delay_ms == 1000
        assert policy.retry_backoff == 2.0
        assert policy.timeout_ms is None
        assert policy.fallback_value is None
        assert policy.fallback_node is None

    def test_retry_policy(self):
        """Test retry policy configuration."""
        policy = ErrorPolicy(
            on_error="retry",
            retry_count=3,
            retry_delay_ms=500,
            retry_backoff=1.5,
        )

        assert policy.on_error == "retry"
        assert policy.retry_count == 3
        assert policy.retry_delay_ms == 500
        assert policy.retry_backoff == 1.5

    def test_skip_policy(self):
        """Test skip policy with fallback value."""
        policy = ErrorPolicy(
            on_error="skip",
            fallback_value={"default": True},
        )

        assert policy.on_error == "skip"
        assert policy.fallback_value == {"default": True}

    def test_fallback_policy(self, session):
        """Test fallback policy with fallback node."""
        fallback_node = FunctionNode(id="fallback", session=session, fn=lambda ctx: "default")
        policy = ErrorPolicy(
            on_error="fallback",
            fallback_node=fallback_node,
        )

        assert policy.on_error == "fallback"
        assert policy.fallback_node is fallback_node

    def test_retry_without_count_raises(self):
        """Test retry policy without retry_count raises error."""
        with pytest.raises(ValueError, match="retry_count must be > 0"):
            ErrorPolicy(on_error="retry", retry_count=0)

    def test_fallback_without_node_raises(self):
        """Test fallback policy without node raises error."""
        with pytest.raises(ValueError, match="fallback_node must be set"):
            ErrorPolicy(on_error="fallback")

    def test_negative_retry_count_raises(self):
        """Test negative retry_count raises error."""
        with pytest.raises(ValueError, match="cannot be negative"):
            ErrorPolicy(retry_count=-1)

    def test_negative_delay_raises(self):
        """Test negative retry_delay_ms raises error."""
        with pytest.raises(ValueError, match="cannot be negative"):
            ErrorPolicy(retry_delay_ms=-100)

    def test_backoff_less_than_one_raises(self):
        """Test backoff < 1.0 raises error."""
        with pytest.raises(ValueError, match="must be >= 1.0"):
            ErrorPolicy(retry_backoff=0.5)

    def test_get_delay_for_attempt(self):
        """Test delay calculation with backoff."""
        policy = ErrorPolicy(
            retry_delay_ms=1000,  # 1 second
            retry_backoff=2.0,
        )

        # First attempt: 1000ms = 1s
        assert policy.get_delay_for_attempt(0) == 1.0

        # Second attempt: 1000ms * 2.0 = 2s
        assert policy.get_delay_for_attempt(1) == 2.0

        # Third attempt: 1000ms * 4.0 = 4s
        assert policy.get_delay_for_attempt(2) == 4.0

    def test_should_retry(self):
        """Test should_retry logic."""
        policy = ErrorPolicy(
            on_error="retry",
            retry_count=3,
        )

        assert policy.should_retry(0) is True  # Can retry
        assert policy.should_retry(1) is True
        assert policy.should_retry(2) is True
        assert policy.should_retry(3) is False  # No more retries

    def test_timeout_policy(self):
        """Test timeout configuration."""
        policy = ErrorPolicy(timeout_ms=5000)
        assert policy.timeout_ms == 5000
