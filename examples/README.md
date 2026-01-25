# CelerySalt Examples

This directory contains example implementations demonstrating how to use CelerySalt.

## Examples

### 1. Basic Broadcast (`basic_broadcast/`)

Demonstrates the **pub/sub (broadcast)** pattern:
- One event published → multiple subscribers receive it
- Fire-and-forget pattern
- No response expected

**Use cases:**
- User signup notifications
- Order status updates
- Audit logging
- Analytics events

[View Example →](basic_broadcast/README.md)

### 2. Basic RPC (`basic_rpc/`)

Demonstrates the **RPC (Request/Response)** pattern:
- Client sends request → waits for response
- Synchronous communication
- Response validation with schemas

**Use cases:**
- API calls between services
- Data queries
- Calculations
- Synchronous operations

[View Example →](basic_rpc/README.md)

## Quick Start with Docker Compose

The easiest way to run the examples is using Docker Compose:

### 1. Start Infrastructure Services

```bash
cd examples
docker-compose up -d
```

This starts:
- **RabbitMQ** on `localhost:5672` (Management UI: http://localhost:15672)
- **Redis** on `localhost:6379` (required for RPC example)

### 2. Run Examples

Follow the instructions in each example's README:
- [Basic Broadcast](basic_broadcast/README.md)
- [Basic RPC](basic_rpc/README.md)

### 3. Stop Services

```bash
docker-compose down
```

To also remove volumes (clears all data):
```bash
docker-compose down -v
```

## Manual Setup

If you prefer to run services manually:

### Prerequisites

1. **RabbitMQ** (required for both examples)
   ```bash
   docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
   ```

2. **Redis** (required for RPC example only)
   ```bash
   docker run -d --name redis -p 6379:6379 redis:7-alpine
   ```

3. **Install CelerySalt in development mode**
   
   Since the package isn't published yet, install it in editable mode:
   ```bash
   # From the project root (celery-salt/)
   pip install -e .
   ```
   
   This makes `celery_salt` available for import without publishing to PyPI.

4. **Install other dependencies**
   ```bash
   pip install celery kombu redis
   ```

## Running Examples

Each example has its own README with detailed instructions. In general:

1. **Start the worker** (subscriber/server):
   ```bash
   cd examples/basic_broadcast  # or basic_rpc
   celery -A subscriber worker --loglevel=info  # or server for RPC
   ```

2. **Run the publisher/client**:
   ```bash
   python publisher.py  # or client.py for RPC
   ```

## Architecture Patterns

### Broadcast Pattern
```
Publisher → Exchange → Subscriber 1
                      → Subscriber 2
                      → Subscriber 3
```

### RPC Pattern
```
Client → Exchange → Server → Response → Client
```

## Key Concepts

### Event Definition
```python
@event("user.signup.completed")
class UserSignupCompleted:
    user_id: int
    email: str
```

### Publishing (Broadcast)
```python
UserSignupCompleted.publish(user_id=123, email="user@example.com")
```

### Subscribing
```python
@subscribe("user.signup.completed")
def handle_signup(data: UserSignupCompleted):
    # Process event
    pass
```

### RPC Call
```python
response = CalculatorAddRequest.call(a=10, b=5, timeout=10)
```

### RPC Handler
```python
@subscribe("rpc.calculator.add")
def handle_add(data: CalculatorAddRequest) -> CalculatorAddResponse:
    return CalculatorAddResponse(result=data.a + data.b)
```

## Troubleshooting

### Services Not Starting

If Docker Compose fails:
1. Check if ports 5672, 15672, or 6379 are already in use
2. Stop conflicting services or change ports in `docker-compose.yml`

### Connection Errors

If you see connection errors:
1. Verify services are running: `docker-compose ps`
2. Check service logs: `docker-compose logs rabbitmq` or `docker-compose logs redis`
3. Wait a few seconds after starting services (health checks may need time)

### RabbitMQ Management UI

Access the management interface at http://localhost:15672
- Username: `guest`
- Password: `guest`

Useful for:
- Viewing queues and exchanges
- Monitoring message flow
- Debugging routing issues

## Next Steps

- Explore the examples in detail
- Modify them to fit your use case
- Check the main [README.md](../README.md) for more information
- Read the [Design Document](../CELERYSALT_DESIGN.md) for architecture details
