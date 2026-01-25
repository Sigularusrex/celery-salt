"""
Shared utilities for both @event decorator and SaltEvent class.

This module provides common functionality to minimize code duplication
between the decorator-based and class-based event APIs.
"""

from typing import Any

from pydantic import BaseModel, ValidationError

from celery_salt.core.exceptions import (
    SchemaConflictError,
    SchemaRegistryUnavailableError,
)
from celery_salt.core.registry import get_schema_registry
from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)


def register_event_schema(
    topic: str,
    version: str,
    schema_model: type[BaseModel],
    publisher_class: type,
    mode: str = "broadcast",
    description: str = "",
    response_schema_model: type[BaseModel] | None = None,
    error_schema_model: type[BaseModel] | None = None,
    auto_register: bool = True,
) -> None:
    """
    Register an event schema to the registry.

    Shared utility used by both @event decorator and SaltEvent class.

    Args:
        topic: Event topic
        version: Schema version
        schema_model: Pydantic model for the event schema
        publisher_class: The event class being registered
        mode: "broadcast" or "rpc"
        description: Human-readable description
        response_schema_model: Optional Pydantic model for RPC response
        error_schema_model: Optional Pydantic model for RPC error
        auto_register: If False, skip registration (for manual control)

    Raises:
        SchemaConflictError: If schema conflicts with existing schema
    """
    if not auto_register:
        return

    try:
        registry = get_schema_registry()
        json_schema = schema_model.model_json_schema()

        response_schema = None
        error_schema = None

        if response_schema_model:
            response_schema = response_schema_model.model_json_schema()
        if error_schema_model:
            error_schema = error_schema_model.model_json_schema()

        # Attempt to register
        result = registry.register_schema(
            topic=topic,
            version=version,
            schema=json_schema,
            publisher_module=publisher_class.__module__,
            publisher_class=publisher_class.__name__,
            mode=mode,
            description=description,
            response_schema=response_schema,
            error_schema=error_schema,
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
            topic,
            version,
            schema_model,
            publisher_class,
            mode,
            description,
            response_schema_model,
            error_schema_model,
        )
    except SchemaConflictError:
        # Re-raise schema conflicts - these are programming errors that should fail fast
        raise
    except Exception as e:
        logger.error(f"Failed to register schema {topic}: {e}", exc_info=True)
        # Don't raise - allow graceful degradation


def ensure_schema_registered(
    topic: str,
    version: str,
    schema_model: type[BaseModel],
    publisher_class: type,
    mode: str = "broadcast",
    description: str = "",
    response_schema_model: type[BaseModel] | None = None,
    error_schema_model: type[BaseModel] | None = None,
) -> None:
    """
    Ensure schema is registered (safety net if import-time registration failed).

    Shared utility used by both @event decorator and SaltEvent class.
    """
    try:
        registry = get_schema_registry()
        json_schema = schema_model.model_json_schema()

        response_schema = None
        error_schema = None

        if response_schema_model:
            response_schema = response_schema_model.model_json_schema()
        if error_schema_model:
            error_schema = error_schema_model.model_json_schema()

        registry.register_schema(
            topic=topic,
            version=version,
            schema=json_schema,
            publisher_module=publisher_class.__module__,
            publisher_class=publisher_class.__name__,
            mode=mode,
            description=description,
            response_schema=response_schema,
            error_schema=error_schema,
        )
    except Exception as e:
        logger.warning(f"Failed to ensure schema registration for {topic}: {e}")


