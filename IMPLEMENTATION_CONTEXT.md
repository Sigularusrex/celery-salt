# CelerySalt Implementation Context

**Date:** January 25, 2026  
**Purpose:** Context document for implementation decisions and architecture

---

## Key Architectural Decisions

### 1. Import-Time Schema Registration

**Critical Innovation:** Schemas register when Python modules are imported, NOT on first publish.

```python
# events/user_events.py
@event("user.signup.completed")  # ← Decorator runs when module imported
class UserSignup:
    user_id: int
    email: str

# celery.py
import myapp.events.user_events  # ← Schema registered here!

# Benefits:
# ✅ Complete event catalog before any events published
# ✅ Schema conflicts detected at startup
# ✅ CI/CD can validate before deployment
# ✅ Zero runtime overhead
```

**Implementation Note:** If PostgreSQL is unavailable at import time, schema is cached locally and registered on first publish (graceful degradation).

### 2. PostgreSQL is Optional

**Infrastructure requirements by use case:**

| Use Case | RabbitMQ | Redis | PostgreSQL |
|----------|----------|-------|------------|
| Broadcast only (no registry) | Required | Optional | **Not needed** |
| Broadcast with registry | Required | Optional | Required |
| RPC (no registry) | Required | Required | **Not needed** |
| RPC with registry | Required | Required | Required |
| With Management UI | Required | Recommended | Required |

**Key insight:** Library works with just RabbitMQ for broadcast events. PostgreSQL only needed for:
- Centralized schema registry
- Schema versioning
- Management UI
- Cross-service validation

**Current Implementation:** In-memory registry is default. PostgreSQL adapter should be pluggable.

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

### 5. All Celery Features Available

**Each `@subscribe` handler is a Celery task**, so all Celery options are supported:

```python
@subscribe(
    "user.signup.completed",
    # Celery retry options
    autoretry_for=(SMTPException, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
    retry_jitter=True,
    
    # Celery task options
    time_limit=300,
    soft_time_limit=240,
    rate_limit='100/m',
    priority=5,
    acks_late=True,
    reject_on_worker_lost=True,
    bind=True,  # Access task instance as 'self'
)
def send_welcome_email(data: UserSignup):
    # Full Celery task with all features
    send_email(data.email)
```

**This is a major selling point** - "Built on Celery, Enhanced for Events"

---

## API Design

### Broadcast Events (Fire-and-Forget)

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
```

### RPC Events (Request/Response)

```python
from celerysalt import event, subscribe, RPCError

# Request schema
@event("rpc.documents.list", mode="rpc")
class DocumentListRequest:
    user_id: int
    folder_id: int | None = None
    limit: int = 50

# Success response schema
@event.response("rpc.documents.list")
class DocumentListResponse:
    documents: list[dict]
    total: int
    has_more: bool

# Error response schema
@event.error("rpc.documents.list")
class DocumentListError:
    error_code: str
    error_message: str
    details: dict | None = None

# Caller
try:
    response = DocumentListRequest.call(
        user_id=123,
        folder_id=456,
        timeout=10
    )
    
    if isinstance(response, DocumentListError):
        print(f"Error: {response.error_message}")
    else:
        print(f"Found {response.total} documents")
        
except TimeoutError:
    print("No response received within timeout")

# Handler
@subscribe("rpc.documents.list")
def handle_list_documents(data: DocumentListRequest) -> DocumentListResponse:
    """Handler for document list RPC."""
    # Validate access
    if not has_access(data.user_id, data.folder_id):
        raise RPCError(
            error_code="NO_ACCESS",
            error_message="User does not have access to this folder",
            details={"user_id": data.user_id, "folder_id": data.folder_id}
        )
    
    # Get documents
    docs = get_documents(
        user_id=data.user_id,
        folder_id=data.folder_id,
        limit=data.limit
    )
    
    # Return validated response
    return DocumentListResponse(
        documents=[doc.to_dict() for doc in docs],
        total=len(docs),
        has_more=len(docs) == data.limit
    )
