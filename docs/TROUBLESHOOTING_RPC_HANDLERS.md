# Troubleshooting: No Handlers Found for RPC Routing Key

## Problem Statement

**Error Message:**
```
Failed to list documents: RPC call failed: No handlers found for routing key 'rpc.cs_pulse.documents.document.list'
```

**Symptoms:**
- ✅ Works fine locally
- ❌ Fails on GCP with "No handlers found"
- RPC calls fail while broadcast events may work

**Root Cause:**
The service that should handle this RPC call doesn't have a handler registered in the GCP environment. This is typically caused by:
1. Handler module not being imported/autodiscovered
2. Service not running on GCP
3. Incorrect queue bindings
4. Import errors preventing handler registration

---

## Quick Diagnostic Checklist

Run through this checklist to identify the issue:

- [ ] **1. Is the handling service running on GCP?**
- [ ] **2. Does the handler exist in the codebase?**
- [ ] **3. Is the handler module being autodiscovered?**
- [ ] **4. Is the service using tchu-tchu v2.2.11+?**
- [ ] **5. Are queue bindings correct in RabbitMQ?**
- [ ] **6. Are there any import errors in the service logs?**

---

## Step-by-Step Debugging

### Step 1: Identify Which Service Should Handle This

The routing key pattern is: `rpc.<service_name>.<resource>.<action>`

For example:
- `rpc.cs_pulse.documents.document.list` → **cs_pulse** service
- `rpc.data_room.documents.list` → **data_room** service
- `rpc.scranton.orders.get` → **scranton** service

**Your routing key:** `___________________________`  
**Should be handled by:** `___________________________`

### Step 2: Verify the Handler Exists

**Location to check:**
```
<service_name>/subscribers/<resource>_subscriber.py
```

**Example:**
```python
# cs_pulse/subscribers/document_subscriber.py

from tchu_tchu import subscribe
import logging

logger = logging.getLogger(__name__)

@subscribe('rpc.cs_pulse.documents.document.list')
def handle_document_list(data):
    """Handle RPC request to list documents."""
    logger.info(f"Handling document list request: {data}")
    
    # Your implementation here
    company_id = data.get('company_id')
    documents = Document.objects.filter(company_id=company_id)
    
    # IMPORTANT: RPC handlers MUST return a value
    return {
        "documents": [doc.to_dict() for doc in documents],
        "count": len(documents)
    }
```

**Check:**
- [ ] Handler function exists
- [ ] `@subscribe('correct.routing.key')` decorator is present
- [ ] Handler returns a value (not `None`)
- [ ] No syntax errors in the file

### Step 3: Verify Handler Module is Being Imported

The most common issue: **the module isn't being autodiscovered**.

**Check your service's `celery.py`:**

```python
# <service_name>/celery.py

from celery import Celery
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys

app = Celery("my_service")

# ✅ CRITICAL: This must include ALL packages with @subscribe decorators
app.autodiscover_tasks([
    "my_service.subscribers",  # ← Does this exist?
    "my_service.consumers",     # ← Any other packages with handlers?
    # Add all packages that contain @subscribe decorators
])

# ✅ IMPORTANT: Pass celery_app to force immediate handler registration (v2.2.11+)
all_routing_keys = get_subscribed_routing_keys(celery_app=app)

print(f"🔍 Registered routing keys: {all_routing_keys}")  # ← Add this for debugging

# Configure queues
tchu_exchange = Exchange("tchu_events", type="topic", durable=True)
all_bindings = [binding(tchu_exchange, routing_key=key) for key in all_routing_keys]

app.conf.task_queues = (
    Queue(
        "my_service_queue",
        exchange=tchu_exchange,
        bindings=all_bindings,
        durable=True,
        auto_delete=False,
    ),
)

app.conf.task_routes = {
    "tchu_tchu.dispatch_event": {"queue": "my_service_queue"},
}

# Create dispatcher
dispatcher = create_topic_dispatcher(app)
```

**Common mistakes:**

