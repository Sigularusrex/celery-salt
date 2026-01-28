"""
Core decorators for CelerySalt: @event and @subscribe.

These decorators provide a Pydantic-based API for defining and subscribing to events,
with import-time schema registration for early error detection.
"""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError, create_model

from celery_salt.core.event_utils import (
    ensure_schema_registered,
    register_event_schema,
    validate_and_call_rpc,
    validate_and_publish,
)
from celery_salt.core.exceptions import RPCError
from celery_salt.core.registry import get_schema_registry
from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)

# Protocol compatibility: Keep exchange name for backward compatibility with tchu-tchu
DEFAULT_EXCHANGE_NAME = "tchu_events"
DEFAULT_DISPATCHER_TASK_NAME = "celery_salt.dispatch_event"

# Global registry for RPC response/error schemas
_rpc_response_schemas: dict[str, type[BaseModel]] = {}
_rpc_error_schemas: dict[str, type[BaseModel]] = {}


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
        # Convert class annotations to Pydantic model
        fields = {}
        for name, annotation in getattr(cls, "__annotations__", {}).items():
            # Skip private attributes
            if name.startswith("_"):
                continue

            # Get default value if present
            default = getattr(cls, name, ...)
            fields[name] = (annotation, default)

        # Create Pydantic model from class
        pydantic_model = create_model(
            cls.__name__,
            __base__=BaseModel,
            **fields,
        )

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
        # Convert class annotations to Pydantic model
        fields = {}
        for name, annotation in getattr(cls, "__annotations__", {}).items():
            if name.startswith("_"):
                continue
            default = getattr(cls, name, ...)
            fields[name] = (annotation, default)

        # Create Pydantic model
        pydantic_model = create_model(
            cls.__name__,
            __base__=BaseModel,
            **fields,
        )

        # Store response schema for this topic
        _rpc_response_schemas[topic] = pydantic_model

        # Add metadata to the Pydantic model (not the original class)
        pydantic_model._celerysalt_topic = topic
        pydantic_model._celerysalt_model = pydantic_model
        pydantic_model._celerysalt_is_response = True

        logger.debug(f"Registered response schema for RPC topic: {topic}")

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
        # Convert class annotations to Pydantic model
        fields = {}
        for name, annotation in getattr(cls, "__annotations__", {}).items():
            if name.startswith("_"):
                continue
            default = getattr(cls, name, ...)
            fields[name] = (annotation, default)

        # Create Pydantic model
        pydantic_model = create_model(
            cls.__name__,
            __base__=BaseModel,
            **fields,
        )

        # Store error schema for this topic
        _rpc_error_schemas[topic] = pydantic_model

        # Add metadata to the Pydantic model (not the original class)
        pydantic_model._celerysalt_topic = topic
        pydantic_model._celerysalt_model = pydantic_model
        pydantic_model._celerysalt_is_error = True

        logger.debug(f"Registered error schema for RPC topic: {topic}")

        # Return the Pydantic model so it can be instantiated directly
        return pydantic_model

    return decorator


# Attach response and error decorators to event function for convenience
event.response = response
event.error = error


# _register_schema_at_import is now replaced by register_event_schema from event_utils
# Keeping these for backward compatibility but they're deprecated
def _register_schema_at_import(
    topic: str,
    version: str,
    model: type[BaseModel],
    publisher_class: type,
) -> None:
    """
    Register schema immediately at import time.

    DEPRECATED: Use register_event_schema from event_utils instead.
    """
    register_event_schema(
        topic=topic,
        version=version,
        schema_model=model,
        publisher_class=publisher_class,
        mode="broadcast",
        description="",
        response_schema_model=None,
        error_schema_model=None,
        auto_register=True,
    )


def _cache_schema_for_later(
    topic: str,
    version: str,
    schema: dict,
    publisher_class: type,
) -> None:
    """Cache schema locally if registry is unavailable at import time."""
    # This is now handled by register_event_schema in event_utils
    pass


def _create_publish_method(
    topic: str,
    model: type[BaseModel],
    exchange_name: str,
) -> Callable:
    """Create publish method for broadcast events."""

    @classmethod
    def publish(cls, broker_url: str | None = None, **kwargs) -> str:
        # 1. Validate data
        validated = model(**kwargs)

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
        validated = model(**kwargs)

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


# _ensure_schema_registered is now replaced by ensure_schema_registered from event_utils
# Keeping this for backward compatibility but it's deprecated
def _ensure_schema_registered(
    topic: str,
    model: type[BaseModel],
    publisher_class: type,
) -> None:
    """Ensure schema is registered (safety net if import-time registration failed)."""
    version = getattr(publisher_class, "_celerysalt_version", "v1")
    mode = getattr(publisher_class, "_celerysalt_mode", "broadcast")
    ensure_schema_registered(
        topic=topic,
        version=version,
        schema_model=model,
        publisher_class=publisher_class,
        mode=mode,
        description="",
        response_schema_model=None,
        error_schema_model=None,
    )


