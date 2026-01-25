# CelerySalt Architecture Design - Conversation Export

**Date:** January 25, 2026  
**Topic:** Event-driven architecture library design for Python/Celery users  
**Purpose:** Export for Cursor IDE context

---

## Executive Summary

This conversation covers the complete architectural design for **CelerySalt**, an event-driven architecture library for Python that extends Celery with event publishing/subscribing patterns. Key decisions:

1. **Import-time schema registration** - Schemas registered when modules load, not on first publish
2. **No shared code packages** - Schema registry eliminates need for `cs_common` across services
3. **Framework agnostic** - Works with Django, Flask, FastAPI, plain Python
4. **Pydantic-based** - Migrating from Django REST Framework serializers to Pydantic
5. **Decorator API** - `@event` and `@subscribe` decorators for clean DX
6. **Open core model** - Free library + paid cloud/premium UI
7. **Separate distributions** - PyPI package (library) + Docker images (UI)

---

## Key Architectural Decisions

### 1. Import-Time Registration (Not First-Publish)

**The Problem We Solved:**
Originally considered registering schemas on first publish, but this has issues:
- Race conditions (what if publisher never publishes?)
- Deployment issues (new schema not registered until runtime)
- No complete event catalog
- Can't validate in CI/CD

**The Solution:**
```python
# Schema registers when Python imports the module
@event("user.signup.completed")
class UserSignup:
    user_id: int
    email: str

# In celery.py
import myapp.events.user_events  # ← Schema registered here!

# Benefits:
# ✅ Complete event catalog before any events published
# ✅ Schema conflicts detected at startup
# ✅ CI/CD can validate before deployment
# ✅ Zero runtime overhead
```

### 2. PostgreSQL is Optional

**Infrastructure requirements by use case:**

| Use Case | RabbitMQ | Redis | PostgreSQL |
|----------|----------|-------|------------|
| Broadcast only (no registry) | Required | Optional | Not needed |
| Broadcast with registry | Required | Optional | Required |
| RPC (no registry) | Required | Required | Not needed |
| RPC with registry | Required | Required | Required |
| With Management UI | Required | Recommended | Required |

**Key insight:** Library works with just RabbitMQ for broadcast events. PostgreSQL only needed for:
- Centralized schema registry
- Schema versioning
- Management UI
- Cross-service validation

### 3. Redis Required for RPC

**Why both RabbitMQ and Redis?**
- **RabbitMQ**: Message routing and delivery
- **Redis**: Result storage for RPC (Celery limitation)
  - RabbitMQ doesn't have built-in result storage
  - Celery needs somewhere to store return values
  - Required for request/response pattern

### 4. UI Distributed Separately

**Two separate packages:**

1. **PyPI Package** (`pip install celerysalt`)
   - Core library only
   - No frontend code
   - ~1-2 MB package size
   - Repository: `github.com/celerysalt/celerysalt`

2. **Docker Images** (Management UI)
   - `celerysalt/ui:latest` (free)
   - `celerysalt/ui-pro:latest` (paid)
   - Separate repository: `github.com/celerysalt/celerysalt-ui`
   - Optional component

**Why separate?**
- Lightweight Python package
- Independent release cycles
- Different tech stacks (Python vs React)
- Optional component

---

## API Design

### Broadcast Events

```python
from celerysalt import event, subscribe

# Define event (schema registers at import time)
@event("user.signup.completed")
class UserSignup:
    """Emitted when a user completes signup."""
    user_id: int
    email: str
    company_id: int
    signup_source: str = "web"

# Publish event
UserSignup.publish(
    user_id=123,
    email="user@example.com",
    company_id=456,
    signup_source="web"
)

# Subscribe to event (in different service)
@subscribe("user.signup.completed")
def send_welcome_email(data: UserSignup):
    """Handler automatically receives validated data."""
    send_email(
        to=data.email,
        template="welcome",
        context={"user_id": data.user_id}
    )

# With Celery options (retries, timeouts, etc.)
@subscribe(
    "user.signup.completed",
    autoretry_for=(SMTPException, ConnectionError),
    retry_backoff=True,
    max_retries=5,
    time_limit=60,
    rate_limit='100/m',
)
def send_welcome_email(data: UserSignup):
    send_email(data.email, template="welcome")
```

### RPC Events

