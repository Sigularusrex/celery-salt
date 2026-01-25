"""Serverless producer for serverless environments (Cloud Functions, Lambda, etc.).

This producer uses pika directly instead of Celery, making it suitable for
short-lived serverless functions where Celery's connection pooling doesn't work well.

Similar to the original tchu library's approach.
"""

import json
import uuid
from typing import Any, Dict, Union, Optional
from urllib.parse import urlparse
from kombu import Connection, Exchange, Producer

from celerysalt.utils.json_encoder import dumps_message
from celerysalt.utils.error_handling import PublishError
from celerysalt.logging.handlers import get_logger, log_error

logger = get_logger(__name__)


class ServerlessProducer:
    """
    Lightweight producer for serverless environments.

    Uses pika directly for short-lived connections that work in
    cloud functions, Lambda, and other serverless platforms.

    Example:
        # In a cloud function
        from celerysalt.serverless_producer import ServerlessProducer

        producer = ServerlessProducer(broker_url="amqp://user:pass@host:5672//")
        producer.publish('user.created', {'user_id': 123})
    """

    def __init__(
        self,
        broker_url: str,
        exchange_name: str = "tchu_events",
        connection_timeout: int = 10,
        dispatcher_task_name: str = "celerysalt.dispatch_event",
    ) -> None:
        """
        Initialize the ServerlessProducer.

        Args:
            broker_url: RabbitMQ connection URL (e.g., "amqp://user:pass@host:5672//")
            exchange_name: Exchange name (default: "tchu_events")
            connection_timeout: Connection timeout in seconds (default: 10)
            dispatcher_task_name: Name of the dispatcher task (default: 'celerysalt.dispatch_event')
        """
        self.broker_url = broker_url
        self.exchange_name = exchange_name
        self.connection_timeout = connection_timeout
        self.dispatcher_task_name = dispatcher_task_name
        self._connection = None
        self._exchange = None

    def _ensure_connection(self) -> None:
        """Ensure connection is established."""
        try:
            if self._connection is None:
                logger.debug(
                    f"[ServerlessProducer] Creating new connection to {self.broker_url}"
                )

                # Create kombu connection
                self._connection = Connection(
                    self.broker_url,
                    connect_timeout=self.connection_timeout,
                )

                logger.debug(
                    f"[ServerlessProducer] Connection object created, "
                    f"transport={self._connection.transport_cls}"
                )

                # Create exchange
                self._exchange = Exchange(
                    self.exchange_name,
                    type="topic",
                    durable=True,
                )

                logger.debug(
                    f"[ServerlessProducer] Exchange created: "
                    f"name={self.exchange_name}, type=topic, durable=True"
                )
                logger.info(f"Initialized connection to RabbitMQ at {self.broker_url}")
            else:
                logger.debug("[ServerlessProducer] Reusing existing connection")
        except Exception as e:
            logger.error(
                f"[ServerlessProducer] Failed to initialize connection: {e}",
                exc_info=True,
            )
            log_error(
                logger,
                f"Failed to initialize RabbitMQ connection",
                e,
                broker_url=self.broker_url,
            )
            raise PublishError(f"Failed to initialize RabbitMQ connection: {e}")

    def publish(
        self,
        routing_key: str,
        body: Union[Dict[str, Any], Any],
        content_type: str = "application/json",
        delivery_mode: int = 2,
        **kwargs,
    ) -> str:
        """
        Publish a message to a routing key (broadcast to all subscribers).

        This creates a Celery task message that will be processed by the
        celerysalt.dispatch_event task on the consumer side.

        Args:
            routing_key: Topic routing key (e.g., 'user.created', 'order.*')
            body: Message body (will be serialized to JSON)
            content_type: Content type (default: "application/json")
            delivery_mode: Delivery mode (1=non-persistent, 2=persistent)
            **kwargs: Additional arguments (for compatibility)

        Returns:
            Message ID for tracking

        Raises:
            PublishError: If publishing fails
        """
        try:
            # Generate unique message ID
            message_id = str(uuid.uuid4())

            logger.debug(
                f"[ServerlessProducer] Starting publish: routing_key={routing_key}, message_id={message_id}"
            )

            # Add tchu metadata and serialize the message body (same as CeleryProducer)
            if isinstance(body, (str, bytes)):
                # If body is already serialized, we can't add metadata
                serialized_body = (
                    body if isinstance(body, str) else body.decode("utf-8")
                )
                logger.debug(
                    f"[ServerlessProducer] Body is string/bytes, type={type(body).__name__}, "
                    f"serialized_body type={type(serialized_body).__name__}"
                )
            else:
                # Add _tchu_meta to the body for dispatcher to determine execution mode
                body_with_meta = {
                    **body,
                    "_tchu_meta": {"is_rpc": False},
                }
                serialized_body = dumps_message(body_with_meta)
                logger.debug(
                    f"[ServerlessProducer] Body serialized with dumps_message, "
                    f"type={type(serialized_body).__name__}, length={len(serialized_body)}"
                )

            # Ensure connection
            self._ensure_connection()
            logger.debug(f"[ServerlessProducer] Connection established")

            # Create Celery task message
            # Note: We pass serialized_body as a string (already JSON),
            # kombu will serialize the entire task dict including this string
            task_message = {
                "task": self.dispatcher_task_name,
                "id": message_id,
                "args": [serialized_body],  # Already JSON string
                "kwargs": {"routing_key": routing_key},
                "retries": 0,
                "eta": None,
                "expires": None,
            }

            logger.debug(
                f"[ServerlessProducer] Task message created: "
                f"task={self.dispatcher_task_name}, id={message_id}"
            )

            # Use kombu to publish the task (handles Celery protocol properly)
            with self._connection.Producer() as producer:
                # Manually serialize to ensure we have bytes
                # This avoids kombu serialization issues
                import json as stdlib_json

                try:
                    message_str = stdlib_json.dumps(
                        task_message,
                        ensure_ascii=False,
                    )
                    logger.debug(
                        f"[ServerlessProducer] Task message JSON serialized, "
                        f"length={len(message_str)}, type={type(message_str).__name__}"
                    )

                    message_bytes = message_str.encode("utf-8")
                    logger.debug(
                        f"[ServerlessProducer] Message encoded to bytes, "
                        f"length={len(message_bytes)}, type={type(message_bytes).__name__}"
                    )
                except Exception as serialize_error:
                    logger.error(
                        f"[ServerlessProducer] Serialization failed: {serialize_error}",
                        exc_info=True,
                    )
                    raise

                # Send pre-serialized bytes
                try:
                    logger.debug(
                        f"[ServerlessProducer] Publishing to exchange={self.exchange_name}, "
                        f"routing_key={routing_key}, delivery_mode={delivery_mode}"
                    )

                    producer.publish(
                        message_bytes,
                        exchange=self._exchange,
                        routing_key=routing_key,
                        serializer=None,  # Don't serialize again
                        content_type="application/json",
                        content_encoding="utf-8",
                        delivery_mode=delivery_mode,
                        declare=[self._exchange],  # Ensure exchange exists
                    )

                    logger.debug(f"[ServerlessProducer] Publish successful")

                except Exception as publish_error:
                    logger.error(
                        f"[ServerlessProducer] Publish to broker failed: {publish_error}",
                        exc_info=True,
                    )
                    raise

            logger.info(
                f"Published message {message_id} to routing key '{routing_key}'",
                extra={"routing_key": routing_key, "message_id": message_id},
            )

            return message_id

        except PublishError:
            raise
        except Exception as e:
            logger.error(
                f"[ServerlessProducer] Failed to publish message to routing key '{routing_key}': {e}",
                exc_info=True,
            )
            log_error(
                logger,
                f"Failed to publish message to routing key '{routing_key}'",
                e,
                routing_key,
            )
            raise PublishError(f"Failed to publish message: {e}")

    def close(self) -> None:
        """Close the connection."""
        try:
            if self._connection:
                self._connection.release()
            logger.debug("Closed RabbitMQ connection")
        except Exception as e:
            logger.warning(f"Error closing connection: {e}")

    def __enter__(self):
        """Context manager entry."""
        self._ensure_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.close()
        except Exception:
            pass


