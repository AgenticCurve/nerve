"""Tests for nerve.core.nodes.trace module."""

from datetime import datetime, timedelta

import pytest

from nerve.core.nodes.trace import ExecutionTrace, StepTrace


class TestStepTrace:
    """Tests for StepTrace dataclass."""

    def test_creation(self):
        """Test basic creation."""
        start = datetime.now()
        end = start + timedelta(milliseconds=100)

        trace = StepTrace(
            step_id="test-step",
            node_id="test-node",
            node_type="function",
            input="hello",
            output="HELLO",
            error=None,
            start_time=start,
            end_time=end,
            duration_ms=100.0,
        )

        assert trace.step_id == "test-step"
        assert trace.node_id == "test-node"
        assert trace.node_type == "function"
        assert trace.input == "hello"
        assert trace.output == "HELLO"
        assert trace.error is None
        assert trace.duration_ms == 100.0
        assert trace.tokens_used == 0

    def test_with_error(self):
        """Test trace with error."""
        start = datetime.now()
        trace = StepTrace(
            step_id="test",
            node_id="node",
            node_type="function",
            input="test",
            output=None,
            error="Something went wrong",
            start_time=start,
            end_time=start,
            duration_ms=0,
        )

        assert trace.error == "Something went wrong"
        assert trace.output is None

    def test_with_tokens(self):
        """Test trace with token count."""
        start = datetime.now()
        trace = StepTrace(
            step_id="test",
            node_id="node",
            node_type="terminal",
            input="test",
            output="response",
            error=None,
            start_time=start,
            end_time=start,
            duration_ms=0,
            tokens_used=1500,
        )

        assert trace.tokens_used == 1500

    def test_to_dict(self):
        """Test to_dict serialization."""
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 0, 1)

        trace = StepTrace(
            step_id="test",
            node_id="node",
            node_type="function",
            input="hello",
            output="world",
            error=None,
            start_time=start,
            end_time=end,
            duration_ms=1000.0,
            tokens_used=100,
            metadata={"key": "value"},
        )

        d = trace.to_dict()

        assert d["step_id"] == "test"
        assert d["node_id"] == "node"
        assert d["node_type"] == "function"
        assert d["input"] == "hello"
        assert d["output"] == "world"
        assert d["error"] is None
        assert d["duration_ms"] == 1000.0
        assert d["tokens_used"] == 100
        assert d["metadata"]["key"] == "value"
        assert "2024-01-01" in d["start_time"]

    def test_to_dict_complex_input(self):
        """Test to_dict with complex input/output."""
        start = datetime.now()
        trace = StepTrace(
            step_id="test",
            node_id="node",
            node_type="function",
            input={"data": [1, 2, 3]},
            output={"result": {"nested": True}},
            error=None,
            start_time=start,
            end_time=start,
            duration_ms=0,
        )

        d = trace.to_dict()

        assert d["input"]["data"] == [1, 2, 3]
        assert d["output"]["result"]["nested"] is True


