"""Celery setup helper for worker queue and event handlers."""

import importlib

from celery.signals import celeryd_after_setup, worker_ready
from kombu import Exchange, Queue, binding

from celery_salt.integrations.dispatcher import (
    create_topic_dispatcher,
    get_subscribed_routing_keys,
)
from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)


def setup_salt_queue(
    celery_app,
    queue_name: str,
    subscriber_modules: list[str] | None = None,
    exchange_name: str = "tchu_events",
    exchange_type: str = "topic",
    durable: bool = True,
    auto_delete: bool = False,
) -> None:
    """
    Set up Salt queue (topic exchange, dispatcher, bindings) for celery-salt event handlers.

    This helper function handles all the boilerplate of:
    1. Importing subscriber modules (deferred until worker is ready)
    2. Collecting routing keys from registered handlers
    3. Creating queue bindings
    4. Configuring Celery queues and task routes
    5. Setting default exchange for cross-service messaging
    6. Creating the dispatcher task

    IMPORTANT: All subscriber module imports and routing key collection are
    deferred until worker_ready signal to ensure the database is available.
    This prevents issues with Celery Beat's DatabaseScheduler which needs
    database access during initialization.

    Usage:
        # In your celery.py - list once in include, pass queue_name only
        from celery import Celery
        app = Celery("my_app", include=["app1.subscribers", "app2.subscribers"])
        app.config_from_object("django.conf:settings", namespace="CELERY")

        from celery_salt.django import setup_salt_queue
        setup_salt_queue(app, queue_name="my_queue")

    Args:
        celery_app: Celery app instance
        queue_name: Name of the queue (e.g., "acme_queue", "pulse_queue")
        subscriber_modules: Module paths containing @subscribe decorators.
            If not provided, uses celery_app.conf.include (same as Celery(include=[...])).
        exchange_name: RabbitMQ exchange name (default: "tchu_events")
        exchange_type: Exchange type (default: "topic")
        durable: Whether queue is durable (default: True)
        auto_delete: Whether queue auto-deletes (default: False)
    """
    if subscriber_modules is None:
        subscriber_modules = getattr(celery_app.conf, "include", None) or []

    # Create topic exchange (no database access needed)
    tchu_exchange = Exchange(exchange_name, type=exchange_type, durable=durable)

    def _configure_queue_bindings(routing_keys: list[str]) -> None:
        """Configure queue with the given routing keys."""
        all_bindings = [binding(tchu_exchange, routing_key=key) for key in routing_keys]

        celery_app.conf.task_queues = (
            Queue(
                queue_name,
                exchange=tchu_exchange,
                bindings=all_bindings,
                durable=durable,
                auto_delete=auto_delete,
            ),
        )

        logger.debug(
            f"Queue '{queue_name}' configured with {len(routing_keys)} binding(s)"
        )

    def _import_subscriber_modules() -> None:
        """Import subscriber modules to register handlers."""
        for module in subscriber_modules:
            try:
                importlib.import_module(module)
                logger.debug(f"Imported subscriber module: {module}")
            except Exception as e:
                logger.error(f"Failed to import {module}: {e}", exc_info=True)

    # Configure initial queue with exchange (ensures exchange is declared)
    # This doesn't require database access - just sets up Celery config
    # Bindings will be updated when worker starts and imports subscribers
    celery_app.conf.task_queues = (
        Queue(
            queue_name,
            exchange=tchu_exchange,
            routing_key=queue_name,  # Basic direct routing initially
            durable=durable,
            auto_delete=auto_delete,
        ),
    )

    @celeryd_after_setup.connect
    def _setup_queue_on_worker_init(sender, instance, **kwargs):
        """
        Configure queue bindings after Celery worker setup but before consuming.

        This signal fires after the worker is configured but before it starts
        consuming messages, making it the ideal time to set up queue bindings.
        By deferring to this point, we ensure the database is available.
        """
        logger.debug(f"Tchu-tchu configuring queue bindings for: {queue_name}")

        # Import subscriber modules now that worker is initializing
        _import_subscriber_modules()

        # Collect routing keys from registered handlers
        all_routing_keys = get_subscribed_routing_keys()

        # Update queue configuration with proper bindings
        _configure_queue_bindings(all_routing_keys)

    @worker_ready.connect
    def _log_on_worker_ready(sender=None, **kwargs):
        """Log summary when worker is fully ready."""
        from celery_salt.integrations.registry import get_handler_registry

        handler_count = get_handler_registry().get_handler_count()

        if handler_count == 0:
            logger.warning(
                f"Tchu-tchu: queue '{queue_name}' ready with no handlers. "
                "Verify subscriber_modules contain @subscribe decorators."
            )
        else:
            logger.debug(
                f"Tchu-tchu: queue '{queue_name}' ready ({handler_count} handlers)"
            )

    # Route dispatcher task to this queue (no database access needed)
    celery_app.conf.task_routes = {
        "celery_salt.dispatch_event": {
            "queue": queue_name,
            "exchange": exchange_name,
            "routing_key": "celery_salt.dispatch_event",
        },
    }

    # Set default queue for all tasks (including @celery.shared_task)
    # This ensures regular Celery tasks also go to the service's queue
    celery_app.conf.task_default_queue = queue_name

    # DON'T set task_default_exchange - let regular tasks use direct routing
    # Only tchu-tchu dispatcher events should use the topic exchange

    # Set prefetch=1 for reliable RPC handling (prevents race conditions)
    celery_app.conf.worker_prefetch_multiplier = 1

    # Create the dispatcher task (registers celery_salt.dispatch_event)
    # This doesn't require database access
    create_topic_dispatcher(celery_app)

    logger.debug(
        f"Tchu-tchu setup registered for queue '{queue_name}' "
        "(bindings will be configured on worker startup)"
    )
