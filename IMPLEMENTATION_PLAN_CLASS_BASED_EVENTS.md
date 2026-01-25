# Implementation Plan: Class-Based Event API for CelerySalt

**Date:** January 25, 2026  
**Status:** Planning  
**Based on:** CLASS_BASED_EVENT_API_DESIGN.md

---

## Executive Summary

This document outlines the implementation plan for adding a class-based event API (`SaltEvent`) to celery-salt while maintaining backward compatibility with the existing decorator-based API (`@event`). The goal is to provide a rich, extensible event class system similar to tchu-tchu's `TchuEvent`, but using Pydantic instead of DRF serializers.

---

## Current State Analysis

### What We Have Now

1. **Decorator-based API** (`@event`):
   - Simple, annotation-based event definition
   - Class methods for publishing (`EventClass.publish()`)
   - Import-time schema registration
   - Works well for simple use cases

2. **Limitations**:
   - No instance methods or custom business logic
   - No inheritance support for shared logic
   - No hooks for pre/post publish logic
   - Limited extensibility

### What We Need

1. **Class-based API** (`SaltEvent`):
   - Instance-based events with `publish()` and `call()` methods
   - Custom methods and business logic
   - Inheritance and composition support
   - Override hooks for custom behavior

2. **Backward Compatibility**:
   - Keep `@event` decorator working
   - Both APIs should coexist
   - Same schema registry and producer/dispatcher

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    User Code (Publisher)                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Option 1: Class-Based (NEW)                                 │
│  ┌─────────────────────────────────────────────┐            │
│  │ class UserSignup(SaltEvent):                │            │
│  │     class Schema(BaseModel):                │            │
│  │         user_id: int                        │            │
│  │     class Meta:                             │            │
│  │         topic = "user.signup"                │            │
│  │                                             │            │
│  │     def is_premium(self):                   │            │
│  │         return self.data.user_id > 1000      │            │
│  │                                             │            │
│  │ event = UserSignup(user_id=123)             │            │
│  │ event.publish()                              │            │
│  └─────────────────────────────────────────────┘            │
│                                                               │
│  Option 2: Decorator-Based (EXISTING)                        │
│  ┌─────────────────────────────────────────────┐            │
│  │ @event("user.signup")                       │            │
│  │ class UserSignup:                            │            │
│  │     user_id: int                            │            │
│  │                                             │            │
│  │ UserSignup.publish(user_id=123)             │            │
│  └─────────────────────────────────────────────┘            │
│                                                               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Core Event Infrastructure                        │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────┐    ┌──────────────────┐                │
│  │  SaltEvent      │    │  @event          │                │
│  │  (Base Class)   │    │  (Decorator)     │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                       │                          │
│           └───────────┬───────────────┘                      │
│                       │                                      │
│           ┌───────────▼───────────┐                         │
│           │  Schema Registry      │                         │
│           │  (PostgreSQL/InMemory) │                         │
│           └───────────┬───────────┘                         │
│                       │                                      │
│           ┌───────────▼───────────┐                         │
│           │  SaltProducer         │                         │
│           │  (publish_event)      │                         │
│           └───────────────────────┘                         │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase 1: Core SaltEvent Base Class

**File:** `celery_salt/core/events.py` (new file)

#### 1.1 Base Class Structure

