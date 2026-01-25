"""Core CelerySalt functionality."""

from celery_salt.core.decorators import event, subscribe
from celery_salt.core.exceptions import (
    CelerySaltError,
    SchemaConflictError,
    SchemaRegistryUnavailableError,
    RPCError,
    PublishError,
    TimeoutError,
)

# Expose response and error decorators via event function
# Usage: @event.response("rpc.topic") or @event.error("rpc.topic")
from celery_salt.core.decorators import response, error

__all__ = [
    "event",
    "subscribe",
    "CelerySaltError",
    "SchemaConflictError",
    "SchemaRegistryUnavailableError",
    "RPCError",
    "PublishError",
    "TimeoutError",
]
