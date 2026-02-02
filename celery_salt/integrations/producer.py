"""
Producer for publishing events via Celery or directly via kombu.

Maintains protocol compatibility with tchu-tchu by using the same
exchange name and message format.

Works with or without Celery - falls back to kombu for serverless environments.

Django: Add 'celery_salt.django' to INSTALLED_APPS and set CELERY_APP = "myproject.celery:app"
so .publish() and .call() work from views with no extra code.
"""

import os
import uuid
from typing import Any

from celery_salt.core.decorators import (
    DEFAULT_DISPATCHER_TASK_NAME,
    DEFAULT_EXCHANGE_NAME,
)
from celery_salt.core.exceptions import (
    PublishError,
)
from celery_salt.core.exceptions import (
    TimeoutError as CelerySaltTimeoutError,
)
from celery_salt.logging.handlers import get_logger
from celery_salt.metrics.collectors import get_metrics_collector
from celery_salt.observability.opentelemetry import (
    inject_trace_context,
    set_publish_span_attributes,
)
from celery_salt.utils.json_encoder import dumps_message

logger = get_logger(__name__)

# Try to import Celery (optional for serverless)
try:
    from celery import current_app

    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    current_app = None

# Try to import kombu (required for serverless fallback)
try:
    from kombu import Connection, Exchange, Producer

    KOMBU_AVAILABLE = True
except ImportError:
    KOMBU_AVAILABLE = False

# Default Celery app (set by celery_salt.django AppConfig when CELERY_APP is in settings)
_default_celery_app: Any | None = None


def set_default_celery_app(app: Any | None) -> None:
    """Set the default Celery app. Called by celery_salt.django AppConfig; rarely needed otherwise."""
    global _default_celery_app
    _default_celery_app = app


def _resolve_app(celery_app: Any | None) -> Any | None:
    """Resolve Celery app: explicit arg, then default (from Django AppConfig), then current_app."""
    if celery_app is not None:
        return celery_app
    if _default_celery_app is not None:
        return _default_celery_app
    return current_app if CELERY_AVAILABLE else None


def _resolve_broker_url(broker_url: str | None, app: Any | None) -> str | None:
    """Resolve broker URL for kombu fallback: explicit, then app.conf, then env/settings."""
    if broker_url:
        return broker_url
    if app is not None:
        url = getattr(app.conf, "broker_url", None)
        if url:
            return url
    url = os.environ.get("CELERY_SALT_BROKER_URL") or os.environ.get("BROKER_URL")
    if url:
        return url
    try:
        from django.conf import settings

        return getattr(settings, "CELERY_BROKER_URL", None) or getattr(settings, "BROKER_URL", None)
    except (ImportError, RuntimeError):
        return None


