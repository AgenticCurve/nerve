"""Tests for nerve.core.nodes.base module."""

import pytest

from nerve.core.nodes.base import (
    FunctionNode,
    Node,
    NodeConfig,
    NodeInfo,
    NodeState,
)
from nerve.core.nodes.context import ExecutionContext
from nerve.core.session.session import Session


class TestNodeState:
    """Tests for NodeState enum."""

    def test_states_exist(self):
        """All expected states exist."""
        assert NodeState.CREATED
        assert NodeState.STARTING
        assert NodeState.READY
        assert NodeState.BUSY
        assert NodeState.STOPPING
        assert NodeState.STOPPED

    def test_state_values_unique(self):
        """State values are unique."""
        values = [s.value for s in NodeState]
        assert len(values) == len(set(values))


class TestNodeInfo:
    """Tests for NodeInfo dataclass."""

    def test_to_dict(self):
        """Test to_dict serialization."""
        info = NodeInfo(
            id="test-node",
            node_type="function",
            state=NodeState.READY,
            persistent=False,
            metadata={"key": "value"},
        )

        d = info.to_dict()
        assert d["id"] == "test-node"
        assert d["type"] == "function"
        assert d["state"] == "READY"
        assert d["persistent"] is False
        assert d["metadata"]["key"] == "value"


class TestNodeConfig:
    """Tests for NodeConfig dataclass."""

    def test_default_values(self):
        """Test default values."""
        config = NodeConfig()
        assert config.id is None
        assert config.metadata == {}

    def test_custom_values(self):
        """Test custom values."""
        config = NodeConfig(id="custom", metadata={"a": 1})
        assert config.id == "custom"
        assert config.metadata["a"] == 1


class TestFunctionNode:
    """Tests for FunctionNode."""

    @pytest.fixture
    def session(self):
        """Create a test session."""
        return Session(name="test-session")

    @pytest.mark.asyncio
    async def test_sync_function(self, session):
        """Test wrapping a sync function."""

        def transform(ctx: ExecutionContext) -> str:
            return ctx.input.upper()

        node = FunctionNode(id="transform", session=session, fn=transform)
        context = ExecutionContext(session=session, input="hello")

        result = await node.execute(context)
        assert result["success"] is True
        assert result["output"] == "HELLO"

    @pytest.mark.asyncio
    async def test_async_function(self, session):
        """Test wrapping an async function."""

        async def fetch(ctx: ExecutionContext) -> dict:
            return {"data": ctx.input}

        node = FunctionNode(id="fetch", session=session, fn=fetch)
        context = ExecutionContext(session=session, input="test")

        result = await node.execute(context)
        assert result["success"] is True
        assert result["output"] == {"data": "test"}

    @pytest.mark.asyncio
    async def test_lambda(self, session):
        """Test wrapping a lambda."""
        node = FunctionNode(id="add", session=session, fn=lambda ctx: ctx.input + 1)
        context = ExecutionContext(session=session, input=5)

        result = await node.execute(context)
        assert result["success"] is True
        assert result["output"] == 6

    def test_properties(self, session):
        """Test node properties."""
        node = FunctionNode(id="test", session=session, fn=lambda ctx: ctx.input)

        assert node.id == "test"
        assert node.persistent is False

    def test_to_info(self, session):
        """Test to_info method."""
        node = FunctionNode(id="test", session=session, fn=lambda ctx: ctx.input)
        info = node.to_info()

        assert info.id == "test"
        assert info.node_type == "function"
        assert info.state == NodeState.READY
        assert info.persistent is False

    def test_repr(self, session):
        """Test repr."""
        node = FunctionNode(id="my-node", session=session, fn=lambda ctx: ctx.input)
        assert "my-node" in repr(node)

    @pytest.mark.asyncio
    async def test_upstream_access(self, session):
        """Test accessing upstream results."""

        def process(ctx: ExecutionContext) -> str:
            return f"got {ctx.upstream['prev']}"

        node = FunctionNode(id="process", session=session, fn=process)
        context = ExecutionContext(session=session, input=None, upstream={"prev": "data"})

        result = await node.execute(context)
        assert result["success"] is True
        assert result["output"] == "got data"

    def test_is_node_protocol(self, session):
        """FunctionNode satisfies Node protocol."""
        node = FunctionNode(id="test", session=session, fn=lambda ctx: ctx.input)
        assert isinstance(node, Node)

    @pytest.mark.asyncio
    async def test_interrupt_cancels_async_task(self, session):
        """Test interrupt() cancels running async task."""
        import asyncio

        execution_started = asyncio.Event()
        execution_completed = False

        async def slow_function(ctx: ExecutionContext):
            nonlocal execution_completed
            execution_started.set()
            await asyncio.sleep(10)  # Long running task
            execution_completed = True
            return "done"

        node = FunctionNode(id="slow", session=session, fn=slow_function)
        context = ExecutionContext(session=session, input=None)

        # Start execution in background
        task = asyncio.create_task(node.execute(context))

        # Wait for execution to start
        await execution_started.wait()

        # Interrupt the node
        await node.interrupt()

        # Task should be cancelled
        with pytest.raises(asyncio.CancelledError):
            await task

        # Execution should not have completed
        assert not execution_completed

    @pytest.mark.asyncio
    async def test_interrupt_when_not_executing(self, session):
        """Test interrupt() is safe to call when not executing."""
        node = FunctionNode(id="test", session=session, fn=lambda ctx: ctx.input)

        # Should not raise
        await node.interrupt()

    @pytest.mark.asyncio
    async def test_interrupt_clears_current_task(self, session):
        """Test that _current_task is cleared after execution."""
        node = FunctionNode(id="test", session=session, fn=lambda ctx: ctx.input)
        context = ExecutionContext(session=session, input="hello")

        # Before execution
        assert node._current_task is None

        # Execute
        await node.execute(context)

        # After execution, task should be cleared
        assert node._current_task is None