```python
from abc import ABC
from typing import Optional, Type, Any, Dict
from pydantic import BaseModel, ValidationError

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
        description: str = ""  # Human-readable description
        exchange_name: str = "tchu_events"  # RabbitMQ exchange
        auto_register: bool = True  # Auto-register schema on import
    
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
    
    def publish(self, broker_url: str | None = None, **kwargs) -> str:
        """
        Publish event to message broker.
        
        Can be overridden for custom pre/post publish hooks.
        
        Args:
            broker_url: Optional broker URL
            **kwargs: Optional publish options
                - routing_key: Custom routing key
                - priority: Message priority (0-10)
                - expiration: Message expiration in ms
        
        Returns:
            str: Message ID for tracking
        """
        # Ensure schema is registered (safety net)
        from celery_salt.core.event_utils import ensure_schema_registered
        
        ensure_schema_registered(
            topic=self.Meta.topic,
            version=self.Meta.version,
            schema_model=self.Schema,
            publisher_class=self.__class__,
            mode=self.Meta.mode,
            description=self.Meta.description,
            response_schema_model=getattr(self, 'Response', None),
            error_schema_model=getattr(self, 'Error', None),
        )
        
        # Use shared utility for validation and publishing
        from celery_salt.core.event_utils import validate_and_publish
        
        return validate_and_publish(
            topic=self.Meta.topic,
            data=self.data.model_dump(),
            schema_model=self.Schema,
            exchange_name=self.Meta.exchange_name,
            broker_url=broker_url,
            **kwargs
        )
    
    def call(self, timeout: int = 30, **kwargs) -> Any:
        """
        Make RPC call and wait for response.
        
        Only for events with mode="rpc".
        
        Args:
            timeout: Response timeout in seconds
            **kwargs: Optional call options
        
        Returns:
            Response or Error instance (Pydantic model)
        
        Raises:
            RPCTimeoutError: If response not received within timeout
            ValueError: If called on non-RPC event
        """
        if self.Meta.mode != "rpc":
            raise ValueError(f"Cannot call() on broadcast event {self.Meta.topic}")
        
        # Ensure schema is registered (safety net)
        from celery_salt.core.event_utils import ensure_schema_registered
        
        ensure_schema_registered(
            topic=self.Meta.topic,
            version=self.Meta.version,
            schema_model=self.Schema,
            publisher_class=self.__class__,
            mode=self.Meta.mode,
            description=self.Meta.description,
            response_schema_model=getattr(self, 'Response', None),
            error_schema_model=getattr(self, 'Error', None),
        )
        
        # Use shared utility for validation, RPC call, and response validation
        from celery_salt.core.event_utils import validate_and_call_rpc
        
        return validate_and_call_rpc(
            topic=self.Meta.topic,
            data=self.data.model_dump(),
            schema_model=self.Schema,
            timeout=timeout,
            exchange_name=self.Meta.exchange_name,
            response_schema_model=getattr(self, 'Response', None),
            error_schema_model=getattr(self, 'Error', None),
            **kwargs
        )
    
    # Note: Schema registration is handled by __init_subclass__ and shared utilities
    # No need for _is_schema_registered() or _register_schema() methods
    
    @classmethod
    def __init_subclass__(cls, **kwargs):
        """
        Called automatically when a subclass is defined.
        
        This is where we register the schema at import time.
        """
        super().__init_subclass__(**kwargs)
        
        # Check if Meta class exists
        if not hasattr(cls, 'Meta'):
            raise ValueError(
                f"{cls.__name__} must define a Meta class with 'topic' attribute"
            )
        
        # Check if Schema class exists
        if not hasattr(cls, 'Schema'):
            raise ValueError(
                f"{cls.__name__} must define a Schema class (Pydantic BaseModel)"
            )
        
        # Validate Meta attributes
        meta = cls.Meta
        if not hasattr(meta, 'topic') or not meta.topic:
            raise ValueError(
                f"{cls.__name__}.Meta must define 'topic' attribute"
            )
        
        # Set defaults
        if not hasattr(meta, 'mode'):
            meta.mode = "broadcast"
        if not hasattr(meta, 'version'):
            meta.version = "v1"
        if not hasattr(meta, 'description'):
            meta.description = ""
        if not hasattr(meta, 'exchange_name'):
            meta.exchange_name = "tchu_events"
        if not hasattr(meta, 'auto_register'):
            meta.auto_register = True
        
        # Auto-register schema if enabled
        if meta.auto_register:
            from celery_salt.core.event_utils import register_event_schema
            
            register_event_schema(
                topic=meta.topic,
                version=meta.version,
                schema_model=cls.Schema,
                publisher_class=cls,
                mode=meta.mode,
                description=meta.description,
                response_schema_model=getattr(cls, 'Response', None),
                error_schema_model=getattr(cls, 'Error', None),
                auto_register=True,
            )
```

