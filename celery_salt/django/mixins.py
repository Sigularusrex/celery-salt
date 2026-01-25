"""Django model mixins for tchu-tchu integration."""

from typing import Any

from celery_salt.integrations.client import TchuClient
from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)

try:
    from django.db import models

    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False


if DJANGO_AVAILABLE:

    class EventPublishingMixin(models.Model):
        """
        Mixin for Django models that provides event publishing capabilities.

        Usage:
            class MyModel(EventPublishingMixin, models.Model):
                name = models.CharField(max_length=100)

                class Meta:
                    tchu_topic_prefix = "myapp.mymodel"
                    tchu_publish_on = ["created", "updated"]
        """

        class Meta:
            abstract = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._tchu_client = None
            self._original_values = {}

            # Store original values for change detection
            if self.pk:
                self._store_original_values()

        @property
        def tchu_client(self) -> TchuClient:
            """Get or create TchuClient instance."""
            if self._tchu_client is None:
                self._tchu_client = TchuClient()
            return self._tchu_client

        def _store_original_values(self):
            """Store original field values for change detection."""
            for field in self._meta.fields:
                try:
                    value = getattr(self, field.name)
                    self._original_values[field.name] = value
                except Exception:
                    pass

        def _get_changed_fields(self) -> list[str]:
            """Get list of fields that have changed."""
            changed_fields = []

            for field in self._meta.fields:
                field_name = field.name
                try:
                    current_value = getattr(self, field_name)
                    original_value = self._original_values.get(field_name)

                    if current_value != original_value:
                        changed_fields.append(field_name)
                except Exception:
                    pass

            return changed_fields

        def _get_topic_config(self) -> dict[str, Any]:
            """Get topic configuration from Meta class."""
            meta = getattr(self, "Meta", None)

            return {
                "topic_prefix": getattr(meta, "tchu_topic_prefix", None),
                "publish_on": getattr(
                    meta, "tchu_publish_on", ["created", "updated", "deleted"]
                ),
                "include_fields": getattr(meta, "tchu_include_fields", None),
                "exclude_fields": getattr(meta, "tchu_exclude_fields", None),
            }

        def _get_model_data(
            self, fields_changed: list[str] | None = None
        ) -> dict[str, Any]:
            """Extract model data for event payload."""
            config = self._get_topic_config()
            include_fields = config["include_fields"]
            exclude_fields = config["exclude_fields"]

            data = {}

            for field in self._meta.fields:
                field_name = field.name

                # Skip excluded fields
                if exclude_fields and field_name in exclude_fields:
                    continue

                # Include only specified fields if include_fields is set
                if include_fields and field_name not in include_fields:
                    continue

                try:
                    value = getattr(self, field_name)

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
                "app_label": self._meta.app_label,
                "model_name": self._meta.model_name,
                "pk": self.pk,
            }

            if fields_changed:
                data["_meta"]["fields_changed"] = fields_changed

            return data

        def publish_event(self, event_type: str, data: dict[str, Any] | None = None):
            """
            Manually publish an event for this model instance.

            Args:
                event_type: Type of event (e.g., "created", "updated", "deleted")
                data: Optional custom data (uses model data if None)
            """
            try:
                config = self._get_topic_config()
                topic_prefix = config["topic_prefix"]

                if topic_prefix is None:
                    topic_prefix = f"{self._meta.app_label}.{self._meta.model_name}"

                topic = f"{topic_prefix}.{event_type}"

                if data is None:
                    data = self._get_model_data()

                self.tchu_client.publish(topic, data)

                logger.info(
                    f"Published {event_type} event for {self.__class__.__name__}",
                    extra={"topic": topic, "model_pk": self.pk},
                )

            except Exception as e:
                logger.error(
                    f"Failed to publish {event_type} event for {self.__class__.__name__}: {e}",
                    extra={"model_pk": self.pk},
                    exc_info=True,
                )

        def save(self, *args, **kwargs):
            """Override save to publish events."""
            config = self._get_topic_config()
            publish_on = config["publish_on"]

            is_creating = self.pk is None
            changed_fields = [] if is_creating else self._get_changed_fields()

            # Call original save
            super().save(*args, **kwargs)

            # Publish events
            try:
                if is_creating and "created" in publish_on:
                    self.publish_event("created")
                elif not is_creating and "updated" in publish_on and changed_fields:
                    data = self._get_model_data(changed_fields)
                    self.publish_event("updated", data)

                # Update original values for next change detection
                self._store_original_values()

            except Exception as e:
                logger.error(f"Failed to publish save event: {e}", exc_info=True)

        def delete(self, *args, **kwargs):
            """Override delete to publish events."""
            config = self._get_topic_config()
            publish_on = config["publish_on"]

            # Store data before deletion
            if "deleted" in publish_on:
                data = self._get_model_data()

            # Call original delete
            result = super().delete(*args, **kwargs)

            # Publish delete event
            try:
                if "deleted" in publish_on:
                    self.publish_event("deleted", data)
            except Exception as e:
                logger.error(f"Failed to publish delete event: {e}", exc_info=True)

            return result

else:
    # Dummy class when Django is not available
    class EventPublishingMixin:
        """Dummy mixin when Django is not available."""

        def __init__(self, *args, **kwargs):
            logger.warning("Django not available. EventPublishingMixin is disabled.")
            super().__init__(*args, **kwargs)
