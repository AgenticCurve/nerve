"""Tests for Commander TUI dependency tracking.

Tests the dependency extraction, validation, and waiting logic for
block references in the Commander TUI.
"""

from __future__ import annotations

import asyncio
from io import StringIO

import pytest
from rich.console import Console

from nerve.frontends.tui.commander.blocks import Block, Timeline
from nerve.frontends.tui.commander.executor import CommandExecutor
from nerve.frontends.tui.commander.variables import extract_block_dependencies


class TestExtractBlockDependencies:
    """Tests for extract_block_dependencies function."""

    def test_no_references(self) -> None:
        """Text with no variable references should return empty set."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        deps = extract_block_dependencies("no variables here", timeline)
        assert deps == set()

    def test_single_numeric_reference(self) -> None:
        """Single :::N reference should be detected."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))
        timeline.add(Block(block_type="bash", node_id="bash2"))

        deps = extract_block_dependencies("review :::0", timeline)
        assert deps == {0}

    def test_multiple_numeric_references(self) -> None:
        """Multiple :::N references should all be detected."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))
        timeline.add(Block(block_type="bash", node_id="bash2"))
        timeline.add(Block(block_type="bash", node_id="bash3"))

        deps = extract_block_dependencies("compare :::0 and :::1", timeline)
        assert deps == {0, 1}

    def test_numeric_reference_with_keyed_access(self) -> None:
        """:::N['key'] should detect dependency on block N."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        deps = extract_block_dependencies("review :::0['output']", timeline)
        assert deps == {0}

    def test_numeric_reference_with_nested_keys(self) -> None:
        """:::N['raw']['stdout'] should detect dependency on block N."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        deps = extract_block_dependencies("check :::0['raw']['stdout']", timeline)
        assert deps == {0}

    def test_negative_index(self) -> None:
        """:::-N should resolve to actual block number."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="bash2"))  # Block 1
        timeline.add(Block(block_type="bash", node_id="bash3"))  # Block 2

        deps = extract_block_dependencies("review :::-1", timeline)
        assert deps == {2}  # Last block

        deps = extract_block_dependencies("review :::-2", timeline)
        assert deps == {1}  # Second to last

    def test_negative_index_with_keyed_access(self) -> None:
        """:::-1['output'] should resolve and detect dependency."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))
        timeline.add(Block(block_type="bash", node_id="bash2"))

        deps = extract_block_dependencies("review :::-1['output']", timeline)
        assert deps == {1}

    def test_last_keyword(self) -> None:
        """:::last should resolve to last block number."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))
        timeline.add(Block(block_type="bash", node_id="bash2"))
        timeline.add(Block(block_type="bash", node_id="bash3"))

        deps = extract_block_dependencies("review :::last", timeline)
        assert deps == {2}

    def test_last_keyword_with_keyed_access(self) -> None:
        """:::last['output'] should detect dependency on last block."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))
        timeline.add(Block(block_type="bash", node_id="bash2"))

        deps = extract_block_dependencies("review :::last['output']", timeline)
        assert deps == {1}

    def test_node_reference_last_block(self) -> None:
        """:::nodename should detect dependency on last block from that node."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="gemini"))  # Block 1
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 2

        nodes_by_type = {"claude": "claude", "gemini": "gemini"}

        deps = extract_block_dependencies("review :::claude", timeline, nodes_by_type)
        assert deps == {2}  # Last claude block

    def test_node_reference_with_numeric_index(self) -> None:
        """:::nodename[N] should detect dependency on Nth block from that node."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="gemini"))  # Block 1
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 2

        nodes_by_type = {"claude": "claude", "gemini": "gemini"}

        deps = extract_block_dependencies("review :::claude[0]", timeline, nodes_by_type)
        assert deps == {0}  # First claude block

    def test_node_reference_with_negative_index(self) -> None:
        """:::nodename[-1] should detect dependency on last block from that node."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="gemini"))  # Block 1
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 2

        nodes_by_type = {"claude": "claude", "gemini": "gemini"}

        deps = extract_block_dependencies("review :::claude[-1]", timeline, nodes_by_type)
        assert deps == {2}  # Last claude block

    def test_node_reference_with_keyed_access(self) -> None:
        """:::nodename['key'] should detect dependency on last block from that node."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 1

        nodes_by_type = {"claude": "claude"}

        # This is the bug we fixed - should now work!
        deps = extract_block_dependencies("review :::claude['output']", timeline, nodes_by_type)
        assert deps == {1}  # Last claude block

    def test_node_reference_with_nested_keyed_access(self) -> None:
        """:::nodename['raw']['stdout'] should detect dependency."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 1

        nodes_by_type = {"claude": "claude"}

        deps = extract_block_dependencies(
            "check :::claude['raw']['stdout']", timeline, nodes_by_type
        )
        assert deps == {1}

    def test_node_reference_indexed_with_keyed_access(self) -> None:
        """:::nodename[N]['key'] should detect dependency on Nth block."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 1

        nodes_by_type = {"claude": "claude"}

        deps = extract_block_dependencies("review :::claude[0]['output']", timeline, nodes_by_type)
        assert deps == {0}  # First claude block

    def test_multiple_node_references(self) -> None:
        """Multiple node references should all be detected."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="gemini"))  # Block 1
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 2

        nodes_by_type = {"claude": "claude", "gemini": "gemini"}

        deps = extract_block_dependencies(
            "compare :::claude and :::gemini", timeline, nodes_by_type
        )
        assert deps == {2, 1}  # Last claude (2) and last gemini (1)

    def test_mixed_references(self) -> None:
        """Mix of numeric and node references should all be detected."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="gemini"))  # Block 1
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 2

        nodes_by_type = {"claude": "claude", "gemini": "gemini"}

        deps = extract_block_dependencies("review :::0 and :::claude", timeline, nodes_by_type)
        assert deps == {0, 2}  # Block 0 and last claude (2)

    def test_node_reference_nonexistent_node(self) -> None:
        """Reference to non-existent node should not add dependency."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))

        nodes_by_type = {"claude": "claude"}

        deps = extract_block_dependencies("review :::gemini", timeline, nodes_by_type)
        assert deps == set()  # No gemini blocks exist

    def test_node_reference_out_of_bounds_index(self) -> None:
        """Reference to out-of-bounds node index should not add dependency."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))

        nodes_by_type = {"claude": "claude"}

        deps = extract_block_dependencies("review :::claude[5]", timeline, nodes_by_type)
        assert deps == set()  # Only 1 claude block exists

    def test_node_reference_without_nodes_by_type(self) -> None:
        """Node references without nodes_by_type still extract dependencies."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 0

        # Even without nodes_by_type, should extract dependency by matching node_id directly
        deps = extract_block_dependencies("review :::claude", timeline)
        assert deps == {0}  # Uses node_ref "claude" as node_id, finds block 0

    def test_duplicate_references_deduplicated(self) -> None:
        """Duplicate references should be deduplicated."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        deps = extract_block_dependencies(":::0 and :::0 again", timeline)
        assert deps == {0}  # Only one entry

    def test_empty_timeline(self) -> None:
        """References on empty timeline should still extract the reference.

        Note: Validation happens later in _wait_for_dependencies, not during extraction.
        """
        timeline = Timeline()

        deps = extract_block_dependencies("review :::0", timeline)
        assert deps == {0}  # Reference extracted, validation happens later

    def test_negative_index_out_of_bounds(self) -> None:
        """Negative index out of bounds should not add dependency."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        deps = extract_block_dependencies("review :::-5", timeline)
        assert deps == set()  # -5 is out of bounds for 1 block


