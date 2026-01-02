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

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nerve.frontends.tui.commander.blocks import Block, Timeline

logger = logging.getLogger(__name__)


class VariableExpander:
    """Expands :::N['key'] and :::nodename variables in text.

    Example:
        expander = VariableExpander(timeline)
        expanded = expander.expand("Previous output: :::-1")
    """

    def __init__(
        self,
        timeline: Timeline,
        nodes_by_type: dict[str, str] | None = None,
        exclude_block_from: int | None = None,
    ) -> None:
        """Initialize expander with a timeline.

        Args:
            timeline: The timeline containing blocks to reference.
            nodes_by_type: Optional mapping from node type/name to node ID.
                E.g., {"claude": "1", "bash": "2"} - maps user-facing names
                to internal node IDs used in blocks.
            exclude_block_from: Exclude blocks at or after this number when resolving
                negative indices. Used to ensure :::-1 references the previous block,
                not the current block being created.
        """
        self.timeline = timeline
        self.nodes_by_type = nodes_by_type or {}
        self.exclude_block_from = exclude_block_from

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
        """Get block by negative index (-1 = last, -2 = second to last).

        Respects exclude_block_from to ensure negative indices don't reference
        the current block being created.
        """
        blocks = self.timeline.blocks

        # Exclude blocks at or after the specified number (e.g., current block)
        if self.exclude_block_from is not None:
            blocks = [b for b in blocks if b.number < self.exclude_block_from]

        if not blocks:
            return None
        try:
            return blocks[neg_idx]  # Python handles negative indexing
        except IndexError:
            return None

    def _resolve_node_id(self, node_ref: str) -> str:
        """Resolve node reference (type/name) to actual node ID.

        Args:
            node_ref: Either a numeric node ID or a node type/name like "claude".

        Returns:
            The actual node ID to use for filtering blocks.
        """
        # If it's already a valid node ID (exists in nodes_by_type values), return as-is
        if node_ref in self.nodes_by_type.values():
            return node_ref
        # Otherwise, try to resolve from type/name to ID
        return self.nodes_by_type.get(node_ref, node_ref)

    def _get_node_blocks(self, node_ref: str) -> list[Block]:
        """Get all blocks for a specific node.

        Respects exclude_block_from to ensure node references resolve to the same
        blocks at expansion time as they did at dependency extraction time.

        Args:
            node_ref: Node reference (ID or type/name like "claude").
        """
        node_id = self._resolve_node_id(node_ref)
        blocks = [b for b in self.timeline.blocks if b.node_id == node_id]

        # Exclude blocks at or after the specified number (e.g., current block)
        # This prevents TOCTOU bugs where new blocks are added between
        # dependency extraction and expansion
        if self.exclude_block_from is not None:
            blocks = [b for b in blocks if b.number < self.exclude_block_from]

        return blocks

    def _get_node_block_by_index(self, node_ref: str, idx: int) -> Block | None:
        """Get block by index within a node's blocks (supports negative indexing).

        Args:
            node_ref: Node reference (ID or type/name like "claude").
            idx: Index within the node's blocks (supports negative indexing).
        """
        node_blocks = self._get_node_blocks(node_ref)
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


def expand_variables(
    timeline: Timeline,
    text: str,
    nodes_by_type: dict[str, str] | None = None,
    exclude_block_from: int | None = None,
) -> str:
    """Convenience function to expand variables in text.

    Args:
        timeline: The timeline containing blocks to reference.
        text: Text with variable references.
        nodes_by_type: Optional mapping from node type/name to node ID.
        exclude_block_from: Exclude blocks at or after this number when resolving
            negative indices. Pass the current block's number to ensure :::-1
            references the previous block, not the current one.

    Returns:
        Text with variables expanded to their values.
    """
    return VariableExpander(timeline, nodes_by_type, exclude_block_from).expand(text)