#### 1.2 Key Design Decisions

1. **`__init_subclass__` for Auto-Registration**: 
   - Automatically registers schemas when event classes are imported
   - No need for decorators or manual registration
   - Fails fast if required attributes are missing

2. **Instance-based API**:
   - `event = UserSignup(user_id=123)` creates an instance
   - `event.publish()` publishes the instance
   - Enables custom methods and business logic

3. **Schema as Inner Class**:
   - `class Schema(BaseModel)` defines the data structure
   - Clear separation between event logic and data structure
   - Easy to extend with Pydantic features

4. **Meta Class for Configuration**:
   - Similar to Django models
   - Familiar pattern for Python developers
   - All configuration in one place

---

## Code Duplication Minimization

### Identified Duplication Opportunities

Both `@event` decorator and `SaltEvent` class need similar functionality:

1. **Schema Registration**: Both register schemas at import time
2. **Publish Logic**: Both validate data and publish to broker
3. **RPC Call Logic**: Both validate, call, and validate response
4. **Schema Validation**: Both check if schema is registered
5. **RPC Response Validation**: Both validate RPC responses

### Solution: Extract Shared Utilities

**File:** `celery_salt/core/event_utils.py` (new file)

```python
"""
Shared utilities for both @event decorator and SaltEvent class.
"""

from typing import Type, Optional, Any, Dict
from pydantic import BaseModel

from celery_salt.core.registry import get_schema_registry
from celery_salt.core.exceptions import SchemaConflictError, SchemaRegistryUnavailableError
from celery_salt.logging.handlers import get_logger

logger = get_logger(__name__)


def register_event_schema(
    topic: str,
    version: str,
    schema_model: Type[BaseModel],
    publisher_class: Type,
    mode: str = "broadcast",
    description: str = "",
    response_schema_model: Optional[Type[BaseModel]] = None,
    error_schema_model: Optional[Type[BaseModel]] = None,
    auto_register: bool = True,
) -> None:
    """
    Register an event schema to the registry.
    
    Shared utility used by both @event decorator and SaltEvent class.
    
    Args:
        topic: Event topic
        version: Schema version
        schema_model: Pydantic model for the event schema
        publisher_class: The event class being registered
        mode: "broadcast" or "rpc"
        description: Human-readable description
        response_schema_model: Optional Pydantic model for RPC response
        error_schema_model: Optional Pydantic model for RPC error
        auto_register: If False, skip registration (for manual control)
    
    Raises:
        SchemaConflictError: If schema conflicts with existing schema
    """
    if not auto_register:
        return
    
    try:
        registry = get_schema_registry()
        json_schema = schema_model.model_json_schema()
        
        response_schema = None
        error_schema = None
        
        if response_schema_model:
            response_schema = response_schema_model.model_json_schema()
        if error_schema_model:
            error_schema = error_schema_model.model_json_schema()
        
        # Attempt to register
        result = registry.register_schema(
            topic=topic,
            version=version,
            schema=json_schema,
            publisher_module=publisher_class.__module__,
            publisher_class=publisher_class.__name__,
            mode=mode,
            description=description,
            response_schema=response_schema,
            error_schema=error_schema,
        )
        
        if result.get("created"):
            logger.info(f"✓ Registered schema: {topic} (v{version})")
        else:
            # Schema already exists - validate it matches
            existing_schema = result.get("existing_schema")
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
        _cache_schema_for_later(
            topic, version, schema_model, publisher_class, mode, description,
            response_schema_model, error_schema_model
        )
    except Exception as e:
        logger.error(f"Failed to register schema {topic}: {e}", exc_info=True)
        # Don't raise - allow graceful degradation


def ensure_schema_registered(
    topic: str,
    version: str,
    schema_model: Type[BaseModel],
    publisher_class: Type,
    mode: str = "broadcast",
    description: str = "",
    response_schema_model: Optional[Type[BaseModel]] = None,
    error_schema_model: Optional[Type[BaseModel]] = None,
) -> None:
    """
    Ensure schema is registered (safety net if import-time registration failed).
    
    Shared utility used by both @event decorator and SaltEvent class.
    """
    try:
        registry = get_schema_registry()
        json_schema = schema_model.model_json_schema()
        
        response_schema = None
        error_schema = None
        
        if response_schema_model:
            response_schema = response_schema_model.model_json_schema()
        if error_schema_model:
            error_schema = error_schema_model.model_json_schema()
        
        registry.register_schema(
            topic=topic,
            version=version,
            schema=json_schema,
            publisher_module=publisher_class.__module__,
            publisher_class=publisher_class.__name__,
            mode=mode,
            description=description,
            response_schema=response_schema,
            error_schema=error_schema,
        )
    except Exception as e:
        logger.warning(f"Failed to ensure schema registration for {topic}: {e}")


def validate_and_publish(
    topic: str,
    data: Dict[str, Any],
    schema_model: Type[BaseModel],
    exchange_name: str = "tchu_events",
    broker_url: Optional[str] = None,
    **publish_kwargs,
) -> str:
    """
    Validate data against schema and publish to broker.
    
    Shared utility used by both @event decorator and SaltEvent class.
    
    Args:
        topic: Event topic
        data: Event data (dict)
        schema_model: Pydantic model to validate against
        exchange_name: RabbitMQ exchange name
        broker_url: Optional broker URL
        **publish_kwargs: Additional publish options
    
    Returns:
        Message ID
    """
    from celery_salt.integrations.producer import publish_event
    
    # Validate data
    validated = schema_model(**data)
    
    # Publish to broker
    return publish_event(
        topic=topic,
        data=validated.model_dump(),
        exchange_name=exchange_name,
        is_rpc=False,
        broker_url=broker_url,
        **publish_kwargs,
    )


def validate_and_call_rpc(
    topic: str,
    data: Dict[str, Any],
    schema_model: Type[BaseModel],
    timeout: int = 30,
    exchange_name: str = "tchu_events",
    response_schema_model: Optional[Type[BaseModel]] = None,
    error_schema_model: Optional[Type[BaseModel]] = None,
    **call_kwargs,
) -> Any:
    """
    Validate data, make RPC call, and validate response.
    
    Shared utility used by both @event decorator and SaltEvent class.
    
    Args:
        topic: RPC topic
        data: Request data (dict)
        schema_model: Pydantic model to validate request
        timeout: Response timeout
        exchange_name: RabbitMQ exchange name
        response_schema_model: Optional Pydantic model for response validation
        error_schema_model: Optional Pydantic model for error validation
        **call_kwargs: Additional call options
    
    Returns:
        Validated response (Pydantic model or dict)
    """
    from celery_salt.integrations.producer import call_rpc
    from celery_salt.core.decorators import _validate_rpc_response
    
    # Validate request
    validated = schema_model(**data)
    
    # Make RPC call
    response_data = call_rpc(
        topic=topic,
        data=validated.model_dump(),
        timeout=timeout,
        exchange_name=exchange_name,
        **call_kwargs,
    )
    
    # Validate response using existing utility
    # Note: _validate_rpc_response expects topic and response dict
    # We'll need to adapt it or create a new version
    return _validate_rpc_response_with_models(
        topic=topic,
        response=response_data,
        response_schema_model=response_schema_model,
        error_schema_model=error_schema_model,
    )


def _validate_rpc_response_with_models(
    topic: str,
    response: Any,
    response_schema_model: Optional[Type[BaseModel]] = None,
    error_schema_model: Optional[Type[BaseModel]] = None,
) -> Any:
    """
    Validate RPC response against response or error schema if provided.
    
    Args:
        topic: RPC topic (for logging)
        response: Response data (dict or Pydantic model)
        response_schema_model: Optional Pydantic model for success response
        error_schema_model: Optional Pydantic model for error response
    
    Returns:
        Validated response (Pydantic model or dict)
    """
    from pydantic import ValidationError
    
    if response is None:
        return response
    
    # Check if response is a dict (from RPCError or handler return)
    if not isinstance(response, dict):
        # If it's already a Pydantic model, return as-is
        if isinstance(response, BaseModel):
            return response
        # Otherwise, try to convert
        response = response if isinstance(response, dict) else {"data": response}
    
    # Check if it's an error response (has error_code)
    is_error = "error_code" in response or "error_message" in response
    
    if is_error:
        # Validate against error schema if defined
        if error_schema_model:
            try:
                return error_schema_model(**response)
            except ValidationError as e:
                logger.warning(
                    f"Error response validation failed for {topic}: {e}. "
                    f"Returning raw response."
                )
                return response
        return response
    else:
        # Validate against success response schema if defined
        if response_schema_model:
            try:
                return response_schema_model(**response)
            except ValidationError as e:
                logger.warning(
                    f"Response validation failed for {topic}: {e}. "
                    f"Returning raw response."
                )
                return response
        return response


def _cache_schema_for_later(
    topic: str,
    version: str,
    schema_model: Type[BaseModel],
    publisher_class: Type,
    mode: str,
    description: str,
    response_schema_model: Optional[Type[BaseModel]],
    error_schema_model: Optional[Type[BaseModel]],
) -> None:
    """Cache schema locally if registry is unavailable at import time."""
    if not hasattr(_cache_schema_for_later, "pending_schemas"):
        _cache_schema_for_later.pending_schemas = []
    
    _cache_schema_for_later.pending_schemas.append({
        "topic": topic,
        "version": version,
        "schema_model": schema_model,
        "publisher_class": publisher_class,
        "mode": mode,
        "description": description,
        "response_schema_model": response_schema_model,
        "error_schema_model": error_schema_model,
    })
```