def validate_and_publish(
    topic: str,
    data: dict[str, Any],
    schema_model: type[BaseModel],
    exchange_name: str = "tchu_events",
    broker_url: str | None = None,
    version: str | None = None,
    **publish_kwargs,
) -> str:
    """
    Validate data against schema and publish to broker.

    Shared utility used by both @event decorator and SaltEvent class.

    Args:
        topic: Event topic
        data: Event data (dict)
        schema_model: Pydantic model to validate against
        exchange_name: RabbitMQ exchange name
        broker_url: Optional broker URL
        version: Optional schema version (for version filtering)
        **publish_kwargs: Additional publish options

    Returns:
        Message ID
    """
    from celery_salt.integrations.producer import publish_event

    # Validate data
    validated = schema_model(**data)

    # Include version in publish_kwargs if provided
    if version:
        publish_kwargs["version"] = version

    # Publish to broker
    return publish_event(
        topic=topic,
        data=validated.model_dump(),
        exchange_name=exchange_name,
        is_rpc=False,
        broker_url=broker_url,
        **publish_kwargs,
    )


def validate_and_call_rpc(
    topic: str,
    data: dict[str, Any],
    schema_model: type[BaseModel],
    timeout: int = 30,
    exchange_name: str = "tchu_events",
    response_schema_model: type[BaseModel] | None = None,
    error_schema_model: type[BaseModel] | None = None,
    version: str | None = None,
    **call_kwargs,
) -> Any:
    """
    Validate data, make RPC call, and validate response.

    Shared utility used by both @event decorator and SaltEvent class.

    Args:
        topic: RPC topic
        data: Request data (dict)
        schema_model: Pydantic model to validate request
        timeout: Response timeout
        exchange_name: RabbitMQ exchange name
        response_schema_model: Optional Pydantic model for response validation
        error_schema_model: Optional Pydantic model for error validation
        version: Optional schema version (for version filtering)
        **call_kwargs: Additional call options

    Returns:
        Validated response (Pydantic model or dict)
    """
    from celery_salt.integrations.producer import call_rpc

    # Validate request
    validated = schema_model(**data)

    # Include version in call_kwargs if provided
    if version:
        call_kwargs["version"] = version

    # Make RPC call
    response_data = call_rpc(
        topic=topic,
        data=validated.model_dump(),
        timeout=timeout,
        exchange_name=exchange_name,
        **call_kwargs,
    )

    # Validate response using shared utility
    return _validate_rpc_response_with_models(
        topic=topic,
        response=response_data,
        response_schema_model=response_schema_model,
        error_schema_model=error_schema_model,
    )


def _validate_rpc_response_with_models(
    topic: str,
    response: Any,
    response_schema_model: type[BaseModel] | None = None,
    error_schema_model: type[BaseModel] | None = None,
) -> Any:
    """
    Validate RPC response against response or error schema if provided.

    Args:
        topic: RPC topic (for logging)
        response: Response data (dict or Pydantic model)
        response_schema_model: Optional Pydantic model for success response
        error_schema_model: Optional Pydantic model for error response

    Returns:
        Validated response (Pydantic model or dict)
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
        if error_schema_model:
            try:
                return error_schema_model(**response)
            except ValidationError as e:
                logger.warning(
                    f"Error response validation failed for {topic}: {e}. "
                    f"Returning raw response."
                )
                return response
        return response
    else:
        # Validate against success response schema if defined
        if response_schema_model:
            try:
                return response_schema_model(**response)
            except ValidationError as e:
                logger.warning(
                    f"Response validation failed for {topic}: {e}. "
                    f"Returning raw response."
                )
                return response
        return response


def _cache_schema_for_later(
    topic: str,
    version: str,
    schema_model: type[BaseModel],
    publisher_class: type,
    mode: str,
    description: str,
    response_schema_model: type[BaseModel] | None,
    error_schema_model: type[BaseModel] | None,
) -> None:
    """Cache schema locally if registry is unavailable at import time."""
    if not hasattr(_cache_schema_for_later, "pending_schemas"):
        _cache_schema_for_later.pending_schemas = []

    _cache_schema_for_later.pending_schemas.append(
        {
            "topic": topic,
            "version": version,
            "schema_model": schema_model,
            "publisher_class": publisher_class,
            "mode": mode,
            "description": description,
            "response_schema_model": response_schema_model,
            "error_schema_model": error_schema_model,
        }
    )