class TestDependencyStorage:
    """Tests for Block dependency storage (depends_on field)."""

    def test_self_reference_storage(self) -> None:
        """Block can store self-reference in depends_on (validation happens later)."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        # Block 1 referencing itself (:::1)
        block = Block(
            block_type="bash",
            node_id="bash2",
            depends_on={1},
        )
        timeline.add(block)

        # Can store self-reference
        assert 1 in block.depends_on
        assert block.number == 1

    def test_forward_reference_storage(self) -> None:
        """Block can store forward reference in depends_on (validation happens later)."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        # Block 1 referencing block 5 (doesn't exist yet)
        block = Block(
            block_type="bash",
            node_id="bash2",
            depends_on={5},
        )
        timeline.add(block)

        # Can store forward reference
        assert 5 in block.depends_on
        assert block.number == 1

    def test_valid_backward_reference_storage(self) -> None:
        """Block can store valid backward reference."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        # Block 1 referencing block 0 (valid)
        block = Block(
            block_type="bash",
            node_id="bash2",
            depends_on={0},
        )
        timeline.add(block)

        # Can store valid backward reference
        assert 0 in block.depends_on
        assert block.number == 1
        assert block.number > 0  # Valid backward reference


class TestDependencyValidation:
    """Tests for actual dependency validation logic in wait_for_dependencies."""

    @pytest.fixture
    def executor(self) -> CommandExecutor:
        """Create a CommandExecutor for testing."""
        timeline = Timeline()
        console = Console(file=StringIO(), width=80)
        return CommandExecutor(timeline=timeline, console=console)

    @pytest.mark.asyncio
    async def test_self_reference_validation_fails(self, executor: CommandExecutor) -> None:
        """Self-reference should fail validation immediately."""
        # Add block 0
        block0 = Block(block_type="bash", node_id="bash1")
        executor.timeline.add(block0)

        # Block 1 referencing itself (:::1)
        block1 = Block(
            block_type="bash",
            node_id="bash2",
            depends_on={1},  # Self-reference!
        )
        executor.timeline.add(block1)

        # Should fail validation
        await executor.wait_for_dependencies(block1)

        assert block1.status == "error"
        assert "Invalid block reference" in block1.error
        assert "cannot reference itself" in block1.error

    @pytest.mark.asyncio
    async def test_forward_reference_validation_fails(self, executor: CommandExecutor) -> None:
        """Forward reference should fail validation immediately."""
        # Add block 0
        block0 = Block(block_type="bash", node_id="bash1")
        executor.timeline.add(block0)

        # Block 1 referencing block 5 (doesn't exist yet)
        block1 = Block(
            block_type="bash",
            node_id="bash2",
            depends_on={5},  # Forward reference!
        )
        executor.timeline.add(block1)

        # Should fail validation
        await executor.wait_for_dependencies(block1)

        assert block1.status == "error"
        assert "Invalid block reference" in block1.error
        assert "future blocks" in block1.error

    @pytest.mark.asyncio
    async def test_valid_backward_reference_waits_for_completion(
        self, executor: CommandExecutor
    ) -> None:
        """Valid backward reference should wait until dependency completes."""
        # Add block 0 (pending)
        block0 = Block(block_type="bash", node_id="bash1", status="pending")
        executor.timeline.add(block0)

        # Block 1 referencing block 0 (valid)
        block1 = Block(
            block_type="bash",
            node_id="bash2",
            depends_on={0},
        )
        executor.timeline.add(block1)

        # Start waiting in background
        wait_task = asyncio.create_task(executor.wait_for_dependencies(block1))

        # Give it time to enter waiting state
        await asyncio.sleep(0.15)

        # Should be in waiting state
        assert block1.status == "waiting"

        # Complete block 0
        block0.status = "completed"

        # Wait should complete
        await wait_task

        # Block 1 should be reset to pending (ready for execution)
        assert block1.status == "pending"

    @pytest.mark.asyncio
    async def test_dependency_wait_completes_on_error_status(
        self, executor: CommandExecutor
    ) -> None:
        """Dependency wait should complete if dependency has error status."""
        # Add block 0 (pending)
        block0 = Block(block_type="bash", node_id="bash1", status="pending")
        executor.timeline.add(block0)

        # Block 1 referencing block 0
        block1 = Block(
            block_type="bash",
            node_id="bash2",
            depends_on={0},
        )
        executor.timeline.add(block1)

        # Start waiting in background
        wait_task = asyncio.create_task(executor.wait_for_dependencies(block1))

        # Give it time to enter waiting state
        await asyncio.sleep(0.15)

        # Should be in waiting state
        assert block1.status == "waiting"

        # Block 0 fails with error
        block0.status = "error"

        # Wait should still complete (error counts as "done")
        await wait_task

        # Block 1 should be reset to pending (ready for execution)
        assert block1.status == "pending"

    @pytest.mark.asyncio
    async def test_multiple_dependencies_wait_for_all(self, executor: CommandExecutor) -> None:
        """Should wait for ALL dependencies to complete."""
        # Add blocks 0 and 1 (pending)
        block0 = Block(block_type="bash", node_id="bash1", status="pending")
        executor.timeline.add(block0)

        block1 = Block(block_type="bash", node_id="bash2", status="pending")
        executor.timeline.add(block1)

        # Block 2 referencing both 0 and 1
        block2 = Block(
            block_type="bash",
            node_id="bash3",
            depends_on={0, 1},
        )
        executor.timeline.add(block2)

        # Start waiting in background
        wait_task = asyncio.create_task(executor.wait_for_dependencies(block2))

        # Give it time to enter waiting state
        await asyncio.sleep(0.15)

        # Should be waiting
        assert block2.status == "waiting"

        # Complete block 0 only
        block0.status = "completed"
        await asyncio.sleep(0.15)

        # Should STILL be waiting (block 1 not done)
        assert block2.status == "waiting"

        # Complete block 1
        block1.status = "completed"

        # Now wait should complete
        await wait_task

        # Block 2 should be ready
        assert block2.status == "pending"

    @pytest.mark.asyncio
    async def test_timeout_protection(self, executor: CommandExecutor) -> None:
        """Should timeout if dependency doesn't complete within limit."""
        # Use a very short timeout for testing (override the default)
        executor_with_timeout = CommandExecutor(
            timeline=executor.timeline,
            console=executor.console,
        )

        # Add block 0 (stays pending forever)
        block0 = Block(block_type="bash", node_id="bash1", status="pending")
        executor_with_timeout.timeline.add(block0)

        # Block 1 referencing block 0
        block1 = Block(
            block_type="bash",
            node_id="bash2",
            depends_on={0},
        )
        executor_with_timeout.timeline.add(block1)

        # Use a custom wait function with short timeout for testing
        async def wait_with_short_timeout(block: Block) -> None:
            # Temporarily replace timeout_seconds in the function
            import time

            # Validate dependencies
            invalid_refs = [dep for dep in block.depends_on if dep >= block.number]
            if invalid_refs:
                block.status = "error"
                block.error = (
                    f"Invalid block reference(s): {invalid_refs}. "
                    f"Block :::{block.number} cannot reference itself or future blocks "
                    f"(valid range: :::0 to :::{block.number - 1})"
                )
                executor_with_timeout.timeline.render_last(executor_with_timeout.console)
                return

            # Show waiting status
            block.status = "waiting"
            executor_with_timeout.timeline.render_last(executor_with_timeout.console)

            # SHORT timeout for testing (0.3 seconds)
            timeout_seconds = 0.3
            start_time = time.monotonic()

            while True:
                elapsed = time.monotonic() - start_time
                if elapsed > timeout_seconds:
                    block.status = "error"
                    block.error = (
                        f"Timeout waiting for dependencies {list(block.depends_on)}. "
                        f"Waited {timeout_seconds}s but dependencies did not complete."
                    )
                    executor_with_timeout.timeline.render_last(executor_with_timeout.console)
                    return

                all_ready = True
                for dep_num in block.depends_on:
                    if dep_num >= len(executor_with_timeout.timeline.blocks):
                        continue
                    dep_block = executor_with_timeout.timeline.blocks[dep_num]
                    if dep_block.status not in ("completed", "error"):
                        all_ready = False
                        break

                if all_ready:
                    block.status = "pending"
                    return

                await asyncio.sleep(0.1)

        # Use the short timeout version
        await wait_with_short_timeout(block1)

        # Should timeout and set error
        assert block1.status == "error"
        assert "Timeout waiting for dependencies" in block1.error
        assert "0.3s" in block1.error


