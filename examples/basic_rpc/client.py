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
app = Celery("client")
app.conf.broker_url = "amqp://guest:guest@localhost:5672//"
app.conf.result_backend = "redis://localhost:6379/0"  # Required for RPC
app.conf.task_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.result_serializer = "json"
app.conf.timezone = "UTC"
app.conf.enable_utc = True

# Set the Celery app as the default
app.set_default()

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


def main():
    """Make RPC calls to the calculator service."""
    print("🔢 Making RPC calls to calculator service...")
    print()

    # Test cases
    test_cases = [
        (10, 5),
        (100, 200),
        (-5, 10),
        (3.14, 2.86),
    ]

    for a, b in test_cases:
        try:
            print(f"Request: {a} + {b} = ?")
            
            # Make RPC call (synchronous, waits for response)
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

    print("✅ All RPC calls completed!")


if __name__ == "__main__":
    main()
