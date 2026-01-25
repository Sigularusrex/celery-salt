"""
Handler registry for routing events to handlers.

This is separate from the schema registry - it tracks which handlers
are registered for which routing keys.
"""

import re
from collections import defaultdict
from collections.abc import Callable
from threading import Lock
from typing import Any

from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)


class HandlerRegistry:
    """Registry for managing routing key-to-handler mappings."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._pattern_handlers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = Lock()
        self._handler_counter = 0

    def register_handler(
        self,
        routing_key: str,
        handler: Callable,
        name: str | None = None,
        handler_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Register a handler for a routing key."""
        with self._lock:
            self._handler_counter += 1

            if handler_id is None:
                handler_id = f"handler_{self._handler_counter}"

            if name is None:
                name = getattr(handler, "__name__", "handler")

            handler_info = {
                "id": handler_id,
                "name": name,
                "function": handler,
                "routing_key": routing_key,
                "metadata": metadata or {},
            }

            # Check if routing_key contains wildcards
            if "*" in routing_key or "#" in routing_key:
                self._pattern_handlers[routing_key].append(handler_info)
                logger.info(
                    f"Registered pattern handler '{name}' for routing key pattern '{routing_key}'"
                )
            else:
                self._handlers[routing_key].append(handler_info)
                logger.info(f"Registered handler '{name}' for routing key '{routing_key}'")

            return handler_info["id"]

    def get_handlers(self, routing_key: str) -> list[dict[str, Any]]:
        """Get all handlers for a specific routing key."""
        with self._lock:
            handlers = []

            # Add exact match handlers
            handlers.extend(self._handlers.get(routing_key, []))

            # Add pattern match handlers
            for pattern, pattern_handlers in self._pattern_handlers.items():
                if self._matches_pattern(routing_key, pattern):
                    handlers.extend(pattern_handlers)

            return handlers

    def get_all_routing_keys(self) -> list[str]:
        """Get all registered routing keys and patterns."""
        with self._lock:
            all_keys = list(self._handlers.keys()) + list(self._pattern_handlers.keys())
            return list(set(all_keys))

    def get_handler_count(self, routing_key: str | None = None) -> int:
        """Get count of handlers."""
        with self._lock:
            if routing_key is None:
                # Count all handlers
                total = sum(len(handlers) for handlers in self._handlers.values())
                total += sum(len(handlers) for handlers in self._pattern_handlers.values())
                return total
            else:
                # Count handlers for specific routing key
                return len(self.get_handlers(routing_key))

    def _matches_pattern(self, routing_key: str, pattern: str) -> bool:
        """Check if a routing key matches a wildcard pattern."""
        # Convert wildcard pattern to regex
        # * matches any sequence of characters (but not dots)
        # # matches zero or more words (separated by dots)
        regex_pattern = pattern.replace(".", r"\.").replace("*", "[^.]*").replace("#", ".*")
        regex_pattern = f"^{regex_pattern}$"

        try:
            return bool(re.match(regex_pattern, routing_key))
        except re.error:
            logger.warning(f"Invalid pattern '{pattern}', treating as exact match")
            return routing_key == pattern


# Global handler registry instance
_global_handler_registry: HandlerRegistry | None = None


def get_handler_registry() -> HandlerRegistry:
    """Get the global handler registry instance."""
    global _global_handler_registry

    if _global_handler_registry is None:
        _global_handler_registry = HandlerRegistry()

    return _global_handler_registry
