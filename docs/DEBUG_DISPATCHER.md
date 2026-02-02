# Debug Dispatcher - Find "No Handlers" Root Cause

Add this enhanced logging to your `celery.py` to debug the "no_handlers" issue:

## Option 1: Monkey Patch the Dispatcher (Temporary Debug)

Add this RIGHT AFTER `setup_salt_queue()` in your `celery.py`:

```python
# At the bottom of your celery.py, after setup_salt_queue()

# Monkey patch to add debug logging
from celery_salt.integrations.registry import get_handler_registry
import logging

logger = logging.getLogger(__name__)

# Get the original dispatcher (task name: celery_salt.dispatch_event)
original_dispatcher = app.tasks.get("celery_salt.dispatch_event")

if original_dispatcher:
    original_run = original_dispatcher.run

    def debug_dispatcher(message_body, routing_key=None):
        """Enhanced dispatcher with debug logging"""
        import json

        # Log what we received
        logger.info("=" * 80)
        logger.info("DISPATCHER DEBUG")
        logger.info(f"Routing key received: %r (type: %s)", routing_key, type(routing_key).__name__)
        logger.info(f"Message body type: %s", type(message_body).__name__)

        # Check registry state
        registry = get_handler_registry()
        all_keys = list(registry._handlers.keys()) + list(registry._pattern_handlers.keys())
        logger.info("Registry has %d pattern(s): %s", len(all_keys), all_keys)

        handlers = registry.get_handlers(routing_key or "")
        logger.info("Handlers found: %d", len(handlers))
        for h in handlers:
            logger.info("  - %s (routing_key: %s)", h.get("name"), h.get("routing_key"))
        if not handlers:
            logger.warning("NO HANDLERS FOUND for routing_key=%r", routing_key)

        logger.info("=" * 80)

        return original_run(message_body, routing_key=routing_key)

    original_dispatcher.run = debug_dispatcher
    logger.info("Debug dispatcher installed")
```

## Option 2: Check Registry State at Startup

Add this RIGHT BEFORE the monkey patch above:

```python
# Check registry state at startup
from celery_salt.integrations.registry import get_handler_registry
import logging

logger = logging.getLogger(__name__)

registry = get_handler_registry()
logger.info("REGISTRY STATE AT STARTUP")
logger.info("Exact routing keys: %s", list(registry._handlers.keys()))
logger.info("Pattern routing keys: %s", list(registry._pattern_handlers.keys()))
for key, handlers in registry._handlers.items():
    for h in handlers:
        logger.info("  %s -> %s", key, h.get("name"))
for key, handlers in registry._pattern_handlers.items():
    for h in handlers:
        logger.info("  %s (pattern) -> %s", key, h.get("name"))
```

## What to Look For

### Case 1: Routing Key Mismatch
Routing key has whitespace or encoding issue; handler is registered for a slightly different key.

### Case 2: Registry Empty
Handlers not registered. Ensure subscriber modules are imported (via `setup_salt_queue(subscriber_modules=[...])` or `Celery(..., include=[...])`).

### Case 3: Pattern Match Failure
Handler registered with a wildcard pattern that does not match the incoming routing key.

## Next Steps

1. Add the debug code above (after `setup_salt_queue()`).
2. Restart workers completely.
3. Publish an event or make an RPC call.
4. Inspect logs for routing key, registry keys, and handler count.

See [TROUBLESHOOTING_RPC_HANDLERS.md](./TROUBLESHOOTING_RPC_HANDLERS.md) for more.