class ServerlessClient:
    """
    Drop-in replacement for TchuClient that works in serverless environments.

    Example:
        # In a cloud function
        from celerysalt.serverless_producer import ServerlessClient

        client = ServerlessClient(broker_url="amqp://user:pass@host:5672//")
        client.publish('user.created', {'user_id': 123})
    """

    def __init__(
        self,
        broker_url: str,
        exchange_name: str = "tchu_events",
        connection_timeout: int = 10,
    ) -> None:
        """
        Initialize the ServerlessClient.

        Args:
            broker_url: RabbitMQ connection URL
            exchange_name: Exchange name (default: "tchu_events")
            connection_timeout: Connection timeout in seconds (default: 10)
        """
        self.producer = ServerlessProducer(
            broker_url=broker_url,
            exchange_name=exchange_name,
            connection_timeout=connection_timeout,
        )

    def publish(self, topic: str, data: Union[Dict[str, Any], Any], **kwargs) -> None:
        """
        Publish a message to a topic (fire-and-forget).

        Args:
            topic: Topic name to publish to
            data: Message data to publish
            **kwargs: Additional arguments passed to the producer
        """
        self.producer.publish(routing_key=topic, body=data, **kwargs)

    def close(self) -> None:
        """Close the connection."""
        self.producer.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
