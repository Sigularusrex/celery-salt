"""Django model decorators for automatic event publishing."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from celery_salt.logging.handlers import get_logger

if TYPE_CHECKING:
    from celery_salt.integrations.client import TchuClient as EventClient

logger = get_logger(__name__)

try:
    from django.db import models
    from django.db.models.signals import post_delete, post_save

    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False
    logger.warning("Django not available. Django integration features disabled.")


def auto_publish(
    topic_prefix: str | None = None,
    include_fields: list[str] | None = None,
    exclude_fields: list[str] | None = None,
    publish_on: list[str] | None = None,
    client: "EventClient | None" = None,
    condition: Callable | None = None,
    event_classes: dict[str, type] | None = None,
    payload_provider: Callable[..., dict[str, Any] | None] | None = None,
):
    """
    Decorator for Django models that automatically publishes events on save/delete.

    Two modes:
        1. Raw mode (without event_classes): Publishes raw dicts to generated topics
        2. Event class + payload_provider: For SaltEvent subclasses. Provider builds
           full payload; returns None to skip.

    For SaltEvent subclasses (e.g. with AuthorizedEventSchema): use payload_provider
    to build the complete event payload (model fields + auth) and return None when
    context is missing (imports, bulk ops). See CONTEXT_PROVIDER_GUIDE.md.

    Args:
        include_fields: List of fields to include (default: all fields)
        exclude_fields: List of fields to exclude
        publish_on: Events to publish ["created", "updated", "deleted"] (auto-inferred if using event_classes)

        # Event class mode:
        event_classes: Dict mapping event types to event classes
                      Example: {"created": ProductCreatedEvent, "updated": ProductUpdatedEvent}
        payload_provider: (instance, event_type) -> dict | None. Builds full event payload.
                         Return None to skip. Required when using event_classes.

        # Raw mode:
        topic_prefix: Prefix for topics (default: app_label.model_name)
        client: Optional event client (uses default if None)

        # Both modes:
        condition: Function to conditionally publish: (instance, event_type) -> bool

    Example:
        def get_product_payload(instance, event_type):
            if not getattr(instance, "_event_request", None):
                return None
            auth = authorize_event({"request": instance._event_request})
            if not auth.get("user"):
                return None
            return {**_product_event_payload(instance), **auth}

        @auto_publish(
            event_classes={"created": ProductCreatedEvent, "updated": ProductUpdatedEvent},
            payload_provider=get_product_payload,
        )
        class Product(models.Model):
            pass
    """
    if not DJANGO_AVAILABLE:

        def no_op_decorator(cls):
            logger.warning(
                f"Django not available. Skipping auto_publish decorator for {cls.__name__}"
            )
            return cls

        return no_op_decorator

    def decorator(model_class):
        if not issubclass(model_class, models.Model):
            raise ValueError("auto_publish can only be applied to Django Model classes")

        # Get model metadata
        app_label = model_class._meta.app_label
        model_name = model_class._meta.model_name

        # Determine which events to publish
        if event_classes:
            # Validate event_classes keys
            valid_event_types = {"created", "updated", "deleted"}
            invalid_types = set(event_classes.keys()) - valid_event_types
            if invalid_types:
                raise ValueError(
                    f"Invalid event types in event_classes: {invalid_types}. "
                    f"Valid types are: {valid_event_types}"
                )
            if not payload_provider:
                raise ValueError(
                    "payload_provider is required when using event_classes. "
                    "SaltEvent subclasses need the full payload at init."
                )
            # Auto-infer from event_classes keys
            events_to_publish = publish_on or list(event_classes.keys())

            # Not needed for event class mode
            base_topic = None
            event_client = None
        else:
            # Raw event mode - need topic prefix and optional client
            events_to_publish = publish_on or ["created", "updated", "deleted"]

            # Generate topic prefix
            if topic_prefix is None:
                base_topic = f"{app_label}.{model_name}"
            else:
                base_topic = f"{topic_prefix}.{model_name}"

            if client is not None:
                event_client = client
            else:
                from celery_salt.integrations.client import TchuClient as EventClient

                event_client = EventClient()

        def get_model_data(
            instance: models.Model, fields_changed: list[str] | None = None
        ) -> dict[str, Any]:
            """Extract model data for event payload."""
            data = {}

            # Get all field values
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
                "app_label": app_label,
                "model_name": model_name,
                "pk": instance.pk,
            }

            if fields_changed:
                data["_meta"]["fields_changed"] = fields_changed

            return data

        def should_publish_event(instance: models.Model, event_type: str) -> bool:
            """Check if event should be published based on condition."""
            if event_type not in events_to_publish:
                return False

            if condition and not condition(instance, event_type):
                return False

            return True

        def publish_event(
            instance: models.Model,
            event_type: str,
            fields_changed: list[str] | None = None,
        ):
            """Publish an event for the model instance."""
            if not should_publish_event(instance, event_type):
                return

            try:
                if event_classes and event_type in event_classes:
                    event_class = event_classes[event_type]
                    try:
                        payload = payload_provider(instance, event_type)
                    except Exception as e:
                        logger.warning(
                            f"Payload provider failed: {e}. Skipping publish.",
                            extra={"model_pk": instance.pk},
                            exc_info=True,
                        )
                        return
                    if payload is None:
                        return  # Provider decided to skip
                    event_instance = event_class(**payload)
                    event_instance.publish()
                else:
                    data = get_model_data(instance, fields_changed)
                    topic = f"{base_topic}.{event_type}"
                    event_client.publish(topic, data)

            except Exception as e:
                logger.error(
                    f"Failed to publish {event_type} event for {model_class.__name__}: {e}",
                    extra={"model_pk": instance.pk},
                    exc_info=True,
                )

        def handle_post_save(sender, instance, created, **kwargs):
            """Handle post_save signal."""
            if created and "created" in events_to_publish:
                publish_event(instance, "created")
            elif not created and "updated" in events_to_publish:
                # Try to determine which fields changed
                fields_changed = None
                if hasattr(instance, "_state") and hasattr(
                    instance._state, "fields_cache"
                ):
                    # This is a best-effort attempt to detect changed fields
                    # In practice, you might want to use django-model-utils or similar
                    pass

                publish_event(instance, "updated", fields_changed)

        def handle_post_delete(sender, instance, **kwargs):
            """Handle post_delete signal."""
            if "deleted" in events_to_publish:
                publish_event(instance, "deleted")

        # Connect signals
        if "created" in events_to_publish or "updated" in events_to_publish:
            post_save.connect(handle_post_save, sender=model_class, weak=False)

        if "deleted" in events_to_publish:
            post_delete.connect(handle_post_delete, sender=model_class, weak=False)

        # Add metadata to the model class
        model_class._celerysalt_auto_publish_config = {
            "topic_prefix": topic_prefix,
            "base_topic": base_topic,
            "include_fields": include_fields,
            "exclude_fields": exclude_fields,
            "publish_on": events_to_publish,
            "client": event_client if not event_classes else None,
            "condition": condition,
            "event_classes": event_classes,
            "payload_provider": payload_provider,
        }

        # Log configuration
        if event_classes:
            event_list = ", ".join(event_classes.keys())
            logger.debug(
                f"Auto-publish: {model_class.__name__} -> events: {event_list}"
            )
        else:
            logger.debug(
                f"Auto-publish: {model_class.__name__} -> topic: {base_topic}.*"
            )

        return model_class

    return decorator


def get_auto_publish_config(model_class) -> dict[str, Any] | None:
    """
    Get the auto-publish configuration for a model class.

    Args:
        model_class: Django model class

    Returns:
        Configuration dictionary or None if not configured
    """
    return getattr(model_class, "_celerysalt_auto_publish_config", None)
