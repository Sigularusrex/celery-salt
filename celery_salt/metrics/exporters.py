"""Metrics exporters for tchu-tchu."""

import json
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from celery_salt.logging.handlers import get_logger
from celery_salt.metrics.collectors import MetricsCollector, get_metrics_collector

logger = get_logger(__name__)


class MetricsExporter(ABC):
    """Base class for metrics exporters."""

    @abstractmethod
    def export(self, metrics: dict[str, Any]) -> None:
        """Export metrics data."""
        pass


class JSONExporter(MetricsExporter):
    """Export metrics as JSON to a file or stdout."""

    def __init__(self, file_path: str | None = None) -> None:
        """
        Initialize the JSON exporter.

        Args:
            file_path: Optional file path to write JSON (prints to stdout if None)
        """
        self.file_path = file_path

    def export(self, metrics: dict[str, Any]) -> None:
        """Export metrics as JSON."""
        try:
            json_data = json.dumps(metrics, indent=2, default=str)

            if self.file_path:
                with open(self.file_path, "w") as f:
                    f.write(json_data)
                logger.info(f"Exported metrics to {self.file_path}")
            else:
                print(json_data)

        except Exception as e:
            logger.error(f"Failed to export metrics as JSON: {e}", exc_info=True)


class PrometheusExporter(MetricsExporter):
    """Export metrics in Prometheus format."""

    def __init__(self, file_path: str | None = None) -> None:
        """
        Initialize the Prometheus exporter.

        Args:
            file_path: Optional file path to write metrics (prints to stdout if None)
        """
        self.file_path = file_path

    def export(self, metrics: dict[str, Any]) -> None:
        """Export metrics in Prometheus format."""
        try:
            prometheus_data = self._convert_to_prometheus(metrics)

            if self.file_path:
                with open(self.file_path, "w") as f:
                    f.write(prometheus_data)
                logger.info(f"Exported Prometheus metrics to {self.file_path}")
            else:
                print(prometheus_data)

        except Exception as e:
            logger.error(f"Failed to export Prometheus metrics: {e}", exc_info=True)

    def _convert_to_prometheus(self, metrics: dict[str, Any]) -> str:
        """Convert metrics to Prometheus format."""
        lines = []

        # Total messages
        lines.append("# HELP tchu_messages_total Total number of messages processed")
        lines.append("# TYPE tchu_messages_total counter")
        lines.append(f"tchu_messages_total {metrics.get('total_messages', 0)}")
        lines.append("")

        # Messages by type
        lines.append("# HELP tchu_messages_by_type_total Messages by event type")
        lines.append("# TYPE tchu_messages_by_type_total counter")
        for event_type, count in metrics.get("messages_by_type", {}).items():
            lines.append(f'tchu_messages_by_type_total{{type="{event_type}"}} {count}')
        lines.append("")

        # Messages by topic
        lines.append("# HELP tchu_messages_by_topic_total Messages by topic")
        lines.append("# TYPE tchu_messages_by_topic_total counter")
        for topic, count in metrics.get("messages_by_topic", {}).items():
            # Sanitize topic name for Prometheus
            sanitized_topic = topic.replace(".", "_").replace("-", "_")
            lines.append(
                f'tchu_messages_by_topic_total{{topic="{sanitized_topic}"}} {count}'
            )
        lines.append("")

        # RPC statistics
        rpc_stats = metrics.get("rpc_statistics", {})
        if rpc_stats:
            lines.append("# HELP tchu_rpc_calls_total Total RPC calls")
            lines.append("# TYPE tchu_rpc_calls_total counter")
            lines.append(f"tchu_rpc_calls_total {rpc_stats.get('count', 0)}")
            lines.append("")

            lines.append("# HELP tchu_rpc_latency_seconds RPC call latency")
            lines.append("# TYPE tchu_rpc_latency_seconds histogram")

            avg_latency = rpc_stats.get("avg_latency", 0)
            min_latency = rpc_stats.get("min_latency", 0)
            max_latency = rpc_stats.get("max_latency", 0)
            p95_latency = rpc_stats.get("p95_latency", 0)
            p99_latency = rpc_stats.get("p99_latency", 0)

            lines.append(f"tchu_rpc_latency_seconds_avg {avg_latency}")
            lines.append(f"tchu_rpc_latency_seconds_min {min_latency}")
            lines.append(f"tchu_rpc_latency_seconds_max {max_latency}")
            lines.append(f"tchu_rpc_latency_seconds_p95 {p95_latency}")
            lines.append(f"tchu_rpc_latency_seconds_p99 {p99_latency}")
            lines.append("")

        # Errors by type
        lines.append("# HELP tchu_errors_by_type_total Errors by type")
        lines.append("# TYPE tchu_errors_by_type_total counter")
        for error_type, count in metrics.get("errors_by_type", {}).items():
            if error_type:  # Skip None error types
                sanitized_error = error_type.replace(".", "_").replace("-", "_")
                lines.append(
                    f'tchu_errors_by_type_total{{error_type="{sanitized_error}"}} {count}'
                )
        lines.append("")

        return "\n".join(lines)


class LogExporter(MetricsExporter):
    """Export metrics to the logging system."""

    def __init__(self, log_level: str = "INFO") -> None:
        """
        Initialize the log exporter.

        Args:
            log_level: Log level to use for metrics output
        """
        self.log_level = log_level.upper()

    def export(self, metrics: dict[str, Any]) -> None:
        """Export metrics to logs."""
        try:
            log_func = getattr(logger, self.log_level.lower(), logger.info)
            log_func("Metrics summary", extra={"metrics": metrics})

        except Exception as e:
            logger.error(f"Failed to export metrics to logs: {e}", exc_info=True)


class MetricsReporter:
    """
    Utility class for collecting and exporting metrics.

    Provides convenient methods for generating and exporting metrics reports.
    """

    def __init__(
        self,
        collector: MetricsCollector | None = None,
        exporters: list | None = None,
    ) -> None:
        """
        Initialize the metrics reporter.

        Args:
            collector: Optional metrics collector (uses global if None)
            exporters: Optional list of exporters (uses JSON exporter if None)
        """
        self.collector = collector or get_metrics_collector()
        self.exporters = exporters or [JSONExporter()]

    def generate_report(
        self, time_window: timedelta | None = None, include_errors: bool = True
    ) -> dict[str, Any]:
        """
        Generate a comprehensive metrics report.

        Args:
            time_window: Optional time window for metrics
            include_errors: Whether to include recent errors in the report

        Returns:
            Dictionary with comprehensive metrics
        """
        report = self.collector.get_summary(time_window)

        if include_errors:
            report["recent_errors"] = self.collector.get_recent_errors()

        return report

    def export_report(
        self, time_window: timedelta | None = None, include_errors: bool = True
    ) -> None:
        """
        Generate and export a metrics report using all configured exporters.

        Args:
            time_window: Optional time window for metrics
            include_errors: Whether to include recent errors in the report
        """
        report = self.generate_report(time_window, include_errors)

        for exporter in self.exporters:
            try:
                exporter.export(report)
            except Exception as e:
                logger.error(
                    f"Failed to export with {type(exporter).__name__}: {e}",
                    exc_info=True,
                )

    def get_topic_report(
        self, topic: str, time_window: timedelta | None = None
    ) -> dict[str, Any]:
        """
        Generate a report for a specific topic.

        Args:
            topic: Topic name
            time_window: Optional time window for metrics

        Returns:
            Dictionary with topic-specific metrics
        """
        return self.collector.get_topic_stats(topic, time_window)
