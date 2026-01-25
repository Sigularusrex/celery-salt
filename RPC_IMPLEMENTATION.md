# RPC Implementation Summary

**Date:** January 25, 2026  
**Status:** ✅ Implemented

---

## What Was Implemented

### 1. Response and Error Decorators

Added `@event.response()` and `@event.error()` decorators for defining RPC response schemas:

```python
from celerysalt import event, subscribe, RPCError

# Request schema
@event("rpc.documents.list", mode="rpc")
class DocumentListRequest:
    user_id: int
    folder_id: int | None = None
    limit: int = 50

# Success response schema
@event.response("rpc.documents.list")
class DocumentListResponse:
    documents: list[dict]
    total: int
    has_more: bool

# Error response schema
@event.error("rpc.documents.list")
class DocumentListError:
    error_code: str
    error_message: str
    details: dict | None = None
```

### 2. Response Validation

**Caller Side:**
- `DocumentListRequest.call()` validates the response
- Returns validated Pydantic model (either `DocumentListResponse` or `DocumentListError`)
- Can use `isinstance()` to check response type

**Handler Side:**
- Handler return value is validated against response schema
- `RPCError` exceptions are caught and converted to error response
- Error response is validated against error schema if defined

### 3. RPCError Handling

```python
@subscribe("rpc.documents.list")
def handle_list_documents(data: DocumentListRequest) -> DocumentListResponse:
    # Validate access
    if not has_access(data.user_id, data.folder_id):
        raise RPCError(
            error_code="NO_ACCESS",
            error_message="User does not have access to this folder",
            details={"user_id": data.user_id, "folder_id": data.folder_id}
        )
    
    # Get documents
    docs = get_documents(
        user_id=data.user_id,
        folder_id=data.folder_id,
        limit=data.limit
    )
    
    # Return validated response
    return DocumentListResponse(
        documents=[doc.to_dict() for doc in docs],
        total=len(docs),
        has_more=len(docs) == data.limit
    )
```

### 4. Usage Example

```python
# Caller
try:
    response = DocumentListRequest.call(
        user_id=123,
        folder_id=456,
        timeout=10
    )
    
    if isinstance(response, DocumentListError):
        print(f"Error: {response.error_message} ({response.error_code})")
    else:
        print(f"Found {response.total} documents")
        for doc in response.documents:
            print(doc)
            
except TimeoutError:
    print("No response received within timeout")
```

---

## Implementation Details

### Global Schema Storage

Response and error schemas are stored in module-level dictionaries:
- `_rpc_response_schemas[topic]` → Response model
- `_rpc_error_schemas[topic]` → Error model

### Validation Flow

1. **Handler returns value** → Validated against response schema
2. **Handler raises RPCError** → Converted to error dict → Validated against error schema
3. **Caller receives response** → Validated against appropriate schema (response or error)

### Graceful Degradation

- If response/error schema not defined, returns raw response (no validation)
- If validation fails, logs warning and returns raw response (doesn't break the call)

---

## Files Modified

1. `celerysalt/core/decorators.py`
   - Added `response()` decorator
   - Added `error()` decorator
   - Updated `_validate_rpc_response()` to validate against schemas
   - Updated `subscribe()` handler to catch `RPCError` and validate responses

2. `celerysalt/integrations/dispatcher.py`
   - Updated to handle Pydantic model responses (convert to dict for serialization)

3. `celerysalt/core/__init__.py`
   - Exports remain the same (response/error accessed via `event.response()` and `event.error()`)

---

## Testing Checklist

- [ ] RPC call with response schema validation
- [ ] RPC call with error schema validation
- [ ] RPC call without schemas (graceful degradation)
- [ ] RPCError exception handling
- [ ] Response validation failures (should log warning, return raw)
- [ ] Error response validation failures (should log warning, return raw)
- [ ] Protocol compatibility (works with tchu-tchu)

---

## Next Steps

1. Add unit tests for RPC functionality
2. Add integration tests with actual Celery workers
3. Update documentation with RPC examples
4. Consider adding response schema registration to schema registry (for UI visibility)