```

**Note:** `@event.response()` and `@event.error()` decorators need to be implemented.

### TchuFollowActions Pattern (State Machines)

```python
# Django example
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
        persist=False  # One-time rule
    )
)
order.save()

# Later, when status changes:
order.status = "paid"
order.save()  # Automatically publishes OrderPaidEvent!
```

**Note:** ORM adapter pattern needed - core logic should be framework-agnostic.

---

## Schema Registry Design

### Adapter Pattern

The schema registry should support multiple backends:

1. **In-Memory** (default, for development)
2. **PostgreSQL** (for production, multi-service)
3. **Cloud API** (for CelerySalt Cloud)

### Database Schema (PostgreSQL)

```sql
CREATE TABLE celerysalt_schemas (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL,
    schema JSONB NOT NULL,
    description TEXT,
    
    -- Metadata
    publisher_service VARCHAR(255),
    publisher_version VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(255),
    
    -- Governance
    is_active BOOLEAN DEFAULT TRUE,
    deprecated_at TIMESTAMP,
    deprecated_reason TEXT,
    
    UNIQUE(topic, version)
);

CREATE INDEX idx_schemas_topic ON celerysalt_schemas(topic);
CREATE INDEX idx_schemas_active ON celerysalt_schemas(is_active) WHERE is_active = TRUE;

-- schema_fields table (denormalized for querying)
CREATE TABLE celerysalt_schema_fields (
    id SERIAL PRIMARY KEY,
    schema_id INTEGER REFERENCES celerysalt_schemas(id) ON DELETE CASCADE,
    field_name VARCHAR(255) NOT NULL,
    field_type VARCHAR(100) NOT NULL,
    is_required BOOLEAN NOT NULL,
    description TEXT,
    format VARCHAR(100),
    
    UNIQUE(schema_id, field_name)
);

-- publishers table (who publishes what)
CREATE TABLE celerysalt_publishers (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    service_name VARCHAR(255) NOT NULL,
    service_version VARCHAR(50),
    last_published_at TIMESTAMP,
    publish_count BIGINT DEFAULT 0,
    
    UNIQUE(topic, service_name)
);

-- subscribers table (who subscribes to what)
CREATE TABLE celerysalt_subscribers (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    service_name VARCHAR(255) NOT NULL,
    handler_name VARCHAR(255),
    registered_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(topic, service_name, handler_name)
);
```

### How It Works

```
Service A (Publisher)
  ↓
  @event decorator runs at import time
  ↓
  Schema extracted from Pydantic model
  ↓
  Schema registered to registry (PostgreSQL or in-memory)
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

---

## Protocol Compatibility

**Critical:** Must maintain compatibility with `tchu-tchu` package:

- **Exchange name:** `tchu_events` (backward compatible)
- **Message format:** `_tchu_meta` field with `is_rpc` flag
- **Routing key patterns:** Same conventions
- **Dispatcher task name:** Can be `celerysalt.dispatch_event` or `tchu_tchu.dispatch_event` (configurable)

This allows:
- Apps using `tchu-tchu` can subscribe to events published by `celery-salt`
- Apps using `celery-salt` can subscribe to events published by `tchu-tchu`

---

## Missing Implementation Pieces

### Phase 1 (Current Priority)

1. **RPC Response/Error Schemas**
   - `@event.response(topic)` decorator
   - `@event.error(topic)` decorator
   - Response validation in RPC handlers
   - Error response handling

2. **PostgreSQL Schema Registry Adapter**
   - `PostgreSQLSchemaRegistry` class
   - Database connection handling
   - Migration scripts
   - Configuration (connection string, etc.)

3. **TchuFollowActions Pattern**
   - Core base class (framework-agnostic)
   - Django adapter
   - SQLAlchemy adapter
   - Pydantic adapter
   - Helper functions

