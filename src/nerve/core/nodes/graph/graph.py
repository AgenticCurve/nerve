"""Graph - orchestrator of nodes, implements Node protocol."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import datetime
from graphlib import TopologicalSorter
from typing import TYPE_CHECKING, Any

from nerve.core.nodes.base import FunctionNode, Node, NodeInfo, NodeState
from nerve.core.nodes.graph.builder import GraphStep
from nerve.core.nodes.graph.events import StepEvent
from nerve.core.nodes.graph.step import Step
from nerve.core.nodes.policies import ErrorPolicy
from nerve.core.nodes.run_logging import (
    log_complete,
    log_error,
    log_start,
    log_warning,
    warn_no_run_logger,
)
from nerve.core.nodes.trace import StepTrace

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session
    from nerve.core.types import ParserType


class Graph:
    """Directed graph of steps that implements Node protocol.

    Graph orchestrates node execution with dependencies, enabling:
    - Composable workflows (graphs containing graphs)
    - Error handling policies per step
    - Budget enforcement across all steps
    - Cooperative cancellation
    - Execution tracing
    - Auto-registers with session on creation

    Args:
        id: Unique identifier for this graph.
        session: Session to register this graph with.
        max_parallel: Maximum concurrent step executions (default 1 = sequential).

    Example:
        >>> session = Session(name="my-session")
        >>> graph = Graph(id="pipeline", session=session)
        >>>
        >>> # Add steps with nodes
        >>> graph.add_step(fetch_node, step_id="fetch", input="http://api")
        >>> graph.add_step(process_node, step_id="process", depends_on=["fetch"])
        >>>
        >>> # Execute
        >>> context = ExecutionContext(session=session, input=None)
        >>> result = await graph.execute(context)
        >>> print(result["output"])  # Output of final step
        >>> print(result["attributes"]["steps"]["process"]["output"])  # Specific step output
        >>> print(result["success"])  # Overall graph success
    """

    def __init__(self, id: str, session: Session, max_parallel: int = 1) -> None:
        """Initialize a graph and register it with the session.

        Args:
            id: Unique identifier for this graph.
            session: Session to register this graph with.
            max_parallel: Maximum concurrent step executions (default 1 = sequential).

        Raises:
            ValueError: If graph_id is empty or conflicts with existing node/graph.
        """
        if not id or not id.strip():
            raise ValueError("graph_id cannot be empty")
        # Validate uniqueness across both nodes and graphs
        session.validate_unique_id(id, "graph")

        self._id = id
        self._session = session
        self._steps: dict[str, Step] = {}
        self._max_parallel = max_parallel

        # Interrupt support
        self._current_context: ExecutionContext | None = None
        self._current_node: Node | None = None
        self._interrupt_lock: asyncio.Lock = asyncio.Lock()

        # Auto-register with session
        session.graphs[id] = self

        # Log graph registration
        if session.session_logger:
            session.session_logger.log_graph_registered(id, steps=0)

    @property
    def id(self) -> str:
        """Unique identifier for this graph."""
        return self._id

    @property
    def session(self) -> Session:
        """Session this graph is registered with."""
        return self._session

    @property
    def persistent(self) -> bool:
        """Graphs are stateless (no state between executions)."""
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
        graph_step = GraphStep(
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
            graph_step._ensure_registered()
        return graph_step

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
                errors.append(f"Step '{step_id}': input and input_fn are mutually exclusive")

            # Check for missing node reference
            if step.node is None and step.node_ref is None:
                errors.append(f"Step '{step_id}': either node or node_ref must be provided")

            # Check for missing dependencies
            for dep_id in step.depends_on:
                if dep_id not in self._steps:
                    errors.append(f"Step '{step_id}' depends on unknown step '{dep_id}'")

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
            Dict with standardized fields:
            - success: bool - True if ALL steps succeeded
            - error: str | None - First error encountered, None if all succeeded
            - error_type: str | None - Error type of first error
            - node_type: str - "graph"
            - node_id: str - ID of this graph
            - input: Any - Input provided to the graph
            - output: Any - Output of the final step in execution order
            - attributes: dict - Contains:
                - steps: dict[str, Any] - All step results (maps step_id -> result)
                - execution_order: list[str] - Step IDs in execution order
                - final_step_id: str - Which step's output is in top-level "output"

        Raises:
            ValueError: If graph is invalid.
            BudgetExceededError: If budget limits are exceeded.
            CancelledError: If execution is cancelled.
        """
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid graph: {errors}")

        results: dict[str, Any] = {}
        trace = context.trace

        # Setup run logging if not already configured
        run_logger = context.run_logger
        owns_run_logger = False
        if run_logger is None and context.session is not None:
            session_logger = context.session.session_logger
            if session_logger is not None:
                run_logger = session_logger.create_graph_run_logger()
                owns_run_logger = True
                context = replace(context, run_logger=run_logger, run_id=run_logger.run_id)
            else:
                warn_no_run_logger(f"graph:{self._id}", "no session_logger on session")
        elif run_logger is None:
            warn_no_run_logger(f"graph:{self._id}", "no session in context")

        # Get graph-specific logger
        graph_logger = run_logger.get_logger("graph") if run_logger else None

        if trace:
            trace.status = "running"

        self._current_context = context

        # Log graph start
        execution_order = self.execution_order()
        graph_start_mono = time.monotonic()
        if graph_logger:
            log_start(
                graph_logger,
                self._id,
                "graph_start",
                steps=len(execution_order),
                run_id=run_logger.run_id if run_logger else None,
            )

        try:
            for step_id in execution_order:
                # Check cancellation and budget before each step
                context.check_cancelled()
                context.check_budget()

                step = self._steps[step_id]
                node = self._resolve_node(step, context.session)

                # Resolve input (pass graph input for {input} template expansion)
                step_input = self._resolve_input(step, results, context.input)

                # Create step context
                step_context = context.with_input(step_input).with_upstream(results)
                if step.parser:
                    step_context = step_context.with_parser(step.parser)

                # Log step start
                if graph_logger:
                    log_start(
                        graph_logger,
                        self._id,
                        "step_start",
                        step=step_id,
                        node=node.id,
                        node_type=self._get_node_type(node),
                        depends_on=step.depends_on,
                    )

                # Execute with policy
                start_time = datetime.now()
                start_mono = time.monotonic()

                # Track current node for interrupt()
                async with self._interrupt_lock:
                    self._current_node = node

                try:
                    result = await self._execute_with_policy(step, node, step_context, step_id)
                    error = None
                except Exception as e:
                    result = None
                    error = str(e)
                    # Log step failure
                    if graph_logger:
                        step_duration = time.monotonic() - start_mono
                        log_error(
                            graph_logger,
                            self._id,
                            "step_failed",
                            e,
                            step=step_id,
                            node=node.id,
                            duration_s=f"{step_duration:.1f}",
                        )
                    raise

                finally:
                    async with self._interrupt_lock:
                        self._current_node = None
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

                # Log step complete (only if no error)
                if graph_logger and error is None:
                    step_duration = time.monotonic() - start_mono
                    log_complete(
                        graph_logger,
                        self._id,
                        "step_complete",
                        step_duration,
                        step=step_id,
                        node=node.id,
                    )

                results[step_id] = result

            # Log graph complete
            graph_duration = time.monotonic() - graph_start_mono
            if graph_logger:
                log_complete(
                    graph_logger,
                    self._id,
                    "graph_complete",
                    graph_duration,
                    steps=len(execution_order),
                )

            if trace:
                trace.complete()

            # Calculate overall success and collect first error
            overall_success = all(
                step_result.get("success", False) for step_result in results.values()
            )
            first_error = None
            first_error_type = None
            for step_id in execution_order:
                if not results[step_id].get("success", False):
                    first_error = results[step_id].get("error")
                    first_error_type = results[step_id].get("error_type")
                    break

            # Get final step's output
            final_step_id = execution_order[-1] if execution_order else None
            final_output = results[final_step_id].get("output") if final_step_id else None

            # Return standardized format
            return {
                "success": overall_success,
                "error": first_error,
                "error_type": first_error_type,
                "node_type": "graph",
                "node_id": self._id,
                "input": context.input,
                "output": final_output,
                "attributes": {
                    "steps": results,
                    "execution_order": execution_order,
                    "final_step_id": final_step_id,
                },
            }

        except Exception as e:
            # Log graph failure
            graph_duration = time.monotonic() - graph_start_mono
            if graph_logger:
                log_error(
                    graph_logger,
                    self._id,
                    "graph_failed",
                    e,
                    duration_s=f"{graph_duration:.1f}",
                )
            if trace:
                trace.complete(error=str(e))
            raise

        finally:
            self._current_context = None
            async with self._interrupt_lock:
                self._current_node = None
            # Cleanup run logger if we created it
            if owns_run_logger and run_logger:
                run_logger.close()

    async def interrupt(self) -> None:
        """Request interruption of graph execution.

        Sets the cancellation token (if present) AND interrupts the
        currently executing node. This provides both:
        - Immediate interruption of the current node
        - Prevention of subsequent steps from starting
        """
        # Set cancellation token to prevent next steps
        if self._current_context and self._current_context.cancellation:
            self._current_context.cancellation.cancel()

        # Interrupt the currently executing node
        async with self._interrupt_lock:
            node = self._current_node
        if node is not None:
            await node.interrupt()

    async def execute_stream(self, context: ExecutionContext) -> AsyncIterator[StepEvent]:
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

        # Setup run logging if not already configured
        run_logger = context.run_logger
        owns_run_logger = False
        if run_logger is None and context.session is not None:
            session_logger = context.session.session_logger
            if session_logger is not None:
                run_logger = session_logger.create_graph_run_logger()
                owns_run_logger = True
                context = replace(context, run_logger=run_logger, run_id=run_logger.run_id)
            else:
                warn_no_run_logger(f"graph:{self._id}:stream", "no session_logger on session")
        elif run_logger is None:
            warn_no_run_logger(f"graph:{self._id}:stream", "no session in context")

        # Get graph-specific logger
        graph_logger = run_logger.get_logger("graph") if run_logger else None

        self._current_context = context

        # Log graph start
        execution_order = self.execution_order()
        graph_start_mono = time.monotonic()
        if graph_logger:
            log_start(
                graph_logger,
                self._id,
                "graph_stream_start",
                steps=len(execution_order),
                run_id=run_logger.run_id if run_logger else None,
            )

        try:
            for step_id in execution_order:
                context.check_cancelled()
                context.check_budget()

                step = self._steps[step_id]
                node = self._resolve_node(step, context.session)

                # Resolve input (pass graph input for {input} template expansion)
                step_input = self._resolve_input(step, results, context.input)
                step_context = context.with_input(step_input).with_upstream(results)
                if step.parser:
                    step_context = step_context.with_parser(step.parser)

                # Log step start
                step_start_mono = time.monotonic()
                if graph_logger:
                    log_start(
                        graph_logger,
                        self._id,
                        "step_start",
                        step=step_id,
                        node=node.id,
                        node_type=self._get_node_type(node),
                        depends_on=step.depends_on,
                    )

                yield StepEvent("step_start", step_id, node.id)

                # Track current node for interrupt()
                async with self._interrupt_lock:
                    self._current_node = node

                try:
                    # If terminal node with streaming support, stream chunks
                    if hasattr(node, "execute_stream") and callable(node.execute_stream):
                        chunks = []
                        async for chunk in node.execute_stream(step_context):
                            chunks.append(chunk)
                            yield StepEvent("step_chunk", step_id, node.id, chunk)
                        result = "".join(chunks) if chunks else None
                    else:
                        result = await self._execute_with_policy(step, node, step_context, step_id)

                    results[step_id] = result

                    # Log step complete
                    if graph_logger:
                        step_duration = time.monotonic() - step_start_mono
                        log_complete(
                            graph_logger,
                            self._id,
                            "step_complete",
                            step_duration,
                            step=step_id,
                            node=node.id,
                        )

                    yield StepEvent("step_complete", step_id, node.id, result)

                except Exception as e:
                    # Log step failure
                    if graph_logger:
                        step_duration = time.monotonic() - step_start_mono
                        log_error(
                            graph_logger,
                            self._id,
                            "step_failed",
                            e,
                            step=step_id,
                            node=node.id,
                            duration_s=f"{step_duration:.1f}",
                        )
                    yield StepEvent("step_error", step_id, node.id, str(e))
                    raise

                finally:
                    async with self._interrupt_lock:
                        self._current_node = None

            # Log graph complete
            graph_duration = time.monotonic() - graph_start_mono
            if graph_logger:
                log_complete(
                    graph_logger,
                    self._id,
                    "graph_stream_complete",
                    graph_duration,
                    steps=len(execution_order),
                )

        except Exception as e:
            # Log graph failure
            graph_duration = time.monotonic() - graph_start_mono
            if graph_logger:
                log_error(
                    graph_logger,
                    self._id,
                    "graph_stream_failed",
                    e,
                    duration_s=f"{graph_duration:.1f}",
                )
            raise

        finally:
            self._current_context = None
            async with self._interrupt_lock:
                self._current_node = None
            # Cleanup run logger if we created it
            if owns_run_logger and run_logger:
                run_logger.close()

    def collect_persistent_nodes(self) -> list[Node]:
        """Recursively find all stateful nodes in this graph.

        Returns:
            List of stateful nodes.
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

    def _resolve_node(self, step: Step, session: Session | None) -> Node:
        """Resolve node from step configuration.

        Args:
            step: The step containing node or node_ref.
            session: Session for node lookup (required if step uses node_ref).

        Returns:
            The resolved node.

        Raises:
            ValueError: If node cannot be resolved.
        """
        if step.node is not None:
            return step.node

        if step.node_ref is not None:
            if session is None:
                raise ValueError(f"Session required to resolve node_ref '{step.node_ref}'")
            node = session.get_node(step.node_ref)
            if node is None:
                raise ValueError(f"Node '{step.node_ref}' not found in session")
            return node

        raise ValueError("Step has neither node nor node_ref")

    def _resolve_input(self, step: Step, upstream: dict[str, Any], graph_input: Any = None) -> Any:
        """Resolve step input from static value or dynamic function.

        Args:
            step: The step with input configuration.
            upstream: Results from upstream steps.
            graph_input: The original input passed to the graph (for {input} templates).

        Returns:
            Resolved input value.
        """
        if step.input_fn is not None:
            # Include graph input under "input" key for template expansion
            data = {**upstream, "input": graph_input}
            return step.input_fn(data)
        return step.input

    async def _execute_with_policy(
        self,
        step: Step,
        node: Node,
        context: ExecutionContext,
        step_id: str | None = None,
    ) -> Any:
        """Execute node with error policy handling.

        Args:
            step: The step being executed.
            node: The node to execute.
            context: Execution context.
            step_id: Step identifier for logging.

        Returns:
            Execution result.

        Raises:
            Exception: If policy is "fail" and execution fails.
        """
        policy = step.error_policy or ErrorPolicy()

        # Get logger for retry logging
        run_logger = context.run_logger
        graph_logger = run_logger.get_logger("graph") if run_logger else None

        for attempt in range(policy.retry_count + 1):
            try:
                if policy.timeout_ms:
                    return await asyncio.wait_for(
                        node.execute(context),
                        timeout=policy.timeout_ms / 1000,
                    )
                else:
                    return await node.execute(context)

            except TimeoutError as e:
                if policy.should_retry(attempt):
                    delay = policy.get_delay_for_attempt(attempt)
                    # Log retry attempt
                    if graph_logger:
                        log_warning(
                            graph_logger,
                            self._id,
                            "step_retry",
                            step=step_id,
                            node=node.id,
                            attempt=attempt + 1,
                            max_attempts=policy.retry_count + 1,
                            delay_ms=int(delay * 1000),
                            error_type="timeout",
                            error=str(e),
                        )
                    await asyncio.sleep(delay)
                    continue

                # Handle timeout based on policy
                return await self._handle_error(policy, context, e, graph_logger, step_id, node.id)

            except Exception as e:
                if policy.should_retry(attempt):
                    delay = policy.get_delay_for_attempt(attempt)
                    # Log retry attempt
                    if graph_logger:
                        log_warning(
                            graph_logger,
                            self._id,
                            "step_retry",
                            step=step_id,
                            node=node.id,
                            attempt=attempt + 1,
                            max_attempts=policy.retry_count + 1,
                            delay_ms=int(delay * 1000),
                            error_type=type(e).__name__,
                            error=str(e),
                        )
                    await asyncio.sleep(delay)
                    continue

                return await self._handle_error(policy, context, e, graph_logger, step_id, node.id)

        # Should never reach here, but handle it with a generic error
        return await self._handle_error(
            policy,
            context,
            RuntimeError("Execution failed after all retries"),
            graph_logger,
            step_id,
            node.id,
        )

    async def _handle_error(
        self,
        policy: ErrorPolicy,
        context: ExecutionContext,
        error: BaseException,
        graph_logger: Any = None,
        step_id: str | None = None,
        node_id: str | None = None,
    ) -> Any:
        """Handle error according to policy after retries exhausted.

        Args:
            policy: The error policy.
            context: Execution context.
            error: The exception that occurred.
            graph_logger: Logger for graph events.
            step_id: Step identifier for logging.
            node_id: Node identifier for logging.

        Returns:
            Fallback value or raises exception.
        """
        if policy.on_error == "fail":
            raise error

        if policy.on_error == "skip":
            # Log skip action
            if graph_logger:
                log_warning(
                    graph_logger,
                    self._id,
                    "step_skipped",
                    step=step_id,
                    node=node_id,
                    error_type=type(error).__name__,
                    error=str(error),
                    fallback_value=str(policy.fallback_value)[:100]
                    if policy.fallback_value
                    else None,
                )
            return policy.fallback_value

        if policy.on_error == "fallback" and policy.fallback_node:
            # Log fallback execution
            if graph_logger:
                log_start(
                    graph_logger,
                    self._id,
                    "step_fallback_start",
                    step=step_id,
                    original_node=node_id,
                    fallback_node=policy.fallback_node.id,
                    error_type=type(error).__name__,
                    error=str(error),
                )
            start_mono = time.monotonic()
            try:
                result = await policy.fallback_node.execute(context)
                # Log fallback complete
                if graph_logger:
                    duration = time.monotonic() - start_mono
                    log_complete(
                        graph_logger,
                        self._id,
                        "step_fallback_complete",
                        duration,
                        step=step_id,
                        fallback_node=policy.fallback_node.id,
                    )
                return result
            except Exception as fallback_error:
                # Log fallback failure
                if graph_logger:
                    duration = time.monotonic() - start_mono
                    log_error(
                        graph_logger,
                        self._id,
                        "step_fallback_failed",
                        fallback_error,
                        step=step_id,
                        fallback_node=policy.fallback_node.id,
                        duration_s=f"{duration:.1f}",
                    )
                raise

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
