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

    @pytest.mark.asyncio
    async def test_sync_function(self):
        """Test wrapping a sync function."""

        def transform(ctx: ExecutionContext) -> str:
            return ctx.input.upper()

        node = FunctionNode(id="transform", fn=transform)
        session = Session()
        context = ExecutionContext(session=session, input="hello")

        result = await node.execute(context)
        assert result == "HELLO"

    @pytest.mark.asyncio
    async def test_async_function(self):
        """Test wrapping an async function."""

        async def fetch(ctx: ExecutionContext) -> dict:
            return {"data": ctx.input}

        node = FunctionNode(id="fetch", fn=fetch)
        session = Session()
        context = ExecutionContext(session=session, input="test")

        result = await node.execute(context)
        assert result == {"data": "test"}

    @pytest.mark.asyncio
    async def test_lambda(self):
        """Test wrapping a lambda."""
        node = FunctionNode(id="add", fn=lambda ctx: ctx.input + 1)
        session = Session()
        context = ExecutionContext(session=session, input=5)

        result = await node.execute(context)
        assert result == 6

    def test_properties(self):
        """Test node properties."""
        node = FunctionNode(id="test", fn=lambda ctx: ctx.input)

        assert node.id == "test"
        assert node.persistent is False

    def test_to_info(self):
        """Test to_info method."""
        node = FunctionNode(id="test", fn=lambda ctx: ctx.input)
        info = node.to_info()

        assert info.id == "test"
        assert info.node_type == "function"
        assert info.state == NodeState.READY
        assert info.persistent is False

    def test_repr(self):
        """Test repr."""
        node = FunctionNode(id="my-node", fn=lambda ctx: ctx.input)
        assert "my-node" in repr(node)

    @pytest.mark.asyncio
    async def test_upstream_access(self):
        """Test accessing upstream results."""

        def process(ctx: ExecutionContext) -> str:
            return f"got {ctx.upstream['prev']}"

        node = FunctionNode(id="process", fn=process)
        session = Session()
        context = ExecutionContext(session=session, input=None, upstream={"prev": "data"})

        result = await node.execute(context)
        assert result == "got data"

    def test_is_node_protocol(self):
        """FunctionNode satisfies Node protocol."""
        node = FunctionNode(id="test", fn=lambda ctx: ctx.input)
        assert isinstance(node, Node)