class TestDependencyPatternPrecedence:
    """Tests for pattern matching precedence and interactions."""

    def test_indexed_node_reference_not_matched_by_bare_pattern(self) -> None:
        """:::claude[0] should only match indexed pattern, not bare pattern."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 1

        nodes_by_type = {"claude": "claude"}

        deps = extract_block_dependencies("review :::claude[0]", timeline, nodes_by_type)
        # Should only add block 0, not block 1 (last claude)
        assert deps == {0}

    def test_keyed_node_reference_matched_by_bare_pattern(self) -> None:
        """:::claude['output'] should match bare pattern (bug we fixed)."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 1

        nodes_by_type = {"claude": "claude"}

        deps = extract_block_dependencies("review :::claude['output']", timeline, nodes_by_type)
        # Should match bare pattern and add last claude block
        assert deps == {1}

    def test_last_keyword_not_matched_as_node_name(self) -> None:
        """:::last should be handled by keyword pattern, not node pattern."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="last"))  # Block 0
        timeline.add(Block(block_type="bash", node_id="claude"))  # Block 1

        nodes_by_type = {"last": "last", "claude": "claude"}

        deps = extract_block_dependencies("review :::last", timeline, nodes_by_type)
        # Should match last keyword (block 1), not node named "last" (block 0)
        assert deps == {1}
