# Decorator Simplification Summary

## Changes Made

### 1. Removed Unnecessary Object Creation
**Before**: Created `base_topic` and `event_client` even when using event classes (where they're not needed)

**After**: Only create what's needed for each mode:
```python
if event_classes:
    # Event class mode - don't need topic or client
    base_topic = None
    event_client = None
else:
    # Raw mode - need topic and client
    base_topic = f"{topic_prefix}.{model_name}"
    event_client = client or TchuClient()
```

**Benefit**: Cleaner logic, no wasted object creation

### 2. Simplified publish_event Function
**Before**: Verbose comments and extra logging

**After**: Clearer two-path logic:
```python
if event_classes and event_type in event_classes:
    # Event class mode: use event class with its topic and serializers
    ...
else:
    # Raw mode: publish directly with generated topic
    ...
```

**Benefit**: Easier to understand the two distinct modes

### 3. Simplified Logging
**Before**: 
```python
logger.info(
    f"Auto-publish configured for {model_class.__name__} "
    f"with event classes: {event_classes_str}{context_info}"
)
```

**After**:
```python
logger.info(
    f"Auto-publish: {model_class.__name__} -> events: {event_list} (with context)"
)
```

**Benefit**: More concise, easier to scan logs

### 4. Simplified Docstring
**Before**: 60+ lines with multiple examples

**After**: 40 lines, clearly separated by mode with concise examples

**Benefit**: Easier to understand the two modes at a glance

## Final Implementation

The decorator now has **two clear modes**:

### Mode 1: Event Class Mode (Recommended)
```python
@auto_publish(
    event_classes={"created": MyCreatedEvent, "updated": MyUpdatedEvent},
    context_provider=get_context  # Optional
)
```

**How it works**:
- Uses event class topics (from Meta)
- Uses event class serializers (from Meta)
- Validates data through serializers
- Can pass context for authorization

### Mode 2: Raw Mode (Legacy)
```python
@auto_publish(
    topic_prefix="my.topic",
    include_fields=["id", "status"],
    publish_on=["created"]
)
```

**How it works**:
- Generates topic: `{topic_prefix}.{model_name}.{event_type}`
- Publishes raw dictionaries (no validation)
- No serializers, no context

## Key Design Decisions

### 1. Two Distinct Paths
The code clearly separates the two modes rather than trying to merge them. This makes the code easier to understand and maintain.

### 2. Event Classes Own Their Configuration
When using event classes:
- Topic comes from the event class Meta
- Serializers come from the event class Meta
- The decorator just coordinates the flow

### 3. Context Provider is Optional
- Only works with event classes (where serializers can use it)
- Fails gracefully if provider errors
- Returns empty dict if no context available

### 4. Auto-Inference
When you provide `event_classes`, the decorator automatically infers `publish_on` from the keys, so you don't have to specify it twice.

## What's NOT Overengineered

These features are essential:

1. **Field filtering** (`include_fields`/`exclude_fields`): Needed to exclude sensitive data
2. **Conditional publishing** (`condition`): Needed for business logic
3. **Context provider**: Needed for authorization in serializers
4. **Metadata** (`_meta` field): Needed for debugging and tracing
5. **Error handling**: Needed for reliability

## Summary

The decorator is now:
- ✅ Clearer: Two distinct modes, not merged
- ✅ Simpler: Only creates what's needed
- ✅ More maintainable: Less code, better comments
- ✅ Still flexible: All features preserved
- ✅ Backward compatible: No breaking changes

## How to Use Context Provider

Since you asked "I'm not sure how to pass request context", here's the pattern:

### Step 1: Store Context on Instance
```python
# In your view/service:
instance = MyModel(field1="value")
instance._event_user_id = request.user.id  # Store temporarily
instance.save()  # Auto-publishes with this context
```

### Step 2: Define Context Provider
```python
def get_context(instance, event_type):
    """Extract context from temporary instance attributes."""
    return {
        "user_id": getattr(instance, '_event_user_id', None),
        "company_id": instance.company_id,
    }
```

### Step 3: Apply Decorator
```python
@auto_publish(
    event_classes={"created": MyCreatedEvent},
    context_provider=get_context
)
class MyModel(models.Model):
    company_id = models.IntegerField()
```

The context is passed to the event serializer's `context` parameter, which you can access in validation:

```python
class MySerializer(serializers.Serializer):
    def validate(self, attrs):
        # Access context
        user_id = self.context.get('user_id')
        # ... use for authorization
        return attrs
```

See `CONTEXT_PROVIDER_GUIDE.md` for more approaches (thread-local storage, model fields, etc.).

