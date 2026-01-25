"""
Example: Broadcast Event Publisher

This script demonstrates how to publish broadcast events using CelerySalt.
Broadcast events are fire-and-forget: one event is delivered to all subscribers.

Prerequisites:
    - RabbitMQ running on localhost:5672
    - Celery worker running (see subscriber.py)

Run:
    python publisher.py
"""

from celery import Celery
from celery_salt import event
from celery_salt.integrations.producer import publish_event
from celery_salt.core.decorators import DEFAULT_EXCHANGE_NAME, DEFAULT_DISPATCHER_TASK_NAME

# Configure Celery to route dispatcher tasks to the topic exchange
app = Celery("publisher")
app.conf.broker_url = "amqp://guest:guest@localhost:5672//"
app.conf.task_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.result_serializer = "json"
app.conf.timezone = "UTC"
app.conf.enable_utc = True

# Configure routing: route dispatcher task to topic exchange
# When we call send_task() with routing_key, Celery will use this exchange
# Note: The routing_key from send_task() call will be used for routing
from kombu import Exchange

# Declare the topic exchange
topic_exchange = Exchange(DEFAULT_EXCHANGE_NAME, type="topic", durable=True)

# Configure route to use topic exchange
# The routing_key passed to send_task() will be used for routing
app.conf.task_routes = {
    DEFAULT_DISPATCHER_TASK_NAME: {
        "exchange": DEFAULT_EXCHANGE_NAME,
        "exchange_type": "topic",
    },
}

# Set as default so publish_event can use it
app.set_default()


# Define the event schema
@event("user.signup.completed")
class UserSignupCompleted:
    """Event published when a user completes signup."""

    user_id: int
    email: str
    company_id: int
    signup_source: str = "web"


def main():
    """Publish a few example events."""
    print("📤 Publishing broadcast events...")
    print()

    # Publish events
    events = [
        {
            "user_id": 123,
            "email": "alice@example.com",
            "company_id": 1,
            "signup_source": "web",
        },
        {
            "user_id": 124,
            "email": "bob@example.com",
            "company_id": 2,
            "signup_source": "mobile",
        },
        {
            "user_id": 125,
            "email": "charlie@example.com",
            "company_id": 1,
            "signup_source": "api",
        },
    ]

    for event_data in events:
        # Use the class method - Celery is now configured to route to topic exchange
        message_id = UserSignupCompleted.publish(**event_data)
        print(
            f"✓ Published event: user_id={event_data['user_id']}, message_id={message_id}"
        )

    print()
    print("✅ All events published!")
    print()
    print("💡 Check your Celery worker logs to see the events being processed.")


if __name__ == "__main__":
    main()
