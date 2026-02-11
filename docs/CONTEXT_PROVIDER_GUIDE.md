# Context Provider Guide

## Why This Matters

**If your event serializers need `self.context`**, you need to read this guide.

DRF serializers can access `self.context` for additional information during validation. When you publish events manually, you pass `context={"request": request, ...}` and the serializer can use this context.

**The problem**: Django signals don't have access to the request object, so the `@auto_publish` decorator needs a way to provide context to serializers.

**The solution**: The `context_provider` parameter extracts context from the model instance and passes it to the serializer.

## Common Use Cases

### 1. Authorization/Authentication
Your serializers extract user/company/auth information from context for validation:

```python
class MySerializer(serializers.Serializer):
    def validate(self, attrs):
        # Extract from self.context
        if self.context:
            attrs['user_id'] = self.context.get('user_id')
            attrs['tenant_id'] = self.context.get('tenant_id')
        return attrs
```

### 2. Contextual Validation
Your serializers use context for business logic:

```python
class MySerializer(serializers.Serializer):
    def validate_status(self, value):
        # Access context for conditional validation
        if self.context.get('is_admin'):
            # Admins can set any status
            return value
        # Regular users have restrictions
        if value in ['archived', 'deleted']:
            raise ValidationError("Permission denied")
        return value
```

### 3. Request Metadata
Your serializers need request information:

```python
class MySerializer(serializers.Serializer):
    def validate(self, attrs):
        if self.context:
            attrs['request_ip'] = self.context.get('ip_address')
            attrs['user_agent'] = self.context.get('user_agent')
        return attrs
```

**Without `context_provider`**: `self.context` is None, validation may fail  
**With `context_provider`**: `self.context` has the data your serializer needs

## How It Works: Complete Flow

```python
# 1. Your view/service
def create_item(request, data):
    item = Item(**data)
    item._event_context = {                      # ← Store any context temporarily
        "user_id": request.user.id,
        "ip_address": request.META.get('REMOTE_ADDR'),
        "is_admin": request.user.is_staff,
    }
    item.save()                                  # ← Triggers post_save signal

# 2. Decorator's context_provider (you define this)
def get_context(instance, event_type):
    return getattr(instance, '_event_context', {})  # ← Extract from instance

# 3. Decorator calls (automatic):
event_instance.serialize_request(
    data={"id": 123, ...}, 
    context={                                     # ← From context_provider
        "user_id": 456,
        "ip_address": "192.168.1.1",
        "is_admin": True
    }
)

# 4. In your serializer's validate() (automatic):
def validate(self, attrs):
    if self.context:                             # ← Context from decorator!
        # Use context for whatever your serializer needs
        attrs['created_by'] = self.context.get('user_id')
        attrs['metadata'] = {
            "ip": self.context.get('ip_address'),
            "admin_action": self.context.get('is_admin')
        }
    return attrs
```

