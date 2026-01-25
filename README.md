# CelerySalt

A modern, event-driven architecture library for Python that extends Celery with schema-validated event publishing/subscribing patterns. Built with Pydantic for type safety and import-time schema registration.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

> **🚀 v1.0.0** - First release! Pydantic-based event schemas, import-time registration, RPC support, and protocol compatibility with tchu-tchu.

## Features

- ✨ **Pydantic-Based Schemas** - Type-safe event definitions with automatic validation
- 🚀 **Import-Time Registration** - Schemas registered at import time for early error detection
- 📡 **Broadcast Events** - Fire-and-forget pub/sub messaging (one event → many subscribers)
- ⚡ **RPC Support** - Synchronous request/response with response/error schema validation
- 🔄 **Protocol Compatible** - Works with existing tchu-tchu applications
- 🎯 **Framework Agnostic** - Core library works with any Python app (Django optional)
- 🛡️ **Schema Registry** - Centralized schema management (in-memory, PostgreSQL, Cloud)
- 🔁 **Celery Integration** - Full Celery features: retries, time limits, rate limiting, monitoring
- 📦 **Simple API** - Decorator-based: `@event` and `@subscribe`

## Quick Start

### Installation

```bash
pip install celery-salt
```

### Broadcast Example

```python
from celerysalt import event, subscribe

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
from celerysalt import event, subscribe, RPCError

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

- [Examples](./examples/) - Working examples for broadcast and RPC
- [Design Document](./CELERYSALT_DESIGN.md) - Full architecture and design
- [Implementation Context](./IMPLEMENTATION_CONTEXT.md) - Development context

## Requirements

- Python 3.10+
- Celery 5.3+
- RabbitMQ (message broker)
- Redis (optional, required for RPC)

## Installation

```bash
# Basic installation
pip install celery-salt

# With Django support
pip install celery-salt[django]

# With all extras
pip install celery-salt[all]
```

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
# Clone repository
git clone https://github.com/sigularusrex/celery-salt.git
cd celery-salt

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run examples
cd examples
docker-compose up -d
celery -A basic_broadcast.subscriber worker --loglevel=info
```

## License

MIT License - see [LICENSE](./LICENSE) file for details.

## Contributing

Contributions welcome! Please open an issue or pull request on GitHub.

## Links

- **GitHub**: https://github.com/sigularusrex/celery-salt
- **Documentation**: https://github.com/sigularusrex/celery-salt
- **Issues**: https://github.com/sigularusrex/celery-salt/issues
