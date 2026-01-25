"""
Example: Advanced Broadcast Event Subscriber - Versioning & Backward Compatibility

This script demonstrates how backward compatibility works with event versioning.
It includes both v1 and v2 handlers for the same event topic.

Scenario:
- Publisher publishes v2 events (with phone_number field)
- v1 handlers receive v2 events (backward compatible, validates against v1 schema)
- v2 handlers receive v2 events (normal, validates against v2 schema)

Prerequisites:
    - RabbitMQ running on localhost:5672
    - Celery configured (see celery_config.py)

Run:
    celery -A subscriber worker --loglevel=info
"""

from celery import Celery
from celery_salt import subscribe, SaltEvent
from celery_salt.integrations.dispatcher import (
    create_topic_dispatcher,
    get_subscribed_routing_keys,
)
from pydantic import BaseModel


# Define v1 Event Schema (for v1 handlers)
class UserSignupV1Schema(BaseModel):
    """v1 Event schema: user_id, email, company_id (no phone_number)"""

    user_id: int
    email: str
    company_id: int


# Define v2 Event Schema (for v2 handlers and reference)
class UserSignupV2Schema(BaseModel):
    """v2 Event schema: user_id, email, company_id, phone_number"""

    user_id: int
    email: str
    company_id: int
    phone_number: str  # NEW field in v2


# Define v2 Event Class (for reference - matches publisher)
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


# Create Celery app
app = Celery("advanced_subscriber")
app.conf.broker_url = "amqp://guest:guest@localhost:5672//"
app.conf.result_backend = "rpc://"
app.conf.task_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.result_serializer = "json"
app.conf.timezone = "UTC"
app.conf.enable_utc = True

# Create the dispatcher task first (needed for routing)
dispatcher = create_topic_dispatcher(app)

# ============================================================================
# V1 HANDLERS (Backward Compatible - receive v2 events with warnings)
# ============================================================================


# v1 Handler 1: Welcome Email
@subscribe("user.signup.completed", version="v1")
def send_welcome_email_v1(data):
    """
    Send welcome email to new user (v1 handler).

    This handler subscribes to v1 but will receive v2 events (backward compatible).
    It validates against v1 schema, so phone_number field is ignored.

    Args:
        data: Pydantic model with v1 fields (user_id, email, company_id)
              Note: phone_number from v2 events is ignored during validation
    """
    print(
        f"📧 [V1 HANDLER] Sending welcome email to {data.email} (user_id={data.user_id})"
    )
    print(f"   ⚠️  This is a v1 handler receiving a v2 event (backward compatible)")
    print(f"   ℹ️  phone_number field is not available in v1 schema")
    # In a real app, you'd send an email here
    return f"Welcome email sent to {data.email} (v1 handler)"


# v1 Handler 2: Analytics
@subscribe("user.signup.completed", version="v1")
def update_user_analytics_v1(data):
    """
    Update analytics for new signup (v1 handler).

    This handler subscribes to v1 but will receive v2 events (backward compatible).
    It validates against v1 schema, so phone_number field is ignored.

    Args:
        data: Pydantic model with v1 fields (user_id, email, company_id)
    """
    print(f"📊 [V1 HANDLER] Updating analytics for user {data.user_id}")
    print(f"   ⚠️  This is a v1 handler receiving a v2 event (backward compatible)")
    print(f"   ℹ️  phone_number field is not available in v1 schema")
    # In a real app, you'd update analytics here
    return f"Analytics updated for user {data.user_id} (v1 handler)"


# ============================================================================
# V2 HANDLERS (Normal Operation - receive v2 events)
# ============================================================================


# v2 Handler 1: Welcome Email with SMS
@subscribe("user.signup.completed", version="v2")
def send_welcome_email_v2(data):
    """
    Send welcome email and SMS to new user (v2 handler).

    This handler subscribes to v2 and receives v2 events normally.
    It validates against v2 schema, so phone_number field is available.

    Args:
        data: Pydantic model with v2 fields (user_id, email, company_id, phone_number)
    """
    print(
        f"📧 [V2 HANDLER] Sending welcome email to {data.email} (user_id={data.user_id})"
    )
    print(f"📱 [V2 HANDLER] Sending SMS to {data.phone_number}")
    print(f"   ✅ This is a v2 handler receiving a v2 event (normal operation)")
    # In a real app, you'd send email and SMS here
    return f"Welcome email and SMS sent to {data.email} (v2 handler)"


