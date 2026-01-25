"""Django model decorators for automatic event publishing."""

from collections.abc import Callable
from typing import Any

from celery_salt.integrations.client import TchuClient
from celery_salt.logging.handlers import get_logger

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
    client: TchuClient | None = None,
    condition: Callable | None = None,
    event_classes: dict[str, type] | None = None,
    context_provider: Callable | None = None,
):
    """
    Decorator for Django models that automatically publishes events on save/delete.

    Two modes:
        1. Raw mode (without event_classes): Publishes raw dicts to generated topics
        2. Event class mode (with event_classes): Uses event classes with validation (legacy compatibility)

    IMPORTANT: If your serializers use self.context, you MUST provide a context_provider.
    See CONTEXT_PROVIDER_GUIDE.md for patterns.

    Args:
        include_fields: List of fields to include (default: all fields)
        exclude_fields: List of fields to exclude
        publish_on: Events to publish ["created", "updated", "deleted"] (auto-inferred if using event_classes)

        # Event class mode (recommended):
        event_classes: Dict mapping event types to event classes (legacy compatibility)
                      Example: {"created": MyCreatedEvent, "updated": MyUpdatedEvent}
        context_provider: Function to extract context from instance for serializers
                         Signature: (instance, event_type) -> Dict[str, Any]

        # Raw mode (legacy):
        topic_prefix: Prefix for topics (default: app_label.model_name)
        client: TchuClient instance (default: creates new)

        # Both modes:
        condition: Function to conditionally publish: (instance, event_type) -> bool

    Example (event class mode):
        def get_context(instance, event_type):
            return {"user_id": instance._event_user_id}

        @auto_publish(
            event_classes={"created": RiskCreatedEvent, "updated": RiskUpdatedEvent},
            context_provider=get_context
        )
        class Risk(models.Model):
            pass

    Example (raw mode):
        @auto_publish(
            topic_prefix="pulse.compliance",
            include_fields=["id", "status"],
            publish_on=["created", "updated"]
        )
        class Risk(models.Model):
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
            # Auto-infer from event_classes keys
            events_to_publish = publish_on or list(event_classes.keys())

            # Not needed for event class mode
            base_topic = None
            event_client = None
        else:
            # Raw event mode - need topic and client
            events_to_publish = publish_on or ["created", "updated", "deleted"]

            # Generate topic prefix
            if topic_prefix is None:
                base_topic = f"{app_label}.{model_name}"
            else:
                base_topic = f"{topic_prefix}.{model_name}"

            # Create client
            event_client = client or TchuClient()

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
                data = get_model_data(instance, fields_changed)

                if event_classes and event_type in event_classes:
                    # Event class mode: use event class with its topic and serializers
                    event_class = event_classes[event_type]
                    event_instance = event_class()

                    # Get context if provider available
                    context = None
                    if context_provider:
                        try:
                            context = context_provider(instance, event_type)
                        except Exception as ctx_err:
                            logger.warning(
                                f"Context provider failed: {ctx_err}. Publishing without context.",
                                extra={"model_pk": instance.pk},
                                exc_info=True,
                            )

                    # Serialize with validation and publish
                    event_instance.serialize_request(data, context=context)
                    event_instance.publish()

                    logger.info(
                        f"Published {event_type} event for {model_class.__name__}",
                        extra={"topic": event_instance.topic, "model_pk": instance.pk},
                    )
                else:
                    # Raw mode: publish directly with generated topic
                    topic = f"{base_topic}.{event_type}"
                    event_client.publish(topic, data)

                    logger.info(
                        f"Published {event_type} event for {model_class.__name__}",
                        extra={"topic": topic, "model_pk": instance.pk},
                    )

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
        model_class._tchu_auto_publish_config = {
            "topic_prefix": topic_prefix,
            "base_topic": base_topic,
            "include_fields": include_fields,
            "exclude_fields": exclude_fields,
            "publish_on": events_to_publish,
            "client": event_client,
            "condition": condition,
            "event_classes": event_classes,
            "context_provider": context_provider,
        }

        # Log configuration
        if event_classes:
            event_list = ", ".join(event_classes.keys())
            context_note = " (with context)" if context_provider else ""
            logger.info(
                f"Auto-publish: {model_class.__name__} -> events: {event_list}{context_note}"
            )
        else:
            logger.info(
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
    return getattr(model_class, "_tchu_auto_publish_config", None)