**Key insight**: The `context_provider` bridges the gap between the model instance (which doesn't have request) and the serializer (which needs context). You can pass ANY data your serializer needs.

## Overview

For event classes, `@auto_publish` uses **`payload_provider`** to build the complete event payload. Return `None` to skip publishing. Required when using `event_classes`.

## SaltEvent and payload_provider

**SaltEvent** subclasses require all schema fields at initialization: `Event(**payload).publish()`. The legacy flow (`event_class()` + `serialize_request`) does not work because SaltEvent has no `serialize_request` and cannot be instantiated without data.

Use `payload_provider` when your event extends SaltEvent and its schema includes request-derived fields (user, company, etc.):

```python
def get_product_payload(instance, event_type):
    """Build full payload. Return None to skip (imports, bulk ops)."""
    if not getattr(instance, "_event_request", None):
        return None
    auth = authorize_event({"request": instance._event_request})
    if not auth.get("user"):
        return None
    return {
        "id": instance.id,
        "company_id": instance.company_id,
        "sku": instance.sku,
        # ... model fields ...
        **auth,
    }

@auto_publish(
    event_classes={"created": ProductCreatedEvent, "updated": ProductUpdatedEvent},
    payload_provider=get_product_payload,
)
class Product(models.Model):
    pass
```

Return `None` when context is missing (e.g. no `_event_request` on imports) so the decorator skips publishing.

## The Problem (legacy context_provider)

When manually publishing events, you typically pass context directly:

```python
# Manual event publishing with context
event = RiskAssessmentCreatedEvent()
event.serialize_request(
    data={"id": 123, "status": "pending"},
    context={"request": request}  # Has user, company, etc.
)
event.publish()
```

However, Django signals (`post_save`, `post_delete`) don't have access to the request object, so the decorator needs a way to extract or construct the context.

## The Solution: Context Provider

The `context_provider` is a function that takes the model instance and event type, and returns a context dictionary:

```python
def context_provider(instance: Model, event_type: str) -> Dict[str, Any]:
    """
    Extract context from the model instance.
    
    Args:
        instance: The Django model instance being saved/deleted
        event_type: The event type ("created", "updated", "deleted")
    
    Returns:
        Context dictionary to pass to the event serializer
    """
    return {
        "user_id": ...,
        "company_id": ...,
        # ... other context fields
    }
```

## General Examples

### Example 1: Simple Dictionary Storage
```python
def get_context(instance, event_type):
    """Extract any context stored as a dict."""
    return getattr(instance, '_event_context', {})

# In view:
instance._event_context = {
    "user_id": request.user.id,
    "ip_address": request.META['REMOTE_ADDR'],
    "custom_field": "any value you need"
}
instance.save()
```

### Example 2: Multiple Temporary Attributes
```python
def get_context(instance, event_type):
    """Extract context from multiple attributes."""
    return {
        "actor_id": getattr(instance, '_actor_id', None),
        "action_source": getattr(instance, '_action_source', 'web'),
        "feature_flags": getattr(instance, '_feature_flags', {}),
    }

# In view:
instance._actor_id = request.user.id
instance._action_source = 'mobile_app'
instance._feature_flags = {'new_ui': True}
instance.save()
```

### Example 3: Model Fields
```python
def get_context(instance, event_type):
    """Extract context from existing model fields."""
    return {
        "created_by_id": instance.created_by_id,
        "organization_id": instance.organization_id,
        "environment": instance.environment,
    }

# No need to set temporary attributes - uses actual model fields
```

## Approach 1: Storing Context on the Instance (Recommended)

Store context temporarily on the model instance before saving:

### Step 1: Add Helper Method to Model

```python
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
    
    def set_event_context(self, user=None, company=None, request=None):
        """Store context for event publishing."""
        if request:
            self._event_user_id = getattr(request.user, 'id', None)
            self._event_company_id = getattr(request, 'company_id', None)
        else:
            self._event_user_id = user
            self._event_company_id = company
        return self
```

### Step 2: Define Context Provider

```python
def risk_assessment_context_provider(instance, event_type):
    """Extract context from temporary instance attributes."""
    context = {}
    
    # Get context from temporary attributes
    user_id = getattr(instance, '_event_user_id', None)
    company_id = getattr(instance, '_event_company_id', None)
    
    if user_id and company_id:
        context['user_id'] = user_id
        context['company_id'] = company_id
    
    return context
```

### Step 3: Apply Decorator with Context Provider

```python
@auto_publish(
    include_fields=["id", "company_id", "status"],
    event_classes={
        "created": RiskAssessmentCreatedEvent,
        "updated": RiskAssessmentUpdatedEvent
    },
    context_provider=risk_assessment_context_provider
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
    
    def set_event_context(self, user=None, company=None, request=None):
        if request:
            self._event_user_id = getattr(request.user, 'id', None)
            self._event_company_id = getattr(request, 'company_id', None)
        else:
            self._event_user_id = user
            self._event_company_id = company
        return self
```

### Step 4: Use in Views

```python
# In your Django view or service
def create_risk_assessment(request, data):
    assessment = RiskAssessment(**data)
    
    # Set context before saving
    assessment.set_event_context(request=request)
    assessment.save()  # Auto-publishes with context!
    
    return assessment
```

## Approach 2: Thread-Local Storage

Use thread-local storage to track the current request:

### Step 1: Create Middleware

```python
# middleware.py
import threading

_thread_locals = threading.local()

class RequestContextMiddleware:
    """Store current request in thread-local storage."""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        _thread_locals.request = request
        response = self.get_response(request)
        _thread_locals.request = None
        return response

def get_current_request():
    """Get the current request from thread-local storage."""
    return getattr(_thread_locals, 'request', None)
```

### Step 2: Define Context Provider Using Thread-Local

```python
from myapp.middleware import get_current_request

def thread_local_context_provider(instance, event_type):
    """Extract context from thread-local request."""
    request = get_current_request()
    
    if not request:
        return {}
    
    return {
        "user_id": getattr(request.user, 'id', None),
        "company_id": getattr(request, 'company_id', None),
    }
```

### Step 3: Apply Decorator

```python
@auto_publish(
    event_classes={
        "created": RiskAssessmentCreatedEvent,
        "updated": RiskAssessmentUpdatedEvent
    },
    context_provider=thread_local_context_provider
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
```

## Approach 3: Extract from Model Fields

Extract context from existing model fields:

```python
def model_field_context_provider(instance, event_type):
    """Extract context from model fields."""
    context = {}
    
    # If model has user/company fields, use them
    if hasattr(instance, 'created_by_user_id'):
        context['user_id'] = instance.created_by_user_id
    
    if hasattr(instance, 'company_id'):
        context['company_id'] = instance.company_id
    
    return context

@auto_publish(
    event_classes={"created": RiskAssessmentCreatedEvent},
    context_provider=model_field_context_provider
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    created_by_user_id = models.IntegerField()
    status = models.CharField(max_length=50)
```

## Approach 4: Mock Request Object

Create a mock request object that DRF serializers can use:

```python
class MockRequest:
    """Mock request object for DRF serializers."""
    
    def __init__(self, user_id, company_id):
        self.user = type('User', (), {'id': user_id})()
        self.company_id = company_id

def mock_request_context_provider(instance, event_type):
    """Create a mock request for DRF serializers."""
    user_id = getattr(instance, '_event_user_id', None)
    company_id = getattr(instance, 'company_id', None)
    
    if user_id and company_id:
        mock_request = MockRequest(user_id, company_id)
        return {"request": mock_request}
    
    return {}

@auto_publish(
    event_classes={"created": RiskAssessmentCreatedEvent},
    context_provider=mock_request_context_provider
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    
    def set_event_context(self, request):
        self._event_user_id = request.user.id
        return self
```

## How Context Flows

1. **Model Save**: You call `instance.save()`
2. **Signal Fires**: Django's `post_save` signal triggers
3. **Context Provider Called**: Decorator calls `context_provider(instance, event_type)`
4. **Context Returned**: Provider returns context dict (or empty dict)
5. **Event Serialization**: `event.serialize_request(data, context=context)`
6. **Serializer Validation**: DRF serializer receives context for authorization
7. **Event Published**: Validated event is published

## Error Handling

The context provider is fail-safe:

```python
def context_provider(instance, event_type):
    # If this raises an exception...
    raise ValueError("Something went wrong")

# Result: Warning is logged, event publishes WITHOUT context
# The event still publishes - context is optional
```

From the logs:
```
WARNING: Context provider failed for created event: Something went wrong. Publishing without context.
```

## Example: Full Integration with EventAuthorizationSerializer

```python
# serializers.py
from rest_framework import serializers

class EventAuthorizationSerializer(serializers.Serializer):
    """Base serializer that validates authorization context."""
    user = serializers.IntegerField(required=False)
    company = serializers.IntegerField(required=False)
    user_company = serializers.IntegerField(required=False)
    
    def validate(self, attrs):
        # Get from context if not in data
        if 'user' not in attrs and self.context:
            attrs['user'] = self.context.get('user_id')
            attrs['company'] = self.context.get('company_id')
        
        # Validate authorization
        if not attrs.get('user') or not attrs.get('company'):
            raise serializers.ValidationError("Missing authorization")
        
        return attrs

class RiskAssessmentCreatedSerializer(EventAuthorizationSerializer):
    """Serializer for risk assessment created event."""
    id = serializers.IntegerField()
    company_id = serializers.IntegerField()
    status = serializers.CharField()
    _meta = serializers.DictField(required=False)

# events.py
class RiskAssessmentCreatedEvent(TchuEvent):
    class Meta:
        topic = "pulse.compliance.risk_assessment.created"
        request_serializer_class = RiskAssessmentCreatedSerializer

# models.py
def risk_assessment_context_provider(instance, event_type):
    """Provide context from instance."""
    return {
        "user_id": getattr(instance, '_event_user_id', None),
        "company_id": instance.company_id,
    }

@auto_publish(
    include_fields=["id", "company_id", "status"],
    event_classes={"created": RiskAssessmentCreatedEvent},
    context_provider=risk_assessment_context_provider
)
class RiskAssessment(models.Model):
    company_id = models.IntegerField()
    status = models.CharField(max_length=50)
    
    def set_event_context(self, user_id):
        self._event_user_id = user_id
        return self

# views.py or services.py
def create_risk_assessment(request, data):
    assessment = RiskAssessment(**data)
    assessment.set_event_context(user_id=request.user.id)
    assessment.save()  # Publishes with authorization context!
    return assessment
```

## Best Practices

### 1. Always Handle Missing Context Gracefully

```python
def context_provider(instance, event_type):
    user_id = getattr(instance, '_event_user_id', None)
    
    # Return empty dict if no context available
    if not user_id:
        return {}
    
    return {"user_id": user_id}
```

### 2. Use Descriptive Temporary Attribute Names

```python
# Good: Clear and unlikely to conflict
instance._event_user_id
instance._event_company_id
instance._event_request_context

# Bad: Too generic, might conflict
instance._user
instance._context
```

### 3. Document Context Requirements

```python
class RiskAssessment(models.Model):
    """
    Risk assessment model.
    
    Event Context:
        To publish events with authorization, call set_event_context()
        before saving:
        
        assessment.set_event_context(request=request)
        assessment.save()
    """
    pass
```

### 4. Consider Different Contexts Per Event Type

```python
def context_provider(instance, event_type):
    """Provide different context based on event type."""
    base_context = {
        "company_id": instance.company_id
    }
    
    if event_type == "created":
        # Created events need creator info
        base_context["user_id"] = getattr(instance, '_event_user_id', None)
    elif event_type == "deleted":
        # Deleted events need deletor info
        base_context["user_id"] = getattr(instance, '_deleted_by_user_id', None)
    
    return base_context
```

### 5. Test Without Context

Ensure your serializers can handle missing context:

```python
class RiskAssessmentCreatedSerializer(serializers.Serializer):
    # Make authorization fields optional for backwards compatibility
    user = serializers.IntegerField(required=False)
    company = serializers.IntegerField(required=False)
    
    # Or use skip_authorization flag
```

## Debugging

### Check if Context Provider is Called

```python
def context_provider(instance, event_type):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Context provider called for {event_type}")
    
    context = {"user_id": getattr(instance, '_event_user_id', None)}
    logger.info(f"Returning context: {context}")
    
    return context
```

### Check Serializer Context

```python
class RiskAssessmentCreatedSerializer(serializers.Serializer):
    def validate(self, attrs):
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Serializer context: {self.context}")
        return attrs
```

## Summary

The `context_provider` parameter enables you to:

1. ✅ Pass authorization context to event serializers
2. ✅ Maintain consistency with manual event publishing
3. ✅ Support EventAuthorizationSerializer patterns
4. ✅ Keep authorization logic in serializers
5. ✅ Handle missing context gracefully

Choose the approach that best fits your application architecture!

