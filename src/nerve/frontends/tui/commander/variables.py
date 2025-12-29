"""Variable expansion for Commander TUI.

Expands block references in text, supporting:
    Block references (0-indexed):
        :::0                     - first block's output
        :::N['output']           - output from block N
        :::N['input']            - input from block N
        :::N['raw']['stdout']    - raw stdout from block N
        :::-1                    - last block (negative indexing)
        :::-2                    - second to last block
        :::last                  - last block's output

    Node references (per-node indexing):
        :::claude                - last block from node 'claude'
        :::claude[0]             - first block from 'claude'
        :::claude[-1]            - last block from 'claude'
        :::claude[-2]            - second to last from 'claude'
        :::bash[0]['input']      - first bash block's input
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nerve.frontends.tui.commander.blocks import Block, Timeline


class VariableExpander:
    """Expands :::N['key'] and :::nodename variables in text.

    Example:
        expander = VariableExpander(timeline)
        expanded = expander.expand("Previous output: :::-1")
    """

    def __init__(self, timeline: Timeline) -> None:
        """Initialize expander with a timeline.

        Args:
            timeline: The timeline containing blocks to reference.
        """
        self.timeline = timeline

    def expand(self, text: str) -> str:
        """Expand all variable references in text.

        Args:
            text: Text with variable references.

        Returns:
            Text with variables expanded to their values.
        """
        # Apply patterns in order (most specific first)
        # Negative index patterns
        text = self._expand_neg_raw(text)
        text = self._expand_neg_key(text)
        text = self._expand_neg_bare(text)

        # Positive index patterns
        text = self._expand_raw(text)
        text = self._expand_last_raw(text)
        text = self._expand_key(text)
        text = self._expand_last_key(text)
        text = self._expand_bare(text)
        text = self._expand_last_bare(text)

        # Node-based patterns (most specific first)
        text = self._expand_node_idx_raw(text)
        text = self._expand_node_idx_key(text)
        text = self._expand_node_idx_bare(text)
        text = self._expand_node_key(text)
        text = self._expand_node_bare(text)

        return text

    # =========================================================================
    # Block Access Helpers
    # =========================================================================

    def _get_block_by_negative_index(self, neg_idx: int) -> Block | None:
        """Get block by negative index (-1 = last, -2 = second to last)."""
        blocks = self.timeline.blocks
        if not blocks:
            return None
        try:
            return blocks[neg_idx]  # Python handles negative indexing
        except IndexError:
            return None

    def _get_node_blocks(self, node_id: str) -> list[Block]:
        """Get all blocks for a specific node."""
        return [b for b in self.timeline.blocks if b.node_id == node_id]

    def _get_node_block_by_index(self, node_id: str, idx: int) -> Block | None:
        """Get block by index within a node's blocks (supports negative indexing)."""
        node_blocks = self._get_node_blocks(node_id)
        if not node_blocks:
            return None
        try:
            return node_blocks[idx]
        except IndexError:
            return None

    # =========================================================================
    # Negative Index Patterns
    # =========================================================================

    def _expand_neg_raw(self, text: str) -> str:
        """Expand :::-N['raw']['key'] pattern."""
        pattern = r":::(-\d+)\[(['\"])raw\2\]\[(['\"])(\w+)\3\]"

        def replace(match: re.Match[str]) -> str:
            neg_idx = int(match.group(1))
            key = match.group(4)
            block = self._get_block_by_negative_index(neg_idx)
            if block is None:
                return f"<error: no block at index {neg_idx}>"
            try:
                raw = block["raw"]
                if isinstance(raw, dict):
                    return str(raw.get(key, f"<no key: {key}>"))
                return "<error: raw is not a dict>"
            except KeyError as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    def _expand_neg_key(self, text: str) -> str:
        """Expand :::-N['key'] pattern."""
        pattern = r":::(-\d+)\[(['\"])(\w+)\2\]"

        def replace(match: re.Match[str]) -> str:
            neg_idx = int(match.group(1))
            key = match.group(3)
            block = self._get_block_by_negative_index(neg_idx)
            if block is None:
                return f"<error: no block at index {neg_idx}>"
            try:
                value = block[key]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    def _expand_neg_bare(self, text: str) -> str:
        """Expand :::-N bare pattern (shorthand for :::-N['output'])."""
        pattern = r":::(-\d+)(?!\[)"

        def replace(match: re.Match[str]) -> str:
            neg_idx = int(match.group(1))
            block = self._get_block_by_negative_index(neg_idx)
            if block is None:
                return f"<error: no block at index {neg_idx}>"
            try:
                value = block["output"]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    # =========================================================================
    # Positive Index Patterns
    # =========================================================================

    def _expand_raw(self, text: str) -> str:
        """Expand :::N['raw']['key'] pattern."""
        pattern = r":::(\d+)\[(['\"])raw\2\]\[(['\"])(\w+)\3\]"

        def replace(match: re.Match[str]) -> str:
            block_num = int(match.group(1))
            key = match.group(4)
            try:
                block = self.timeline[block_num]
                raw = block["raw"]
                if isinstance(raw, dict):
                    return str(raw.get(key, f"<no key: {key}>"))
                return "<error: raw is not a dict>"
            except (IndexError, KeyError) as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    def _expand_last_raw(self, text: str) -> str:
        """Expand :::last['raw']['key'] pattern."""
        pattern = r":::last\[(['\"])raw\1\]\[(['\"])(\w+)\2\]"

        def replace(match: re.Match[str]) -> str:
            key = match.group(3)
            block = self.timeline.last()
            if block is None:
                return "<error: no blocks yet>"
            try:
                raw = block["raw"]
                if isinstance(raw, dict):
                    return str(raw.get(key, f"<no key: {key}>"))
                return "<error: raw is not a dict>"
            except KeyError as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    def _expand_key(self, text: str) -> str:
        """Expand :::N['key'] pattern."""
        pattern = r":::(\d+)\[(['\"])(\w+)\2\]"

        def replace(match: re.Match[str]) -> str:
            block_num = int(match.group(1))
            key = match.group(3)
            try:
                block = self.timeline[block_num]
                value = block[key]
                return str(value) if not isinstance(value, str) else value
            except (IndexError, KeyError) as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    def _expand_last_key(self, text: str) -> str:
        """Expand :::last['key'] pattern."""
        pattern = r":::last\[(['\"])(\w+)\1\]"

        def replace(match: re.Match[str]) -> str:
            key = match.group(2)
            block = self.timeline.last()
            if block is None:
                return "<error: no blocks yet>"
            try:
                value = block[key]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    def _expand_bare(self, text: str) -> str:
        """Expand :::N bare pattern (shorthand for :::N['output'])."""
        pattern = r":::(\d+)(?!\[)"

        def replace(match: re.Match[str]) -> str:
            block_num = int(match.group(1))
            try:
                block = self.timeline[block_num]
                value = block["output"]
                return str(value) if not isinstance(value, str) else value
            except (IndexError, KeyError) as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    def _expand_last_bare(self, text: str) -> str:
        """Expand :::last bare pattern (shorthand for :::last['output'])."""
        pattern = r":::last(?!\[)"

        def replace(match: re.Match[str]) -> str:
            block = self.timeline.last()
            if block is None:
                return "<error: no blocks yet>"
            try:
                value = block["output"]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    # =========================================================================
    # Node-Based Patterns
    # =========================================================================

    def _expand_node_idx_raw(self, text: str) -> str:
        """Expand :::node[N]['raw']['key'] pattern."""
        pattern = r":::([a-zA-Z_][a-zA-Z0-9_-]*)\[(-?\d+)\]\[(['\"])raw\3\]\[(['\"])(\w+)\4\]"

        def replace(match: re.Match[str]) -> str:
            node_id = match.group(1)
            idx = int(match.group(2))
            key = match.group(5)
            block = self._get_node_block_by_index(node_id, idx)
            if block is None:
                return f"<error: no block for {node_id}[{idx}]>"
            try:
                raw = block["raw"]
                if isinstance(raw, dict):
                    return str(raw.get(key, f"<no key: {key}>"))
                return "<error: raw is not a dict>"
            except KeyError as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    def _expand_node_idx_key(self, text: str) -> str:
        """Expand :::node[N]['key'] pattern."""
        pattern = r":::([a-zA-Z_][a-zA-Z0-9_-]*)\[(-?\d+)\]\[(['\"])(\w+)\3\]"

        def replace(match: re.Match[str]) -> str:
            node_id = match.group(1)
            idx = int(match.group(2))
            key = match.group(4)
            block = self._get_node_block_by_index(node_id, idx)
            if block is None:
                return f"<error: no block for {node_id}[{idx}]>"
            try:
                value = block[key]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    def _expand_node_idx_bare(self, text: str) -> str:
        """Expand :::node[N] bare pattern (shorthand for :::node[N]['output'])."""
        pattern = r":::([a-zA-Z_][a-zA-Z0-9_-]*)\[(-?\d+)\](?!\[)"

        def replace(match: re.Match[str]) -> str:
            node_id = match.group(1)
            idx = int(match.group(2))
            block = self._get_node_block_by_index(node_id, idx)
            if block is None:
                return f"<error: no block for {node_id}[{idx}]>"
            try:
                value = block["output"]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    def _expand_node_key(self, text: str) -> str:
        """Expand :::node['key'] pattern (last block from node)."""
        pattern = r":::([a-zA-Z_][a-zA-Z0-9_-]*)\[(['\"])(\w+)\2\]"

        def replace(match: re.Match[str]) -> str:
            node_id = match.group(1)
            key = match.group(3)
            block = self._get_node_block_by_index(node_id, -1)  # Last block
            if block is None:
                return f"<error: no blocks for {node_id}>"
            try:
                value = block[key]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)

    def _expand_node_bare(self, text: str) -> str:
        """Expand :::node bare pattern (last block's output from node)."""
        # Must not match "last" or start with digit
        pattern = r":::([a-zA-Z_][a-zA-Z0-9_-]*)(?!\[)"

        def replace(match: re.Match[str]) -> str:
            node_id = match.group(1)
            if node_id == "last":  # Skip, handled by _expand_last_bare
                return match.group(0)
            block = self._get_node_block_by_index(node_id, -1)  # Last block
            if block is None:
                return f"<error: no blocks for {node_id}>"
            try:
                value = block["output"]
                return str(value) if not isinstance(value, str) else value
            except KeyError as e:
                return f"<error: {e}>"

        return re.sub(pattern, replace, text)


def expand_variables(timeline: Timeline, text: str) -> str:
    """Convenience function to expand variables in text.

    Args:
        timeline: The timeline containing blocks to reference.
        text: Text with variable references.

    Returns:
        Text with variables expanded to their values.
    """
    return VariableExpander(timeline).expand(text)
