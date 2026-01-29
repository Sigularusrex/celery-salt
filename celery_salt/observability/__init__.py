"""Optional observability integrations (OpenTelemetry)."""

from celery_salt.observability.opentelemetry import (
    get_trace_ids_for_logs,
    inject_trace_context,
    set_dispatch_span_attributes,
    set_publish_span_attributes,
)

__all__ = [
    "get_trace_ids_for_logs",
    "inject_trace_context",
    "set_dispatch_span_attributes",
    "set_publish_span_attributes",
]
