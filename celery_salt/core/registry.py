"""
Schema registry for CelerySalt.

Provides a centralized schema management system with adapter pattern for
different backends (in-memory, PostgreSQL, cloud API).
"""

from collections import defaultdict
from threading import Lock
from typing import Any

from celery_salt.core.exceptions import SchemaRegistryUnavailableError
from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)


class InMemorySchemaRegistry:
    """
    In-memory schema registry (default implementation).

    Suitable for development and single-service deployments.
    For production multi-service deployments, use PostgreSQL adapter.
    """

    def __init__(self) -> None:
        self._schemas: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._lock = Lock()

    def register_schema(
        self,
        topic: str,
        version: str,
        schema: dict,
        publisher_module: str,
        publisher_class: str,
        mode: str = "broadcast",
        description: str = "",
        response_schema: dict | None = None,
        error_schema: dict | None = None,
    ) -> dict:
        """
        Register a schema.

        Args:
            topic: Event topic
            version: Schema version
            schema: JSON schema dict
            publisher_module: Module where event class is defined
            publisher_class: Name of event class
            mode: "broadcast" or "rpc" (default: "broadcast")
            description: Human-readable description
            response_schema: Optional JSON schema for RPC response
            error_schema: Optional JSON schema for RPC error

        Returns:
            dict with 'created' (bool) and optionally 'existing_schema'
        """
        with self._lock:
            key = f"{topic}:{version}"

            if key in self._schemas:
                existing = self._schemas[key]
                return {
                    "created": False,
                    "existing_schema": existing["schema"],
                }

            self._schemas[key] = {
                "topic": topic,
                "version": version,
                "schema": schema,
                "publisher_module": publisher_module,
                "publisher_class": publisher_class,
                "mode": mode,
                "description": description,
                "response_schema": response_schema,
                "error_schema": error_schema,
            }

            return {"created": True}

    def get_schema(self, topic: str, version: str = "latest") -> dict:
        """Fetch schema from registry."""
        with self._lock:
            if version == "latest":
                # Find latest version
                versions = [
                    k.split(":")[1]
                    for k in self._schemas.keys()
                    if k.startswith(f"{topic}:")
                ]
                if not versions:
                    raise SchemaRegistryUnavailableError(
                        f"No schema found for topic: {topic}"
                    )
                # Simple version comparison (v1, v2, etc.)
                version = max(versions, key=lambda v: int(v[1:]) if v[1:].isdigit() else 0)

            key = f"{topic}:{version}"
            if key not in self._schemas:
                raise SchemaRegistryUnavailableError(
                    f"No schema found for topic: {topic}, version: {version}"
                )

            return self._schemas[key]["schema"]

    def track_subscriber(self, topic: str, handler_name: str) -> None:
        """Track a subscriber (optional, for observability)."""
        # In-memory registry doesn't track subscribers
        pass


# Global registry instance
_global_registry: InMemorySchemaRegistry | None = None


def get_schema_registry() -> InMemorySchemaRegistry:
    """Get the global schema registry instance."""
    global _global_registry

    if _global_registry is None:
        _global_registry = InMemorySchemaRegistry()

    return _global_registry


def set_schema_registry(registry: InMemorySchemaRegistry) -> None:
    """Set a custom schema registry (for testing or PostgreSQL adapter)."""
    global _global_registry
    _global_registry = registry
