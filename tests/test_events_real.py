"""Tests for SaltEvent - testing actual functionality, not just mocks."""

import pytest
from pydantic import BaseModel, ValidationError

from celery_salt.core.events import SaltEvent
from celery_salt.core.exceptions import SchemaRegistryUnavailableError
from celery_salt.core.registry import (
    InMemorySchemaRegistry,
    set_schema_registry,
)


class TestSaltEventRealFunctionality:
    """Test SaltEvent with real functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        # Use fresh registry for each test
        self.registry = InMemorySchemaRegistry()
        set_schema_registry(self.registry)

    def test_event_initialization_validates_data(self):
        """Test that event initialization actually validates data with Pydantic."""

        class UserSignup(SaltEvent):
            class Schema(BaseModel):
                user_id: int
                email: str

            class Meta:
                topic = "user.signup"

        # Valid data should work
        event = UserSignup(user_id=123, email="user@example.com")
        assert event.data.user_id == 123
        assert event.data.email == "user@example.com"

        # Invalid data should raise ValidationError
        with pytest.raises(ValidationError):
            UserSignup(user_id="not_an_int", email="user@example.com")

    def test_event_initialization_with_missing_fields(self):
        """Test that missing required fields raise ValidationError."""

        class UserSignup(SaltEvent):
            class Schema(BaseModel):
                user_id: int
                email: str

            class Meta:
                topic = "user.signup"

        with pytest.raises(ValidationError):
            UserSignup(user_id=123)  # Missing email

    def test_event_initialization_with_defaults(self):
        """Test that optional fields with defaults work."""

        class UserSignup(SaltEvent):
            class Schema(BaseModel):
                user_id: int
                email: str
                status: str = "active"

            class Meta:
                topic = "user.signup"

        event = UserSignup(user_id=123, email="user@example.com")
        assert event.data.status == "active"

        event2 = UserSignup(user_id=123, email="user@example.com", status="inactive")
        assert event2.data.status == "inactive"

    def test_event_schema_registration(self):
        """Test that event schema is actually registered to registry."""

        class UserSignup(SaltEvent):
            class Schema(BaseModel):
                user_id: int
                email: str

            class Meta:
                topic = "user.signup"
                auto_register = True

        # Schema should be registered
        schema = self.registry.get_schema("user.signup", "v1")
        assert schema is not None
        assert "properties" in schema
        assert "user_id" in schema["properties"]
        assert "email" in schema["properties"]

    def test_event_custom_methods(self):
        """Test that custom methods work on event instances."""

        class UserSignup(SaltEvent):
            class Schema(BaseModel):
                user_id: int
                email: str

            class Meta:
                topic = "user.signup"

            def is_premium_user(self) -> bool:
                return self.data.user_id > 1000

        event1 = UserSignup(user_id=500, email="user@example.com")
        assert event1.is_premium_user() is False

        event2 = UserSignup(user_id=2000, email="premium@example.com")
        assert event2.is_premium_user() is True

    def test_event_inheritance(self):
        """Test that events can inherit from other events."""

        class BaseEvent(SaltEvent):
            class Schema(BaseModel):
                timestamp: int = 1234567890

            class Meta:
                topic = "base.event"

        class UserSignup(BaseEvent):
            class Schema(BaseModel):
                user_id: int
                email: str
                timestamp: int = 1234567890

            class Meta:
                topic = "user.signup"

        event = UserSignup(user_id=123, email="user@example.com")
        assert event.data.user_id == 123
        assert event.data.email == "user@example.com"
        assert event.data.timestamp == 1234567890

    def test_event_with_custom_version(self):
        """Test that events can specify custom versions."""

        class UserSignupV2(SaltEvent):
            class Schema(BaseModel):
                user_id: int
                email: str
                phone: str  # New field

            class Meta:
                topic = "user.signup"
                version = "v2"

        # Schema should be registered with v2
        schema = self.registry.get_schema("user.signup", "v2")
        assert schema is not None
        assert "phone" in schema["properties"]

        # v1 should not exist
        with pytest.raises(SchemaRegistryUnavailableError):
            self.registry.get_schema("user.signup", "v1")

    def test_event_rpc_mode(self):
        """Test that RPC events can define response and error schemas."""

        class CalculatorAdd(SaltEvent):
            class Schema(BaseModel):
                a: float
                b: float

            class Response(BaseModel):
                result: float

            class Error(BaseModel):
                error_code: str
                error_message: str

            class Meta:
                topic = "rpc.calculator.add"
                mode = "rpc"

        # Event should be created
        event = CalculatorAdd(a=10, b=32)
        assert event.data.a == 10
        assert event.data.b == 32

        # Response and Error classes should exist
        assert CalculatorAdd.Response is not None
        assert CalculatorAdd.Error is not None

        # Can create response instances
        response = CalculatorAdd.Response(result=42)
        assert response.result == 42

        # Can create error instances
        error = CalculatorAdd.Error(error_code="INVALID", error_message="Bad input")
        assert error.error_code == "INVALID"
        assert error.error_message == "Bad input"