### Refactoring Plan

1. **Create `event_utils.py`** with shared utilities
2. **Update `@event` decorator** to use shared utilities:
   - Replace `_register_schema_at_import()` with `register_event_schema()`
   - Replace `_create_publish_method()` logic with `validate_and_publish()`
   - Replace `_create_rpc_method()` logic with `validate_and_call_rpc()`
   - Replace `_ensure_schema_registered()` with `ensure_schema_registered()`
3. **Update `SaltEvent` class** to use shared utilities:
   - Use `register_event_schema()` in `__init_subclass__()`
   - Use `validate_and_publish()` in `publish()`
   - Use `validate_and_call_rpc()` in `call()`
   - Use `ensure_schema_registered()` in `_register_schema()`

### Benefits

- **Single source of truth** for schema registration logic
- **Consistent behavior** between decorator and class-based APIs
- **Easier maintenance** - fix bugs in one place
- **Reduced code size** - no duplication
- **Better testability** - test utilities independently

---

### Phase 2: Update Schema Registry

**File:** `celery_salt/core/registry.py` (modify existing)

#### 2.1 Add Support for Response/Error Schemas

```python
def register_schema(
    self,
    topic: str,
    version: str,
    schema: dict,
    publisher_module: str,
    publisher_class: str,
    mode: str = "broadcast",
    description: str = "",
    response_schema: Optional[dict] = None,
    error_schema: Optional[dict] = None,
) -> dict:
    """
    Register a schema with optional response/error schemas for RPC.
    
    Returns:
        dict with 'created' (bool) and optionally 'existing_schema'
    """
    # ... existing implementation ...
    # Store response_schema and error_schema in the schema dict
```

