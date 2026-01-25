"""Django signal handlers for tchu-tchu integration."""

from typing import Any

from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)

try:
    import django.db.models  # noqa: F401

    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False


def create_signal_handler(
    topic: str,
    client: Any,
    include_fields: list | None = None,
    exclude_fields: list | None = None,
    condition: callable | None = None,
):
    """
    Create a signal handler for Django model events.

    Args:
        topic: Topic to publish to
        client: TchuClient instance
        include_fields: Fields to include in payload
        exclude_fields: Fields to exclude from payload
        condition: Optional condition function

    Returns:
        Signal handler function
    """

    def signal_handler(sender, instance, **kwargs):
        """Generic signal handler for model events."""
        try:
            # Check condition if provided
            if condition and not condition(instance, kwargs):
                return

            # Extract model data
            data = extract_model_data(
                instance, include_fields=include_fields, exclude_fields=exclude_fields
            )

            # Add signal metadata
            data["_signal"] = {
                "sender": sender.__name__,
                "signal_type": kwargs.get("signal_type", "unknown"),
            }

            # Publish event
            client.publish(topic, data)

            logger.info(
                f"Published signal event to topic '{topic}'",
                extra={"topic": topic, "model": sender.__name__, "pk": instance.pk},
            )

        except Exception as e:
            logger.error(
                f"Failed to handle signal for {sender.__name__}: {e}",
                extra={"topic": topic, "model": sender.__name__},
                exc_info=True,
            )

    return signal_handler


def extract_model_data(
    instance: Any,
    include_fields: list | None = None,
    exclude_fields: list | None = None,
) -> dict[str, Any]:
    """
    Extract data from a Django model instance.

    Args:
        instance: Django model instance
        include_fields: Fields to include
        exclude_fields: Fields to exclude

    Returns:
        Dictionary with model data
    """
    if not DJANGO_AVAILABLE:
        return {"error": "Django not available"}

    data = {}

    try:
        for field in instance._meta.fields:
            field_name = field.name

            # Skip excluded fields
            if exclude_fields and field_name in exclude_fields:
                continue

            # Include only specified fields if include_fields is set
            if include_fields and field_name not in include_fields:
                continue

            try:
                value = getattr(instance, field_name)

                # Handle special field types
                if hasattr(value, "isoformat"):  # datetime/date/time
                    data[field_name] = value.isoformat()
                elif hasattr(value, "__str__"):
                    data[field_name] = str(value) if value is not None else None
                else:
                    data[field_name] = value

            except Exception as e:
                logger.warning(f"Failed to get value for field '{field_name}': {e}")
                continue

        # Add metadata
        data["_meta"] = {
            "app_label": instance._meta.app_label,
            "model_name": instance._meta.model_name,
            "pk": instance.pk,
        }

    except Exception as e:
        logger.error(f"Failed to extract model data: {e}", exc_info=True)
        data = {"error": f"Failed to extract model data: {e}"}

    return data
