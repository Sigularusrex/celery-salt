# Decorator Enhancement Summary

## What Changed

The `@auto_publish` decorator now supports using custom `TchuEvent` classes through the `event_classes` parameter.

## Key Features

### 1. One Event Class Per Action

Instead of a single event class for all actions, you can now define separate event classes for each action type:

```python
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

### 2. Event Classes Define Their Own Topics

Each event class specifies its own topic in the `Meta` class:

```python
class RiskAssessmentCreatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.created"  # Custom topic!
        request_serializer_class = RiskAssessmentCreatedSerializer
```

The decorator **respects** the event class's topic instead of overriding it.

### 3. Event Classes Define Their Own Serializers

Each event class specifies its own serializer, allowing different validation per action:

```python
class RiskAssessmentCreatedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    company_id = serializers.IntegerField()
    status = serializers.CharField()
    _meta = serializers.DictField(required=False)
    # ... can include different fields than updated serializer

class RiskAssessmentCreatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.created"
        request_serializer_class = RiskAssessmentCreatedSerializer
```

### 4. Auto-Infer `publish_on`

If you provide `event_classes`, the `publish_on` parameter is automatically inferred:

```python
@auto_publish(
    event_classes={
        "created": MyCreatedEvent,
        "updated": MyUpdatedEvent
        # Only these two will be published (no deleted)
    }
)
```

### 5. Context Provider for Authorization

Pass request context to event serializers (e.g., for EventAuthorizationSerializer):

```python
def provide_context(instance, event_type):
    return {
        "user_id": getattr(instance, '_event_user_id', None),
        "company_id": instance.company_id,
    }

@auto_publish(
    event_classes={"created": MyCreatedEvent},
    context_provider=provide_context  # Pass context to serializers!
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    
    def set_event_context(self, user_id):
        self._event_user_id = user_id
        return self
```

See `CONTEXT_PROVIDER_GUIDE.md` for detailed patterns.

### 6. Backward Compatible

Without `event_classes`, the decorator works exactly as before:

```python
@auto_publish(
    topic_prefix="pulse.compliance",
    include_fields=["id", "status"],
    publish_on=["created", "updated"]
)
class RiskAssessment(models.Model):
    # Still works with raw event publishing!
    pass
```

## API Changes

### Before (Still Supported)

```python
@auto_publish(
    topic_prefix: Optional[str] = None,
    include_fields: Optional[List[str]] = None,
    exclude_fields: Optional[List[str]] = None,
    publish_on: Optional[List[str]] = None,
    client: Optional[TchuClient] = None,
    condition: Optional[Callable] = None,
)
```

### After (New)

```python
@auto_publish(
    topic_prefix: Optional[str] = None,              # Only used without event_classes
    include_fields: Optional[List[str]] = None,
    exclude_fields: Optional[List[str]] = None,
    publish_on: Optional[List[str]] = None,          # Auto-inferred from event_classes
    client: Optional[TchuClient] = None,             # Only used without event_classes
    condition: Optional[Callable] = None,
    event_classes: Optional[Dict[str, Type]] = None, # NEW! One event class per action
    context_provider: Optional[Callable] = None,     # NEW! Provide context to serializers
)
```

## Benefits

1. **Validation**: Data is validated through DRF serializers before publishing
2. **Type Safety**: Better IDE support and type checking
3. **Flexibility**: Different topics and serializers per action
4. **Consistency**: Same event classes for manual and automatic publishing
5. **Error Handling**: Better error messages from serializer validation
6. **Authorization**: Pass request context to serializers via `context_provider`
7. **Fail-Safe**: Context provider errors don't prevent event publishing

## Documentation

- **`CUSTOM_EVENT_CLASS_EXAMPLE.md`**: Comprehensive examples and patterns for using event classes
- **`CONTEXT_PROVIDER_GUIDE.md`**: Detailed guide on passing request context to serializers

## Migration Path

1. Keep existing decorators as-is (backward compatible)
2. Gradually migrate to event classes for new models
3. When ready, migrate existing models by:
   - Creating event classes with appropriate topics and serializers
   - Adding `event_classes` parameter to decorator
   - Removing `topic_prefix` parameter (if using event classes)

## Testing

All changes maintain backward compatibility. Existing tests should continue to pass.

