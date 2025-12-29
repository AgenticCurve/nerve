"""Session-level logging for comprehensive file-based logging.

Provides:
- Session lifecycle logging (session.log)
- Node lifecycle logging (node-runs/<id>.log + session.log)
- Graph run logging (graph-runs/<run-id>/)
- Direct node execution logging (node-runs/<id>.log with exec_id)

New Log Structure:
    .nerve/<server-name>/<session-name>/<session-timestamp>/
    ├── session.log                      # Session lifecycle + node/graph registration
    ├── graph-runs/                      # Graph executions
    │   └── <run-id>/
    │       ├── graph.log                # Graph orchestration
    │       └── <node-id>.log            # Node execution within graph
    └── node-runs/                       # Direct node executions (no graph)
        └── <node-id>.log                # All executions for this node
"""

from __future__ import annotations

import logging
import random
import string
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nerve.core.nodes.run_logging import (
    generate_run_id,
    log_complete,
    log_start,
)

if TYPE_CHECKING:
    from nerve.core.nodes.context import ExecutionContext
    from nerve.core.session.session import Session


# =============================================================================
# Shared Logging Utilities
# =============================================================================

# Standard log format used across all nerve loggers
LOG_FORMAT = "%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def create_log_formatter() -> logging.Formatter:
    """Create the standard log formatter used by all nerve loggers."""
    return logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)


def add_log_handlers(
    logger: logging.Logger,
    handlers_cache: dict[str, logging.Handler],
    cache_key: str,
    log_file: Path | None = None,
    file_logging: bool = True,
    console_logging: bool = False,
) -> None:
    """Add file and/or console handlers to a logger.

    This is a shared utility used by SessionLogger and _GraphRunLogger
    to configure loggers consistently.

    Args:
        logger: Logger to configure.
        handlers_cache: Dict to store handler references for cleanup.
        cache_key: Key for caching handlers.
        log_file: Path for file handler (required if file_logging=True).
        file_logging: Whether to add file handler.
        console_logging: Whether to add console handler.
    """
    formatter = create_log_formatter()

    if file_logging and log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        handlers_cache[f"{cache_key}:file"] = file_handler

    if console_logging:
        import sys

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        handlers_cache[f"{cache_key}:console"] = console_handler


def close_loggers(
    handlers: dict[str, logging.Handler],
    loggers: dict[str, logging.Logger],
) -> None:
    """Close all handlers and clean up loggers.

    Args:
        handlers: Dict of handler references to close.
        loggers: Dict of logger references to clean up.
    """
    for handler in handlers.values():
        handler.close()
    for logger in loggers.values():
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
    handlers.clear()
    loggers.clear()


# =============================================================================
# Logger Context for Node Execution
# =============================================================================


@dataclass
class LoggerContext:
    """Result of get_execution_logger.

    Attributes:
        logger: Logger instance, or None if logging unavailable.
        exec_id: Execution ID for direct execution, or None for graph execution.
    """

    logger: logging.Logger | None
    exec_id: str | None


def get_execution_logger(
    node_id: str,
    context: ExecutionContext,
    session: Session | None,
) -> LoggerContext:
    """Get logger and exec_id for node execution.

    Returns logger from run_logger (graph execution) or
    session_logger (direct execution with generated exec_id).

    Args:
        node_id: Node identifier.
        context: Execution context (may have run_logger for graph runs).
        session: Session (may have session_logger for direct execution).

    Returns:
        LoggerContext with logger and optional exec_id.
    """
    if context.run_logger:
        return LoggerContext(context.run_logger.get_logger(node_id), None)
    if session and session.session_logger:
        return LoggerContext(
            session.session_logger.get_node_logger(node_id),
            generate_exec_id(),
        )
    return LoggerContext(None, None)


def generate_session_timestamp() -> str:
    """Generate a session timestamp.

    Format: YYYYMMDD_HHMMSS

    Returns:
        Timestamp string like "20251228_143022"
    """
    return time.strftime("%Y%m%d_%H%M%S")


