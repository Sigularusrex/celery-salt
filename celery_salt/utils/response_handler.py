"""Response handling utilities for tchu-tchu."""

from typing import Any

from celery.result import AsyncResult, EagerResult, GroupResult

from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)


def normalize_rpc_result(obj: Any) -> Any:
    """
    Convert list-of-pairs back to dict when present (serialization artifact).

    Some Celery result backends or serializers store dicts as [[k, v], [k, v], ...].
    This recursively converts that shape back to a plain dict so RPC callers
    receive normal JSON-style objects.

    Args:
        obj: Raw value (possibly list-of-pairs at any nesting level)

    Returns:
        Same structure with any list-of-pairs converted to dict
    """
    if isinstance(obj, list):
        # Heuristic: list of 2-element lists where first element is a string key
        if obj and all(
            isinstance(item, list) and len(item) == 2 and isinstance(item[0], str)
            for item in obj
        ):
            return {k: normalize_rpc_result(v) for k, v in obj}
        return [normalize_rpc_result(item) for item in obj]
    if isinstance(obj, dict):
        return {k: normalize_rpc_result(v) for k, v in obj.items()}
    return obj


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
