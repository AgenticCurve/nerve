"""NerveEngine - Command dispatcher for the Nerve server.

NerveEngine is a thin dispatcher that:
- Routes commands to appropriate domain handlers
- Provides structured exception handling
- Emits error events for infrastructure failures
- Exposes shutdown_requested property for server loop

This is the refactored version that follows domain-driven design with clear
separation of concerns. All business logic is in the handlers package.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nerve.core.session import Session
from nerve.server.factories.node_factory import NodeFactory
from nerve.server.handlers.graph_handler import GraphHandler
from nerve.server.handlers.node_interaction_handler import NodeInteractionHandler
from nerve.server.handlers.node_lifecycle_handler import NodeLifecycleHandler
from nerve.server.handlers.python_executor import PythonExecutor
from nerve.server.handlers.repl_command_handler import ReplCommandHandler
from nerve.server.handlers.server_handler import ServerHandler
from nerve.server.handlers.session_handler import SessionHandler
from nerve.server.protocols import (
    Command,
    CommandResult,
    CommandType,
    Event,
    EventType,
)
from nerve.server.proxy_manager import ProxyHealthError, ProxyManager, ProxyStartError
from nerve.server.session_registry import SessionRegistry
from nerve.server.validation import ValidationHelpers

if TYPE_CHECKING:
    from nerve.server.protocols import EventSink

logger = logging.getLogger(__name__)


@dataclass
class NerveEngine:
    """Command dispatcher for the Nerve server.

    Responsibilities:
    - Route commands to appropriate domain handlers
    - Structured exception handling
    - Error event emission
    - Handler map construction
    - Expose shutdown_requested property for server loop

    Example:
        >>> sink = MyEventSink()
        >>> engine = build_nerve_engine(event_sink=sink)
        >>>
        >>> result = await engine.execute(Command(
        ...     type=CommandType.CREATE_NODE,
        ...     params={"node_id": "my-claude", "command": "claude"},
        ... ))
        >>>
        >>> node_id = result.data["node_id"]  # "my-claude"
    """

    event_sink: EventSink
    session_registry: SessionRegistry
    node_lifecycle_handler: NodeLifecycleHandler
    node_interaction_handler: NodeInteractionHandler
    graph_handler: GraphHandler
    session_handler: SessionHandler
    python_executor: PythonExecutor
    repl_command_handler: ReplCommandHandler
    server_handler: ServerHandler

    # Handler map (built in __post_init__)
    _handlers: dict[
        CommandType, Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]
    ] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Initialize handler map."""
        self._handlers = self._build_handler_map()

    @property
    def shutdown_requested(self) -> bool:
        """Whether shutdown has been requested (delegates to ServerHandler)."""
        return self.server_handler.shutdown_requested

    def request_shutdown(self) -> None:
        """Request server shutdown (for signal handlers)."""
        self.server_handler._shutdown_requested = True

    async def execute(self, command: Command) -> CommandResult:
        """Dispatch command to appropriate handler.

        Error Handling Strategy:
        - ValueError: User/validation errors (expected)
        - ProxyError: Infrastructure errors (emit event)
        - CancelledError: Propagate (don't swallow)
        - Exception: Internal errors (log + emit event)

        Args:
            command: The command to execute.

        Returns:
            CommandResult with success/failure and data.
        """
        handler = self._handlers.get(command.type)
        if not handler:
            return CommandResult(
                success=False,
                error=f"Unknown command type: {command.type}",
                request_id=command.request_id,
            )

        try:
            data = await handler(command.params)
            return CommandResult(
                success=True,
                data=data,
                request_id=command.request_id,
            )
        except ValueError as e:
            # Validation/user errors - expected, no event
            return CommandResult(
                success=False,
                error=str(e),
                request_id=command.request_id,
            )
        except (ProxyStartError, ProxyHealthError) as e:
            # Infrastructure errors - emit event
            await self.event_sink.emit(
                Event(
                    type=EventType.ERROR,
                    data={"error": str(e), "type": "infrastructure"},
                )
            )
            return CommandResult(
                success=False,
                error=str(e),
                request_id=command.request_id,
            )
        except asyncio.CancelledError:
            # Cancellation should propagate
            raise
        except Exception as e:
            # Unexpected internal errors - log with trace
            logger.exception(f"Command {command.type.name} failed")
            await self.event_sink.emit(
                Event(
                    type=EventType.ERROR,
                    data={"error": str(e), "type": "internal"},
                )
            )
            return CommandResult(
                success=False,
                error=f"Internal error: {type(e).__name__}: {e}",
                request_id=command.request_id,
            )

    def _build_handler_map(
        self,
    ) -> dict[CommandType, Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]]:
        """Build command type → handler method mapping."""
        return {
            # Node lifecycle
            CommandType.CREATE_NODE: self.node_lifecycle_handler.create_node,
            CommandType.DELETE_NODE: self.node_lifecycle_handler.delete_node,
            CommandType.LIST_NODES: self.node_lifecycle_handler.list_nodes,
            CommandType.GET_NODE: self.node_lifecycle_handler.get_node,
            # Node interaction
            CommandType.RUN_COMMAND: self.node_interaction_handler.run_command,
            CommandType.EXECUTE_INPUT: self.node_interaction_handler.execute_input,
            CommandType.SEND_INTERRUPT: self.node_interaction_handler.send_interrupt,
            CommandType.WRITE_DATA: self.node_interaction_handler.write_data,
            CommandType.GET_BUFFER: self.node_interaction_handler.get_buffer,
            CommandType.GET_HISTORY: self.node_interaction_handler.get_history,
            # Python execution
            CommandType.EXECUTE_PYTHON: self.python_executor.execute_python,
            # REPL commands
            CommandType.EXECUTE_REPL_COMMAND: self.repl_command_handler.execute_repl_command,
            # Graph execution
            CommandType.CREATE_GRAPH: self.graph_handler.create_graph,
            CommandType.DELETE_GRAPH: self.graph_handler.delete_graph,
            CommandType.EXECUTE_GRAPH: self.graph_handler.execute_graph,
            CommandType.RUN_GRAPH: self.graph_handler.run_graph,
            CommandType.CANCEL_GRAPH: self.graph_handler.cancel_graph,
            CommandType.LIST_GRAPHS: self.graph_handler.list_graphs,
            CommandType.GET_GRAPH: self.graph_handler.get_graph_info,
            # Session management
            CommandType.CREATE_SESSION: self.session_handler.create_session,
            CommandType.DELETE_SESSION: self.session_handler.delete_session,
            CommandType.LIST_SESSIONS: self.session_handler.list_sessions,
            CommandType.GET_SESSION: self.session_handler.get_session_info,
            # Server control
            CommandType.STOP: self.server_handler.stop,
            CommandType.PING: self.server_handler.ping,
        }