def extract_block_dependencies(
    text: str, timeline: Timeline, nodes_by_type: dict[str, str] | None = None
) -> set[int]:
    """Extract block numbers that this text depends on.

    Parses variable references to identify which blocks must complete
    before this text can be safely expanded and executed.

    Examples:
        "review :::0" -> {0}
        "compare :::0 and :::1" -> {0, 1}
        "check :::-1" -> {<actual last block number>}
        ":::last summary" -> {<last block number>}
        "review :::claude" -> {<last claude block number>}
        "compare :::claude[0] and :::gemini[0]" -> {<first claude>, <first gemini>}
        "no refs" -> set()

    Args:
        text: Text with potential variable references.
        timeline: Timeline to resolve relative references (:::last, :::-N, :::node).
        nodes_by_type: Optional mapping from node type/name to node ID.
            Required for resolving node references like :::claude.

    Returns:
        Set of block numbers (0-indexed) that must be completed before
        this text can be expanded.
    """
    dependencies = set()

    # Pattern 1: :::N (positive numeric references)
    for match in re.finditer(r":::(\d+)", text):
        dependencies.add(int(match.group(1)))

    # Pattern 2: :::-N (negative indexing - resolve to actual block number NOW)
    for match in re.finditer(r":::(-\d+)", text):
        neg_idx = int(match.group(1))
        actual_idx = len(timeline.blocks) + neg_idx
        if 0 <= actual_idx < len(timeline.blocks):
            dependencies.add(actual_idx)

    # Pattern 3: :::last (resolve to last block number NOW)
    if ":::last" in text and timeline.blocks:
        dependencies.add(len(timeline.blocks) - 1)

    # Pattern 4 & 5: Node references (:::nodename, :::nodename[N])
    # Resolve to actual block numbers at extraction time
    # Works even without nodes_by_type by using node_ref directly as node_id

    # Pattern 4a: :::nodename[N] - specific indexed block from node
    # Must check this BEFORE bare nodename to avoid partial matches
    for match in re.finditer(r":::([a-zA-Z_][a-zA-Z0-9_-]*)\[(-?\d+)\]", text):
        node_ref = match.group(1)
        if node_ref == "last":
            continue  # Already handled by pattern 3

        idx = int(match.group(2))

        # Resolve node_ref to actual node_id
        # If nodes_by_type provided, try to resolve, otherwise use node_ref as-is
        node_id = nodes_by_type.get(node_ref, node_ref) if nodes_by_type else node_ref

        # Find all blocks for this node
        node_blocks = [b for b in timeline.blocks if b.node_id == node_id]

        # Get the specific indexed block (supports negative indexing)
        if node_blocks:
            try:
                target_block = node_blocks[idx]
                dependencies.add(target_block.number)
            except IndexError:
                pass  # Out of bounds - will error during expansion

    # Pattern 4b: :::nodename - last block from node
    # Negative lookahead: don't match if followed by [NUMBER] (handled by pattern 4a)
    # But DO match if followed by ['key'] (keyed access like :::claude['output'])
    for match in re.finditer(r":::([a-zA-Z_][a-zA-Z0-9_-]*)(?!\[-?\d+\])", text):
        node_ref = match.group(1)
        if node_ref == "last":
            continue  # Already handled by pattern 3

        # Resolve node_ref to actual node_id
        # If nodes_by_type provided, try to resolve, otherwise use node_ref as-is
        node_id = nodes_by_type.get(node_ref, node_ref) if nodes_by_type else node_ref

        # Find all blocks for this node
        node_blocks = [b for b in timeline.blocks if b.node_id == node_id]

        # Get the last block from this node
        if node_blocks:
            last_block_num = node_blocks[-1].number
            dependencies.add(last_block_num)
            # DEBUG: Show which block is being referenced
            logger.debug(
                ":::%s resolved to block %d (found %d blocks for node '%s', using last one)",
                node_ref,
                last_block_num,
                len(node_blocks),
                node_id,
            )

    return dependencies


