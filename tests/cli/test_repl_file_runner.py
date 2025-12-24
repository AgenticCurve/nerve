"""Tests for REPL file runner."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from nerve.frontends.cli.repl.file_runner import run_from_file


class TestRunFromFile:
    """Tests for run_from_file function."""

    @pytest.mark.asyncio
    async def test_run_from_file_not_found(self, capsys):
        """run_from_file handles file not found error."""
        await run_from_file("nonexistent_file.py", dry_run=False)
        captured = capsys.readouterr()

        assert "Error: File not found: nonexistent_file.py" in captured.out

    @pytest.mark.asyncio
    async def test_run_from_file_no_graph(self, capsys):
        """run_from_file handles file with no graph variable."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("x = 10\nprint('Hello')\n")
            filepath = f.name

        try:
            await run_from_file(filepath, dry_run=False)
            captured = capsys.readouterr()

            assert f"Loading: {filepath}" in captured.out
            assert "No 'graph' variable found in file" in captured.out
        finally:
            Path(filepath).unlink()

    @pytest.mark.asyncio
    async def test_run_from_file_with_graph_dry_run(self, capsys):
        """run_from_file performs dry run correctly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("""
# Create a simple graph for testing
graph = session.create_graph("test-graph")

# Mock nodes (we can't use await in exec context)
from unittest.mock import Mock
node1 = Mock()
node1.id = "node1"
node2 = Mock()
node2.id = "node2"

graph.add_step(node1, step_id="step1", input="test")
graph.add_step(node2, step_id="step2", depends_on=["step1"], input="test")
""")
            filepath = f.name

        try:
            await run_from_file(filepath, dry_run=True)
            captured = capsys.readouterr()

            assert f"Loading: {filepath}" in captured.out
            assert "[DRY RUN]" in captured.out
            assert "[1] step1" in captured.out
            assert "[2] step2" in captured.out
        finally:
            Path(filepath).unlink()

    @pytest.mark.asyncio
    async def test_run_from_file_syntax_error(self, capsys):
        """run_from_file handles syntax errors."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("this is not valid python syntax !!!")
            filepath = f.name

        try:
            await run_from_file(filepath, dry_run=False)
            captured = capsys.readouterr()

            assert "Error:" in captured.out
        finally:
            Path(filepath).unlink()

    @pytest.mark.asyncio
    async def test_run_from_file_namespace_includes_session(self, capsys):
        """run_from_file provides session in namespace."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("""
# Test that session is available
assert session is not None
assert session.name == "repl"
print(f"Session name: {session.name}")
""")
            filepath = f.name

        try:
            await run_from_file(filepath, dry_run=False)
            captured = capsys.readouterr()

            assert "Session name: repl" in captured.out
        finally:
            Path(filepath).unlink()

    @pytest.mark.asyncio
    async def test_run_from_file_namespace_includes_imports(self, capsys):
        """run_from_file provides standard imports in namespace."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("""
# Test that standard imports are available
assert Session is not None
assert Graph is not None
assert ExecutionContext is not None
assert ParserType is not None
assert BackendType is not None
print("All imports available")
""")
            filepath = f.name

        try:
            await run_from_file(filepath, dry_run=False)
            captured = capsys.readouterr()

            assert "All imports available" in captured.out
        finally:
            Path(filepath).unlink()

    @pytest.mark.asyncio
    async def test_run_from_file_displays_loading_banner(self, capsys):
        """run_from_file displays loading banner."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("pass")
            filepath = f.name

        try:
            await run_from_file(filepath, dry_run=False)
            captured = capsys.readouterr()

            assert f"Loading: {filepath}" in captured.out
            assert "=" * 50 in captured.out
        finally:
            Path(filepath).unlink()
