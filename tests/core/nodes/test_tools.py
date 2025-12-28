"""Tests for node-as-tool adapter."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from nerve.core.nodes import BashNode, ExecutionContext
from nerve.core.nodes.tools import (
    ToolCapable,
    is_tool_capable,
    tools_from_nodes,
    truncate_result,
    node_to_tool_definition,
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

            def tool_description(self) -> str:
                return "test"

            # Missing: tool_parameters, tool_input, tool_result

        node = PartialNode()
        assert not is_tool_capable(node)

    def test_mock_tool_capable(self):
        """Mock with all methods is tool-capable."""
        mock = MagicMock()
        mock.id = "mock"
        mock.execute = AsyncMock(return_value={})
        mock.tool_description = MagicMock(return_value="desc")
        mock.tool_parameters = MagicMock(return_value={})
        mock.tool_input = MagicMock(return_value="input")
        mock.tool_result = MagicMock(return_value="result")

        assert is_tool_capable(mock)


class TestBashNodeToolMethods:
    """Test BashNode tool method implementations."""

    def test_tool_description(self, bash_node):
        """tool_description returns a string."""
        desc = bash_node.tool_description()
        assert isinstance(desc, str)
        assert len(desc) > 0
        assert "bash" in desc.lower() or "command" in desc.lower()

    def test_tool_parameters(self, bash_node):
        """tool_parameters returns valid JSON Schema."""
        params = bash_node.tool_parameters()

        assert params["type"] == "object"
        assert "properties" in params
        assert "command" in params["properties"]
        assert params["properties"]["command"]["type"] == "string"
        assert "required" in params
        assert "command" in params["required"]

    def test_tool_input(self, bash_node):
        """tool_input extracts command from args."""
        args = {"command": "ls -la"}
        result = bash_node.tool_input(args)
        assert result == "ls -la"

    def test_tool_input_empty(self, bash_node):
        """tool_input handles missing command gracefully."""
        args = {}
        result = bash_node.tool_input(args)
        assert result == ""

    def test_tool_result_success(self, bash_node):
        """tool_result formats successful execution."""
        result = {
            "success": True,
            "stdout": "file1.txt\nfile2.txt",
            "stderr": "",
            "exit_code": 0,
        }
        formatted = bash_node.tool_result(result)
        assert formatted == "file1.txt\nfile2.txt"

    def test_tool_result_success_empty(self, bash_node):
        """tool_result handles empty stdout."""
        result = {
            "success": True,
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
        }
        formatted = bash_node.tool_result(result)
        assert formatted == "(no output)"

    def test_tool_result_error(self, bash_node):
        """tool_result formats error execution."""
        result = {
            "success": False,
            "stdout": "",
            "stderr": "command not found",
            "exit_code": 127,
            "error": "Command exited with code 127",
        }
        formatted = bash_node.tool_result(result)
        assert "Error" in formatted
        assert "127" in formatted
        assert "command not found" in formatted


class TestNodeToToolDefinition:
    """Test tool definition generation."""

    def test_basic_conversion(self, bash_node):
        """node_to_tool_definition creates valid ToolDefinition."""
        tool_def = node_to_tool_definition(bash_node)

        assert tool_def.name == "bash"
        assert "bash" in tool_def.description.lower() or "command" in tool_def.description.lower()
        assert tool_def.parameters["type"] == "object"
        assert "command" in tool_def.parameters["properties"]


class TestToolsFromNodes:
    """Test tools_from_nodes utility function."""

    def test_single_tool_capable_node(self, bash_node):
        """Single tool-capable node creates one tool."""
        tools, executor = tools_from_nodes([bash_node])

        assert len(tools) == 1
        assert tools[0].name == "bash"
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
        assert tools[0].name == "bash"

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

        result = await executor("bash", {"command": "echo hello"})

        assert "hello" in result

    @pytest.mark.asyncio
    async def test_executor_handles_error(self, bash_node):
        """Executor handles node execution errors."""
        tools, executor = tools_from_nodes([bash_node])

        # Run a command that will fail
        result = await executor("bash", {"command": "exit 42"})

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

        result = await executor("bash", {"command": "echo test"}, context)

        assert "test" in result

    @pytest.mark.asyncio
    async def test_executor_without_context(self, bash_node):
        """Executor works without context."""
        tools, executor = tools_from_nodes([bash_node])

        # No context passed
        result = await executor("bash", {"command": "echo test"})

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
        assert tool_names == {"bash1", "bash2"}

    @pytest.mark.asyncio
    async def test_executor_dispatches_correctly(self, session):
        """Executor routes to correct node."""
        bash1 = BashNode(id="bash1", session=session, cwd="/tmp")
        bash2 = BashNode(id="bash2", session=session, cwd="/")

        tools, executor = tools_from_nodes([bash1, bash2])

        # Call bash1 - should run in /tmp
        result1 = await executor("bash1", {"command": "pwd"})
        assert "/tmp" in result1

        # Call bash2 - should run in /
        result2 = await executor("bash2", {"command": "pwd"})
        # Note: result2 will be "/" not "/tmp"
        assert result2.strip() == "/" or "/tmp" not in result2
