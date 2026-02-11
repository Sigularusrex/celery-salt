"""
Core decorators for CelerySalt: @event and @subscribe.

These decorators provide a Pydantic-based API for defining and subscribing to events,
with import-time schema registration for early error detection.
"""

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError, create_model

from celery_salt.core.event_utils import (
    ensure_schema_registered,
    register_event_schema,
    validate_and_call_rpc,
    validate_and_publish,
)
from celery_salt.core.exceptions import EventValidationError, RPCError
from celery_salt.core.registry import get_schema_registry
from celery_salt.logging.handlers import get_logger
from celery_salt.logging.validation_errors import format_validation_error
from celery_salt.utils.json_encoder import dumps_message

logger = get_logger(__name__)

# Protocol compatibility: Keep exchange name for backward compatibility with tchu-tchu
DEFAULT_EXCHANGE_NAME = "tchu_events"
DEFAULT_DISPATCHER_TASK_NAME = "celery_salt.dispatch_event"

# Global registry for RPC response/error schemas
_rpc_response_schemas: dict[str, type[BaseModel]] = {}
_rpc_error_schemas: dict[str, type[BaseModel]] = {}


def _class_to_pydantic_model(cls: type) -> type[BaseModel]:
    """Convert class annotations to a Pydantic model, skipping private attributes."""
    fields = {}
    for name, annotation in getattr(cls, "__annotations__", {}).items():
        if name.startswith("_"):
            continue
        default = getattr(cls, name, ...)
        fields[name] = (annotation, default)
    return create_model(cls.__name__, __base__=BaseModel, **fields)


def event(
    topic: str,
    mode: str = "broadcast",
    version: str = "v1",
    exchange_name: str = DEFAULT_EXCHANGE_NAME,
) -> Callable:
    """
    Decorator to define an event schema with import-time registration.

    Schema is registered IMMEDIATELY when this decorator runs (at import time),
    not when events are first published.

    Args:
        topic: Event topic (e.g., "user.signup.completed")
        mode: "broadcast" or "rpc" (default: "broadcast")
        version: Schema version (default: "v1")
        exchange_name: RabbitMQ exchange name (default: "tchu_events" for compatibility)

    Usage:
        @event("user.signup.completed")
        class UserSignup:
            user_id: int
            email: str
            company_id: int
            signup_source: str = "web"

        # Publish event
        UserSignup.publish(
            user_id=123,
            email="user@example.com",
            company_id=456,
            signup_source="web"
        )
    """

    def decorator(cls: type) -> type:
        pydantic_model = _class_to_pydantic_model(cls)

        # Register schema IMMEDIATELY (import time!)
        register_event_schema(
            topic=topic,
            version=version,
            schema_model=pydantic_model,
            publisher_class=cls,
            mode=mode,
            description="",
            response_schema_model=None,
            error_schema_model=None,
            auto_register=True,
        )

        # Add metadata to class
        cls._celerysalt_topic = topic
        cls._celerysalt_mode = mode
        cls._celerysalt_version = version
        cls._celerysalt_model = pydantic_model
        cls._celerysalt_exchange = exchange_name

        # Add publish method for broadcast events
        if mode == "broadcast":
            cls.publish = _create_publish_method(topic, pydantic_model, exchange_name)
        elif mode == "rpc":
            cls.call = _create_rpc_method(topic, pydantic_model, exchange_name)

        return cls

    return decorator


def response(topic: str, version: str = "v1") -> Callable:
    """
    Decorator to define a success response schema for an RPC event.

    Args:
        topic: RPC topic (must match the request topic)
        version: Schema version (default: "v1")

    Usage:
        @event("rpc.documents.list", mode="rpc")
        class DocumentListRequest:
            user_id: int

        @event.response("rpc.documents.list")
        class DocumentListResponse:
            documents: list[dict]
            total: int
    """

    def decorator(cls: type) -> type:
        pydantic_model = _class_to_pydantic_model(cls)

        # Store response schema for this topic
        _rpc_response_schemas[topic] = pydantic_model

        # Add metadata to the Pydantic model (not the original class)
        pydantic_model._celerysalt_topic = topic
        pydantic_model._celerysalt_model = pydantic_model
        pydantic_model._celerysalt_is_response = True

        # Return the Pydantic model so it can be instantiated directly
        return pydantic_model

    return decorator


