"""
Core decorators for CelerySalt: @event and @subscribe.

These decorators provide a Pydantic-based API for defining and subscribing to events,
with import-time schema registration for early error detection.
"""

from typing import Type, Any, Callable
from pydantic import BaseModel, create_model, ValidationError

from celery_salt.core.exceptions import (
    SchemaConflictError,
    SchemaRegistryUnavailableError,
    RPCError,
)
from celery_salt.core.registry import get_schema_registry
from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)

# Protocol compatibility: Keep exchange name for backward compatibility with tchu-tchu
DEFAULT_EXCHANGE_NAME = "tchu_events"
DEFAULT_DISPATCHER_TASK_NAME = "celery_salt.dispatch_event"

# Global registry for RPC response/error schemas
_rpc_response_schemas: dict[str, Type[BaseModel]] = {}
_rpc_error_schemas: dict[str, Type[BaseModel]] = {}


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

    def decorator(cls: Type) -> Type:
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
        _register_schema_at_import(
            topic=topic,
            version=version,
            model=pydantic_model,
            publisher_class=cls,
        )

        # Add metadata to class
        cls._celerysalt_topic = topic
        cls._celerysalt_mode = mode
        cls._celerysalt_version = version
        cls._celerysalt_model = pydantic_model
        cls._celerysalt_exchange = exchange_name

        # Add publish method for broadcast events
        if mode == "broadcast":
            cls.publish = classmethod(
                _create_publish_method(topic, pydantic_model, exchange_name)
            )
        elif mode == "rpc":
            cls.call = classmethod(
                _create_rpc_method(topic, pydantic_model, exchange_name)
            )

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

    def decorator(cls: Type) -> Type:
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

    def decorator(cls: Type) -> Type:
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


def _register_schema_at_import(
    topic: str,
    version: str,
    model: Type[BaseModel],
    publisher_class: Type,
) -> None:
    """
    Register schema immediately at import time.

    Benefits:
    - Schemas available before first publish
    - Early detection of schema conflicts
    - Complete event catalog visible
    - Can validate in CI/CD before deployment
    """
    try:
        registry = get_schema_registry()

        # Extract JSON schema from Pydantic model
        json_schema = model.model_json_schema()

        # Attempt to register
        result = registry.register_schema(
            topic=topic,
            version=version,
            schema=json_schema,
            publisher_module=publisher_class.__module__,
            publisher_class=publisher_class.__name__,
        )

        if result.get("created"):
            logger.info(f"✓ Registered schema: {topic} (v{version})")
        else:
            # Schema already exists - validate it matches
            existing_schema = result.get("existing_schema")
            if existing_schema != json_schema:
                logger.error(
                    f"✗ Schema conflict for {topic} (v{version})\n"
                    f"  Existing schema differs from new definition!"
                )
                raise SchemaConflictError(topic, version)
            else:
                logger.debug(f"Schema already registered: {topic} (v{version})")

    except SchemaRegistryUnavailableError as e:
        # Registry unavailable (network issue, DB down, etc.)
        # Cache schema locally for later registration
        logger.warning(
            f"⚠ Could not register schema {topic} at import time: {e}\n"
            f"  Schema cached for registration on first publish."
        )
        _cache_schema_for_later(
            topic, version, model.model_json_schema(), publisher_class
        )
    except Exception as e:
        logger.error(f"Failed to register schema {topic}: {e}", exc_info=True)
        # Don't raise - allow graceful degradation


def _cache_schema_for_later(
    topic: str,
    version: str,
    schema: dict,
    publisher_class: Type,
) -> None:
    """Cache schema locally if registry is unavailable at import time."""
    if not hasattr(_cache_schema_for_later, "pending_schemas"):
        _cache_schema_for_later.pending_schemas = []

    _cache_schema_for_later.pending_schemas.append(
        {
            "topic": topic,
            "version": version,
            "schema": schema,
            "publisher_module": publisher_class.__module__,
            "publisher_class": publisher_class.__name__,
        }
    )


def _create_publish_method(
    topic: str,
    model: Type[BaseModel],
    exchange_name: str,
) -> Callable:
    """Create publish method for broadcast events."""

    @classmethod
    def publish(cls, broker_url: str | None = None, **kwargs) -> str:
        # 1. Validate data
        validated = model(**kwargs)

        # 2. Ensure schema registered (safety net if import-time registration failed)
        _ensure_schema_registered(topic, model, cls)

        # 3. Publish to broker
        from celery_salt.integrations.producer import publish_event

        return publish_event(
            topic=topic,
            data=validated.model_dump(),
            exchange_name=exchange_name,
            is_rpc=False,
            broker_url=broker_url,
        )

    return publish


def _create_rpc_method(
    topic: str,
    model: Type[BaseModel],
    exchange_name: str,
) -> Callable:
    """Create call method for RPC events."""

    @classmethod
    def call(cls, timeout: int = 30, **kwargs) -> Any:
        # 1. Validate request
        validated = model(**kwargs)

        # 2. Register schema if needed
        _ensure_schema_registered(topic, model, cls)

        # 3. Make RPC call
        from celery_salt.integrations.producer import call_rpc

        response = call_rpc(
            topic=topic,
            data=validated.model_dump(),
            timeout=timeout,
            exchange_name=exchange_name,
        )

        # 4. Validate response (checks for error vs success response schemas)
        return _validate_rpc_response(topic, response)

    return call


def _ensure_schema_registered(
    topic: str,
    model: Type[BaseModel],
    publisher_class: Type,
) -> None:
    """Ensure schema is registered (safety net if import-time registration failed)."""
    try:
        registry = get_schema_registry()
        json_schema = model.model_json_schema()

        registry.register_schema(
            topic=topic,
            version=getattr(publisher_class, "_celerysalt_version", "v1"),
            schema=json_schema,
            publisher_module=publisher_class.__module__,
            publisher_class=publisher_class.__name__,
        )
    except Exception as e:
        logger.warning(f"Failed to ensure schema registration for {topic}: {e}")


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
    topic: str,
    version: str = "latest",
    **celery_options,
) -> Callable:
    """
    Decorator to register an event handler.

    Handler becomes a Celery task with all Celery features available.

    Args:
        topic: Event topic pattern (supports wildcards: user.*, #)
        version: Schema version to validate against (default: "latest")
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
    """

    def decorator(func: Callable) -> Callable:
        # 1. Fetch schema from registry
        schema = _fetch_schema(topic, version)

        # 2. Create Pydantic model from schema
        ValidationModel = _create_model_from_schema(schema)

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
                validated = ValidationModel(**raw_data)
            except ValidationError as e:
                logger.error(f"Validation failed for {topic}: {e}")
                raise

            # Call handler with validated data
            try:
                result = func(validated)
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
            name=f"celery_salt.{topic}.{func.__name__}",
            bind=True,  # Always bind to get task instance
            **celery_options,
        )(validated_handler)

        # 5. Register handler in global registry (for queue binding)
        from celery_salt.integrations.registry import get_handler_registry

        registry = get_handler_registry()
        registry.register_handler(topic, task)

        # 6. Track subscriber in database (if schema registry supports it)
        try:
            schema_registry = get_schema_registry()
            if hasattr(schema_registry, "track_subscriber"):
                schema_registry.track_subscriber(
                    topic=topic,
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


def _create_model_from_schema(schema: dict) -> Type[BaseModel]:
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


def _json_schema_type_to_python(field_schema: dict) -> Type:
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
