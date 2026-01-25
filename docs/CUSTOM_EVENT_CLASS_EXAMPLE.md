# Custom Event Classes with `@auto_publish` Decorator

The `@auto_publish` decorator now supports using your own custom `TchuEvent` classes for event serialization and publishing. This allows you to:

- Use DRF serializers for validation
- Add authorization context to events
- Transform model data before publishing
- Maintain consistency across manual and automatic event publishing
- **Define separate event classes for created, updated, and deleted events**

---

## ⚠️ Important: Serializers That Need Context

**If your serializers use `self.context`**, you need the `context_provider` parameter!

DRF serializers can access `self.context` for validation, authorization, or business logic. Common use cases:

```python
# Use case 1: Authorization
class MySerializer(serializers.Serializer):
    def validate(self, attrs):
        if self.context:
            attrs['user_id'] = self.context.get('user_id')
        return attrs

# Use case 2: Conditional validation
class MySerializer(serializers.Serializer):
    def validate_field(self, value):
        if self.context and self.context.get('is_admin'):
            return value  # Admins can set any value
        # Restrict non-admins
        return restricted_value
```

Without `context_provider`, `self.context` is None and your validation may fail!

```python
@auto_publish(
    event_classes={"created": MyEvent},
    context_provider=get_context  # ← Required if serializer uses self.context!
)
```

**See `CONTEXT_PROVIDER_GUIDE.md` for detailed patterns and examples.**

---

## Basic Usage

### Step 1: Define Your Custom Event Classes

Each event class defines its own **topic** and **serializers**:

```python
from tchu_tchu.events import TchuEvent
from rest_framework import serializers

class RiskAssessmentCreatedSerializer(serializers.Serializer):
    """Serializer for risk assessment created events."""
    id = serializers.IntegerField()
    company_id = serializers.IntegerField()
    status = serializers.CharField(max_length=50)
    risk_score = serializers.FloatField(required=False)
    # Metadata added by decorator
    _meta = serializers.DictField(required=False)
    # Authorization fields (optional)
    user = serializers.IntegerField(required=False)
    company = serializers.IntegerField(required=False)
    user_company = serializers.IntegerField(required=False)

class RiskAssessmentUpdatedSerializer(serializers.Serializer):
    """Serializer for risk assessment updated events."""
    id = serializers.IntegerField()
    company_id = serializers.IntegerField()
    status = serializers.CharField(max_length=50)
    risk_score = serializers.FloatField(required=False)
    _meta = serializers.DictField(required=False)

class RiskAssessmentCreatedEvent(TchuEvent):
    """Event published when a risk assessment is created."""
    
    class Meta:
        topic = "pulse.compliance.risk_assessment.created"
        request_serializer_class = RiskAssessmentCreatedSerializer

class RiskAssessmentUpdatedEvent(TchuEvent):
    """Event published when a risk assessment is updated."""
    
    class Meta:
        topic = "pulse.compliance.risk_assessment.updated"
        request_serializer_class = RiskAssessmentUpdatedSerializer
```

### Step 2: Use the Event Classes with `@auto_publish`

```python
from django.db import models
from tchu_tchu.django.decorators import auto_publish
from .events import RiskAssessmentCreatedEvent, RiskAssessmentUpdatedEvent

@auto_publish(
    include_fields=["id", "company_id", "status", "risk_score"],
    event_classes={
        "created": RiskAssessmentCreatedEvent,
        "updated": RiskAssessmentUpdatedEvent
    }
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
    risk_score = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

## How It Works

When a `RiskAssessment` model is saved or deleted:

1. **Data Extraction**: The decorator extracts model fields based on `include_fields`/`exclude_fields`
2. **Event Selection**: Selects the appropriate event class based on the action (created/updated/deleted)
3. **Event Instantiation**: Creates an instance of the selected event class (using its own topic from Meta)
4. **Serialization**: Calls `event_instance.serialize_request(data)` to validate the data through the event's DRF serializer
5. **Publishing**: Calls `event_instance.publish()` to send the validated event with the event's defined topic

## Advanced Examples

### Example 1: Full CRUD with Event Classes

```python
from tchu_tchu.django.decorators import auto_publish

class RiskAssessmentCreatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.created"
        request_serializer_class = RiskAssessmentCreatedSerializer

class RiskAssessmentUpdatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.updated"
        request_serializer_class = RiskAssessmentUpdatedSerializer

class RiskAssessmentDeletedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.deleted"
        request_serializer_class = RiskAssessmentDeletedSerializer