def error(topic: str, version: str = "v1") -> Callable:
    """
    Decorator to define an error response schema for an RPC event.

    Args:
        topic: RPC topic (must match the request topic)
        version: Schema version (default: "v1")

    Usage:
        @event("rpc.documents.list", mode="rpc")
        class DocumentListRequest:
            user_id: int

        @event.error("rpc.documents.list")
        class DocumentListError:
            error_code: str
            error_message: str
            details: dict | None = None
    """

    def decorator(cls: type) -> type:
        pydantic_model = _class_to_pydantic_model(cls)

        # Store error schema for this topic
        _rpc_error_schemas[topic] = pydantic_model

        # Add metadata to the Pydantic model (not the original class)
        pydantic_model._celerysalt_topic = topic
        pydantic_model._celerysalt_model = pydantic_model
        pydantic_model._celerysalt_is_error = True

        # Return the Pydantic model so it can be instantiated directly
        return pydantic_model

    return decorator


# Attach response and error decorators to event function for convenience
event.response = response
event.error = error


def _create_publish_method(
    topic: str,
    model: type[BaseModel],
    exchange_name: str,
) -> Callable:
    """Create publish method for broadcast events."""

    @classmethod
    def publish(cls, broker_url: str | None = None, **kwargs) -> str:
        # 1. Validate data
        try:
            validated = model(**kwargs)
        except ValidationError as e:
            fmt = format_validation_error(e)
            logger.error(
                f"Publish schema validation failed for topic '{topic}': {fmt['summary']}",
                extra={"topic": topic, "validation_errors": fmt["errors"]},
            )
            raise

        # 2. Ensure schema registered (safety net if import-time registration failed)
        version = getattr(cls, "_celerysalt_version", "v1")
        mode = getattr(cls, "_celerysalt_mode", "broadcast")
        ensure_schema_registered(
            topic=topic,
            version=version,
            schema_model=model,
            publisher_class=cls,
            mode=mode,
            description="",
            response_schema_model=None,
            error_schema_model=None,
        )

        # 3. Use shared utility for publishing
        # Get version from class metadata
        version = getattr(cls, "_celerysalt_version", "v1")
        return validate_and_publish(
            topic=topic,
            data=validated.model_dump(),
            schema_model=model,
            exchange_name=exchange_name,
            broker_url=broker_url,
            version=version,
        )

    return publish


def _create_rpc_method(
    topic: str,
    model: type[BaseModel],
    exchange_name: str,
) -> Callable:
    """Create call method for RPC events."""

    @classmethod
    def call(cls, timeout: int = 30, **kwargs) -> Any:
        # 1. Validate request
        try:
            validated = model(**kwargs)
        except ValidationError as e:
            fmt = format_validation_error(e)
            logger.error(
                f"RPC request schema validation failed for topic '{topic}': {fmt['summary']}",
                extra={"topic": topic, "validation_errors": fmt["errors"]},
            )
            raise

        # 2. Register schema if needed
        version = getattr(cls, "_celerysalt_version", "v1")
        ensure_schema_registered(
            topic=topic,
            version=version,
            schema_model=model,
            publisher_class=cls,
            mode="rpc",
            description="",
            response_schema_model=_rpc_response_schemas.get(topic),
            error_schema_model=_rpc_error_schemas.get(topic),
        )

        # 3. Use shared utility for RPC call and response validation
        # Get version from class metadata
        version = getattr(cls, "_celerysalt_version", "v1")
        return validate_and_call_rpc(
            topic=topic,
            data=validated.model_dump(),
            schema_model=model,
            timeout=timeout,
            exchange_name=exchange_name,
            response_schema_model=_rpc_response_schemas.get(topic),
            error_schema_model=_rpc_error_schemas.get(topic),
            version=version,
        )

    return call


def _resolve_subscribe_args(
    topic: str | type,
    version: str,
    event_cls: type | None,
) -> tuple[str, str, type | None]:
    """
    Resolve topic, version, and event_cls for @subscribe.
    When topic is a SaltEvent subclass, infer topic/version from Meta.
    """
    resolved_topic = topic
    resolved_version = version
    resolved_event_cls = event_cls

    if isinstance(resolved_topic, type):
        from celery_salt.core.events import SaltEvent

        if issubclass(resolved_topic, SaltEvent):
            resolved_event_cls = resolved_topic
            resolved_topic = resolved_event_cls.Meta.topic
            if version == "latest":
                resolved_version = getattr(resolved_event_cls.Meta, "version", "v1")

    return resolved_topic, resolved_version, resolved_event_cls