def publish_event(
    topic: str,
    data: dict[str, Any],
    exchange_name: str = DEFAULT_EXCHANGE_NAME,
    is_rpc: bool = False,
    celery_app: Any | None = None,
    dispatcher_task_name: str = DEFAULT_DISPATCHER_TASK_NAME,
    broker_url: str | None = None,
    version: str | None = None,
    correlation_id: str | None = None,
    **publish_kwargs,
) -> str:
    """
    Publish an event to a topic (broadcast to all subscribers).

    Works with or without Celery:
    - With Celery: Uses Celery's send_task (preferred for long-running apps)
    - Without Celery: Uses kombu directly (for serverless environments)

    Protocol compatibility: Uses same exchange name and message format as tchu-tchu.

    Args:
        topic: Topic routing key (e.g., 'user.created', 'order.*')
        data: Message body (will be serialized)
        exchange_name: RabbitMQ exchange name (default: "tchu_events" for compatibility)
        is_rpc: Whether this is an RPC call (default: False)
        celery_app: Optional Celery app instance (uses current_app if None)
        dispatcher_task_name: Name of the dispatcher task
        broker_url: Optional broker URL for serverless mode (required if no Celery app)

    Returns:
        Message ID for tracking

    Raises:
        PublishError: If publishing fails
    """
    try:
        # Generate unique message ID
        message_id = str(uuid.uuid4())

        # Add _tchu_meta for protocol compatibility with tchu-tchu
        # Include version and correlation_id if provided (for observability/tracing)
        tchu_meta = {"is_rpc": is_rpc}
        if version:
            tchu_meta["version"] = version
        if correlation_id:
            tchu_meta["correlation_id"] = correlation_id
        inject_trace_context(tchu_meta)

        body_with_meta = {
            **data,
            "_tchu_meta": tchu_meta,
        }
        serialized_body = dumps_message(body_with_meta)

        # If broker_url is explicitly provided, prefer kombu (for examples and serverless)
        # This ensures messages go to the topic exchange, not Celery's default direct exchange
        if broker_url is not None:
            if not KOMBU_AVAILABLE:
                raise PublishError(
                    "broker_url provided but kombu not installed. "
                    "Install kombu: pip install kombu"
                )

            # Use kombu directly (ensures topic exchange routing)
            _publish_via_kombu(
                broker_url=broker_url,
                exchange_name=exchange_name,
                routing_key=topic,
                message_body=serialized_body,
                dispatcher_task_name=dispatcher_task_name,
                message_id=message_id,
            )

            get_metrics_collector().record_message_published(
                topic, task_id=message_id, metadata={"transport": "kombu"}
            )
            set_publish_span_attributes(topic, message_id=message_id, is_rpc=is_rpc)
            _log_extra = {"routing_key": topic, "message_id": message_id}
            if correlation_id:
                _log_extra["correlation_id"] = correlation_id
            if version:
                _log_extra["version"] = version
            logger.info(
                f"Published message {message_id} to routing key '{topic}' (via kombu)",
                extra=_log_extra,
            )

            return message_id

        # Try Celery (if available and no broker_url provided)
        app = _resolve_app(celery_app)
        if CELERY_AVAILABLE and app is not None:
            try:
                routes = getattr(app.conf, "task_routes", {})
                dispatcher_route = routes.get(dispatcher_task_name, {})

                if (
                    dispatcher_route.get("exchange") == exchange_name
                    and dispatcher_route.get("exchange_type") == "topic"
                ):
                    app.send_task(
                        dispatcher_task_name,
                        args=[serialized_body],
                        kwargs={"routing_key": topic},
                        routing_key=topic,
                        task_id=message_id,
                    )
                    get_metrics_collector().record_message_published(
                        topic, task_id=message_id, metadata={"transport": "celery"}
                    )
                    set_publish_span_attributes(
                        topic, message_id=message_id, is_rpc=is_rpc
                    )
                    _log_extra = {"routing_key": topic, "message_id": message_id}
                    if correlation_id:
                        _log_extra["correlation_id"] = correlation_id
                    if version:
                        _log_extra["version"] = version
                    logger.info(
                        f"Published message {message_id} to routing key '{topic}' (via Celery)",
                        extra=_log_extra,
                    )
                    return message_id

                logger.debug(
                    f"Celery routing not configured for topic exchange, using kombu. "
                    f"Configure task_routes for {dispatcher_task_name} to use topic exchange."
                )
                raise AttributeError("Topic exchange routing not configured")
            except (AttributeError, RuntimeError) as e:
                # Celery app not available or routing not configured, fall through to kombu
                logger.debug(
                    f"Celery publish not available, falling back to kombu: {e}"
                )
                pass

        # Fallback to kombu (serverless or topic routing not configured)
        if not KOMBU_AVAILABLE:
            raise PublishError(
                "Cannot publish: Celery not available and kombu not installed. "
                "Install kombu for serverless support: pip install kombu"
            )

        resolved_broker_url = _resolve_broker_url(broker_url, app)
        if resolved_broker_url is None:
            raise PublishError(
                "broker_url required for publish. "
                "Django: add 'celery_salt.django' to INSTALLED_APPS and set CELERY_APP, "
                "or set CELERY_BROKER_URL / CELERY_SALT_BROKER_URL."
            )

        _publish_via_kombu(
            broker_url=resolved_broker_url,
            exchange_name=exchange_name,
            routing_key=topic,
            message_body=serialized_body,
            dispatcher_task_name=dispatcher_task_name,
            message_id=message_id,
        )

        get_metrics_collector().record_message_published(
            topic, task_id=message_id, metadata={"transport": "kombu_serverless"}
        )
        set_publish_span_attributes(topic, message_id=message_id, is_rpc=is_rpc)
        _log_extra = {"routing_key": topic, "message_id": message_id}
        if correlation_id:
            _log_extra["correlation_id"] = correlation_id
        if version:
            _log_extra["version"] = version
        logger.info(
            f"Published message {message_id} to routing key '{topic}' (via kombu/serverless)",
            extra=_log_extra,
        )

        return message_id

    except PublishError:
        raise
    except Exception as e:
        logger.error(
            f"Failed to publish message to routing key '{topic}': {e}", exc_info=True
        )
        raise PublishError(f"Failed to publish message: {e}")


