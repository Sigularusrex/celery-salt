# Celery Configuration Template for CelerySalt

## Recommended Pattern: setup_salt_queue (Django)

Use the standard Celery app and configure the event queue with **`setup_salt_queue()`**:

```python
# your_service/celery.py
import os
import django

from celery import Celery
from celery_salt.django import setup_salt_queue

# 1. Initialize Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.production")
django.setup()

# 2. Create Celery app
app = Celery("your_service_name")
app.config_from_object("django.conf:settings", namespace="CELERY")

# 3. Configure CelerySalt event queue
setup_salt_queue(
    app,
    queue_name="your_service_queue",  # Replace with unique queue name
    subscriber_modules=[
        "your_service.subscribers.example_subscriber",
        "your_service.subscribers.user_subscriber",
        # Add more subscriber modules as needed
    ],
)
```

**That's it!** This automatically:
- Imports all subscriber modules so `@subscribe` handlers are registered
- Collects routing keys from the handler registry
- Creates queue bindings to the `tchu_events` exchange
- Configures Celery task routes for the dispatcher
- Registers the dispatcher task for broadcast and RPC

**Optional:** If you use `Celery(..., include=[...])`, you can omit `subscriber_modules` and `setup_salt_queue()` will use `app.conf.include`.

See [EXTENDED_CELERY_USAGE.md](./EXTENDED_CELERY_USAGE.md) for details.

---

## Alternative: Subscriber modules from Celery `include`

Specify subscriber modules once in the Celery constructor:

```python
# your_service/celery.py
import os
import django

from celery import Celery
from celery_salt.django import setup_salt_queue

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.production")
django.setup()

app = Celery(
    "your_service_name",
    include=[
        "your_service.subscribers.example_subscriber",
        "your_service.subscribers.user_subscriber",
    ],
)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Uses app.conf.include for subscriber modules
setup_salt_queue(app, queue_name="your_service_queue")
```

---

## Manual Configuration Pattern (Non-Django or Advanced Use)

This pattern works reliably in **all environments** when you need full control:

```python
# your_service/celery.py

from celery import Celery
from kombu import Exchange, Queue, binding
from celery_salt.integrations.dispatcher import (
    create_topic_dispatcher,
    get_subscribed_routing_keys,
)

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
    "celery_salt.dispatch_event": {"queue": "your_service_queue"},
}

# 10. Create the dispatcher (registers the celery_salt.dispatch_event task)
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

from celery_salt import subscribe
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
from celery_salt.integrations.dispatcher import (
    create_topic_dispatcher,
    get_subscribed_routing_keys,
)

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
    "celery_salt.dispatch_event": {"queue": "cs_pulse_queue"},
}

# Create dispatcher
dispatcher = create_topic_dispatcher(app)
```

## Pattern Comparison

| Approach | Ease of Use | Django Support | Maintenance | Best For |
|----------|-------------|----------------|-------------|----------|
| **Extended Celery class** | ⭐⭐⭐⭐⭐ | ✅ Yes | ✅ Auto | Django projects |
| **setup_salt_queue()** | ⭐⭐⭐⭐ | ✅ Yes | ✅ Auto | Django projects |
| **Manual imports** | ⭐⭐⭐ | ✅ Yes | ⚠️ Manual | Advanced/non-Django |

### setup_salt_queue() (Recommended)
✅ Simple function call  
✅ Auto-imports subscriber modules (or uses Celery `include`)  
✅ Works with standard Celery class  
✅ Configures dispatcher and queue bindings  

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

**Check logs for:** Handler registration happens when subscriber modules are imported; ensure your queue is bound to the routing key in RabbitMQ.

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

1. **RabbitMQ bindings:** Queue should be bound to your routing keys.
   ```bash
   docker exec -it rabbitmq3 rabbitmqctl list_bindings | grep your_service_queue
   ```

2. **Test RPC call:**
   ```python
   from celery_salt import TchuClient
   client = TchuClient()
   result = client.call("rpc.your_service.test", {"test": "data"})
   ```

## Related Documentation

- [Troubleshooting RPC](./TROUBLESHOOTING_RPC_HANDLERS.md)
- [EXTENDED_CELERY_USAGE](./EXTENDED_CELERY_USAGE.md)
- [Main README](../README.md)

