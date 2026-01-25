"""Logging handlers and utilities for tchu-tchu."""

import logging
from typing import Optional

from celerysalt.logging.formatters import TchuFormatter


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    Get a configured logger for tchu-tchu components.

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

    # Add handler with TchuFormatter if none exists
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(TchuFormatter())
        logger.addHandler(handler)

    return logger


def log_message_published(
    logger: logging.Logger, topic: str, task_id: Optional[str] = None
) -> None:
    """Log a message publication event."""
    logger.info(
        "Message published successfully", extra={"topic": topic, "task_id": task_id}
    )


def log_message_received(
    logger: logging.Logger, topic: str, task_id: Optional[str] = None
) -> None:
    """Log a message reception event."""
    logger.info("Message received", extra={"topic": topic, "task_id": task_id})


def log_handler_executed(
    logger: logging.Logger,
    handler_name: str,
    topic: str,
    task_id: Optional[str] = None,
) -> None:
    """Log a handler execution event."""
    logger.info(
        f"Handler '{handler_name}' executed successfully",
        extra={"handler": handler_name, "topic": topic, "task_id": task_id},
    )


def log_rpc_call(
    logger: logging.Logger,
    topic: str,
    execution_time: float,
    task_id: Optional[str] = None,
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
    topic: Optional[str] = None,
    task_id: Optional[str] = None,
) -> None:
    """Log an error with context."""
    logger.error(
        message,
        extra={"topic": topic, "task_id": task_id, "error_type": type(error).__name__},
        exc_info=True,
    )
