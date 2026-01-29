# Observability in Celery Salt

This document describes how to observe and operate celery-salt in production: structured logging, metrics, and optional correlation IDs.

## Structured logging

All celery-salt loggers use a **JSON formatter** by default so that log aggregators (Datadog, ELK, CloudWatch, etc.) can parse and query by field.

### One line per task (INFO)

At INFO level you get **one log line per dispatch** with:

- `message`: `"Dispatch completed"`
- `topic`, `task_id`, `duration_seconds`, `is_rpc`, `handlers_executed`, `status`
- `correlation_id` (if set in `_tchu_meta`)

Example:

```json
{"timestamp": "2026-01-29T16:02:50.112Z", "level": "INFO", "logger": "celery_salt.integrations.dispatcher", "message": "Dispatch completed", "topic": "rpc.data_room.data_room.survey_submission.retrieve", "task_id": "007cdb60-2954-42e3-ae82-ebadae47956a", "duration_seconds": 0.279, "is_rpc": true, "handlers_executed": 1, "status": "completed"}
```

### Reducing duplicate lines

Celery-salt loggers use `propagate = False` when they attach their own handler, so each event is emitted **once** (as JSON). You will still see Celery’s own lines (e.g. “Task … received”, “Task … succeeded”); to reduce noise you can:

- Raise Celery’s log level for the worker, or
- Rely on the single `"Dispatch completed"` line and treat Celery’s lines as optional.

### Verbose (DEBUG)

At DEBUG you also get:

- `"Message received"` when a message is taken off the queue
- `"Handler executed successfully"` per handler

Set the logger level to DEBUG when troubleshooting:

```python
import logging
logging.getLogger("celery_salt.integrations.dispatcher").setLevel(logging.DEBUG)
```

### Using your app’s logging config

If your app already configures logging (e.g. in Django `LOGGING`), celery-salt will **not** add an extra handler for loggers that already have handlers. Configure the `celery_salt.*` loggers in your app so they use your preferred formatter and destination.

## Metrics

The package collects **in-process metrics** automatically when messages are published or dispatched:

- **Received**: `record_message_received(topic, task_id=…)`
- **Published**: `record_message_published(topic, task_id=…)`
- **RPC**: `record_rpc_call(topic, execution_time, task_id=…)` (server and client)
- **Errors**: `record_error(topic, error_type, task_id=…)`

No extra configuration is required; the global collector is used by the dispatcher and producer.

### Reading metrics

```python
from celery_salt.metrics.collectors import get_metrics_collector
from datetime import timedelta

collector = get_metrics_collector()

# Summary (e.g. last hour)
summary = collector.get_summary(time_window=timedelta(hours=1))
# total_messages, messages_by_type, messages_by_topic, errors_by_type, rpc_statistics

# Per-topic stats
stats = collector.get_topic_stats("rpc.myapp.myresource.retrieve", time_window=timedelta(hours=1))

# Recent errors
errors = collector.get_recent_errors(limit=50)
```

### Exporting (Prometheus, JSON, logs)

Use `MetricsReporter` to generate a report and send it to one or more exporters:

```python
from celery_salt.metrics.collectors import get_metrics_collector
from celery_salt.metrics.exporters import MetricsReporter, PrometheusExporter, JSONExporter
from datetime import timedelta

reporter = MetricsReporter(
    collector=get_metrics_collector(),
    exporters=[
        PrometheusExporter("/tmp/celery_salt_metrics.prom"),
        JSONExporter("/tmp/celery_salt_metrics.json"),
    ],
)

# One-off report (e.g. from a cron or management command)
reporter.export_report(time_window=timedelta(hours=1), include_errors=True)
```

For Prometheus, point a scrape config at the file or expose the report via an HTTP endpoint (e.g. Django view that runs `export_report` and returns the Prometheus text).

## Correlation ID (distributed tracing)

To trace a request across publisher → queue → worker:

1. **Publisher**: Pass `correlation_id` when publishing (e.g. your HTTP request ID or OpenTelemetry trace id):

   ```python
   from celery_salt.integrations.producer import publish_event, call_rpc

   request_id = request.headers.get("X-Request-ID")  # or generate one

   # Broadcast
   publish_event("myapp.event.created", payload, correlation_id=request_id)

   # RPC
   result = call_rpc("myapp.resource.retrieve", payload, correlation_id=request_id)
   ```

   The value is stored in `_tchu_meta.correlation_id` and carried to the worker.

2. **Worker**: The dispatcher reads `_tchu_meta.correlation_id` and adds it to the **Dispatch completed** log line and to the formatter’s `extra`, so log aggregators can filter or group by `correlation_id`.

## OpenTelemetry (optional)

When [OpenTelemetry](https://opentelemetry.io/) is available, celery-salt integrates with it so traces and logs line up with your existing instrumentation.

### Install

```bash
pip install celery-salt[opentelemetry]
```

Or install `opentelemetry-api` (and optionally the SDK + instrumentation) yourself.

### What you get

- **Trace context in messages**  
  When publishing, the current trace context (W3C `traceparent` / `tracestate`) is injected into `_tchu_meta`. Consumers that use OpenTelemetry can continue the same trace.

- **Span attributes**  
  The current span is enriched with celery-salt semantics:
  - **Producer**: `celery_salt.topic`, `celery_salt.message_id`, `celery_salt.is_rpc`
  - **Dispatcher**: `celery_salt.topic`, `celery_salt.task_id`, `celery_salt.is_rpc`, `celery_salt.handlers_executed`, `celery_salt.duration_seconds`, `celery_salt.status`

  So in Jaeger/Datadog/etc. you can filter or group by topic or status.

- **Log–trace correlation**  
  If OpenTelemetry is installed, the JSON formatter adds `trace_id` and `span_id` to each log line so your log backend can link logs to traces.

### Using with Celery instrumentation

For end-to-end traces across publisher → queue → worker, use [opentelemetry-instrumentation-celery](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/celery/celery.html) and initialise it in the worker (e.g. in `worker_process_init`). Celery-salt then adds the attributes above to the same spans and propagates context in the message body so non-Celery consumers can still continue the trace.

### No OpenTelemetry

If `opentelemetry-api` is not installed, all of the above is skipped (no-ops). The rest of observability (structured logs, in-process metrics, correlation_id) still works.

---

## Summary

| Concern            | What you get |
|--------------------|--------------|
| **Log format**     | JSON with timestamp, level, logger, message, topic, task_id, duration_seconds, is_rpc, handlers_executed, status, optional correlation_id, optional trace_id/span_id (OpenTelemetry). |
| **Log volume**     | One INFO line per task (`Dispatch completed`); per-message/handler lines at DEBUG. |
| **Metrics**        | Automatic recording of received, published, RPC, and errors; summary and per-topic stats; export via Prometheus/JSON/log. |
| **Tracing**        | Set `_tchu_meta.correlation_id` when publishing; it appears in dispatch logs. With `opentelemetry-api`, W3C trace context is injected in messages and span attributes + trace_id/span_id in logs. |
