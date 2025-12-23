"""Tests for nerve.core.nodes.budget module."""

import time

import pytest

from nerve.core.nodes.budget import Budget, BudgetExceededError, ResourceUsage


class TestBudget:
    """Tests for Budget dataclass."""

    def test_default_values(self):
        """Test default values (no limits)."""
        budget = Budget()

        assert budget.max_tokens is None
        assert budget.max_time_seconds is None
        assert budget.max_steps is None
        assert budget.max_api_calls is None
        assert budget.max_cost_dollars is None

    def test_token_limit(self):
        """Test token limit configuration."""
        budget = Budget(max_tokens=10000)
        assert budget.max_tokens == 10000

    def test_time_limit(self):
        """Test time limit configuration."""
        budget = Budget(max_time_seconds=60.0)
        assert budget.max_time_seconds == 60.0

    def test_step_limit(self):
        """Test step limit configuration."""
        budget = Budget(max_steps=100)
        assert budget.max_steps == 100

    def test_api_call_limit(self):
        """Test API call limit configuration."""
        budget = Budget(max_api_calls=50)
        assert budget.max_api_calls == 50

    def test_cost_limit(self):
        """Test cost limit configuration."""
        budget = Budget(max_cost_dollars=10.0)
        assert budget.max_cost_dollars == 10.0

    def test_is_limited_true(self):
        """Test is_limited returns True when limits set."""
        budget = Budget(max_tokens=100)
        assert budget.is_limited() is True

    def test_is_limited_false(self):
        """Test is_limited returns False when no limits."""
        budget = Budget()
        assert budget.is_limited() is False


class TestResourceUsage:
    """Tests for ResourceUsage dataclass."""

    def test_default_values(self):
        """Test default values."""
        usage = ResourceUsage()

        assert usage.tokens_used == 0
        assert usage.steps_executed == 0
        assert usage.api_calls == 0
        assert usage.cost_dollars == 0.0

    def test_add_tokens(self):
        """Test add_tokens method."""
        usage = ResourceUsage()
        usage.add_tokens(100)
        assert usage.tokens_used == 100

        usage.add_tokens(50)
        assert usage.tokens_used == 150

    def test_add_step(self):
        """Test add_step method."""
        usage = ResourceUsage()
        usage.add_step()
        assert usage.steps_executed == 1

        usage.add_step()
        assert usage.steps_executed == 2

    def test_add_api_call(self):
        """Test add_api_call method."""
        usage = ResourceUsage()
        usage.add_api_call()
        assert usage.api_calls == 1

    def test_add_cost(self):
        """Test add_cost method."""
        usage = ResourceUsage()
        usage.add_cost(0.01)
        assert usage.cost_dollars == 0.01

        usage.add_cost(0.02)
        assert usage.cost_dollars == pytest.approx(0.03)

    def test_time_elapsed(self):
        """Test time_elapsed_seconds property."""
        usage = ResourceUsage()

        # Should be nearly instant
        assert usage.time_elapsed_seconds < 1.0

        # Wait a bit
        time.sleep(0.1)
        assert usage.time_elapsed_seconds >= 0.1

    def test_exceeds_tokens(self):
        """Test exceeds check for tokens."""
        budget = Budget(max_tokens=100)
        usage = ResourceUsage(tokens_used=150)

        exceeded, reason = usage.exceeds(budget)
        assert exceeded is True
        assert "Token limit" in reason

    def test_exceeds_steps(self):
        """Test exceeds check for steps."""
        budget = Budget(max_steps=5)
        usage = ResourceUsage(steps_executed=10)

        exceeded, reason = usage.exceeds(budget)
        assert exceeded is True
        assert "Step limit" in reason

    def test_exceeds_api_calls(self):
        """Test exceeds check for API calls."""
        budget = Budget(max_api_calls=10)
        usage = ResourceUsage(api_calls=15)

        exceeded, reason = usage.exceeds(budget)
        assert exceeded is True
        assert "API call limit" in reason

    def test_exceeds_cost(self):
        """Test exceeds check for cost."""
        budget = Budget(max_cost_dollars=1.0)
        usage = ResourceUsage(cost_dollars=1.50)

        exceeded, reason = usage.exceeds(budget)
        assert exceeded is True
        assert "Cost limit" in reason

    def test_not_exceeded(self):
        """Test exceeds returns False when under limits."""
        budget = Budget(max_tokens=1000, max_steps=100)
        usage = ResourceUsage(tokens_used=500, steps_executed=50)

        exceeded, reason = usage.exceeds(budget)
        assert exceeded is False
        assert reason is None

    def test_not_exceeded_no_limits(self):
        """Test exceeds returns False with no limits."""
        budget = Budget()
        usage = ResourceUsage(tokens_used=1000000, steps_executed=10000)

        exceeded, reason = usage.exceeds(budget)
        assert exceeded is False

    def test_parent_tracking(self):
        """Test that child usage propagates to parent."""
        parent = ResourceUsage()
        child = ResourceUsage(_parent_usage=parent)

        # Add usage to child
        child.add_tokens(100)
        child.add_step()
        child.add_api_call()
        child.add_cost(0.05)

        # Child should have the values
        assert child.tokens_used == 100
        assert child.steps_executed == 1
        assert child.api_calls == 1
        assert child.cost_dollars == pytest.approx(0.05)

        # Parent should also have the values
        assert parent.tokens_used == 100
        assert parent.steps_executed == 1
        assert parent.api_calls == 1
        assert parent.cost_dollars == pytest.approx(0.05)

    def test_nested_parent_tracking(self):
        """Test that nested parent tracking propagates through chain."""
        grandparent = ResourceUsage()
        parent = ResourceUsage(_parent_usage=grandparent)
        child = ResourceUsage(_parent_usage=parent)

        # Add usage to child
        child.add_tokens(50)

        # All should have the tokens
        assert child.tokens_used == 50
        assert parent.tokens_used == 50
        assert grandparent.tokens_used == 50


class TestBudgetExceededError:
    """Tests for BudgetExceededError."""

    def test_creation(self):
        """Test error creation with details."""
        budget = Budget(max_tokens=100)
        usage = ResourceUsage(tokens_used=150)
        reason = "Token limit exceeded"

        error = BudgetExceededError(usage, budget, reason)

        assert error.usage is usage
        assert error.budget is budget
        assert error.reason == reason
        assert str(error) == reason

    def test_as_exception(self):
        """Test raising and catching the error."""
        budget = Budget(max_tokens=100)
        usage = ResourceUsage(tokens_used=150)

        with pytest.raises(BudgetExceededError) as exc_info:
            raise BudgetExceededError(usage, budget, "Test error")

        assert exc_info.value.budget.max_tokens == 100
        assert exc_info.value.usage.tokens_used == 150
