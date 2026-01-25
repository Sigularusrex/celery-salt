"""Structured logging formatters for tchu-tchu."""

import json
import logging
from datetime import datetime
from typing import Any, Dict


class TchuFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging in tchu-tchu.

    Formats log records as JSON with consistent structure including:
    - timestamp
    - level
    - logger name
    - message
    - topic (if available)
    - task_id (if available)
    - extra context
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add topic if available
        if hasattr(record, "topic"):
            log_entry["topic"] = record.topic

        # Add task_id if available
        if hasattr(record, "task_id"):
            log_entry["task_id"] = record.task_id

        # Add correlation_id if available
        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id

        # Add execution time if available
        if hasattr(record, "execution_time"):
            log_entry["execution_time"] = record.execution_time

        # Add any extra fields
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "topic",
                "task_id",
                "correlation_id",
                "execution_time",
            }:
                extra_fields[key] = value

        if extra_fields:
            log_entry["extra"] = extra_fields

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)
