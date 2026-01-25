# Implementation Plan: Native Celery Retry Support via `celery_options`

> **Status: IMPLEMENTED in v3.0.0**

## Goal

Maximize Celery delegation while maintaining tchu-tchu's API:

1. **ALL broadcast handlers become Celery tasks** - dispatched via `.delay()`
2. **`celery_options` adds retry config** - optional, for handlers that need retries
3. **RPC handlers execute directly** - must return result to caller
4. **Handlers always receive `TchuEvent` instance** - consistent API
5. **No Celery imports in consuming apps** - everything goes through tchu-tchu

---

## Architecture Overview

```
Message arrives (with _tchu_meta.is_rpc flag)
    ↓
tchu_tchu.dispatch_event (Celery task)
    ↓
Registry lookup → Find handlers for routing key
    ↓
For each handler:
    IF is_rpc:
        → Call handler(data) directly (must return result)
    ELSE (broadcast):
        → Call handler_task.delay(data)  # ALWAYS async Celery task
```

**Simple rule:** RPC = direct, Broadcast = Celery task

---

## Execution Matrix

| Message Type | Execution | `celery_options` effect |
|--------------|-----------|------------------------|
| RPC (`call()`) | Direct call | N/A (ignored - must return result) |
| Broadcast (`publish()`) | `.delay()` async | Adds retry/rate-limit config |

---

## Implementation Steps

### Step 1: Modify publisher to include message type metadata

Add `_tchu_meta` to messages indicating whether it's RPC or broadcast:

```python
# In producer.py / client.py

class CeleryProducer:
    def publish(self, routing_key: str, body: dict, **kwargs):
        """Broadcast - fire and forget."""
        message = {
            **body,
            "_tchu_meta": {"is_rpc": False}
        }
        # ... send message ...

    def call(self, routing_key: str, body: dict, timeout: int = 30, **kwargs):
        """RPC - expects response."""
        message = {
            **body,
            "_tchu_meta": {"is_rpc": True}
        }
        # ... send message and wait for response ...
```

### Step 2: Modify `TchuEvent.subscribe()` to ALWAYS create Celery tasks

ALL handlers become Celery tasks. `celery_options` just adds retry config:

```python
# In events.py - TchuEvent.subscribe()

def subscribe(self) -> str:
    if not self.handler:
        raise ValueError(...)

    # ALWAYS create a Celery task (for broadcast dispatch)
    handler_task = self._create_celery_task_handler()

    # Register the task
    registry.register_handler(
        routing_key=self.topic,
        handler=handler_task,
        metadata={
            "celery_options": self.celery_options,
        },
        ...
    )
```

### Step 3: Implement `_create_celery_task_handler()`

Creates a Celery task with TchuEvent wrapper logic. Uses `celery_options` if provided:

```python
def _create_celery_task_handler(self):
    """Create a Celery task that wraps the handler with TchuEvent logic."""
    from celery import shared_task
    
    # Capture references for the closure
    event_class = self.__class__
    original_handler = self.handler
    context_helper = self._instance_context_helper or self._context_helper
    
    # Build task options - use celery_options if provided, otherwise defaults
    task_options = {
        "name": f"tchu_tchu.handler.{event_class.__module__}.{event_class.__name__}.{original_handler.__name__}",
    }
    
    # Add celery_options if provided (retries, rate limits, etc.)
    if self.celery_options:
        task_options.update(self.celery_options)
    
    @shared_task(**task_options)
    def celery_task_handler(data):
        """Celery task that wraps handler with TchuEvent logic."""
        # Remove _tchu_meta before processing
        clean_data = {k: v for k, v in data.items() if k != "_tchu_meta"}
        
        # Create event instance
        event_instance = event_class()
        
        # Check authorization
        auth_fields = [clean_data.get("user"), clean_data.get("company"), clean_data.get("user_company")]
        authorization_was_skipped = all(field is None for field in auth_fields)
        
        if authorization_was_skipped:
            event_instance.serialize_request(
                clean_data,
                skip_authorization=True,
                skip_reason="Authorization was skipped in original event",
            )
        else:
            context = None
            if context_helper:
                try:
                    context = context_helper(clean_data)
                except Exception:
                    pass
            event_instance.serialize_request(clean_data, context=context)
        
        # Call handler with TchuEvent instance
        return original_handler(event_instance)
    
    return celery_task_handler
```

### Step 4: Modify `@subscribe` decorator

Same pattern - ALWAYS create a Celery task:

```python
# In subscriber.py

def subscribe(routing_key, celery_options=None, ...):
    def decorator(func):
        from celery import shared_task
        
        # Build task options
        task_options = {
            "name": f"tchu_tchu.handler.{func.__module__}.{func.__name__}",
        }
        
        # Add celery_options if provided
        if celery_options:
            task_options.update(celery_options)
        
        # Wrap to remove _tchu_meta
        def clean_wrapper(data):
            clean_data = {k: v for k, v in data.items() if k != "_tchu_meta"}
            return func(clean_data)
        
        # ALWAYS create Celery task
        handler_task = shared_task(**task_options)(clean_wrapper)
        
        registry.register_handler(
            routing_key=routing_key,
            handler=handler_task,
            metadata={"celery_options": celery_options},
            ...
        )
        
        return func
    return decorator
```

