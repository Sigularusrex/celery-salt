"""
Example: Broadcast Event Subscriber

This script demonstrates how to subscribe to broadcast events using CelerySalt.
Multiple subscribers can listen to the same event topic.

Prerequisites:
    - RabbitMQ running on localhost:5672
    - Celery configured (see celery_config.py)

Run:
    celery -A subscriber worker --loglevel=info
"""

from celery import Celery
from celery_salt import event, subscribe, SaltEvent
from celery_salt.integrations.dispatcher import (
    create_topic_dispatcher,
    get_subscribed_routing_keys,
)
from pydantic import BaseModel


# Option 1: Decorator-based API
# Define the event schema (must match publisher)
@event("user.signup.completed")
class UserSignupCompleted:
    """Event published when a user completes signup."""

    user_id: int
    email: str
    company_id: int
    signup_source: str = "web"


# Option 2: Class-based API
# Note: For subscribers, we don't need to define the event class
# The @subscribe decorator fetches the schema from the registry automatically
# But we can define it for type hints if we want
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


# Create Celery app
app = Celery("subscriber")
app.conf.broker_url = "amqp://guest:guest@localhost:5672//"
app.conf.result_backend = "rpc://"
app.conf.task_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.result_serializer = "json"
app.conf.timezone = "UTC"
app.conf.enable_utc = True

# Create the dispatcher task first (needed for routing)
dispatcher = create_topic_dispatcher(app)

# Subscribe to events (must be before queue setup so handlers are registered)
@subscribe("user.signup.completed", autoretry_for=(Exception,), max_retries=3)
def send_welcome_email(data: UserSignupCompleted):
    """Send welcome email to new user."""
    print(f"📧 Sending welcome email to {data.email} (user_id={data.user_id})")
    # In a real app, you'd send an email here
    return f"Welcome email sent to {data.email}"


@subscribe("user.signup.completed")
def update_user_analytics(data: UserSignupCompleted):
    """Update analytics for new signup."""
    print(f"📊 Updating analytics for user {data.user_id} from {data.signup_source}")
    # In a real app, you'd update analytics here
    return f"Analytics updated for user {data.user_id}"


@subscribe("user.signup.completed")
def notify_admin(data: UserSignupCompleted):
    """Notify admin about new signup."""
    print(
        f"🔔 Admin notification: New user {data.email} signed up via {data.signup_source}"
    )
    # In a real app, you'd send admin notification here
    return f"Admin notified about user {data.user_id}"


# Option 2: Class-based API handlers (v2)
# These handlers receive dynamically-typed Pydantic models from the schema registry
# Note: version="v2" specifies we want v2 events, default is "latest"
@subscribe("user.signup.completed", version="v2")
def send_welcome_email_v2(data):
    """
    Send welcome email to new user (class-based API, v2).

    Args:
        data: Dynamic Pydantic model with fields: user_id, email, company_id, signup_source
    """
    print(f"📧 [V2] Sending welcome email to {data.email} (user_id={data.user_id})")
    # In a real app, you'd send an email here
    return f"Welcome email sent to {data.email}"


@subscribe("user.signup.completed", version="v2")
def update_user_analytics_v2(data):
    """
    Update analytics for new signup (class-based API, v2).

    Args:
        data: Dynamic Pydantic model with fields: user_id, email, company_id, signup_source
    """
    print(
        f"📊 [V2] Updating analytics for user {data.user_id} from {data.signup_source}"
    )
    # In a real app, you'd update analytics here
    return f"Analytics updated for user {data.user_id}"


@subscribe("user.signup.completed", version="v2")
def notify_admin_v2(data):
    """
    Notify admin about new signup (class-based API, v2).

    Args:
        data: Dynamic Pydantic model with fields: user_id, email, company_id, signup_source
    """
    print(
        f"🔔 [V2] Admin notification: New user {data.email} signed up via {data.signup_source}"
    )
    # In a real app, you'd send admin notification here
    return f"Admin notified about user {data.user_id}"


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
    print("📋 Registered event handlers:")
    routing_keys = get_subscribed_routing_keys(celery_app=app)
    for key in routing_keys:
        print(f"  - {key}")
    print()
    print("🚀 Starting Celery worker...")
    print("   Run: celery -A subscriber worker --loglevel=info")
    print()
    print("💡 This script should be imported by Celery, not run directly.")