def validate_variable_references(
    text: str, timeline: Timeline, nodes_by_type: dict[str, str] | None = None
) -> list[str]:
    """Validate variable references and return list of errors.

    Checks for unresolvable references that would fail during expansion:
    - Node references (:::nodename) where the node has no blocks yet
    - :::last when timeline is empty
    - :::-N when timeline has fewer than N blocks

    Use this BEFORE extract_block_dependencies to fail fast on invalid references.

    Args:
        text: Text with potential variable references.
        timeline: Timeline to validate against.
        nodes_by_type: Optional mapping from node type/name to node ID.

    Returns:
        List of error messages. Empty list means all references are valid.

    Example:
        errors = validate_variable_references("review :::nav", timeline, nodes_by_type)
        if errors:
            # Handle errors - don't proceed with block creation
            for err in errors:
                print(f"Error: {err}")
    """
    errors: list[str] = []

    # Check :::last on empty timeline
    if ":::last" in text and not timeline.blocks:
        errors.append(":::last cannot be used - no blocks in timeline yet")

    # Check :::-N references
    for match in re.finditer(r":::(-\d+)", text):
        neg_idx = int(match.group(1))
        actual_idx = len(timeline.blocks) + neg_idx
        if actual_idx < 0 or actual_idx >= len(timeline.blocks):
            if not timeline.blocks:
                errors.append(f":::{neg_idx} cannot be used - no blocks in timeline yet")
            else:
                errors.append(
                    f":::{neg_idx} is out of range - only {len(timeline.blocks)} block(s) exist"
                )

    # Check :::N positive references (don't match :::N[...] indexed patterns)
    for match in re.finditer(r":::(\d+)(?!\[)", text):
        block_num = int(match.group(1))
        if block_num >= len(timeline.blocks):
            if not timeline.blocks:
                errors.append(f":::{block_num} cannot be used - no blocks in timeline yet")
            else:
                errors.append(
                    f":::{block_num} is out of range - only {len(timeline.blocks)} block(s) exist"
                )

    # Check :::nodename[N] references
    for match in re.finditer(r":::([a-zA-Z_][a-zA-Z0-9_-]*)\[(-?\d+)\]", text):
        node_ref = match.group(1)
        if node_ref == "last":
            continue  # Handled above

        idx = int(match.group(2))
        node_id = nodes_by_type.get(node_ref, node_ref) if nodes_by_type else node_ref
        node_blocks = [b for b in timeline.blocks if b.node_id == node_id]

        if not node_blocks:
            errors.append(
                f":::{node_ref}[{idx}] cannot be used - node '{node_ref}' has no blocks yet"
            )
        else:
            # Check index bounds
            try:
                _ = node_blocks[idx]
            except IndexError:
                errors.append(
                    f":::{node_ref}[{idx}] is out of range - node '{node_ref}' only has {len(node_blocks)} block(s)"
                )

    # Check bare :::nodename references (must check AFTER indexed to avoid double-reporting)
    # Track indexed refs we've already seen to avoid partial matching issues
    indexed_refs = set()
    for match in re.finditer(r":::([a-zA-Z_][a-zA-Z0-9_-]*)\[-?\d+\]", text):
        indexed_refs.add(match.start())

    for match in re.finditer(r":::([a-zA-Z_][a-zA-Z0-9_-]*)", text):
        # Skip if this position was already handled by indexed pattern
        if match.start() in indexed_refs:
            continue

        node_ref = match.group(1)
        if node_ref == "last":
            continue  # Handled above

        # Skip if this is actually an indexed ref (the pattern might have matched a prefix)
        # Check if the full match is followed by [
        end_pos = match.end()
        if end_pos < len(text) and text[end_pos] == "[":
            continue

        node_id = nodes_by_type.get(node_ref, node_ref) if nodes_by_type else node_ref
        node_blocks = [b for b in timeline.blocks if b.node_id == node_id]

        if not node_blocks:
            errors.append(f":::{node_ref} cannot be used - node '{node_ref}' has no blocks yet")

    return errors
