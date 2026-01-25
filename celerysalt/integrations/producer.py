"""
Producer for publishing events via Celery.

Maintains protocol compatibility with tchu-tchu by using the same
exchange name and message format.
"""

import uuid
from typing import Any, Dict, Optional
from celery import current_app

from celerysalt.utils.json_encoder import dumps_message
from celerysalt.core.exceptions import PublishError, TimeoutError as CelerySaltTimeoutError
from celerysalt.logging.handlers import get_logger
from celerysalt.core.decorators import DEFAULT_EXCHANGE_NAME, DEFAULT_DISPATCHER_TASK_NAME

logger = get_logger(__name__)


def publish_event(
    topic: str,
    data: Dict[str, Any],
    exchange_name: str = DEFAULT_EXCHANGE_NAME,
    is_rpc: bool = False,
    celery_app: Optional[Any] = None,
    dispatcher_task_name: str = DEFAULT_DISPATCHER_TASK_NAME,
) -> str:
    """
    Publish an event to a topic (broadcast to all subscribers).

    Protocol compatibility: Uses same exchange name and message format as tchu-tchu.

    Args:
        topic: Topic routing key (e.g., 'user.created', 'order.*')
        data: Message body (will be serialized)
        exchange_name: RabbitMQ exchange name (default: "tchu_events" for compatibility)
        is_rpc: Whether this is an RPC call (default: False)
        celery_app: Optional Celery app instance (uses current_app if None)
        dispatcher_task_name: Name of the dispatcher task

    Returns:
        Message ID for tracking

    Raises:
        PublishError: If publishing fails
    """
    try:
        app = celery_app or current_app

        # Generate unique message ID
        message_id = str(uuid.uuid4())

        # Add _tchu_meta for protocol compatibility with tchu-tchu
        body_with_meta = {
            **data,
            "_tchu_meta": {"is_rpc": is_rpc},
        }
        serialized_body = dumps_message(body_with_meta)

        # Send task to dispatcher with routing_key in properties
        app.send_task(
            dispatcher_task_name,
            args=[serialized_body],
            kwargs={"routing_key": topic},
            routing_key=topic,  # Used by AMQP for routing to queues
            task_id=message_id,
        )

        logger.info(
            f"Published message {message_id} to routing key '{topic}'",
            extra={"routing_key": topic, "message_id": message_id},
        )

        return message_id

    except Exception as e:
        logger.error(f"Failed to publish message to routing key '{topic}': {e}", exc_info=True)
        raise PublishError(f"Failed to publish message: {e}")


def call_rpc(
    topic: str,
    data: Dict[str, Any],
    timeout: int = 30,
    exchange_name: str = DEFAULT_EXCHANGE_NAME,
    celery_app: Optional[Any] = None,
    dispatcher_task_name: str = DEFAULT_DISPATCHER_TASK_NAME,
    allow_join: bool = False,
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
    app = celery_app or current_app

    try:
        # Generate unique message ID
        message_id = str(uuid.uuid4())

        # Add _tchu_meta for protocol compatibility
        body_with_meta = {
            **data,
            "_tchu_meta": {"is_rpc": True},
        }
        serialized_body = dumps_message(body_with_meta)

        # Send task to dispatcher and wait for result
        result = app.send_task(
            dispatcher_task_name,
            args=[serialized_body],
            kwargs={"routing_key": topic},
            routing_key=topic,
            task_id=message_id,
        )

        logger.info(
            f"RPC call {message_id} sent to routing key '{topic}'",
            extra={"routing_key": topic, "message_id": message_id},
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
            logger.info(
                f"RPC call {message_id} completed in {execution_time:.2f} seconds",
                extra={
                    "routing_key": topic,
                    "message_id": message_id,
                    "execution_time": execution_time,
                },
            )

            # Extract the actual result from the dispatcher response
            if isinstance(response, dict):
                # Check if there were no handlers
                if response.get("status") == "no_handlers":
                    raise PublishError(f"No handlers found for routing key '{topic}'")

                # Extract results from the first successful handler
                results = response.get("results", [])
                if results:
                    first_result = results[0]
                    if first_result.get("status") == "success":
                        return first_result.get("result")
                    else:
                        error = first_result.get("error", "Unknown error")
                        handler_name = first_result.get("handler", "unknown")
                        raise PublishError(f"Handler '{handler_name}' failed: {error}")
                else:
                    raise PublishError(
                        f"No results returned from handler for routing key '{topic}'"
                    )

            # If response is not a dict, return it as-is
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
        logger.error(f"Failed to execute RPC call to routing key '{topic}': {e}", exc_info=True)
        raise PublishError(f"Failed to execute RPC call: {e}")
