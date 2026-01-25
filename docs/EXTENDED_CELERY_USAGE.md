# Extended Celery Class - Usage Guide

## Overview

Starting with version 2.2.26, tchu-tchu provides an extended `Celery` class that wraps the original Celery library and adds tchu-tchu specific functionality. This provides a cleaner, more Pythonic API for Django projects.

## Benefits

1. **Cleaner API**: Import one class instead of multiple functions
2. **Better encapsulation**: tchu-tchu setup is attached to the Celery app instance
3. **Backward compatible**: All original Celery functionality is preserved
4. **More intuitive**: Use `app.message_broker()` instead of `setup_celery_queue(app, ...)`

## Migration Guide

### Before (using standalone function)

```python
from __future__ import absolute_import, unicode_literals

import os
import django
from celery import Celery
from tchu_tchu.django import setup_celery_queue

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.development")
django.setup()

app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Old way: call setup_celery_queue as a separate function
setup_celery_queue(
    app,
    queue_name="my_queue",
    subscriber_modules=[
        "app1.subscribers",
        "app2.subscribers",
    ]
)
```

### After (using extended Celery class)

```python
from __future__ import absolute_import, unicode_literals

import os
import django
from tchu_tchu.django import Celery  # Import from tchu_tchu instead of celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.development")
django.setup()

app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")

# New way: use the message_broker method with 'include' parameter (matches Celery naming)
app.message_broker(
    queue_name="my_queue",
    include=[
        "app1.subscribers",
        "app2.subscribers",
    ]
)
```

## Key Changes

1. **Import**: Change from `from celery import Celery` to `from tchu_tchu.django import Celery`
2. **Setup**: Change from `setup_celery_queue(app, ...)` to `app.message_broker(...)`
3. **Parameter**: `subscriber_modules` renamed to `include` to match Celery's naming convention

## Complete Example (Scranton Service)

### With Explicit Subscriber Modules

```python
from __future__ import absolute_import, unicode_literals

import os
import django

# Import extended Celery from tchu_tchu
from tchu_tchu.django import Celery
from tchu_tchu.events import TchuEvent

# Import context helper to persist context through events
from cs_common.events.events.tchu_event_context_helper import (
    create_request_context_from_event,
)

# Set default deployment to development if not specified
deployment = os.environ.get("SCRANTON_DEPLOYMENT", "development")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"settings.{deployment}")

# Setup Django
_setup_flag = os.environ.get("_CELERY_SETUP_DONE")
if not _setup_flag:
    os.environ["_CELERY_SETUP_DONE"] = "1"
    django.setup()

# Create Celery app with extended tchu-tchu functionality
app = Celery("scranton")

# Set up context helper
TchuEvent.set_context_helper(create_request_context_from_event)

# Load Django settings
app.config_from_object("django.conf:settings", namespace="CELERY")

# Configure message broker with explicit include modules
app.message_broker(
    queue_name="scranton_queue",
    include=[
        "scranton.subscribers",
        "cs_pulse_consumer.subscribers",
        "eudr.subscribers",
    ],
)
```

### With Auto-Discovery from Celery 'include'

```python
from __future__ import absolute_import, unicode_literals

import os
import django

# Import extended Celery from tchu_tchu
from tchu_tchu.django import Celery
from tchu_tchu.events import TchuEvent

from cs_common.events.events.tchu_event_context_helper import (
    create_request_context_from_event,
)

deployment = os.environ.get("SCRANTON_DEPLOYMENT", "development")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"settings.{deployment}")

_setup_flag = os.environ.get("_CELERY_SETUP_DONE")
if not _setup_flag:
    os.environ["_CELERY_SETUP_DONE"] = "1"
    django.setup()

# Specify full module paths in Celery's 'include' parameter
app = Celery(
    "scranton",
    include=[
        "scranton.subscribers",
        "eudr.subscribers",
        "cs_pulse_consumer.subscribers",
    ],
)

TchuEvent.set_context_helper(create_request_context_from_event)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover subscriber modules from Celery's include parameter
app.message_broker(queue_name="scranton_queue")
```

## All Available Methods

The extended `Celery` class provides:

### Standard Celery Methods
- All methods from the original `celery.Celery` class
- `config_from_object()`, `task()`, `worker_main()`, etc.

### Tchu-tchu Extensions
- `message_broker()` - Configure message broker with tchu-tchu event handling

## Backward Compatibility

The old standalone function `setup_celery_queue()` is still available and fully supported. You can continue using it if you prefer:

```python
from celery import Celery
from tchu_tchu.django import setup_celery_queue

app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")
setup_celery_queue(app, queue_name="my_queue", subscriber_modules=[...])
```

Both approaches work identically - use whichever you prefer!

## API Reference

### `Celery.message_broker()`

```python
def message_broker(
    self,
    queue_name: str,
    include: Optional[List[str]] = None,
    exchange_name: str = "tchu_events",
    exchange_type: str = "topic",
    durable: bool = True,
    auto_delete: bool = False,
) -> None:
    """
    Configure message broker with tchu-tchu event handling.
    
    Args:
        queue_name: Name of the queue (e.g., "acme_queue", "pulse_queue")
        include: Optional list of full module paths containing @subscribe decorators.
            If not provided, uses modules from Celery's 'include' constructor parameter.
            Matches Celery's naming convention for consistency.
            Note: Full paths required (e.g., "app1.subscribers", not just "app1")
        exchange_name: RabbitMQ exchange name (default: "tchu_events")
        exchange_type: Exchange type (default: "topic")
        durable: Whether queue is durable (default: True)
        auto_delete: Whether queue auto-deletes (default: False)
    """
```

**Auto-Discovery:**
If `include` is not provided to `message_broker()`, it will use the modules from `Celery(..., include=[...])`.
No automatic path modifications - you must provide full module paths.

Example:
```python
# Full module paths in Celery constructor
app = Celery("my_app", include=["app1.subscribers", "app2.subscribers", "app3.subscribers"])
app.message_broker(queue_name="my_queue")
# Uses: app1.subscribers, app2.subscribers, app3.subscribers
```

## Questions?

See the main [README.md](README.md) for more information about tchu-tchu configuration and usage.