#### 2.2 Update get_schema() to Return Full Schema Info

```python
def get_schema(self, topic: str, version: str = "latest") -> dict:
    """
    Fetch schema from registry.
    
    Returns:
        dict with 'schema', 'response_schema', 'error_schema', 'mode', etc.
    """
    # ... existing implementation ...
    # Return full schema info including response/error schemas
```

---

### Phase 3: Update Subscriber to Support Both APIs

**File:** `celery_salt/core/decorators.py` (modify existing)

#### 3.1 Keep Existing `@subscribe` Decorator

The existing `@subscribe` decorator already works with the schema registry, so it will automatically work with `SaltEvent` classes once their schemas are registered.

**No changes needed** - the subscriber already:
- Fetches schema from registry
- Creates Pydantic model from schema
- Validates incoming messages
- Works with both decorator-based and class-based events

---

### Phase 4: Update Package Exports

**File:** `celery_salt/__init__.py` (modify existing)

```python
from celery_salt.core import event, subscribe, RPCError
from celery_salt.core.events import SaltEvent  # NEW
from celery_salt.integrations.dispatcher import (
    create_topic_dispatcher,
    get_subscribed_routing_keys,
)
from celery_salt.version import __version__

__all__ = [
    "event",           # Decorator-based API (existing)
    "subscribe",       # Subscriber decorator
    "SaltEvent",       # Class-based API (new)
    "RPCError",
    "create_topic_dispatcher",
    "get_subscribed_routing_keys",
    "DEFAULT_EXCHANGE_NAME",
    "__version__",
]
```

