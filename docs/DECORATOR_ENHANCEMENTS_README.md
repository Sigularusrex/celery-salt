# @auto_publish Decorator Enhancements

## Overview

The `@auto_publish` decorator has been enhanced to support custom `TchuEvent` classes with full serialization, validation, and request context support.

## What's New

### 1. Event Classes Per Action
Define separate event classes for `created`, `updated`, and `deleted` events:

```python
@auto_publish(
    event_classes={
        "created": RiskAssessmentCreatedEvent,
        "updated": RiskAssessmentUpdatedEvent,
        "deleted": RiskAssessmentDeletedEvent
    }
)
class RiskAssessment(models.Model):
    pass
```

### 2. Event Classes Define Their Own Topics & Serializers
Each event class specifies its own topic and serializers:

```python
class RiskAssessmentCreatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.created"
        request_serializer_class = RiskAssessmentCreatedSerializer
```

### 3. Context Provider for Authorization
Pass request context to event serializers:

```python
def provide_context(instance, event_type):
    return {
        "user_id": getattr(instance, '_event_user_id', None),
        "company_id": instance.company_id,
    }

@auto_publish(
    event_classes={"created": MyEvent},
    context_provider=provide_context
)
```

## Documentation

| Document | Description |
|----------|-------------|
| **[DECORATOR_CHANGES_SUMMARY.md](DECORATOR_CHANGES_SUMMARY.md)** | Quick summary of all changes and new features |
| **[CUSTOM_EVENT_CLASS_EXAMPLE.md](CUSTOM_EVENT_CLASS_EXAMPLE.md)** | Comprehensive examples of using event classes |
| **[CONTEXT_PROVIDER_GUIDE.md](CONTEXT_PROVIDER_GUIDE.md)** | Detailed guide on passing request context |

## Quick Start

### Basic Usage (Backward Compatible)

```python
@auto_publish(
    topic_prefix="pulse.compliance",
    include_fields=["id", "status"],
    publish_on=["created", "updated"]
)
class RiskAssessment(models.Model):
    status = models.CharField(max_length=50)
```

### With Event Classes (Recommended)

```python
# 1. Define your event classes
class RiskAssessmentCreatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.created"
        request_serializer_class = RiskAssessmentSerializer

# 2. Apply decorator
@auto_publish(
    include_fields=["id", "status"],
    event_classes={"created": RiskAssessmentCreatedEvent}
)
class RiskAssessment(models.Model):
    status = models.CharField(max_length=50)
```

### With Context Provider (for serializers using self.context)

**⚠️ REQUIRED if your serializers use `self.context`**

```python
# 1. Define context provider
def provide_context(instance, event_type):
    """Extract any context your serializer needs."""
    return {
        "user_id": getattr(instance, '_event_user_id', None),
        "is_admin": getattr(instance, '_is_admin', False),
        "tenant_id": instance.tenant_id,
        # ... any other context your serializer needs
    }

# 2. Apply decorator with context provider
@auto_publish(
    event_classes={"created": MyCreatedEvent},
    context_provider=provide_context  # ← Required if serializer uses self.context!
)
class MyModel(models.Model):
    tenant_id = models.IntegerField()
    
    def set_event_context(self, user_id, is_admin=False):
        """Store context for event publishing."""
        self._event_user_id = user_id
        self._is_admin = is_admin
        return self

# 3. Use in views
item = MyModel(tenant_id=123)
item.set_event_context(user_id=request.user.id, is_admin=request.user.is_staff)
item.save()  # Publishes with context!
```

**Why?** DRF serializers can access `self.context` for validation/authorization. Without `context_provider`, `self.context` is None. See `CONTEXT_PROVIDER_GUIDE.md` for patterns.

## Key Benefits

✅ **Type Safety**: Better IDE support and type checking  
✅ **Validation**: DRF serializer validation before publishing  
✅ **Flexibility**: Different topics and serializers per action  
✅ **Authorization**: Pass request context to serializers  
✅ **Consistency**: Same event classes for manual and automatic publishing  
✅ **Backward Compatible**: Existing decorators continue to work  

## API Reference

```python
@auto_publish(
    # Field selection
    include_fields: Optional[List[str]] = None,
    exclude_fields: Optional[List[str]] = None,
    
    # Event configuration
    publish_on: Optional[List[str]] = None,        # Auto-inferred from event_classes
    event_classes: Optional[Dict[str, Type]] = None,
    
    # Context & authorization
    context_provider: Optional[Callable] = None,
    
    # Conditional publishing
    condition: Optional[Callable] = None,
    
    # Legacy options (without event_classes)
    topic_prefix: Optional[str] = None,
    client: Optional[TchuClient] = None,
)
```

## Migration Checklist

- [ ] Read `DECORATOR_CHANGES_SUMMARY.md` for overview
- [ ] Define event classes for your models (see `CUSTOM_EVENT_CLASS_EXAMPLE.md`)
- [ ] Add DRF serializers for each event type
- [ ] Add `event_classes` parameter to decorator
- [ ] (Optional) Add `context_provider` if using `EventAuthorizationSerializer`
- [ ] Test event publishing
- [ ] Remove `topic_prefix` (if using event_classes)

## Common Patterns

### Pattern 1: Simple CRUD Events

```python
@auto_publish(
    event_classes={
        "created": ModelCreatedEvent,
        "updated": ModelUpdatedEvent,
        "deleted": ModelDeletedEvent
    }
)
```

### Pattern 2: Selective Publishing

```python
@auto_publish(
    event_classes={
        "created": ModelCreatedEvent,
        # Only publish created events
    }
)
```

### Pattern 3: With Authorization

```python
def provide_auth_context(instance, event_type):
    return {
        "user_id": instance._event_user_id,
        "company_id": instance.company_id
    }

@auto_publish(
    event_classes={"created": ModelCreatedEvent},
    context_provider=provide_auth_context
)
```

### Pattern 4: Conditional Publishing

```python
def should_publish(instance, event_type):
    if event_type == "updated":
        return instance.status == "completed"
    return True

@auto_publish(
    event_classes={"updated": ModelUpdatedEvent},
    condition=should_publish
)
```

## Troubleshooting

### "DRF serializer validation failed"
- Ensure serializer fields match model fields in `include_fields`
- Add `_meta = serializers.DictField(required=False)` to serializers
- Use `required=False` for optional fields

### "Context provider failed"
- Context provider errors are logged but don't stop publishing
- Check logs for details
- Ensure context provider returns a dict

### "Invalid event types in event_classes"
- Only use: `"created"`, `"updated"`, `"deleted"`

## Support

For questions or issues:
1. Check the documentation files listed above
2. Review the decorator source: `tchu_tchu/django/decorators.py`
3. Review the event class source: `tchu_tchu/events.py`

## Version

These enhancements are available in tchu-tchu 2.2.32+