def _create_validated_handler(
    validation_model: type[BaseModel],
    func: Callable,
    resolved_topic: str,
    resolved_event_cls: type | None,
) -> Callable:
    """Build the inner Celery task that validates payload and invokes the handler."""

    def validated_handler(self: Any, raw_data: dict) -> Any:
        meta = raw_data.get("_tchu_meta", {})
        is_rpc = meta.get("is_rpc", False)
        clean_data = {k: v for k, v in raw_data.items() if k != "_tchu_meta"}

        try:
            validated = validation_model(**clean_data)
        except ValidationError as e:
            fmt = format_validation_error(e)
            logger.error(
                f"Schema validation failed for topic '{resolved_topic}' "
                f"(handler={func.__name__}): {fmt['summary']}",
                extra={
                    "topic": resolved_topic,
                    "handler": func.__name__,
                    "validation_errors": fmt["errors"],
                    "data_keys": list(clean_data.keys()),
                },
            )
            raise EventValidationError(
                str(e),
                topic=resolved_topic,
                handler_name=func.__name__,
                validation_error=e,
            ) from e

        handler_arg: Any = validated
        if resolved_event_cls is not None:
            try:
                handler_arg = resolved_event_cls(**validated.model_dump())
            except ValidationError as e:
                fmt = format_validation_error(e)
                logger.error(
                    f"Event class validation failed for topic '{resolved_topic}' "
                    f"(handler={func.__name__}): {fmt['summary']}",
                    extra={
                        "topic": resolved_topic,
                        "handler": func.__name__,
                        "validation_errors": fmt["errors"],
                    },
                )
                raise EventValidationError(
                    str(e),
                    topic=resolved_topic,
                    handler_name=func.__name__,
                    validation_error=e,
                ) from e

        try:
            result = func(handler_arg)
        except RPCError as rpc_error:
            if is_rpc:
                error_response = rpc_error.to_response_dict()
                logger.warning(
                    f"RPC error for '{resolved_topic}': {rpc_error.error_code} - {rpc_error.error_message}"
                )
                if resolved_topic in _rpc_error_schemas:
                    error_model = _rpc_error_schemas[resolved_topic]
                    try:
                        return error_model(**error_response)
                    except ValidationError as e:
                        fmt = format_validation_error(e)
                        logger.warning(
                            f"RPC error response schema validation failed for '{resolved_topic}': "
                            f"{fmt['summary']}",
                            extra={
                                "topic": resolved_topic,
                                "validation_errors": fmt["errors"],
                            },
                        )
                        return error_response
                return error_response
            raise

        if is_rpc:
            if isinstance(result, BaseModel):
                result = result.model_dump()
            if resolved_topic in _rpc_response_schemas and isinstance(result, dict):
                response_model = _rpc_response_schemas[resolved_topic]
                try:
                    return response_model(**result)
                except ValidationError as e:
                    fmt = format_validation_error(e)
                    logger.warning(
                        f"RPC response schema validation failed for '{resolved_topic}': "
                        f"{fmt['summary']}. Returning raw response.",
                        extra={
                            "topic": resolved_topic,
                            "validation_errors": fmt["errors"],
                        },
                    )
                    return result
            return result

        if result is None:
            return None
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json")
        return json.loads(dumps_message(result))

    return validated_handler


