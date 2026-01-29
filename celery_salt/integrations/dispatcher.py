"""
Event dispatcher for CelerySalt.

Routes incoming messages to registered handlers based on routing keys.
Maintains protocol compatibility with tchu-tchu.
"""

import json
import time
from typing import Any

from pydantic import BaseModel

from celery_salt.core.decorators import DEFAULT_DISPATCHER_TASK_NAME
from celery_salt.core.versioning import (
    compare_versions,
    is_version_compatible,
)
from celery_salt.integrations.registry import get_handler_registry
from celery_salt.logging.handlers import (
    get_logger,
    log_dispatch_completed,
    log_error,
    log_handler_executed,
    log_message_received,
)
from celery_salt.metrics.collectors import get_metrics_collector
from celery_salt.observability.opentelemetry import set_dispatch_span_attributes
from celery_salt.utils.json_encoder import loads_message

logger = get_logger(__name__)


def create_topic_dispatcher(
    celery_app: Any,
    task_name: str = DEFAULT_DISPATCHER_TASK_NAME,
) -> Any:
    """
    Create a Celery task that dispatches messages to local handlers.

    Protocol compatibility: Handles both celery-salt and tchu-tchu message formats.

    Args:
        celery_app: Celery app instance
        task_name: Name for the dispatcher task

    Returns:
        Celery task function that dispatches to local handlers
    """
    registry = get_handler_registry()

    @celery_app.task(name=task_name, bind=True)
    def dispatch_event(self, message_body: str, routing_key: str | None = None):
        """
        Dispatcher task that routes messages to local handlers.

        Execution mode is determined by _tchu_meta.is_rpc in the message:
        - is_rpc=True: Direct call (must return result to caller)
        - is_rpc=False: Async dispatch via .delay() (fire-and-forget)

        Protocol compatibility: Handles messages from both celery-salt and tchu-tchu.
        """
        # Extract routing key from task request if not provided
        if routing_key is None:
            routing_key = self.request.get("routing_key", "unknown")

        message_id = self.request.id
        started_at = time.perf_counter()
        log_message_received(logger, routing_key, message_id)

        metrics = get_metrics_collector()
        metrics.record_message_received(routing_key, task_id=message_id)

        try:
            # Deserialize message
            if isinstance(message_body, str):
                try:
                    deserialized = loads_message(message_body)
                except Exception:
                    # If deserialization fails, try standard JSON
                    deserialized = json.loads(message_body)
            else:
                deserialized = message_body

            # Extract message type, version, and correlation_id from _tchu_meta
            # Protocol compatibility: Handle both celery-salt and tchu-tchu messages
            message_version = None
            correlation_id = None
            if "_tchu_meta" not in deserialized:
                # No metadata = old 2.x message or tchu-tchu message, default to direct call
                is_rpc = True
                logger.debug(
                    f"No _tchu_meta found (tchu-tchu publisher?), using direct call for '{routing_key}'"
                )
            else:
                tchu_meta = deserialized["_tchu_meta"]
                is_rpc = tchu_meta.get("is_rpc", False)
                message_version = tchu_meta.get("version")
                correlation_id = tchu_meta.get("correlation_id")

            # Get all matching handlers for this routing key
            all_handlers = registry.get_handlers(routing_key)

            # Filter handlers by version compatibility
            # Rules:
            # - Handler with specific version receives same or newer message versions (backward compatible)
            # - Handler with "latest" receives all messages
            # - Warn if handler is on older version than message (subscriber needs to upgrade)
            handlers = []
            for handler_info in all_handlers:
                handler_version = handler_info.get("metadata", {}).get(
                    "version", "latest"
                )

                # Normalize handler version
                if handler_version is None:
                    handler_version = "latest"

                # Case 1: Message has no version (legacy/tchu-tchu compatibility)
                if message_version is None:
                    # Only handlers with "latest" should receive it
                    if handler_version == "latest":
                        handlers.append(handler_info)
                    continue

                # Case 2: Handler subscribes to "latest"
                if handler_version == "latest":
                    # "latest" handlers receive all messages
                    handlers.append(handler_info)
                    continue

                # Case 3: Handler subscribes to specific version
                # Handler receives messages with same or newer versions (backward compatible)
                # Handler does NOT receive messages with older versions (defensive check)
                if is_version_compatible(handler_version, message_version):
                    # Check if handler is on older version (for warning)
                    comparison = compare_versions(handler_version, message_version)
                    if comparison < 0:
                        # Handler version < message version (handler is on older version)
                        logger.warning(
                            f"Handler '{handler_info.get('name', 'unknown')}' subscribed to "
                            f"{handler_version} is processing {message_version} message for topic "
                            f"'{routing_key}'. Subscriber is on an older version. "
                            f"Consider upgrading subscriber to {message_version}."
                        )
                    handlers.append(handler_info)

            if not handlers:
                duration_seconds = time.perf_counter() - started_at
                metrics.record_error(routing_key, "no_handlers", task_id=message_id)
                set_dispatch_span_attributes(
                    routing_key,
                    task_id=message_id,
                    is_rpc=is_rpc,
                    handlers_executed=0,
                    duration_seconds=duration_seconds,
                    status="no_handlers",
                )
                log_dispatch_completed(
                    logger,
                    routing_key,
                    message_id,
                    duration_seconds,
                    is_rpc=False,
                    handlers_executed=0,
                    status="no_handlers",
                    correlation_id=correlation_id,
                )
                logger.warning(
                    f"No local handlers found for routing key '{routing_key}'",
                    extra={"routing_key": routing_key},
                )
                return {"status": "no_handlers", "routing_key": routing_key}

            # Execute all matching handlers
            results = []
            for handler_info in handlers:
                handler_task = handler_info["function"]  # This is a Celery task
                handler_name = handler_info["name"]
                handler_id = handler_info["id"]

                try:
                    if is_rpc:
                        # RPC: Must call directly (synchronously) to return result to caller
                        # Cannot use apply_async().get() because we're already in a task
                        # For bound tasks (bind=True), we need to access the underlying function
                        # and call it with a mock task instance

                        # RPC: Execute synchronously in the same process
                        # For bound tasks (bind=True), we need to access the underlying function
                        # and call it with a mock task instance
                        import inspect

                        # Get the actual function from the Celery task
                        # For bound tasks, the function is the task's run method
                        sig = inspect.signature(handler_task)
                        params = list(sig.parameters.keys())

                        if params and params[0] == "self":
                            # Bound task - create minimal task instance
                            class MockTaskInstance:
                                def __init__(self, task_id: str):
                                    self.request = type(
                                        "obj",
                                        (object,),
                                        {
                                            "id": task_id,
                                            "retries": 0,
                                            "is_eager": False,
                                        },
                                    )()

                            # Get the underlying function (the validated_handler)
                            # It's stored in the task's run attribute
                            func = handler_task.run
                            mock_task = MockTaskInstance(
                                f"{message_id}:rpc:{handler_id}"
                            )
                            result = func(mock_task, deserialized)
                        else:
                            # Not bound, call directly
                            result = handler_task(deserialized)

                        # Result is already validated by the handler wrapper
                        # It may be a Pydantic model (response or error schema)
                        # Convert to dict for serialization if needed
                        if isinstance(result, BaseModel):
                            result = result.model_dump()

                        results.append(
                            {
                                "handler": handler_name,
                                "status": "success",
                                "result": result,
                            }
                        )
                        log_handler_executed(
                            logger, handler_name, routing_key, message_id
                        )
                    else:
                        # Broadcast: Dispatch as async Celery task
                        handler_task_id = f"{message_id}:{handler_id}"

                        async_result = handler_task.apply_async(
                            args=[deserialized],
                            task_id=handler_task_id,
                        )
                        results.append(
                            {
                                "handler": handler_name,
                                "status": "dispatched",
                                "task_id": async_result.id,
                            }
                        )
                        logger.debug(
                            f"Dispatched handler '{handler_name}' (task_id={async_result.id})",
                            extra={
                                "routing_key": routing_key,
                                "task_id": async_result.id,
                            },
                        )

                except Exception as e:
                    metrics.record_error(
                        routing_key,
                        type(e).__name__,
                        task_id=message_id,
                        metadata={"handler": handler_name},
                    )
                    log_error(
                        logger, f"Handler '{handler_name}' failed", e, routing_key
                    )
                    results.append(
                        {
                            "handler": handler_name,
                            "status": "error",
                            "error": str(e),
                        }
                    )

            duration_seconds = time.perf_counter() - started_at
            if is_rpc:
                metrics.record_rpc_call(
                    routing_key,
                    duration_seconds,
                    task_id=message_id,
                    metadata={"handlers_executed": len(results)},
                )
            set_dispatch_span_attributes(
                routing_key,
                task_id=message_id,
                is_rpc=is_rpc,
                handlers_executed=len(results),
                duration_seconds=duration_seconds,
                status="completed",
            )
            log_dispatch_completed(
                logger,
                routing_key,
                message_id,
                duration_seconds,
                is_rpc,
                len(results),
                status="completed",
                correlation_id=correlation_id,
            )

            return {
                "status": "completed",
                "routing_key": routing_key,
                "is_rpc": is_rpc,
                "handlers_executed": len(results),
                "results": results,
            }

        except Exception as e:
            duration_seconds = time.perf_counter() - started_at
            metrics.record_error(
                routing_key,
                type(e).__name__,
                task_id=message_id,
            )
            set_dispatch_span_attributes(
                routing_key,
                task_id=message_id,
                is_rpc=False,
                duration_seconds=duration_seconds,
                status="error",
            )
            log_error(
                logger, f"Failed to dispatch event for '{routing_key}'", e, routing_key
            )
            raise

    return dispatch_event


