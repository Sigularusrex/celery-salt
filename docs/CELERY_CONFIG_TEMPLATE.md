# Celery Configuration Template for tchu-tchu

## Recommended Pattern: Extended Celery Class (v2.2.26+)

This is the simplest and most Pythonic approach for Django projects:

```python
# your_service/celery.py
import os
import django

from tchu_tchu.django import Celery  # Extended Celery from tchu-tchu
from tchu_tchu.events import TchuEvent

# 1. Initialize Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.production")
django.setup()

# 2. Create Celery app with tchu-tchu extensions
app = Celery("your_service_name")
app.config_from_object("django.conf:settings", namespace="CELERY")

# 3. Optional: Set context helper for request reconstruction
def create_context_helper(event_data):
    # Your context reconstruction logic
    return {}

TchuEvent.set_context_helper(create_context_helper)

# 4. Configure message broker - ONE METHOD CALL! 🎉
app.message_broker(
    queue_name="your_service_queue",  # Replace with unique queue name
    include=[
        "your_service.subscribers.example_subscriber",
        "your_service.subscribers.user_subscriber",
        # Add more subscriber modules as needed
    ],
)
```

**That's it!** This automatically:
- ✅ Imports all subscriber modules after Django is ready
- ✅ Collects all routing keys from `@subscribe` decorators
- ✅ Creates queue bindings to the `tchu_events` exchange
- ✅ Configures Celery queues and task routes
- ✅ Sets up cross-service RPC messaging
- ✅ Creates the dispatcher task

See [EXTENDED_CELERY_USAGE.md](./EXTENDED_CELERY_USAGE.md) for complete documentation.

---

## Alternative Pattern: setup_celery_queue() Function

Use the standalone function if you prefer or need more control:

```python
# your_service/celery.py
import os
import django

from celery import Celery  # Standard Celery
from tchu_tchu.django import setup_celery_queue

# 1. Initialize Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.production")
django.setup()

# 2. Create Celery app
app = Celery("your_service_name")
app.config_from_object("django.conf:settings", namespace="CELERY")

# 3. Set up tchu-tchu queue
setup_celery_queue(
    app,
    queue_name="your_service_queue",
    subscriber_modules=[
        "your_service.subscribers.example_subscriber",
        "your_service.subscribers.user_subscriber",
    ],
)
```

---

## Manual Configuration Pattern (Non-Django or Advanced Use)

This pattern works reliably in **all environments** when you need full control:

```python
# your_service/celery.py

from celery import Celery
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys

# 1. Create Celery app
app = Celery(
    "your_service_name",  # Replace with your service name
)

# 2. Load Django settings (if using Django)
app.config_from_object("django.conf:settings", namespace="CELERY")

# 3. Configure broker URL (if not in settings)
# app.conf.broker_url = "amqp://guest:guest@rabbitmq:5672//"

# 4. Define the topic exchange (MUST be "tchu_events" across all services)
tchu_exchange = Exchange("tchu_events", type="topic", durable=True)

# 5. ✅ MANUALLY IMPORT ALL SUBSCRIBER MODULES
# Add one import line for each subscriber file that contains @subscribe decorators
import your_service.subscribers.example_subscriber  # noqa
import your_service.subscribers.user_subscriber  # noqa
import your_service.subscribers.order_subscriber  # noqa
# Add more as needed...

# 6. Get routing keys from registered handlers
all_routing_keys = get_subscribed_routing_keys()

# Optional: Log routing keys for debugging
print(f"📋 Registered routing keys: {all_routing_keys}")

# 7. Create bindings for each routing key
all_bindings = [
    binding(tchu_exchange, routing_key=key) 
    for key in all_routing_keys
]

# 8. Configure queue with bindings
app.conf.task_queues = (
    Queue(
        "your_service_queue",  # Replace with unique queue name
        exchange=tchu_exchange,
        bindings=all_bindings,
        durable=True,
        auto_delete=False,
    ),
)

# 9. Route the dispatcher task to your queue
app.conf.task_routes = {
    "tchu_tchu.dispatch_event": {"queue": "your_service_queue"},
}

# 10. Create the dispatcher (registers the tchu_tchu.dispatch_event task)
dispatcher = create_topic_dispatcher(app)

# 11. Optional: Additional Celery configuration
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
```

## Example Subscriber File

