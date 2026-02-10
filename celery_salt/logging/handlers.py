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


def log_handler_processed(
    logger: logging.Logger,
    handler_name: str,
    topic: str,
    task_id: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    """Log when a subscriber handler has processed an event (INFO)."""
    extra: dict[str, str | float | None] = {
        "handler": handler_name,
        "topic": topic,
        "task_id": task_id,
    }
    if duration_seconds is not None:
        extra["duration_seconds"] = duration_seconds
    logger.info(
        f"Subscriber '{handler_name}' processed '{topic}' ({duration_seconds:.2f}s)"
        if duration_seconds is not None
        else f"Subscriber '{handler_name}' processed '{topic}'",
        extra=extra,
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
    handler_errors: int = 0,
) -> None:
    """Log a single observability event per dispatch (one line per task at INFO or WARNING)."""
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
    if handler_errors:
        extra["handler_errors"] = handler_errors
    if handler_errors and is_rpc:
        logger.warning(
            f"Dispatch completed ({handler_errors} handler(s) failed)",
            extra=extra,
        )
    else:
        logger.info(
            "Dispatch completed",
            extra=extra,
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
