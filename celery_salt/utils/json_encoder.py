"""
JSON encoding utilities for handling various Python types in AMQP messaging.

This module provides a centralized JSON encoder that can handle common Python types
that are not natively JSON serializable, such as UUID, datetime, Decimal, etc.
"""

import json
import uuid
import datetime
import decimal
from typing import Any


class MessageJSONEncoder(json.JSONEncoder):
    """
    Custom JSON encoder for AMQP message serialization.

    Handles common Python types that are not natively JSON serializable:
    - UUID objects -> string representation
    - datetime objects -> ISO format string
    - date objects -> ISO format string
    - time objects -> ISO format string
    - Decimal objects -> float (or string for high precision)
    - set objects -> list
    - bytes objects -> base64 encoded string (if needed)
    """

    def default(self, obj: Any) -> Any:
        """
        Convert non-JSON serializable objects to JSON serializable types.

        Args:
            obj: The object to serialize

        Returns:
            JSON serializable representation of the object

        Raises:
            TypeError: If the object type is not supported
        """
        # Handle UUID objects
        if isinstance(obj, uuid.UUID):
            return str(obj)

        # Handle datetime objects
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()

        # Handle date objects
        if isinstance(obj, datetime.date):
            return obj.isoformat()

        # Handle time objects
        if isinstance(obj, datetime.time):
            return obj.isoformat()

        # Handle Decimal objects
        if isinstance(obj, decimal.Decimal):
            # Convert to float for JSON compatibility
            # Note: This may lose precision for very large/precise decimals
            return float(obj)

        # Handle set objects
        if isinstance(obj, set):
            return list(obj)

        # Handle bytes objects (convert to base64 if needed)
        if isinstance(obj, bytes):
            # For simple cases, try to decode as UTF-8
            try:
                return obj.decode("utf-8")
            except UnicodeDecodeError:
                # If not UTF-8, encode as base64
                import base64

                return base64.b64encode(obj).decode("ascii")

        # Let the base class handle the rest
        return super().default(obj)


def dumps_message(obj: Any, **kwargs) -> str:
    """
    Convenience function to serialize objects using the MessageJSONEncoder.

    Args:
        obj: The object to serialize
        **kwargs: Additional arguments to pass to json.dumps

    Returns:
        JSON string representation of the object
    """
    return json.dumps(obj, cls=MessageJSONEncoder, **kwargs)


def loads_message(s: str, **kwargs) -> Any:
    """
    Convenience function to deserialize JSON strings.

    Note: This is just a wrapper around json.loads for consistency.
    Custom deserialization logic can be added here if needed.

    Args:
        s: The JSON string to deserialize
        **kwargs: Additional arguments to pass to json.loads

    Returns:
        The deserialized Python object
    """
    return json.loads(s, **kwargs)
