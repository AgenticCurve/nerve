"""Centralized logging configuration for Nerve.

This module provides a unified way to configure logging across all Nerve components.
It supports both console (text) and file (JSON optional) output.

Usage:
    from nerve.core.logging_config import configure_logging, get_logger

    # Configure once at application startup
    configure_logging(level="DEBUG", json_output=False)

    # Get loggers in modules
    logger = get_logger(__name__)

Environment Variables:
    NERVE_LOG_LEVEL: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    NERVE_LOG_FORMAT: Output format ("text" or "json")
    NERVE_LOG_FILE: Optional log file path
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

# Default format for text output
TEXT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
TEXT_FORMAT_WITH_MS = "%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Track if logging has been configured
_configured = False


@dataclass
class LogConfig:
    """Logging configuration.

    Attributes:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        format: Output format ("text" or "json").
        file_path: Optional file path for file logging.
        include_ms: Include milliseconds in timestamp.
        propagate: Whether child loggers propagate to root.
    """

    level: str = "INFO"
    format: Literal["text", "json"] = "text"
    file_path: str | None = None
    include_ms: bool = True
    propagate: bool = True


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging.

    Outputs logs as JSON objects with consistent structure:
    {
        "timestamp": "2025-12-28T14:30:00.123Z",
        "level": "DEBUG",
        "logger": "nerve.core.session",
        "message": "session_created: name=test",
        "extra": {...}
    }
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Args:
            record: Log record to format.

        Returns:
            JSON string.
        """
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields (anything set on record that's not standard)
        standard_attrs = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "taskName",
            "message",
        }
        extra = {k: v for k, v in record.__dict__.items() if k not in standard_attrs}
        if extra:
            log_data["extra"] = extra

        return json.dumps(log_data, default=str)


def configure_logging(
    level: str | None = None,
    format: Literal["text", "json"] | None = None,
    file_path: str | None = None,
    include_ms: bool = True,
    force: bool = False,
) -> None:
    """Configure logging for the application.

    This should be called once at application startup. Subsequent calls
    are ignored unless force=True.

    Configuration can be overridden via environment variables:
    - NERVE_LOG_LEVEL: Log level
    - NERVE_LOG_FORMAT: Output format ("text" or "json")
    - NERVE_LOG_FILE: Log file path

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               Defaults to NERVE_LOG_LEVEL or "INFO".
        format: Output format. Defaults to NERVE_LOG_FORMAT or "text".
        file_path: Optional file path. Defaults to NERVE_LOG_FILE.
        include_ms: Include milliseconds in timestamp.
        force: Force reconfiguration even if already configured.
    """
    global _configured
    if _configured and not force:
        return

    # Apply environment variable overrides
    level = level or os.environ.get("NERVE_LOG_LEVEL", "INFO")
    format = format or os.environ.get("NERVE_LOG_FORMAT", "text")  # type: ignore
    file_path = file_path or os.environ.get("NERVE_LOG_FILE")

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Create formatter based on format type
    if format == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        fmt = TEXT_FORMAT_WITH_MS if include_ms else TEXT_FORMAT
        formatter = logging.Formatter(fmt, datefmt=DATE_FORMAT)

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if file_path:
        file_handler = logging.FileHandler(file_path)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.

    This is a convenience wrapper around logging.getLogger that ensures
    consistent logger naming.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Configured logger.
    """
    return logging.getLogger(name)


def set_level(level: str, logger_name: str | None = None) -> None:
    """Set log level for a specific logger or root logger.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        logger_name: Logger name. None for root logger.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, level.upper()))


def add_file_handler(
    file_path: str,
    level: str = "DEBUG",
    json_format: bool = False,
    logger_name: str | None = None,
) -> logging.FileHandler:
    """Add a file handler to a logger.

    Useful for adding per-component file logging.

    Args:
        file_path: Path to log file.
        level: Log level for this handler.
        json_format: Use JSON format.
        logger_name: Logger name. None for root logger.

    Returns:
        The created file handler.
    """
    logger = logging.getLogger(logger_name)

    handler = logging.FileHandler(file_path)
    handler.setLevel(getattr(logging, level.upper()))

    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(TEXT_FORMAT_WITH_MS, datefmt=DATE_FORMAT))

    logger.addHandler(handler)
    return handler
