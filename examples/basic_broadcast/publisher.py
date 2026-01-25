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
from kombu import Exchange
from pydantic import BaseModel

from celery_salt import SaltEvent, event
from celery_salt.core.decorators import (
    DEFAULT_DISPATCHER_TASK_NAME,
    DEFAULT_EXCHANGE_NAME,
)

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


# Option 1: Decorator-based API (simple)
@event("user.signup.completed")
class UserSignupCompleted:
    """Event published when a user completes signup."""

    user_id: int
    email: str
    company_id: int
    signup_source: str = "web"


# Option 2: Class-based API (for custom logic)
class UserSignupCompletedV2(SaltEvent):
    """Event published when a user completes signup (class-based version)."""

    class Schema(BaseModel):
        user_id: int
        email: str
        company_id: int
        signup_source: str = "web"

    class Meta:
        topic = "user.signup.completed"
        version = "v2"
        description = "User completed signup process (class-based API, v2)"

    def is_premium_user(self) -> bool:
        """Check if user is premium based on user_id."""
        return self.data.user_id > 1000

    def publish(self, **kwargs):
        """Custom publish with premium user logging."""
        if self.is_premium_user():
            print(f"  ⭐ Premium user signup: {self.data.email}")
        return super().publish(**kwargs)


def main():
    """Publish a few example events using both APIs."""
    print("📤 Publishing broadcast events...")
    print()
    print("=" * 60)
    print("Option 1: Decorator-based API")
    print("=" * 60)
    print()

    # Publish events using decorator-based API
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
        # Option 1: Decorator-based API (class method)
        message_id = UserSignupCompleted.publish(**event_data)
        print(
            f"✓ Published event (decorator): user_id={event_data['user_id']}, message_id={message_id}"
        )

    print()
    print("=" * 60)
    print("Option 2: Class-based API (with custom logic, v2)")
    print("=" * 60)
    print()

    # Publish events using class-based API (v2)
    class_based_events = [
        {
            "user_id": 2000,  # Premium user (user_id > 1000)
            "email": "premium@example.com",
            "company_id": 1,
            "signup_source": "web",
        },
        {
            "user_id": 500,
            "email": "regular@example.com",
            "company_id": 2,
            "signup_source": "mobile",
        },
    ]

    for event_data in class_based_events:
        # Option 2: Class-based API (instance method) - publishes as v2
        event = UserSignupCompletedV2(**event_data)
        message_id = event.publish()
        print(
            f"✓ Published event (class-based v2): user_id={event_data['user_id']}, message_id={message_id}"
        )

    print()
    print("✅ All events published!")
    print()
    print("💡 Check your Celery worker logs to see the events being processed.")


if __name__ == "__main__":
    main()
