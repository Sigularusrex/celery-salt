# Debug Dispatcher - Find "No Handlers" Root Cause

Add this enhanced logging to your `celery.py` to debug the "no_handlers" issue:

## Option 1: Monkey Patch the Dispatcher (Temporary Debug)

Add this RIGHT AFTER `app.message_broker()` in your `celery.py`:

```python
# At the bottom of your celery.py, after message_broker()

# Monkey patch to add debug logging
from tchu_tchu import subscriber
from tchu_tchu.registry import get_registry
import logging

logger = logging.getLogger(__name__)

# Get the original dispatcher
original_dispatcher = app.tasks.get('tchu_tchu.dispatch_event')

if original_dispatcher:
    original_run = original_dispatcher.run
    
    def debug_dispatcher(message_body, routing_key=None):
        """Enhanced dispatcher with debug logging"""
        import json
        
        # Log what we received
        logger.info("=" * 80)
        logger.info("🔍 DISPATCHER DEBUG")
        logger.info(f"Routing key received: '{routing_key}' (type: {type(routing_key)})")
        logger.info(f"Routing key repr: {repr(routing_key)}")
        logger.info(f"Message body type: {type(message_body)}")
        
        # Check registry state
        registry = get_registry()
        all_patterns = list(registry._handlers.keys())
        logger.info(f"Registry has {len(all_patterns)} patterns: {all_patterns}")
        
        # Try to get handlers
        handlers = registry.get_handlers(routing_key)
        logger.info(f"Handlers found: {len(handlers)}")
        if handlers:
            for h in handlers:
                logger.info(f"  - {h['name']} (module: {h['module']})")
        else:
            logger.warning("⚠️  NO HANDLERS FOUND!")
            logger.info("Trying to match manually...")
            # Manual pattern matching to see what's wrong
            for pattern in all_patterns:
                logger.info(f"  Testing pattern: '{pattern}'")
                # Check if it should match
                if pattern == routing_key:
                    logger.error(f"❌ EXACT MATCH EXISTS BUT get_handlers() didn't find it!")
                elif pattern.endswith('#') or pattern.endswith('*'):
                    logger.info(f"    (wildcard pattern, checking match logic)")
        
        logger.info("=" * 80)
        
        # Call original dispatcher
        return original_run(message_body, routing_key=routing_key)
    
    # Replace with debug version
    original_dispatcher.run = debug_dispatcher
    logger.info("✅ Debug dispatcher installed")
```

## Option 2: Check Registry State at Startup

Add this RIGHT BEFORE the monkey patch above:

```python
# Check registry state at startup
from tchu_tchu.registry import get_registry
import logging

logger = logging.getLogger(__name__)

registry = get_registry()
logger.info("\n" + "=" * 80)
logger.info("📋 REGISTRY STATE AT STARTUP")
logger.info(f"Total patterns registered: {len(registry._handlers)}")

for pattern, handlers in registry._handlers.items():
    logger.info(f"\n  Pattern: '{pattern}' (repr: {repr(pattern)})")
    for handler in handlers:
        logger.info(f"    ✓ {handler['name']}")
        logger.info(f"      Module: {handler['module']}")
        logger.info(f"      Function: {handler['function']}")

logger.info("=" * 80 + "\n")
```

## What to Look For

### Case 1: Routing Key Mismatch
```
Routing key received: 'coolset.event ' (extra space!)
Registry has patterns: ['coolset.event']
NO HANDLERS FOUND!
```
**Fix:** Routing key has whitespace or encoding issue.

### Case 2: Registry Empty
```
Routing key received: 'coolset.event'
Registry has 0 patterns: []
NO HANDLERS FOUND!
```
**Fix:** Handlers not registered. Django setup or import issue.

### Case 3: Pattern Match Failure
```
Routing key received: 'coolset.event'
Registry has patterns: ['coolset.#']
NO HANDLERS FOUND!
Testing pattern: 'coolset.#' (wildcard pattern, checking match logic)
```
**Fix:** Pattern matching logic broken.

### Case 4: Registry Corruption
```
Registry has patterns: ['coolset.event']
EXACT MATCH EXISTS BUT get_handlers() didn't find it!
```
**Fix:** Registry state is corrupt. Need to investigate `get_handlers()` logic.

## Next Steps

1. Add the debug code above
2. Restart workers completely
3. Publish an event
4. Share the debug logs here

This will show us EXACTLY why "no_handlers" is returned!

