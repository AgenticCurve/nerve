"""Tests for Commander TUI variable expansion.

Tests the variable expansion logic that replaces :::N references
with actual block outputs.
"""

from __future__ import annotations

from nerve.frontends.tui.commander.blocks import Block, Timeline
from nerve.frontends.tui.commander.variables import VariableExpander, expand_variables


class TestNumericBlockReferences:
    """Tests for numeric block reference expansion (:::N)."""

    def test_expand_single_numeric_reference(self) -> None:
        """:::N should expand to block N's output."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="hello"))

        result = expand_variables(timeline, "review :::0")
        assert result == "review hello"

    def test_expand_multiple_numeric_references(self) -> None:
        """Multiple :::N references should all expand."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="hello"))
        timeline.add(Block(block_type="bash", node_id="bash2", output_text="world"))

        result = expand_variables(timeline, "compare :::0 and :::1")
        assert result == "compare hello and world"

    def test_expand_numeric_reference_with_output_key(self) -> None:
        """:::N['output'] should expand to block N's output."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="test output"))

        result = expand_variables(timeline, "review :::0['output']")
        assert result == "review test output"

    def test_expand_numeric_reference_with_input_key(self) -> None:
        """:::N['input'] should expand to block N's input."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", input_text="original command"))

        result = expand_variables(timeline, "check :::0['input']")
        assert result == "check original command"

    def test_expand_numeric_reference_with_raw_key(self) -> None:
        """:::N['raw']['stdout'] should expand to raw field."""
        timeline = Timeline()
        block = Block(block_type="bash", node_id="bash1")
        block.raw = {"stdout": "raw output", "stderr": ""}
        timeline.add(block)

        result = expand_variables(timeline, "check :::0['raw']['stdout']")
        assert result == "check raw output"

    def test_expand_nonexistent_block(self) -> None:
        """Reference to non-existent block should show error."""
        timeline = Timeline()

        result = expand_variables(timeline, "review :::5")
        assert "<error:" in result.lower()

    def test_expand_nonexistent_key(self) -> None:
        """Reference to non-existent key should show error."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1"))

        result = expand_variables(timeline, "check :::0['nonexistent']")
        assert "<error:" in result.lower() or "<no key:" in result.lower()


class TestNegativeIndexReferences:
    """Tests for negative index reference expansion (:::-N)."""

    def test_expand_last_with_negative_one(self) -> None:
        """:::-1 should expand to last block's output."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="first"))
        timeline.add(Block(block_type="bash", node_id="bash2", output_text="second"))
        timeline.add(Block(block_type="bash", node_id="bash3", output_text="third"))

        result = expand_variables(timeline, "review :::-1")
        assert result == "review third"

    def test_expand_second_to_last(self) -> None:
        """:::-2 should expand to second-to-last block's output."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="first"))
        timeline.add(Block(block_type="bash", node_id="bash2", output_text="second"))
        timeline.add(Block(block_type="bash", node_id="bash3", output_text="third"))

        result = expand_variables(timeline, "review :::-2")
        assert result == "review second"

    def test_expand_negative_index_with_key(self) -> None:
        """:::-1['input'] should expand to last block's input."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", input_text="first cmd"))
        timeline.add(Block(block_type="bash", node_id="bash2", input_text="second cmd"))

        result = expand_variables(timeline, "check :::-1['input']")
        assert result == "check second cmd"

    def test_expand_negative_index_out_of_bounds(self) -> None:
        """Negative index out of bounds should show error."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="only"))

        result = expand_variables(timeline, "review :::-5")
        assert "<error:" in result.lower()

    def test_negative_index_excludes_current_block(self) -> None:
        """:::-1 should reference previous block, not the current block being created.

        This test simulates the scenario where we're creating a new block that uses :::-1.
        The new block should reference the PREVIOUS block, not itself.

        Timeline state:
        - Block 0: "first"
        - Block 1: "second"
        - Block 2: (being created, uses :::-1)

        Expected: :::-1 should expand to "second" (block 1), not block 2.
        """
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="first"))
        timeline.add(Block(block_type="bash", node_id="bash2", output_text="second"))

        # Simulate creating block 2 that references :::-1
        # Add the block to timeline (as would happen in commander.py)
        current_block = Block(block_type="bash", node_id="bash3", input_text=":::-1")
        timeline.add(current_block)

        # Now expand variables, excluding the current block from negative index resolution
        result = expand_variables(
            timeline, ":::-1", nodes_by_type=None, exclude_block_from=current_block.number
        )

        # Should expand to "second" (block 1), not reference block 2 (current block)
        assert result == "second"

    def test_negative_index_minus_two_excludes_current_block(self) -> None:
        """:::-2 should reference 2 blocks back, not 1 block back.

        Timeline state:
        - Block 0: "zero"
        - Block 1: "one"
        - Block 2: "two"
        - Block 3: (being created, uses :::-2)

        Expected: :::-2 should expand to "one" (block 1), not "two" (block 2).
        """
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="zero"))
        timeline.add(Block(block_type="bash", node_id="bash2", output_text="one"))
        timeline.add(Block(block_type="bash", node_id="bash3", output_text="two"))

        # Simulate creating block 3 that references :::-2
        current_block = Block(block_type="bash", node_id="bash4", input_text=":::-2")
        timeline.add(current_block)

        # Expand with current block excluded
        result = expand_variables(
            timeline, ":::-2", nodes_by_type=None, exclude_block_from=current_block.number
        )

        # Should expand to "one" (block 1), not "two" (block 2)
        assert result == "one"

    def test_negative_index_without_exclude_includes_current(self) -> None:
        """Without exclude_block_from, :::-1 includes all blocks (backward compatibility).

        This ensures that existing code that doesn't pass exclude_block_from
        still works as expected (though it may reference unintended blocks).
        """
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="first"))
        timeline.add(Block(block_type="bash", node_id="bash2", output_text="second"))

        # Don't pass exclude_block_from - should use all blocks
        result = expand_variables(timeline, ":::-1", nodes_by_type=None)

        # Should expand to "second" (last block in timeline)
        assert result == "second"


class TestLastKeywordReferences:
    """Tests for :::last keyword expansion."""

    def test_expand_last_keyword(self) -> None:
        """:::last should expand to last block's output."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="first"))
        timeline.add(Block(block_type="bash", node_id="bash2", output_text="last"))

        result = expand_variables(timeline, "review :::last")
        assert result == "review last"

    def test_expand_last_keyword_with_key(self) -> None:
        """:::last['input'] should expand to last block's input."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", input_text="first cmd"))
        timeline.add(Block(block_type="bash", node_id="bash2", input_text="last cmd"))

        result = expand_variables(timeline, "check :::last['input']")
        assert result == "check last cmd"

    def test_expand_last_keyword_with_raw(self) -> None:
        """:::last['raw']['stderr'] should expand to raw field."""
        timeline = Timeline()
        block = Block(block_type="bash", node_id="bash1")
        block.raw = {"stdout": "", "stderr": "error message"}
        timeline.add(block)

        result = expand_variables(timeline, "check :::last['raw']['stderr']")
        assert result == "check error message"

    def test_expand_last_on_empty_timeline(self) -> None:
        """:::last on empty timeline should show error."""
        timeline = Timeline()

        result = expand_variables(timeline, "review :::last")
        assert "<error:" in result.lower()


class TestNodeReferences:
    """Tests for node reference expansion (:::nodename)."""

    def test_expand_node_reference_last_block(self) -> None:
        """:::nodename should expand to last block from that node."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude", output_text="first claude"))
        timeline.add(Block(block_type="bash", node_id="gemini", output_text="gemini"))
        timeline.add(Block(block_type="bash", node_id="claude", output_text="second claude"))

        nodes_by_type = {"claude": "claude", "gemini": "gemini"}

        result = expand_variables(timeline, "review :::claude", nodes_by_type)
        assert result == "review second claude"

    def test_expand_node_reference_with_index(self) -> None:
        """:::nodename[N] should expand to Nth block from that node."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude", output_text="first"))
        timeline.add(Block(block_type="bash", node_id="claude", output_text="second"))
        timeline.add(Block(block_type="bash", node_id="claude", output_text="third"))

        nodes_by_type = {"claude": "claude"}

        result = expand_variables(timeline, "review :::claude[0]", nodes_by_type)
        assert result == "review first"

    def test_expand_node_reference_with_negative_index(self) -> None:
        """:::nodename[-1] should expand to last block from that node."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude", output_text="first"))
        timeline.add(Block(block_type="bash", node_id="claude", output_text="second"))

        nodes_by_type = {"claude": "claude"}

        result = expand_variables(timeline, "review :::claude[-1]", nodes_by_type)
        assert result == "review second"

    def test_expand_node_reference_with_key(self) -> None:
        """:::nodename['input'] should expand to last block's input."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude", input_text="first cmd"))
        timeline.add(Block(block_type="bash", node_id="claude", input_text="second cmd"))

        nodes_by_type = {"claude": "claude"}

        result = expand_variables(timeline, "check :::claude['input']", nodes_by_type)
        assert result == "check second cmd"

    def test_expand_node_reference_indexed_with_key(self) -> None:
        """:::nodename[N]['output'] should expand correctly."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude", output_text="first"))
        timeline.add(Block(block_type="bash", node_id="claude", output_text="second"))

        nodes_by_type = {"claude": "claude"}

        result = expand_variables(timeline, "review :::claude[0]['output']", nodes_by_type)
        assert result == "review first"

    def test_expand_multiple_node_references(self) -> None:
        """Multiple node references should all expand."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude", output_text="claude says"))
        timeline.add(Block(block_type="bash", node_id="gemini", output_text="gemini says"))

        nodes_by_type = {"claude": "claude", "gemini": "gemini"}

        result = expand_variables(timeline, "compare :::claude and :::gemini", nodes_by_type)
        assert result == "compare claude says and gemini says"

    def test_expand_node_reference_nonexistent_node(self) -> None:
        """Reference to non-existent node should show error."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude", output_text="output"))

        nodes_by_type = {"claude": "claude"}

        result = expand_variables(timeline, "review :::gemini", nodes_by_type)
        assert "<error:" in result.lower()

    def test_expand_node_reference_without_nodes_by_type(self) -> None:
        """Node reference without nodes_by_type still tries to match by node_id."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude", output_text="output"))

        result = expand_variables(timeline, "review :::claude")
        # Even without nodes_by_type, it matches blocks by node_id directly
        assert result == "review output"


class TestMixedReferences:
    """Tests for mixed reference patterns in a single string."""

    def test_expand_mixed_numeric_and_node(self) -> None:
        """Mix of :::N and :::nodename should all expand."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="bash output"))
        timeline.add(Block(block_type="bash", node_id="claude", output_text="claude output"))

        nodes_by_type = {"claude": "claude"}

        result = expand_variables(timeline, "compare :::0 and :::claude", nodes_by_type)
        assert result == "compare bash output and claude output"

    def test_expand_mixed_with_keys(self) -> None:
        """Mix of keyed and bare references should all expand."""
        timeline = Timeline()
        timeline.add(
            Block(
                block_type="bash",
                node_id="bash1",
                input_text="input cmd",
                output_text="output text",
            )
        )

        result = expand_variables(timeline, "input: :::0['input'], output: :::0['output']")
        assert result == "input: input cmd, output: output text"

    def test_expand_same_block_multiple_times(self) -> None:
        """Same block referenced multiple times should expand each time."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="repeated"))

        result = expand_variables(timeline, ":::0 and :::0 again")
        assert result == "repeated and repeated again"


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_expand_empty_output(self) -> None:
        """Block with empty output should expand to empty string."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text=""))

        result = expand_variables(timeline, "result: :::0")
        assert result == "result: "

    def test_expand_with_error_block(self) -> None:
        """Block with error status should expand its output (if any)."""
        timeline = Timeline()
        block = Block(block_type="bash", node_id="bash1")
        block.status = "error"
        block.output_text = "partial output before error"
        timeline.add(block)

        result = expand_variables(timeline, "check :::0")
        assert result == "check partial output before error"

    def test_expand_no_references(self) -> None:
        """Text with no references should remain unchanged."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="output"))

        result = expand_variables(timeline, "no variables here")
        assert result == "no variables here"

    def test_expand_with_special_characters_in_output(self) -> None:
        """Output with special characters should expand correctly."""
        timeline = Timeline()
        timeline.add(
            Block(
                block_type="bash",
                node_id="bash1",
                output_text="output with 'quotes' and \"double quotes\"",
            )
        )

        result = expand_variables(timeline, ":::0")
        assert result == "output with 'quotes' and \"double quotes\""

    def test_expand_multiline_output(self) -> None:
        """Multiline output should expand with newlines preserved."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="line1\nline2\nline3"))

        result = expand_variables(timeline, "output:\n:::0")
        assert result == "output:\nline1\nline2\nline3"


