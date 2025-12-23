"""Tests for nerve.core.nodes.context module."""

import pytest

from nerve.core.nodes.budget import Budget, BudgetExceededError, ResourceUsage
from nerve.core.nodes.cancellation import CancelledException, CancellationToken
from nerve.core.nodes.context import ExecutionContext
from nerve.core.session.session import Session
from nerve.core.types import ParserType


class TestExecutionContext:
    """Tests for ExecutionContext."""

    def test_basic_creation(self):
        """Test basic context creation."""
        session = Session()
        context = ExecutionContext(session=session)

        assert context.session is session
        assert context.input is None
        assert context.upstream == {}
        assert context.parser is None
        assert context.timeout is None

    def test_creation_with_all_fields(self):
        """Test context with all fields."""
        session = Session()
        budget = Budget(max_tokens=100)
        usage = ResourceUsage()
        token = CancellationToken()

        context = ExecutionContext(
            session=session,
            input="test input",
            upstream={"prev": "result"},
            parser=ParserType.CLAUDE,
            timeout=30.0,
            budget=budget,
            usage=usage,
            cancellation=token,
        )

        assert context.input == "test input"
        assert context.upstream["prev"] == "result"
        assert context.parser == ParserType.CLAUDE
        assert context.timeout == 30.0
        assert context.budget is budget
        assert context.usage is usage
        assert context.cancellation is token

    def test_with_input(self):
        """Test with_input creates new context."""
        session = Session()
        context = ExecutionContext(session=session, input="original")

        new_context = context.with_input("new")

        assert new_context.input == "new"
        assert context.input == "original"  # Original unchanged
        assert new_context.session is context.session

    def test_with_upstream(self):
        """Test with_upstream merges upstream dict."""
        session = Session()
        context = ExecutionContext(
            session=session, upstream={"a": 1, "b": 2}
        )

        new_context = context.with_upstream({"c": 3, "b": 99})

        assert new_context.upstream == {"a": 1, "b": 99, "c": 3}
        assert context.upstream == {"a": 1, "b": 2}  # Original unchanged

    def test_with_parser(self):
        """Test with_parser creates new context."""
        session = Session()
        context = ExecutionContext(session=session)

        new_context = context.with_parser(ParserType.CLAUDE)

        assert new_context.parser == ParserType.CLAUDE
        assert context.parser is None

    def test_check_cancelled_not_cancelled(self):
        """Test check_cancelled when not cancelled."""
        session = Session()
        token = CancellationToken()
        context = ExecutionContext(session=session, cancellation=token)

        # Should not raise
        context.check_cancelled()

    def test_check_cancelled_when_cancelled(self):
        """Test check_cancelled when cancelled."""
        session = Session()
        token = CancellationToken()
        token.cancel()
        context = ExecutionContext(session=session, cancellation=token)

        with pytest.raises(CancelledException):
            context.check_cancelled()

    def test_check_cancelled_no_token(self):
        """Test check_cancelled with no token."""
        session = Session()
        context = ExecutionContext(session=session)

        # Should not raise
        context.check_cancelled()

    def test_check_budget_not_exceeded(self):
        """Test check_budget when not exceeded."""
        session = Session()
        budget = Budget(max_steps=10)
        usage = ResourceUsage(steps_executed=5)
        context = ExecutionContext(
            session=session, budget=budget, usage=usage
        )

        # Should not raise
        context.check_budget()

    def test_check_budget_exceeded(self):
        """Test check_budget when exceeded."""
        session = Session()
        budget = Budget(max_steps=5)
        usage = ResourceUsage(steps_executed=10)
        context = ExecutionContext(
            session=session, budget=budget, usage=usage
        )

        with pytest.raises(BudgetExceededError):
            context.check_budget()

    def test_check_budget_no_budget(self):
        """Test check_budget with no budget."""
        session = Session()
        context = ExecutionContext(session=session)

        # Should not raise
        context.check_budget()

    def test_with_sub_budget(self):
        """Test with_sub_budget creates isolated budget context."""
        session = Session()
        parent_budget = Budget(max_tokens=1000)
        parent_usage = ResourceUsage(tokens_used=100)
        context = ExecutionContext(
            session=session, budget=parent_budget, usage=parent_usage
        )

        sub_budget = Budget(max_tokens=500)
        sub_context = context.with_sub_budget(sub_budget)

        assert sub_context.budget is sub_budget
        assert sub_context.usage.tokens_used == 0  # Fresh usage
        assert context.usage.tokens_used == 100  # Parent unchanged

    def test_with_sub_budget_propagates_to_parent(self):
        """Test with_sub_budget propagates usage to parent."""
        session = Session()
        parent_budget = Budget(max_tokens=1000)
        parent_usage = ResourceUsage(tokens_used=100)
        context = ExecutionContext(
            session=session, budget=parent_budget, usage=parent_usage
        )

        sub_budget = Budget(max_tokens=500)
        sub_context = context.with_sub_budget(sub_budget)

        # Add tokens to sub-budget
        sub_context.usage.add_tokens(50)
        sub_context.usage.add_step()
        sub_context.usage.add_api_call()
        sub_context.usage.add_cost(0.01)

        # Child usage should be tracked
        assert sub_context.usage.tokens_used == 50
        assert sub_context.usage.steps_executed == 1
        assert sub_context.usage.api_calls == 1
        assert sub_context.usage.cost_dollars == 0.01

        # Parent usage should also be updated
        assert parent_usage.tokens_used == 150  # 100 + 50
        assert parent_usage.steps_executed == 1
        assert parent_usage.api_calls == 1
        assert parent_usage.cost_dollars == 0.01

    def test_record_step_no_trace(self):
        """Test record_step is no-op when trace is None."""
        from datetime import datetime

        session = Session()
        context = ExecutionContext(session=session)

        # Should not raise
        context.record_step(
            step_id="test",
            node=object(),
            input="in",
            output="out",
            start_time=datetime.now(),
            end_time=datetime.now(),
        )

    def test_record_step_with_trace(self):
        """Test record_step adds step to trace."""
        from datetime import datetime, timedelta

        from nerve.core.nodes.trace import ExecutionTrace

        session = Session()
        trace = ExecutionTrace(graph_id="test-graph", start_time=datetime.now())
        context = ExecutionContext(session=session, trace=trace)

        class FakeNode:
            id = "fake-node"

        start = datetime.now()
        end = start + timedelta(milliseconds=100)

        context.record_step(
            step_id="step1",
            node=FakeNode(),
            input="hello",
            output="world",
            start_time=start,
            end_time=end,
            tokens_used=42,
        )

        assert len(trace.steps) == 1
        step = trace.steps[0]
        assert step.step_id == "step1"
        assert step.node_id == "fake-node"
        assert step.input == "hello"
        assert step.output == "world"
        assert step.tokens_used == 42
        assert step.duration_ms == pytest.approx(100, rel=0.1)

    def test_record_step_with_error(self):
        """Test record_step records error."""
        from datetime import datetime

        from nerve.core.nodes.trace import ExecutionTrace

        session = Session()
        trace = ExecutionTrace(graph_id="test-graph", start_time=datetime.now())
        context = ExecutionContext(session=session, trace=trace)

        class FakeNode:
            id = "fake-node"

        now = datetime.now()

        context.record_step(
            step_id="step1",
            node=FakeNode(),
            input="test",
            output=None,
            start_time=now,
            end_time=now,
            error="Something went wrong",
        )

        assert len(trace.steps) == 1
        assert trace.steps[0].error == "Something went wrong"
