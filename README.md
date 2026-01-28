# CelerySalt

A schema-driven event API on top of Celery: publish/subscribe (broadcast) and RPC with
Pydantic validation and a schema registry.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

## Features

- **Pydantic schemas**: type-checked event payloads with validation.
- **Broadcast**: fire-and-forget pub/sub (one event to many subscribers).
- **RPC**: request/response with response and error schema validation.
- **Schema registry**: schema registration and lookup by topic/version.
- **Versioning**: topic stays stable; versions are metadata.
- **Django integration**: optional helpers for wiring queues and module discovery.
- **Protocol compatibility**: interoperates with `tchu-tchu` (`tchu_events` exchange and `_tchu_meta`).

## Quick Start

### Installation

```bash
pip install celery-salt
```

### Broadcast Example

```python
from celery_salt import event, subscribe

# Define event schema
@event("user.signup.completed")
class UserSignupCompleted:
    user_id: int
    email: str
    company_id: int
    signup_source: str = "web"

# Publish event
UserSignupCompleted.publish(
    user_id=123,
    email="alice@example.com",
    company_id=1,
    signup_source="web"
)

# Subscribe to event
@subscribe("user.signup.completed")
def send_welcome_email(data: UserSignupCompleted):
    print(f"Sending welcome email to {data.email}")
```

### RPC Example

```python
from celery_salt import event, subscribe, RPCError

# Define RPC request/response schemas
@event("rpc.calculator.add", mode="rpc")
class CalculatorAddRequest:
    a: float
    b: float

@event.response("rpc.calculator.add")
class CalculatorAddResponse:
    result: float
    operation: str = "add"

@event.error("rpc.calculator.add")
class CalculatorAddError:
    error_code: str
    error_message: str

# Handler
@subscribe("rpc.calculator.add")
def handle_add(data: CalculatorAddRequest) -> CalculatorAddResponse:
    return CalculatorAddResponse(result=data.a + data.b, operation="add")

# Client call
response = CalculatorAddRequest.call(a=10, b=5, timeout=10)
print(f"Result: {response.result}")  # 15.0
```

## Architecture

```
Publisher → RabbitMQ Exchange (tchu_events) → Subscribers
```

- **Exchange**: `tchu_events` (topic exchange, protocol compatible)
- **Routing**: Topic-based with wildcard support (`user.*`, `#`)
- **Serialization**: JSON with Pydantic validation
- **Result Backend**: Redis (required for RPC)

## Documentation

- **Examples**: [./examples/](./examples/)
- **Docs**: [./docs/](./docs/)
- **Typing subscriber payloads**: [./docs/TYPING_SUBSCRIBER_EVENTS.md](./docs/TYPING_SUBSCRIBER_EVENTS.md)

## Requirements

- Python 3.10+
- Celery 5.3+
- RabbitMQ (message broker)
- Redis (optional, required for RPC)

## Examples

See the [examples](./examples/) directory for complete working examples:

- [Basic Broadcast](./examples/basic_broadcast/) - Pub/sub messaging
- [Basic RPC](./examples/basic_rpc/) - Request/response pattern

Run examples with Docker Compose:

```bash
cd examples
docker-compose up -d  # Starts RabbitMQ and Redis
```

## Key Concepts

### Event Schemas

Schemas are defined using Pydantic models and registered at import time:

```python
@event("user.created")
class UserCreated:
    user_id: int
    email: str
    created_at: datetime
```

### Publishing Events

```python
# Broadcast (fire-and-forget)
UserCreated.publish(user_id=123, email="user@example.com", created_at=datetime.now())

# RPC (synchronous)
response = CalculatorAddRequest.call(a=10, b=5, timeout=10)
```

### Subscribing to Events

```python
@subscribe("user.created")
def handle_user_created(data: UserCreated):
    # Process event
    pass
```

### RPC Response Validation

```python
@event.response("rpc.calculator.add")
class CalculatorAddResponse:
    result: float

@event.error("rpc.calculator.add")
class CalculatorAddError:
    error_code: str
    error_message: str
```

## Protocol Compatibility

CelerySalt maintains protocol compatibility with `tchu-tchu`:
- Same exchange name: `tchu_events`
- Same message format: `_tchu_meta` field
- Same routing key conventions

This allows gradual migration: apps using `celery-salt` can communicate with apps still using `tchu-tchu`.

## Development

```bash
git clone https://github.com/sigularusrex/celery-salt.git
cd celery-salt

# tests
python -m pytest
```

## License

MIT License - see [LICENSE](./LICENSE) file for details.

## Contributing

Please open an issue or pull request on GitHub.

## Links

- **GitHub**: `https://github.com/sigularusrex/celery-salt`
- **Issues**: `https://github.com/sigularusrex/celery-salt/issues`
