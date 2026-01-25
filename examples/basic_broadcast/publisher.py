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
from celerysalt import event
from celerysalt.integrations.producer import publish_event

# Configure Celery (minimal config for publishing)
app = Celery("publisher")
app.conf.broker_url = "amqp://guest:guest@localhost:5672//"
app.conf.task_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.result_serializer = "json"
app.conf.timezone = "UTC"
app.conf.enable_utc = True

# Set the Celery app as the default
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
        # Use the class method which will use the configured Celery app
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
