"""Step - configuration for a single step in a graph.

A step combines a node reference with execution configuration,
including input, dependencies, and error handling.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nerve.core.nodes.base import Node
    from nerve.core.nodes.policies import ErrorPolicy
    from nerve.core.types import ParserType


@dataclass
class Step:
    """A step in a graph execution.

    Steps combine a node with execution configuration.
    Dependencies are on the step, not the node, allowing
    the same node to appear in multiple steps.

    Attributes:
        node: Direct reference to the node to execute.
        node_ref: ID-based reference (resolved from session at execution).
        input: Static input value for the step.
        input_fn: Dynamic input function that receives upstream results.
        depends_on: List of step IDs this step depends on.
        error_policy: How to handle errors in this step.
        parser: Parser to use for terminal nodes (overrides node default).

    Note:
        Either node or node_ref must be provided, not both.
        Either input or input_fn can be provided, not both.
    """

    node: Node | None = None
    node_ref: str | None = None
    input: Any = None
    input_fn: Callable[[dict[str, Any]], Any] | None = None
    depends_on: list[str] = field(default_factory=list)
    error_policy: ErrorPolicy | None = None
    parser: ParserType | None = None

    def __post_init__(self) -> None:
        """Validate step configuration."""
        # Validate node vs node_ref: exactly one must be provided
        if self.node is not None and self.node_ref is not None:
            raise ValueError("Step cannot have both 'node' and 'node_ref'; provide only one")
        if self.node is None and self.node_ref is None:
            raise ValueError("Step must have either 'node' or 'node_ref'; neither was provided")

        # Validate input vs input_fn: at most one can be provided
        if self.input is not None and self.input_fn is not None:
            raise ValueError("Step cannot have both 'input' and 'input_fn'; provide only one")
