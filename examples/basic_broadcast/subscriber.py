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
from celerysalt import event, subscribe
from celerysalt.integrations.dispatcher import create_topic_dispatcher, get_subscribed_routing_keys

# Define the event schema (must match publisher)
@event("user.signup.completed")
class UserSignupCompleted:
    """Event published when a user completes signup."""
    user_id: int
    email: str
    company_id: int
    signup_source: str = "web"


# Create Celery app
app = Celery("subscriber")
app.conf.broker_url = "amqp://guest:guest@localhost:5672//"
app.conf.result_backend = "rpc://"
app.conf.task_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.result_serializer = "json"
app.conf.timezone = "UTC"
app.conf.enable_utc = True

# Create the dispatcher task
dispatcher = create_topic_dispatcher(app)

# Configure queue routing for the dispatcher
from celerysalt.core.decorators import DEFAULT_EXCHANGE_NAME, DEFAULT_DISPATCHER_TASK_NAME

app.conf.task_routes = {
    DEFAULT_DISPATCHER_TASK_NAME: {
        "queue": "celerysalt_events",
        "exchange": DEFAULT_EXCHANGE_NAME,
        "exchange_type": "topic",
        "routing_key": DEFAULT_DISPATCHER_TASK_NAME,
    },
}

# Declare exchange and queue
from kombu import Exchange, Queue

app.conf.task_queues = (
    Queue(
        "celerysalt_events",
        exchange=Exchange(DEFAULT_EXCHANGE_NAME, type="topic"),
        routing_key="#",  # Bind to all routing keys
    ),
)


# Subscribe to events
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
    print(f"🔔 Admin notification: New user {data.email} signed up via {data.signup_source}")
    # In a real app, you'd send admin notification here
    return f"Admin notified about user {data.user_id}"


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