4. **CLI Tools**
   - `celerysalt validate` - Validate schemas
   - `celerysalt generate` - Generate event classes
   - `celerysalt migrate` - Migration from DRF

### Phase 2 (UI)

5. **Management UI** (separate repository)
   - Schema browser
   - Event viewer
   - Analytics dashboard
   - Docker images

### Phase 3 (Cloud)

6. **Cloud API Client**
   - API key authentication
   - Schema registry API
   - Event publishing API
   - Usage tracking

---

## Configuration

### Environment Variables

```python
# Minimal (no database)
CELERYSALT_RABBITMQ_URL = "amqp://localhost:5672"

# With schema registry
CELERYSALT_RABBITMQ_URL = "amqp://localhost:5672"
CELERYSALT_REDIS_URL = "redis://localhost:6379"  # For RPC
CELERYSALT_POSTGRES_URL = "postgresql://localhost/celerysalt"  # For schemas

# Cloud mode
CELERYSALT_MODE = "cloud"
CELERYSALT_API_KEY = "cs_live_..."
CELERYSALT_API_URL = "https://api.celerysalt.cloud"
```

### Programmatic Configuration

```python
from celerysalt.core.registry import set_schema_registry
from celerysalt.adapters.postgres import PostgreSQLSchemaRegistry

# Set PostgreSQL registry
registry = PostgreSQLSchemaRegistry(
    database_url="postgresql://localhost/celerysalt"
)
set_schema_registry(registry)
```

---

## Framework Support

### Django (Optional)

```python
# Installation
pip install celerysalt[django]

# Usage
from celerysalt.adapters.django import DjangoTchuFollowActions
from celerysalt.django import setup_celery_queue
```

### SQLAlchemy (Optional)

```python
# Installation
pip install celerysalt[sqlalchemy]

# Usage
from celerysalt.adapters.sqlalchemy import SQLAlchemyTchuFollowActions
```

### Plain Python / FastAPI / Flask

```python
# Installation
pip install celerysalt

# Usage - no framework-specific code needed
from celerysalt import event, subscribe
```

---

## Key Questions for Implementation

1. **PostgreSQL Adapter Priority**
   - Should we implement PostgreSQL adapter now (Phase 1) or wait for UI?
   - Answer: **Now** - needed for multi-service deployments

2. **RPC Response/Error Decorators**
   - Should `@event.response()` and `@event.error()` be implemented now?
   - Answer: **Yes** - Phase 1 feature

3. **TchuFollowActions**
   - Should ORM adapters be implemented now?
   - Answer: **Yes** - Phase 1 feature, but can start with Django only

4. **Configuration Strategy**
   - Environment variables vs config file vs programmatic?
   - Answer: **All three** - env vars for defaults, programmatic for flexibility

5. **CLI Tools**
   - Should CLI be Phase 1 or Phase 2?
   - Answer: **Phase 1** - helps with adoption and developer experience

---

## Current Implementation Status

### ✅ Completed
- Package renamed: `tchu_tchu` → `celerysalt`
- Core `@event` decorator with import-time registration
- Core `@subscribe` decorator with Celery integration
- In-memory schema registry
- Handler registry for routing
- Event dispatcher (protocol compatible)
- Producer integration
- Protocol compatibility maintained
- Django integration updated
- Old DRF code removed

### ⏳ Pending (Phase 1)
- RPC response/error schema decorators
- PostgreSQL schema registry adapter
- TchuFollowActions pattern (ORM adapters)
- CLI tools
- Response validation for RPC

### 🔮 Future (Phase 2+)
- Management UI (separate repository)
- Cloud API client
- Advanced features

---

## Notes

- **Django is optional** - Core library is framework-agnostic
- **PostgreSQL is optional** - Works with just RabbitMQ for broadcast
- **Redis is required for RPC** - Celery limitation
- **UI is separate** - Docker images, not in PyPI package
- **Protocol compatible** - Works with `tchu-tchu` package
