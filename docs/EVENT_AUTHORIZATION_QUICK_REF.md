# Context Provider Quick Reference: Authorization Pattern

> **Note**: This is ONE use case for `context_provider`. The `context_provider` can pass ANY context your serializers need, not just authorization. See `CONTEXT_PROVIDER_GUIDE.md` for other patterns.

## Authorization Use Case

If your event serializers extract authorization/authentication fields from `self.context`:

```python
class EventAuthorizationSerializer(serializers.Serializer):
    user = serializers.IntegerField(required=False)
    company = serializers.IntegerField(required=False)
    user_company = serializers.IntegerField(required=False)
    
    def validate(self, attrs):
        # Extracts from self.context
        if self.context:
            attrs['user'] = self.context.get('user_id')
            attrs['company'] = self.context.get('company_id')
        return attrs
```

**Manual publishing** (works fine):
```python
event = MyEvent()
event.serialize_request(data, context={"request": request})  # ← context provided
event.publish()
```

**Auto-publish without context_provider** (FAILS):
```python
@auto_publish(event_classes={"created": MyEvent})  # ← No context_provider!
class MyModel(models.Model):
    pass

instance.save()  # Serializer gets self.context = None → authorization fails!
```

## The Solution

Use `context_provider` to extract context from the model instance:

```python
# Step 1: Define context provider
def get_context(instance, event_type):
    return {
        "user_id": getattr(instance, '_event_user_id', None),
        "company_id": instance.company_id,
    }

# Step 2: Add to decorator
@auto_publish(
    event_classes={"created": MyEvent},
    context_provider=get_context  # ← Now serializer gets context!
)
class MyModel(models.Model):
    company_id = models.IntegerField()

# Step 3: Store context before saving
instance = MyModel(company_id=123)
instance._event_user_id = request.user.id  # ← Temporary storage
instance.save()  # Serializer gets self.context = {"user_id": ..., "company_id": ...}
```

## How It Flows

```
1. Your View
   └─> instance._event_user_id = request.user.id
   └─> instance.save()

2. Django Signal (post_save)
   └─> Decorator's publish_event()

3. Decorator calls your context_provider
   └─> get_context(instance, "created")
   └─> Returns: {"user_id": 456, "company_id": 789}

4. Decorator calls event.serialize_request()
   └─> event.serialize_request(data, context={"user_id": 456, ...})

5. DRF Serializer
   └─> self.context = {"user_id": 456, "company_id": 789}
   └─> EventAuthorizationSerializer.validate() extracts fields
   └─> attrs['user'] = self.context['user_id']  # Success!
```

## Common Patterns

### Pattern 1: Temporary Attribute (Recommended)
```python
def get_context(instance, event_type):
    return {
        "user_id": getattr(instance, '_event_user_id', None),
        "company_id": instance.company_id,
    }

# In view:
instance._event_user_id = request.user.id
instance.save()
```

### Pattern 2: Model Fields
```python
def get_context(instance, event_type):
    return {
        "user_id": instance.created_by_user_id,
        "company_id": instance.company_id,
    }

class MyModel(models.Model):
    created_by_user_id = models.IntegerField()
    company_id = models.IntegerField()
```

### Pattern 3: Thread-Local Storage
```python
# middleware.py
_thread_locals = threading.local()

def get_current_request():
    return getattr(_thread_locals, 'request', None)

# context provider
def get_context(instance, event_type):
    request = get_current_request()
    if not request:
        return {}
    return {
        "user_id": request.user.id,
        "company_id": instance.company_id,
    }
```

## Checklist

When adding `@auto_publish` to a model:

- [ ] Does your event serializer extend `EventAuthorizationSerializer`?
- [ ] If yes, have you added a `context_provider`?
- [ ] Does your context provider extract `user_id` and `company_id`?
- [ ] Do you store context on the instance before saving?
- [ ] Does your serializer handle missing context gracefully?

## Testing

```python
@patch('tchu_tchu.events.TchuEvent.publish')
def test_publishes_with_authorization(self, mock_publish):
    """Test that events include authorization context."""
    instance = MyModel(company_id=123)
    instance._event_user_id = 456
    instance.save()
    
    # Verify publish was called
    mock_publish.assert_called_once()
    
    # Check that context was passed
    # (You can inspect the event instance's validated_data)
```

## Error Messages

### "Missing authorization" or "User/Company required"
**Cause**: Serializer didn't receive context  
**Fix**: Add `context_provider` parameter

### "Context provider failed"
**Cause**: Exception in context_provider function  
**Fix**: Check logs for details, ensure attributes exist on instance

### AttributeError: 'MyModel' object has no attribute '_event_user_id'
**Cause**: Forgot to set context on instance before saving  
**Fix**: Call `instance._event_user_id = request.user.id` before `save()`

## Full Example

```python
# serializers.py
class EventAuthorizationSerializer(serializers.Serializer):
    user = serializers.IntegerField(required=False)
    company = serializers.IntegerField(required=False)
    
    def validate(self, attrs):
        if self.context:
            attrs['user'] = self.context.get('user_id')
            attrs['company'] = self.context.get('company_id')
        
        if not attrs.get('user') or not attrs.get('company'):
            raise serializers.ValidationError("Missing authorization")
        
        return attrs

class RiskCreatedSerializer(EventAuthorizationSerializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    _meta = serializers.DictField(required=False)

# events.py
class RiskCreatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk.created"
        request_serializer_class = RiskCreatedSerializer

# models.py
def risk_context_provider(instance, event_type):
    return {
        "user_id": getattr(instance, '_event_user_id', None),
        "company_id": instance.company_id,
    }

@auto_publish(
    event_classes={"created": RiskCreatedEvent},
    context_provider=risk_context_provider
)
class Risk(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)

# views.py
def create_risk(request, data):
    risk = Risk(**data)
    risk._event_user_id = request.user.id  # ← Critical!
    risk.save()  # ← Auto-publishes with authorization
    return risk
```

## See Also

- **CONTEXT_PROVIDER_GUIDE.md**: Detailed guide on all context provider patterns
- **CUSTOM_EVENT_CLASS_EXAMPLE.md**: Full examples of using event classes
- **DECORATOR_ENHANCEMENTS_README.md**: Overview of all decorator features

