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
from kombu import Exchange, Queue, binding
from pydantic import BaseModel

from celery_salt import RPCError, SaltEvent, event, subscribe
from celery_salt.core.decorators import (
    DEFAULT_DISPATCHER_TASK_NAME,
    DEFAULT_EXCHANGE_NAME,
)
from celery_salt.integrations.dispatcher import (
    create_topic_dispatcher,
    get_subscribed_routing_keys,
)


# Option 1: Decorator-based API (simple)
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


# Option 2: Class-based API (for custom logic)
class CalculatorAddRequestV2(SaltEvent):
    """RPC request to add two numbers (class-based version, v2)."""

    class Schema(BaseModel):
        a: float
        b: float

    class Response(BaseModel):
        result: float
        operation: str = "add"

    class Error(BaseModel):
        error_code: str
        error_message: str
        details: dict | None = None

    class Meta:
        topic = "rpc.calculator.add"
        version = "v2"
        mode = "rpc"
        description = "Add two numbers (class-based API, v2)"


# Create Celery app
app = Celery("server")
app.conf.broker_url = "amqp://guest:guest@localhost:5672//"
app.conf.result_backend = "redis://localhost:6379/0"  # Required for RPC
app.conf.task_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.result_serializer = "json"
app.conf.timezone = "UTC"
app.conf.enable_utc = True

# Create the dispatcher task first (needed for routing)
dispatcher = create_topic_dispatcher(app)


# RPC Handlers (must be before queue setup so handlers are registered)


# Option 1: Decorator-based API handler
@subscribe("rpc.calculator.add")
def handle_calculator_add(data: CalculatorAddRequest) -> CalculatorAddResponse:
    """
    Handle calculator add RPC request (decorator-based API).

    Returns:
        CalculatorAddResponse: The result of the addition
    """
    print(f"🔢 Processing RPC request (decorator-based): {data.a} + {data.b}")

    # Validate inputs (example: prevent division by zero scenarios)
    if abs(data.a) > 1e10 or abs(data.b) > 1e10:
        raise RPCError(
            error_code="VALUE_TOO_LARGE",
            error_message="Input values are too large",
            details={"a": data.a, "b": data.b, "max": 1e10},
        )

    # Perform calculation
    result = data.a + data.b

    print(f"  ✅ Result: {result}")

    # Return response (will be validated against CalculatorAddResponse schema)
    return CalculatorAddResponse(result=result, operation="add")


# Option 2: Class-based API handler (v2)
# Note: version="v2" specifies we want v2 events, default is "latest"
@subscribe("rpc.calculator.add", version="v2")
def handle_calculator_add_v2(data) -> dict:
    """
    Handle calculator add RPC request (class-based API, v2).

    The data parameter is a dynamically-typed Pydantic model from the schema registry.
    It has fields: a (float), b (float)

    Returns:
        dict: Response matching CalculatorAddRequestV2.Response schema
    """
    print(f"🔢 Processing RPC request (class-based v2): {data.a} + {data.b}")

    # Validate inputs
    if abs(data.a) > 1e10 or abs(data.b) > 1e10:
        raise RPCError(
            error_code="VALUE_TOO_LARGE",
            error_message="Input values are too large",
            details={"a": data.a, "b": data.b, "max": 1e10},
        )

    # Perform calculation
    result = data.a + data.b

    print(f"  ✅ Result: {result}")

    # Return response dict (will be validated against CalculatorAddRequestV2.Response schema)
    return {"result": result, "operation": "add"}


# Configure queue routing AFTER handlers are registered
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
