"""Structured logging formatters for CelerySalt."""

import json
import logging
from datetime import datetime
from typing import Any


class CelerySaltFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging in CelerySalt.

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
        log_entry: dict[str, Any] = {
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

        # OpenTelemetry: add trace_id and span_id when available (for log-trace correlation)
        try:
            from celery_salt.observability.opentelemetry import get_trace_ids_for_logs

            trace_ids = get_trace_ids_for_logs()
            if trace_ids:
                log_entry["trace_id"] = trace_ids.get("trace_id")
                log_entry["span_id"] = trace_ids.get("span_id")
        except Exception:
            pass

        # Add execution time if available
        if hasattr(record, "execution_time"):
            log_entry["execution_time"] = record.execution_time

        # Observability: one-line-per-dispatch fields
        if hasattr(record, "duration_seconds"):
            log_entry["duration_seconds"] = record.duration_seconds
        if hasattr(record, "is_rpc"):
            log_entry["is_rpc"] = record.is_rpc
        if hasattr(record, "handlers_executed"):
            log_entry["handlers_executed"] = record.handlers_executed
        if hasattr(record, "status"):
            log_entry["status"] = record.status

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
                "duration_seconds",
                "is_rpc",
                "handlers_executed",
                "status",
                "trace_id",
                "span_id",
            }:
                extra_fields[key] = value

        if extra_fields:
            log_entry["extra"] = extra_fields

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)
