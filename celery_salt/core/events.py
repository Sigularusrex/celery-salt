"""
Base class for class-based events in CelerySalt.

Provides a rich, extensible API for defining events with custom business logic,
inheritance, and hooks while maintaining compatibility with the decorator-based API.
"""

from abc import ABC
from typing import Any

from pydantic import BaseModel

from celery_salt.core.event_utils import (
    ensure_schema_registered,
    register_event_schema,
    validate_and_call_rpc,
    validate_and_publish,
)
from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)


class SaltResponse:
    """
    Wrapper for an RPC response, mirroring the SaltEvent API.

    Returned by ``event.call()`` so you can use ``.payload`` and attribute
    access like with the event instance (e.g. ``event.payload`` for the request).

    Attributes:
        event: The SaltEvent instance that made the call.
        data: The validated Response or Error (Pydantic model).
    """

    __slots__ = ("event", "data")

    def __init__(self, event: "SaltEvent", data: Any) -> None:
        self.event = event
        self.data = data

    @property
    def payload(self) -> dict[str, Any] | list[Any] | Any:
        """
        Return the response as a JSON-serializable dict or list.

        Use this for DRF ``Response(...)``, ``JsonResponse(...)``, etc.
        For ``RootModel[list[...]]`` responses, this is the bare list (array of dicts).
        """
        return self.event.response_payload(self.data)

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the response data (e.g. response.result, response.root)."""
        return getattr(self.data, name)


class SaltEvent(ABC):
    """
    Base class for all CelerySalt events.

    Publishers define event classes that inherit from SaltEvent.
    Schemas are automatically registered to the schema registry on import.

    Attributes:
        data: Validated event data (Pydantic model instance)

    Example:
        class UserSignup(SaltEvent):
            class Schema(BaseModel):
                user_id: int
                email: str

            class Meta:
                topic = "user.signup"

            def is_premium(self) -> bool:
                return self.data.user_id > 1000

        event = UserSignup(user_id=123, email="user@example.com")
        event.publish()
    """

    # Required: Event schema definition
    class Schema(BaseModel):
        """Pydantic schema for this event."""

        pass

    # Required: Event metadata
    class Meta:
        topic: str  # Event topic (e.g., "pulse.risk.created")
        mode: str = "broadcast"  # "broadcast" or "rpc"
        version: str = "v1"  # Schema version
        description: str = ""  # Human-readable description
        exchange_name: str = "tchu_events"  # RabbitMQ exchange
        auto_register: bool = True  # Auto-register schema on import

    # Optional: RPC response schema
    class Response(BaseModel):
        """Response schema for RPC events."""

        pass

    # Optional: RPC error schema
    class Error(BaseModel):
        """Error schema for RPC events."""

        pass

    def __init__(self, **kwargs):
        """
        Initialize event with data.

        Args:
            **kwargs: Event data matching Schema fields
        """
        self.data = self.Schema(**kwargs)

    def __getattr__(self, name: str) -> Any:
        """
        Proxy attribute access to the event payload (Schema instance).

        Allows direct access to schema fields, e.g. event.id instead of event.data.id.
        """
        return getattr(self.data, name)

    @property
    def payload(self) -> dict[str, Any]:
        """
        Return the validated event payload as a plain dict.

        This is a convenience alias for `to_dict()` with default options.
        """
        return self.to_dict()

    def to_dict(self, **kwargs) -> dict[str, Any]:
        """
        Dump the validated event payload to a dict.

        This delegates to Pydantic's `model_dump()` on the event schema instance.
        Any `**kwargs` are forwarded to `model_dump()` (e.g. `exclude_none=True`).
        """
        return self.data.model_dump(**kwargs)

    def response_payload(self, response: Any) -> dict[str, Any] | list[Any] | Any:
        """
        Return the RPC response as a JSON-serializable dict or list.

        Use this like ``payload`` for the request: after ``response = event.call()``
        (or in a handler after building a response), call
        ``event.response_payload(response)`` or use ``response.payload`` on a
        SaltResponse instance.

        - For a normal Response schema: returns the same as ``response.model_dump()``.
        - For a ``RootModel[list[...]]`` response: returns the bare list (array of
          dicts), so you get a JSON array without a wrapping ``{"root": [...]}``.

        Only valid for events with ``mode="rpc"``.
        """
        if self.Meta.mode != "rpc":
            raise ValueError(
                f"response_payload() is only for RPC events; "
                f"{self.Meta.topic} has mode={self.Meta.mode!r}"
            )
        if response is None:
            return response
        if isinstance(response, BaseModel):
            dumped = response.model_dump()
            # RootModel dumps as {"root": ...}; return bare root for API use
            if isinstance(dumped, dict) and list(dumped.keys()) == ["root"]:
                return dumped["root"]
            return dumped
        if isinstance(response, dict):
            return response
        return response

    def respond(self, data: Any = None, **kwargs) -> Any:
        """
        Build a validated success response for RPC handlers.

        Uses this event's Response schema. Handlers can return
        event.respond(...) so the response is guaranteed to match the schema.

        Only valid for events with mode="rpc".

        Args:
            data: Optional dict, list, or value to use as response (e.g. serializer.data).
                Validated via Response.model_validate(data); invalid data raises ValidationError.
            **kwargs: Field values for the Response schema (e.g. result=42, operation="add").
                Ignored if data is provided.

        Returns:
            Response: Validated Pydantic model instance (self.Response)

        Raises:
            ValueError: If called on a non-RPC event
            ValidationError: If data does not match the Response schema (e.g. extra keys when extra="forbid")

        Example:
            return event.respond(serializer.data)
            return event.respond(documents=[...], total=5)
        """
        if self.Meta.mode != "rpc":
            raise ValueError(
                f"respond() is only for RPC events; {self.Meta.topic} has mode={self.Meta.mode!r}"
            )
        if data is not None:
            return self.Response.model_validate(data)
        return self.Response(**kwargs)

    def publish(self, broker_url: str | None = None, **kwargs) -> str:
        """
        Publish event to message broker.

        Can be overridden for custom pre/post publish hooks.

        Args:
            broker_url: Optional broker URL
            **kwargs: Optional publish options
                - routing_key: Custom routing key
                - priority: Message priority (0-10)
                - expiration: Message expiration in ms

        Returns:
            str: Message ID for tracking
        """
        # Ensure schema is registered (safety net)
        ensure_schema_registered(
            topic=self.Meta.topic,
            version=self.Meta.version,
            schema_model=self.Schema,
            publisher_class=self.__class__,
            mode=self.Meta.mode,
            description=self.Meta.description,
            response_schema_model=getattr(self, "Response", None),
            error_schema_model=getattr(self, "Error", None),
        )

        # Use shared utility for validation and publishing
        return validate_and_publish(
            topic=self.Meta.topic,
            data=self.to_dict(),
            schema_model=self.Schema,
            exchange_name=self.Meta.exchange_name,
            broker_url=broker_url,
            version=self.Meta.version,
            **kwargs,
        )

    def call(self, timeout: int = 30, **kwargs) -> Any:
        """
        Make RPC call and wait for response.

        Only for events with mode="rpc".

        Args:
            timeout: Response timeout in seconds
            **kwargs: Optional call options

        Returns:
            SaltResponse: Wrapper with ``.event``, ``.data`` (Response/Error model),
                and ``.payload`` (JSON-serializable dict/list). Attribute access
                (e.g. ``response.result``, ``response.root``) is proxied to ``.data``.

        Raises:
            RPCTimeoutError: If response not received within timeout
            ValueError: If called on non-RPC event
        """
        if self.Meta.mode != "rpc":
            raise ValueError(f"Cannot call() on broadcast event {self.Meta.topic}")

        # Ensure schema is registered (safety net)
        ensure_schema_registered(
            topic=self.Meta.topic,
            version=self.Meta.version,
            schema_model=self.Schema,
            publisher_class=self.__class__,
            mode=self.Meta.mode,
            description=self.Meta.description,
            response_schema_model=getattr(self, "Response", None),
            error_schema_model=getattr(self, "Error", None),
        )

        # Use shared utility for validation, RPC call, and response validation
        raw = validate_and_call_rpc(
            topic=self.Meta.topic,
            data=self.to_dict(),
            schema_model=self.Schema,
            timeout=timeout,
            exchange_name=self.Meta.exchange_name,
            response_schema_model=getattr(self, "Response", None),
            error_schema_model=getattr(self, "Error", None),
            version=self.Meta.version,
            **kwargs,
        )
        return SaltResponse(event=self, data=raw)

    @classmethod
    def __init_subclass__(cls, **kwargs):
        """
        Called automatically when a subclass is defined.

        This is where we register the schema at import time.
        """
        super().__init_subclass__(**kwargs)

        # Check if Meta class exists
        if not hasattr(cls, "Meta"):
            raise ValueError(
                f"{cls.__name__} must define a Meta class with 'topic' attribute"
            )

        # Check if Schema class exists
        if not hasattr(cls, "Schema"):
            raise ValueError(
                f"{cls.__name__} must define a Schema class (Pydantic BaseModel)"
            )

        # Validate Meta attributes
        meta = cls.Meta
        if not hasattr(meta, "topic") or not meta.topic:
            raise ValueError(f"{cls.__name__}.Meta must define 'topic' attribute")

        # Set defaults
        if not hasattr(meta, "mode"):
            meta.mode = "broadcast"
        if not hasattr(meta, "version"):
            meta.version = "v1"
        if not hasattr(meta, "description"):
            meta.description = ""
        if not hasattr(meta, "exchange_name"):
            meta.exchange_name = "tchu_events"
        if not hasattr(meta, "auto_register"):
            meta.auto_register = True

        # Auto-register schema if enabled
        if meta.auto_register:
            register_event_schema(
                topic=meta.topic,
                version=meta.version,
                schema_model=cls.Schema,
                publisher_class=cls,
                mode=meta.mode,
                description=meta.description,
                response_schema_model=getattr(cls, "Response", None),
                error_schema_model=getattr(cls, "Error", None),
                auto_register=True,
            )
