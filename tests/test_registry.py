"""Tests for schema registry - testing actual functionality."""

import pytest

from celery_salt.core.exceptions import SchemaRegistryUnavailableError
from celery_salt.core.registry import (
    InMemorySchemaRegistry,
    get_schema_registry,
    set_schema_registry,
)


class TestInMemorySchemaRegistry:
    """Test InMemorySchemaRegistry - real functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = InMemorySchemaRegistry()

    def test_register_and_retrieve_schema(self):
        """Test registering and retrieving a schema."""
        schema = {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer"},
                "email": {"type": "string"},
            },
            "required": ["user_id", "email"],
        }

        result = self.registry.register_schema(
            topic="test.topic",
            version="v1",
            schema=schema,
            publisher_module="test_module",
            publisher_class="TestEvent",
        )

        assert result["created"] is True

        # Retrieve it
        retrieved = self.registry.get_schema("test.topic", "v1")
        assert retrieved == schema

    def test_register_duplicate_schema_returns_existing(self):
        """Test registering duplicate schema returns existing."""
        schema = {"type": "object", "properties": {}}

        # Register first time
        result1 = self.registry.register_schema(
            topic="test.topic",
            version="v1",
            schema=schema,
            publisher_module="test_module",
            publisher_class="TestEvent",
        )
        assert result1["created"] is True

        # Register again (same schema)
        result2 = self.registry.register_schema(
            topic="test.topic",
            version="v1",
            schema=schema,
            publisher_module="test_module",
            publisher_class="TestEvent",
        )
        assert result2["created"] is False
        assert "existing_schema" in result2
        assert result2["existing_schema"] == schema

    def test_register_different_versions(self):
        """Test registering different versions of same topic."""
        schema_v1 = {"type": "object", "properties": {"v1_field": {"type": "string"}}}
        schema_v2 = {"type": "object", "properties": {"v2_field": {"type": "string"}}}

        result1 = self.registry.register_schema(
            topic="test.topic",
            version="v1",
            schema=schema_v1,
            publisher_module="test_module",
            publisher_class="TestEvent",
        )
        assert result1["created"] is True

        result2 = self.registry.register_schema(
            topic="test.topic",
            version="v2",
            schema=schema_v2,
            publisher_module="test_module",
            publisher_class="TestEvent",
        )
        assert result2["created"] is True

        # Both versions should exist
        assert self.registry.get_schema("test.topic", "v1") == schema_v1
        assert self.registry.get_schema("test.topic", "v2") == schema_v2

    def test_get_schema_not_found_raises_error(self):
        """Test getting non-existent schema raises error."""
        with pytest.raises(SchemaRegistryUnavailableError):
            self.registry.get_schema("nonexistent.topic", "v1")

    def test_get_schema_latest_version(self):
        """Test getting latest version of schema."""
        schema_v1 = {"type": "object", "properties": {"version": {"type": "string", "default": "v1"}}}
        schema_v2 = {"type": "object", "properties": {"version": {"type": "string", "default": "v2"}}}
        schema_v10 = {"type": "object", "properties": {"version": {"type": "string", "default": "v10"}}}

        self.registry.register_schema(
            topic="test.topic",
            version="v1",
            schema=schema_v1,
            publisher_module="test_module",
            publisher_class="TestEvent",
        )
        self.registry.register_schema(
            topic="test.topic",
            version="v2",
            schema=schema_v2,
            publisher_module="test_module",
            publisher_class="TestEvent",
        )
        self.registry.register_schema(
            topic="test.topic",
            version="v10",
            schema=schema_v10,
            publisher_module="test_module",
            publisher_class="TestEvent",
        )

        # Latest should be v10 (not v2, because v10 > v2)
        latest = self.registry.get_schema("test.topic", "latest")
        assert latest == schema_v10

    def test_register_rpc_schema_with_response_error(self):
        """Test registering RPC schema with response and error schemas."""
        request_schema = {"type": "object", "properties": {"a": {"type": "number"}}}
        response_schema = {"type": "object", "properties": {"result": {"type": "number"}}}
        error_schema = {"type": "object", "properties": {"error_code": {"type": "string"}}}

        result = self.registry.register_schema(
            topic="rpc.test",
            version="v1",
            schema=request_schema,
            publisher_module="test_module",
            publisher_class="TestEvent",
            mode="rpc",
            response_schema=response_schema,
            error_schema=error_schema,
        )

        assert result["created"] is True

    def test_track_subscriber_no_op(self):
        """Test tracking subscriber (no-op for in-memory registry)."""
        # Should not raise
        self.registry.track_subscriber("test.topic", "handler_name")


class TestGlobalRegistry:
    """Test global registry functions."""

    def test_get_schema_registry_singleton(self):
        """Test that get_schema_registry returns singleton."""
        registry1 = get_schema_registry()
        registry2 = get_schema_registry()

        assert registry1 is registry2

    def test_set_schema_registry(self):
        """Test setting custom registry."""
        original_registry = get_schema_registry()
        custom_registry = InMemorySchemaRegistry()

        set_schema_registry(custom_registry)

        # Should return custom registry
        assert get_schema_registry() is custom_registry

        # Restore original
        set_schema_registry(original_registry)
        assert get_schema_registry() is original_registry
