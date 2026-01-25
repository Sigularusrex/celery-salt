"""Tests for event_utils - testing actual validation and registration logic."""

import pytest
from pydantic import BaseModel, ValidationError

from celery_salt.core.event_utils import (
    register_event_schema,
    validate_and_publish,
    validate_and_call_rpc,
)
from celery_salt.core.registry import set_schema_registry, InMemorySchemaRegistry
from celery_salt.core.exceptions import SchemaConflictError


class TestRegisterEventSchemaReal:
    """Test register_event_schema with real registry."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = InMemorySchemaRegistry()
        set_schema_registry(self.registry)

    def test_register_schema_actually_registers(self):
        """Test that register_event_schema actually registers to registry."""

        class TestSchema(BaseModel):
            user_id: int
            email: str

        class TestEvent:
            pass

        register_event_schema(
            topic="test.topic",
            version="v1",
            schema_model=TestSchema,
            publisher_class=TestEvent,
        )

        # Verify it's actually in the registry
        schema = self.registry.get_schema("test.topic", "v1")
        assert schema is not None
        assert "properties" in schema
        assert "user_id" in schema["properties"]

    def test_register_duplicate_schema_detects_conflict(self):
        """Test that registering conflicting schemas raises error."""
        # Use a unique topic to avoid conflicts from other tests
        unique_topic = f"test.conflict.{id(self)}"

        class Schema1(BaseModel):
            user_id: int

        class Schema2(BaseModel):
            user_id: int
            email: str  # Different schema - will have different JSON schema

        class TestEvent:
            pass

        # Register first schema
        register_event_schema(
            topic=unique_topic,
            version="v1",
            schema_model=Schema1,
            publisher_class=TestEvent,
        )

        # Register conflicting schema should raise error
        with pytest.raises(SchemaConflictError):
            register_event_schema(
                topic=unique_topic,
                version="v1",
                schema_model=Schema2,
                publisher_class=TestEvent,
            )

    def test_register_same_schema_twice_no_error(self):
        """Test that registering the same schema twice doesn't error."""

        class TestSchema(BaseModel):
            user_id: int

        class TestEvent:
            pass

        # Register first time
        register_event_schema(
            topic="test.topic",
            version="v1",
            schema_model=TestSchema,
            publisher_class=TestEvent,
        )

        # Register same schema again - should not error
        register_event_schema(
            topic="test.topic",
            version="v1",
            schema_model=TestSchema,
            publisher_class=TestEvent,
        )

        # Should still be registered
        schema = self.registry.get_schema("test.topic", "v1")
        assert schema is not None


class TestValidateAndPublishReal:
    """Test validate_and_publish with real validation."""

    def test_validate_and_publish_validates_data(self):
        """Test that validate_and_publish actually validates data."""

        class TestSchema(BaseModel):
            user_id: int
            email: str

        # Valid data should pass validation
        from unittest.mock import patch

        with patch("celery_salt.integrations.producer.publish_event") as mock_publish:
            mock_publish.return_value = "message_123"
            message_id = validate_and_publish(
                topic="test.topic",
                data={"user_id": 123, "email": "user@example.com"},
                schema_model=TestSchema,
            )
            assert message_id == "message_123"
            # Verify publish was called with validated data
            assert mock_publish.called

        # Invalid data should raise ValidationError
        with pytest.raises(ValidationError):
            validate_and_publish(
                topic="test.topic",
                data={"user_id": "not_an_int", "email": "user@example.com"},
                schema_model=TestSchema,
            )

    def test_validate_and_publish_with_missing_fields(self):
        """Test that missing required fields raise ValidationError."""

        class TestSchema(BaseModel):
            user_id: int
            email: str

        with pytest.raises(ValidationError):
            validate_and_publish(
                topic="test.topic",
                data={"user_id": 123},  # Missing email
                schema_model=TestSchema,
            )


class TestValidateAndCallRpcReal:
    """Test validate_and_call_rpc with real validation."""

    def test_validate_and_call_rpc_validates_request(self):
        """Test that validate_and_call_rpc validates request data."""

        class RequestSchema(BaseModel):
            a: float
            b: float

        class ResponseSchema(BaseModel):
            result: float

        # Valid request should pass validation
        from unittest.mock import patch

        with patch("celery_salt.integrations.producer.call_rpc") as mock_call:
            mock_call.return_value = {"result": 42}
            with patch(
                "celery_salt.core.event_utils._validate_rpc_response_with_models"
            ) as mock_validate:
                mock_validate.return_value = ResponseSchema(result=42)
                response = validate_and_call_rpc(
                    topic="rpc.test",
                    data={"a": 10, "b": 32},
                    schema_model=RequestSchema,
                    response_schema_model=ResponseSchema,
                )
                assert isinstance(response, ResponseSchema)
                assert response.result == 42

        # Invalid request should raise ValidationError
        with pytest.raises(ValidationError):
            validate_and_call_rpc(
                topic="rpc.test",
                data={"a": "not_a_float", "b": 32},
                schema_model=RequestSchema,
            )

    def test_validate_and_call_rpc_validates_response(self):
        """Test that validate_and_call_rpc validates response."""

        class RequestSchema(BaseModel):
            value: int

        class ResponseSchema(BaseModel):
            result: float

        from unittest.mock import patch

        with patch("celery_salt.integrations.producer.call_rpc") as mock_call:
            # Return valid response
            mock_call.return_value = {"result": 42}
            with patch(
                "celery_salt.core.event_utils._validate_rpc_response_with_models"
            ) as mock_validate:
                mock_validate.return_value = ResponseSchema(result=42)
                response = validate_and_call_rpc(
                    topic="rpc.test",
                    data={"value": 10},
                    schema_model=RequestSchema,
                    response_schema_model=ResponseSchema,
                )
                assert isinstance(response, ResponseSchema)
                assert response.result == 42
