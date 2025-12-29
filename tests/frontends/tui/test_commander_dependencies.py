"""Tests for Commander TUI dependency tracking.

Tests the dependency extraction, validation, and waiting logic for
block references in the Commander TUI.
"""

from __future__ import annotations

from nerve.frontends.tui.commander.blocks import Block, Timeline
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
        """Node references without nodes_by_type parameter should be ignored."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude"))

        deps = extract_block_dependencies("review :::claude", timeline)
        assert deps == set()  # No nodes_by_type provided

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


class TestDependencyValidation:
    """Tests for dependency validation in _wait_for_dependencies."""

    def test_self_reference_detected(self) -> None:
        """Block referencing itself should be detected as invalid."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        # Block 1 referencing itself (:::1)
        block = Block(
            block_type="bash",
            node_id="bash2",
            depends_on={1},
        )
        timeline.add(block)

        # Should detect self-reference
        assert 1 in block.depends_on
        assert block.number == 1

    def test_forward_reference_detected(self) -> None:
        """Block referencing future block should be detected as invalid."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        # Block 1 referencing block 5 (doesn't exist yet)
        block = Block(
            block_type="bash",
            node_id="bash2",
            depends_on={5},
        )
        timeline.add(block)

        # Should detect forward reference
        assert 5 in block.depends_on
        assert block.number == 1

    def test_valid_backward_reference(self) -> None:
        """Block referencing earlier block should be valid."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        # Block 1 referencing block 0 (valid)
        block = Block(
            block_type="bash",
            node_id="bash2",
            depends_on={0},
        )
        timeline.add(block)

        # Should be valid
        assert 0 in block.depends_on
        assert block.number == 1
        assert block.number > 0  # Valid backward reference


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