❌ **Wrong package name:**
```python
app.autodiscover_tasks(["subscribers"])  # Missing service prefix
```

✅ **Correct:**
```python
app.autodiscover_tasks(["my_service.subscribers"])  # Full module path
```

❌ **Missing celery_app parameter:**
```python
all_routing_keys = get_subscribed_routing_keys()  # Handlers not registered yet!
```

✅ **Correct (v2.2.11+):**
```python
all_routing_keys = get_subscribed_routing_keys(celery_app=app)  # Forces import
```

### Step 4: Check Service Logs on GCP

**Look for handler registration logs:**

```bash
# Kubernetes
kubectl logs <pod-name> | grep -i "registered handler"

# Docker Compose
docker-compose logs <service-name> | grep -i "registered handler"

# GCP Cloud Run
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=<service-name>" --limit 100 | grep -i "registered handler"
```

**What to look for:**

✅ **Success - Handler registered:**
```
INFO:tchu_tchu.registry:Registered handler 'handle_document_list' for routing key 'rpc.cs_pulse.documents.document.list'
```

❌ **Problem - Handler not found:**
```
# No output means handler wasn't registered
```

❌ **Problem - Import error:**
```
ERROR: Cannot import module 'cs_pulse.subscribers.document_subscriber'
ModuleNotFoundError: No module named 'something'
```

### Step 5: Verify Queue Bindings in RabbitMQ

**Connect to RabbitMQ on GCP:**

```bash
# Kubernetes
kubectl exec -it <rabbitmq-pod> -- rabbitmqctl list_bindings | grep "<service_queue>"

# Docker
docker exec -it <rabbitmq-container> rabbitmqctl list_bindings | grep "<service_queue>"

# Or use RabbitMQ Management UI
# https://<rabbitmq-host>:15672 → Queues → <service_queue> → Bindings
```

**Expected output:**
```
tchu_events  exchange  cs_pulse_queue  queue  rpc.cs_pulse.documents.document.list  []
tchu_events  exchange  cs_pulse_queue  queue  rpc.cs_pulse.users.validate  []
```

**If bindings are missing:**
1. Handlers aren't being registered (see Step 3)
2. Service hasn't restarted since updating code
3. Old queues exist with stale bindings (see Step 6)

### Step 6: Delete Old Queues (If Necessary)

If you recently updated to tchu-tchu v2.2.11 or changed handler routing keys:

```bash
# Connect to RabbitMQ
kubectl exec -it <rabbitmq-pod> -- bash
# or
docker exec -it <rabbitmq-container> bash

# Delete the queue
rabbitmqctl delete_queue <service_queue_name>

# Exit and restart the service
exit
kubectl rollout restart deployment/<service-name>
# or
docker-compose restart <service-name>
```

The queue will be recreated with correct bindings on service startup.

### Step 7: Add Debug Logging

**Temporarily add this to your handler module:**

```python
# At the TOP of your subscriber file (module level)
import logging
logger = logging.getLogger(__name__)

# This executes when the module is imported
logger.info("=" * 80)
logger.info(f"🚀 MODULE LOADED: {__name__}")
logger.info("=" * 80)

@subscribe('rpc.cs_pulse.documents.document.list')
def handle_document_list(data):
    logger.info("=" * 80)
    logger.info(f"📋 HANDLER CALLED: handle_document_list")
    logger.info(f"📦 DATA RECEIVED: {data}")
    logger.info("=" * 80)
    
    # Your implementation
    result = {"documents": [...]}
    
    logger.info(f"✅ RETURNING RESULT: {result}")
    return result
```

**Deploy and check logs:**

1. **Look for "MODULE LOADED"** → Confirms module is imported
2. **Look for "HANDLER CALLED"** → Confirms handler is executed
3. **If neither appears** → Module isn't being imported (go back to Step 3)

### Step 8: Test Handler Registration Directly

**Add this temporary endpoint to your service:**