```python
# your_service/subscribers/example_subscriber.py

from tchu_tchu import subscribe
import logging

logger = logging.getLogger(__name__)

# RPC handler - MUST return a value
@subscribe('rpc.your_service.resource.action')
def handle_rpc_request(data):
    """Handle RPC request."""
    logger.info(f"Handling RPC request: {data}")
    
    # Your business logic here
    result = process_data(data)
    
    # MUST return a value for RPC handlers
    return {
        "status": "success",
        "result": result
    }

# Broadcast event handler - can return None
@subscribe('other_service.event.created')
def handle_event(data):
    """Handle broadcast event."""
    logger.info(f"Received event: {data}")
    
    # Your business logic here
    process_event(data)
    
    # No need to return anything for broadcast events
```

## Real-World Example: CS Pulse Service

```python
# cs_pulse/celery.py

from celery import Celery
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys

app = Celery("cs_pulse")
app.config_from_object("django.conf:settings", namespace="CELERY")

tchu_exchange = Exchange("tchu_events", type="topic", durable=True)

# ✅ Manually import all subscriber modules
import cs_pulse.subscribers.document_subscriber  # noqa
import cs_pulse.subscribers.user_subscriber  # noqa
import cs_pulse.subscribers.compliance_subscriber  # noqa

# Get routing keys
all_routing_keys = get_subscribed_routing_keys()

# Create bindings
all_bindings = [binding(tchu_exchange, routing_key=key) for key in all_routing_keys]

# Configure queue
app.conf.task_queues = (
    Queue(
        "cs_pulse_queue",
        exchange=tchu_exchange,
        bindings=all_bindings,
        durable=True,
        auto_delete=False,
    ),
)

# Route dispatcher
app.conf.task_routes = {
    "tchu_tchu.dispatch_event": {"queue": "cs_pulse_queue"},
}

# Create dispatcher
dispatcher = create_topic_dispatcher(app)
```

## Pattern Comparison

| Approach | Ease of Use | Django Support | Maintenance | Best For |
|----------|-------------|----------------|-------------|----------|
| **Extended Celery class** | ⭐⭐⭐⭐⭐ | ✅ Yes | ✅ Auto | Django projects |
| **setup_celery_queue()** | ⭐⭐⭐⭐ | ✅ Yes | ✅ Auto | Django projects |
| **Manual imports** | ⭐⭐⭐ | ✅ Yes | ⚠️ Manual | Advanced/non-Django |

### Extended Celery Class (Recommended)
✅ Cleanest API  
✅ Method-based configuration  
✅ All Celery features preserved  
✅ Auto-handles Django initialization  
✅ Auto-imports subscriber modules  

### setup_celery_queue() Function
✅ Simple function call  
✅ Auto-handles Django initialization  
✅ Auto-imports subscriber modules  
✅ Works with standard Celery class  

### Manual Configuration
✅ Maximum control  
✅ Works in all environments  
✅ No hidden magic  
⚠️ Requires manual module imports  
⚠️ More boilerplate code

## Troubleshooting

### "No handlers found for routing key"

**Cause:** Handler module not imported.

**Solution:** Add import to celery.py:
```python
import your_service.subscribers.missing_subscriber  # noqa
```

### Handler not registered in logs

**Check logs for:**
```
INFO:tchu_tchu.registry:Registered handler 'handle_document_list' for routing key 'rpc.cs_pulse.documents.document.list'
```

**If missing:** The module wasn't imported. Add it to celery.py.

### Import order matters

Always import subscriber modules **BEFORE** calling `get_subscribed_routing_keys()`:

```python
# ✅ Correct order
import your_service.subscribers.example_subscriber  # noqa
all_routing_keys = get_subscribed_routing_keys()

# ❌ Wrong order
all_routing_keys = get_subscribed_routing_keys()
import your_service.subscribers.example_subscriber  # noqa - TOO LATE!
```

## Running the Worker

```bash
# Development
celery -A your_service worker -l info

# Production
celery -A your_service worker -l info --concurrency=4

# With autoreload (development only)
watchmedo auto-restart -d . -p '*.py' -- celery -A your_service worker -l info
```

## Verification

After starting your worker, check:

1. **Handler registration logs:**
   ```
   INFO:tchu_tchu.registry:Registered handler 'handle_document_list' for routing key 'rpc.cs_pulse.documents.document.list'
   ```

2. **RabbitMQ bindings:**
   ```bash
   docker exec -it rabbitmq3 rabbitmqctl list_bindings | grep your_service_queue
   ```

3. **Test RPC call:**
   ```python
   from tchu_tchu import TchuClient
   client = TchuClient()
   result = client.call('rpc.your_service.test', {'test': 'data'})
   ```

## Related Documentation

- [Migration Guide](./MIGRATION_2.2.11.md)
- [Troubleshooting Guide](./TROUBLESHOOTING_RPC_HANDLERS.md)
- [Main README](./README.md)