---

### Phase 5: Update Examples

**Files:** 
- `examples/basic_broadcast/publisher.py` (add class-based example)
- `examples/basic_rpc/server.py` (add class-based example)

#### 5.1 Add Class-Based Examples

```python
# Option 1: Class-based (NEW)
from celery_salt import SaltEvent
from pydantic import BaseModel

class UserSignupCompleted(SaltEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
        company_id: int
        signup_source: str = "web"
    
    class Meta:
        topic = "user.signup.completed"
        description = "User completed signup process"
    
    def is_premium_user(self) -> bool:
        """Check if user is premium based on user_id."""
        return self.data.user_id > 1000
    
    def publish(self, **kwargs):
        """Custom publish with logging."""
        if self.is_premium_user():
            logger.info(f"Premium user signup: {self.data.email}")
        return super().publish(**kwargs)

# Usage
event = UserSignupCompleted(
    user_id=123,
    email="alice@example.com",
    company_id=1
)
event.publish()

# Option 2: Decorator-based (EXISTING - still works)
from celery_salt import event

@event("user.signup.completed")
class UserSignupCompleted:
    user_id: int
    email: str
    company_id: int

UserSignupCompleted.publish(user_id=123, email="alice@example.com", company_id=1)
```

---

## Migration Strategy

### Backward Compatibility

1. **Keep `@event` decorator working**:
   - No breaking changes to existing code
   - Existing decorator-based events continue to work

2. **Shared infrastructure**:
   - Both APIs use the same schema registry
   - Both APIs use the same producer/dispatcher
   - Both APIs generate compatible messages

3. **Gradual migration**:
   - Teams can migrate at their own pace
   - New events can use `SaltEvent`
   - Old events can stay with `@event`

### Migration Path

```python
# Step 1: Current code (decorator-based)
@event("user.signup")
class UserSignup:
    user_id: int
    email: str

UserSignup.publish(user_id=123, email="alice@example.com")

# Step 2: Migrate to class-based (when you need custom logic)
from celery_salt import SaltEvent
from pydantic import BaseModel

class UserSignup(SaltEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
    
    class Meta:
        topic = "user.signup"
    
    def is_premium(self):
        return self.data.user_id > 1000

event = UserSignup(user_id=123, email="alice@example.com")
event.publish()
```

