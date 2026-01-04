"""Tests for multi-tool node handling in Commander."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from nerve.core.nodes.tools import ToolDefinition
from nerve.frontends.tui.commander.multi_tool import (
    is_help_command,
    is_multi_tool_node_type,
    parse_help_command,
    parse_multi_tool_input,
    render_node_tools_help,
    render_tool_help,
)


class TestIsMultiToolNodeType:
    """Test is_multi_tool_node_type() function."""

    def test_mcp_node_is_multi_tool(self):
        """MCPNode is a multi-tool node."""
        assert is_multi_tool_node_type("MCPNode") is True
        assert is_multi_tool_node_type("mcp") is True
        assert is_multi_tool_node_type("MCP") is True

    def test_bash_node_is_not_multi_tool(self):
        """BashNode is not a multi-tool node."""
        assert is_multi_tool_node_type("BashNode") is False
        assert is_multi_tool_node_type("bash") is False

    def test_claude_wezterm_is_not_multi_tool(self):
        """ClaudeWezTermNode is not a multi-tool node."""
        assert is_multi_tool_node_type("ClaudeWezTermNode") is False


class TestIsHelpCommand:
    """Test is_help_command() function."""

    def test_single_question_mark(self):
        """'?' is a help command."""
        assert is_help_command("?") is True
        assert is_help_command(" ? ") is True

    def test_tool_question_mark(self):
        """'tool ?' is a help command."""
        assert is_help_command("read_file ?") is True
        assert is_help_command("echo ?") is True

    def test_not_help_command(self):
        """Regular commands are not help commands."""
        assert is_help_command("read_file {}") is False
        assert is_help_command("hello world") is False
        assert is_help_command("") is False


class TestParseHelpCommand:
    """Test parse_help_command() function."""

    def test_node_help(self):
        """'?' returns (True, None) for node-level help."""
        is_help, tool_name = parse_help_command("?")
        assert is_help is True
        assert tool_name is None

    def test_tool_help(self):
        """'tool ?' returns (True, tool_name) for tool-level help."""
        is_help, tool_name = parse_help_command("read_file ?")
        assert is_help is True
        assert tool_name == "read_file"

    def test_not_help(self):
        """Regular input returns (False, None)."""
        is_help, tool_name = parse_help_command("read_file {}")
        assert is_help is False
        assert tool_name is None


class TestParseMultiToolInput:
    """Test parse_multi_tool_input() function."""

    def test_simple_tool_call(self):
        """Parse simple tool call with JSON args."""
        tool_name, args = parse_multi_tool_input('echo {"message": "hello"}')
        assert tool_name == "echo"
        assert args == {"message": "hello"}

    def test_complex_args(self):
        """Parse tool call with complex JSON args."""
        tool_name, args = parse_multi_tool_input('add {"a": 10, "b": 20}')
        assert tool_name == "add"
        assert args == {"a": 10, "b": 20}

    def test_no_args(self):
        """Tool call without args returns empty dict."""
        tool_name, args = parse_multi_tool_input("list_all")
        assert tool_name == "list_all"
        assert args == {}

    def test_empty_input_raises(self):
        """Empty input raises ValueError."""
        with pytest.raises(ValueError, match="No tool specified"):
            parse_multi_tool_input("")

    def test_invalid_json_raises(self):
        """Invalid JSON raises ValueError."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_multi_tool_input("echo {invalid}")

    def test_non_object_args_raises(self):
        """Non-object JSON raises ValueError."""
        with pytest.raises(ValueError, match="must be a JSON object"):
            parse_multi_tool_input('echo ["array"]')


class TestRenderNodeToolsHelp:
    """Test render_node_tools_help() function."""

    def test_renders_tools_list(self):
        """Renders a list of tools."""
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)

        tools = [
            ToolDefinition(
                name="echo",
                description="Echo the input message",
                parameters={},
                node_id="test-mcp",
            ),
            ToolDefinition(
                name="add",
                description="Add two numbers",
                parameters={},
                node_id="test-mcp",
            ),
        ]

        render_node_tools_help(console, "test-mcp", tools)

        result = output.getvalue()
        assert "test-mcp" in result
        assert "echo" in result
        assert "add" in result
        assert "Echo the input message" in result

    def test_empty_tools_list(self):
        """Handles empty tools list."""
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)

        render_node_tools_help(console, "test-mcp", [])

        result = output.getvalue()
        assert "No tools available" in result


class TestRenderToolHelp:
    """Test render_tool_help() function."""

    def test_renders_tool_details(self):
        """Renders detailed tool help."""
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)

        tool = ToolDefinition(
            name="read_file",
            description="Read contents of a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read",
                    },
                },
                "required": ["path"],
            },
            node_id="fs-mcp",
        )

        render_tool_help(console, "fs-mcp", tool)

        result = output.getvalue()
        assert "read_file" in result
        assert "Read contents of a file" in result
        assert "Parameters" in result
        assert "path" in result
        assert "string" in result

    def test_no_parameters(self):
        """Handles tool with no parameters."""
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)

        tool = ToolDefinition(
            name="ping",
            description="Ping the server",
            parameters={"type": "object", "properties": {}},
            node_id="test-mcp",
        )

        render_tool_help(console, "test-mcp", tool)

        result = output.getvalue()
        assert "ping" in result
        assert "No parameters" in result
