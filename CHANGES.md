# Changes to @auto_publish Decorator

## Summary

Enhanced the `@auto_publish` decorator to support custom `TchuEvent` classes with proper serialization, validation, and request context support.

## Changed Files

### Core Implementation
- **`tchu_tchu/django/decorators.py`**
  - Added `event_classes` parameter (Dict[str, Type])
  - Added `context_provider` parameter (Callable)
  - Modified `publish_event()` to use event classes when provided
  - Auto-infer `publish_on` from `event_classes` keys
  - Pass context to event serializers
  - Graceful error handling for context provider failures

## New Features

### 1. Event Classes Per Action
```python
@auto_publish(
    event_classes={
        "created": MyCreatedEvent,
        "updated": MyUpdatedEvent,
        "deleted": MyDeletedEvent
    }
)
```

### 2. Context Provider for Authorization
```python
def provide_context(instance, event_type):
    return {"user_id": instance._event_user_id}

@auto_publish(
    event_classes={"created": MyEvent},
    context_provider=provide_context
)
```

## Key Points

1. **Respects Event Class Topics**: Event classes define their own topics (not overridden)
2. **Respects Event Class Serializers**: Each event class defines its own serializers
3. **Context Support**: Pass request context for EventAuthorizationSerializer patterns
4. **Auto-Inference**: `publish_on` automatically inferred from `event_classes` keys
5. **Fail-Safe**: Context provider errors logged but don't prevent publishing
6. **Backward Compatible**: Works without `event_classes` as before

## Documentation Files

| File | Purpose |
|------|---------|
| **DECORATOR_ENHANCEMENTS_README.md** | Main entry point with quick start |
| **DECORATOR_CHANGES_SUMMARY.md** | Technical summary of changes |
| **CUSTOM_EVENT_CLASS_EXAMPLE.md** | Comprehensive event class examples |
| **CONTEXT_PROVIDER_GUIDE.md** | Detailed guide on passing context |

## Usage Example

```python
# Event classes
class RiskAssessmentCreatedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    company_id = serializers.IntegerField()
    status = serializers.CharField()
    _meta = serializers.DictField(required=False)
    user = serializers.IntegerField(required=False)
    company = serializers.IntegerField(required=False)

class RiskAssessmentCreatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.created"
        request_serializer_class = RiskAssessmentCreatedSerializer

# Context provider
def provide_context(instance, event_type):
    return {
        "user_id": getattr(instance, '_event_user_id', None),
        "company_id": instance.company_id,
    }

# Decorator
@auto_publish(
    include_fields=["id", "company_id", "status"],
    event_classes={"created": RiskAssessmentCreatedEvent},
    context_provider=provide_context
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
    
    def set_event_context(self, user_id):
        self._event_user_id = user_id
        return self

# Usage in views
assessment = RiskAssessment(company_id=123, status="pending")
assessment.set_event_context(user_id=request.user.id)
assessment.save()  # Auto-publishes with validation and authorization!
```

## Benefits

✅ Validation through DRF serializers before publishing  
✅ Type safety and IDE support  
✅ Different topics and serializers per action  
✅ Authorization context support  
✅ Consistent with manual event publishing  
✅ Better error messages  
✅ Backward compatible  

## Testing

No breaking changes. All existing decorators continue to work as before.

## Next Steps

1. Review documentation files
2. Update models to use event classes
3. Add context providers where needed for authorization
4. Test thoroughly

Date: 2025-11-18