def _publish_via_kombu(
    broker_url: str,
    exchange_name: str,
    routing_key: str,
    message_body: str,
    dispatcher_task_name: str,
    message_id: str,
) -> None:
    """Publish message directly via kombu (serverless mode)."""
    connection = None
    try:
        # Create connection
        connection = Connection(broker_url)
        connection.connect()

        # Create exchange
        exchange = Exchange(exchange_name, type="topic", durable=True)

        # Create producer
        producer = Producer(connection, exchange=exchange, serializer="json")

        # Create task message (mimics Celery's task format)
        task_message = {
            "id": message_id,
            "task": dispatcher_task_name,
            "args": [message_body],
            "kwargs": {"routing_key": routing_key},
        }

        # Publish
        producer.publish(
            task_message,
            routing_key=routing_key,
            declare=[exchange],
        )

    finally:
        if connection:
            connection.close()


def call_rpc(
    topic: str,
    data: dict[str, Any],
    timeout: int = 30,
    exchange_name: str = DEFAULT_EXCHANGE_NAME,
    celery_app: Any | None = None,
    dispatcher_task_name: str = DEFAULT_DISPATCHER_TASK_NAME,
    allow_join: bool = False,
    version: str | None = None,
    correlation_id: str | None = None,
    **call_kwargs,
) -> Any:
    """
    Send a message and wait for a response (RPC-style).

    Protocol compatibility: Uses same exchange name and message format as tchu-tchu.

    Args:
        topic: Topic routing key (e.g., 'user.validate')
        data: Message body (will be serialized)
        timeout: Timeout in seconds to wait for response (default: 30)
        exchange_name: RabbitMQ exchange name (default: "tchu_events" for compatibility)
        celery_app: Optional Celery app instance (uses current_app if None)
        dispatcher_task_name: Name of the dispatcher task
        allow_join: Allow calling result.get() from within a task (default: False)

    Returns:
        Response from the handler

    Raises:
        PublishError: If publishing fails
        CelerySaltTimeoutError: If no response received within timeout
    """
    import time

    start_time = time.time()

    # RPC requires Celery (for result backend)
    if not CELERY_AVAILABLE:
        raise PublishError(
            "RPC calls require Celery (for result backend). "
            "Install celery for RPC support: pip install celery"
        )

    app = _resolve_app(celery_app)
    if app is None:
        raise PublishError("Celery app required for RPC calls")

    try:
        # Generate unique message ID
        message_id = str(uuid.uuid4())

        # Add _tchu_meta for protocol compatibility
        # Include version and correlation_id if provided (for observability/tracing)
        tchu_meta = {"is_rpc": True}
        if version:
            tchu_meta["version"] = version
        if correlation_id:
            tchu_meta["correlation_id"] = correlation_id
        inject_trace_context(tchu_meta)

        body_with_meta = {
            **data,
            "_tchu_meta": tchu_meta,
        }
        serialized_body = dumps_message(body_with_meta)

        # Check if routing is configured for topic exchange
        # If not, the message won't reach the topic exchange
        routes = getattr(app.conf, "task_routes", {})
        dispatcher_route = routes.get(dispatcher_task_name, {})

        if (
            dispatcher_route.get("exchange") != exchange_name
            or dispatcher_route.get("exchange_type") != "topic"
        ):
            logger.warning(
                f"RPC routing not configured for topic exchange. "
                f"Configure task_routes for {dispatcher_task_name} to use topic exchange. "
                f"Falling back to default routing (may not work)."
            )

        # Send task to dispatcher and wait for result
        result = app.send_task(
            dispatcher_task_name,
            args=[serialized_body],
            kwargs={"routing_key": topic},
            routing_key=topic,  # This will be used with the configured topic exchange
            task_id=message_id,
        )

        _log_extra = {"routing_key": topic, "message_id": message_id}
        if correlation_id:
            _log_extra["correlation_id"] = correlation_id
        if version:
            _log_extra["version"] = version
        logger.info(
            f"RPC call {message_id} sent to routing key '{topic}'",
            extra=_log_extra,
        )

        try:
            # Wait for result with timeout
            if allow_join:
                from celery.result import allow_join_result

                with allow_join_result():
                    response = result.get(timeout=timeout)
            else:
                response = result.get(timeout=timeout)

            execution_time = time.time() - start_time
            get_metrics_collector().record_rpc_call(
                topic,
                execution_time,
                task_id=message_id,
                metadata={"side": "client"},
            )
            set_publish_span_attributes(topic, message_id=message_id, is_rpc=True)

            # Extract the actual result from the dispatcher response
            if isinstance(response, dict):
                # Check if there were no handlers
                if response.get("status") == "no_handlers":
                    logger.warning(
                        f"RPC call {message_id} failed: no handlers for routing key '{topic}'",
                        extra={
                            "routing_key": topic,
                            "message_id": message_id,
                            "execution_time": execution_time,
                        },
                    )
                    raise PublishError(f"No handlers found for routing key '{topic}'")

                results = response.get("results", [])
                if results:
                    first_result = results[0]
                    if first_result.get("status") == "success":
                        logger.info(
                            f"RPC call {message_id} completed in {execution_time:.2f} seconds",
                            extra={
                                "routing_key": topic,
                                "message_id": message_id,
                                "execution_time": execution_time,
                            },
                        )
                        return first_result.get("result")
                    else:
                        error = first_result.get("error", "Unknown error")
                        handler_name = first_result.get("handler", "unknown")
                        logger.warning(
                            f"RPC call {message_id} failed: handler '{handler_name}' raised: {error}",
                            extra={
                                "routing_key": topic,
                                "message_id": message_id,
                                "execution_time": execution_time,
                                "handler": handler_name,
                                "error": error,
                            },
                        )
                        raise PublishError(f"Handler '{handler_name}' failed: {error}")
                else:
                    logger.warning(
                        f"RPC call {message_id} failed: no results from handler for routing key '{topic}'",
                        extra={
                            "routing_key": topic,
                            "message_id": message_id,
                            "execution_time": execution_time,
                        },
                    )
                    raise PublishError(
                        f"No results returned from handler for routing key '{topic}'"
                    )

            # If response is not a dict, return it as-is (legacy)
            logger.info(
                f"RPC call {message_id} completed in {execution_time:.2f} seconds",
                extra={
                    "routing_key": topic,
                    "message_id": message_id,
                    "execution_time": execution_time,
                },
            )
            return response

        except Exception as e:
            # Check if it's a timeout
            if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                raise CelerySaltTimeoutError(
                    f"No response received within {timeout} seconds for routing key '{topic}'"
                )
            raise PublishError(f"RPC call failed: {e}")

    except (PublishError, CelerySaltTimeoutError):
        raise
    except Exception as e:
        logger.error(
            f"Failed to execute RPC call to routing key '{topic}': {e}", exc_info=True
        )
        raise PublishError(f"Failed to execute RPC call: {e}")