class TestExecutionTrace:
    """Tests for ExecutionTrace dataclass."""

    def test_creation(self):
        """Test basic creation."""
        start = datetime.now()
        trace = ExecutionTrace(graph_id="test-graph", start_time=start)

        assert trace.graph_id == "test-graph"
        assert trace.start_time == start
        assert trace.end_time is None
        assert trace.status == "running"
        assert trace.steps == []
        assert trace.total_tokens == 0
        assert trace.total_cost == 0.0
        assert trace.error is None

    def test_add_step(self):
        """Test add_step method."""
        trace = ExecutionTrace(
            graph_id="test", start_time=datetime.now()
        )

        step = StepTrace(
            step_id="step1",
            node_id="node1",
            node_type="function",
            input=None,
            output="result",
            error=None,
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_ms=50,
            tokens_used=100,
        )

        trace.add_step(step)

        assert len(trace.steps) == 1
        assert trace.steps[0] is step
        assert trace.total_tokens == 100

    def test_add_multiple_steps(self):
        """Test adding multiple steps aggregates tokens."""
        trace = ExecutionTrace(
            graph_id="test", start_time=datetime.now()
        )
        now = datetime.now()

        for i in range(3):
            trace.add_step(
                StepTrace(
                    step_id=f"step{i}",
                    node_id=f"node{i}",
                    node_type="function",
                    input=None,
                    output=None,
                    error=None,
                    start_time=now,
                    end_time=now,
                    duration_ms=0,
                    tokens_used=50,
                )
            )

        assert len(trace.steps) == 3
        assert trace.total_tokens == 150

    def test_complete_success(self):
        """Test complete marks trace as completed."""
        trace = ExecutionTrace(
            graph_id="test", start_time=datetime.now()
        )

        trace.complete()

        assert trace.status == "completed"
        assert trace.end_time is not None
        assert trace.error is None

    def test_complete_with_error(self):
        """Test complete with error marks trace as failed."""
        trace = ExecutionTrace(
            graph_id="test", start_time=datetime.now()
        )

        trace.complete(error="Something failed")

        assert trace.status == "failed"
        assert trace.end_time is not None
        assert trace.error == "Something failed"

    def test_cancel(self):
        """Test cancel marks trace as cancelled."""
        trace = ExecutionTrace(
            graph_id="test", start_time=datetime.now()
        )

        trace.cancel()

        assert trace.status == "cancelled"
        assert trace.end_time is not None

    def test_duration_ms_while_running(self):
        """Test duration_ms returns None while running."""
        trace = ExecutionTrace(
            graph_id="test", start_time=datetime.now()
        )

        assert trace.duration_ms is None

    def test_duration_ms_after_complete(self):
        """Test duration_ms after completion."""
        start = datetime.now()
        trace = ExecutionTrace(graph_id="test", start_time=start)

        trace.end_time = start + timedelta(seconds=2)

        assert trace.duration_ms == pytest.approx(2000, rel=0.01)

    def test_explain_simple(self):
        """Test explain output for simple trace."""
        trace = ExecutionTrace(
            graph_id="pipeline", start_time=datetime.now()
        )
        now = datetime.now()

        trace.add_step(
            StepTrace(
                step_id="fetch",
                node_id="fn1",
                node_type="function",
                input="url",
                output="data",
                error=None,
                start_time=now,
                end_time=now,
                duration_ms=100,
            )
        )
        trace.complete()

        output = trace.explain()

        assert "pipeline" in output
        assert "completed" in output
        assert "fetch" in output
        assert "function" in output
        assert "100" in output

    def test_explain_with_error(self):
        """Test explain output with step error."""
        trace = ExecutionTrace(
            graph_id="test", start_time=datetime.now()
        )
        now = datetime.now()

        trace.add_step(
            StepTrace(
                step_id="broken",
                node_id="fn1",
                node_type="function",
                input="test",
                output=None,
                error="Connection failed",
                start_time=now,
                end_time=now,
                duration_ms=50,
            )
        )

        output = trace.explain()

        assert "broken" in output
        assert "Connection failed" in output

    def test_to_dict(self):
        """Test to_dict serialization."""
        start = datetime(2024, 1, 1, 12, 0, 0)
        trace = ExecutionTrace(graph_id="test", start_time=start)

        trace.add_step(
            StepTrace(
                step_id="step1",
                node_id="node1",
                node_type="function",
                input="in",
                output="out",
                error=None,
                start_time=start,
                end_time=start,
                duration_ms=50,
                tokens_used=100,
            )
        )
        trace.total_cost = 0.01
        trace.complete()

        d = trace.to_dict()

        assert d["graph_id"] == "test"
        assert d["status"] == "completed"
        assert d["total_tokens"] == 100
        assert d["total_cost"] == 0.01
        assert len(d["steps"]) == 1
        assert d["steps"][0]["step_id"] == "step1"