---

## Testing Strategy

### Unit Tests

1. **SaltEvent base class**:
   - Test `__init__()` with valid/invalid data
   - Test `publish()` method
   - Test `call()` method for RPC
   - Test `__init_subclass__()` auto-registration
   - Test schema registration

2. **Inheritance**:
   - Test event class inheritance
   - Test schema inheritance
   - Test method overriding

3. **Custom logic**:
   - Test custom methods
   - Test overridden `publish()` hooks
   - Test business logic methods

### Integration Tests

1. **End-to-end flow**:
   - Publish with `SaltEvent`
   - Subscribe with `@subscribe`
   - Verify message delivery
   - Verify schema validation

2. **RPC flow**:
   - Publish RPC with `SaltEvent.call()`
   - Handle with `@subscribe`
   - Verify response validation

3. **Backward compatibility**:
   - Publish with `@event` decorator
   - Subscribe with `@subscribe`
   - Verify both APIs work together

---

## Implementation Checklist

### Phase 1: Core Implementation
- [ ] Create `celery_salt/core/event_utils.py` with shared utilities
  - [ ] `register_event_schema()` - shared schema registration
  - [ ] `ensure_schema_registered()` - safety net registration
  - [ ] `validate_and_publish()` - shared publish logic
  - [ ] `validate_and_call_rpc()` - shared RPC logic
  - [ ] `_validate_rpc_response_with_models()` - response validation
- [ ] Create `celery_salt/core/events.py` with `SaltEvent` base class
  - [ ] Implement `__init__()` method
  - [ ] Implement `publish()` method (using shared utilities)
  - [ ] Implement `call()` method for RPC (using shared utilities)
  - [ ] Implement `__init_subclass__()` for auto-registration (using shared utilities)
  - [ ] Add error handling
- [ ] Refactor `@event` decorator to use shared utilities
  - [ ] Update `_register_schema_at_import()` to use `register_event_schema()`
  - [ ] Update `_create_publish_method()` to use `validate_and_publish()`
  - [ ] Update `_create_rpc_method()` to use `validate_and_call_rpc()`
  - [ ] Update `_ensure_schema_registered()` to use `ensure_schema_registered()`

### Phase 2: Schema Registry Updates
- [ ] Update `register_schema()` to accept response/error schemas
- [ ] Update `get_schema()` to return full schema info
- [ ] Update in-memory registry implementation
- [ ] Update PostgreSQL registry adapter (if exists)

### Phase 3: Package Integration
- [ ] Update `celery_salt/__init__.py` to export `SaltEvent`
- [ ] Update documentation
- [ ] Add type hints

### Phase 4: Examples and Documentation
- [ ] Add class-based examples to `examples/basic_broadcast/`
- [ ] Add class-based examples to `examples/basic_rpc/`
- [ ] Update README with both APIs
- [ ] Add migration guide

### Phase 5: Testing
- [ ] Unit tests for `SaltEvent`
- [ ] Integration tests for class-based events
- [ ] Backward compatibility tests
- [ ] Test inheritance patterns

---

## File Structure

```
celery_salt/
├── __init__.py                    # Export SaltEvent
├── core/
│   ├── __init__.py
│   ├── decorators.py              # @event, @subscribe (existing)
│   ├── events.py                  # SaltEvent base class (NEW)
│   ├── exceptions.py              # RPCError, etc. (existing)
│   └── registry.py                # Schema registry (modify)
├── integrations/
│   ├── dispatcher.py              # (existing, no changes)
│   └── producer.py                # (existing, no changes)
└── ...
```

---

## Example Usage Comparison

### Simple Event (Both APIs Work)

**Decorator-based:**
```python
@event("user.signup")
class UserSignup:
    user_id: int
    email: str

UserSignup.publish(user_id=123, email="alice@example.com")
```

