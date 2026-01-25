# Design Alternatives for Event Definition

## Current Design (Pydantic-as-Class)

```python
@event("rpc.coolset.data_room.survey_submission.save_to_bucket", mode="rpc")
class SurveySubmissionSaveToBucketRequest:
    submission_context: dict
    bucket_url: str | None = None
    file_path: str | None = None

@event.response("rpc.coolset.data_room.survey_submission.save_to_bucket")
class SurveySubmissionSaveToBucketResponse:
    success: bool
    error_message: str | None = None
```

**Pros:**
- Clean, minimal syntax
- Type hints directly on class
- Pydantic validation built-in

**Cons:**
- Class becomes a Pydantic model (not a "real" class)
- Less familiar to DRF users
- Harder to add custom methods/logic

---

## Alternative 1: Meta Class Pattern (Closest to Your Old Design)

```python
from celery_salt import Event, RPCResponse, RPCError

class SurveySubmissionSaveToBucketRequestEvent(Event):
    """Event for saving survey submission to bucket."""
    
    class Request:
        submission_context: dict
        bucket_url: str | None = None
        file_path: str | None = None
    
    class Response(RPCResponse):
        success: bool
        error_message: str | None = None
    
    class Error(RPCError):
        error_code: str
        error_message: str
        details: dict | None = None
    
    class Meta:
        topic = "rpc.coolset.data_room.survey_submission.save_to_bucket"
        mode = "rpc"
        version = "v1"

# Usage:
response = SurveySubmissionSaveToBucketRequestEvent.call(
    submission_context={...},
    bucket_url="s3://...",
)
```

**Implementation:**
- `Event` base class handles registration
- Inner `Request`, `Response`, `Error` classes become Pydantic models
- `Meta` class holds configuration
- `call()` and `publish()` methods on base class

**Pros:**
- Very familiar to DRF users
- Clear separation of concerns
- Easy to add custom methods to the event class
- Can have class-level logic/helpers

**Cons:**
- More verbose
- Nested classes might feel awkward

---

## Alternative 2: Explicit Model Definition

```python
from celery_salt import Event
from pydantic import BaseModel

class SurveySubmissionSaveToBucketRequest(BaseModel):
    submission_context: dict
    bucket_url: str | None = None
    file_path: str | None = None

class SurveySubmissionSaveToBucketResponse(BaseModel):
    success: bool
    error_message: str | None = None

@event(
    topic="rpc.coolset.data_room.survey_submission.save_to_bucket",
    mode="rpc",
    request_model=SurveySubmissionSaveToBucketRequest,
    response_model=SurveySubmissionSaveToBucketResponse,
)
class SurveySubmissionSaveToBucketEvent(Event):
    """Event for saving survey submission to bucket."""
    pass

# Usage:
response = SurveySubmissionSaveToBucketEvent.call(
    submission_context={...},
    bucket_url="s3://...",
)
```

**Pros:**
- Models defined separately (can reuse)
- Event class is a real class (can add methods)
- Clear separation

**Cons:**
- More verbose
- Models defined separately from event

---

## Alternative 3: Hybrid - Meta with Inline Models

```python
from celery_salt import Event

class SurveySubmissionSaveToBucketEvent(Event):
    """Event for saving survey submission to bucket."""
    
    # Request schema (inline)
    submission_context: dict
    bucket_url: str | None = None
    file_path: str | None = None
    
    # Response schema (as class attribute)
    Response = type('Response', (BaseModel,), {
        'success': bool,
        'error_message': str | None = None,
    })
    
    class Meta:
        topic = "rpc.coolset.data_room.survey_submission.save_to_bucket"
        mode = "rpc"
        version = "v1"
        # Optional: explicit response/error models
        # response_model = SurveySubmissionSaveToBucketResponse
        # error_model = SurveySubmissionSaveToBucketError

# Usage:
response = SurveySubmissionSaveToBucketEvent.call(
    submission_context={...},
    bucket_url="s3://...",
)
```

**Pros:**
- Request fields on main class (familiar)
- Response/Error as nested classes
- Meta class for configuration
- Can add custom methods

**Cons:**
- Mixing styles (fields on class vs nested)
- Response definition is a bit awkward

---

## Alternative 4: Decorator with Meta (Recommended)

```python
from celery_salt import event
from pydantic import BaseModel

class SurveySubmissionSaveToBucketRequest(BaseModel):
    submission_context: dict
    bucket_url: str | None = None
    file_path: str | None = None

class SurveySubmissionSaveToBucketResponse(BaseModel):
    success: bool
    error_message: str | None = None

@event(
    topic="rpc.coolset.data_room.survey_submission.save_to_bucket",
    mode="rpc",
)
class SurveySubmissionSaveToBucketEvent:
    """Event for saving survey submission to bucket."""
    
    # Request model (required)
    Request = SurveySubmissionSaveToBucketRequest
    
    # Response model (optional for RPC)
    Response = SurveySubmissionSaveToBucketResponse
    
    # Error model (optional)
    # Error = SurveySubmissionSaveToBucketError
    
    class Meta:
        version = "v1"
        # Additional metadata if needed

# Usage:
response = SurveySubmissionSaveToBucketEvent.call(
    submission_context={...},
    bucket_url="s3://...",
)
```

**Pros:**
- Models are explicit Pydantic models (reusable, testable)
- Event class is a real class (can add methods, properties)
- Meta class for configuration
- Familiar pattern
- Clear separation

**Cons:**
- Slightly more verbose than current
- Need to define models separately

---

## Alternative 5: Current Design with Helper Base Class

Keep current design but add a base class for those who want it:

```python
from celery_salt import EventBase

class SurveySubmissionSaveToBucketEvent(EventBase):
    """Event for saving survey submission to bucket."""
    
    class Request:
        submission_context: dict
        bucket_url: str | None = None
        file_path: str | None = None
    
    class Response:
        success: bool
        error_message: str | None = None
    
    class Meta:
        topic = "rpc.coolset.data_room.survey_submission.save_to_bucket"
        mode = "rpc"
        version = "v1"

# EventBase automatically:
# 1. Converts Request/Response to Pydantic models
# 2. Registers schema
# 3. Adds call()/publish() methods
```

**Pros:**
- Most familiar to your old design
- Automatic conversion
- Can add custom methods to event class

**Cons:**
- Requires base class
- Magic conversion might be surprising

---

## Recommendation

I'd recommend **Alternative 4** (Decorator with Meta + Explicit Models) because:

1. **Familiar**: Uses Meta class like your old design
2. **Explicit**: Models are clear Pydantic models (testable, reusable)
3. **Flexible**: Event class can have custom methods
4. **Type-safe**: Full Pydantic validation
5. **Clean**: Clear separation of concerns

Would you like me to implement one of these alternatives?
