"""Logging handlers and utilities for CelerySalt."""

import logging

from celery_salt.logging.formatters import CelerySaltFormatter


def get_logger(name: str, level: str | None = None) -> logging.Logger:
    """
    Get a configured logger for CelerySalt components.

    Args:
        name: Logger name (typically __name__)
        level: Optional log level override

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Set level if provided
    if level:
        logger.setLevel(getattr(logging, level.upper()))
    elif not logger.handlers:
        # Default to INFO if no handlers configured
        logger.setLevel(logging.INFO)

    # Add handler with CelerySaltFormatter if none exists.
    # Set propagate=False to avoid duplicate output (root logger would emit again).
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(CelerySaltFormatter())
        logger.addHandler(handler)
        logger.propagate = False

    return logger


def log_message_published(
    logger: logging.Logger, topic: str, task_id: str | None = None
) -> None:
    """Log a message publication event."""
    logger.info(
        "Message published successfully", extra={"topic": topic, "task_id": task_id}
    )


def log_message_received(
    logger: logging.Logger, topic: str, task_id: str | None = None
) -> None:
    """Log a message reception event (DEBUG to reduce INFO noise)."""
    logger.debug("Message received", extra={"topic": topic, "task_id": task_id})


def log_handler_executed(
    logger: logging.Logger,
    handler_name: str,
    topic: str,
    task_id: str | None = None,
) -> None:
    """Log a handler execution event (DEBUG to reduce INFO noise)."""
    logger.debug(
        "Handler executed successfully",
        extra={"handler": handler_name, "topic": topic, "task_id": task_id},
    )


def log_dispatch_completed(
    logger: logging.Logger,
    topic: str,
    task_id: str | None,
    duration_seconds: float,
    is_rpc: bool,
    handlers_executed: int,
    status: str = "completed",
    correlation_id: str | None = None,
) -> None:
    """Log a single observability event per dispatch (one line per task at INFO)."""
    extra = {
        "topic": topic,
        "task_id": task_id,
        "duration_seconds": duration_seconds,
        "is_rpc": is_rpc,
        "handlers_executed": handlers_executed,
        "status": status,
    }
    if correlation_id:
        extra["correlation_id"] = correlation_id
    logger.info(
        "Dispatch completed",
        extra=extra,
    )


def log_rpc_call(
    logger: logging.Logger,
    topic: str,
    execution_time: float,
    task_id: str | None = None,
) -> None:
    """Log an RPC call completion."""
    logger.info(
        f"RPC call completed in {execution_time:.2f} seconds",
        extra={"topic": topic, "execution_time": execution_time, "task_id": task_id},
    )


def log_error(
    logger: logging.Logger,
    message: str,
    error: Exception,
    topic: str | None = None,
    task_id: str | None = None,
) -> None:
    """Log an error with context."""
    logger.error(
        message,
        extra={"topic": topic, "task_id": task_id, "error_type": type(error).__name__},
        exc_info=True,
    )
