"""Integration tests for CelerySalt.

These tests verify that both APIs work together and schemas are registered.
We avoid heavy mocking and focus on real functionality.
"""

from pydantic import BaseModel

from celery_salt import SaltEvent, event, subscribe
from celery_salt.core.registry import (
    InMemorySchemaRegistry,
    set_schema_registry,
)


class TestEndToEndBroadcast:
    """Test end-to-end broadcast event flow."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = InMemorySchemaRegistry()
        set_schema_registry(self.registry)

    def test_decorator_api_schema_registration(self):
        """Test decorator-based API: schema registration."""

        # Define event
        @event("test.topic")
        class TestEvent:
            user_id: int
            email: str

        # Subscribe to event
        @subscribe("test.topic")
        def handler(data):
            return f"Processed {data.user_id}"

        # Verify schema is registered
        schema = self.registry.get_schema("test.topic", "v1")
        assert schema is not None
        assert "user_id" in schema.get("properties", {})
        assert "email" in schema.get("properties", {})

    def test_class_based_api_schema_registration(self):
        """Test class-based API: schema registration."""

        class TestEvent(SaltEvent):
            class Schema(BaseModel):
                user_id: int
                email: str

            class Meta:
                topic = "test.topic"

        # Verify schema is registered
        schema = self.registry.get_schema("test.topic", "v1")
        assert schema is not None
        assert "user_id" in schema.get("properties", {})
        assert "email" in schema.get("properties", {})


class TestVersioningIntegration:
    """Test versioning integration."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = InMemorySchemaRegistry()
        set_schema_registry(self.registry)

    def test_versioned_events_same_topic(self):
        """Test that different versions can use same topic."""

        # Register v1 event
        @event("test.topic", version="v1")
        class TestEventV1:
            user_id: int
            email: str

        # Register v2 event (same topic, different version)
        @event("test.topic", version="v2")
        class TestEventV2:
            user_id: int
            email: str
            phone: str  # New field

        # Both should be registered
        schema_v1 = self.registry.get_schema("test.topic", "v1")
        schema_v2 = self.registry.get_schema("test.topic", "v2")

        assert schema_v1 is not None
        assert schema_v2 is not None
        assert "phone" not in schema_v1.get("properties", {})
        assert "phone" in schema_v2.get("properties", {})

    def test_backward_compatibility_schema_registration(self):
        """Test v1 and v2 schemas are both registered for backward compatibility."""

        # Register v1 event first (needed for v1 handler)
        @event("test.topic", version="v1")
        class TestEventV1:
            user_id: int
            email: str

        # Register v2 event
        @event("test.topic", version="v2")
        class TestEventV2:
            user_id: int
            email: str
            phone: str  # New field in v2

        # Subscribe with v1 handler (backward compatible)
        @subscribe("test.topic", version="v1")
        def handler_v1(data):
            # Should receive v2 message but validate against v1 schema
            # phone field will be ignored
            return f"V1 handler: {data.user_id}"

        # Both schemas should be registered
        schema_v1 = self.registry.get_schema("test.topic", "v1")
        schema_v2 = self.registry.get_schema("test.topic", "v2")
        assert schema_v1 is not None
        assert schema_v2 is not None
        assert "phone" not in schema_v1.get("properties", {})
        assert "phone" in schema_v2.get("properties", {})


class TestRpcIntegration:
    """Test RPC integration."""

    def setup_method(self):
        self.registry = InMemorySchemaRegistry()
        set_schema_registry(self.registry)

    def test_decorator_api_rpc_schema_registration(self):
        """Test decorator-based API: RPC schema registration."""

        @event("rpc.test", mode="rpc")
        class TestRPC:
            value: int

        @event.response("rpc.test")
        class TestResponse:
            result: int

        # Verify request schema is registered
        schema = self.registry.get_schema("rpc.test", "v1")
        assert schema is not None
        assert "value" in schema.get("properties", {})

    def test_class_based_api_rpc_schema_registration(self):
        """Test class-based API: RPC schema registration."""

        class TestRPC(SaltEvent):
            class Schema(BaseModel):
                value: int

            class Response(BaseModel):
                result: int

            class Meta:
                topic = "rpc.test"
                mode = "rpc"

        # Verify request schema is registered
        schema = self.registry.get_schema("rpc.test", "v1")
        assert schema is not None
        assert "value" in schema.get("properties", {})


class TestBothApisTogether:
    """Test that both APIs work together."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = InMemorySchemaRegistry()
        set_schema_registry(self.registry)

    def test_decorator_and_class_based_same_topic(self):
        """Test that decorator and class-based APIs can use same topic."""

        # Decorator-based event
        @event("test.topic", version="v1")
        class DecoratorEvent:
            user_id: int

        # Class-based event (same topic, different version)
        class ClassEvent(SaltEvent):
            class Schema(BaseModel):
                user_id: int
                email: str  # Additional field

            class Meta:
                topic = "test.topic"
                version = "v2"

        # Both should be registered
        schema_v1 = self.registry.get_schema("test.topic", "v1")
        schema_v2 = self.registry.get_schema("test.topic", "v2")

        assert schema_v1 is not None
        assert schema_v2 is not None