@auto_publish(
    include_fields=["id", "company_id", "status"],
    event_classes={
        "created": RiskAssessmentCreatedEvent,
        "updated": RiskAssessmentUpdatedEvent,
        "deleted": RiskAssessmentDeletedEvent
    }
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
```

### Example 2: Auto-inferring publish_on from event_classes

If you don't specify `publish_on`, it will be automatically inferred from the keys in `event_classes`:

```python
# This decorator will only publish on "created" and "updated"
# because those are the only keys in event_classes
@auto_publish(
    include_fields=["id", "company_id", "status"],
    event_classes={
        "created": RiskAssessmentCreatedEvent,
        "updated": RiskAssessmentUpdatedEvent
        # No "deleted" event class, so delete events won't be published
    }
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
```

### Example 3: With Context Provider for Authorization

If your event serializers use `EventAuthorizationSerializer` or need request context:

```python
# Define context provider
def provide_context(instance, event_type):
    """Extract context from model instance."""
    return {
        "user_id": getattr(instance, '_event_user_id', None),
        "company_id": instance.company_id,
    }

@auto_publish(
    include_fields=["id", "company_id", "status"],
    event_classes={
        "created": RiskAssessmentCreatedEvent,
        "updated": RiskAssessmentUpdatedEvent
    },
    context_provider=provide_context
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
    
    def set_event_context(self, user_id):
        """Store user_id for event publishing."""
        self._event_user_id = user_id
        return self

# In your view/service:
assessment = RiskAssessment(company_id=123, status="pending")
assessment.set_event_context(user_id=request.user.id)
assessment.save()  # Publishes with authorization context!
```

See `CONTEXT_PROVIDER_GUIDE.md` for detailed patterns and approaches.

### Example 4: Combining with Conditional Publishing

```python
def should_publish_risk_assessment(instance, event_type):
    """Only publish if risk score is high."""
    if event_type == "updated":
        return instance.risk_score is not None and instance.risk_score > 7.0
    return True  # Always publish on create/delete

@auto_publish(
    include_fields=["id", "company_id", "status", "risk_score"],
    event_classes={
        "created": RiskAssessmentCreatedEvent,
        "updated": RiskAssessmentUpdatedEvent
    },
    condition=should_publish_risk_assessment
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
    risk_score = models.FloatField(null=True, blank=True)
```

## Benefits of Using Custom Event Classes

1. **Validation**: Your event data is validated through DRF serializers before publishing
2. **Consistency**: Same serializers for manual and automatic publishing
3. **Type Safety**: Better IDE support and type checking
4. **Authorization**: Include authorization context (user, company, user_company) in events
5. **Transformation**: Transform model data before publishing (via serializer methods)
6. **Error Handling**: Validation errors are caught and logged appropriately

## Backward Compatibility

If you don't provide `event_classes`, the decorator works exactly as before with raw event publishing:

```python
@auto_publish(
    topic_prefix="pulse.compliance",
    include_fields=["id", "status"],
    publish_on=["created", "updated"]
)
class RiskAssessment(models.Model):
    # ... fields ...
    pass

# This still publishes raw dictionaries directly through TchuClient
# Topics will be: pulse.compliance.risk_assessment.created, pulse.compliance.risk_assessment.updated
```

## Topic Behavior

### With Event Classes (Recommended)

When using `event_classes`, each event class **defines its own topic** in the `Meta` class:

```python
class RiskAssessmentCreatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.created"  # This topic is used!
        request_serializer_class = RiskAssessmentCreatedSerializer

@auto_publish(
    event_classes={"created": RiskAssessmentCreatedEvent}
)
class RiskAssessment(models.Model):
    pass

# Published topic: "pulse.compliance.risk_assessment.created" (from event class)
```

### Without Event Classes (Legacy)

Without `event_classes`, the decorator generates topics from `topic_prefix`:

```python
@auto_publish(
    topic_prefix="pulse.compliance",
    publish_on=["created", "updated"]
)
class RiskAssessment(models.Model):
    pass

# Generated topics: 
# - pulse.compliance.risk_assessment.created
# - pulse.compliance.risk_assessment.updated
```

## Inspecting Configuration

You can inspect the auto-publish configuration at runtime:

```python
from tchu_tchu.django.decorators import get_auto_publish_config

config = get_auto_publish_config(RiskAssessment)
print(config['event_classes'])  # {'created': RiskAssessmentCreatedEvent, 'updated': RiskAssessmentUpdatedEvent}
print(config['base_topic'])     # pulse.compliance.risk_assessment (only used without event_classes)
print(config['publish_on'])     # ['created', 'updated']
print(config['include_fields']) # ['id', 'company_id', 'status']
```

## Common Patterns

### Pattern 1: Shared Event Classes for Manual and Automatic Publishing

```python
# Define serializer once
class OrderCreatedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    customer_id = serializers.IntegerField()
    total = serializers.DecimalField(max_digits=10, decimal_places=2)
    _meta = serializers.DictField(required=False)
    user = serializers.IntegerField(required=False)
    company = serializers.IntegerField(required=False)

# Define event classes
class OrderCreatedEvent(TchuEvent):
    class Meta:
        topic = "orders.created"
        request_serializer_class = OrderCreatedSerializer

class OrderNotificationEvent(TchuEvent):
    class Meta:
        topic = "orders.notification"
        request_serializer_class = OrderCreatedSerializer  # Reuse same serializer

# Use in decorator for automatic publishing
@auto_publish(
    include_fields=["id", "customer_id", "total"],
    event_classes={
        "created": OrderCreatedEvent
    }
)
class Order(models.Model):
    customer_id = models.IntegerField()
    total = models.DecimalField(max_digits=10, decimal_places=2)

# Also use manually when needed
def manual_order_notification(order_id, user_context):
    event = OrderNotificationEvent()
    event.serialize_request({
        'id': order_id,
        'user': user_context['user_id'],
        'company': user_context['company_id']
    })
    event.publish()
```

### Pattern 2: Exclude Sensitive Fields

```python
class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    username = serializers.CharField()
    _meta = serializers.DictField(required=False)
    # password is NOT included in serializer

class UserCreatedEvent(TchuEvent):
    class Meta:
        topic = "users.created"
        request_serializer_class = UserSerializer

class UserUpdatedEvent(TchuEvent):
    class Meta:
        topic = "users.updated"
        request_serializer_class = UserSerializer

@auto_publish(
    exclude_fields=["password", "password_hash", "secret_key"],
    event_classes={
        "created": UserCreatedEvent,
        "updated": UserUpdatedEvent
    }
)
class User(models.Model):
    username = models.CharField(max_length=150)
    email = models.EmailField()
    password = models.CharField(max_length=128)  # Excluded
    password_hash = models.CharField(max_length=256)  # Excluded
```

## Troubleshooting

### Validation Errors

If your event class serializer validation fails, the error will be logged:

```
ERROR: Failed to publish created event for RiskAssessment: 
       Failed to serialize request: DRF serializer validation failed: {'field_name': ['error message']}
```

**Solution**: Ensure your serializer fields match the data being extracted from the model. Remember:
- The decorator adds a `_meta` field to the data (include it in your serializer as `required=False`)
- Use `required=False` for any fields that might not always be present

### Invalid Event Type Keys

If you use invalid keys in `event_classes`:

```python
@auto_publish(
    event_classes={
        "new": MyEvent  # ERROR: Invalid key!
    }
)
```

**Solution**: Only use valid event types: `"created"`, `"updated"`, `"deleted"`

### Missing Fields

If fields aren't being published:

1. Check `include_fields` / `exclude_fields` parameters
2. Ensure fields exist on the model
3. Check that serializer accepts those fields (use `required=False` for optional fields)
4. Check that the `_meta` field is in your serializer with `required=False`

## Migration Guide

### Migrating Existing Decorators to Use Event Classes

**Before** (raw event publishing):
```python
@auto_publish(
    topic_prefix="pulse.compliance",
    include_fields=["id", "status", "company_id"],
    publish_on=["created", "updated"]
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
```

**After** (with event classes):
```python
# 1. Create serializers (one per event type or shared)
class RiskAssessmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    company_id = serializers.IntegerField()
    _meta = serializers.DictField(required=False)  # Always include this

# 2. Create event classes
class RiskAssessmentCreatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.created"
        request_serializer_class = RiskAssessmentSerializer

class RiskAssessmentUpdatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.updated"
        request_serializer_class = RiskAssessmentSerializer

# 3. Update decorator to use event_classes
@auto_publish(
    include_fields=["id", "status", "company_id"],
    event_classes={
        "created": RiskAssessmentCreatedEvent,
        "updated": RiskAssessmentUpdatedEvent
    }
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
```

**Benefits after migration**:
- ✅ Data validation before publishing
- ✅ Consistent serialization for manual and automatic publishing
- ✅ Better error messages
- ✅ Type safety
- ✅ Full control over topics per event type

## Testing

### Testing Models with `@auto_publish` and Custom Event Classes

```python
import pytest
from django.test import TestCase
from unittest.mock import patch, MagicMock

class TestRiskAssessmentPublishing(TestCase):
    @patch('tchu_tchu.events.TchuEvent.publish')
    def test_creates_and_publishes_with_event_class(self, mock_publish):
        """Test that creating a model publishes through the event class."""
        # Create instance
        assessment = RiskAssessment.objects.create(
            company_id=123,
            status="pending",
            risk_score=8.5
        )
        
        # Verify publish was called
        mock_publish.assert_called_once()
        
    @patch('tchu_tchu.events.TchuEvent.publish')
    def test_different_events_use_different_classes(self, mock_publish):
        """Test that created and updated use different event classes."""
        # Create
        assessment = RiskAssessment.objects.create(
            company_id=123,
            status="pending"
        )
        assert mock_publish.call_count == 1
        
        # Update
        assessment.status = "completed"
        assessment.save()
        assert mock_publish.call_count == 2
```

## Key Takeaways

1. **One event class per action**: Define separate event classes for `created`, `updated`, and `deleted`
2. **Each event defines its own topic**: Event classes specify their topics in the `Meta` class
3. **Each event defines its own serializer**: Event classes specify their serializers in the `Meta` class
4. **Auto-infer publish_on**: If you provide `event_classes`, `publish_on` is automatically inferred from the keys
5. **Backward compatible**: Without `event_classes`, the decorator works as before with raw event publishing

## Additional Resources

- See `tchu_tchu/events.py` for full `TchuEvent` API
- See `tchu_tchu/django/decorators.py` for decorator implementation
- See `tests/test_*.py` for more examples

