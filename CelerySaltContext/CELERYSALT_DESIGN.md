# CelerySalt - Design Document

**Version:** 1.0  
**Date:** January 25, 2026  
**Status:** Design Phase

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Vision & Positioning](#vision--positioning)
3. [Core Architecture](#core-architecture)
4. [API Design](#api-design)
5. [Schema Registry](#schema-registry)
6. [Deployment Models](#deployment-models)
7. [Business Model](#business-model)
8. [Technical Implementation](#technical-implementation)
9. [Migration Strategy](#migration-strategy)
10. [Roadmap](#roadmap)

---

## Executive Summary

### What is CelerySalt?

CelerySalt is an event-driven architecture library for Python that extends Celery with event publishing/subscribing patterns. It provides schema validation, automatic retries, and observability while maintaining the familiar Celery developer experience.

### Key Value Proposition

*"If you're using Celery for async tasks, use CelerySalt for event-driven workflows"*

### Core Innovation

**No shared code packages required** - A schema registry eliminates the need for services to import shared event definitions, while still providing type safety and validation.

### Target Users

- Celery power users across any Python framework (Django, Flask, FastAPI)
- Teams already running RabbitMQ/Redis for Celery
- Organizations building microservices with event-driven architecture

---

## Vision & Positioning

### Market Position

| Competitor | CelerySalt Advantage |
|------------|---------------------|
| **AWS EventBridge** | Better DX for Python, simpler pricing, Python-first |
| **Pusher/Ably** | Backend-focused (service-to-service), not frontend WebSockets |
| **Kafka/Confluent** | Simpler than Kafka, leverages existing Celery/RabbitMQ knowledge |
| **Raw Celery** | Schema validation, event patterns, observability UI |

### Unique Features

1. **TchuFollowActions Pattern** - State machine rules stored as data
2. **Celery Integration** - Every subscriber gets automatic retries, timeouts, rate limiting
3. **Schema Registry** - Centralized schema management without code sharing
4. **Framework Agnostic** - Works with Django, Flask, FastAPI, plain Python

---

## Core Architecture

### High-Level Components

```
┌─────────────────────────────────────────────────────────────┐
│  CelerySalt Library (PyPI)                                  │
│  ┌────────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │   Decorators   │  │   Schema     │  │   Celery       │  │
│  │   @event       │  │   Registry   │  │   Integration  │  │
│  │   @subscribe   │  │   Client     │  │   (retries)    │  │
│  └────────────────┘  └──────────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Message Broker Infrastructure                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  RabbitMQ    │  │    Redis     │  │  PostgreSQL  │     │
│  │  (messages)  │  │   (cache)    │  │  (schemas)   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Management UI (Optional)                                   │
│  - Schema browser                                           │
│  - Event viewer                                             │
│  - Analytics dashboard                                      │
│  - Event replay                                             │
└─────────────────────────────────────────────────────────────┘
```

### Key Architectural Insight: Import-Time Registration

**The @event and @subscribe decorators run at module import time, not runtime:**

```python
# events/user_events.py
@event("user.signup.completed")  # ← Decorator runs when module imported
class UserSignup:
    user_id: int

# celery.py
import myapp.events.user_events  # ← This line triggers schema registration!

# Schema is now in registry before ANY code runs
# Before ANY events are published
# Before ANY requests are handled
```

**This means:**
- ✅ Schemas registered at **startup**, not on first publish
- ✅ Schema conflicts detected **before deployment**
- ✅ Complete event catalog **always visible**
- ✅ CI/CD can **validate schemas** before merge
- ✅ Zero runtime overhead for registration

### Technology Stack

**Core Library:**
- Python 3.10+
- Pydantic 2.x (validation, serialization)
- Celery 5.x (task execution, retries)
- RabbitMQ (message broker)
- Redis (required for RPC result backend, optional for caching)

**Infrastructure Requirements by Use Case:**

| Use Case | RabbitMQ | Redis | PostgreSQL | Notes |
|----------|----------|-------|------------|-------|
| Broadcast events (no registry) | ✅ Required | ❌ Optional | ❌ Not needed | Pydantic validates locally |
| Broadcast events (with registry) | ✅ Required | ❌ Optional | ✅ Required | Central schema storage |
| RPC (no registry) | ✅ Required | ✅ Required | ❌ Not needed | Pydantic validates locally |
| RPC (with registry) | ✅ Required | ✅ Required | ✅ Required | Central schema storage |
| With Management UI | ✅ Required | ✅ Recommended | ✅ Required | UI needs DB for schemas + metadata |
| Cloud mode (library only) | ✅ Required | Depends on RPC | ❌ Not needed | Cloud handles schemas |

**About the Schema Registry (PostgreSQL):**
- **Optional for library-only usage** - schemas can validate locally via Pydantic
- **Required if you want:**
  - Centralized schema management
  - Schema versioning and history
  - Cross-service schema validation
  - Management UI
- **Not needed if:**
  - Just using the library for publish/subscribe
  - Using CelerySalt Cloud (schemas stored in cloud)
  - Don't need schema governance features

**Why Both RabbitMQ and Redis?**
- **RabbitMQ**: Message routing and delivery
  - Topic exchanges for broadcast patterns
  - Point-to-point routing for RPC
- **Redis**: Result storage for RPC pattern
  - RabbitMQ doesn't have built-in result storage
  - This is a Celery limitation, not CelerySalt-specific
  - Celery needs somewhere to store RPC return values
  - Also useful for caching schemas locally

**Schema Registry:**
- PostgreSQL (schema storage)
- SQLAlchemy or Django ORM (adapter pattern)

**Management UI:**
- Backend: FastAPI or Django
- Frontend: React/Next.js
- Real-time: WebSockets for live event stream

---

## API Design

### 1. Broadcast Events (Fire-and-Forget)

**Basic Pattern:**
```python
from celerysalt import event, subscribe

# Define event - schema registered at import time!
@event("user.signup.completed")
class UserSignup:
    """Emitted when a user completes signup."""
    user_id: int
    email: str
    company_id: int
    signup_source: str = "web"

# When Python imports this module:
# 1. @event decorator runs
# 2. Schema extracted from class
# 3. Schema registered to registry (PostgreSQL or cloud)
# All happens at startup, before any events published!

# Publish event (schema already registered)
UserSignup.publish(
    user_id=123,
    email="user@example.com",
    company_id=456,
    signup_source="web"
)

# Subscribe to event (in different service)
@subscribe("user.signup.completed")
def send_welcome_email(data: UserSignup):
    """
    Handler automatically receives validated data.
    
    At startup, this handler:
    1. Fetches schema from registry
    2. Creates Pydantic validation model
    3. Registers itself for this topic
    """
    send_email(
        to=data.email,
        template="welcome",
        context={"user_id": data.user_id}
    )
```

**With Celery Options:**
```python
@subscribe(
    "user.signup.completed",
    # Celery retry options
    autoretry_for=(SMTPException, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
    
    # Celery task options
    time_limit=60,
    soft_time_limit=50,
    rate_limit='100/m',
    priority=5,
    acks_late=True,
)
def send_welcome_email(data: UserSignup):
    """
    This handler is a Celery task with:
    - Auto-retry on SMTP/connection errors
    - Exponential backoff
    - 60 second timeout
    - Rate limited to 100/min
    """
    send_email(data.email, template="welcome")
```

### 2. RPC Events (Request/Response)

**Important: RPC requires Redis as Celery's result backend** because RabbitMQ doesn't provide a good result storage mechanism. This is a Celery limitation, not CelerySalt-specific.

**Configuration:**
```python
# celery.py - Required for RPC to work
app = Celery('myapp')

# RabbitMQ for message transport
app.conf.broker_url = 'amqp://localhost:5672'

# Redis for RPC results (required!)
app.conf.result_backend = 'redis://localhost:6379/0'

# Optional: Result expiration
app.conf.result_expires = 3600  # Results expire after 1 hour
```

**Pattern:**
```python
from celerysalt import event, subscribe, RPCError

# Define request schema
@event("rpc.documents.list", mode="rpc")
class DocumentListRequest:
    """Request to list documents."""
    user_id: int
    folder_id: int | None = None
    limit: int = 50

# Define success response schema
@event.response("rpc.documents.list")
class DocumentListResponse:
    """Successful response."""
    documents: list[dict]
    total: int
    has_more: bool

# Define error response schema
@event.error("rpc.documents.list")
class DocumentListError:
    """Error response."""
    error_code: str
    error_message: str
    details: dict | None = None

# === Caller Side ===
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

# === Handler Side ===
@subscribe("rpc.documents.list")
def handle_list_documents(data: DocumentListRequest) -> DocumentListResponse:
    """
    Handler for document list RPC.
    
    Can return DocumentListResponse or raise RPCError.
    """
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

### 3. TchuFollowActions Pattern (State Machines)

**Django Example:**
```python
from celerysalt.adapters.django import DjangoTchuFollowActions
from django.db import models

class Order(DjangoTchuFollowActions, models.Model):
    """
    Order model with automatic event triggering.
    
    When status changes to specific values, events are automatically
    published based on rules stored in on_change_rules.
    """
    order_id = models.UUIDField(primary_key=True)
    status = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Rules stored as JSONB
    on_change_rules = models.JSONField(default=list)

# Adding a rule (typically in view/service layer)
from celerysalt.patterns.follow_actions import FollowActionHelper

order = Order.objects.get(order_id=order_id)

# Add rule: when status changes to "paid", publish event
rule = FollowActionHelper.create_rule(
    field_name="status",
    operator="eql",
    value="paid",
    event_class=OrderPaidEvent,
    event_data={
        "order_id": str(order.order_id),
        "amount": str(order.amount)
    },
    persist=False  # Remove rule after execution
)

order.on_change_rules.append(rule)
order.save()

# Later, when order.status changes to "paid":
order.status = "paid"
order.save()  # Automatically publishes OrderPaidEvent!
```

**SQLAlchemy Example:**
```python
from celerysalt.adapters.sqlalchemy import SQLAlchemyTchuFollowActions
from sqlalchemy import Column, String, Numeric, JSON
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Order(SQLAlchemyTchuFollowActions, Base):
    __tablename__ = 'orders'
    
    order_id = Column(String, primary_key=True)
    status = Column(String(50))
    amount = Column(Numeric(10, 2))
    on_change_rules = Column(JSON, default=list)

# Usage is identical to Django version
```

**Pydantic (No ORM) Example:**
```python
from celerysalt.adapters.pydantic import PydanticTchuFollowActions
from pydantic import BaseModel

class Order(BaseModel, PydanticTchuFollowActions):
    order_id: str
    status: str
    amount: float
    on_change_rules: list[dict] = []
    
    def persist(self):
        """Override to save to your storage (Redis, S3, API, etc.)"""
        redis.set(f"order:{self.order_id}", self.model_dump_json())

# Usage
order = Order(order_id="123", status="pending", amount=99.99)
order.add_follow_action(...)
order.status = "paid"
order.save()  # Calls persist() after triggering actions
```

---

## Schema Registry

### Purpose

The schema registry is the **single source of truth** for all event schemas. It eliminates the need for services to share code packages while maintaining validation and type safety.

### Registration Strategy: Import-Time vs First-Publish

**CelerySalt uses import-time registration** (when modules are imported at startup), not first-publish registration. This provides significant benefits:

#### Why Import-Time Registration?

**❌ Problems with First-Publish Registration:**
```python
# Service A publishes before Service B starts
UserSignupEvent.publish(...)  # Schema registered

# Service B starts later
@subscribe("user.signup.completed")  # Uses existing schema

# But what if Service A never publishes?
# Service B has no schema to validate against!
```

**✅ Benefits of Import-Time Registration:**

1. **Early Error Detection**
```bash
$ celery -A myapp worker

[ERROR] Schema conflict for user.signup.completed (v1)
  Existing schema differs from new definition!

# Fails at startup, not at runtime!
```

2. **Complete Event Catalog**
```python
# UI shows all events, even ones never published
GET /api/schemas
[
  {
    "topic": "order.created",
    "status": "registered",
    "publishers": ["order-service"],
    "subscribers": ["email-service"],
    "last_published": null  # Never published yet, but schema exists!
  }
]
```

3. **CI/CD Validation**
```bash
# Validate schemas in CI pipeline
$ celerysalt validate

✓ All schemas registered
✓ No schema conflicts
✓ All subscribers have matching schemas

# Deploy with confidence!
```

4. **Zero Configuration**
```python
# Just import event modules - schemas register automatically!
import myapp.events.user_events  # ← All @event decorators run

# No explicit registration calls needed
```

5. **Graceful Degradation**
```python
# If registry is unavailable at startup:
# - Schema cached locally
# - Registered on first publish
# - Service still works
```

### How It Works

```
┌──────────────────────────────────────────────────────────┐
│  Service A (Publisher)                                   │
│                                                           │
│  # events/user_events.py                                │
│  @event("user.signup.completed")                        │
│  class UserSignup:                                       │
│      user_id: int                                        │
│      email: str                                          │
│                                                           │
│  # Schema registered IMMEDIATELY when module imported!   │
│  # (at startup, not on first publish)                   │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Schema Registry (PostgreSQL)                            │
│                                                           │
│  Topic: user.signup.completed                           │
│  Version: v1                                             │
│  Schema: {                                               │
│    "properties": {                                       │
│      "user_id": {"type": "integer"},                    │
│      "email": {"type": "string", "format": "email"}     │
│    },                                                    │
│    "required": ["user_id", "email"]                     │
│  }                                                       │
│  Registered at: 2026-01-25 10:30:00 (startup)           │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Service B (Consumer - Different Codebase!)             │
│                                                           │
│  # subscribers/user_subscribers.py                       │
│  @subscribe("user.signup.completed")                    │
│  def handle_signup(data):                               │
│      # Fetches schema from registry at startup          │
│      # data is auto-validated against registry schema   │
│      print(data.user_id)  # Type-safe access            │
│      print(data.email)                                   │
│                                                           │
│  NO IMPORT OF UserSignup CLASS NEEDED!                   │
└──────────────────────────────────────────────────────────┘
```

### Database Schema

```sql
-- schemas table
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

-- events table (metadata about published events)
CREATE TABLE celerysalt_events (
    id BIGSERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    message_id UUID NOT NULL,
    published_at TIMESTAMP NOT NULL,
    publisher_service VARCHAR(255),
    
    -- Payload stored separately (S3, etc.)
    payload_location VARCHAR(500),
    payload_size_bytes INTEGER,
    
    -- For search/filtering
    schema_version VARCHAR(50),
    
    UNIQUE(message_id)
);

CREATE INDEX idx_events_topic ON celerysalt_events(topic);
CREATE INDEX idx_events_published_at ON celerysalt_events(published_at);
```

### Schema Auto-Registration

**Registration happens at import time, not on first publish:**

```python
# events/user_events.py
from celerysalt import event

@event("user.signup.completed")
class UserSignup:
    """Schema registered IMMEDIATELY when this module is imported."""
    user_id: int
    email: str


# When Python imports this module (at startup):
# 1. @event decorator runs
# 2. Extracts Pydantic schema
# 3. Registers to schema registry
# 4. All happens before any events are published!
```

**Implementation:**
```python
def event(topic: str, version: str = "v1", mode: str = "broadcast"):
    """
    Decorator that registers schema at import time.
    
    This is called as soon as the Python module is imported,
    not when events are published.
    """
    def decorator(cls):
        # 1. Convert class to Pydantic model
        pydantic_model = _create_pydantic_model_from_class(cls)
        
        # 2. Register schema IMMEDIATELY (import time!)
        _register_schema_at_import(
            topic=topic,
            version=version,
            model=pydantic_model,
            publisher_class=cls
        )
        
        # 3. Store metadata and add publish method
        cls._celerysalt_topic = topic
        cls._celerysalt_model = pydantic_model
        cls.publish = classmethod(_create_publish_method(topic, pydantic_model))
        
        return cls
    return decorator


def _register_schema_at_import(topic, version, model, publisher_class):
    """
    Register schema immediately at import time.
    
    Benefits:
    - Schemas available before first publish
    - Early detection of schema conflicts
    - Complete event catalog visible
    - Can validate in CI/CD before deployment
    
    Note: If PostgreSQL is not configured, schemas are validated
    locally via Pydantic only (no central registry).
    """
    logger = get_logger(__name__)
    
    # Extract JSON schema
    json_schema = model.model_json_schema()
    
    # Get registry (could be local DB, cloud API, or None)
    try:
        registry = get_schema_registry()
    except SchemaRegistryNotConfiguredError:
        # No registry configured - that's fine!
        # Schemas still work via local Pydantic validation
        logger.debug(
            f"No schema registry configured. "
            f"Schema for {topic} will validate locally only."
        )
        return
    
    try:
        # Attempt to register
        result = registry.register_schema(
            topic=topic,
            version=version,
            schema=json_schema,
            publisher_module=publisher_class.__module__,
            publisher_class=publisher_class.__name__,
            registered_at_import=True
        )
        
        if result.get('created'):
            logger.info(f"✓ Registered schema: {topic} (v{version})")
        else:
            # Schema already exists - validate it matches
            existing_schema = result.get('existing_schema')
            if existing_schema != json_schema:
                logger.error(
                    f"✗ Schema conflict for {topic} (v{version})\n"
                    f"  Existing schema differs from new definition!"
                )
                raise SchemaConflictError(topic, version)
            else:
                logger.debug(f"Schema already registered: {topic} (v{version})")
    
    except SchemaRegistryUnavailableError as e:
        # Registry unavailable (network issue, DB down, etc.)
        # Cache schema locally for later registration
        logger.warning(
            f"⚠ Could not register schema {topic} at import time: {e}\n"
            f"  Schema cached for registration on first publish."
        )
        _cache_schema_for_later(topic, version, json_schema, publisher_class)


def _cache_schema_for_later(topic, version, schema, publisher_class):
    """
    Cache schema locally if registry is unavailable at import time.
    
    Will be registered on first publish or when registry becomes available.
    This provides graceful degradation.
    """
    if not hasattr(_cache_schema_for_later, 'pending_schemas'):
        _cache_schema_for_later.pending_schemas = []
    
    _cache_schema_for_later.pending_schemas.append({
        'topic': topic,
        'version': version,
        'schema': schema,
        'publisher_module': publisher_class.__module__,
        'publisher_class': publisher_class.__name__,
    })
```

**Startup logs show registration:**
```bash
$ celery -A myapp worker --loglevel=info

[2026-01-25 10:30:00] INFO: Importing myapp.events.user_events
[2026-01-25 10:30:00] INFO: ✓ Registered schema: user.signup.completed (v1)
[2026-01-25 10:30:00] INFO: ✓ Registered schema: user.profile.updated (v1)

[2026-01-25 10:30:00] INFO: Importing myapp.events.order_events
[2026-01-25 10:30:00] INFO: ✓ Registered schema: order.created (v1)
[2026-01-25 10:30:00] INFO: ✓ Registered schema: order.paid (v1)

[2026-01-25 10:30:01] INFO: CelerySalt: 4 schemas registered at startup
[2026-01-25 10:30:01] INFO: celery@worker1 ready.
```

### Schema Validation on Subscribe

```python
def subscribe(topic: str, version: str = "latest", **celery_options):
    """
    Decorator that validates incoming data against schema registry.
    """
    def decorator(func):
        # 1. Fetch schema from registry (at registration time)
        schema = _fetch_schema_from_registry(topic, version)
        
        # 2. Create Pydantic model dynamically from schema
        ValidationModel = _create_pydantic_model(schema)
        
        # 3. Wrap handler with validation
        def validated_handler(raw_data: dict):
            # Validate against schema
            validated = ValidationModel(**raw_data)
            
            # Call original handler with validated data
            return func(validated)
        
        # 4. Register as Celery task
        task = celery_app.task(
            name=f"celerysalt.{topic}.{func.__name__}",
            **celery_options
        )(validated_handler)
        
        # 5. Bind to RabbitMQ routing key
        _bind_queue_to_topic(topic, task)
        
        return task
    
    return decorator
```

### Schema Versioning Strategy

**Semantic Versioning for Schemas:**
- **Major version** (v1 → v2): Breaking changes (removed fields, changed types)
- **Minor version** (v1.1 → v1.2): Additive changes (new optional fields)
- **Patch version** (v1.1.0 → v1.1.1): Documentation, descriptions only

**Version Management:**
```python
# Publisher specifies version
@event("user.signup.completed", version="v2")
class UserSignup:
    user_id: int
    email: str
    utm_params: dict  # New in v2

# Subscriber can handle multiple versions
@subscribe("user.signup.completed", version="v1")
def handle_v1(data):
    # Only has user_id, email
    pass

@subscribe("user.signup.completed", version="v2")
def handle_v2(data):
    # Has user_id, email, utm_params
    pass

@subscribe("user.signup.completed")  # Latest version
def handle_latest(data):
    # Receives current version
    pass
```

---

## Deployment Models

### 1. Library-Only (Self-Hosted Infrastructure)

**Use Case:** Teams that already have RabbitMQ/Redis, want minimal setup

**Installation:**
```bash
pip install celerysalt
```

**Configuration (No Schema Registry):**
```python
# settings.py - Minimal setup
CELERYSALT_RABBITMQ_URL = "amqp://localhost:5672"
CELERYSALT_REDIS_URL = "redis://localhost:6379"  # Only if using RPC

# No PostgreSQL needed!
# Schemas validate locally via Pydantic
# No centralized registry
```

**Configuration (With Self-Hosted Schema Registry):**
```python
# settings.py - With centralized schemas
CELERYSALT_RABBITMQ_URL = "amqp://localhost:5672"
CELERYSALT_REDIS_URL = "redis://localhost:6379"  # Only if using RPC
CELERYSALT_POSTGRES_URL = "postgresql://localhost/celerysalt"  # Optional

# PostgreSQL stores:
# - Event schemas
# - Schema versions
# - Publisher/subscriber metadata
```

**Configuration (With Cloud Schema Registry):**
```python
# settings.py - Cloud registry, local brokers
CELERYSALT_MODE = "cloud"
CELERYSALT_API_KEY = "cs_live_..."
CELERYSALT_RABBITMQ_URL = "amqp://localhost:5672"
CELERYSALT_REDIS_URL = "redis://localhost:6379"  # Only if using RPC

# No local PostgreSQL needed!
# Schemas stored in CelerySalt Cloud
```

**What You Get:**
- ✅ Event publishing/subscribing
- ✅ Pydantic validation
- ✅ Celery retries, timeouts, etc.
- ✅ RPC support (if Redis configured)
- ❌ No Management UI (unless cloud)
- ❌ No centralized schema registry (unless configured)
- ❌ No schema versioning/history (unless configured)

**Infrastructure:**
```
Minimal Setup:
├── RabbitMQ (required)
└── Redis (only if using RPC)

With Self-Hosted Registry:
├── RabbitMQ (required)
├── Redis (only if using RPC)
└── PostgreSQL (for schemas)

With Cloud Registry:
├── RabbitMQ (required, local)
├── Redis (only if using RPC, local)
└── CelerySalt Cloud (schemas, remote)
```

---

### 2. Self-Hosted with Docker Compose

**Use Case:** Teams that want the full stack (broker + UI) but self-hosted

**Important:** The Management UI is distributed as a Docker image, **not** as part of the PyPI package.

**Structure:**
```yaml
# docker-compose.yml
version: '3.8'

services:
  rabbitmq:
    image: rabbitmq:3-management
    ports:
      - "5672:5672"   # AMQP
      - "15672:15672"  # Management UI
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq
    environment:
      RABBITMQ_DEFAULT_USER: celerysalt
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASSWORD}

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    # Redis is REQUIRED if using RPC events
    # Optional for broadcast-only deployments

  postgres:
    image: postgres:15-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: celerysalt
      POSTGRES_USER: celerysalt
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data

  ui:
    # UI is a separate Docker image, NOT in the PyPI package
    image: celerysalt/ui:latest  # Free version from Docker Hub
    # OR
    # image: celerysalt/ui-pro:latest  # Paid version (requires license)
    ports:
      - "8000:8000"
    environment:
      RABBITMQ_URL: amqp://celerysalt:${RABBITMQ_PASSWORD}@rabbitmq:5672
      REDIS_URL: redis://redis:6379/0
      DATABASE_URL: postgresql://celerysalt:${POSTGRES_PASSWORD}@postgres:5432/celerysalt
      
      # For pro version
      CELERYSALT_LICENSE_KEY: ${LICENSE_KEY}  # Optional
    depends_on:
      - rabbitmq
      - redis
      - postgres

volumes:
  rabbitmq_data:
  redis_data:
  postgres_data:
```

**Getting the UI:**
```bash
# Pull from Docker Hub
docker pull celerysalt/ui:latest

# OR download docker-compose.yml from repo
curl -O https://raw.githubusercontent.com/celerysalt/celerysalt/main/docker-compose.yml

# Start everything
docker-compose up -d

# Access UI
open http://localhost:8000
```

**Important Notes:**
- The UI is **not** part of `pip install celerysalt`
- The UI is distributed as Docker images only
- UI source code is in a separate GitHub repository (`celerysalt-ui`)
- Library works perfectly without the UI

**Startup:**
```bash
# Clone repo or download docker-compose.yml
curl -O https://celerysalt.io/docker-compose.yml

# Set environment variables
export RABBITMQ_PASSWORD=secure_password
export POSTGRES_PASSWORD=secure_password

# Start stack
docker-compose up -d

# Access UI
open http://localhost:8000
```

**Why Docker Compose (not single container):**
- ✅ Industry standard
- ✅ Components scale independently
- ✅ Easy to swap components (use AWS ElastiCache instead of Redis)
- ✅ Easier upgrades (update UI without restarting broker)
- ✅ Better resource allocation

---

### 3. CelerySalt Cloud (Managed SaaS)

**Use Case:** Teams that want zero infrastructure management

**Setup:**
```bash
# 1. Sign up at celerysalt.cloud
# 2. Get API key

# 3. Install library
pip install celerysalt

# 4. Configure for cloud
export CELERYSALT_MODE="cloud"
export CELERYSALT_API_KEY="cs_live_abc123..."

# 5. Use exactly the same API
@event("user.signup.completed")
class UserSignup:
    user_id: int

UserSignup.publish(user_id=123)  # Routes to cloud!
```

**Infrastructure (Managed by CelerySalt):**
```
CelerySalt Cloud:
├── Multi-Tenant RabbitMQ Cluster
│   ├── VHost: customer_a
│   ├── VHost: customer_b
│   └── ... (isolation via virtual hosts)
│
├── Multi-Tenant Redis Cluster
│   └── Namespaced per customer
│
├── PostgreSQL (Shared)
│   ├── Schemas table (all customers)
│   ├── Events metadata (all customers)
│   └── Customer isolation via customer_id column
│
├── Object Storage (S3)
│   └── Event payloads for retention
│
└── Multi-Tenant UI
    ├── Customer authentication
    ├── Schema browser
    ├── Event viewer
    └── Analytics
```

**Multi-Tenancy via RabbitMQ VHosts:**
```python
# Customer A connects to:
RABBITMQ_URL = "amqps://customer_a:token@rabbitmq.celerysalt.cloud/customer_a"

# Customer B connects to:
RABBITMQ_URL = "amqps://customer_b:token@rabbitmq.celerysalt.cloud/customer_b"

# Perfect isolation - can't see each other's messages
```

---

## Business Model

### Open Core Strategy

```
┌─────────────────────────────────────────────────────┐
│  FREE (Open Source - MIT License)                   │
├─────────────────────────────────────────────────────┤
│  ✅ PyPI library (celerysalt)                       │
│  ✅ Event publishing/subscribing                    │
│  ✅ Pydantic validation                             │
│  ✅ Celery integration (retries, timeouts, etc.)   │
│  ✅ TchuFollowActions pattern                       │
│  ✅ CLI tools                                        │
│  ✅ Self-hosted deployment (Docker Compose)         │
│  ✅ Basic UI (celerysalt/ui:latest)                 │
│      - Topic browser                                 │
│      - Event viewer (last 100 events)               │
│      - Basic schema registry                         │
│      - 7 day retention                               │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  MANAGED CLOUD                                       │
├─────────────────────────────────────────────────────┤
│  Starter ($29/mo)                                    │
│  - Hosted RabbitMQ + Redis + PostgreSQL             │
│  - 10M events/month                                  │
│  - Event viewer (7 day retention)                   │
│  - Basic schema registry                             │
│  - Email support                                     │
│                                                       │
│  Pro ($99/mo)                                        │
│  - 100M events/month                                 │
│  - Event search & replay                             │
│  - 30 day retention                                  │
│  - Advanced analytics                                │
│  - Team collaboration (5 users)                      │
│  - Slack/Discord support                             │
│                                                       │
│  Enterprise (Custom)                                 │
│  - Unlimited events                                  │
│  - Custom retention (90+ days)                       │
│  - Dedicated infrastructure                          │
│  - SLA guarantees (99.99%)                           │
│  - SSO/SAML                                          │
│  - Dedicated support                                 │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  PRO UI (Self-Hosted License)                       │
├─────────────────────────────────────────────────────┤
│  Pro Self-Hosted ($49/mo per license)               │
│  - All Pro cloud features                            │
│  - But runs on your infrastructure                   │
│  - License key unlocks:                              │
│      • Event search                                  │
│      • Event replay                                  │
│      • Advanced analytics                            │
│      • Team collaboration                            │
│      • 30+ day retention                             │
│      • Audit logs                                    │
└─────────────────────────────────────────────────────┘
```

### License Enforcement (Self-Hosted Pro UI)

**How it works:**
```python
# In docker-compose.yml
services:
  ui:
    image: celerysalt/ui-pro:latest
    environment:
      CELERYSALT_LICENSE_KEY: cs_lic_abc123...  # Customer's license key
```

**License validation:**
```python
# UI calls license server on startup
def validate_license(key: str) -> dict:
    response = requests.post(
        "https://license.celerysalt.cloud/validate",
        json={
            "key": key,
            "version": "1.0.0",
            "deployment_id": get_deployment_fingerprint()
        }
    )
    
    # Returns feature flags
    return response.json()
    # {
    #   "valid": true,
    #   "tier": "pro",
    #   "features": ["search", "replay", "analytics", "team"],
    #   "expires": "2026-12-31",
    #   "max_users": 5
    # }

# UI enables/disables features based on response
if "search" in features:
    enable_event_search()
if "replay" in features:
    enable_event_replay()
```

**No DRM** - Just feature flags. Trust-based with validation.

### Pricing Comparison

| Feature | Self-Hosted Free | Self-Hosted Pro | Cloud Starter | Cloud Pro | Enterprise |
|---------|-----------------|-----------------|---------------|-----------|------------|
| **Infrastructure** | You manage | You manage | We manage | We manage | Dedicated |
| **Events/month** | Unlimited | Unlimited | 10M | 100M | Unlimited |
| **Retention** | 7 days | 30+ days | 7 days | 30 days | Custom |
| **Event Search** | ❌ | ✅ | ❌ | ✅ | ✅ |
| **Event Replay** | ❌ | ✅ | ❌ | ✅ | ✅ |
| **Analytics** | Basic | Advanced | Basic | Advanced | Advanced |
| **Team Users** | 1 | 5 | 1 | 5 | Unlimited |
| **Support** | Community | Email | Email | Slack/Discord | Dedicated |
| **Price** | Free | $49/mo | $29/mo | $99/mo | Custom |

---

## Technical Implementation

### Distribution Strategy

CelerySalt is distributed in **two separate packages**:

#### 1. Core Library (PyPI)

**Package:** `celerysalt`  
**Installation:** `pip install celerysalt`  
**Repository:** `github.com/celerysalt/celerysalt`  
**License:** MIT (Open Source)

**Contains:**
- Core event library (@event, @subscribe)
- Pydantic validation
- Celery integration
- Schema registry client
- CLI tools
- ORM adapters (Django, SQLAlchemy, Pydantic)

**Does NOT contain:**
- Management UI (separate distribution)
- Frontend code
- UI dependencies

**Why separate?**
- ✅ Lightweight install for library users
- ✅ No frontend bloat in Python package
- ✅ Independent release cycles
- ✅ Clear separation of concerns

#### 2. Management UI (Docker Images)

**Images:** 
- `celerysalt/ui:latest` (free version)
- `celerysalt/ui-pro:latest` (paid version with license)

**Repository:** `github.com/celerysalt/celerysalt-ui`  
**License:** 
- Free version: Apache 2.0
- Pro version: Proprietary (requires license key)

**Distribution:**
- Docker Hub (public images)
- Not available via PyPI
- Optional component

**Tech Stack:**
- Backend: FastAPI or Django
- Frontend: React/Next.js
- Database: PostgreSQL (required)

**Why Docker-only?**
- ✅ Consistent deployment across platforms
- ✅ Bundles frontend assets easily
- ✅ Includes all dependencies (Node.js, Python, etc.)
- ✅ Easy updates (`docker pull`)
- ✅ Standard for web applications

#### 3. Development Setup

**For Library Development:**
```bash
# Clone library repo
git clone https://github.com/celerysalt/celerysalt
cd celerysalt

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Build and publish to PyPI
python setup.py sdist bdist_wheel
twine upload dist/*
```

**For UI Development:**
```bash
# Clone UI repo (separate)
git clone https://github.com/celerysalt/celerysalt-ui
cd celerysalt-ui

# Start development stack
docker-compose -f docker-compose.dev.yml up

# Access UI at http://localhost:3000 (frontend)
# API at http://localhost:8000 (backend)

# Build production image
docker build -t celerysalt/ui:latest .

# Push to Docker Hub
docker push celerysalt/ui:latest
```

### Package Structure

```
PyPI Package (celerysalt):
├── setup.py
├── README.md
├── LICENSE (MIT)
│
├── celerysalt/
│   ├── __init__.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── decorators.py          # @event, @subscribe
│   │   ├── event.py                # Base event class
│   │   ├── registry.py             # Schema registry client
│   │   ├── validation.py           # Pydantic helpers
│   │   └── exceptions.py           # Custom exceptions
│   │
│   ├── patterns/
│   │   ├── __init__.py
│   │   ├── rpc.py                  # RPC helpers
│   │   └── follow_actions/
│   │       ├── __init__.py
│   │       ├── base.py             # Framework-agnostic base
│   │       ├── django.py           # Django adapter
│   │       ├── sqlalchemy.py       # SQLAlchemy adapter
│   │       └── pydantic.py         # Pure Pydantic adapter
│   │
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── celery.py               # Celery integration
│   │   ├── rabbitmq.py             # RabbitMQ client
│   │   └── redis.py                # Redis client
│   │
│   ├── cloud/
│   │   ├── __init__.py
│   │   ├── client.py               # Cloud API client
│   │   └── auth.py                 # API key authentication
│   │
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py                 # CLI entry point
│   │   ├── generate.py             # Code generation commands
│   │   └── schema.py               # Schema management commands
│   │
│   └── utils/
│       ├── __init__.py
│       ├── json_encoder.py
│       ├── logging.py
│       └── cache.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
└── docs/
    ├── getting-started.md
    ├── api-reference.md
    ├── deployment.md
    ├── migration-guide.md
    └── examples/

Separate Repository - Management UI:
├── celerysalt-ui/
│   ├── Dockerfile (for celerysalt/ui:latest)
│   ├── backend/              # FastAPI or Django
│   │   ├── api/
│   │   ├── models/
│   │   └── services/
│   ├── frontend/             # React/Next.js
│   │   ├── components/
│   │   ├── pages/
│   │   └── hooks/
│   └── docker-compose.yml    # For development
```

**Key Point:** The Management UI is **NOT** included in the PyPI package. It's distributed as:
- Docker images: `celerysalt/ui:latest` (free) and `celerysalt/ui-pro:latest` (paid)
- Separate GitHub repository for development
- Optional component - library works without it

### Installation Options

```bash
# Minimal (no framework dependencies)
pip install celerysalt

# With Django support
pip install celerysalt[django]

# With SQLAlchemy support
pip install celerysalt[sqlalchemy]

# With all adapters
pip install celerysalt[all]

# Development install
pip install celerysalt[dev]
```

### Key Implementation Details

#### 1. @event Decorator

```python
from typing import Type, Any
from pydantic import BaseModel, create_model

def event(topic: str, mode: str = "broadcast", version: str = "v1"):
    """
    Decorator to define an event schema.
    
    Schema is registered IMMEDIATELY when this decorator runs (at import time).
    
    Args:
        topic: Event topic (e.g., "user.signup.completed")
        mode: "broadcast" or "rpc"
        version: Schema version (default: "v1")
    
    Usage:
        @event("user.signup.completed")
        class UserSignup:
            user_id: int
            email: str
    """
    def decorator(cls):
        # Convert class annotations to Pydantic model
        fields = {}
        for name, annotation in cls.__annotations__.items():
            default = getattr(cls, name, ...)
            fields[name] = (annotation, default)
        
        # Create Pydantic model
        pydantic_model = create_model(
            cls.__name__,
            __base__=BaseModel,
            **fields
        )
        
        # Register schema IMMEDIATELY (import time!)
        _register_schema_at_import(
            topic=topic,
            version=version,
            model=pydantic_model,
            publisher_class=cls
        )
        
        # Add metadata
        cls._celerysalt_topic = topic
        cls._celerysalt_mode = mode
        cls._celerysalt_version = version
        cls._celerysalt_model = pydantic_model
        
        # Add publish method
        if mode == "broadcast":
            cls.publish = classmethod(_create_publish_method(topic, pydantic_model))
        elif mode == "rpc":
            cls.call = classmethod(_create_rpc_method(topic, pydantic_model))
        
        return cls
    
    return decorator


def _create_publish_method(topic: str, model: Type[BaseModel]):
    """Create publish method for broadcast events."""
    def publish(cls, **kwargs):
        # 1. Validate data
        validated = model(**kwargs)
        
        # 2. Ensure schema registered (safety net if import-time registration failed)
        _ensure_schema_registered(topic, model, cls)
        
        # 3. Publish to broker
        _publish_to_rabbitmq(topic, validated.model_dump())
    
    return publish


def _create_rpc_method(topic: str, model: Type[BaseModel]):
    """Create call method for RPC events."""
    def call(cls, timeout: int = 30, **kwargs):
        # 1. Validate request
        validated = model(**kwargs)
        
        # 2. Register schema if needed
        _ensure_schema_registered(topic, model)
        
        # 3. Make RPC call
        response = _rpc_call(topic, validated.model_dump(), timeout)
        
        # 4. Validate response
        # (checks for error vs success response serializers)
        return _validate_rpc_response(topic, response)
    
    return call
```

#### 2. @subscribe Decorator

```python
def subscribe(topic: str, version: str = "latest", **celery_options):
    """
    Decorator to register an event handler.
    
    Handler becomes a Celery task with all Celery features available.
    
    Args:
        topic: Event topic pattern (supports wildcards: user.*, #)
        version: Schema version to validate against (default: "latest")
        **celery_options: All Celery task options
            - autoretry_for: Tuple of exceptions to retry
            - max_retries: Maximum retry attempts
            - retry_backoff: Enable exponential backoff
            - time_limit: Hard timeout (seconds)
            - soft_time_limit: Soft timeout (seconds)
            - rate_limit: Rate limit (e.g., '100/m')
            - priority: Task priority (0-9)
            - etc.
    
    Usage:
        @subscribe("user.signup.completed", autoretry_for=(Exception,))
        def handle_signup(data):
            send_email(data.email)
    """
    def decorator(func):
        # 1. Fetch schema from registry
        schema = _fetch_schema(topic, version)
        
        # 2. Create Pydantic model from schema
        ValidationModel = _create_model_from_schema(schema)
        
        # 3. Wrap handler with validation
        def validated_handler(raw_data: dict):
            # Extract _tchu_meta if present (for RPC detection)
            meta = raw_data.pop("_tchu_meta", {})
            is_rpc = meta.get("is_rpc", False)
            
            # Validate data
            try:
                validated = ValidationModel(**raw_data)
            except ValidationError as e:
                logger.error(f"Validation failed for {topic}: {e}")
                raise
            
            # Call handler
            result = func(validated)
            
            # For RPC, return result
            if is_rpc:
                return result
            
            return None
        
        # 4. Register as Celery task
        task = celery_app.task(
            name=f"celerysalt.{topic}.{func.__name__}",
            bind=True,  # Always bind to get task instance
            **celery_options
        )(validated_handler)
        
        # 5. Register handler in global registry (for queue binding)
        _register_handler(topic, task)
        
        # 6. Track subscriber in database
        _track_subscriber(topic, func.__name__)
        
        return task
    
    return decorator
```

#### 3. Schema Registry Client

```python
class SchemaRegistry:
    """Client for interacting with schema registry."""
    
    def __init__(self, database_url: str = None, api_url: str = None, api_key: str = None):
        """
        Initialize registry client.
        
        For self-hosted: Provide database_url
        For cloud: Provide api_url and api_key
        """
        self.mode = "cloud" if api_url else "local"
        
        if self.mode == "local":
            self.db = self._connect_database(database_url)
        else:
            self.api_url = api_url
            self.api_key = api_key
    
    def register_schema(self, topic: str, version: str, schema: dict, publisher: str):
        """Register a new schema."""
        if self.mode == "local":
            return self._register_local(topic, version, schema, publisher)
        else:
            return self._register_cloud(topic, version, schema, publisher)
    
    def get_schema(self, topic: str, version: str = "latest") -> dict:
        """Fetch schema from registry."""
        # Check cache first
        if cached := _schema_cache.get(topic, version):
            return cached
        
        # Fetch from registry
        if self.mode == "local":
            schema = self._fetch_local(topic, version)
        else:
            schema = self._fetch_cloud(topic, version)
        
        # Cache it
        _schema_cache.set(topic, version, schema)
        
        return schema
    
    def _register_local(self, topic, version, schema, publisher):
        """Register schema to local PostgreSQL."""
        # Check if already exists
        existing = self.db.query(Schema).filter_by(
            topic=topic,
            version=version
        ).first()
        
        if existing:
            return existing
        
        # Create new schema record
        schema_record = Schema(
            topic=topic,
            version=version,
            schema=schema,
            publisher_service=publisher,
            created_at=datetime.utcnow()
        )
        
        self.db.add(schema_record)
        self.db.commit()
        
        return schema_record
    
    def _register_cloud(self, topic, version, schema, publisher):
        """Register schema to cloud API."""
        response = requests.post(
            f"{self.api_url}/schemas",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "topic": topic,
                "version": version,
                "schema": schema,
                "publisher": publisher
            }
        )
        response.raise_for_status()
        return response.json()
```

#### 4. Dynamic Pydantic Model Creation

```python
from pydantic import create_model, EmailStr, Field
from typing import get_args, get_origin

def create_model_from_schema(schema: dict) -> Type[BaseModel]:
    """
    Create Pydantic model from JSON Schema.
    
    Handles:
    - Basic types (str, int, float, bool)
    - Complex types (list, dict)
    - String formats (email, uuid, date-time)
    - Required vs optional fields
    - Default values
    """
    fields = {}
    
    for field_name, field_schema in schema.get("properties", {}).items():
        # Determine Python type from JSON Schema type
        field_type = _json_schema_type_to_python(field_schema)
        
        # Check if required
        is_required = field_name in schema.get("required", [])
        
        # Get default value
        default = field_schema.get("default", ... if is_required else None)
        
        # Handle optional fields (Union with None)
        if not is_required:
            field_type = field_type | None
        
        # Create field with metadata
        fields[field_name] = (
            field_type,
            Field(
                default=default,
                description=field_schema.get("description"),
                **_extract_field_constraints(field_schema)
            )
        )
    
    # Create model
    return create_model(
        schema.get("title", "DynamicModel"),
        __base__=BaseModel,
        **fields
    )


def _json_schema_type_to_python(field_schema: dict) -> Type:
    """Convert JSON Schema type to Python type."""
    json_type = field_schema.get("type")
    format_type = field_schema.get("format")
    
    # Handle formats first
    if format_type == "email":
        return EmailStr
    if format_type == "uuid":
        return UUID
    if format_type == "date-time":
        return datetime
    
    # Handle basic types
    type_mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    
    python_type = type_mapping.get(json_type, Any)
    
    # Handle array items
    if json_type == "array" and "items" in field_schema:
        item_type = _json_schema_type_to_python(field_schema["items"])
        return list[item_type]
    
    return python_type


def _extract_field_constraints(field_schema: dict) -> dict:
    """Extract Pydantic Field constraints from JSON Schema."""
    constraints = {}
    
    # String constraints
    if "minLength" in field_schema:
        constraints["min_length"] = field_schema["minLength"]
    if "maxLength" in field_schema:
        constraints["max_length"] = field_schema["maxLength"]
    if "pattern" in field_schema:
        constraints["pattern"] = field_schema["pattern"]
    
    # Number constraints
    if "minimum" in field_schema:
        constraints["ge"] = field_schema["minimum"]
    if "maximum" in field_schema:
        constraints["le"] = field_schema["maximum"]
    
    # Enum
    if "enum" in field_schema:
        # This would need Literal type handling
        pass
    
    return constraints
```

---

## Migration Strategy

### From Current (DRF Serializers) to New (Pydantic Decorators)

#### Phase 1: Add Pydantic Support (Non-Breaking)

**Step 1:** Install new version
```bash
pip install celerysalt>=2.0.0
```

**Step 2:** Events work with both APIs
```python
# OLD WAY (still works)
from celerysalt.legacy import TchuEvent
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


# NEW WAY (recommended)
from celerysalt import event

@event("user.signup.completed")
class UserSignup:
    user_id: int

UserSignup.publish(user_id=123)
```

**Step 3:** Migrate subscribers first (safer)
```python
# Subscribers can migrate independently
# OLD
@subscribe('user.signup.completed')
def handle(event_data):
    user_id = event_data.get("user_id")

# NEW
@subscribe('user.signup.completed')
def handle(data: UserSignup):
    user_id = data.user_id  # Type-safe!
```

**Step 4:** Migrate publishers
```python
# After all subscribers are updated, migrate publishers
```

#### Phase 2: Deprecate Legacy API

**Version 2.1.0:**
- Add deprecation warnings to DRF-based API
- Document migration path
- Provide automated migration tool

```bash
# Auto-convert events
celerysalt migrate --from-drf events/
```

#### Phase 3: Remove Legacy (v3.0.0)

**Version 3.0.0:**
- Remove DRF serializer support
- Pure Pydantic API only
- Breaking change, but clean codebase

### Migration Tool

```bash
# Automated migration
celerysalt migrate \
    --input cs_common/events/ \
    --output celerysalt_events/ \
    --format pydantic

# Before:
# cs_common/events/user_signup_event.py
class UserSignupEvent(TchuEvent):
    class Meta:
        topic = "user.signup.completed"
        request_serializer_class = RequestSerializer

# After:
# celerysalt_events/user_signup.py
@event("user.signup.completed")
class UserSignup:
    user_id: int
    email: str
```

---

## Roadmap

### Phase 1: Core Library (Q1 2026 - 3 months)

**Milestone 1.0: Pydantic Migration**
- ✅ Implement `@event` decorator
- ✅ Implement `@subscribe` decorator
- ✅ Celery integration (pass through all options)
- ✅ RPC support (request/response pattern)
- ✅ Schema auto-registration
- ✅ Dynamic Pydantic model creation
- ✅ Unit tests (90%+ coverage)
- ✅ Documentation
- ✅ Migration guide from DRF

**Milestone 1.1: ORM Adapters**
- ✅ TchuFollowActions base class (framework-agnostic)
- ✅ Django adapter
- ✅ SQLAlchemy adapter
- ✅ Pydantic-only adapter
- ✅ Example projects for each

**Milestone 1.2: Developer Experience**
- ✅ CLI tool (`celerysalt`)
- ✅ Code generation (`celerysalt generate <topic>`)
- ✅ Schema validation (`celerysalt validate`)
- ✅ PyPI package published
- ✅ Initial adoption (target: 100 GitHub stars)

---

### Phase 2: Self-Hosted UI (Q2 2026 - 2-3 months)

**Milestone 2.0: Basic UI**
- ✅ Schema registry viewer
- ✅ Topic browser
- ✅ Event viewer (last 100 events)
- ✅ Real-time event stream (WebSockets)
- ✅ Docker Compose setup
- ✅ PostgreSQL schema migrations

**Milestone 2.1: Observability**
- ✅ Event search (by topic, payload, date range)
- ✅ Analytics dashboard (volume, errors, latency)
- ✅ Event lineage (what triggers what)
- ✅ Publisher/subscriber tracking

**Milestone 2.2: Testing Tools**
- ✅ Event replay (republish past events)
- ✅ Test event sender
- ✅ Payload validation tool

---

### Phase 3: Cloud Offering (Q3 2026 - 3-4 months)

**Milestone 3.0: Cloud Infrastructure**
- ✅ Multi-tenant RabbitMQ setup (vhosts)
- ✅ Multi-tenant Redis (namespacing)
- ✅ PostgreSQL for metadata
- ✅ S3 for event retention
- ✅ Regional deployment (US-East)

**Milestone 3.1: Cloud API**
- ✅ API key authentication
- ✅ Schema registry API
- ✅ Event publishing API
- ✅ Event query API
- ✅ Rate limiting
- ✅ Usage tracking

**Milestone 3.2: Billing & Licensing**
- ✅ Stripe integration
- ✅ License validation API
- ✅ Usage-based billing
- ✅ Self-service signup
- ✅ Customer portal

**Milestone 3.3: Pro UI Features**
- ✅ Advanced analytics
- ✅ Team collaboration
- ✅ Audit logs
- ✅ Custom retention policies
- ✅ Webhooks

---

### Phase 4: Enterprise & Scale (Q4 2026 - Ongoing)

**Milestone 4.0: Enterprise Features**
- ✅ SSO/SAML authentication
- ✅ RBAC (role-based access control)
- ✅ Custom SLAs
- ✅ Dedicated infrastructure option
- ✅ Compliance certifications (SOC 2, etc.)

**Milestone 4.1: Global Scale**
- ✅ Multi-region deployment (EU, APAC)
- ✅ Edge locations for low latency
- ✅ Global event routing
- ✅ Cross-region replication

**Milestone 4.2: Advanced Features**
- ✅ Event transformation (map/filter/enrich)
- ✅ Dead letter queue management
- ✅ Event archival (S3, Glacier)
- ✅ Compliance tools (GDPR deletion, etc.)
- ✅ Advanced monitoring (Datadog integration)

---

## Success Metrics

### Open Source Success (Phase 1-2)

**Adoption Metrics:**
- PyPI downloads: 10k/month by end of Q2
- GitHub stars: 1k by end of Q2
- Active contributors: 10+ by end of Q2
- Framework integrations: Django, Flask, FastAPI packages

**Community Health:**
- Discord/Slack community: 500+ members
- Weekly active contributors
- Documentation quality (>90% coverage)
- Issue response time (<48 hours)

### Cloud Success (Phase 3-4)

**Revenue Metrics:**
- MRR (Monthly Recurring Revenue): $10k by end of Q3
- Customer count: 100 paying customers by end of Q3
- Average event volume: 50M events/customer/month
- Free → Paid conversion: 5%

**Customer Satisfaction:**
- NPS (Net Promoter Score): >50
- Churn rate: <5% monthly
- Support satisfaction: >90%
- Feature request alignment: >80%

**Product-Market Fit Signals:**
- Organic growth (word of mouth referrals)
- Enterprise inquiries (companies >100 employees)
- Integration requests (from other tools)
- Conference/meetup presentations

---

## Risks & Mitigations

### Technical Risks

**Risk 1: Latency in Cloud Model**
- **Impact:** High latency makes cloud offering unusable
- **Mitigation:** 
  - Regional deployments (US, EU, APAC)
  - Edge locations for low latency
  - Hybrid model (brokers local, only telemetry to cloud)
  - Performance SLAs in contracts

**Risk 2: Schema Registry Becomes Bottleneck**
- **Impact:** Schema fetches slow down event processing
- **Mitigation:**
  - Aggressive caching (schemas rarely change)
  - Local schema cache in library
  - CDN for schema distribution
  - Schema bundling on service startup

**Risk 3: Breaking Changes in Pydantic/Celery**
- **Impact:** Library breaks when dependencies update
- **Mitigation:**
  - Pin major versions in requirements
  - Extensive CI/CD testing
  - Version compatibility matrix
  - Automated upgrade testing

### Business Risks

**Risk 1: Low Cloud Adoption**
- **Impact:** Cloud offering doesn't generate revenue
- **Mitigation:**
  - Focus on open source first (build community)
  - Validate demand before investing in cloud
  - Start with observability SaaS (lower barrier)
  - Freemium model to reduce friction

**Risk 2: Competition from AWS/GCP**
- **Impact:** Cloud providers bundle similar features
- **Mitigation:**
  - Focus on Python/Celery ecosystem (niche)
  - Better developer experience
  - Open source moat (community ownership)
  - Hybrid deployment options

**Risk 3: Open Source Cannibalizes Paid**
- **Impact:** Everyone self-hosts, nobody pays
- **Mitigation:**
  - Make self-hosted viable but tedious at scale
  - Premium UI features require license
  - Cloud offers convenience, not just features
  - Enterprise requires dedicated support

---

## Frequently Asked Questions

### Why do I need both RabbitMQ and Redis?

**RabbitMQ** handles message routing and delivery:
- Routes events to the right consumers based on topic patterns
- Provides reliable message delivery guarantees
- Handles queue management and bindings

**Redis** stores RPC results:
- Celery needs a result backend to store return values from RPC handlers
- RabbitMQ doesn't have built-in result storage (it's designed for message passing, not storage)
- This is a Celery limitation, not specific to CelerySalt

**Can I skip Redis?**
- Yes, if you only use **broadcast events** (fire-and-forget)
- No, if you use **RPC events** (request/response pattern)
- Recommended to include anyway for schema caching

### Do I need PostgreSQL for the library?

**No!** PostgreSQL is **optional** for library-only usage.

**You DON'T need PostgreSQL if:**
- Just publishing and subscribing to events
- Using local Pydantic validation (schemas defined in code)
- Using CelerySalt Cloud for schema registry
- Don't need centralized schema governance

**You DO need PostgreSQL if:**
- Want centralized schema registry (self-hosted)
- Need schema versioning and history
- Want to validate schemas across services
- Running the Management UI (self-hosted)

**Example without PostgreSQL:**
```python
# Minimal setup - no database
@event("user.signup.completed")
class UserSignup:
    user_id: int
    email: str

# Works fine! Pydantic validates locally
UserSignup.publish(user_id=123, email="test@example.com")
```

**Example with PostgreSQL:**
```python
# With registry - schemas centralized
@event("user.signup.completed")
class UserSignup:
    user_id: int

# Schema registered to PostgreSQL at import time
# Other services can validate against same schema
```

### What about using RabbitMQ's RPC pattern instead?

RabbitMQ does support RPC via reply-to queues, but Celery's result backend pattern is more robust:
- Better timeout handling
- Result persistence and expiration policies
- Support for multiple result consumers
- Consistent API across different backends (Redis, PostgreSQL, etc.)

CelerySalt follows Celery's conventions rather than implementing custom RabbitMQ RPC.

### Is the Management UI included in the Python package?

**No!** The Management UI is distributed separately as Docker images.

**Why?**
- Library users don't need UI dependencies (React, Node.js, etc.)
- UI can be updated independently from library
- Smaller, faster `pip install celerysalt`
- Different tech stacks (library = Python, UI = React/TypeScript)

**How to get the UI:**
```bash
# Pull Docker image
docker pull celerysalt/ui:latest

# OR use docker-compose
curl -O https://celerysalt.io/docker-compose.yml
docker-compose up -d
```

**Do I need the UI?**
No! The library works perfectly without it. The UI is only for:
- Browsing event schemas
- Viewing event history
- Analytics and monitoring
- Event replay/testing

If you're just publishing/subscribing to events, you don't need the UI.

---

## Appendix: Detailed Examples

### Example 1: E-commerce Order Flow

```python
# Service A: Orders Service
from celerysalt import event

@event("order.created")
class OrderCreated:
    order_id: str
    user_id: int
    total_amount: float
    items: list[dict]

@event("order.paid")
class OrderPaid:
    order_id: str
    payment_method: str
    transaction_id: str

# When order is created
OrderCreated.publish(
    order_id="ORD-123",
    user_id=456,
    total_amount=99.99,
    items=[{"sku": "WIDGET-1", "qty": 2}]
)

# When payment succeeds
OrderPaid.publish(
    order_id="ORD-123",
    payment_method="stripe",
    transaction_id="pi_123456"
)


# Service B: Email Service
from celerysalt import subscribe

@subscribe("order.created")
def send_order_confirmation(data: OrderCreated):
    send_email(
        to=get_user_email(data.user_id),
        template="order_confirmation",
        context={"order_id": data.order_id, "total": data.total_amount}
    )

@subscribe("order.paid")
def send_payment_receipt(data: OrderPaid):
    send_email(
        to=get_user_email_by_order(data.order_id),
        template="payment_receipt",
        context={"transaction_id": data.transaction_id}
    )


# Service C: Inventory Service
from celerysalt import subscribe

@subscribe(
    "order.paid",
    autoretry_for=(InventoryError,),
    max_retries=3,
    retry_backoff=True
)
def reserve_inventory(data: OrderPaid):
    """Reserve inventory with automatic retry on failure."""
    order = get_order(data.order_id)
    for item in order.items:
        inventory.reserve(item["sku"], item["qty"])


# Service D: Analytics Service
from celerysalt import subscribe

@subscribe("order.*")  # Wildcard: all order events
def track_order_event(data):
    """Track all order events in analytics."""
    analytics.track(
        event_type=data._celerysalt_topic,
        properties=data.model_dump()
    )
```

### Example 2: User Management with RPC

```python
# Service A: User Service
from celerysalt import event, subscribe, RPCError

@event("rpc.user.validate", mode="rpc")
class ValidateUserRequest:
    email: str
    password: str

@event.response("rpc.user.validate")
class ValidateUserResponse:
    user_id: int
    email: str
    is_active: bool

@event.error("rpc.user.validate")
class ValidateUserError:
    error_code: str
    error_message: str

@subscribe("rpc.user.validate")
def validate_user(data: ValidateUserRequest) -> ValidateUserResponse:
    user = User.objects.filter(email=data.email).first()
    
    if not user:
        raise RPCError(
            error_code="USER_NOT_FOUND",
            error_message="No user with this email"
        )
    
    if not user.check_password(data.password):
        raise RPCError(
            error_code="INVALID_PASSWORD",
            error_message="Incorrect password"
        )
    
    return ValidateUserResponse(
        user_id=user.id,
        email=user.email,
        is_active=user.is_active
    )


# Service B: Auth Service
from celerysalt import event

response = ValidateUserRequest.call(
    email="user@example.com",
    password="secret123",
    timeout=5
)

if isinstance(response, ValidateUserError):
    return {"error": response.error_message}
else:
    # Issue JWT token
    token = create_jwt(user_id=response.user_id)
    return {"token": token}
```

### Example 3: State Machine with TchuFollowActions

```python
# Django model with automatic event triggering
from celerysalt.adapters.django import DjangoTchuFollowActions
from django.db import models

class Subscription(DjangoTchuFollowActions, models.Model):
    """
    Subscription with automatic event publishing on state changes.
    """
    subscription_id = models.UUIDField(primary_key=True)
    user_id = models.IntegerField()
    status = models.CharField(max_length=50)  # trial, active, cancelled, expired
    trial_ends_at = models.DateTimeField(null=True)
    
    on_change_rules = models.JSONField(default=list)


# In view/service layer - set up rules
from celerysalt.patterns.follow_actions import FollowActionHelper

subscription = Subscription.objects.create(
    user_id=123,
    status="trial",
    trial_ends_at=datetime.utcnow() + timedelta(days=7)
)

# Rule 1: When status changes to "active", publish subscription.activated event
subscription.on_change_rules.append(
    FollowActionHelper.create_rule(
        field_name="status",
        operator="eql",
        value="active",
        event_class=SubscriptionActivatedEvent,
        event_data={"subscription_id": str(subscription.subscription_id)},
        persist=False  # One-time rule
    )
)

# Rule 2: When status changes to "cancelled", publish subscription.cancelled event
subscription.on_change_rules.append(
    FollowActionHelper.create_rule(
        field_name="status",
        operator="eql",
        value="cancelled",
        event_class=SubscriptionCancelledEvent,
        event_data={"subscription_id": str(subscription.subscription_id)},
        persist=False
    )
)

subscription.save()

# Later, when subscription is activated:
subscription.status = "active"
subscription.save()  # Automatically publishes SubscriptionActivatedEvent!

# The event triggers downstream actions:
@subscribe("subscription.activated")
def send_welcome_email(data):
    send_email(template="subscription_active", ...)

@subscribe("subscription.activated")
def setup_billing(data):
    billing.create_customer(...)
```

---

## Conclusion

CelerySalt is positioned to become the standard event-driven architecture library for Python teams using Celery. By combining:

1. **Familiar patterns** (Celery task features)
2. **Modern tooling** (Pydantic, decorators)
3. **Import-time schema registration** (zero boilerplate, early error detection)
4. **Zero-config schema management** (auto-registration at startup)
5. **Flexible deployment** (self-hosted or cloud)
6. **Business model** (open core with managed offering)

...we create a compelling product for both open source adoption and commercial success.

**Key Innovation:**
Import-time registration means schemas are registered when Python modules are imported (at startup), not when events are first published. This provides:
- ✅ Complete event catalog visible before any events published
- ✅ Schema conflicts detected at startup, not runtime
- ✅ CI/CD can validate schemas before deployment
- ✅ Zero runtime registration overhead
- ✅ Pythonic developer experience (decorators "just work")

**Next Steps:**
1. Implement Phase 1 (core library with Pydantic + import-time registration)
2. Build community through open source
3. Validate cloud demand through user research
4. Execute on roadmap based on feedback

---

**Document Version:** 1.1  
**Last Updated:** January 25, 2026  
**Status:** Ready for Implementation  
**Key Update:** Import-time registration pattern added as primary approach
