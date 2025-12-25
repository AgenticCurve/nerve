"""Fluent builder classes for graph construction.

GraphStep and GraphStepList enable intuitive graph building with the >> operator:

    A = graph.step("A", node, input="First")
    B = graph.step("B", node)
    C = graph.step("C", node)
    A >> B >> C  # B depends on A, C depends on B

    A >> [B, C]  # Both B and C depend on A
    [A, B] >> C  # C depends on both A and B
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from nerve.core.nodes.base import Node
    from nerve.core.nodes.graph.graph import Graph
    from nerve.core.nodes.policies import ErrorPolicy
    from nerve.core.types import ParserType


class GraphStep:
    """Wrapper for fluent graph building with >> operator.

    Example:
        >>> A = graph.step("A", node, input="First")
        >>> B = graph.step("B", node, input="Second")
        >>> C = graph.step("C", node, input="Third")
        >>> A >> B >> C  # B depends on A, C depends on B
    """

    def __init__(
        self,
        graph: Graph,
        step_id: str,
        node: Node | None = None,
        node_ref: str | None = None,
        input: Any = None,
        input_fn: Callable[[dict[str, Any]], Any] | None = None,
        depends_on: list[str] | None = None,
        error_policy: ErrorPolicy | None = None,
        parser: ParserType | None = None,
    ):
        self.graph = graph
        self.step_id = step_id
        self.node = node
        self.node_ref = node_ref
        self.input = input
        self.input_fn = input_fn
        self.error_policy = error_policy
        self.parser = parser
        self.depends_on: list[str] = depends_on or []
        self._registered = False

    def _ensure_registered(self) -> None:
        """Add this step to the graph if not already registered."""
        if not self._registered:
            if self.node:
                self.graph.add_step(
                    self.node,
                    self.step_id,
                    input=self.input,
                    input_fn=self.input_fn,
                    depends_on=self.depends_on,
                    error_policy=self.error_policy,
                    parser=self.parser,
                )
            elif self.node_ref:
                self.graph.add_step_ref(
                    self.node_ref,
                    self.step_id,
                    input=self.input,
                    input_fn=self.input_fn,
                    depends_on=self.depends_on,
                    error_policy=self.error_policy,
                    parser=self.parser,
                )
            else:
                raise ValueError(f"Step {self.step_id} has neither node nor node_ref")
            self._registered = True

    def __rshift__(
        self, other: GraphStep | list[GraphStep] | GraphStepList
    ) -> GraphStep | GraphStepList:
        """A >> B makes B depend on A.

        Supports:
            A >> B           # B depends on A
            A >> [B, C]      # Both B and C depend on A
        """
        if isinstance(other, (list, GraphStepList)):
            # A >> [B, C]
            for step in other:
                if isinstance(step, GraphStep):
                    step.depends_on.append(self.step_id)
                    self._ensure_registered()
                    step._ensure_registered()
            return GraphStepList(other)
        elif isinstance(other, GraphStep):
            # A >> B
            other.depends_on.append(self.step_id)
            self._ensure_registered()
            other._ensure_registered()
            return other
        else:
            raise TypeError(f"Cannot use >> with {type(other)}")

    def __repr__(self) -> str:
        return f"GraphStep(id={self.step_id!r}, depends_on={self.depends_on})"


class GraphStepList(list[GraphStep]):
    """List wrapper that supports >> operator for parallel dependencies.

    Example:
        >>> [A, B] >> C  # C depends on both A and B
    """

    def __rshift__(
        self, other: GraphStep | list[GraphStep] | GraphStepList
    ) -> GraphStep | GraphStepList:
        """[A, B] >> C makes C depend on all items in the list.

        Supports:
            [A, B] >> C        # C depends on both A and B
            [A, B] >> [C, D]   # C and D depend on both A and B
        """
        if isinstance(other, (list, GraphStepList)):
            # [A, B] >> [C, D]
            for downstream in other:
                if isinstance(downstream, GraphStep):
                    for upstream in self:
                        if isinstance(upstream, GraphStep):
                            downstream.depends_on.append(upstream.step_id)
                            upstream._ensure_registered()
                    downstream._ensure_registered()
            return GraphStepList(other)
        elif isinstance(other, GraphStep):
            # [A, B] >> C
            for upstream in self:
                if isinstance(upstream, GraphStep):
                    other.depends_on.append(upstream.step_id)
                    upstream._ensure_registered()
            other._ensure_registered()
            return other
        else:
            raise TypeError(f"Cannot use >> with {type(other)}")
