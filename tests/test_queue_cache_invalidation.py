"""Tests for queue cache invalidation fix in setup_salt_queue.

Verifies that:
1. Signal handlers survive setup_salt_queue return (weak=False)
2. After celeryd_after_setup fires, app.amqp.queues cached_property is
   invalidated so the Consumer bootstep reads the updated task_queues
3. worker_ready declares explicit broker bindings as defense-in-depth
"""

from unittest.mock import MagicMock, patch

import pytest
from celery import Celery
from celery.signals import celeryd_after_setup, worker_ready

from celery_salt.django.celery import setup_salt_queue


@pytest.fixture(autouse=True)
def _clean_signals():
    """Disconnect all signal receivers between tests to avoid cross-contamination."""
    celeryd_after_setup.receivers = []
    celeryd_after_setup.sender_receivers_cache.clear()
    worker_ready.receivers = []
    worker_ready.sender_receivers_cache.clear()
    yield
    celeryd_after_setup.receivers = []
    celeryd_after_setup.sender_receivers_cache.clear()
    worker_ready.receivers = []
    worker_ready.sender_receivers_cache.clear()


@pytest.fixture()
def celery_test_app():
    """Create an isolated Celery app for testing."""
    app = Celery("test_app")
    app.config_from_object(
        {
            "task_always_eager": True,
            "task_eager_propagates": True,
            "broker_url": "memory://",
            "result_backend": "cache+memory://",
        }
    )
    return app


def test_signal_handlers_survive_setup_return(celery_test_app):
    """Signal handlers must not be garbage-collected after setup_salt_queue returns."""
    with patch(
        "celery_salt.django.celery.get_subscribed_routing_keys",
        return_value=[],
    ), patch("celery_salt.django.celery.create_topic_dispatcher"):
        setup_salt_queue(
            celery_test_app,
            queue_name="test_queue",
            subscriber_modules=[],
        )

    # Handlers should be alive (not dead weak references)
    assert len(celeryd_after_setup.receivers) == 1
    assert len(worker_ready.receivers) == 1

    # Verify they're not dead weak references by firing the signal
    with patch(
        "celery_salt.django.celery.get_subscribed_routing_keys",
        return_value=["rpc.test"],
    ):
        results = celeryd_after_setup.send(sender="test", instance=MagicMock())

    assert len(results) == 1
    assert results[0][1] is None  # handler returned None (no error)


def test_queue_cache_invalidated_after_setup(celery_test_app):
    """After celeryd_after_setup, app.amqp.queues must NOT hold stale direct routing."""
    with patch(
        "celery_salt.django.celery.get_subscribed_routing_keys",
        return_value=["rpc.test.list", "event.product.updated"],
    ), patch("celery_salt.django.celery.create_topic_dispatcher"):
        setup_salt_queue(
            celery_test_app,
            queue_name="test_queue",
            subscriber_modules=[],
        )

    # Simulate what WorkController.__init__ does: access app.amqp.queues
    # to trigger the cached_property evaluation with the initial (stale) config.
    _ = celery_test_app.amqp.queues
    assert "queues" in celery_test_app.amqp.__dict__

    # Fire celeryd_after_setup signal (celery-salt handler updates config,
    # then the cache invalidation clears the stale cached_property)
    with patch(
        "celery_salt.django.celery.get_subscribed_routing_keys",
        return_value=["rpc.test.list", "event.product.updated"],
    ):
        celeryd_after_setup.send(sender="test_worker", instance=MagicMock())

    # After signal: the stale cache must be gone
    assert "queues" not in celery_test_app.amqp.__dict__

    # Re-access queues — should now reflect the updated task_queues with topic bindings
    queues = celery_test_app.amqp.queues
    test_queue = queues["test_queue"]
    assert test_queue.bindings
    binding_keys = {b.routing_key for b in test_queue.bindings}
    assert binding_keys == {"rpc.test.list", "event.product.updated"}
    for b in test_queue.bindings:
        assert b.exchange.type == "topic"


def test_broker_bindings_declared_on_worker_ready(celery_test_app):
    """worker_ready signal should call queue_bind for each routing key."""
    with patch(
        "celery_salt.django.celery.get_subscribed_routing_keys",
        return_value=["rpc.test.list", "event.product.updated"],
    ), patch("celery_salt.django.celery.create_topic_dispatcher"):
        setup_salt_queue(
            celery_test_app,
            queue_name="test_queue",
            subscriber_modules=[],
        )

    mock_channel = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.default_channel = mock_channel

    with patch(
        "celery_salt.django.celery.get_subscribed_routing_keys",
        return_value=["rpc.test.list", "event.product.updated"],
    ), patch.object(
        celery_test_app, "connection_for_write", return_value=mock_conn
    ):
        worker_ready.send(sender=MagicMock())

    # Verify queue_bind was called for each routing key
    bind_calls = mock_channel.queue_bind.call_args_list
    assert len(bind_calls) == 2

    bound_keys = {call.kwargs["routing_key"] for call in bind_calls}
    assert bound_keys == {"rpc.test.list", "event.product.updated"}

    for call in bind_calls:
        assert call.kwargs["queue"] == "test_queue"
        assert call.kwargs["exchange"] == "tchu_events"


def test_broker_binding_failure_does_not_crash(celery_test_app):
    """If broker binding fails, it should log but not raise."""
    with patch(
        "celery_salt.django.celery.get_subscribed_routing_keys",
        return_value=["rpc.test.list"],
    ), patch("celery_salt.django.celery.create_topic_dispatcher"):
        setup_salt_queue(
            celery_test_app,
            queue_name="test_queue",
            subscriber_modules=[],
        )

    with patch(
        "celery_salt.django.celery.get_subscribed_routing_keys",
        return_value=["rpc.test.list"],
    ), patch.object(
        celery_test_app,
        "connection_for_write",
        side_effect=ConnectionError("broker down"),
    ):
        # Should not raise
        worker_ready.send(sender=MagicMock())


def test_no_bindings_skips_broker_call(celery_test_app):
    """If there are no routing keys, worker_ready should not connect to broker."""
    with patch(
        "celery_salt.django.celery.get_subscribed_routing_keys",
        return_value=[],
    ), patch("celery_salt.django.celery.create_topic_dispatcher"):
        setup_salt_queue(
            celery_test_app,
            queue_name="test_queue",
            subscriber_modules=[],
        )

    with patch(
        "celery_salt.django.celery.get_subscribed_routing_keys",
        return_value=[],
    ), patch.object(celery_test_app, "connection_for_write") as mock_conn:
        worker_ready.send(sender=MagicMock())

    mock_conn.assert_not_called()
