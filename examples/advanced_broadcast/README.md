# Advanced Broadcast Example - Versioning & Backward Compatibility

This example demonstrates how event versioning and backward compatibility work in CelerySalt.

## Scenario

- **v1 Event Schema**: `user_id`, `email`, `company_id`
- **v2 Event Schema**: `user_id`, `email`, `company_id`, `phone_number` (new field)
- **Publisher**: Publishes v2 events
- **Subscribers**: Both v1 and v2 handlers exist

## Key Concepts Demonstrated

### 1. Backward Compatibility

When a publisher upgrades to v2, existing v1 handlers can still process v2 events:

- ✅ v1 handlers receive v2 events (backward compatible)
- ⚠️ Worker logs show warnings: "Subscriber is on an older version"
- ✅ v1 handlers validate against v1 schema (new fields are ignored)
- ✅ v2 handlers validate against v2 schema (all fields available)

### 2. Version Matching

- **v1 handlers** (`version="v1"`): Receive v1 and v2 events (backward compatible)
- **v2 handlers** (`version="v2"`): Receive only v2 events (normal operation)

### 3. Schema Validation

Each handler validates against **its subscribed schema version**, not the message version:

- v1 handler + v2 message → validates against v1 schema → `phone_number` ignored
- v2 handler + v2 message → validates against v2 schema → `phone_number` available

## Running the Example

### Prerequisites

1. **RabbitMQ** running on `localhost:5672`
2. **Python 3.8+** with `celery-salt` installed

### Step 1: Start the Subscriber (Worker)

In one terminal:

```bash
cd examples/advanced_broadcast
celery -A subscriber worker --loglevel=info
```

You should see:
- Registered handlers (v1 and v2)
- Queue bindings configured

### Step 2: Publish Events

In another terminal:

```bash
cd examples/advanced_broadcast
python publisher.py
```

### Step 3: Observe the Results

Watch the worker terminal. You should see:

1. **Warnings for v1 handlers**:
   ```
   WARNING: Handler 'send_welcome_email_v1' subscribed to v1 is processing v2 message...
   Subscriber is on an older version. Consider upgrading subscriber to v2.
   ```

2. **v1 handlers processing events**:
   ```
   📧 [V1 HANDLER] Sending welcome email to alice@example.com (user_id=1001)
   ⚠️  This is a v1 handler receiving a v2 event (backward compatible)
   ℹ️  phone_number field is not available in v1 schema
   ```

3. **v2 handlers processing events**:
   ```
   📧 [V2 HANDLER] Sending welcome email to alice@example.com (user_id=1001)
   📱 [V2 HANDLER] Sending SMS to +1-555-0101
   ✅ This is a v2 handler receiving a v2 event (normal operation)
   ```

## Expected Output

### Publisher Output

```
📤 Publishing v2 events (demonstrating backward compatibility)...

======================================================================
Event Versioning: v2 Publisher
======================================================================

📋 Event Schema (v2):
   - user_id: int
   - email: str
   - company_id: int
   - phone_number: str  ← NEW in v2

🎯 Expected Behavior:
   - v1 handlers: Will receive v2 events (backward compatible)
     → Validates against v1 schema (ignores phone_number)
     → Logs WARNING: 'Subscriber is on an older version'
   - v2 handlers: Will receive v2 events (normal operation)
     → Validates against v2 schema (includes phone_number)

✓ Published v2 event: user_id=1001, email=alice@example.com, phone=+1-555-0101, message_id=...
✓ Published v2 event: user_id=1002, email=bob@example.com, phone=+1-555-0102, message_id=...
✓ Published v2 event: user_id=1003, email=charlie@example.com, phone=+1-555-0103, message_id=...
```

### Subscriber Output (Worker Logs)

```
[INFO] Handler 'send_welcome_email_v1' subscribed to v1 is processing v2 message for topic 'user.signup.completed'. Subscriber is on an older version. Consider upgrading subscriber to v2.
📧 [V1 HANDLER] Sending welcome email to alice@example.com (user_id=1001)
   ⚠️  This is a v1 handler receiving a v2 event (backward compatible)
   ℹ️  phone_number field is not available in v1 schema

[INFO] Handler 'update_user_analytics_v1' subscribed to v1 is processing v2 message for topic 'user.signup.completed'. Subscriber is on an older version. Consider upgrading subscriber to v2.
📊 [V1 HANDLER] Updating analytics for user 1001
   ⚠️  This is a v1 handler receiving a v2 event (backward compatible)
   ℹ️  phone_number field is not available in v1 schema

📧 [V2 HANDLER] Sending welcome email to alice@example.com (user_id=1001)
📱 [V2 HANDLER] Sending SMS to +1-555-0101
   ✅ This is a v2 handler receiving a v2 event (normal operation)

📊 [V2 HANDLER] Updating analytics for user 1001
   📱 Phone number: +1-555-0101
   ✅ This is a v2 handler receiving a v2 event (normal operation)

📱 [V2 HANDLER] Verifying phone number +1-555-0101 for user 1001
   ✅ This is a v2 handler receiving a v2 event (normal operation)
   ✅ phone_number field is available in v2 schema
```

## Key Takeaways

1. **Backward Compatibility**: Older handlers can process newer events
2. **Version Warnings**: Workers log warnings when older handlers receive newer events
3. **Schema Validation**: Each handler validates against its subscribed schema version
4. **Gradual Migration**: You can upgrade publishers before upgrading all subscribers
5. **Publisher Control**: Publishers decide when to sunset old versions by no longer publishing them

## Migration Path

1. **Phase 1**: Publisher upgrades to v2, publishes v2 events
2. **Phase 2**: v1 handlers continue working (backward compatible, with warnings)
3. **Phase 3**: Gradually upgrade v1 handlers to v2
4. **Phase 4**: Publisher stops publishing v1 events (sunset v1)

This allows zero-downtime upgrades and gradual migration of subscribers.