def generate_exec_id() -> str:
    """Generate an execution ID for direct node execution.

    Format: ex_HHMMSS_xxx
    - Shorter than run_id (meant for per-execution correlation)
    - 3-char random suffix

    Returns:
        Exec ID string like "ex_143022_x7k"
    """
    timestamp = time.strftime("%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=3))
    return f"ex_{timestamp}_{suffix}"


@dataclass
class SessionLogger:
    """Manages logging for a session's lifetime.

    Creates and manages log files in:
    .nerve/<server_name>/<session_name>/<session_timestamp>/

    Attributes:
        session_name: Session name.
        server_name: Server name.
        session_timestamp: Session start timestamp (YYYYMMDD_HHMMSS).
        base_dir: Base directory (default: .nerve in cwd).
        file_logging: Whether to write logs to files (default: True).
        console_logging: Whether to write logs to stdout (default: False).
    """

    session_name: str
    server_name: str
    session_timestamp: str
    base_dir: Path = field(default_factory=lambda: Path.cwd() / ".nerve")
    file_logging: bool = True
    console_logging: bool = False

    # Internal state
    _handlers: dict[str, logging.Handler] = field(default_factory=dict, repr=False)
    _loggers: dict[str, logging.Logger] = field(default_factory=dict, repr=False)
    _session_logger: logging.Logger | None = field(default=None, repr=False)

    @property
    def session_dir(self) -> Path:
        """Root directory for this session's logs."""
        return self.base_dir / self.server_name / self.session_name / self.session_timestamp

    @property
    def session_log_path(self) -> Path:
        """Path to session.log file."""
        return self.session_dir / "session.log"

    @property
    def graph_runs_dir(self) -> Path:
        """Directory for graph run logs."""
        return self.session_dir / "graph-runs"

    @property
    def node_runs_dir(self) -> Path:
        """Directory for direct node execution logs."""
        return self.session_dir / "node-runs"

    def setup(self) -> None:
        """Create log directories if file logging is enabled."""
        if self.file_logging:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            self.graph_runs_dir.mkdir(parents=True, exist_ok=True)
            self.node_runs_dir.mkdir(parents=True, exist_ok=True)

    def _add_handlers(
        self,
        logger: logging.Logger,
        cache_key: str,
        log_file: Path | None = None,
    ) -> None:
        """Add file and/or console handlers to a logger.

        Args:
            logger: Logger to configure.
            cache_key: Key for caching handlers.
            log_file: Path for file handler (required if file_logging=True).
        """
        add_log_handlers(
            logger,
            self._handlers,
            cache_key,
            log_file,
            self.file_logging,
            self.console_logging,
        )

    def get_graph_run_dir(self, run_id: str) -> Path:
        """Get directory for a specific graph run.

        Args:
            run_id: The run ID.

        Returns:
            Path to graph-runs/<run-id>/
        """
        return self.graph_runs_dir / run_id

    def get_node_run_path(self, node_id: str) -> Path:
        """Get log file path for direct node execution.

        Args:
            node_id: The node ID.

        Returns:
            Path to node-runs/<node-id>.log
        """
        return self.node_runs_dir / f"{node_id}.log"

    def get_session_logger(self) -> logging.Logger:
        """Get or create the session logger for session.log.

        Returns:
            Logger configured based on file_logging and console_logging settings.
        """
        if self._session_logger is not None:
            return self._session_logger

        # Create logger with unique name
        logger_name = f"nerve.session.{self.server_name}.{self.session_name}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        # Add handlers based on configuration
        self._add_handlers(logger, "session", self.session_log_path)

        self._session_logger = logger
        return logger

    def get_node_logger(self, node_id: str) -> logging.Logger:
        """Get or create a logger for direct node execution.

        Args:
            node_id: Node identifier.

        Returns:
            Logger configured based on file_logging and console_logging settings.
        """
        cache_key = f"node:{node_id}"
        if cache_key in self._loggers:
            return self._loggers[cache_key]

        # Ensure node-runs directory exists if file logging
        if self.file_logging:
            self.node_runs_dir.mkdir(parents=True, exist_ok=True)

        # Create logger with unique name
        logger_name = f"nerve.node.{self.server_name}.{self.session_name}.{node_id}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        # Add handlers based on configuration
        log_file = self.get_node_run_path(node_id)
        self._add_handlers(logger, cache_key, log_file)

        self._loggers[cache_key] = logger
        return logger

    def create_graph_run_logger(self, run_id: str | None = None) -> _GraphRunLogger:
        """Create a RunLogger for graph execution.

        Args:
            run_id: Run ID (generated if not provided).

        Returns:
            Configured _GraphRunLogger with directory created.
        """
        if run_id is None:
            run_id = generate_run_id()

        # Create the run directory under graph-runs
        run_dir = self.get_graph_run_dir(run_id)

        # Create a _GraphRunLogger that uses this directory
        run_logger = _GraphRunLogger(
            run_id=run_id,
            _log_dir=run_dir,
            file_logging=self.file_logging,
            console_logging=self.console_logging,
        )
        run_logger.setup()
        return run_logger

    # =========================================================================
    # Session Lifecycle Logging
    # =========================================================================

    def log_session_start(
        self,
        persistent_nodes: int = 0,
        node_ids: list[str] | None = None,
    ) -> None:
        """Log session start event.

        Args:
            persistent_nodes: Number of stateful nodes.
            node_ids: List of stateful node IDs.
        """
        logger = self.get_session_logger()
        log_start(
            logger,
            self.session_name,
            "session_start",
            server=self.server_name,
            timestamp=self.session_timestamp,
            persistent_nodes=persistent_nodes,
            node_ids=node_ids or [],
        )

    def log_session_stop(
        self,
        nodes: int,
        graphs: int,
        duration_s: float | None = None,
    ) -> None:
        """Log session stop event.

        Args:
            nodes: Number of nodes at stop.
            graphs: Number of graphs at stop.
            duration_s: Session duration in seconds (if known).
        """
        logger = self.get_session_logger()
        if duration_s is not None:
            log_complete(
                logger,
                self.session_name,
                "session_stop",
                duration_s,
                nodes=nodes,
                graphs=graphs,
            )
        else:
            log_start(
                logger,
                self.session_name,
                "session_stop",
                nodes=nodes,
                graphs=graphs,
            )

    # =========================================================================
    # Node Lifecycle Logging (dual logging to session.log + node-runs/<id>.log)
    # =========================================================================

    def log_node_lifecycle(
        self,
        node_id: str,
        node_type: str,
        persistent: bool = False,
        started: bool = False,
        command: str | None = None,
        pid: int | None = None,
    ) -> None:
        """Log node registration, creation, and optionally start.

        Convenience method that combines log_node_registered, log_node_created,
        and optionally log_node_started.

        Args:
            node_id: Node identifier.
            node_type: Node class name.
            persistent: Whether the node is persistent.
            started: If True, also log node_started event.
            command: Command for node_started (if started=True).
            pid: Process ID for node_started (if started=True).
        """
        self.log_node_registered(node_id, node_type, persistent)
        self.log_node_created(node_id, node_type, persistent)
        if started:
            self.log_node_started(node_id, command, pid)

    def log_node_registered(
        self,
        node_id: str,
        node_type: str,
        persistent: bool = False,
    ) -> None:
        """Log node registration to session.log.

        Args:
            node_id: Node identifier.
            node_type: Node class name.
            persistent: Whether the node is persistent.
        """
        logger = self.get_session_logger()
        log_start(
            logger,
            self.session_name,
            "node_registered",
            node_id=node_id,
            type=node_type,
            persistent=persistent,
        )

    def log_node_created(
        self,
        node_id: str,
        node_type: str,
        persistent: bool = False,
    ) -> None:
        """Log node creation to node-runs/<id>.log.

        Args:
            node_id: Node identifier.
            node_type: Node class name.
            persistent: Whether the node is persistent.
        """
        logger = self.get_node_logger(node_id)
        log_start(
            logger,
            node_id,
            "node_created",
            type=node_type,
            persistent=persistent,
        )

    def log_node_started(
        self,
        node_id: str,
        command: str | None = None,
        pid: int | None = None,
    ) -> None:
        """Log persistent node started (dual log).

        Args:
            node_id: Node identifier.
            command: Command that started the node.
            pid: Process ID.
        """
        kwargs: dict[str, Any] = {}
        if command:
            kwargs["command"] = command
        if pid:
            kwargs["pid"] = pid

        # Log to session.log
        session_logger = self.get_session_logger()
        log_start(session_logger, self.session_name, "node_started", node_id=node_id, **kwargs)

        # Log to node-runs/<id>.log
        node_logger = self.get_node_logger(node_id)
        log_start(node_logger, node_id, "node_started", **kwargs)

    def log_node_stopped(
        self,
        node_id: str,
        reason: str = "manual",
    ) -> None:
        """Log persistent node stopped (dual log).

        Args:
            node_id: Node identifier.
            reason: Reason for stopping.
        """
        # Log to session.log
        session_logger = self.get_session_logger()
        log_start(session_logger, self.session_name, "node_stopped", node_id=node_id, reason=reason)

        # Log to node-runs/<id>.log
        node_logger = self.get_node_logger(node_id)
        log_start(node_logger, node_id, "node_stopped", reason=reason)

    def log_node_deregistered(
        self,
        node_id: str,
        reason: str = "deleted",
    ) -> None:
        """Log node deregistration to session.log.

        Args:
            node_id: Node identifier.
            reason: Reason for deregistration.
        """
        logger = self.get_session_logger()
        log_start(
            logger,
            self.session_name,
            "node_deregistered",
            node_id=node_id,
            reason=reason,
        )

    def log_node_deleted(
        self,
        node_id: str,
        reason: str = "deleted",
    ) -> None:
        """Log node deletion to node-runs/<id>.log.

        Args:
            node_id: Node identifier.
            reason: Reason for deletion.
        """
        logger = self.get_node_logger(node_id)
        log_start(
            logger,
            node_id,
            "node_deleted",
            reason=reason,
        )

    # =========================================================================
    # Graph Lifecycle Logging
    # =========================================================================

    def log_graph_registered(
        self,
        graph_id: str,
        steps: int,
    ) -> None:
        """Log graph registration to session.log.

        Args:
            graph_id: Graph identifier.
            steps: Number of steps in the graph.
        """
        logger = self.get_session_logger()
        log_start(
            logger,
            self.session_name,
            "graph_registered",
            graph_id=graph_id,
            steps=steps,
        )

    def log_graph_deregistered(
        self,
        graph_id: str,
    ) -> None:
        """Log graph deregistration to session.log.

        Args:
            graph_id: Graph identifier.
        """
        logger = self.get_session_logger()
        log_start(
            logger,
            self.session_name,
            "graph_deregistered",
            graph_id=graph_id,
        )

    # =========================================================================
    # Cleanup
    # =========================================================================

    def close(self) -> None:
        """Close all file handlers."""
        # Close session logger separately since it's not in _loggers
        if self._session_logger:
            for handler in self._session_logger.handlers[:]:
                self._session_logger.removeHandler(handler)
            self._session_logger = None
        # Use shared cleanup utility for cached loggers
        close_loggers(self._handlers, self._loggers)

    # =========================================================================
    # Factory
    # =========================================================================

    @classmethod
    def create(
        cls,
        session_name: str,
        server_name: str = "default",
        session_timestamp: str | None = None,
        base_dir: Path | None = None,
        file_logging: bool = True,
        console_logging: bool = False,
    ) -> SessionLogger:
        """Create and setup a new SessionLogger.

        Args:
            session_name: Session name.
            server_name: Server name.
            session_timestamp: Session timestamp (generated if not provided).
            base_dir: Base directory (default: .nerve in cwd).
            file_logging: Write logs to files (default: True).
            console_logging: Write logs to stderr (default: False).

        Returns:
            Configured SessionLogger with directories created.
        """
        if session_timestamp is None:
            session_timestamp = generate_session_timestamp()

        if base_dir is None:
            base_dir = Path.cwd() / ".nerve"

        session_logger = cls(
            session_name=session_name,
            server_name=server_name,
            session_timestamp=session_timestamp,
            base_dir=base_dir,
            file_logging=file_logging,
            console_logging=console_logging,
        )
        session_logger.setup()
        return session_logger


@dataclass
class _GraphRunLogger:
    """Internal RunLogger for graph runs within a session.

    This is a simplified logger that has the same interface as RunLogger
    but points to graph-runs/<run-id>/ instead of runs/<run-id>/.
    """

    run_id: str
    _log_dir: Path
    file_logging: bool = True
    console_logging: bool = False

    # Internal state
    _handlers: dict[str, logging.Handler] = field(default_factory=dict, repr=False)
    _loggers: dict[str, logging.Logger] = field(default_factory=dict, repr=False)

    @property
    def log_dir(self) -> Path:
        """Get the log directory for this run."""
        return self._log_dir

    def setup(self) -> None:
        """Create log directory if file logging is enabled."""
        if self.file_logging:
            self._log_dir.mkdir(parents=True, exist_ok=True)

    def get_logger(self, name: str) -> logging.Logger:
        """Get or create a logger for a specific component.

        Args:
            name: Component name (e.g., "graph", "step-fetch", "bash").

        Returns:
            Logger configured based on file_logging and console_logging settings.
        """
        if name in self._loggers:
            return self._loggers[name]

        # Create logger with unique name to avoid conflicts
        logger_name = f"nerve.graphrun.{self.run_id}.{name}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        # Don't propagate to root logger (avoid duplicate console output)
        logger.propagate = False

        # Use shared handler utility
        log_file = self._log_dir / f"{name}.log" if self.file_logging else None
        add_log_handlers(
            logger,
            self._handlers,
            name,
            log_file,
            self.file_logging,
            self.console_logging,
        )

        self._loggers[name] = logger
        return logger

    def close(self) -> None:
        """Close all handlers."""
        close_loggers(self._handlers, self._loggers)