```python
# In your service's views or a management command

from tchu_tchu import get_registry

def debug_handlers(request):
    """Debug endpoint to check registered handlers."""
    registry = get_registry()
    
    all_handlers = {}
    for routing_key in registry.get_all_routing_keys_and_patterns():
        handlers = registry.get_handlers(routing_key)
        all_handlers[routing_key] = [
            {
                "name": h["name"],
                "handler_id": h["id"],
                "function": str(h["function"])
            }
            for h in handlers
        ]
    
    return JsonResponse({
        "total_routing_keys": len(all_handlers),
        "handlers": all_handlers
    })
```

**Call this endpoint on GCP:**
```bash
curl https://<your-service-gcp-url>/debug/handlers
```

**Look for your routing key:**
```json
{
  "total_routing_keys": 5,
  "handlers": {
    "rpc.cs_pulse.documents.document.list": [
      {
        "name": "handle_document_list",
        "handler_id": "cs_pulse.subscribers.document_subscriber.handle_document_list",
        "function": "<function handle_document_list at 0x...>"
      }
    ]
  }
}
```

If your routing key is **missing** from this output, the handler isn't registered.

---

## Common Issues & Solutions

### Issue 1: Module Not in autodiscover_tasks

**Problem:**
```python
app.autodiscover_tasks(["my_service.api"])  # Missing .subscribers
```

**Solution:**
```python
app.autodiscover_tasks([
    "my_service.api",
    "my_service.subscribers",  # ← Add this
])
```

### Issue 2: Import Error Due to Missing Dependency

**Problem:**
```
ModuleNotFoundError: No module named 'some_package'
```

**Solution:**
Check your `requirements.txt` or `pyproject.toml` includes all dependencies, especially:
- Database packages (psycopg2, mysqlclient)
- Django apps that the handler imports
- Any custom internal packages

### Issue 3: Circular Import

**Problem:**
```
ImportError: cannot import name 'X' from partially initialized module 'Y'
```

**Solution:**
Move imports inside the handler function:

```python
@subscribe('rpc.cs_pulse.documents.document.list')
def handle_document_list(data):
    # Import here instead of at module level
    from cs_pulse.models import Document
    from cs_pulse.services.document_service import DocumentService
    
    # Your implementation
    return DocumentService.list_documents(data)
```

### Issue 4: Wrong Environment Configuration

**Problem:**
Service connects to different RabbitMQ instance on GCP than locally.

**Solution:**
Check environment variables:

```bash
# In GCP environment
echo $CELERY_BROKER_URL
echo $CELERY_RESULT_BACKEND

# Should point to the shared RabbitMQ instance
# Example: amqp://guest:guest@rabbitmq:5672//
```

### Issue 5: Service Not Running

**Problem:**
Service crashed or isn't deployed to GCP.

**Solution:**
```bash
# Check service status
kubectl get pods | grep <service-name>
docker-compose ps

# Check recent restarts/crashes
kubectl describe pod <pod-name>
docker-compose logs <service-name> --tail=100
```

### Issue 6: Multiple Services Handling Same Routing Key

**Problem:**
Two services both have handlers for the same RPC routing key (this causes conflicts).

**Solution:**
RPC handlers should be unique. Only ONE service should handle a specific RPC routing key.

```python
# ❌ BAD: Both services define this handler
# Service A
@subscribe('rpc.documents.list')
def handle_list_a(data): ...

# Service B  
@subscribe('rpc.documents.list')
def handle_list_b(data): ...

# ✅ GOOD: Use namespaced routing keys
# Service A
@subscribe('rpc.service_a.documents.list')
def handle_list_a(data): ...

# Service B
@subscribe('rpc.service_b.documents.list')
def handle_list_b(data): ...
```

---

## Environment Differences: Local vs GCP

### Why It Works Locally But Not on GCP

| Aspect | Local | GCP | Potential Issue |
|--------|-------|-----|----------------|
| **Dependencies** | All installed | Some missing | Import errors |
| **Environment vars** | `.env` file | Cloud config | Wrong RabbitMQ URL |
| **Code version** | Latest | Older deploy | Handler not deployed yet |
| **RabbitMQ** | Fresh queues | Stale queues | Old bindings |
| **Logs visible** | Terminal | Need to check | Errors missed |
| **Auto-reload** | Yes (runserver) | No | Need restart |

