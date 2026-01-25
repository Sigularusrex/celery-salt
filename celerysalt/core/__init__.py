"""Core CelerySalt functionality."""

from celerysalt.core.decorators import event, subscribe
from celerysalt.core.exceptions import (
    CelerySaltError,
    SchemaConflictError,
    SchemaRegistryUnavailableError,
    RPCError,
    PublishError,
    TimeoutError,
)

# Expose response and error decorators via event function
# Usage: @event.response("rpc.topic") or @event.error("rpc.topic")
from celerysalt.core.decorators import response, error

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
