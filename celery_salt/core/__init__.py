"""Core CelerySalt functionality."""

from celery_salt.core.decorators import event, subscribe
from celery_salt.core.events import SaltEvent
from celery_salt.core.exceptions import (
    CelerySaltError,
    PublishError,
    RPCError,
    SchemaConflictError,
    SchemaRegistryUnavailableError,
    TimeoutError,
)

# Expose response and error decorators via event function
# Usage: @event.response("rpc.topic") or @event.error("rpc.topic")

__all__ = [
    "event",
    "subscribe",
    "SaltEvent",
    "CelerySaltError",
    "SchemaConflictError",
    "SchemaRegistryUnavailableError",
    "RPCError",
    "PublishError",
    "TimeoutError",
]