def subscribe(
    topic: str | type,
    version: str = "latest",
    event_cls: type | None = None,
    **celery_options,
) -> Callable:
    """
    Decorator to register an event handler.

    Handler becomes a Celery task with all Celery features available.

    Args:
        topic: Either an event topic pattern (supports wildcards: user.*, #)
            or a `SaltEvent` subclass. When a `SaltEvent` subclass is passed,
            `topic` and `version` are inferred from `event_cls.Meta`.
        version: Schema version to validate against (default: "latest"). When
            `topic` is a `SaltEvent` subclass and `version` is left as
            `"latest"`, defaults to `event_cls.Meta.version`.
        event_cls: Optional `SaltEvent` subclass. If provided (or inferred by
            passing a `SaltEvent` subclass as the first argument), the handler
            will receive a constructed event instance (validated payload wrapped
            in the event class) instead of the raw validated payload model.
        **celery_options: All Celery task options (passed to shared_task). Examples:
            - priority: Task priority 0-9
            - autoretry_for: Tuple of exceptions to retry (e.g. (Exception,) or (ConnectionError,))
            - max_retries: Maximum retry attempts
            - retry_backoff: Enable exponential backoff (bool)
            - retry_backoff_max_interval: Max seconds between retries
            - time_limit: Hard timeout (seconds)
            - soft_time_limit: Soft timeout (seconds)
            - rate_limit: Rate limit (e.g. '100/m')
            Any other Celery task option is forwarded to shared_task.

    Usage:
        @subscribe("user.signup.completed", priority=5, autoretry_for=(Exception,), max_retries=3)
        def send_welcome_email(data: UserSignup):
            send_email(data.email)

        @subscribe(UserSignupEvent, priority=3)  # topic/version inferred from Meta
        def handler(evt: UserSignupEvent):
            do_something(evt.data.user_id)
    """

    def decorator(func: Callable) -> Callable:
        resolved_topic, resolved_version, resolved_event_cls = _resolve_subscribe_args(
            topic, version, event_cls
        )

        schema = _fetch_schema(resolved_topic, resolved_version)
        validation_model = _create_model_from_schema(schema)
        validated_handler = _create_validated_handler(
            validation_model, func, resolved_topic, resolved_event_cls
        )

        # Register as Celery task
        from celery import shared_task

        task = shared_task(
            name=f"celery_salt.{resolved_topic}.{func.__name__}",
            bind=True,  # Always bind to get task instance
            **celery_options,
        )(validated_handler)

        # Register handler in global registry (for queue binding)
        from celery_salt.integrations.registry import get_handler_registry

        registry = get_handler_registry()
        # Store version in metadata for version filtering
        metadata = {"version": resolved_version}
        registry.register_handler(resolved_topic, task, metadata=metadata)

        # Track subscriber in database (if schema registry supports it)
        try:
            schema_registry = get_schema_registry()
            if hasattr(schema_registry, "track_subscriber"):
                schema_registry.track_subscriber(
                    topic=resolved_topic,
                    handler_name=func.__name__,
                )
        except Exception:
            pass

        return task

    return decorator


def _fetch_schema(topic: str, version: str) -> dict:
    """Fetch schema from registry."""
    registry = get_schema_registry()
    return registry.get_schema(topic, version)


def _create_model_from_schema(schema: dict) -> type[BaseModel]:
    """
    Create Pydantic model from JSON Schema.

    Handles:
    - Basic types (str, int, float, bool)
    - Complex types (list, dict)
    - String formats (email, uuid, date-time)
    - Required vs optional fields
    - Default values
    """
    from pydantic import Field

    fields = {}

    for field_name, field_schema in schema.get("properties", {}).items():
        # Determine Python type from JSON Schema type
        field_type = _json_schema_type_to_python(field_schema)

        # Check if required
        is_required = field_name in schema.get("required", [])

        # Get default value
        default = field_schema.get("default", ... if is_required else None)

        # Handle optional fields (Union with None)
        if not is_required and default is ...:
            field_type = field_type | None
            default = None

        # Create field with metadata
        fields[field_name] = (
            field_type,
            Field(
                default=default,
                description=field_schema.get("description"),
                **_extract_field_constraints(field_schema),
            ),
        )

    # Create model
    return create_model(
        schema.get("title", "DynamicModel"),
        __base__=BaseModel,
        **fields,
    )


def _json_schema_type_to_python(field_schema: dict) -> type:
    """Convert JSON Schema type to Python type."""
    from datetime import datetime
    from uuid import UUID

    from pydantic import EmailStr

    json_type = field_schema.get("type")
    format_type = field_schema.get("format")

    # Handle formats first
    if format_type == "email":
        return EmailStr
    if format_type == "uuid":
        return UUID
    if format_type == "date-time":
        return datetime

    # Handle basic types
    type_mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    python_type = type_mapping.get(json_type, Any)

    # Handle array items
    if json_type == "array" and "items" in field_schema:
        item_type = _json_schema_type_to_python(field_schema["items"])
        return list[item_type]

    return python_type


def _extract_field_constraints(field_schema: dict) -> dict:
    """Extract Pydantic Field constraints from JSON Schema."""
    constraints = {}

    # String constraints
    if "minLength" in field_schema:
        constraints["min_length"] = field_schema["minLength"]
    if "maxLength" in field_schema:
        constraints["max_length"] = field_schema["maxLength"]
    if "pattern" in field_schema:
        constraints["pattern"] = field_schema["pattern"]

    # Number constraints
    if "minimum" in field_schema:
        constraints["ge"] = field_schema["minimum"]
    if "maximum" in field_schema:
        constraints["le"] = field_schema["maximum"]

    return constraints
