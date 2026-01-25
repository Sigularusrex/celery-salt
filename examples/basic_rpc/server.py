"""
Example: RPC Server (Handler)

This script demonstrates how to handle RPC calls using CelerySalt.
RPC handlers process requests and return responses synchronously.

Prerequisites:
    - RabbitMQ running on localhost:5672
    - Redis running on localhost:6379 (for Celery result backend)
    - Celery configured (see celery_config.py)

Run:
    celery -A server worker --loglevel=info
"""

from celery import Celery
from celery_salt import event, subscribe, RPCError
from celery_salt.integrations.dispatcher import create_topic_dispatcher, get_subscribed_routing_keys

# Define the RPC request schema (must match client)
@event("rpc.calculator.add", mode="rpc")
class CalculatorAddRequest:
    """RPC request to add two numbers."""
    a: float
    b: float


# Define response schema (optional but recommended)
@event.response("rpc.calculator.add")
class CalculatorAddResponse:
    """Response from calculator add operation."""
    result: float
    operation: str = "add"


# Define error schema (optional but recommended)
@event.error("rpc.calculator.add")
class CalculatorAddError:
    """Error response from calculator add operation."""
    error_code: str
    error_message: str
    details: dict | None = None


# Create Celery app
app = Celery("server")
app.conf.broker_url = "amqp://guest:guest@localhost:5672//"
app.conf.result_backend = "redis://localhost:6379/0"  # Required for RPC
app.conf.task_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.result_serializer = "json"
app.conf.timezone = "UTC"
app.conf.enable_utc = True

# Create the dispatcher task
dispatcher = create_topic_dispatcher(app)

# Configure queue routing for the dispatcher
from celery_salt.core.decorators import DEFAULT_EXCHANGE_NAME, DEFAULT_DISPATCHER_TASK_NAME

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


# RPC Handler
@subscribe("rpc.calculator.add")
def handle_calculator_add(data: CalculatorAddRequest) -> CalculatorAddResponse:
    """
    Handle calculator add RPC request.
    
    Returns:
        CalculatorAddResponse: The result of the addition
    """
    print(f"🔢 Processing RPC request: {data.a} + {data.b}")
    
    # Validate inputs (example: prevent division by zero scenarios)
    if abs(data.a) > 1e10 or abs(data.b) > 1e10:
        raise RPCError(
            error_code="VALUE_TOO_LARGE",
            error_message="Input values are too large",
            details={"a": data.a, "b": data.b, "max": 1e10}
        )
    
    # Perform calculation
    result = data.a + data.b
    
    print(f"  ✅ Result: {result}")
    
    # Return response (will be validated against CalculatorAddResponse schema)
    return CalculatorAddResponse(
        result=result,
        operation="add"
    )


if __name__ == "__main__":
    # Print registered handlers
    print("📋 Registered RPC handlers:")
    routing_keys = get_subscribed_routing_keys(celery_app=app)
    for key in routing_keys:
        print(f"  - {key}")
    print()
    print("🚀 Starting Celery worker...")
    print("   Run: celery -A server worker --loglevel=info")
    print()
    print("💡 This script should be imported by Celery, not run directly.")
