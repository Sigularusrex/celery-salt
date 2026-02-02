# Celery Queue Setup for CelerySalt (Django)

## Overview

CelerySalt uses the **standard** Celery class. There is no extended Celery subclass. You configure the event queue with **`setup_salt_queue(app, ...)`** from `celery_salt.django`. This registers the dispatcher task, creates queue bindings to the `tchu_events` exchange, and discovers handlers from your subscriber modules.

## Basic Setup

```python
# your_project/celery.py
import os
import django
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.development")
django.setup()

app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Configure CelerySalt event queue
from celery_salt.django import setup_salt_queue

setup_salt_queue(
    app,
    queue_name="my_queue",
    subscriber_modules=[
        "app1.subscribers",
        "app2.subscribers",
    ],
)
```

## Subscriber Module Discovery

- **Explicit:** Pass `subscriber_modules=[...]` to `setup_salt_queue()`. These modules are imported so all `@subscribe` handlers are registered.
- **From Celery `include`:** If you omit `subscriber_modules`, `setup_salt_queue()` uses `app.conf.include` (the list you pass to `Celery(..., include=[...])`). So you can specify subscriber modules once in the Celery constructor.

### With explicit subscriber modules

```python
from celery import Celery
from celery_salt.django import setup_salt_queue

app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")

setup_salt_queue(
    app,
    queue_name="my_queue",
    subscriber_modules=[
        "app1.subscribers",
        "app2.subscribers",
    ],
)
```

### With Celery `include` (auto-discovery)

```python
from celery import Celery
from celery_salt.django import setup_salt_queue

app = Celery(
    "my_app",
    include=[
        "app1.subscribers",
        "app2.subscribers",
    ],
)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Uses app.conf.include for subscriber modules
setup_salt_queue(app, queue_name="my_queue")
```

## What `setup_salt_queue` Does

1. Imports the subscriber modules (from `subscriber_modules` or `app.conf.include`) so all `@subscribe` handlers are registered.
2. Collects routing keys from the handler registry.
3. Creates a topic queue bound to the `tchu_events` exchange with those routing keys.
4. Configures Celery task routes so the dispatcher task uses that queue and the topic exchange.
5. Registers the dispatcher task that receives messages and invokes the appropriate handlers.

## API Reference

### `setup_salt_queue()`

```python
def setup_salt_queue(
    celery_app,
    queue_name: str = "celerysalt_events",
    subscriber_modules: list[str] | None = None,
    exchange_name: str = "tchu_events",
    dispatcher_task_name: str = "celery_salt.integrations.dispatcher.dispatch_event",
    exclude_patterns: list[str] | None = None,
) -> None:
    """
    Configure CelerySalt event queue and dispatcher.

    Args:
        celery_app: Celery application instance.
        queue_name: Name of the queue (e.g. "my_service_queue").
        subscriber_modules: Modules to import for @subscribe handlers.
            If None, uses celery_app.conf.include.
        exchange_name: RabbitMQ exchange name (default "tchu_events").
        dispatcher_task_name: Task name for the dispatcher.
        exclude_patterns: Optional routing key patterns to exclude from bindings.
    """
```

## Django Settings

For `.publish()` and `.call()` to work from the web process (no Celery worker in process):

1. Add `'celery_salt.django'` to `INSTALLED_APPS`.
2. Set `CELERY_APP = "your_project.celery:app"` in settings.

See [README.md](../README.md) and [CELERY_CONFIG_TEMPLATE.md](./CELERY_CONFIG_TEMPLATE.md) for full configuration.
