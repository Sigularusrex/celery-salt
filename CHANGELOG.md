# Changelog

All notable changes to tchu-tchu will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.3] - 2026-01-20

### Fixed
- **Exchange declaration during setup**: Fixed `no exchange 'tchu_events'` error
  - 3.0.2 deferred ALL queue setup including exchange declaration, causing publish failures
  - Now declares a basic queue with the exchange immediately during setup
  - Subscriber imports and detailed bindings are still deferred to `celeryd_after_setup`
  - Publishers can now send to `tchu_events` even before workers start

---

## [3.0.2] - 2026-01-19

### Fixed
- **Celery Beat DatabaseScheduler compatibility**: Fixed connection pool timeout when using `django-celery-beat` with `DatabaseScheduler`
  - Subscriber module imports and routing key collection are now deferred until `celeryd_after_setup` signal
  - Previously, imports happened during Celery app initialization which could exhaust database connections before Beat's scheduler initialized
  - Celery Beat no longer triggers subscriber imports (it doesn't need them)
  - Workers still import and configure everything correctly, just at a slightly later stage

### Changed
- Added `celeryd_after_setup` signal handler to configure queue bindings after worker setup but before consuming
- Moved subscriber module imports from setup time to worker initialization time
- **Reduced startup logging verbosity**: 
  - Per-handler registration logs changed from `info` to `debug` level
  - Per-dispatch logs changed from `info` to `debug` level
  - Worker ready now shows single summary line: `Tchu-tchu: queue 'X' ready (N handlers)`
- No changes required in consuming apps - API remains backward compatible

---

## [3.0.1] - 2024-12-31

### Fixed
- **Backward compatibility with 2.x publishers**: Messages without `_tchu_meta` (from 2.x publishers) now default to direct call (old behavior) instead of async dispatch
- This allows gradual migration: upgrade subscribers to 3.x first, then publishers
- RPC calls from 2.x publishers now work correctly with 3.x subscribers

---

## [3.0.0] - 2024-12-31

### ⚠️ BREAKING CHANGES

This is a major architectural change that maximizes Celery delegation:

1. **ALL handlers are now Celery tasks** - Created at subscribe time (import time)
2. **Broadcast messages run async** - Dispatched via `.delay()` instead of direct calls
3. **RPC messages still run sync** - Direct calls to return results to caller
4. **Native deduplication via Celery task_id** - No duplicate task execution

### Changed

- **Broadcast execution model**: Handlers for `publish()` messages now run as async Celery tasks
  - Previous: Direct synchronous call within dispatcher
  - New: Dispatched via `.apply_async()` with deterministic task_id
  - Handlers must be idempotent (already required due to at-least-once delivery)

- **RPC execution model**: Unchanged - handlers still run synchronously to return results

- **Message metadata**: Messages now include `_tchu_meta.is_rpc` to determine execution mode
  - `client.publish()` → `is_rpc: False` → async dispatch
  - `client.call()` → `is_rpc: True` → direct call

### Added

- **Native Celery retry support** via `celery_options` parameter
  - Pass Celery retry options through `TchuEvent` or `@subscribe` decorator
  - Your consuming app never needs to import Celery directly!
  - Supports all major Celery task options:
    - `autoretry_for`: Tuple of exception classes to auto-retry on
    - `retry_backoff`: Enable exponential backoff (bool or int)
    - `retry_backoff_max`: Maximum backoff time in seconds
    - `retry_jitter`: Add randomness to backoff (thundering herd prevention)
    - `max_retries`: Maximum retry attempts
    - `default_retry_delay`: Default delay between retries
    - `rate_limit`: Task rate limit (e.g., "10/m")
    - `time_limit`: Hard time limit in seconds
    - `soft_time_limit`: Soft time limit in seconds
    - `acks_late`: Acknowledge after task completes
    - `reject_on_worker_lost`: Reject task if worker dies

- **Native deduplication** via Celery's task_id
  - Handler task_id = `{message_id}:{handler_id}` (deterministic)
  - Celery's result backend automatically prevents duplicate execution
  - Requires result backend configuration (see Migration section)

### Examples

```python
# Via TchuEvent - handler receives TchuEvent instance
DataExchangeRunInitiatedEvent(
    handler=execute_task,
    celery_options={
        "autoretry_for": (ConnectionError, TimeoutError),
        "retry_backoff": True,
        "retry_backoff_max": 600,
        "retry_jitter": True,
        "max_retries": 5,
    }
).subscribe()

# Via @subscribe decorator - handler receives clean data dict
@subscribe(
    'data.process',
    celery_options={
        "autoretry_for": (ConnectionError,),
        "retry_backoff": True,
        "max_retries": 3,
    }
)
def process_data(data):
    ...
```

### Migration from 2.x

1. **Ensure result backend is configured** (required for deduplication):
   ```python
   # celeryconfig.py
   result_backend = 'redis://localhost:6379/0'
   task_ignore_result = False
   result_expires = 3600  # 1 hour dedup window
   ```

2. **Handlers must be idempotent** - They may run multiple times (retries) or be skipped (dedup)

3. **Broadcast handlers now run async** - If you relied on synchronous execution, review your code

4. **Update tchu-tchu**: `pip install tchu-tchu==3.0.0`

5. **Restart all workers** - Handlers are registered as Celery tasks at import time

### Architecture Overview

```
Message arrives (with _tchu_meta.is_rpc flag)
    ↓
tchu_tchu.dispatch_event (Celery task)
    ↓
Registry lookup → Find handlers (all are Celery tasks now)
    ↓
For each handler:
    IF is_rpc (from client.call()):
        → Call handler directly (must return result)
    ELSE (from client.publish()):
        → handler.apply_async(task_id=message_id:handler_id)
        → Celery handles retries, dedup, rate limits, etc.
```

---

## [2.4.0] - 2024-12-29 (Superseded by 3.0.0)

### Added
- Initial `celery_options` support (dynamic task creation at dispatch time)
- This approach had issues with task registration across workers
- **Superseded by 3.0.0** which creates tasks at subscribe time

---

## [2.2.31] - 2025-11-07

### Changed
- Improved logging for handler registration to aid in diagnosing queue binding issues
- Simplified log messages (removed excessive emojis and visual separators)
- Log messages now use `logger.debug()` for verbose import details
- Added handler count to queue configuration log for visibility

## [2.2.30] - 2025-11-07

### Fixed
- **CRITICAL**: Fixed `ServerlessProducer` serialization by pre-encoding to bytes
  - Manually serialize task message to bytes before passing to kombu
  - Set `serializer=None` to prevent double serialization
  - Fixes "argument for 's' must be a bytes object" error in struct.pack

### Added
- Comprehensive debug logging in `ServerlessProducer` for troubleshooting
  - Logs connection initialization with transport details
  - Logs message serialization steps with type information
  - Logs publish attempts with exchange and routing key
  - Includes detailed error logging with stack traces
  - All logs prefixed with `[ServerlessProducer]` for easy filtering

**If you're using v2.2.29, upgrade immediately** - serialization is still broken!

## [2.2.29] - 2025-11-06

### Fixed
- **CRITICAL**: Fixed `ServerlessProducer` serialization error: "argument for 's' must be a bytes object"
  - Properly handle string vs bytes conversion before passing to kombu
  - Ensure task message structure is correctly serialized
  - Messages now publish without struct.pack errors

**If you're using v2.2.28, upgrade immediately** - all messages are failing to publish!

## [2.2.28] - 2025-11-06

### Fixed
- **CRITICAL**: Fixed `ServerlessProducer` to use `kombu` instead of manual message creation
  - Messages are now properly formatted as Celery tasks and consumed by workers
  - Previous version (2.2.27) published messages that were not processed by subscribers
  - Now uses `kombu.Producer` with Celery protocol (same as CeleryProducer)
  - Compatible with all existing tchu-tchu subscribers

### Changed
- Switched from `pika` to `kombu` for ServerlessProducer (kombu is already a dependency)
- ServerlessProducer now creates proper Celery task messages that dispatch correctly

**If you're using v2.2.27, upgrade immediately** - messages are being published but not consumed!

## [2.2.27] - 2025-11-06

### Added
- **NEW**: `ServerlessProducer` and `ServerlessClient` for serverless environments
  - Designed for Cloud Functions, Lambda, and other short-lived serverless platforms
  - Uses `pika` directly instead of Celery for lightweight, short-lived connections
  - Similar approach to the original tchu library (works where Celery connection pooling fails)
  - Perfect for publish-only scenarios in cloud functions
  - Supports context manager pattern for automatic connection cleanup
- Added `pika>=1.3.0` as a core dependency
- Comprehensive documentation in README for serverless usage
  - Usage examples for Google Cloud Functions
  - Network configuration guidance (VPC connectors)
  - Comparison table: ServerlessClient vs TchuClient

### Use Cases
```python
# Cloud Function example
from tchu_tchu.serverless_producer import ServerlessClient

def publish_event(request):
    with ServerlessClient(broker_url=BROKER_URL) as client:
        client.publish('user.created', {'user_id': 123})
    return {'status': 'published'}
```

### Key Features
- ✅ Works in Cloud Functions, AWS Lambda, Azure Functions
- ✅ Lightweight - minimal dependencies and overhead
- ✅ Auto-reconnect with retry logic built-in
- ✅ Context manager support for clean resource management
- ⚠️ Publish-only (no RPC or subscribe support)

### Migration from Old Tchu
If you're migrating from the original `tchu` library in cloud functions:
```python
# Old tchu library
from tchu import TchuClient
client = TchuClient()
client.publish('topic', data)

# New tchu-tchu (v2.2.27+)
from tchu_tchu.serverless_producer import ServerlessClient
client = ServerlessClient(broker_url=BROKER_URL)
client.publish('topic', data)
```

## [2.2.26] - 2025-11-05

### Added
- **NEW**: Extended `Celery` class that wraps standard `celery.Celery` with tchu-tchu integration
  - Import with `from tchu_tchu.django import Celery` for seamless Django integration
  - Provides `app.message_broker()` method for cleaner, more Pythonic API
  - **Parameter naming**: Uses `include` parameter (matches Celery's naming convention)
  - **Auto-discovery**: `include` parameter is optional
    - If not provided to `message_broker()`, uses Celery's `include` constructor parameter
    - No automatic path modifications - full module paths required
    - Example: `Celery("app", include=["app1.subscribers", "app2.subscribers"])`
  - Stores `include` from kwargs in `self.tchu_include` for easy access
  - Fully backward compatible - all standard Celery functionality preserved
  - More intuitive than standalone function approach
- Added comprehensive documentation in `EXTENDED_CELERY_USAGE.md`
- Updated `tchu_tchu.django.__init__.py` to export the extended `Celery` class

### Changed
- `message_broker()` method wraps `setup_celery_queue()` for better encapsulation
- Uses `include` parameter name to match Celery's API (not `subscriber_modules`)
- `include` parameter is optional - defaults to Celery's `include` from constructor
- README updated to show extended Celery class as the recommended approach
- Standalone `setup_celery_queue()` function remains available for backward compatibility

### Examples
```python
from tchu_tchu.django import Celery  # Extended class

# With explicit include modules
app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.message_broker(
    queue_name="my_queue",
    include=["app1.subscribers", "app2.subscribers"],
)

# With auto-discovery from Celery's include parameter
app = Celery("my_app", include=["app1.subscribers", "app2.subscribers"])
app.config_from_object("django.conf:settings", namespace="CELERY")
app.message_broker(queue_name="my_queue")  # Uses app1.subscribers, app2.subscribers
```

## [2.2.25] - 2025-11-04

### Fixed
- **CRITICAL**: Fixed `@celery.shared_task` tasks broadcasting to all services
  - Removed `task_default_exchange` setting that was causing regular tasks to use broadcast exchange
  - Regular @celery.shared_task tasks now use direct routing to service's own queue
  - Only tchu-tchu event dispatcher uses the broadcast topic exchange
  - Prevents tasks from one service being sent to workers of other services

### Changed
- `setup_celery_queue()` now only sets `task_default_queue` without changing default exchange
- Regular Celery tasks stay within their service, broadcast events go to all services

## [2.2.24] - 2025-11-04

### Fixed
- **CRITICAL**: Fixed `@celery.shared_task` tasks not being routed to any queue
  - Added `task_default_queue` setting to route all tasks (including regular Celery tasks) to tchu-tchu queue
  - Ensures `.delay()` and `@shared_task` work properly alongside `@subscribe` handlers
  - Previously, only tchu-tchu dispatcher tasks were routed, leaving regular tasks orphaned

### Changed
- `setup_celery_queue()` now sets `task_default_queue` to ensure all tasks go to the configured queue
- Both event-driven handlers (@subscribe) and async tasks (@shared_task) now work together

## [2.2.23] - 2025-11-04

### Changed
- Added explicit logging for `worker_prefetch_multiplier=1` setting to verify it's being applied
- Makes it easier to diagnose if the RPC reliability fix is active

## [2.2.22] - 2025-11-04

### Fixed
- **CRITICAL**: Fixed intermittent RPC call failures with `rpc://` result backend
  - Set `worker_prefetch_multiplier=1` to prevent workers from prefetching multiple tasks
  - Removed `acks_late=True` settings that are incompatible with RabbitMQ's `rpc://` result backend
  - This is the KEY fix: prefetch multiplier prevents race conditions when multiple workers handle RPC calls
  - Works with both `rpc://` (RabbitMQ) and Redis result backends

### Changed
- Simplified task configuration to work with all result backend types
- `setup_celery_queue()` now only sets `worker_prefetch_multiplier=1` (the critical fix)
- No migration required - just update tchu-tchu and restart services

### Root Cause
- Default Celery `worker_prefetch_multiplier=4` caused workers to prefetch multiple RPC tasks
- Multiple workers prefetching the same or overlapping tasks created race conditions with result storage
- With `rpc://` backend, temporary result queues had timing issues with prefetched tasks
- Setting prefetch to 1 ensures each worker processes one RPC call at a time (eliminates races)

## [2.2.21] - 2025-11-04 (Yanked - incompatible with rpc:// backend)

### Fixed
- Attempted fix for intermittent RPC failures but incompatible with `rpc://` result backend
- Use v2.2.22 instead

## [2.2.20] - 2025-11-04

### Fixed
- **CRITICAL**: Fixed `setup_celery_queue()` callback never executing, causing RPC handlers to not be registered
  - Added `worker_process_init` signal to import subscriber modules when worker starts
  - Added graceful exception handling for `AppRegistryNotReady` errors during Django initialization
  - Allows both Celery workers and web processes to initialize successfully without crashes
  - Fixes "No handlers found for routing key" errors for RPC calls

### Changed
- `setup_celery_queue()` now uses dual approach: immediate import (if Django ready) + `worker_process_init` signal
- Gracefully handles `AppRegistryNotReady` exceptions when called during Django app initialization
- No migration required - just update tchu-tchu and restart services

## [2.2.11] - 2025-10-28

### Fixed
- **CRITICAL**: Fixed broadcast events not being received due to incorrect RabbitMQ queue bindings
  - `get_subscribed_routing_keys()` was being called before handlers were registered
  - Resulted in empty routing key list and queues with exact-match-only bindings
  - RPC calls worked, but broadcast events failed silently

### Added
- New `celery_app` parameter to `get_subscribed_routing_keys()` to force immediate handler registration
- New `force_import` parameter (default: `True`) to control import behavior
- Improved documentation and examples in function docstring

### Changed
- `get_subscribed_routing_keys()` now calls `celery_app.loader.import_default_modules()` if `celery_app` is provided
- This ensures handlers are registered before queue configuration

### Migration Required
- **BREAKING**: Services must pass `celery_app` parameter: `get_subscribed_routing_keys(celery_app=app)`
- **CRITICAL**: Delete old queues from RabbitMQ to remove incorrect persistent bindings
- See [MIGRATION_2.2.11.md](./MIGRATION_2.2.11.md) for detailed upgrade instructions

## [2.2.10] - 2025-10-28 (Unreleased)

### Changed
- Enhanced error messages for RPC calls with no handlers
- Improved logging to distinguish between RPC and broadcast event routing issues

## [2.2.9] - 2025-10-28

### Added
- Initial stable release with RPC and broadcast event support
- Topic exchange-based routing with Celery
- `@subscribe` decorator for handler registration
- `CeleryProducer` for publishing events and making RPC calls
- `create_topic_dispatcher` for event dispatching

### Changed
- Migrated from Pika-based implementation to Celery-only implementation
- Unified RPC and broadcast events under single topic exchange

---

## Upgrade Guide

### From 2.2.9 to 2.2.11

This is a **critical bug fix release**. All services using broadcast events should upgrade immediately.

**Quick upgrade:**
```bash
# 1. Update library
pip install tchu-tchu==2.2.11

# 2. Update celery.py
# FROM: all_routing_keys = get_subscribed_routing_keys()
# TO:   all_routing_keys = get_subscribed_routing_keys(celery_app=app)

# 3. Delete old RabbitMQ queues
rabbitmqctl delete_queue your_queue_name

# 4. Restart services
docker-compose restart your_service
```

See [MIGRATION_2.2.11.md](./MIGRATION_2.2.11.md) for complete instructions.

---

## Version History

- **3.0.3** (2026-01-20): Fixed exchange declaration (was missing in 3.0.2)
- **3.0.2** (2026-01-19): Fixed Celery Beat DatabaseScheduler compatibility (deferred imports)
- **3.0.1** (2024-12-31): Backward compatibility fix for 2.x publishers
- **3.0.0** (2024-12-31): Major architecture change - all handlers as Celery tasks, async broadcast, native dedup
- **2.4.0** (2024-12-29): Initial celery_options support (superseded by 3.0.0)
- **2.3.1** (2024-12-15): Minor bugfixes
- **2.2.31** (2025-11-07): Logging improvements
- **2.2.30** (2025-11-07): ServerlessProducer serialization fix
- **2.2.26** (2025-11-05): Extended Celery class
- **2.2.11** (2025-10-28): Fixed broadcast event routing
- **2.2.9** (2025-10-28): Stable Celery-based release
- **2.2.0-2.2.8**: Development versions
- **2.1.x**: Pika-based implementation (deprecated)
- **2.0.x**: Initial release

