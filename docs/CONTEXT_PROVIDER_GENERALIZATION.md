# Context Provider Generalization

## Summary

Updated all documentation to emphasize that `context_provider` is a **general-purpose** mechanism for passing ANY context to serializers, not just authorization fields (`user`, `company`, `user_company`).

## Changes Made

### 1. CONTEXT_PROVIDER_GUIDE.md
**Before**: Focused on `EventAuthorizationSerializer` pattern with specific `user`, `company`, `user_company` fields

**After**: 
- Starts with "If your serializers need `self.context`" (general)
- Shows 3 common use cases:
  1. Authorization/Authentication (one use case)
  2. Contextual Validation (e.g., admin checks)
  3. Request Metadata (e.g., IP address, user agent)
- General flow example with flexible context dict
- Added "General Examples" section showing:
  - Simple dictionary storage
  - Multiple temporary attributes
  - Model fields
  - **Any data your serializers need**

### 2. CUSTOM_EVENT_CLASS_EXAMPLE.md
**Before**: "If your serializers extend EventAuthorizationSerializer"

**After**: "If your serializers use `self.context`" with multiple use case examples:
- Authorization (extracting user_id, tenant_id)
- Conditional validation (checking is_admin)
- Emphasizes this is for ANY serializer that needs context

### 3. tchu_tchu/django/decorators.py
**Before**: "If your serializers extend EventAuthorizationSerializer"

**After**: "If your serializers use self.context"

### 4. DECORATOR_ENHANCEMENTS_README.md
**Before**: Section titled "With Authorization Context (EventAuthorizationSerializer)"

**After**: Section titled "With Context Provider (for serializers using self.context)" with examples showing:
- user_id
- is_admin
- tenant_id
- "... any other context your serializer needs"

### 5. EVENT_AUTHORIZATION_QUICK_REF.md
**Added** prominent note at the top:
> **Note**: This is ONE use case for `context_provider`. The `context_provider` can pass ANY context your serializers need, not just authorization.

Renamed to: "Context Provider Quick Reference: Authorization Pattern"

## Key Messages Now Emphasized

✅ **General Purpose**: Context provider passes ANY data to `self.context`  
✅ **Flexible**: Not limited to authorization fields  
✅ **Common Uses**: Authorization, validation, metadata, business logic  
✅ **Your Choice**: Pass whatever your serializers need  

## Examples Now Shown

### General Context Examples
```python
# Example 1: Authorization + metadata
context = {
    "user_id": 123,
    "is_admin": True,
    "ip_address": "192.168.1.1",
}

# Example 2: Business logic flags
context = {
    "feature_flags": {"new_ui": True},
    "environment": "production",
    "action_source": "mobile_app",
}

# Example 3: Any custom data
context = {
    "organization_id": 456,
    "actor_id": 789,
    "custom_field": "any value",
}
```

## Authorization Pattern Still Documented

The authorization pattern (user/company/user_company) is still fully documented as **ONE use case**, particularly in:
- `EVENT_AUTHORIZATION_QUICK_REF.md` (dedicated to this pattern)
- `CONTEXT_PROVIDER_GUIDE.md` (as "Approach 1")
- But now clearly labeled as one of many possible uses

## Benefits

1. **More Accurate**: Documentation reflects that this is general-purpose
2. **Not Prescriptive**: Doesn't assume your specific authorization pattern
3. **More Useful**: Developers can see other use cases
4. **Clearer**: Authorization is presented as an example, not the only way
5. **Flexible**: Works with any context structure your serializers need

## Migration for Users

No code changes needed! This is documentation-only. Your existing code with user/company/user_company still works exactly the same - it's just one pattern among many possible patterns.

