# CelerySalt Class-Based Event API Design
**Version:** 1.0  
**Date:** January 25, 2026  
**Status:** Proposed

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Core Principle: No Shared Code](#core-principle-no-shared-code)
3. [API Design](#api-design)
4. [Class Structure](#class-structure)
5. [Schema Registration](#schema-registration)
6. [Usage Examples](#usage-examples)
7. [Advanced Patterns](#advanced-patterns)
8. [Type Safety for Subscribers](#type-safety-for-subscribers)
9. [Migration from tchu-tchu](#migration-from-tchu-tchu)
10. [Implementation Roadmap](#implementation-roadmap)
11. [FAQ](#faq)

---

## Executive Summary

CelerySalt provides a **class-based event API** that enables:

1. **Publishers** to define rich event classes with custom business logic
2. **Subscribers** to receive events without importing shared event classes
3. **Zero shared code** between services via schema registry

**Key Innovation:** Publishers use full Python classes (`SaltEvent`), while subscribers receive dynamically-typed Pydantic models generated from the schema registry. This eliminates tight coupling while maintaining type safety.

**Core Class:** `SaltEvent` (renamed from `TchuEvent` for clarity)

---

## Core Principle: No Shared Code

### The Problem We're Solving

Traditional event systems require shared code packages:

```python
# ❌ OLD WAY - Tight Coupling
# Service A (Publisher)
from cs_common.events import RiskAssessmentCreatedEvent

event = RiskAssessmentCreatedEvent(assessment_id="RA-123", ...)
event.publish()

# Service B (Subscriber) 
from cs_common.events import RiskAssessmentCreatedEvent  # Must import!

@subscribe(RiskAssessmentCreatedEvent)
def handle_risk_created(event: RiskAssessmentCreatedEvent):
    print(event.assessment_id)
```

**Problems:**
- Services are tightly coupled via `cs_common.events` package
- Version conflicts when Service A uses v2.0 but Service B uses v1.5
- Deployment coordination required across all services
- Can't have independent release cycles

### The CelerySalt Solution

```python
# ✅ NEW WAY - Zero Coupling via Schema Registry

# Service A (Publisher) - defines full class
from celerysalt import SaltEvent
from pydantic import BaseModel, Field

class RiskAssessmentCreated(SaltEvent):
    class Schema(BaseModel):
        assessment_id: str
        company_id: int
        risk_score: float = Field(ge=0, le=10)
    
    class Meta:
        topic = "pulse.risk.created"
    
    # Custom business logic
    def is_high_risk(self) -> bool:
        return self.data.risk_score >= 7.0

event = RiskAssessmentCreated(assessment_id="RA-123", company_id=456, risk_score=8.5)
event.publish()  # Schema auto-registered to PostgreSQL

# Service B (Subscriber) - NO IMPORT NEEDED!
from celerysalt import subscribe

@subscribe("pulse.risk.created")
def handle_risk_created(data):
    """
    Args:
        data: Dynamically typed Pydantic model from schema registry
              with fields: assessment_id, company_id, risk_score
    """
    print(f"Assessment {data.assessment_id} created with score {data.risk_score}")
    # data is validated using schema from registry
```

**Benefits:**
- ✅ No shared code packages between services
- ✅ Independent versioning and deployments
- ✅ Type safety maintained via schema validation
- ✅ Publishers get rich class API for business logic
- ✅ Subscribers get clean, simple interface

### How It Works

```
┌─────────────────────────────────────────────────────────────┐
│ Service A (Publisher)                                       │
│                                                             │
│  class RiskAssessmentCreated(SaltEvent):                   │
│      class Schema(BaseModel):                              │
│          assessment_id: str                                │
│          risk_score: float                                 │
│                                                             │
│      def is_high_risk(self): ...                           │
│                                                             │
│  event.publish()  ────────────────┐                        │
└───────────────────────────────────│────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │ Schema Registry (PostgreSQL)  │
                    │                               │
                    │ Topic: pulse.risk.created     │
                    │ Schema: {                     │
                    │   "properties": {             │
                    │     "assessment_id": {...},   │
                    │     "risk_score": {...}       │
                    │   }                           │
                    │ }                             │
                    └───────────────────────────────┘
                                    │
                                    │ Fetch schema at startup
                                    ▼
┌─────────────────────────────────────────────────────────────┐
│ Service B (Subscriber)                                      │
│                                                             │
│  @subscribe("pulse.risk.created")                          │
│  def handle_risk_created(data):                            │
│      # data is Pydantic model generated from schema        │
│      print(data.assessment_id)  # ✅ Type-safe!            │
│      print(data.risk_score)     # ✅ Validated!            │
└─────────────────────────────────────────────────────────────┘
```

---

## API Design

### Design Goals

1. **Rich Publisher API:** Full Python classes with methods, inheritance, hooks
2. **Simple Subscriber API:** No imports, dynamic typing from registry
3. **Type Safety:** Pydantic validation throughout
4. **Extensibility:** Support custom logic, inheritance, composition
5. **Backward Compatibility:** Easy migration from tchu-tchu

### Core Components

| Component | Purpose | Used By |
|-----------|---------|---------|
| `SaltEvent` | Base class for all events | Publishers |
| `@subscribe()` | Decorator to handle events | Subscribers |
| `SchemaRegistry` | Stores/retrieves schemas | Both |
| `SaltProducer` | Publishes to RabbitMQ | `SaltEvent.publish()` |
| `SaltDispatcher` | Routes events to handlers | Subscribers |

---

## Class Structure

### Base Class: `SaltEvent`

```python
from celerysalt import SaltEvent
from pydantic import BaseModel, Field
from typing import Optional, Type
from abc import ABC

class SaltEvent(ABC):
    """
    Base class for all CelerySalt events.
    
    Publishers define event classes that inherit from SaltEvent.
    Schemas are automatically registered to PostgreSQL on import.
    
    Attributes:
        data: Validated event data (Pydantic model instance)
    """
    
    # Required: Event schema definition
    class Schema(BaseModel):
        """Pydantic schema for this event."""
        pass
    
    # Required: Event metadata
    class Meta:
        topic: str              # Event topic (e.g., "pulse.risk.created")
        mode: str = "broadcast" # "broadcast" or "rpc"
        version: str = "v1"     # Schema version
        description: str = ""   # Human-readable description
    
    # Optional: RPC response schema
    class Response(BaseModel):
        """Response schema for RPC events."""
        pass
    
    # Optional: RPC error schema
    class Error(BaseModel):
        """Error schema for RPC events."""
        pass
    
    def __init__(self, **kwargs):
        """
        Initialize event with data.
        
        Args:
            **kwargs: Event data matching Schema fields
        """
        self.data = self.Schema(**kwargs)
    
    def publish(self, **kwargs) -> dict:
        """
        Publish event to message broker.
        
        Can be overridden for custom pre/post publish hooks.
        
        Args:
            **kwargs: Optional publish options
                - routing_key: Custom routing key
                - priority: Message priority (0-10)
                - expiration: Message expiration in ms
        
        Returns:
            dict: Publish metadata (message_id, timestamp, etc.)
        """
        # Auto-register schema if not registered
        if not self._is_schema_registered():
            self._register_schema()
        
        # Publish to broker
        return SaltProducer.publish(
            topic=self.Meta.topic,
            data=self.data.model_dump(),
            **kwargs
        )
    
    def call(self, timeout: int = 30, **kwargs):
        """
        Make RPC call and wait for response.
        
        Only for events with mode="rpc".
        
        Args:
            timeout: Response timeout in seconds
            **kwargs: Optional call options
        
        Returns:
            Response or Error instance
        
        Raises:
            RPCTimeoutError: If response not received within timeout
            ValueError: If called on non-RPC event
        """
        if self.Meta.mode != "rpc":
            raise ValueError(f"Cannot call() on broadcast event {self.Meta.topic}")
        
        # Make RPC call
        response_data = SaltProducer.call(
            topic=self.Meta.topic,
            data=self.data.model_dump(),
            timeout=timeout,
            **kwargs
        )
        
        # Parse response
        if "error" in response_data:
            return self.Error(**response_data["error"])
        else:
            return self.Response(**response_data)
    
    # Private helper methods
    def _is_schema_registered(self) -> bool:
        """Check if schema is registered in registry."""
        registry = get_schema_registry()
        return registry.has_schema(self.Meta.topic, self.Meta.version)
    
    def _register_schema(self):
        """Register schema to registry."""
        registry = get_schema_registry()
        registry.register_schema(
            topic=self.Meta.topic,
            version=self.Meta.version,
            schema=self.Schema.model_json_schema(),
            mode=self.Meta.mode,
            description=self.Meta.description,
            response_schema=self.Response.model_json_schema() if hasattr(self, 'Response') else None,
            error_schema=self.Error.model_json_schema() if hasattr(self, 'Error') else None,
        )
```

### Minimal Event Example

```python
from celerysalt import SaltEvent
from pydantic import BaseModel

class UserSignup(SaltEvent):
    """User signup event."""
    
    class Schema(BaseModel):
        user_id: int
        email: str
        signup_source: str = "web"
    
    class Meta:
        topic = "auth.user.signup"

# Usage
event = UserSignup(user_id=123, email="user@example.com")
event.publish()
```

### Event with Custom Logic

```python
from celerysalt import SaltEvent
from pydantic import BaseModel, Field

class RiskAssessmentCreated(SaltEvent):
    """Risk assessment created event."""
    
    class Schema(BaseModel):
        assessment_id: str
        company_id: int
        risk_score: float = Field(ge=0, le=10)
        assessment_type: str
    
    class Meta:
        topic = "pulse.risk.created"
        description = "A new risk assessment has been created"
    
    # ✅ Custom methods
    def is_high_risk(self) -> bool:
        """Check if this is a high-risk assessment."""
        return self.data.risk_score >= 7.0
    
    def get_risk_level(self) -> str:
        """Get risk level classification."""
        if self.data.risk_score >= 8:
            return "critical"
        elif self.data.risk_score >= 6:
            return "high"
        elif self.data.risk_score >= 4:
            return "medium"
        return "low"
    
    def get_cache_key(self) -> str:
        """Generate cache key."""
        return f"risk:{self.data.company_id}:{self.data.assessment_id}"
    
    # ✅ Override publish for custom behavior
    def publish(self, **kwargs):
        """Custom publish with audit logging."""
        # Pre-publish hook
        AuditLog.create(
            event_type="risk_created",
            company_id=self.data.company_id,
            risk_score=self.data.risk_score
        )
        
        # Publish
        result = super().publish(**kwargs)
        
        # Post-publish hook
        if self.is_high_risk():
            ComplianceNotification.send(
                assessment_id=self.data.assessment_id,
                risk_level=self.get_risk_level()
            )
        
        return result

# Usage
event = RiskAssessmentCreated(
    assessment_id="RA-123",
    company_id=456,
    risk_score=8.5,
    assessment_type="supplier_audit"
)

if event.is_high_risk():
    print(f"⚠️ High risk detected: {event.get_risk_level()}")

event.publish()
```

### RPC Event

```python
from celerysalt import SaltEvent
from pydantic import BaseModel, Field
from typing import Optional

class RiskAssessmentInformationRequest(SaltEvent):
    """RPC request for risk assessment information."""
    
    class Schema(BaseModel):
        identifier: str = Field(..., max_length=1024)
        assessment_type: str
        include_history: bool = False
    
    class Response(BaseModel):
        information: dict
        cached: bool = False
    
    class Error(BaseModel):
        error_code: str
        error_message: str
        details: Optional[dict] = None
    
    class Meta:
        topic = "rpc.pulse.risk.information"
        mode = "rpc"
        description = "Request information about a risk assessment"
    
    # ✅ Custom RPC logic
    def call_with_cache(self, timeout: int = 30):
        """Make RPC call with caching."""
        cache_key = f"risk_info:{self.data.identifier}"
        
        # Check cache first
        cached = cache.get(cache_key)
        if cached:
            return self.Response(information=cached, cached=True)
        
        # Make RPC call
        response = self.call(timeout=timeout)
        
        # Cache successful response
        if isinstance(response, self.Response):
            cache.set(cache_key, response.information, timeout=300)
        
        return response

# Usage
request = RiskAssessmentInformationRequest(
    identifier="RA-123",
    assessment_type="supplier_audit",
    include_history=True
)

response = request.call_with_cache(timeout=10)

if isinstance(response, RiskAssessmentInformationRequest.Error):
    print(f"❌ Error: {response.error_message}")
else:
    print(f"✅ Got info (cached={response.cached})")
```

---

## Schema Registration

### Automatic Registration

Schemas are automatically registered when the event class is **imported**:

```python
# When this module is imported...
from celerysalt import SaltEvent
from pydantic import BaseModel

class UserSignup(SaltEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
    
    class Meta:
        topic = "auth.user.signup"

# ...the schema is automatically registered to PostgreSQL
```

**How it works:**

1. Python imports the module containing `UserSignup`
2. `SaltEvent.__init_subclass__()` is called automatically
3. Schema is extracted from `Schema` class
4. Schema is registered to PostgreSQL via `SchemaRegistry`

### Manual Registration

For advanced use cases, you can manually control registration:

```python
from celerysalt import SaltEvent

class MyEvent(SaltEvent):
    class Schema(BaseModel):
        data: dict
    
    class Meta:
        topic = "my.event"
        auto_register = False  # ❌ Don't auto-register

# Manually register when ready
MyEvent._register_schema()
```

### Schema Versioning

Support schema evolution with versions:

```python
# v1 schema
class UserSignup(SaltEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
    
    class Meta:
        topic = "auth.user.signup"
        version = "v1"

# v2 schema (breaking changes)
class UserSignupV2(SaltEvent):
    class Schema(BaseModel):
        user_id: str  # Changed to string!
        email: str
        user_name: str  # New required field
    
    class Meta:
        topic = "auth.user.signup"
        version = "v2"

# Both schemas exist in registry
# Subscribers can choose which version to handle
```

### Schema Registry Structure

Schema stored in PostgreSQL:

```sql
CREATE TABLE celerysalt_schemas (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL,
    mode VARCHAR(20) NOT NULL,  -- 'broadcast' or 'rpc'
    schema JSONB NOT NULL,
    response_schema JSONB,
    error_schema JSONB,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(topic, version)
);

CREATE INDEX idx_schemas_topic ON celerysalt_schemas(topic);
```

Example stored schema:

```json
{
    "topic": "pulse.risk.created",
    "version": "v1",
    "mode": "broadcast",
    "schema": {
        "type": "object",
        "properties": {
            "assessment_id": {"type": "string"},
            "company_id": {"type": "integer"},
            "risk_score": {"type": "number", "minimum": 0, "maximum": 10},
            "assessment_type": {"type": "string"}
        },
        "required": ["assessment_id", "company_id", "risk_score", "assessment_type"]
    },
    "description": "A new risk assessment has been created"
}
```

---

## Usage Examples

### Example 1: Simple Broadcast Event

```python
# Service A: pulse/events/risk_events.py
from celerysalt import SaltEvent
from pydantic import BaseModel, Field

class RiskAssessmentCreated(SaltEvent):
    class Schema(BaseModel):
        assessment_id: str
        company_id: int
        risk_score: float = Field(ge=0, le=10)
    
    class Meta:
        topic = "pulse.risk.created"

# Publish event
event = RiskAssessmentCreated(
    assessment_id="RA-123",
    company_id=456,
    risk_score=7.5
)
event.publish()
```

```python
# Service B: email_service/subscribers.py
from celerysalt import subscribe

@subscribe("pulse.risk.created")
def handle_risk_created(data):
    """
    Handle risk assessment creation.
    
    Args:
        data: Dynamic Pydantic model with fields from registry:
              - assessment_id: str
              - company_id: int
              - risk_score: float
    """
    print(f"📧 Sending notification for {data.assessment_id}")
    send_email(
        to=get_compliance_email(data.company_id),
        subject=f"Risk Assessment {data.assessment_id}",
        body=f"Risk score: {data.risk_score}"
    )
```

### Example 2: RPC with Response/Error

```python
# Service A: pulse/events/risk_rpc_events.py
from celerysalt import SaltEvent
from pydantic import BaseModel

class GetRiskAssessment(SaltEvent):
    class Schema(BaseModel):
        assessment_id: str
    
    class Response(BaseModel):
        assessment_id: str
        risk_score: float
        status: str
    
    class Error(BaseModel):
        error_code: str
        error_message: str
    
    class Meta:
        topic = "rpc.pulse.risk.get"
        mode = "rpc"

# Make RPC call
request = GetRiskAssessment(assessment_id="RA-123")
response = request.call(timeout=10)

if isinstance(response, GetRiskAssessment.Error):
    print(f"❌ {response.error_message}")
else:
    print(f"✅ Score: {response.risk_score}")
```

```python
# Service B: pulse/rpc_handlers.py
from celerysalt import subscribe, RPCError

@subscribe("rpc.pulse.risk.get")
def handle_get_risk_assessment(data):
    """
    Handle RPC request for risk assessment.
    
    Args:
        data: Dynamic model with field: assessment_id
    
    Returns:
        dict matching Response schema
        
    Raises:
        RPCError: If assessment not found
    """
    try:
        assessment = RiskAssessment.objects.get(
            identifier=data.assessment_id
        )
        
        return {
            "assessment_id": assessment.identifier,
            "risk_score": assessment.risk_score,
            "status": assessment.status
        }
    
    except RiskAssessment.DoesNotExist:
        raise RPCError(
            error_code="NOT_FOUND",
            error_message=f"Assessment {data.assessment_id} not found"
        )
```

### Example 3: Inheritance with Shared Logic

```python
# Service A: pulse/events/base_risk_events.py
from celerysalt import SaltEvent
from pydantic import BaseModel, Field
from abc import abstractmethod

class BaseRiskEvent(SaltEvent):
    """Base class for all risk events."""
    
    class Schema(BaseModel):
        assessment_id: str
        company_id: int
        risk_score: float = Field(ge=0, le=10)
    
    # Shared logic
    def is_high_risk(self) -> bool:
        return self.data.risk_score >= 7.0
    
    def get_risk_level(self) -> str:
        if self.data.risk_score >= 8:
            return "critical"
        elif self.data.risk_score >= 6:
            return "high"
        elif self.data.risk_score >= 4:
            return "medium"
        return "low"
    
    @abstractmethod
    def get_notification_template(self) -> str:
        """Get email template for this event."""
        pass

class RiskAssessmentCreated(BaseRiskEvent):
    """Risk assessment created."""
    
    class Schema(BaseRiskEvent.Schema):
        created_by: str
    
    class Meta:
        topic = "pulse.risk.created"
    
    def get_notification_template(self) -> str:
        return "risk_created"

class RiskAssessmentUpdated(BaseRiskEvent):
    """Risk assessment updated."""
    
    class Schema(BaseRiskEvent.Schema):
        updated_by: str
        previous_score: float
    
    class Meta:
        topic = "pulse.risk.updated"
    
    def get_notification_template(self) -> str:
        return "risk_updated"
    
    def score_increased(self) -> bool:
        return self.data.risk_score > self.data.previous_score

# Usage
event = RiskAssessmentCreated(
    assessment_id="RA-123",
    company_id=456,
    risk_score=8.5,
    created_by="analyst@company.com"
)

# Use shared logic
if event.is_high_risk():
    template = event.get_notification_template()
    send_notification(template, event.data)

event.publish()
```

### Example 4: Cascading Events (Your Use Case!)

```python
# Service A: scranton/events/tag_events.py
from celerysalt import SaltEvent
from pydantic import BaseModel, Field
from typing import Optional, Literal

class TaggedItemCreated(SaltEvent):
    """Tag added to a model."""
    
    class Schema(BaseModel):
        company_id: int
        identifier: str = Field(..., description="e.g., 'order:123'")
        model_identifier: str = Field(..., description="e.g., 'order'")
        object_json: dict
        tag_name: str
        tag_slug: str
        action: Literal["created", "deleted"] = "created"
        value_chain_id: Optional[int] = None
    
    class Meta:
        topic = "scranton.tagged_item.created"
    
    def get_related_models(self) -> list[dict]:
        """Get models that should also be tagged."""
        if self.data.model_identifier == "order" and self.data.value_chain_id:
            return [{
                "model_identifier": "valuechain",
                "identifier": f"valuechain:{self.data.value_chain_id}",
                "reason": "order_to_valuechain_cascade"
            }]
        return []
    
    def should_cascade(self) -> bool:
        """Check if tag should cascade."""
        if self.data.tag_slug.startswith("system_"):
            return False
        return len(self.get_related_models()) > 0
    
    def create_cascade_events(self) -> list['TaggedItemCreated']:
        """Create events for cascading."""
        if not self.should_cascade():
            return []
        
        cascade_events = []
        for related in self.get_related_models():
            event = TaggedItemCreated(
                company_id=self.data.company_id,
                identifier=related["identifier"],
                model_identifier=related["model_identifier"],
                object_json={"cascade_reason": related["reason"]},
                tag_name=self.data.tag_name,
                tag_slug=self.data.tag_slug,
                action="created"
            )
            cascade_events.append(event)
        
        return cascade_events
    
    def publish(self, **kwargs):
        """Publish with cascading."""
        # Publish this event
        result = super().publish(**kwargs)
        
        # Publish cascade events
        for cascade_event in self.create_cascade_events():
            cascade_event.publish(**kwargs)
        
        return result

# Usage
event = TaggedItemCreated(
    company_id=123,
    identifier="order:456",
    model_identifier="order",
    object_json={"order_id": 456},
    tag_name="High Priority",
    tag_slug="high_priority",
    value_chain_id=789
)

print(f"Will cascade: {event.should_cascade()}")
event.publish()  # Auto-cascades to valuechain:789
```

```python
# Service B: rules_engine/subscribers/tag_subscribers.py
from celerysalt import subscribe

@subscribe("scranton.tagged_item.created")
def handle_tagged_item_created(data):
    """
    Process tag creation event.
    
    Args:
        data: Dynamic model with fields from registry
    """
    print(f"🏷️ Tag '{data.tag_name}' added to {data.identifier}")
    
    # Execute matching rules
    rules = Rule.objects.filter(
        company_id=data.company_id,
        trigger_type="tagged_item_created",
        trigger_config__tag_slug=data.tag_slug
    )
    
    for rule in rules:
        execute_rule(rule, event_data=data.dict())
```

---

## Advanced Patterns

### Pattern 1: Event Composition

```python
from celerysalt import SaltEvent
from pydantic import BaseModel

class OrderEvent(SaltEvent):
    """Base class for order events."""
    
    class Schema(BaseModel):
        order_id: str
        company_id: int
    
    def get_order(self):
        """Fetch order from database."""
        return Order.objects.get(identifier=self.data.order_id)
    
    def notify_customer(self, template: str):
        """Send notification to customer."""
        order = self.get_order()
        send_email(
            to=order.customer_email,
            template=template,
            context={"order": order}
        )

class OrderCreated(OrderEvent):
    class Meta:
        topic = "orders.created"
    
    def publish(self, **kwargs):
        result = super().publish(**kwargs)
        self.notify_customer("order_created")
        return result

class OrderShipped(OrderEvent):
    class Schema(OrderEvent.Schema):
        tracking_number: str
    
    class Meta:
        topic = "orders.shipped"
    
    def publish(self, **kwargs):
        result = super().publish(**kwargs)
        self.notify_customer("order_shipped")
        return result
```

### Pattern 2: Event Validation Hooks

```python
from celerysalt import SaltEvent
from pydantic import BaseModel, validator

class PaymentProcessed(SaltEvent):
    class Schema(BaseModel):
        payment_id: str
        amount: float
        currency: str
        
        @validator('amount')
        def amount_must_be_positive(cls, v):
            if v <= 0:
                raise ValueError('Amount must be positive')
            return v
        
        @validator('currency')
        def currency_must_be_valid(cls, v):
            valid_currencies = ['USD', 'EUR', 'GBP']
            if v not in valid_currencies:
                raise ValueError(f'Currency must be one of {valid_currencies}')
            return v
    
    class Meta:
        topic = "payments.processed"
    
    def publish(self, **kwargs):
        # Additional validation before publish
        if self.data.amount > 10000:
            # Require manual approval for large payments
            ApprovalRequest.create(
                payment_id=self.data.payment_id,
                amount=self.data.amount
            )
            return {"status": "pending_approval"}
        
        return super().publish(**kwargs)
```

### Pattern 3: Event Batching

```python
from celerysalt import SaltEvent
from pydantic import BaseModel
from typing import List

class BatchEvent(SaltEvent):
    """Base class for batch events."""
    
    @classmethod
    def publish_batch(cls, items: List[dict], batch_size: int = 100):
        """Publish events in batches."""
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            events = [cls(**item) for item in batch]
            
            # Publish all events in batch
            for event in events:
                event.publish()

class UserCreated(BatchEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
    
    class Meta:
        topic = "auth.user.created"

# Usage: Bulk user creation
users = [
    {"user_id": 1, "email": "user1@example.com"},
    {"user_id": 2, "email": "user2@example.com"},
    # ... 10,000 users
]

UserCreated.publish_batch(users, batch_size=100)
```

### Pattern 4: Event Replay

```python
from celerysalt import SaltEvent
from pydantic import BaseModel
from datetime import datetime

class ReplayableEvent(SaltEvent):
    """Base class for events that support replay."""
    
    class Schema(BaseModel):
        event_id: str
        timestamp: datetime
        replay: bool = False
    
    def publish(self, **kwargs):
        """Publish with replay metadata."""
        if not self.data.replay:
            # Store event for replay
            EventStore.save(
                event_id=self.data.event_id,
                topic=self.Meta.topic,
                data=self.data.model_dump(),
                timestamp=self.data.timestamp
            )
        
        return super().publish(**kwargs)
    
    @classmethod
    def replay_events(cls, start_time: datetime, end_time: datetime):
        """Replay events from event store."""
        events = EventStore.get_events(
            topic=cls.Meta.topic,
            start_time=start_time,
            end_time=end_time
        )
        
        for event_data in events:
            event_data['replay'] = True
            event = cls(**event_data)
            event.publish()

# Usage
class OrderCreated(ReplayableEvent):
    class Schema(ReplayableEvent.Schema):
        order_id: str
        amount: float
    
    class Meta:
        topic = "orders.created"

# Replay all order created events from last week
OrderCreated.replay_events(
    start_time=datetime.now() - timedelta(days=7),
    end_time=datetime.now()
)
```

---

## Type Safety for Subscribers

### The Challenge

Subscribers don't import event classes, so IDE doesn't know field types:

```python
@subscribe("pulse.risk.created")
def handle_risk_created(data):
    print(data.assessment_id)  # ❌ IDE doesn't know this field exists
```

### Solution 1: Type Hints in Docstrings

```python
@subscribe("pulse.risk.created")
def handle_risk_created(data):
    """
    Handle risk assessment creation.
    
    Args:
        data: Dynamic Pydantic model with fields:
              - assessment_id: str
              - company_id: int
              - risk_score: float (0-10)
              - assessment_type: str
    """
    print(data.assessment_id)  # User knows type from docstring
```

### Solution 2: Type Stub Generation (Recommended)

Generate Python type stubs from schema registry:

```bash
# Generate type stubs for all schemas
celerysalt generate-stubs --output event_stubs/

# Generated files:
# event_stubs/pulse_risk_created.py
# event_stubs/orders_created.py
# ...
```

Generated stub example:

```python
# event_stubs/pulse_risk_created.py (auto-generated)
"""Type stub for pulse.risk.created event"""
from pydantic import BaseModel

class PulseRiskCreated(BaseModel):
    """Auto-generated from schema registry"""
    assessment_id: str
    company_id: int
    risk_score: float
    assessment_type: str
```

Use in subscriber:

```python
from celerysalt import subscribe
from event_stubs.pulse_risk_created import PulseRiskCreated

@subscribe("pulse.risk.created")
def handle_risk_created(data: PulseRiskCreated):  # ✅ Type hint!
    print(data.assessment_id)  # ✅ IDE autocomplete works!
    print(data.risk_score)     # ✅ Type checking works!
```

### Solution 3: Runtime Type Checking

```python
from celerysalt import subscribe
from pydantic import ValidationError

@subscribe("pulse.risk.created")
def handle_risk_created(data):
    # Runtime validation
    try:
        assert isinstance(data.assessment_id, str)
        assert isinstance(data.risk_score, float)
        assert 0 <= data.risk_score <= 10
    except (AssertionError, AttributeError) as e:
        logger.error(f"Invalid event data: {e}")
        return
    
    # Process event
    print(f"Assessment {data.assessment_id} created")
```

### Stub Generation Implementation

```python
# celerysalt/cli/generate_stubs.py

from celerysalt.registry import get_schema_registry
import json

def generate_stubs(output_dir: str = "event_stubs"):
    """Generate Python type stubs from schema registry."""
    registry = get_schema_registry()
    
    for topic, version, schema_data in registry.get_all_schemas():
        # Convert topic to class name
        # "pulse.risk.created" -> "PulseRiskCreated"
        class_name = topic_to_class_name(topic)
        
        # Generate stub file
        stub_code = generate_stub_code(class_name, schema_data)
        
        # Write file
        file_path = f"{output_dir}/{topic.replace('.', '_')}.py"
        write_file(file_path, stub_code)
        
        print(f"✅ Generated {file_path}")

def topic_to_class_name(topic: str) -> str:
    """Convert topic to PascalCase class name."""
    parts = topic.replace('-', '_').split('.')
    return ''.join(word.capitalize() for word in parts)

def generate_stub_code(class_name: str, schema: dict) -> str:
    """Generate Python code for type stub."""
    code = f'''"""Auto-generated type stub"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class {class_name}(BaseModel):
    """Auto-generated from schema registry"""
'''
    
    for field_name, field_info in schema["properties"].items():
        python_type = json_type_to_python(field_info)
        required = field_name in schema.get("required", [])
        
        if required:
            code += f'    {field_name}: {python_type}\n'
        else:
            code += f'    {field_name}: Optional[{python_type}] = None\n'
    
    return code

def json_type_to_python(field_info: dict) -> str:
    """Convert JSON schema type to Python type."""
    json_type = field_info.get("type", "any")
    
    type_map = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "object": "dict",
        "array": "list",
    }
    
    return type_map.get(json_type, "Any")
```

Usage in CI/CD:

```bash
# In subscriber service deployment
pip install celerysalt
celerysalt generate-stubs --output ./event_stubs
python -m mypy .  # Type checking with stubs
```

---

## Migration from tchu-tchu

### What's Changing

| Old (`tchu-tchu`) | New (CelerySalt) | Notes |
|-------------------|------------------|-------|
| `TchuEvent` | `SaltEvent` | Renamed for clarity |
| `TchuProducer` | `SaltProducer` | Renamed |
| `TchuDispatcher` | `SaltDispatcher` | Renamed |
| `Meta.topic` format | Same | No change |
| DRF Serializers | Pydantic | Better validation |
| Import-time registration | Same | No change |

### Migration Steps

#### Step 1: Install CelerySalt

```bash
pip uninstall tchu-tchu
pip install celerysalt
```

#### Step 2: Update Imports

```python
# OLD
from tchu_tchu import TchuEvent, TchuProducer

# NEW
from celerysalt import SaltEvent, SaltProducer
```

#### Step 3: Convert DRF Serializers to Pydantic

```python
# OLD (DRF)
from rest_framework import serializers
from tchu_tchu import TchuEvent

class RequestSerializer(serializers.Serializer):
    assessment_id = serializers.CharField(max_length=1024)
    company_id = serializers.IntegerField()

class RiskAssessmentEvent(TchuEvent):
    class Meta:
        topic = "pulse.risk.created"
        request_serializer_class = RequestSerializer

# NEW (Pydantic)
from pydantic import BaseModel, Field
from celerysalt import SaltEvent

class RiskAssessmentCreated(SaltEvent):
    class Schema(BaseModel):
        assessment_id: str = Field(..., max_length=1024)
        company_id: int
    
    class Meta:
        topic = "pulse.risk.created"
```

#### Step 4: Update Event Publishing

```python
# OLD
from tchu_tchu import TchuProducer

TchuProducer.publish_event(
    topic="pulse.risk.created",
    data={"assessment_id": "RA-123", "company_id": 456}
)

# NEW
from celerysalt import SaltEvent

class RiskAssessmentCreated(SaltEvent):
    class Schema(BaseModel):
        assessment_id: str
        company_id: int
    
    class Meta:
        topic = "pulse.risk.created"

event = RiskAssessmentCreated(assessment_id="RA-123", company_id=456)
event.publish()
```

#### Step 5: Update Subscribers

```python
# OLD
from tchu_tchu.decorators import subscribe

@subscribe("pulse.risk.created")
def handle_risk_created(data):
    print(data["assessment_id"])

# NEW (same!)
from celerysalt import subscribe

@subscribe("pulse.risk.created")
def handle_risk_created(data):
    print(data.assessment_id)  # ✅ Now dot notation (Pydantic model)
```

### Backward Compatibility

CelerySalt maintains backward compatibility with tchu-tchu:

- Same topic naming convention
- Same exchange (`tchu_events`)
- Same message format (JSON)
- Subscribers don't need to change

This allows **gradual migration**:

```
Week 1: Service A switches to CelerySalt (publisher)
Week 2: Service B still uses tchu-tchu (subscriber) ✅ Still works!
Week 3: Service B switches to CelerySalt
```

### Migration Checklist

- [ ] Install CelerySalt
- [ ] Update imports: `TchuEvent` → `SaltEvent`
- [ ] Convert DRF serializers to Pydantic `Schema` classes
- [ ] Update event publishing to use class instances
- [ ] Update subscribers to use dot notation for Pydantic models
- [ ] Test event publishing and consumption
- [ ] Generate type stubs for IDE support
- [ ] Update documentation

---

## Implementation Roadmap

### Phase 1: Core Implementation (Week 1)

**Goal:** Basic `SaltEvent` class and schema registration

- [ ] Implement `SaltEvent` base class
  - [ ] `__init__()` - validate data with Pydantic
  - [ ] `publish()` - publish to broker
  - [ ] `call()` - RPC support
  - [ ] `_register_schema()` - register to PostgreSQL
- [ ] Implement `SchemaRegistry` PostgreSQL adapter
  - [ ] `register_schema()`
  - [ ] `get_schema()`
  - [ ] `has_schema()`
  - [ ] `get_all_schemas()`
- [ ] Implement `SaltProducer`
  - [ ] `publish()` - broadcast events
  - [ ] `call()` - RPC calls
- [ ] Unit tests (70%+ coverage)

**Deliverable:** Basic event publishing with schema registration

### Phase 2: Subscriber Support (Week 2)

**Goal:** Dynamic Pydantic model creation for subscribers

- [ ] Implement `@subscribe()` decorator
  - [ ] Fetch schema from registry at startup
  - [ ] Create Pydantic model from JSON schema
  - [ ] Validate incoming messages
  - [ ] Route to handler functions
- [ ] Implement `SaltDispatcher`
  - [ ] Message routing
  - [ ] Error handling
  - [ ] Retry logic
- [ ] Integration tests
  - [ ] Publisher → Registry → Subscriber flow
  - [ ] RPC request/response
  - [ ] Error handling

**Deliverable:** End-to-end event flow without shared code

### Phase 3: Advanced Features (Week 3)

**Goal:** Type stubs, CLI tools, documentation

- [ ] Implement CLI tools
  - [ ] `celerysalt generate-stubs` - type stub generation
  - [ ] `celerysalt validate` - schema validation
  - [ ] `celerysalt list-events` - list registered events
- [ ] Write comprehensive documentation
  - [ ] API reference
  - [ ] Migration guide
  - [ ] Best practices
  - [ ] Example patterns
- [ ] Create example applications
  - [ ] Simple broadcast example
  - [ ] RPC example
  - [ ] Inheritance example
  - [ ] Your tagged item example

**Deliverable:** Production-ready library with documentation

### Phase 4: Polish & Release (Week 4)

**Goal:** v1.0 release

- [ ] Code review and refinements
- [ ] Performance testing
- [ ] Security review
- [ ] Package for PyPI
- [ ] Write blog post
- [ ] Create video tutorial

**Deliverable:** CelerySalt v1.0 on PyPI

---

## FAQ

### Why not use decorators like `@event()`?

**Answer:** Decorators limit extensibility. Class-based API provides:

- Custom methods and business logic
- Inheritance hierarchies
- Override hooks (`publish()`, `call()`)
- Better IDE support
- Easier testing

However, we could add decorators as **syntactic sugar** later:

```python
# Decorator (simple cases)
@event("user.signup")
class UserSignup:
    user_id: int
    email: str

# Class-based (complex cases)
class RiskAssessmentCreated(SaltEvent):
    class Schema(BaseModel):
        assessment_id: str
    
    def is_high_risk(self): ...
    def publish(self): ...  # Custom logic
```

### Why Pydantic instead of DRF serializers?

**Answer:** 

1. **Framework agnostic** - doesn't require Django
2. **Better validation** - more expressive field validation
3. **Type hints** - native Python type hints
4. **Performance** - faster than DRF
5. **Industry standard** - used by FastAPI, SQLModel, etc.

### How do subscribers know what fields are available?

**Answer:** Three options:

1. **Docstrings** - Document fields in function docstring
2. **Type stubs** - Generate Python stubs from registry
3. **Documentation** - Publish event catalog with field descriptions

**Recommended:** Use type stubs for IDE support:

```python
# Generated stub
from event_stubs.pulse_risk_created import PulseRiskCreated

@subscribe("pulse.risk.created")
def handle_risk_created(data: PulseRiskCreated):  # ✅ IDE knows types
    print(data.assessment_id)
```

### What happens if schema changes?

**Answer:** Use versioning:

```python
# v1
class UserSignup(SaltEvent):
    class Meta:
        topic = "auth.user.signup"
        version = "v1"

# v2 (breaking changes)
class UserSignupV2(SaltEvent):
    class Meta:
        topic = "auth.user.signup"
        version = "v2"

# Subscribers choose version
@subscribe("auth.user.signup", version="v1")  # Old version
@subscribe("auth.user.signup", version="v2")  # New version
```

### Can I still use tchu-tchu?

**Answer:** Yes! CelerySalt maintains backward compatibility:

- Same exchange (`tchu_events`)
- Same message format
- Same topic naming

You can migrate gradually:

1. Service A publishes with CelerySalt
2. Service B still subscribes with tchu-tchu ✅ Works!
3. Eventually migrate Service B to CelerySalt

### How do I test events?

**Answer:** Three approaches:

1. **Unit tests** - Test event class in isolation

```python
def test_risk_event():
    event = RiskAssessmentCreated(
        assessment_id="RA-123",
        risk_score=8.5
    )
    assert event.is_high_risk() == True
```

2. **Mock publish** - Mock the publish method

```python
from unittest.mock import patch

@patch.object(RiskAssessmentCreated, 'publish')
def test_publish(mock_publish):
    event = RiskAssessmentCreated(...)
    event.publish()
    mock_publish.assert_called_once()
```

3. **Integration tests** - Test with real broker

```python
def test_event_flow():
    # Publish event
    event = RiskAssessmentCreated(...)
    event.publish()
    
    # Wait for subscriber to process
    time.sleep(1)
    
    # Check side effects
    assert Email.objects.filter(subject="Risk Alert").exists()
```

### What about event sourcing?

**Answer:** CelerySalt is designed for event-driven architecture, not event sourcing. However, you can build event sourcing on top:

```python
class EventSourced(SaltEvent):
    """Base class for event sourcing."""
    
    def publish(self, **kwargs):
        # Store event in event store
        EventStore.append(
            stream=f"{self.Meta.topic}:{self.data.aggregate_id}",
            event_type=self.Meta.topic,
            data=self.data.model_dump(),
            version=self.get_current_version()
        )
        
        # Publish to broker
        return super().publish(**kwargs)
```

### Why PostgreSQL for schema registry?

**Answer:**

- **Shared state** - All services see same schemas
- **ACID guarantees** - No race conditions
- **Queryable** - Can search/filter schemas
- **Already required** - Most services already use PostgreSQL

Alternative: Could support Redis, MongoDB, etc. via adapter pattern.

### What if I don't want schema registry?

**Answer:** You can disable it:

```python
from celerysalt import SaltEvent

class MyEvent(SaltEvent):
    class Meta:
        topic = "my.event"
        use_registry = False  # ❌ Don't use registry

# Schema not registered, subscribers must handle raw dict
```

### How do I migrate from other event systems?

**Answer:** See migration guides:

- [Migrating from tchu-tchu](#migration-from-tchu-tchu)
- [Migrating from Django Signals](./docs/migrations/django-signals.md)
- [Migrating from Celery Tasks](./docs/migrations/celery-tasks.md)
- [Migrating from Kafka](./docs/migrations/kafka.md)

---

## Appendix: Comparison with Alternatives

### vs. tchu-tchu (Your Old System)

| Feature | tchu-tchu | CelerySalt |
|---------|-----------|-----------|
| Event Class | `TchuEvent` | `SaltEvent` ✅ Renamed |
| Serialization | DRF Serializers | Pydantic ✅ Better |
| Custom Logic | Yes | Yes ✅ Same |
| Schema Registry | No | Yes ✅ New! |
| Shared Code | Required | Optional ✅ Better |
| IDE Support | Good | Better ✅ Type stubs |

### vs. Django Signals

| Feature | Django Signals | CelerySalt |
|---------|---------------|-----------|
| Cross-Service | ❌ No | ✅ Yes |
| Async | ❌ No | ✅ Yes (Celery) |
| Reliability | ❌ No guarantees | ✅ At-least-once |
| Schema Validation | ❌ No | ✅ Yes (Pydantic) |
| Type Safety | ❌ No | ✅ Yes |

### vs. Celery Tasks

| Feature | Celery Tasks | CelerySalt |
|---------|--------------|-----------|
| Pattern | RPC | Events ✅ Better |
| Pub/Sub | ❌ No | ✅ Yes |
| Schema | ❌ No | ✅ Yes |
| Versioning | ❌ No | ✅ Yes |
| Observability | ⚠️ Limited | ✅ Full (via UI) |

### vs. Kafka

| Feature | Kafka | CelerySalt |
|---------|-------|-----------|
| Scale | ✅ Massive | ⚠️ Medium |
| Setup | ❌ Complex | ✅ Simple |
| Schema | ⚠️ Schema Registry | ✅ Built-in |
| Python API | ⚠️ Low-level | ✅ High-level |
| Celery Integration | ❌ No | ✅ Native |

---

## Summary

CelerySalt's class-based event API provides:

✅ **Rich Publisher API** - Full Python classes with custom logic  
✅ **Simple Subscriber API** - No shared code, dynamic typing  
✅ **Type Safety** - Pydantic validation throughout  
✅ **Schema Registry** - PostgreSQL-backed schema storage  
✅ **Zero Coupling** - Services are truly independent  
✅ **Easy Migration** - Gradual migration from tchu-tchu  
✅ **Best Practices** - Inheritance, composition, hooks  

**Next Steps:**

1. Review this design document
2. Provide feedback
3. Begin implementation (Phase 1)
4. Build examples
5. Write tests
6. Release v1.0!

---

**Questions? Feedback?** Let's discuss! 🚀