# v2 Handler 2: Analytics with Phone
@subscribe("user.signup.completed", version="v2")
def update_user_analytics_v2(data):
    """
    Update analytics for new signup with phone number (v2 handler).

    This handler subscribes to v2 and receives v2 events normally.
    It validates against v2 schema, so phone_number field is available.

    Args:
        data: Pydantic model with v2 fields (user_id, email, company_id, phone_number)
    """
    print(f"📊 [V2 HANDLER] Updating analytics for user {data.user_id}")
    print(f"   📱 Phone number: {data.phone_number}")
    print(f"   ✅ This is a v2 handler receiving a v2 event (normal operation)")
    # In a real app, you'd update analytics with phone number here
    return f"Analytics updated for user {data.user_id} with phone {data.phone_number} (v2 handler)"


# v2 Handler 3: Phone Verification
@subscribe("user.signup.completed", version="v2")
def verify_phone_number_v2(data):
    """
    Verify phone number for new signup (v2 handler - v2-only feature).

    This handler subscribes to v2 and receives v2 events normally.
    It requires phone_number, which is only available in v2.

    Args:
        data: Pydantic model with v2 fields (user_id, email, company_id, phone_number)
    """
    print(
        f"📱 [V2 HANDLER] Verifying phone number {data.phone_number} for user {data.user_id}"
    )
    print(f"   ✅ This is a v2 handler receiving a v2 event (normal operation)")
    print(f"   ✅ phone_number field is available in v2 schema")
    # In a real app, you'd verify the phone number here
    return f"Phone verification initiated for {data.phone_number} (v2 handler)"


# Configure queue routing AFTER handlers are registered
from celery_salt.core.decorators import (
    DEFAULT_EXCHANGE_NAME,
    DEFAULT_DISPATCHER_TASK_NAME,
)
from kombu import Exchange, Queue, binding

# Create topic exchange
tchu_exchange = Exchange(DEFAULT_EXCHANGE_NAME, type="topic", durable=True)

# Get subscribed routing keys (handlers are now registered)
routing_keys = get_subscribed_routing_keys(celery_app=app, force_import=False)

# Create bindings for each routing key
if routing_keys:
    bindings_list = [binding(tchu_exchange, routing_key=key) for key in routing_keys]
else:
    # Fallback: bind to all routing keys if no handlers found
    bindings_list = [binding(tchu_exchange, routing_key="#")]

# Declare queue with bindings
queue_name = "celerysalt_events"
event_queue = Queue(
    queue_name,
    exchange=tchu_exchange,
    bindings=bindings_list,
    durable=True,
    auto_delete=False,
)

# Set queues - this tells Celery to ONLY consume from these queues
app.conf.task_queues = (event_queue,)

# Set as default queue so worker consumes from it
app.conf.task_default_queue = queue_name

# Configure queue routing for the dispatcher
app.conf.task_routes = {
    DEFAULT_DISPATCHER_TASK_NAME: {
        "queue": queue_name,
    },
}

# IMPORTANT: The queue is bound to the topic exchange (tchu_exchange)
# Messages published to the topic exchange with matching routing keys will be delivered to this queue


if __name__ == "__main__":
    # Print registered handlers
    print()
    print("=" * 70)
    print("📋 Registered Event Handlers:")
    print("=" * 70)
    routing_keys = get_subscribed_routing_keys(celery_app=app)
    for key in routing_keys:
        print(f"  - {key}")
    print()
    print("=" * 70)
    print("🔍 Handler Summary:")
    print("=" * 70)
    print()
    print("V1 Handlers (Backward Compatible):")
    print("  - send_welcome_email_v1 (version='v1')")
    print("  - update_user_analytics_v1 (version='v1')")
    print("  → Will receive v2 events with WARNINGS")
    print("  → Validates against v1 schema (phone_number ignored)")
    print()
    print("V2 Handlers (Normal Operation):")
    print("  - send_welcome_email_v2 (version='v2')")
    print("  - update_user_analytics_v2 (version='v2')")
    print("  - verify_phone_number_v2 (version='v2')")
    print("  → Will receive v2 events normally")
    print("  → Validates against v2 schema (phone_number available)")
    print()
    print("=" * 70)
    print("🚀 Starting Celery worker...")
    print("   Run: celery -A subscriber worker --loglevel=info")
    print()
    print("💡 When v2 events are published:")
    print("   1. v1 handlers will process them (backward compatible)")
    print("   2. Worker logs will show WARNING: 'Subscriber is on an older version'")
    print("   3. v2 handlers will process them normally")
    print("=" * 70)
