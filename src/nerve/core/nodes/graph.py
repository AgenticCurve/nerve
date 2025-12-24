"""Graph - orchestrator of nodes, implements Node protocol.

Graph is a composable workflow that:
- Contains steps (node + input + dependencies)
- Executes in topological order
- Supports nested graphs (Graph implements Node)
- Integrates error policies, budgets, cancellation, and tracing
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from graphlib import TopologicalSorter
from typing import TYPE_CHECKING, Any, Literal

from nerve.core.nodes.base import FunctionNode, Node, NodeInfo, NodeState
from nerve.core.nodes.policies import ErrorPolicy
from nerve.core.nodes.trace import ExecutionTrace, StepTrace

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session
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


@dataclass
class StepEvent:
    """Event emitted during streaming graph execution.

    Used by Graph.execute_stream() to provide real-time
    feedback on execution progress.

    Attributes:
        event_type: Type of event.
        step_id: The step this event relates to.
        node_id: The node being executed.
        data: Event-specific data (chunk content, result, or error).
        timestamp: When the event occurred.
    """

    event_type: Literal["step_start", "step_chunk", "step_complete", "step_error"]
    step_id: str
    node_id: str
    data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)


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
        graph: "Graph",
        step_id: str,
        node: Node | None = None,
        node_ref: str | None = None,
        input: Any = None,
        input_fn: Callable[[dict[str, Any]], Any] | None = None,
        depends_on: list[str] | None = None,
        error_policy: ErrorPolicy | None = None,
        parser: "ParserType | None" = None,
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

    def _ensure_registered(self):
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

    def __rshift__(self, other):
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

    def __repr__(self):
        return f"GraphStep(id={self.step_id!r}, depends_on={self.depends_on})"


class GraphStepList(list):
    """List wrapper that supports >> operator for parallel dependencies.

    Example:
        >>> [A, B] >> C  # C depends on both A and B
    """

    def __rshift__(self, other):
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


class Graph:
    """Directed graph of steps that implements Node protocol.

    Graph orchestrates node execution with dependencies, enabling:
    - Composable workflows (graphs containing graphs)
    - Error handling policies per step
    - Budget enforcement across all steps
    - Cooperative cancellation
    - Execution tracing

    Example:
        >>> graph = Graph(id="pipeline")
        >>>
        >>> # Add steps with nodes
        >>> graph.add_step(fetch_node, step_id="fetch", input="http://api")
        >>> graph.add_step(process_node, step_id="process", depends_on=["fetch"])
        >>>
        >>> # Execute
        >>> context = ExecutionContext(session=session, input=None)
        >>> results = await graph.execute(context)
        >>> print(results["process"])
    """

    def __init__(self, id: str, max_parallel: int = 1) -> None:
        """Initialize a graph.

        Args:
            id: Unique identifier for this graph.
            max_parallel: Maximum concurrent step executions (default 1 = sequential).
        """
        self._id = id
        self._steps: dict[str, Step] = {}
        self._max_parallel = max_parallel

    @property
    def id(self) -> str:
        """Unique identifier for this graph."""
        return self._id

    @property
    def persistent(self) -> bool:
        """Graphs are ephemeral (stateless between executions)."""
        return False

    def add_step(
        self,
        node: Node,
        step_id: str,
        input: Any = None,
        input_fn: Callable[[dict[str, Any]], Any] | None = None,
        depends_on: list[str] | None = None,
        error_policy: ErrorPolicy | None = None,
        parser: ParserType | None = None,
    ) -> Graph:
        """Add step with direct node reference.

        Args:
            node: The node to execute.
            step_id: Unique identifier for this step.
            input: Static input value (mutually exclusive with input_fn).
            input_fn: Dynamic input function that receives upstream results.
            depends_on: List of step IDs this step depends on.
            error_policy: How to handle errors in this step.
            parser: Parser to use for terminal nodes (overrides node default).

        Returns:
            Self for chaining.

        Raises:
            ValueError: If step_id already exists or is empty.
        """
        if not step_id or not step_id.strip():
            raise ValueError("step_id cannot be empty")

        if step_id in self._steps:
            raise ValueError(f"Step '{step_id}' already exists")

        self._steps[step_id] = Step(
            node=node,
            input=input,
            input_fn=input_fn,
            depends_on=depends_on or [],
            error_policy=error_policy,
            parser=parser,
        )
        return self

    def add_step_ref(
        self,
        node_id: str,
        step_id: str,
        input: Any = None,
        input_fn: Callable[[dict[str, Any]], Any] | None = None,
        depends_on: list[str] | None = None,
        error_policy: ErrorPolicy | None = None,
        parser: ParserType | None = None,
    ) -> Graph:
        """Add step with node ID (resolved from session at execution).

        Args:
            node_id: ID of node to resolve from session.
            step_id: Unique identifier for this step.
            input: Static input value (mutually exclusive with input_fn).
            input_fn: Dynamic input function that receives upstream results.
            depends_on: List of step IDs this step depends on.
            error_policy: How to handle errors in this step.
            parser: Parser to use for terminal nodes (overrides node default).

        Returns:
            Self for chaining.

        Raises:
            ValueError: If step_id already exists or is empty.
        """
        if not step_id or not step_id.strip():
            raise ValueError("step_id cannot be empty")

        if step_id in self._steps:
            raise ValueError(f"Step '{step_id}' already exists")

        self._steps[step_id] = Step(
            node_ref=node_id,
            input=input,
            input_fn=input_fn,
            depends_on=depends_on or [],
            error_policy=error_policy,
            parser=parser,
        )
        return self

    def step(
        self,
        step_id: str,
        node: Node | None = None,
        node_ref: str | None = None,
        input: Any = None,
        input_fn: Callable[[dict[str, Any]], Any] | None = None,
        depends_on: list[str] | None = None,
        error_policy: ErrorPolicy | None = None,
        parser: ParserType | None = None,
    ) -> GraphStep:
        """Create a step for fluent graph building with >> operator.

        This method returns a GraphStep that can be chained with >> operators
        to build dependencies. Steps are automatically registered when dependencies
        are set (either via >> operator or explicit depends_on parameter).

        Args:
            step_id: Unique identifier for this step.
            node: Direct reference to node to execute (mutually exclusive with node_ref).
            node_ref: ID of node to resolve from session (mutually exclusive with node).
            input: Static input value (mutually exclusive with input_fn).
            input_fn: Dynamic input function that receives upstream results.
            depends_on: List of step IDs this step depends on (optional, can use >> instead).
            error_policy: How to handle errors in this step.
            parser: Parser to use for terminal nodes (overrides node default).

        Returns:
            GraphStep that supports >> operator for dependency chaining.

        Example:
            >>> # Using >> operator
            >>> A = graph.step("fetch", node, input="http://api")
            >>> B = graph.step("process", node)
            >>> C = graph.step("output", node)
            >>> A >> B >> C  # B depends on A, C depends on B
            >>>
            >>> # Using explicit depends_on
            >>> A = graph.step("fetch", node, input="http://api")
            >>> B = graph.step("process", node, depends_on=["fetch"])
            >>>
            >>> # Parallel branches with >>
            >>> D = graph.step("branch1", node)
            >>> E = graph.step("branch2", node)
            >>> F = graph.step("merge", node)
            >>> C >> [D, E] >> F  # D and E depend on C, F depends on both
        """
        step = GraphStep(
            self,
            step_id,
            node=node,
            node_ref=node_ref,
            input=input,
            input_fn=input_fn,
            depends_on=depends_on,
            error_policy=error_policy,
            parser=parser,
        )
        # If depends_on was provided, register the step immediately
        if depends_on:
            step._ensure_registered()
        return step

    def chain(self, *step_ids: str) -> Graph:
        """Set linear dependencies between steps.

        Args:
            step_ids: Step IDs in execution order.

        Returns:
            Self for chaining.

        Example:
            >>> graph.chain("fetch", "process", "output")
            # process depends on fetch, output depends on process
        """
        for i in range(1, len(step_ids)):
            current_id = step_ids[i]
            previous_id = step_ids[i - 1]

            if current_id in self._steps:
                step = self._steps[current_id]
                if previous_id not in step.depends_on:
                    step.depends_on.append(previous_id)

        return self

    def validate(self) -> list[str]:
        """Validate graph structure and configuration.

        Checks for:
        - Empty or whitespace-only step IDs
        - Self-dependencies
        - Mutually exclusive input/input_fn
        - Missing dependencies
        - Cycles

        Returns:
            List of error messages (empty if valid).
        """
        errors: list[str] = []

        for step_id, step in self._steps.items():
            # Check for empty step IDs
            if not step_id or not step_id.strip():
                errors.append("Empty step_id not allowed")

            # Check for self-dependencies
            if step_id in step.depends_on:
                errors.append(f"Step '{step_id}' depends on itself")

            # Check for mutually exclusive input/input_fn
            if step.input is not None and step.input_fn is not None:
                errors.append(
                    f"Step '{step_id}': input and input_fn are mutually exclusive"
                )

            # Check for missing node reference
            if step.node is None and step.node_ref is None:
                errors.append(
                    f"Step '{step_id}': either node or node_ref must be provided"
                )

            # Check for missing dependencies
            for dep_id in step.depends_on:
                if dep_id not in self._steps:
                    errors.append(
                        f"Step '{step_id}' depends on unknown step '{dep_id}'"
                    )

        # Check for cycles (only if no other errors)
        if not errors:
            try:
                graph = {sid: set(s.depends_on) for sid, s in self._steps.items()}
                list(TopologicalSorter(graph).static_order())
            except Exception as e:
                errors.append(f"Cycle detected: {e}")

        return errors

    def execution_order(self) -> list[str]:
        """Get topological execution order.

        Returns:
            List of step IDs in execution order.

        Raises:
            ValueError: If graph is invalid.
        """
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid graph: {errors}")

        graph = {sid: set(s.depends_on) for sid, s in self._steps.items()}
        return list(TopologicalSorter(graph).static_order())

    def get_step(self, step_id: str) -> Step | None:
        """Get a step by ID.

        Args:
            step_id: The step ID.

        Returns:
            The step, or None if not found.
        """
        return self._steps.get(step_id)

    def list_steps(self) -> list[str]:
        """List all step IDs.

        Returns:
            List of step IDs.
        """
        return list(self._steps.keys())

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Execute graph steps in topological order.

        Args:
            context: Execution context with session, input, and agent capabilities.

        Returns:
            Dict mapping step_id to step result.

        Raises:
            ValueError: If graph is invalid.
            BudgetExceededError: If budget limits are exceeded.
            CancelledException: If execution is cancelled.
        """
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid graph: {errors}")

        results: dict[str, Any] = {}
        trace = context.trace

        if trace:
            trace.status = "running"

        try:
            for step_id in self.execution_order():
                # Check cancellation and budget before each step
                context.check_cancelled()
                context.check_budget()

                step = self._steps[step_id]
                node = self._resolve_node(step, context.session)

                # Resolve input
                step_input = self._resolve_input(step, results)

                # Create step context
                step_context = context.with_input(step_input).with_upstream(results)
                if step.parser:
                    step_context = step_context.with_parser(step.parser)

                # Execute with policy
                start_time = datetime.now()
                start_mono = time.monotonic()

                try:
                    result = await self._execute_with_policy(step, node, step_context)
                    error = None
                except Exception as e:
                    result = None
                    error = str(e)
                    raise

                finally:
                    end_time = datetime.now()
                    duration_ms = (time.monotonic() - start_mono) * 1000

                    # Record trace
                    if trace:
                        step_trace = StepTrace(
                            step_id=step_id,
                            node_id=node.id,
                            node_type=self._get_node_type(node),
                            input=step_input,
                            output=result,
                            error=error,
                            start_time=start_time,
                            end_time=end_time,
                            duration_ms=duration_ms,
                        )
                        trace.add_step(step_trace)

                    # Update resource usage
                    if context.usage:
                        context.usage.add_step()

                results[step_id] = result

            if trace:
                trace.complete()

        except Exception as e:
            if trace:
                trace.complete(error=str(e))
            raise

        return results

    async def execute_stream(
        self, context: ExecutionContext
    ) -> AsyncIterator[StepEvent]:
        """Execute graph steps and stream events as they occur.

        Yields:
            StepEvent for each step lifecycle event.

        Note:
            This method does NOT return final results. Callers should collect
            results from step_complete events if needed.

        Example:
            >>> results = {}
            >>> async for event in graph.execute_stream(context):
            ...     if event.event_type == "step_chunk":
            ...         print(event.data, end="", flush=True)
            ...     elif event.event_type == "step_complete":
            ...         results[event.step_id] = event.data
        """
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid graph: {errors}")

        results: dict[str, Any] = {}

        for step_id in self.execution_order():
            context.check_cancelled()
            context.check_budget()

            step = self._steps[step_id]
            node = self._resolve_node(step, context.session)

            step_input = self._resolve_input(step, results)
            step_context = context.with_input(step_input).with_upstream(results)
            if step.parser:
                step_context = step_context.with_parser(step.parser)

            yield StepEvent("step_start", step_id, node.id)

            try:
                # If terminal node with streaming support, stream chunks
                if hasattr(node, "execute_stream") and callable(
                    getattr(node, "execute_stream")
                ):
                    chunks = []
                    async for chunk in node.execute_stream(step_context):
                        chunks.append(chunk)
                        yield StepEvent("step_chunk", step_id, node.id, chunk)
                    result = "".join(chunks) if chunks else None
                else:
                    result = await self._execute_with_policy(step, node, step_context)

                results[step_id] = result
                yield StepEvent("step_complete", step_id, node.id, result)

            except Exception as e:
                yield StepEvent("step_error", step_id, node.id, str(e))
                raise

    def collect_persistent_nodes(self) -> list[Node]:
        """Recursively find all persistent nodes in this graph.

        Returns:
            List of persistent nodes.
        """
        persistent: list[Node] = []
        for step in self._steps.values():
            if step.node and step.node.persistent:
                persistent.append(step.node)
            # Recurse into nested graphs
            if step.node and isinstance(step.node, Graph):
                persistent.extend(step.node.collect_persistent_nodes())
        return persistent

    def to_info(self) -> NodeInfo:
        """Get node information.

        Returns:
            NodeInfo for this graph.
        """
        return NodeInfo(
            id=self.id,
            node_type="graph",
            state=NodeState.READY,
            persistent=self.persistent,
            metadata={"steps": len(self._steps)},
        )

    def _resolve_node(self, step: Step, session: Session) -> Node:
        """Resolve node from step configuration.

        Args:
            step: The step containing node or node_ref.
            session: Session for node lookup.

        Returns:
            The resolved node.

        Raises:
            ValueError: If node cannot be resolved.
        """
        if step.node is not None:
            return step.node

        if step.node_ref is not None:
            node = session.get_node(step.node_ref)
            if node is None:
                raise ValueError(f"Node '{step.node_ref}' not found in session")
            return node

        raise ValueError("Step has neither node nor node_ref")

    def _resolve_input(self, step: Step, upstream: dict[str, Any]) -> Any:
        """Resolve step input from static value or dynamic function.

        Args:
            step: The step with input configuration.
            upstream: Results from upstream steps.

        Returns:
            Resolved input value.
        """
        if step.input_fn is not None:
            return step.input_fn(upstream)
        return step.input

    async def _execute_with_policy(
        self,
        step: Step,
        node: Node,
        context: ExecutionContext,
    ) -> Any:
        """Execute node with error policy handling.

        Args:
            step: The step being executed.
            node: The node to execute.
            context: Execution context.

        Returns:
            Execution result.

        Raises:
            Exception: If policy is "fail" and execution fails.
        """
        policy = step.error_policy or ErrorPolicy()

        for attempt in range(policy.retry_count + 1):
            try:
                if policy.timeout_ms:
                    return await asyncio.wait_for(
                        node.execute(context),
                        timeout=policy.timeout_ms / 1000,
                    )
                else:
                    return await node.execute(context)

            except asyncio.TimeoutError as e:
                if policy.should_retry(attempt):
                    delay = policy.get_delay_for_attempt(attempt)
                    await asyncio.sleep(delay)
                    continue

                # Handle timeout based on policy
                return await self._handle_error(policy, context, e)

            except Exception as e:
                if policy.should_retry(attempt):
                    delay = policy.get_delay_for_attempt(attempt)
                    await asyncio.sleep(delay)
                    continue

                return await self._handle_error(policy, context, e)

        # Should never reach here, but handle it with a generic error
        return await self._handle_error(
            policy, context, RuntimeError("Execution failed after all retries")
        )

    async def _handle_error(
        self, policy: ErrorPolicy, context: ExecutionContext, error: BaseException
    ) -> Any:
        """Handle error according to policy after retries exhausted.

        Args:
            policy: The error policy.
            context: Execution context.
            error: The exception that occurred.

        Returns:
            Fallback value or raises exception.
        """
        if policy.on_error == "fail":
            raise error

        if policy.on_error == "skip":
            return policy.fallback_value

        if policy.on_error == "fallback" and policy.fallback_node:
            # Execute fallback node asynchronously
            return await policy.fallback_node.execute(context)

        raise error

    def _get_node_type(self, node: Node) -> str:
        """Get type name for a node.

        Args:
            node: The node.

        Returns:
            Type string for tracing.
        """
        if isinstance(node, FunctionNode):
            return "function"
        if isinstance(node, Graph):
            return "graph"
        # For terminal nodes, we'll use class name
        return type(node).__name__.lower().replace("node", "")

    def __repr__(self) -> str:
        step_ids = list(self._steps.keys())
        return f"Graph(id={self.id!r}, steps={step_ids})"

    def __len__(self) -> int:
        return len(self._steps)
