"""
Optional OpenTelemetry integration for celery-salt.

When opentelemetry-api is installed, this module:
- Injects W3C trace context into _tchu_meta when publishing (for distributed tracing).
- Sets semantic attributes on the current span in dispatcher and producer
  (topic, task_id, is_rpc, duration, etc.) so traces are queryable by topic/handler.
- Exposes trace_id and span_id for log correlation (e.g. in CelerySaltFormatter).

Install the optional extra to enable:
  pip install celery-salt[opentelemetry]

Or install opentelemetry-api (and optionally opentelemetry-sdk + instrumentation) yourself.
"""

from typing import Any

# Lazy imports and availability check; all public functions no-op when OTel is not installed
_OTEL_AVAILABLE = False
_trace = None
_propagate = None

try:
    from opentelemetry import propagate, trace

    _trace = trace
    _propagate = propagate
    _OTEL_AVAILABLE = True
except ImportError:
    pass


def inject_trace_context(tchu_meta: dict[str, Any]) -> None:
    """
    Inject the current trace context into _tchu_meta so consumers can continue the trace.

    Call this when building the message (e.g. in producer) before publishing.
    Keys such as traceparent and tracestate (W3C Trace Context) are added to tchu_meta.
    No-op if opentelemetry is not installed.
    """
    if not _OTEL_AVAILABLE or not tchu_meta:
        return
    try:
        propagator = _propagate.get_global_textmap()
        propagator.inject(tchu_meta)
    except Exception:
        pass


def set_publish_span_attributes(
    topic: str,
    message_id: str | None = None,
    is_rpc: bool = False,
) -> None:
    """
    Set attributes on the current span when publishing a message.

    Use after starting or when you have an active span (e.g. from HTTP or Celery instrumentation).
    No-op if opentelemetry is not installed or there is no recording span.
    """
    if not _OTEL_AVAILABLE:
        return
    try:
        span = _trace.get_current_span()
        if span.is_recording():
            span.set_attribute("celery_salt.topic", topic)
            span.set_attribute("celery_salt.is_rpc", is_rpc)
            if message_id:
                span.set_attribute("celery_salt.message_id", message_id)
    except Exception:
        pass


def set_dispatch_span_attributes(
    topic: str,
    task_id: str | None = None,
    is_rpc: bool = False,
    handlers_executed: int | None = None,
    duration_seconds: float | None = None,
    status: str | None = None,
) -> None:
    """
    Set attributes on the current span when dispatching a message (worker side).

    Call at the end of dispatch so the Celery task span (or current span) is enriched.
    No-op if opentelemetry is not installed or there is no recording span.
    """
    if not _OTEL_AVAILABLE:
        return
    try:
        span = _trace.get_current_span()
        if span.is_recording():
            span.set_attribute("celery_salt.topic", topic)
            span.set_attribute("celery_salt.is_rpc", is_rpc)
            if task_id:
                span.set_attribute("celery_salt.task_id", task_id)
            if handlers_executed is not None:
                span.set_attribute("celery_salt.handlers_executed", handlers_executed)
            if duration_seconds is not None:
                span.set_attribute("celery_salt.duration_seconds", duration_seconds)
            if status:
                span.set_attribute("celery_salt.status", status)
    except Exception:
        pass


def get_trace_ids_for_logs() -> dict[str, str]:
    """
    Return trace_id and span_id for the current span for log correlation.

    Use in log formatters or handlers so log backends can link logs to traces.
    Returns {} if opentelemetry is not installed or span is invalid.
    """
    if not _OTEL_AVAILABLE:
        return {}
    try:
        span = _trace.get_current_span()
        ctx = span.get_span_context()
        if not ctx or not ctx.is_valid:
            return {}
        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
        }
    except Exception:
        return {}