### Step 5: Simplify dispatcher - RPC direct, broadcast async

```python
# In subscriber.py - create_topic_dispatcher()

@celery_app.task(name=task_name, bind=True)
def dispatch_event(self, message_body: str, routing_key: Optional[str] = None):
    # ... deserialize message_body to 'deserialized' ...
    
    # Extract message type from metadata
    tchu_meta = deserialized.get("_tchu_meta", {})
    is_rpc = tchu_meta.get("is_rpc", False)
    
    # Get handlers
    handlers = registry.get_handlers(routing_key)
    
    results = []
    for handler_info in handlers:
        handler_task = handler_info["function"]  # Always a Celery task now
        handler_name = handler_info["name"]
        
        if is_rpc:
            # RPC: Call task function directly (not .delay()) to return result
            result = handler_task(deserialized)
            results.append({
                "handler": handler_name,
                "status": "success",
                "result": result,
            })
        else:
            # Broadcast: Dispatch as async Celery task
            # Use deterministic task_id for deduplication
            message_id = self.request.id  # Original message task_id
            handler_task_id = f"{message_id}:{handler_name}"
            
            async_result = handler_task.apply_async(
                args=[deserialized],
                task_id=handler_task_id,  # Celery deduplicates based on this
            )
            results.append({
                "handler": handler_name,
                "status": "dispatched",
                "task_id": async_result.id,
            })
    
    return {
        "status": "completed",
        "routing_key": routing_key,
        "is_rpc": is_rpc,
        "handlers_executed": len(results),
        "results": results,
    }
```

---

## Message Flow Diagrams

### Broadcast (ALL broadcasts are now async)

```
Publisher                 Dispatcher              Handler Task (Celery)
    │                         │                          │
    │── publish() ───────────>│                          │
    │   {data, _tchu_meta:    │                          │
    │    {is_rpc: false}}     │                          │
    │                         │── handler.delay() ──────>│
    │                         │   (async dispatch)       │
    │<── {status: dispatched} │                          │
    │                         │                          │── runs async
    │                         │                          │   with retries if
    │                         │                          │   celery_options set
```

### RPC (direct call for result)

```
Caller                    Dispatcher                  Handler Task
    │                         │                          │
    │── call() ──────────────>│                          │
    │   {data, _tchu_meta:    │                          │
    │    {is_rpc: true}}      │                          │
    │                         │── handler(data) ────────>│
    │                         │   (direct call)          │
    │                         │<── return result ────────│
    │<── result ──────────────│                          │
```

---

## Key Design Decisions

### 1. Message deduplication via Celery's task_id

Celery natively prevents duplicate task execution based on `task_id`. With the new architecture:

- **Dispatcher receives message** with unique `task_id` (from `message_id`)
- **Dispatcher creates handler tasks** with deterministic `task_id` derived from message
- **Celery's result backend** tracks executed task IDs
- **Duplicate messages** are automatically skipped

**Requirements:**
```python
# celeryconfig.py
result_backend = 'redis://localhost:6379/0'
task_ignore_result = False  # Must track results for dedup
result_expires = 3600  # TTL for dedup window
```

**Handler task_id derivation:**
```python
# Deterministic task_id = message_id + handler_name
handler_task_id = f"{message_id}:{handler_name}"
handler_task.apply_async(args=[data], task_id=handler_task_id)
```

This ensures:
- Same message → same handler task_id → Celery skips duplicate
- Different handlers for same message get different task_ids (both run)
- No custom deduplication code needed

### 2. ALL handlers are Celery tasks

Every handler registered via `TchuEvent.subscribe()` or `@subscribe` becomes a Celery task at import time. This ensures:
- Consistent execution model
- All workers have tasks registered
- Full Celery ecosystem available

### 2. Dispatch method determined by message type

- `client.publish()` → `is_rpc: False` → `.delay()` async
- `client.call()` → `is_rpc: True` → direct call

### 3. `celery_options` is optional enhancement

- Without `celery_options`: Task runs with Celery defaults
- With `celery_options`: Task gets retry/rate-limit config

### 4. TchuEvent wrapper inside every task

Handlers ALWAYS receive a `TchuEvent` instance (for `TchuEvent.subscribe()`) or clean data dict (for `@subscribe`). Consistent API.

---

## Supported `celery_options`

All standard Celery task options are supported:

| Option | Type | Description |
|--------|------|-------------|
| `autoretry_for` | `tuple` | Exception classes that trigger automatic retry |
| `retry_backoff` | `bool/int` | Enable exponential backoff |
| `retry_backoff_max` | `int` | Maximum backoff time in seconds |
| `retry_jitter` | `bool` | Add randomness to backoff |
| `max_retries` | `int` | Maximum retry attempts |
| `default_retry_delay` | `int` | Default delay between retries |
| `rate_limit` | `str` | Task rate limit (e.g., "10/m") |
| `time_limit` | `int` | Hard time limit in seconds |
| `soft_time_limit` | `int` | Soft time limit in seconds |
| `acks_late` | `bool` | Acknowledge after task completes |
| `reject_on_worker_lost` | `bool` | Reject task if worker dies |

---

## Usage Examples

### Broadcast with retries

```python
class CompanyInvitationAcceptedEvent(TchuEvent):
    class Meta:
        topic = "coolset.accounts.company.invite.accepted"
        request_serializer_class = InvitationSerializer

def handle_invitation(event):
    # event is a TchuEvent instance
    company_id = event.get('company_id')
    # ... business logic ...

CompanyInvitationAcceptedEvent(
    handler=handle_invitation,
    celery_options={
        "autoretry_for": (ConnectionError, TimeoutError),
        "retry_backoff": True,
        "retry_backoff_max": 600,
        "retry_jitter": True,
        "max_retries": 5,
    }
).subscribe()

# Publisher
client.publish('coolset.accounts.company.invite.accepted', data)
# → Dispatched as async Celery task with retry support
```

### Broadcast without retries (still async!)

```python
class UserCreatedEvent(TchuEvent):
    class Meta:
        topic = "user.created"

def handle_user_created(event):
    # ... simple logic that doesn't need retries ...
    pass

UserCreatedEvent(handler=handle_user_created).subscribe()
# No celery_options - still dispatched async, just no retry config

# Publisher
client.publish('user.created', data)
# → Dispatched as async Celery task (default behavior)
```

### RPC (always direct)

```python
class GetDocumentsEvent(TchuEvent):
    class Meta:
        topic = "rpc.documents.list"
        response_serializer_class = ResponseSerializer

def get_documents(event):
    return {"documents": [...]}

GetDocumentsEvent(handler=get_documents).subscribe()

# Caller
result = client.call('rpc.documents.list', {"company_id": 123})
# → Direct call, result returned (celery_options ignored for RPC)
```

### Via @subscribe decorator

```python
@subscribe(
    'user.created',
    celery_options={
        "autoretry_for": (ConnectionError,),
        "retry_backoff": True,
        "max_retries": 3,
    }
)
def handle_user_created(data):
    user_id = data.get('user_id')
    # ...
```

---

## Testing Plan

1. **Unit tests for message metadata**
   - Verify `publish()` sets `is_rpc: False`
   - Verify `call()` sets `is_rpc: True`

2. **Unit tests for task creation**
   - Verify ALL handlers become Celery tasks at subscribe time
   - Verify task options applied correctly
   - Verify task name follows convention

3. **Integration tests for dispatch**
   - Verify RPC calls execute directly and return result
   - Verify ALL broadcasts dispatch via `.delay()`
   - Verify TchuEvent instance is passed to handlers

4. **Retry tests**
   - Verify `autoretry_for` triggers retry on matching exceptions
   - Verify `retry_backoff` applies exponential delay
   - Verify `max_retries` is respected

5. **Multi-worker tests**
   - Verify tasks are registered on all workers
   - Verify no "unregistered task" errors

---

## Migration Notes

- **Breaking change for broadcast handlers** - they now run async instead of sync within the dispatcher
- **RPC unchanged** - still returns results synchronously
- **Idempotency unchanged** - handlers should already be idempotent (RabbitMQ at-least-once delivery)
- **Result backend required** - Celery result backend must be configured for deduplication
- **Version bump** - Major version bump recommended due to behavior change

### Required Celery Configuration

For deduplication to work, ensure your Celery app has:

```python
# celeryconfig.py or app.conf
result_backend = 'redis://localhost:6379/0'  # Or your Redis URL
task_ignore_result = False
result_expires = 3600  # Dedup window in seconds (1 hour)
```

---

## Files to Modify

1. `tchu_tchu/producer.py`
   - Add `_tchu_meta` to messages in `publish()` and `call()`

2. `tchu_tchu/client.py`
   - Same as producer if client wraps producer

3. `tchu_tchu/events.py`
   - Modify `subscribe()` to ALWAYS create Celery task
   - Add `_create_celery_task_handler()` method

4. `tchu_tchu/subscriber.py`
   - Modify `@subscribe` to ALWAYS create Celery task
   - Simplify dispatcher: RPC = direct, broadcast = `.delay()`

5. `tests/test_celery_options.py` (new)
   - Unit and integration tests

6. `README.md`
   - Update documentation
   - Note breaking change for broadcasts

7. `CHANGELOG.md`
   - Add release notes
