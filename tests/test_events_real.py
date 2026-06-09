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

        # Convenience dump helpers
        assert event.to_dict() == {
            "user_id": 123,
            "email": "user@example.com",
            "status": "active",
        }
        assert event.payload["email"] == "user@example.com"

    def test_event_direct_attribute_access(self):
        """Test that schema fields are accessible directly on the event (evt.id)."""

        class MyNewEvent(SaltEvent):
            class Schema(BaseModel):
                id: int
                name: str

            class Meta:
                topic = "my.new.event"

        evt = MyNewEvent(id=42, name="test")
        assert evt.id == 42
        assert evt.name == "test"
        assert evt.data.id == 42
        assert evt.data.name == "test"
        # Missing attribute raises AttributeError
        with pytest.raises(AttributeError):
            _ = evt.nonexistent_field

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

    def test_call_defaults_priority_9_and_expires_equals_timeout(self):
        """call() must default to priority=9 and expires=timeout to prevent worker starvation."""
        from unittest.mock import patch

        class PingRpc(SaltEvent):
            class Schema(BaseModel):
                pass

            class Meta:
                topic = "rpc.ping"
                mode = "rpc"

        event = PingRpc()

        with patch("celery_salt.integrations.producer.call_rpc") as mock_call_rpc:
            mock_call_rpc.return_value = None
            try:
                event.call(timeout=30)
            except Exception:
                pass  # response validation may fail; we only care about the call args

        mock_call_rpc.assert_called_once()
        _, kwargs = mock_call_rpc.call_args
        assert kwargs.get("priority") == 9, "RPC call must default to priority=9"
        assert kwargs.get("expires") == 30, "RPC expires must default to timeout value"

    def test_call_expires_matches_custom_timeout(self):
        """expires should track a custom timeout when not explicitly set."""
        from unittest.mock import patch

        class PingRpc(SaltEvent):
            class Schema(BaseModel):
                pass

            class Meta:
                topic = "rpc.ping.timeout"
                mode = "rpc"

        event = PingRpc()

        with patch("celery_salt.integrations.producer.call_rpc") as mock_call_rpc:
            mock_call_rpc.return_value = None
            try:
                event.call(timeout=60)
            except Exception:
                pass

        _, kwargs = mock_call_rpc.call_args
        assert kwargs.get("expires") == 60

    def test_call_allows_overriding_priority_and_expires(self):
        """Callers must be able to override priority and expires explicitly."""
        from unittest.mock import patch

        class PingRpc(SaltEvent):
            class Schema(BaseModel):
                pass

            class Meta:
                topic = "rpc.ping.override"
                mode = "rpc"

        event = PingRpc()

        with patch("celery_salt.integrations.producer.call_rpc") as mock_call_rpc:
            mock_call_rpc.return_value = None
            try:
                event.call(timeout=30, priority=5, expires=10)
            except Exception:
                pass

        _, kwargs = mock_call_rpc.call_args
        assert kwargs.get("priority") == 5
        assert kwargs.get("expires") == 10

    def test_call_broadcast_event_raises(self):
        """call() on a broadcast event must raise ValueError."""

        class BroadcastEvent(SaltEvent):
            class Schema(BaseModel):
                pass

            class Meta:
                topic = "broadcast.thing"
                mode = "broadcast"

        event = BroadcastEvent()
        with pytest.raises(ValueError, match="broadcast"):
            event.call()
