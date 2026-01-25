"""
Example: Advanced Broadcast Event Publisher - Versioning & Backward Compatibility

This script demonstrates event versioning and backward compatibility.
The publisher publishes v2 events, which can be received by both v1 and v2 handlers.

Scenario:
- v1 Event: user_id, email, company_id
- v2 Event: user_id, email, company_id, phone_number (new field added)
- Publisher publishes v2 events
- v1 handlers receive v2 events (backward compatible, with warnings)
- v2 handlers receive v2 events (normal operation)

Prerequisites:
    - RabbitMQ running on localhost:5672
    - Celery worker running (see subscriber.py)

Run:
    python publisher.py
"""

from celery import Celery
from celery_salt import SaltEvent
from celery_salt.core.decorators import (
    DEFAULT_EXCHANGE_NAME,
    DEFAULT_DISPATCHER_TASK_NAME,
)
from pydantic import BaseModel

# Configure Celery to route dispatcher tasks to the topic exchange
app = Celery("advanced_publisher")
app.conf.broker_url = "amqp://guest:guest@localhost:5672//"
app.conf.task_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.result_serializer = "json"
app.conf.timezone = "UTC"
app.conf.enable_utc = True

# Configure routing: route dispatcher task to topic exchange
from kombu import Exchange

# Declare the topic exchange
topic_exchange = Exchange(DEFAULT_EXCHANGE_NAME, type="topic", durable=True)

# Configure route to use topic exchange
app.conf.task_routes = {
    DEFAULT_DISPATCHER_TASK_NAME: {
        "exchange": DEFAULT_EXCHANGE_NAME,
        "exchange_type": "topic",
    },
}

# Set as default so publish_event can use it
app.set_default()


# Define v1 Event Schema (for reference - not used by publisher)
class UserSignupV1Schema(BaseModel):
    """v1 Event schema: user_id, email, company_id"""

    user_id: int
    email: str
    company_id: int


# Define v2 Event Schema (used by publisher)
class UserSignupV2(SaltEvent):
    """v2 Event: Adds phone_number field to v1 schema."""

    class Schema(BaseModel):
        user_id: int
        email: str
        company_id: int
        phone_number: str  # NEW field in v2

    class Meta:
        topic = "user.signup.completed"
        version = "v2"
        description = "User completed signup (v2: includes phone_number)"


def main():
    """Publish v2 events to demonstrate backward compatibility."""
    print("📤 Publishing v2 events (demonstrating backward compatibility)...")
    print()
    print("=" * 70)
    print("Event Versioning: v2 Publisher")
    print("=" * 70)
    print()
    print("📋 Event Schema (v2):")
    print("   - user_id: int")
    print("   - email: str")
    print("   - company_id: int")
    print("   - phone_number: str  ← NEW in v2")
    print()
    print("🎯 Expected Behavior:")
    print("   - v1 handlers: Will receive v2 events (backward compatible)")
    print("     → Validates against v1 schema (ignores phone_number)")
    print("     → Logs WARNING: 'Subscriber is on an older version'")
    print("   - v2 handlers: Will receive v2 events (normal operation)")
    print("     → Validates against v2 schema (includes phone_number)")
    print()

    # Publish v2 events
    events = [
        {
            "user_id": 1001,
            "email": "alice@example.com",
            "company_id": 1,
            "phone_number": "+1-555-0101",  # v2 field
        },
        {
            "user_id": 1002,
            "email": "bob@example.com",
            "company_id": 2,
            "phone_number": "+1-555-0102",  # v2 field
        },
        {
            "user_id": 1003,
            "email": "charlie@example.com",
            "company_id": 1,
            "phone_number": "+1-555-0103",  # v2 field
        },
    ]

    for event_data in events:
        # Publish v2 event
        event = UserSignupV2(**event_data)
        message_id = event.publish()
        print(
            f"✓ Published v2 event: user_id={event_data['user_id']}, "
            f"email={event_data['email']}, phone={event_data['phone_number']}, "
            f"message_id={message_id}"
        )

    print()
    print("=" * 70)
    print("✅ All v2 events published!")
    print("=" * 70)
    print()
    print("💡 Check your Celery worker logs to see:")
    print("   1. v1 handlers processing v2 events (with warnings)")
    print("   2. v2 handlers processing v2 events (normal)")
    print()


if __name__ == "__main__":
    main()
