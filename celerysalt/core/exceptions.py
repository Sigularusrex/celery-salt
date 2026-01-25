"""Core exceptions for CelerySalt."""


class CelerySaltError(Exception):
    """Base exception class for all CelerySalt errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SchemaConflictError(CelerySaltError):
    """Raised when a schema conflict is detected during registration."""

    def __init__(self, topic: str, version: str, message: str | None = None) -> None:
        if message is None:
            message = f"Schema conflict for {topic} (v{version})"
        super().__init__(message, {"topic": topic, "version": version})
        self.topic = topic
        self.version = version


class SchemaRegistryUnavailableError(CelerySaltError):
    """Raised when the schema registry is unavailable."""

    pass


class PublishError(CelerySaltError):
    """Raised when there's an issue publishing a message."""

    pass


class TimeoutError(CelerySaltError):
    """Raised when an RPC call times out."""

    pass


class RPCError(CelerySaltError):
    """
    Exception for RPC handler errors that return responses instead of raising.

    When raised in an RPC handler, this exception is caught and converted
    to a response dict that's sent back to the caller (not an exception).

    Usage:
        raise RPCError(
            error_code="USER_NOT_FOUND",
            error_message="User does not have access",
            details={"user_id": 123}
        )
    """

    def __init__(
        self,
        error_code: str | None = None,
        error_message: str | None = None,
        message: str | None = None,
        code: str | None = None,
        details: dict | None = None,
    ) -> None:
        # Support both new API (error_code, error_message) and legacy API (code, message)
        if error_code is None and code is not None:
            error_code = code
        if error_message is None and message is not None:
            error_message = message

        if error_code is None:
            error_code = "RPC_ERROR"
        if error_message is None:
            error_message = "RPC error occurred"

        super().__init__(error_message, details)
        self.error_code = error_code
        self.error_message = error_message
        # Legacy aliases for backward compatibility
        self.code = error_code
        self.message = error_message

    def to_response_dict(self) -> dict:
        """Convert exception to a response dictionary."""
        return {
            "error_code": self.error_code,
            "error_message": self.error_message,
            "details": self.details,
        }