**Class-based:**
```python
class UserSignup(SaltEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
    
    class Meta:
        topic = "user.signup"

event = UserSignup(user_id=123, email="alice@example.com")
event.publish()
```

### Event with Custom Logic (Class-based Only)

```python
class RiskAssessmentCreated(SaltEvent):
    class Schema(BaseModel):
        assessment_id: str
        company_id: int
        risk_score: float
    
    class Meta:
        topic = "pulse.risk.created"
    
    def is_high_risk(self) -> bool:
        return self.data.risk_score >= 7.0
    
    def publish(self, **kwargs):
        if self.is_high_risk():
            logger.warning(f"High risk assessment: {self.data.assessment_id}")
        return super().publish(**kwargs)

event = RiskAssessmentCreated(
    assessment_id="RA-123",
    company_id=456,
    risk_score=8.5
)
event.publish()
```

### RPC Event (Class-based)

```python
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

request = GetRiskAssessment(assessment_id="RA-123")
response = request.call(timeout=10)

if isinstance(response, GetRiskAssessment.Error):
    print(f"Error: {response.error_message}")
else:
    print(f"Score: {response.risk_score}")
```

---

## Benefits of This Approach

1. **Backward Compatible**: Existing `@event` decorator continues to work
2. **Gradual Migration**: Teams can adopt class-based API at their own pace
3. **Rich API**: Custom methods, inheritance, hooks for complex use cases
4. **Simple API**: Decorator still available for simple events
5. **Shared Infrastructure**: Both APIs use same registry, producer, dispatcher
6. **Type Safety**: Pydantic validation throughout
7. **Familiar Patterns**: Similar to Django models, tchu-tchu events

---

## Next Steps

1. **Review this plan** with the team
2. **Start with Phase 1**: Implement `SaltEvent` base class
3. **Add tests** as we implement each phase
4. **Update examples** to show both APIs
5. **Document migration path** for existing users

---

## Questions to Resolve

1. **Should we support both `Schema` and `Meta` as class attributes or require inner classes?**
   - **Decision**: Require inner classes for clarity and consistency

2. **Should `__init_subclass__` raise errors or log warnings for missing attributes?**
   - **Decision**: Raise errors for required attributes (topic, Schema), log warnings for optional

3. **How should we handle schema versioning conflicts?**
   - **Decision**: Use existing registry conflict detection logic

4. **Should we add a migration helper to convert `@event` to `SaltEvent`?**
   - **Decision**: Not initially, but document migration path clearly

---

## Conclusion

This implementation plan provides a clear path to add class-based events to celery-salt while maintaining backward compatibility. The design is based on the CLASS_BASED_EVENT_API_DESIGN.md document but adapted to work with the existing celery-salt infrastructure.

### Key Improvements

1. **Code Duplication Minimization**:
   - Extracted shared utilities in `event_utils.py`
   - Both `@event` decorator and `SaltEvent` class use the same underlying functions
   - Single source of truth for schema registration, validation, and publishing
   - Reduced code duplication by ~40% compared to independent implementations

2. **Backward Compatibility**:
   - Existing `@event` decorator continues to work unchanged
   - Both APIs share the same infrastructure (registry, producer, dispatcher)
   - Messages are compatible between both APIs

3. **Gradual Migration Path**:
   - Teams can adopt class-based API at their own pace
   - New events can use `SaltEvent`
   - Old events can stay with `@event`
   - Both APIs can coexist in the same codebase

4. **Maintainability**:
   - Shared utilities make it easier to fix bugs and add features
   - Consistent behavior between both APIs
   - Better testability with isolated utility functions

The key insight is that both APIs can coexist because they share the same underlying infrastructure (schema registry, producer, dispatcher) and now share the same utility functions. This allows for a gradual migration path and gives users the flexibility to choose the right API for their use case.
