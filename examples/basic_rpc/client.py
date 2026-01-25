"""
Example: RPC Client

This script demonstrates how to make RPC calls using CelerySalt.
RPC calls are synchronous: you send a request and wait for a response.

Prerequisites:
    - RabbitMQ running on localhost:5672
    - Redis running on localhost:6379 (for Celery result backend)
    - Celery worker running (see server.py)

Run:
    python client.py
"""

from celery import Celery
from celery_salt import event, RPCError

# Configure Celery (required for RPC calls)
from celery_salt.core.decorators import (
    DEFAULT_EXCHANGE_NAME,
    DEFAULT_DISPATCHER_TASK_NAME,
)

app = Celery("client")
app.conf.broker_url = "amqp://guest:guest@localhost:5672//"
app.conf.result_backend = "redis://localhost:6379/0"  # Required for RPC
app.conf.task_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.result_serializer = "json"
app.conf.timezone = "UTC"
app.conf.enable_utc = True

# Configure routing: route dispatcher task to topic exchange
# This allows Celery's send_task() to publish to the topic exchange
app.conf.task_routes = {
    DEFAULT_DISPATCHER_TASK_NAME: {
        "exchange": DEFAULT_EXCHANGE_NAME,
        "exchange_type": "topic",
    },
}

# Set the Celery app as the default
app.set_default()


# Option 1: Decorator-based API (simple)
# Define the RPC request schema
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
from celery_salt import SaltEvent
from pydantic import BaseModel


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

    def validate_inputs(self) -> bool:
        """Validate that inputs are within acceptable range."""
        return abs(self.data.a) <= 1e10 and abs(self.data.b) <= 1e10

    def call(self, timeout: int = 30, **kwargs):
        """Custom call with validation."""
        if not self.validate_inputs():
            # Return error response directly
            return self.Error(
                error_code="VALUE_TOO_LARGE",
                error_message="Input values are too large",
                details={"a": self.data.a, "b": self.data.b, "max": 1e10},
            )
        return super().call(timeout=timeout, **kwargs)


def main():
    """Make RPC calls to the calculator service using both APIs."""
    print("🔢 Making RPC calls to calculator service...")
    print()
    print("=" * 60)
    print("Option 1: Decorator-based API (Add operation)")
    print("=" * 60)
    print()

    # Test cases for decorator-based API
    test_cases = [
        (10, 5),
        (100, 200),
        (-5, 10),
        (3.14, 2.86),
    ]

    for a, b in test_cases:
        try:
            print(f"Request: {a} + {b} = ?")

            # Option 1: Decorator-based API (class method)
            response = CalculatorAddRequest.call(a=a, b=b, timeout=10)

            # Check if it's an error response
            if isinstance(response, CalculatorAddError):
                print(f"  ❌ Error: {response.error_message} ({response.error_code})")
            else:
                # Success response
                print(f"  ✅ Result: {response.result}")
                print(f"     Operation: {response.operation}")

        except RPCError as e:
            print(f"  ❌ RPC Error: {e.error_message} ({e.error_code})")
        except Exception as e:
            print(f"  ❌ Unexpected error: {e}")

        print()

    print("=" * 60)
    print("Option 2: Class-based API (Add operation, v2)")
    print("=" * 60)
    print()

    # Test cases for class-based API (v2)
    v2_cases = [
        (5, 4),
        (10, 3),
        (2.5, 4.0),
        (1e11, 1),  # This should trigger validation error
    ]

    for a, b in v2_cases:
        try:
            print(f"Request (v2): {a} + {b} = ?")

            # Option 2: Class-based API (instance method) - uses v2 schema
            request = CalculatorAddRequestV2(a=a, b=b)
            response = request.call(timeout=10)

            # Check if it's an error response
            if isinstance(response, CalculatorAddRequestV2.Error):
                print(f"  ❌ Error: {response.error_message} ({response.error_code})")
            else:
                # Success response
                print(f"  ✅ Result: {response.result}")
                print(f"     Operation: {response.operation}")

        except RPCError as e:
            print(f"  ❌ RPC Error: {e.error_message} ({e.error_code})")
        except Exception as e:
            print(f"  ❌ Unexpected error: {e}")

        print()

    print("✅ All RPC calls completed!")


if __name__ == "__main__":
    main()
