"""
CelerySalt: Event-driven architecture library for Python.

Extends Celery with event publishing/subscribing patterns, schema validation,
and automatic retries while maintaining the familiar Celery developer experience.
"""

from celery_salt.core import RPCError, event, subscribe
from celery_salt.core.events import SaltEvent
from celery_salt.integrations.dispatcher import (
    create_topic_dispatcher,
    get_subscribed_routing_keys,
)
from celery_salt.version import __version__

# Protocol compatibility: Keep exchange name for backward compatibility
DEFAULT_EXCHANGE_NAME = "tchu_events"

__all__ = [
    "event",
    "subscribe",
    "SaltEvent",
    "RPCError",
    "create_topic_dispatcher",
    "get_subscribed_routing_keys",
    "DEFAULT_EXCHANGE_NAME",
    "__version__",
]
