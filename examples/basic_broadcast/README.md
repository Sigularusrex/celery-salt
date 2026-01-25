# Basic Broadcast Example

This example demonstrates the **broadcast (pub/sub)** pattern using CelerySalt.

## What This Example Shows

- How to define event schemas with `@event`
- How to publish broadcast events (fire-and-forget)
- How to subscribe to events with `@subscribe`
- Multiple subscribers can handle the same event

## Architecture

```
Publisher → RabbitMQ Exchange → Multiple Subscribers
```

When you publish a `user.signup.completed` event, all three subscribers will receive it:
1. `send_welcome_email` - Sends welcome email
2. `update_user_analytics` - Updates analytics
3. `notify_admin` - Notifies admin

## Prerequisites

1. **Start infrastructure services** (RabbitMQ)
   
   **Option A: Using Docker Compose (Recommended)**
   ```bash
   cd examples
   docker-compose up -d rabbitmq
   ```
   
   **Option B: Manual Docker**
   ```bash
   docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
   ```

2. **Install dependencies**
   ```bash
   pip install celery celerysalt kombu
   ```

## Running the Example

### Terminal 1: Start the Subscriber (Worker)

```bash
cd examples/basic_broadcast
celery -A subscriber worker --loglevel=info
```

You should see:
```
[tasks]
  . celerysalt.dispatch_event
  . celerysalt.user.signup.completed.send_welcome_email
  . celerysalt.user.signup.completed.update_user_analytics
  . celerysalt.user.signup.completed.notify_admin
```

### Terminal 2: Run the Publisher

```bash
cd examples/basic_broadcast
python publisher.py
```

You should see:
```
📤 Publishing broadcast events...

✓ Published event: user_id=123, message_id=...
✓ Published event: user_id=124, message_id=...
✓ Published event: user_id=125, message_id=...

✅ All events published!
```

### Check Terminal 1 (Worker)

You should see all three handlers processing each event:
```
📧 Sending welcome email to alice@example.com (user_id=123)
📊 Updating analytics for user 123 from web
🔔 Admin notification: New user alice@example.com signed up via web
```

## Key Concepts

### Event Schema Definition

```python
@event("user.signup.completed")
class UserSignupCompleted:
    user_id: int
    email: str
    company_id: int
    signup_source: str = "web"
```

### Publishing Events

```python
message_id = UserSignupCompleted.publish(
    user_id=123,
    email="alice@example.com",
    company_id=1,
    signup_source="web"
)
```

### Subscribing to Events

```python
@subscribe("user.signup.completed")
def send_welcome_email(data: UserSignupCompleted):
    # Handler logic here
    pass
```

## Next Steps

- Try adding more subscribers
- Experiment with wildcard patterns: `@subscribe("user.*")`
- Add error handling and retries
- See the RPC example for request/response patterns