```python
from celerysalt import event, subscribe, RPCError

# Define request/response schemas
@event("rpc.documents.list", mode="rpc")
class DocumentListRequest:
    user_id: int
    folder_id: int | None = None

@event.response("rpc.documents.list")
class DocumentListResponse:
    documents: list[dict]
    total: int

@event.error("rpc.documents.list")
class DocumentListError:
    error_code: str
    error_message: str

# Caller
response = DocumentListRequest.call(
    user_id=123,
    folder_id=456,
    timeout=10
)

if isinstance(response, DocumentListError):
    print(f"Error: {response.error_message}")
else:
    print(f"Found {response.total} documents")

# Handler
@subscribe("rpc.documents.list")
def handle_list_documents(data: DocumentListRequest) -> DocumentListResponse:
    if not has_access(data.user_id, data.folder_id):
        raise RPCError(
            error_code="NO_ACCESS",
            error_message="User does not have access"
        )
    
    docs = get_documents(data.user_id, data.folder_id)
    return DocumentListResponse(documents=docs, total=len(docs))
```

### TchuFollowActions (State Machines)

```python
from celerysalt.adapters.django import DjangoTchuFollowActions
from django.db import models

class Order(DjangoTchuFollowActions, models.Model):
    """Order with automatic event triggering on state changes."""
    order_id = models.UUIDField(primary_key=True)
    status = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    on_change_rules = models.JSONField(default=list)

# Add rule: when status → "paid", publish event
from celerysalt.patterns.follow_actions import FollowActionHelper

order.on_change_rules.append(
    FollowActionHelper.create_rule(
        field_name="status",
        operator="eql",
        value="paid",
        event_class=OrderPaidEvent,
        event_data={"order_id": str(order.order_id)},
        persist=False
    )
)
order.save()

# Later, when status changes:
order.status = "paid"
order.save()  # Automatically publishes OrderPaidEvent!
```

---

## Schema Registry Design

### How It Works

```
Service A (Publisher)
  ↓
  @event decorator runs at import time
  ↓
  Schema extracted from Pydantic model
  ↓
  Schema registered to PostgreSQL
  ↓
Service B (Subscriber)
  ↓
  @subscribe decorator runs at import time
  ↓
  Fetches schema from registry
  ↓
  Creates dynamic Pydantic model
  ↓
  Validates incoming data automatically
```

### Key Features

1. **No shared code packages** - Service B doesn't import Service A's event class
2. **Automatic validation** - Both sides validate against same schema
3. **Version management** - Supports multiple schema versions
4. **Early error detection** - Schema conflicts found at startup

### Database Schema

```sql
CREATE TABLE celerysalt_schemas (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL,
    schema JSONB NOT NULL,
    publisher_service VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    deprecated_at TIMESTAMP,
    UNIQUE(topic, version)
);

CREATE TABLE celerysalt_publishers (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    service_name VARCHAR(255) NOT NULL,
    last_published_at TIMESTAMP,
    publish_count BIGINT DEFAULT 0,
    UNIQUE(topic, service_name)
);

CREATE TABLE celerysalt_subscribers (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    service_name VARCHAR(255) NOT NULL,
    handler_name VARCHAR(255),
    registered_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(topic, service_name, handler_name)
);
```

---

## Deployment Models

### 1. Library Only (Minimal)

```bash
pip install celerysalt
```

**Configuration:**
```python
# Minimal - no database
CELERYSALT_RABBITMQ_URL = "amqp://localhost:5672"
# Works with just RabbitMQ for broadcast events!
```

### 2. Self-Hosted with Docker Compose

```yaml
services:
  rabbitmq:
    image: rabbitmq:3-management
  redis:
    image: redis:7-alpine
  postgres:
    image: postgres:15-alpine
  ui:
    image: celerysalt/ui:latest
    # Separate Docker image, not in PyPI package
```

### 3. Cloud Managed

```python
CELERYSALT_MODE = "cloud"
CELERYSALT_API_KEY = "cs_live_..."
# Cloud handles schema registry
# Local brokers still used for messages
```

---

## Business Model

### Open Core Strategy

**Free (MIT License):**
- Core library (PyPI)
- All event features
- Self-hosted deployment
- Basic UI (Docker image)

**Paid:**
- Cloud hosting ($29-499/mo)
- Pro UI features (self-hosted, $49/mo)
- Advanced analytics
- Event replay
- Team collaboration
- Enterprise support

---

## Technology Stack

**Library:**
- Python 3.10+
- Pydantic 2.x (validation)
- Celery 5.x (task execution)
- RabbitMQ (message broker)
- Redis (RPC results)
- PostgreSQL (schemas - optional)

**UI (separate):**
- Backend: FastAPI or Django
- Frontend: React/Next.js
- Database: PostgreSQL (required for UI)

