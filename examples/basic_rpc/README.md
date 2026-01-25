# Basic RPC Example

This example demonstrates the **RPC (Request/Response)** pattern using CelerySalt.

## What This Example Shows

- How to define RPC request/response/error schemas
- How to make RPC calls (synchronous request/response)
- How to handle RPC requests
- Error handling with `RPCError`
- Response validation with `@event.response()` and `@event.error()`

## Architecture

```
Client → RabbitMQ Exchange → Server (Handler) → Response → Client
```

The client makes a synchronous call and waits for the server's response.

## Prerequisites

1. **Start infrastructure services** (RabbitMQ and Redis)
   
   **Option A: Using Docker Compose (Recommended)**
   ```bash
   cd examples
   docker-compose up -d
   ```
   This starts both RabbitMQ and Redis.
   
   **Option B: Manual Docker**
   ```bash
   # RabbitMQ
   docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
   
   # Redis
   docker run -d --name redis -p 6379:6379 redis:7-alpine
   ```

2. **Install CelerySalt in development mode**
   
   Since the package isn't published yet, install it in editable mode:
   ```bash
   # From the project root (celery-salt/)
   pip install -e .
   ```
   
   This makes `celery_salt` available for import without publishing to PyPI.

3. **Install other dependencies**
   ```bash
   pip install celery kombu redis
   ```

## Running the Example

### Terminal 1: Start the Server (Worker)

```bash
cd examples/basic_rpc
celery -A server worker --loglevel=info
```

You should see:
```
[tasks]
  . celery_salt.dispatch_event
  . celery_salt.rpc.calculator.add.handle_calculator_add
```

### Terminal 2: Run the Client

```bash
cd examples/basic_rpc
python client.py
```

You should see:
```
🔢 Making RPC calls to calculator service...

Request: 10 + 5 = ?
  ✅ Result: 15.0
     Operation: add

Request: 100 + 200 = ?
  ✅ Result: 300.0
     Operation: add

✅ All RPC calls completed!
```

### Check Terminal 1 (Worker)

You should see the server processing requests:
```
🔢 Processing RPC request: 10.0 + 5.0
  ✅ Result: 15.0
```

## Key Concepts

### RPC Request Schema

```python
@event("rpc.calculator.add", mode="rpc")
class CalculatorAddRequest:
    a: float
    b: float
```

### Response Schema (Optional but Recommended)

```python
@event.response("rpc.calculator.add")
class CalculatorAddResponse:
    result: float
    operation: str = "add"
```

### Error Schema (Optional but Recommended)

```python
@event.error("rpc.calculator.add")
class CalculatorAddError:
    error_code: str
    error_message: str
    details: dict | None = None
```

### Making RPC Calls

```python
response = CalculatorAddRequest.call(a=10, b=5, timeout=10)

if isinstance(response, CalculatorAddError):
    print(f"Error: {response.error_message}")
else:
    print(f"Result: {response.result}")
```

### Handling RPC Requests

```python
@subscribe("rpc.calculator.add")
def handle_calculator_add(data: CalculatorAddRequest) -> CalculatorAddResponse:
    result = data.a + data.b
    return CalculatorAddResponse(result=result, operation="add")
```

### Error Handling

```python
@subscribe("rpc.calculator.add")
def handle_calculator_add(data: CalculatorAddRequest) -> CalculatorAddResponse:
    if data.a > 1e10:
        raise RPCError(
            error_code="VALUE_TOO_LARGE",
            error_message="Input value too large"
        )
    return CalculatorAddResponse(result=data.a + data.b, operation="add")
```

## Important Notes

1. **Redis Required**: RPC requires a result backend (Redis) because Celery needs to store and retrieve results.

2. **Synchronous**: RPC calls block until a response is received or timeout occurs.

3. **Schema Validation**: Response and error schemas are validated automatically if defined.

4. **Error Handling**: Use `RPCError` for application-level errors. The client receives a validated error response.

## Next Steps

- Try adding more RPC operations (subtract, multiply, divide)
- Experiment with error handling
- Add timeout handling
- See the broadcast example for fire-and-forget patterns
