"""Metrics collection for tchu-tchu operations."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)


@dataclass
class MessageMetric:
    """Represents a single message metric."""

    topic: str
    event_type: str  # "published", "received", "rpc_call", "error"
    timestamp: datetime
    execution_time: float | None = None
    task_id: str | None = None
    error_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MetricsCollector:
    """
    Collects and aggregates metrics for tchu-tchu operations.

    Tracks:
    - Message publish/receive counts
    - RPC call latencies
    - Error rates
    - Topic usage statistics
    - Handler performance
    """

    def __init__(self, max_history_size: int = 10000) -> None:
        """
        Initialize the metrics collector.

        Args:
            max_history_size: Maximum number of metrics to keep in memory
        """
        self.max_history_size = max_history_size
        self._metrics: list[MessageMetric] = []
        self._lock = Lock()

        # Aggregated counters
        self._message_counts = Counter()
        self._error_counts = Counter()
        self._topic_counts = Counter()
        self._rpc_latencies = defaultdict(list)

    def record_message_published(
        self,
        topic: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a message publication event."""
        metric = MessageMetric(
            topic=topic,
            event_type="published",
            timestamp=datetime.utcnow(),
            task_id=task_id,
            metadata=metadata or {},
        )
        self._add_metric(metric)

    def record_message_received(
        self,
        topic: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a message reception event."""
        metric = MessageMetric(
            topic=topic,
            event_type="received",
            timestamp=datetime.utcnow(),
            task_id=task_id,
            metadata=metadata or {},
        )
        self._add_metric(metric)

    def record_rpc_call(
        self,
        topic: str,
        execution_time: float,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an RPC call completion event."""
        metric = MessageMetric(
            topic=topic,
            event_type="rpc_call",
            timestamp=datetime.utcnow(),
            execution_time=execution_time,
            task_id=task_id,
            metadata=metadata or {},
        )
        self._add_metric(metric)

    def record_error(
        self,
        topic: str,
        error_type: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an error event."""
        metric = MessageMetric(
            topic=topic,
            event_type="error",
            timestamp=datetime.utcnow(),
            task_id=task_id,
            error_type=error_type,
            metadata=metadata or {},
        )
        self._add_metric(metric)

    def _add_metric(self, metric: MessageMetric) -> None:
        """Add a metric to the collection."""
        with self._lock:
            self._metrics.append(metric)

            # Update counters
            self._message_counts[f"{metric.topic}.{metric.event_type}"] += 1
            self._topic_counts[metric.topic] += 1

            if metric.error_type:
                self._error_counts[f"{metric.topic}.{metric.error_type}"] += 1

            if metric.execution_time is not None:
                self._rpc_latencies[metric.topic].append(metric.execution_time)
                # Keep only recent latencies for memory efficiency
                if len(self._rpc_latencies[metric.topic]) > 1000:
                    self._rpc_latencies[metric.topic] = self._rpc_latencies[
                        metric.topic
                    ][-500:]

            # Trim metrics if we exceed max size
            if len(self._metrics) > self.max_history_size:
                self._metrics = self._metrics[-self.max_history_size :]

    def get_summary(self, time_window: timedelta | None = None) -> dict[str, Any]:
        """
        Get a summary of metrics.

        Args:
            time_window: Optional time window to filter metrics (e.g., last hour)

        Returns:
            Dictionary with metric summaries
        """
        with self._lock:
            metrics = self._metrics

            # Filter by time window if specified
            if time_window:
                cutoff_time = datetime.utcnow() - time_window
                metrics = [m for m in metrics if m.timestamp >= cutoff_time]

            # Calculate summaries
            total_messages = len(metrics)
            messages_by_type = Counter(m.event_type for m in metrics)
            messages_by_topic = Counter(m.topic for m in metrics)
            errors_by_type = Counter(m.error_type for m in metrics if m.error_type)

            # RPC latency statistics
            rpc_metrics = [
                m for m in metrics if m.event_type == "rpc_call" and m.execution_time
            ]
            rpc_latencies = [m.execution_time for m in rpc_metrics]

            rpc_stats = {}
            if rpc_latencies:
                rpc_stats = {
                    "count": len(rpc_latencies),
                    "avg_latency": sum(rpc_latencies) / len(rpc_latencies),
                    "min_latency": min(rpc_latencies),
                    "max_latency": max(rpc_latencies),
                    "p95_latency": self._percentile(rpc_latencies, 95),
                    "p99_latency": self._percentile(rpc_latencies, 99),
                }

            return {
                "total_messages": total_messages,
                "messages_by_type": dict(messages_by_type),
                "messages_by_topic": dict(messages_by_topic),
                "errors_by_type": dict(errors_by_type),
                "rpc_statistics": rpc_stats,
                "time_window": str(time_window) if time_window else "all_time",
                "collection_time": datetime.utcnow().isoformat(),
            }

    def get_topic_stats(
        self, topic: str, time_window: timedelta | None = None
    ) -> dict[str, Any]:
        """
        Get statistics for a specific topic.

        Args:
            topic: Topic name
            time_window: Optional time window to filter metrics

        Returns:
            Dictionary with topic-specific statistics
        """
        with self._lock:
            metrics = [m for m in self._metrics if m.topic == topic]

            # Filter by time window if specified
            if time_window:
                cutoff_time = datetime.utcnow() - time_window
                metrics = [m for m in metrics if m.timestamp >= cutoff_time]

            messages_by_type = Counter(m.event_type for m in metrics)
            errors = [m for m in metrics if m.error_type]
            rpc_calls = [
                m for m in metrics if m.event_type == "rpc_call" and m.execution_time
            ]

            rpc_stats = {}
            if rpc_calls:
                latencies = [m.execution_time for m in rpc_calls]
                rpc_stats = {
                    "count": len(latencies),
                    "avg_latency": sum(latencies) / len(latencies),
                    "min_latency": min(latencies),
                    "max_latency": max(latencies),
                }

            return {
                "topic": topic,
                "total_messages": len(metrics),
                "messages_by_type": dict(messages_by_type),
                "error_count": len(errors),
                "error_rate": len(errors) / len(metrics) if metrics else 0,
                "rpc_statistics": rpc_stats,
                "time_window": str(time_window) if time_window else "all_time",
            }

    def get_recent_errors(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Get recent error events.

        Args:
            limit: Maximum number of errors to return

        Returns:
            List of error event dictionaries
        """
        with self._lock:
            error_metrics = [m for m in self._metrics if m.error_type]
            error_metrics.sort(key=lambda x: x.timestamp, reverse=True)

            return [
                {
                    "topic": m.topic,
                    "error_type": m.error_type,
                    "timestamp": m.timestamp.isoformat(),
                    "task_id": m.task_id,
                    "metadata": m.metadata,
                }
                for m in error_metrics[:limit]
            ]

    def clear_metrics(self) -> None:
        """Clear all collected metrics."""
        with self._lock:
            self._metrics.clear()
            self._message_counts.clear()
            self._error_counts.clear()
            self._topic_counts.clear()
            self._rpc_latencies.clear()

        logger.info("Cleared all metrics")

    def _percentile(self, values: list[float], percentile: int) -> float:
        """Calculate percentile of a list of values."""
        if not values:
            return 0.0

        sorted_values = sorted(values)
        index = int((percentile / 100.0) * len(sorted_values))
        index = min(index, len(sorted_values) - 1)
        return sorted_values[index]


# Global metrics collector instance
_global_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance."""
    return _global_collector