def _validate_rpc_response(topic: str, response: Any) -> Any:
    """
    Validate RPC response against response or error schema if defined.

    Returns:
        Validated response as Pydantic model instance (response or error schema)
    """
    if response is None:
        return response

    # Check if response is a dict (from RPCError or handler return)
    if not isinstance(response, dict):
        # If it's already a Pydantic model, return as-is
        if isinstance(response, BaseModel):
            return response
        # Otherwise, try to convert
        response = response if isinstance(response, dict) else {"data": response}

    # Check if it's an error response (has error_code)
    is_error = "error_code" in response or "error_message" in response

    if is_error:
        # Validate against error schema if defined
        if topic in _rpc_error_schemas:
            error_model = _rpc_error_schemas[topic]
            try:
                return error_model(**response)
            except ValidationError as e:
                logger.warning(
                    f"Error response validation failed for {topic}: {e}. "
                    f"Returning raw response."
                )
                # Return raw response if validation fails
                return response
        else:
            # No error schema defined, return as-is
            return response
    else:
        # Validate against success response schema if defined
        if topic in _rpc_response_schemas:
            response_model = _rpc_response_schemas[topic]
            try:
                return response_model(**response)
            except ValidationError as e:
                logger.warning(
                    f"Response validation failed for {topic}: {e}. "
                    f"Returning raw response."
                )
                # Return raw response if validation fails
                return response
        else:
            # No response schema defined, return as-is
            return response


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
        **celery_options: All Celery task options
            - autoretry_for: Tuple of exceptions to retry
            - max_retries: Maximum retry attempts
            - retry_backoff: Enable exponential backoff
            - time_limit: Hard timeout (seconds)
            - soft_time_limit: Soft timeout (seconds)
            - rate_limit: Rate limit (e.g., '100/m')
            - priority: Task priority (0-9)
            - etc.

    Usage:
        @subscribe("user.signup.completed", autoretry_for=(Exception,))
        def send_welcome_email(data: UserSignup):
            send_email(data.email)

        @subscribe(UserSignupEvent)  # topic/version inferred from Meta
        def handler(evt: UserSignupEvent):
            do_something(evt.data.user_id)
    """

    def decorator(func: Callable) -> Callable:
        resolved_topic = topic
        resolved_version = version
        resolved_event_cls = event_cls

        # Allow @subscribe(EventClass) where EventClass is a SaltEvent subclass.
        if isinstance(resolved_topic, type):
            # Local import to avoid circulars at import time.
            from celery_salt.core.events import SaltEvent

            if issubclass(resolved_topic, SaltEvent):
                resolved_event_cls = resolved_topic
                resolved_topic = resolved_event_cls.Meta.topic
                if version == "latest":
                    resolved_version = getattr(resolved_event_cls.Meta, "version", "v1")

        # 1. Fetch schema from registry
        schema = _fetch_schema(resolved_topic, resolved_version)

        # 2. Create Pydantic model from schema
        validation_model = _create_model_from_schema(schema)

        # 3. Wrap handler with validation
        # Note: bind=True means Celery will pass task instance as first arg
        def validated_handler(self, raw_data: dict) -> Any:
            # self is the Celery task instance (because bind=True)
            # raw_data is the event data

            # Extract _tchu_meta if present (for RPC detection and protocol compatibility)
            meta = raw_data.pop("_tchu_meta", {})
            is_rpc = meta.get("is_rpc", False)

            # Validate data
            try:
                validated = validation_model(**raw_data)
            except ValidationError as e:
                logger.error(f"Validation failed for {topic}: {e}")
                raise

            # Call handler with validated data
            try:
                handler_arg: Any = validated
                if resolved_event_cls is not None:
                    # Wrap the validated payload in a full event instance.
                    # Note: event_cls.__init__ validates using its Schema too.
                    handler_arg = resolved_event_cls(**validated.model_dump())

                result = func(handler_arg)
            except RPCError as rpc_error:
                # Convert RPCError to error response dict
                if is_rpc:
                    error_response = rpc_error.to_response_dict()
                    logger.debug(
                        f"RPC error for {topic}: {rpc_error.error_code} - {rpc_error.error_message}"
                    )
                    # Validate against error schema if defined
                    if topic in _rpc_error_schemas:
                        error_model = _rpc_error_schemas[topic]
                        try:
                            return error_model(**error_response)
                        except ValidationError:
                            # If validation fails, return raw error dict
                            return error_response
                    return error_response
                else:
                    # For broadcast events, re-raise the exception
                    raise

            # For RPC, validate and return result
            if is_rpc:
                # If result is already a Pydantic model, convert to dict
                if isinstance(result, BaseModel):
                    result = result.model_dump()

                # Validate against response schema if defined
                if topic in _rpc_response_schemas and isinstance(result, dict):
                    response_model = _rpc_response_schemas[topic]
                    try:
                        return response_model(**result)
                    except ValidationError as e:
                        logger.warning(
                            f"Response validation failed for {topic}: {e}. "
                            f"Returning raw response."
                        )
                        # Return raw response if validation fails
                        return result

                return result

            return None

        # 4. Register as Celery task
        from celery import shared_task

        task = shared_task(
            name=f"celery_salt.{resolved_topic}.{func.__name__}",
            bind=True,  # Always bind to get task instance
            **celery_options,
        )(validated_handler)

        # 5. Register handler in global registry (for queue binding)
        from celery_salt.integrations.registry import get_handler_registry

        registry = get_handler_registry()
        # Store version in metadata for version filtering
        metadata = {"version": resolved_version}
        registry.register_handler(resolved_topic, task, metadata=metadata)

        # 6. Track subscriber in database (if schema registry supports it)
        try:
            schema_registry = get_schema_registry()
            if hasattr(schema_registry, "track_subscriber"):
                schema_registry.track_subscriber(
                    topic=resolved_topic,
                    handler_name=func.__name__,
                )
        except Exception as e:
            logger.debug(f"Could not track subscriber: {e}")

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