class TestVariableExpanderClass:
    """Tests for VariableExpander class directly."""

    def test_expander_with_timeline(self) -> None:
        """VariableExpander should work with timeline."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="bash1", output_text="output"))

        expander = VariableExpander(timeline)
        result = expander.expand("check :::0")
        assert result == "check output"

    def test_expander_with_nodes_by_type(self) -> None:
        """VariableExpander should work with nodes_by_type."""
        timeline = Timeline()
        timeline.add(Block(block_type="bash", node_id="claude", output_text="claude output"))

        nodes_by_type = {"claude": "claude"}
        expander = VariableExpander(timeline, nodes_by_type)
        result = expander.expand("check :::claude")
        assert result == "check claude output"


class TestBashOutputPreference:
    """Tests for bash node output preference (stdout/stderr over output_text)."""

    def test_bash_node_prefers_stdout(self) -> None:
        """:::N['output'] for bash nodes should prefer raw stdout."""
        timeline = Timeline()
        block = Block(block_type="bash", node_id="bash1")
        block.output_text = "general output"
        block.raw = {"stdout": "stdout content", "stderr": ""}
        timeline.add(block)

        # Using dict-like access ['output'] should prefer stdout for bash nodes
        result = expand_variables(timeline, ":::0['output']")
        assert result == "stdout content"

    def test_bash_node_uses_stderr_if_no_stdout(self) -> None:
        """:::N['output'] should use stderr if stdout is empty."""
        timeline = Timeline()
        block = Block(block_type="bash", node_id="bash1")
        block.output_text = "general output"
        block.raw = {"stdout": "", "stderr": "stderr content"}
        timeline.add(block)

        result = expand_variables(timeline, ":::0['output']")
        assert result == "stderr content"

    def test_non_bash_node_uses_output_text(self) -> None:
        """:::N['output'] for non-bash nodes should use output_text."""
        timeline = Timeline()
        block = Block(block_type="llm", node_id="claude")
        block.output_text = "llm output"
        block.raw = {"some_field": "value"}
        timeline.add(block)

        result = expand_variables(timeline, ":::0['output']")
        assert result == "llm output"
