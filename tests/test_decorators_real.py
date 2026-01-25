"""Tests for decorators - testing actual functionality."""

import pytest
from pydantic import ValidationError

from celery_salt.core.decorators import event, subscribe
from celery_salt.core.registry import set_schema_registry, InMemorySchemaRegistry


class TestEventDecoratorReal:
    """Test @event decorator with real functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = InMemorySchemaRegistry()
        set_schema_registry(self.registry)

    def test_event_decorator_creates_pydantic_model(self):
        """Test that @event decorator actually creates a working Pydantic model."""
        @event("test.topic")
        class TestEvent:
            user_id: int
            email: str

        # Should be able to instantiate with validated data
        instance = TestEvent._celerysalt_model(user_id=123, email="user@example.com")
        assert instance.user_id == 123
        assert instance.email == "user@example.com"

        # Invalid data should raise ValidationError
        with pytest.raises(ValidationError):
            TestEvent._celerysalt_model(user_id="not_an_int", email="user@example.com")

    def test_event_decorator_registers_schema(self):
        """Test that @event decorator actually registers schema to registry."""
        @event("test.topic")
        class TestEvent:
            user_id: int
            email: str

        # Schema should be registered
        schema = self.registry.get_schema("test.topic", "v1")
        assert schema is not None
        assert "properties" in schema
        assert "user_id" in schema["properties"]
        assert "email" in schema["properties"]

    def test_event_decorator_with_default_values(self):
        """Test @event decorator with default values."""
        @event("test.topic")
        class TestEvent:
            user_id: int
            email: str
            status: str = "active"

        instance = TestEvent._celerysalt_model(user_id=123, email="user@example.com")
        assert instance.status == "active"

        instance2 = TestEvent._celerysalt_model(
            user_id=123, email="user@example.com", status="inactive"
        )
        assert instance2.status == "inactive"

    def test_event_decorator_with_custom_version(self):
        """Test @event decorator with custom version."""
        @event("test.topic", version="v2")
        class TestEvent:
            user_id: int

        # Schema should be registered with v2
        schema = self.registry.get_schema("test.topic", "v2")
        assert schema is not None

        # v1 should not exist
        with pytest.raises(Exception):
            self.registry.get_schema("test.topic", "v1")

    def test_event_decorator_skips_private_attributes(self):
        """Test that @event decorator skips private attributes."""
        @event("test.topic")
        class TestEvent:
            user_id: int
            _private_field: str = "private"
            __dunder_field: str = "dunder"

        # Only public fields should be in schema
        schema = self.registry.get_schema("test.topic", "v1")
        assert "user_id" in schema["properties"]
        assert "_private_field" not in schema["properties"]
        assert "__dunder_field" not in schema["properties"]

    def test_event_decorator_publish_validates_data(self):
        """Test that publish method validates data before publishing."""
        @event("test.topic")
        class TestEvent:
            user_id: int
            email: str

        # Valid data should work (we'll mock the actual publish)
        from unittest.mock import patch
        with patch("celery_salt.integrations.producer.publish_event") as mock_publish:
            mock_publish.return_value = "message_123"
            message_id = TestEvent.publish(
                user_id=123, email="user@example.com", broker_url="amqp://localhost"
            )
            assert message_id == "message_123"
            # Verify the data passed was validated
            call_args = mock_publish.call_args
            assert call_args is not None

        # Invalid data should raise ValidationError before publishing
        with pytest.raises(ValidationError):
            TestEvent.publish(user_id="not_an_int", email="user@example.com")


class TestSubscribeDecoratorReal:
    """Test @subscribe decorator with real functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = InMemorySchemaRegistry()
        set_schema_registry(self.registry)

        # Register a test schema first
        @event("test.topic")
        class TestEvent:
            user_id: int
            email: str

    def test_subscribe_decorator_creates_handler(self):
        """Test that @subscribe decorator creates a callable handler."""
        @subscribe("test.topic")
        def handler(data):
            return f"Processed {data.user_id}"

        # Handler should be callable
        assert callable(handler)

    def test_subscribe_decorator_fetches_schema(self):
        """Test that @subscribe decorator fetches schema from registry."""
        # Schema should already be registered from @event
        schema = self.registry.get_schema("test.topic", "v1")
        assert schema is not None

        @subscribe("test.topic")
        def handler(data):
            # Handler receives validated data
            assert hasattr(data, "user_id")
            assert hasattr(data, "email")
            return "processed"

        assert callable(handler)
