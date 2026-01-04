"""Tests for node-as-tool adapter."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nerve.core.nodes import BashNode, ExecutionContext
from nerve.core.nodes.tools import (
    ToolCapable,
    ToolDefinition,
    is_multi_tool_node,
    is_tool_capable,
    tools_from_nodes,
    truncate_result,
)
from nerve.core.session import Session


@pytest.fixture
def session():
    """Create a test session."""
    return Session(name="test-session")


@pytest.fixture
def bash_node(session):
    """Create a BashNode for testing."""
    return BashNode(id="bash", session=session, timeout=5.0)


class TestToolCapableProtocol:
    """Test ToolCapable protocol detection."""

    def test_bash_node_is_tool_capable(self, bash_node):
        """BashNode implements ToolCapable protocol."""
        assert is_tool_capable(bash_node)
        assert isinstance(bash_node, ToolCapable)

    def test_plain_object_not_tool_capable(self):
        """Plain objects are not tool-capable."""
        obj = object()
        assert not is_tool_capable(obj)

    def test_partial_implementation_not_tool_capable(self):
        """Objects with only some tool methods are not tool-capable."""

        class PartialNode:
            id = "partial"

            def list_tools(self) -> list:
                return []

            # Missing: call_tool

        node = PartialNode()
        assert not is_tool_capable(node)

    def test_mock_tool_capable(self):
        """Mock with all methods is tool-capable."""
        mock = MagicMock()
        mock.id = "mock"
        mock.list_tools = MagicMock(return_value=[])
        mock.call_tool = AsyncMock(return_value="result")

        assert is_tool_capable(mock)

    def test_is_multi_tool_node_single_tool(self, bash_node):
        """BashNode is a single-tool node."""
        assert not is_multi_tool_node(bash_node)

    def test_is_multi_tool_node_multiple_tools(self):
        """Multi-tool node detection."""
        mock = MagicMock()
        mock.id = "multi"
        mock.list_tools = MagicMock(
            return_value=[
                ToolDefinition(name="tool1", description="", parameters={}, node_id="multi"),
                ToolDefinition(name="tool2", description="", parameters={}, node_id="multi"),
            ]
        )
        mock.call_tool = AsyncMock(return_value="result")

        assert is_multi_tool_node(mock)


class TestBashNodeToolMethods:
    """Test BashNode tool method implementations."""

    def test_list_tools(self, bash_node):
        """list_tools returns a list with one tool."""
        tools = bash_node.list_tools()
        assert len(tools) == 1
        tool = tools[0]
        assert tool.name == "bash"
        assert "bash" in tool.description.lower() or "command" in tool.description.lower()
        assert tool.node_id == bash_node.id

    def test_tool_parameters(self, bash_node):
        """Tool parameters is valid JSON Schema."""
        tools = bash_node.list_tools()
        params = tools[0].parameters

        assert params["type"] == "object"
        assert "properties" in params
        assert "command" in params["properties"]
        assert params["properties"]["command"]["type"] == "string"
        assert "required" in params
        assert "command" in params["required"]

    @pytest.mark.asyncio
    async def test_call_tool_success(self, bash_node):
        """call_tool executes command and returns output."""
        result = await bash_node.call_tool("bash", {"command": "echo hello"})
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_call_tool_empty_command(self, bash_node):
        """call_tool handles empty command."""
        result = await bash_node.call_tool("bash", {})
        assert "Error" in result or "no output" in result.lower()

    @pytest.mark.asyncio
    async def test_call_tool_error(self, bash_node):
        """call_tool formats error execution."""
        result = await bash_node.call_tool("bash", {"command": "exit 127"})
        assert "Error" in result
        assert "127" in result

    @pytest.mark.asyncio
    async def test_call_tool_unknown_tool(self, bash_node):
        """call_tool raises ValueError for unknown tool."""
        with pytest.raises(ValueError, match="Unknown tool"):
            await bash_node.call_tool("unknown", {})


class TestToolDefinition:
    """Test ToolDefinition dataclass."""

    def test_to_dict(self, bash_node):
        """ToolDefinition.to_dict creates valid OpenAI format."""
        tools = bash_node.list_tools()
        tool_def = tools[0]
        result = tool_def.to_dict()

        assert result["type"] == "function"
        assert result["function"]["name"] == "bash"
        assert (
            "bash" in result["function"]["description"].lower()
            or "command" in result["function"]["description"].lower()
        )
        assert result["function"]["parameters"]["type"] == "object"
        assert "command" in result["function"]["parameters"]["properties"]


class TestToolsFromNodes:
    """Test tools_from_nodes utility function."""

    def test_single_tool_capable_node(self, bash_node):
        """Single tool-capable node creates one tool."""
        tools, executor = tools_from_nodes([bash_node])

        assert len(tools) == 1
        # Tool names are now prefixed with node ID
        assert tools[0].name == "bash.bash"
        assert tools[0].node_id == "bash"
        assert callable(executor)

    def test_filters_non_tool_capable(self, session, bash_node):
        """Non-tool-capable nodes are filtered out."""
        # Create a non-tool-capable mock node
        non_tool = MagicMock()
        non_tool.id = "non-tool"
        # Doesn't have tool methods

        tools, executor = tools_from_nodes([bash_node, non_tool])

        # Only bash should be included
        assert len(tools) == 1
        assert tools[0].name == "bash.bash"

    def test_empty_list(self):
        """Empty list produces no tools."""
        tools, executor = tools_from_nodes([])

        assert len(tools) == 0
        assert callable(executor)

    @pytest.mark.asyncio
    async def test_executor_unknown_tool(self, bash_node):
        """Executor returns error for unknown tool."""
        tools, executor = tools_from_nodes([bash_node])

        result = await executor("nonexistent", {"command": "test"})

        assert "Error" in result
        assert "Unknown tool" in result
        assert "nonexistent" in result

    @pytest.mark.asyncio
    async def test_executor_calls_node(self, bash_node):
        """Executor correctly calls the node."""
        tools, executor = tools_from_nodes([bash_node])

        # Use prefixed tool name
        result = await executor("bash.bash", {"command": "echo hello"})

        assert "hello" in result

    @pytest.mark.asyncio
    async def test_executor_handles_error(self, bash_node):
        """Executor handles node execution errors."""
        tools, executor = tools_from_nodes([bash_node])

        # Run a command that will fail
        result = await executor("bash.bash", {"command": "exit 42"})

        assert "Error" in result
        assert "42" in result


class TestTruncateResult:
    """Test result truncation."""

    def test_short_string_unchanged(self):
        """Short strings are not truncated."""
        result = "short string"
        truncated = truncate_result(result, max_length=100)
        assert truncated == result

    def test_long_string_truncated(self):
        """Long strings are truncated with indicator."""
        result = "a" * 1000
        truncated = truncate_result(result, max_length=100)

        assert len(truncated) < 200  # 100 + truncation message
        assert "TRUNCATED" in truncated
        assert "1000 chars" in truncated

    def test_exact_length_unchanged(self):
        """String at exact max length is not truncated."""
        result = "a" * 100
        truncated = truncate_result(result, max_length=100)
        assert truncated == result
        assert "TRUNCATED" not in truncated


class TestToolExecutorWithContext:
    """Test executor context inheritance."""

    @pytest.mark.asyncio
    async def test_executor_with_context(self, bash_node):
        """Executor passes context to node."""
        tools, executor = tools_from_nodes([bash_node])

        # Create a context with exec_id
        context = ExecutionContext(
            session=bash_node.session,
            input="test",
            exec_id="exec-123",
        )

        # Use prefixed tool name
        result = await executor("bash.bash", {"command": "echo test"}, context)

        assert "test" in result

    @pytest.mark.asyncio
    async def test_executor_without_context(self, bash_node):
        """Executor works without context."""
        tools, executor = tools_from_nodes([bash_node])

        # No context passed (use prefixed tool name)
        result = await executor("bash.bash", {"command": "echo test"})

        assert "test" in result


class TestMultipleToolCapableNodes:
    """Test with multiple tool-capable nodes."""

    @pytest.mark.asyncio
    async def test_multiple_nodes(self, session):
        """Multiple tool-capable nodes all become tools."""
        bash1 = BashNode(id="bash1", session=session)
        bash2 = BashNode(id="bash2", session=session)

        tools, executor = tools_from_nodes([bash1, bash2])

        assert len(tools) == 2
        tool_names = {t.name for t in tools}
        # Tool names are now prefixed with node ID
        assert tool_names == {"bash1.bash", "bash2.bash"}

    @pytest.mark.asyncio
    async def test_executor_dispatches_correctly(self, session):
        """Executor routes to correct node."""
        bash1 = BashNode(id="bash1", session=session, cwd="/tmp")
        bash2 = BashNode(id="bash2", session=session, cwd="/")

        tools, executor = tools_from_nodes([bash1, bash2])

        # Call bash1 - should run in /tmp
        result1 = await executor("bash1.bash", {"command": "pwd"})
        assert "/tmp" in result1

        # Call bash2 - should run in /
        result2 = await executor("bash2.bash", {"command": "pwd"})
        # Note: result2 will be "/" not "/tmp"
        assert result2.strip() == "/" or "/tmp" not in result2
