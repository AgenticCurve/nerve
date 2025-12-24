"""Tests for BashNode."""

import asyncio

import pytest

from nerve.core.nodes import BashNode, ExecutionContext, NodeState
from nerve.core.session import Session


@pytest.fixture
def session():
    """Create a test session."""
    return Session(name="test-session")


@pytest.fixture
def bash_node():
    """Create a BashNode for testing."""
    return BashNode(id="test-bash", timeout=5.0)


@pytest.mark.asyncio
async def test_bash_node_basic_execution(session, bash_node):
    """Test basic command execution."""
    context = ExecutionContext(session=session, input="echo hello")
    result = await bash_node.execute(context)

    assert result["success"] is True
    assert "hello" in result["stdout"]
    assert result["stderr"] == ""
    assert result["exit_code"] == 0
    assert result["command"] == "echo hello"
    assert result["error"] is None
    assert result["interrupted"] is False


@pytest.mark.asyncio
async def test_bash_node_command_failure(session, bash_node):
    """Test command that fails with non-zero exit code."""
    context = ExecutionContext(session=session, input="exit 42")
    result = await bash_node.execute(context)

    assert result["success"] is False
    assert result["exit_code"] == 42
    assert result["error"] == "Command exited with code 42"


@pytest.mark.asyncio
async def test_bash_node_chained_commands(session, bash_node):
    """Test chained commands with && operator."""
    context = ExecutionContext(session=session, input="cd /tmp && pwd")
    result = await bash_node.execute(context)

    assert result["success"] is True
    assert "/tmp" in result["stdout"]


@pytest.mark.asyncio
async def test_bash_node_timeout(session):
    """Test command timeout."""
    bash_node = BashNode(id="test-bash", timeout=0.5)
    context = ExecutionContext(session=session, input="sleep 10")
    result = await bash_node.execute(context)

    assert result["success"] is False
    assert "timed out" in result["error"]
    assert result["exit_code"] is None


@pytest.mark.asyncio
async def test_bash_node_interrupt(session, bash_node):
    """Test interrupting a running command."""
    context = ExecutionContext(session=session, input="sleep 10")

    # Start command in background
    task = asyncio.create_task(bash_node.execute(context))

    # Wait a bit, then interrupt
    await asyncio.sleep(0.2)
    await bash_node.interrupt()

    # Get result
    result = await task

    assert result["success"] is False
    assert result["interrupted"] is True
    assert "interrupted" in result["error"].lower()


@pytest.mark.asyncio
async def test_bash_node_working_directory(session, tmp_path):
    """Test working directory configuration."""
    bash_node = BashNode(id="test-bash", cwd=str(tmp_path))
    context = ExecutionContext(session=session, input="pwd")
    result = await bash_node.execute(context)

    assert result["success"] is True
    assert str(tmp_path) in result["stdout"]


@pytest.mark.asyncio
async def test_bash_node_environment_variables(session, bash_node):
    """Test environment variable injection."""
    bash_node = BashNode(id="test-bash", env={"TEST_VAR": "test_value"})
    context = ExecutionContext(session=session, input="echo $TEST_VAR")
    result = await bash_node.execute(context)

    assert result["success"] is True
    assert "test_value" in result["stdout"]


@pytest.mark.asyncio
async def test_bash_node_empty_command(session, bash_node):
    """Test handling of empty command."""
    context = ExecutionContext(session=session, input="")
    result = await bash_node.execute(context)

    assert result["success"] is False
    assert "No command provided" in result["error"]


@pytest.mark.asyncio
async def test_bash_node_context_timeout_override(session, bash_node):
    """Test that context timeout overrides node timeout."""
    # Node has 5s timeout, context has 0.5s
    context = ExecutionContext(session=session, input="sleep 10", timeout=0.5)
    result = await bash_node.execute(context)

    assert result["success"] is False
    assert "0.5s" in result["error"]


@pytest.mark.asyncio
async def test_bash_node_metadata(bash_node):
    """Test metadata is included in to_info."""
    bash_node.metadata = {"custom": "value"}
    info = bash_node.to_info()

    assert info.id == "test-bash"
    assert info.node_type == "bash"
    assert info.state == NodeState.READY
    assert info.persistent is False
    assert info.metadata["custom"] == "value"


@pytest.mark.asyncio
async def test_bash_node_to_info(bash_node):
    """Test to_info returns correct NodeInfo."""
    info = bash_node.to_info()

    assert info.id == "test-bash"
    assert info.node_type == "bash"
    assert info.state == NodeState.READY
    assert info.persistent is False
    assert "timeout" in info.metadata


@pytest.mark.asyncio
async def test_bash_node_multiple_interrupts(session, bash_node):
    """Test that multiple interrupt() calls are safe."""
    context = ExecutionContext(session=session, input="sleep 10")
    task = asyncio.create_task(bash_node.execute(context))

    await asyncio.sleep(0.2)

    # Call interrupt multiple times - should be safe
    await bash_node.interrupt()
    await bash_node.interrupt()
    await bash_node.interrupt()

    result = await task
    assert result["interrupted"] is True


@pytest.mark.asyncio
async def test_bash_node_interrupt_when_idle(bash_node):
    """Test that interrupt() is safe when no command is running."""
    # Should not raise even when no process is running
    await bash_node.interrupt()


@pytest.mark.asyncio
async def test_bash_node_stderr_capture(session, bash_node):
    """Test that stderr is captured correctly."""
    context = ExecutionContext(session=session, input="echo error >&2")
    result = await bash_node.execute(context)

    assert result["success"] is True
    assert "error" in result["stderr"]
    assert result["stdout"].strip() == ""


@pytest.mark.asyncio
async def test_bash_node_repr(bash_node):
    """Test __repr__ returns expected format."""
    assert repr(bash_node) == "BashNode(id='test-bash', cwd=None)"


@pytest.mark.asyncio
async def test_bash_node_persistent_property(bash_node):
    """Test that persistent property is False."""
    assert bash_node.persistent is False