def build_nerve_engine(
    event_sink: EventSink,
    server_name: str = "default",
) -> NerveEngine:
    """Build fully-wired NerveEngine with all handlers.

    Uses SessionRegistry pattern to solve shared mutable state problem.
    Creates default session on initialization (matching original engine behavior).

    Args:
        event_sink: EventSink for emitting events.
        server_name: Server name for session/history paths.

    Returns:
        Fully-wired NerveEngine instance.
    """
    # Create session registry (solves shared state problem)
    session_registry = SessionRegistry()

    # Create and register default session (matching engine.__post_init__ behavior)
    default_session = Session(name="default", server_name=server_name)
    session_registry.add_session("default", default_session)
    session_registry.set_default("default")

    # Shared dependencies
    proxy_manager = ProxyManager()
    validation = ValidationHelpers()

    # Factories
    node_factory = NodeFactory()

    # Handlers (ALL take session_registry, not raw state)
    node_lifecycle_handler = NodeLifecycleHandler(
        event_sink=event_sink,
        node_factory=node_factory,
        proxy_manager=proxy_manager,
        validation=validation,
        session_registry=session_registry,
        server_name=server_name,
    )

    node_interaction_handler = NodeInteractionHandler(
        event_sink=event_sink,
        validation=validation,
        session_registry=session_registry,
        server_name=server_name,
    )

    python_executor = PythonExecutor(
        validation=validation,
        session_registry=session_registry,
    )

    repl_command_handler = ReplCommandHandler(
        validation=validation,
        session_registry=session_registry,
    )

    graph_handler = GraphHandler(
        event_sink=event_sink,
        validation=validation,
        session_registry=session_registry,
    )

    session_handler = SessionHandler(
        event_sink=event_sink,
        validation=validation,
        session_registry=session_registry,
        server_name=server_name,
    )

    server_handler = ServerHandler(
        event_sink=event_sink,
        proxy_manager=proxy_manager,
        session_registry=session_registry,
        graph_handler=graph_handler,
    )

    # Engine (dispatcher)
    return NerveEngine(
        event_sink=event_sink,
        session_registry=session_registry,
        node_lifecycle_handler=node_lifecycle_handler,
        node_interaction_handler=node_interaction_handler,
        graph_handler=graph_handler,
        session_handler=session_handler,
        python_executor=python_executor,
        repl_command_handler=repl_command_handler,
        server_handler=server_handler,
    )