def get_subscribed_routing_keys(
    exclude_patterns: list[str] | None = None,
    celery_app: Any | None = None,
    force_import: bool = True,
) -> list[str]:
    """
    Get all routing keys that have handlers registered.

    Useful for auto-configuring Celery queue bindings.

    Args:
        exclude_patterns: Optional list of patterns to exclude (e.g., ['rpc.*'])
        celery_app: Optional Celery app instance to force task discovery
        force_import: If True and celery_app provided, forces immediate task import

    Returns:
        List of routing keys with registered handlers
    """
    import fnmatch

    # Force task discovery if Celery app provided
    if celery_app and force_import:
        try:
            celery_app.loader.import_default_modules()
        except Exception as e:
            logger.warning(
                f"Failed to force import tasks from Celery app: {e}. "
                f"Handlers may not be registered yet."
            )

    from celery_salt.integrations.registry import get_handler_registry

    registry = get_handler_registry()
    all_keys = registry.get_all_routing_keys()

    if not exclude_patterns:
        return all_keys

    # Filter out excluded patterns
    filtered_keys = []
    for key in all_keys:
        should_exclude = False
        for pattern in exclude_patterns:
            # Convert RabbitMQ pattern to fnmatch pattern
            fnmatch_pattern = (
                pattern.replace(".", r"\.").replace("*", ".*").replace("#", ".*")
            )
            if fnmatch.fnmatch(key, fnmatch_pattern):
                should_exclude = True
                break

        if not should_exclude:
            filtered_keys.append(key)

    return filtered_keys
