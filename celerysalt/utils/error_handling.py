"""Error handling utilities for CelerySalt (backward compatibility)."""

from typing import Optional

# Re-export from core exceptions for backward compatibility
from celerysalt.core.exceptions import (
    CelerySaltError,
    PublishError,
    TimeoutError,
    RPCError,
)

# Legacy aliases for backward compatibility
TchuError = CelerySaltError
TchuRPCException = RPCError


class ConnectionError(CelerySaltError):
    """Raised when there's an issue with Celery broker connection."""

    pass


class SerializationError(CelerySaltError):
    """Raised when there's an issue with message serialization/deserialization."""

    pass


class SubscriptionError(CelerySaltError):
    """Raised when there's an issue with topic subscription."""

    pass


# TchuRPCException is aliased to RPCError above for backward compatibility
# The RPCError class in core.exceptions has the same interface
