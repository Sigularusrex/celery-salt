"""Response handling utilities for tchu-tchu."""

from typing import Any

from celery.result import AsyncResult, EagerResult, GroupResult

from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)


def serialize_celery_result(
    result: GroupResult | AsyncResult | EagerResult | Any,
) -> dict[str, Any] | Any:
    """
    Serialize Celery result objects to a JSON-compatible dictionary.

    This function matches the behavior of your existing _serialize_celery_result()
    function to maintain compatibility with your current RPC response patterns.

    Args:
        result: The Celery result object to serialize

    Returns:
        A JSON-serializable representation of the result
    """
    try:
        if isinstance(result, GroupResult):
            # Return only the first result from the GroupResult
            if len(result) > 0:
                return serialize_celery_result(result[0])
            return None

        elif isinstance(result, AsyncResult | EagerResult):
            return {
                "id": result.id
                if isinstance(result, AsyncResult)
                else getattr(result, "task_id", None),
                "status": result.status,
                "result": result.result,
            }

        # For any other type, return as-is
        return result

    except Exception as e:
        logger.error(f"Error serializing Celery result: {e}", exc_info=True)
        # Return a safe fallback
        return {
            "error": "Failed to serialize result",
            "error_type": type(e).__name__,
            "original_type": type(result).__name__,
        }