---

## Migration from Current Implementation

### Current (tchu-tchu with DRF)

```python
# Current
from rest_framework import serializers

class RequestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()

class UserSignupEvent(TchuEvent):
    class Meta:
        topic = "user.signup.completed"
        request_serializer_class = RequestSerializer

event = UserSignupEvent()
event.serialize_request({"user_id": 123})
event.publish()
```

### New (CelerySalt with Pydantic)

```python
# New
@event("user.signup.completed")
class UserSignup:
    user_id: int

UserSignup.publish(user_id=123)
# Schema registered at import time automatically!
```

---

## ORM Adapter Pattern

Framework-agnostic design supports multiple ORMs:

```python
# Django
from celerysalt.adapters.django import DjangoTchuFollowActions

class Order(DjangoTchuFollowActions, models.Model):
    on_change_rules = models.JSONField(default=list)

# SQLAlchemy
from celerysalt.adapters.sqlalchemy import SQLAlchemyTchuFollowActions

class Order(SQLAlchemyTchuFollowActions, Base):
    on_change_rules = Column(JSON, default=list)

# Pydantic (no ORM)
from celerysalt.adapters.pydantic import PydanticTchuFollowActions

class Order(BaseModel, PydanticTchuFollowActions):
    on_change_rules: list[dict] = []
```

---

## Implementation Phases

### Phase 1: Core Library (2-3 months)
- Pydantic migration
- @event and @subscribe decorators
- Schema auto-registration
- RPC support
- ORM adapters
- PyPI package

### Phase 2: Self-Hosted UI (2-3 months)
- Schema registry viewer
- Event browser
- Real-time event stream
- Docker images
- Basic observability

### Phase 3: Cloud Offering (3-4 months)
- Multi-tenant infrastructure
- Cloud API
- Event storage/retention
- Advanced UI features
- Billing system

---

## Key Insights for Cursor

### Import-Time Registration Pattern

The most important architectural decision:

```python
# When you define an event:
@event("user.signup")  # ← Decorator executes at module import
class UserSignup:
    user_id: int

# When Python imports this file:
# 1. @event decorator runs
# 2. Extracts Pydantic schema
# 3. Registers to PostgreSQL (if configured)
# 4. Caches locally
# All before any code executes!
```

**Benefits:**
- ✅ Schemas available before first publish
- ✅ Conflicts detected at startup (not runtime)
- ✅ Complete catalog visible in UI
- ✅ CI/CD can validate schemas
- ✅ Zero runtime registration overhead

### Graceful Degradation

```python
# If PostgreSQL not configured:
# - Schema still works (local Pydantic validation)
# - No central registry
# - Service runs normally

# If PostgreSQL temporarily down:
# - Schema cached locally
# - Registered on first publish
# - Service continues working
```

### Why Both RabbitMQ and Redis?

This is a Celery limitation, not CelerySalt-specific:

- **RabbitMQ**: Built for message routing (pub/sub patterns)
- **Redis**: Built for data storage (result storage)
- RabbitMQ has no good result backend
- Redis required for RPC, optional for broadcast

### Distribution Strategy

**Why separate PyPI and Docker distributions?**

1. **PyPI package** = lightweight library
   - No frontend code
   - No Node.js dependencies
   - Fast `pip install`
   - Just Python

2. **Docker images** = complete UI
   - Backend + frontend bundled
   - All dependencies included
   - Easy updates
   - Optional component

---

## Competitive Positioning

| Competitor | CelerySalt Advantage |
|------------|---------------------|
| AWS EventBridge | Better DX for Python, simpler pricing |
| Pusher/Ably | Backend-focused, not WebSockets |
| Kafka/Confluent | Simpler, leverages existing Celery knowledge |
| Raw Celery | Schema validation, observability UI |

**Unique features:**
- TchuFollowActions pattern (state machines as data)
- Import-time registration (early error detection)
- Framework agnostic (Django/Flask/FastAPI/plain Python)

---

## Next Steps

1. Implement Phase 1 (core library with Pydantic)
2. Build community through open source
3. Validate cloud demand
4. Execute roadmap based on feedback

---

## References

- Full design document: `CELERYSALT_DESIGN.md` (included)
- Current implementation: `/mnt/project/` files
- Conversation transcript: Available in this export

---

**For Cursor:** This conversation established the complete architecture for CelerySalt. The key innovation is **import-time schema registration** combined with a **schema registry** that eliminates shared code packages. The library is distributed via PyPI (lightweight), while the UI is distributed as separate Docker images (optional).