**Action:** Ensure GCP environment matches your local setup.

---

## Verification Checklist

After making changes, verify:

### ✅ Handler is Registered
```bash
# Check service logs for:
grep "Registered handler.*rpc.cs_pulse.documents.document.list" <logs>
```

### ✅ Queue Bindings are Correct
```bash
# Check RabbitMQ:
rabbitmqctl list_bindings | grep "rpc.cs_pulse.documents.document.list"
```

### ✅ Service Can Be Called
```python
# Test from another service:
from tchu_tchu import TchuClient

client = TchuClient()
try:
    result = client.call('rpc.cs_pulse.documents.document.list', {'company_id': 67})
    print(f"✅ Success: {result}")
except Exception as e:
    print(f"❌ Failed: {e}")
```

### ✅ Logs Show Handler Execution
```bash
# After making a test call, check logs for:
grep "Handling document list request" <service-logs>
```

---

## Still Having Issues?

### Gather This Information:

1. **Service name:** `___________________________`
2. **Routing key:** `___________________________`
3. **Handler file path:** `___________________________`
4. **Celery config file path:** `___________________________`
5. **Service logs (last 100 lines):**
   ```bash
   kubectl logs <pod> --tail=100 > service_logs.txt
   ```
6. **RabbitMQ bindings:**
   ```bash
   rabbitmqctl list_bindings | grep <queue_name> > rabbitmq_bindings.txt
   ```
7. **Output of debug endpoint (Step 8):** `___________________________`

### Quick Test Commands

```bash
# 1. Check if service is running
kubectl get pods | grep <service-name>

# 2. Check service logs for errors
kubectl logs <pod-name> | grep -i error

# 3. Check if handler is registered
kubectl logs <pod-name> | grep "Registered handler"

# 4. Check RabbitMQ bindings
kubectl exec -it <rabbitmq-pod> -- rabbitmqctl list_bindings | grep <routing-key>

# 5. Restart service
kubectl rollout restart deployment/<service-name>

# 6. Test RPC call
# (Use your service's test suite or Postman)
```

---

## Related Documentation

- [tchu-tchu Migration Guide v2.2.11](./MIGRATION_2.2.11.md) - Critical fixes for handler registration
- [tchu-tchu README](./README.md) - Full API documentation
- [RabbitMQ Topic Exchange](https://www.rabbitmq.com/tutorials/tutorial-five-python.html) - Understanding routing keys

---

## Prevention: Best Practices

### 1. Always Use Namespaced RPC Routing Keys
```python
# ✅ Good
@subscribe('rpc.cs_pulse.documents.document.list')

# ❌ Bad (conflicts possible)
@subscribe('rpc.documents.list')
```

### 2. Log Handler Registration
```python
# Add to celery.py
all_routing_keys = get_subscribed_routing_keys(celery_app=app)
logger.info(f"📋 Registered {len(all_routing_keys)} routing keys: {all_routing_keys}")
```

### 3. Add Health Check Endpoint
```python
# Verify handlers are registered
@app.route('/health')
def health():
    from tchu_tchu import get_registry
    handler_count = get_registry().get_handler_count()
    return {
        "status": "healthy",
        "handlers_registered": handler_count
    }
```

### 4. Test RPC Handlers in CI/CD
```python
# Add to test suite
def test_rpc_handler_registered():
    from tchu_tchu import get_registry
    handlers = get_registry().get_handlers('rpc.cs_pulse.documents.document.list')
    assert len(handlers) > 0, "Handler not registered!"
```

### 5. Use Consistent Naming Convention
```
Pattern: rpc.<service>.<resource>.<action>

Examples:
- rpc.data_room.documents.list
- rpc.data_room.documents.get
- rpc.scranton.orders.create
- rpc.pulse.risk_assessments.calculate
```

---

**Last Updated:** 2025-11-03  
**tchu-tchu Version:** 2.2.11+

