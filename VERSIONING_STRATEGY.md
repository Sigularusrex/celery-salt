# Versioning Strategy for CelerySalt Events

**Date:** January 25, 2026  
**Status:** Design Document

---

## Core Principles

1. **Publisher Owns the Event**: Publishers define and control event schemas
2. **Subscribers Never Run Higher Version**: Subscribers are always on same or older version than publishers
3. **Backward Compatibility**: Older-version handlers can process newer-version events
4. **Publisher Manages Sunsetting**: Publishers decide when to stop supporting old versions
5. **Subscriber Warnings**: Subscribers on old versions should be warned when receiving newer events

---

## Problem Statement

When events evolve (v1 → v2), we need to support:

1. **Backward Compatibility**: v1 handlers should be able to process v2 events (validate against v1 schema)
2. **Version Warnings**: v1 handlers should be warned when receiving v2 events (they're on an old version)
3. **Schema Validation**: Each handler validates against its subscribed schema version (not message version)
4. **Publisher Control**: Publishers can sunset old versions by no longer publishing them

### Example Scenario

```python
# v1 Event (original)
class UserSignup(SaltEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
    
    class Meta:
        topic = "user.signup"
        version = "v1"

# v2 Event (adds new field)
class UserSignupV2(SaltEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
        phone_number: str  # NEW field
    
    class Meta:
        topic = "user.signup"
        version = "v2"
```

**Assumptions:**
- Publisher can be on v1 or v2
- Subscriber can be on v1 (if publisher is v2) or v2 (if publisher is v2)
- Subscriber will NEVER be on v2 if publisher is on v1 (subscribers never run higher version)

**Requirements:**
- v1 handler should receive v2 events, but only see v1 fields (user_id, email)
- v1 handler should be WARNED when receiving v2 events (they're on an old version)
- v2 handler should only receive v2 events, see all fields (user_id, email, phone_number)
- v1 publisher → v1 handler: ✅ Works
- v2 publisher → v1 handler: ✅ Works (backward compatible, with warning)
- v2 publisher → v2 handler: ✅ Works

---

## Proposed Solution

### Core Principle: Schema Version vs. Message Version

- **Message Version**: The version of the event that was published (in `_tchu_meta.version`)
- **Handler Schema Version**: The schema version the handler subscribes to (in `@subscribe(version=...)`)

### Handler Matching Rules

1. **Handler with specific version** (e.g., `version="v1"`):
   - ✅ Receives messages with same version (v1 → v1)
   - ✅ Receives messages with newer versions (v2 → v1, v3 → v1, etc.) - **with warning**
   - ❌ Does NOT receive messages with older versions (v1 handler does NOT receive v0 messages)
   - **Note**: Since subscribers never run higher version than publishers, handler version will always be <= message version

2. **Handler with `version="latest"`**:
   - ✅ Receives messages with latest version
   - ⚠️ Receives messages with newer versions (if publisher upgraded) - **with warning**
   - ❌ Does NOT receive messages with older versions (shouldn't happen if subscribers never run higher)

3. **Handler with no version** (defaults to "latest"):
   - Same as `version="latest"`

### Validation Strategy

Each handler validates against **its subscribed schema version**, not the message version:

- v1 handler receives v2 message → validates against v1 schema → only v1 fields are validated
- v2 handler receives v2 message → validates against v2 schema → all fields validated
- v2 handler receives v1 message → validation fails (missing required field `phone_number`)

---

## Implementation Plan

### Phase 1: Update Handler Matching Logic

**File:** `celery_salt/integrations/dispatcher.py`

```python
# Current logic (too strict):
if handler_version == message_version:
    handlers.append(handler_info)

# New logic (backward compatible):
def should_call_handler(handler_version: str, message_version: Optional[str]) -> bool:
    """
    Determine if handler should be called for this message version.
    
    Rules (assuming subscribers never run higher version than publishers):
    - Handler with specific version receives same or newer message versions
    - Handler with "latest" receives latest or newer message versions
    - Handler with no version (None) defaults to "latest"
    - If handler version < message version, log a warning (subscriber is on old version)
    """
    # Normalize handler version
    if handler_version is None:
        handler_version = "latest"
    
    # If message has no version, only call handlers with "latest" or no version
    if message_version is None:
        return handler_version == "latest" or handler_version is None
    
    # If handler is "latest", it should receive any message
    if handler_version == "latest":
        return True
    
    # Handler with specific version receives same or newer versions
    # Compare versions: "v1" < "v2" < "v3", etc.
    handler_v_num = _extract_version_number(handler_version)
    message_v_num = _extract_version_number(message_version)
    
    # Handler can process same or newer versions (backward compatible)
    can_process = handler_v_num <= message_v_num
    
    # Warn if handler is on older version (subscriber needs to upgrade)
    if can_process and handler_v_num < message_v_num:
        logger.warning(
            f"Handler subscribed to {handler_version} is processing {message_version} message. "
            f"Consider upgrading subscriber to {message_version}."
        )
    
    return can_process
```

### Phase 2: Version Comparison Utility

**File:** `celery_salt/core/versioning.py` (new file)

```python
def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two version strings.
    
    Returns:
        -1 if v1 < v2
         0 if v1 == v2
         1 if v1 > v2
    
    Examples:
        compare_versions("v1", "v2") -> -1
        compare_versions("v2", "v1") -> 1
        compare_versions("v1", "v1") -> 0
    """
    # Extract numeric part (assumes "v1", "v2", etc.)
    def extract_version(version_str: str) -> int:
        if version_str.startswith("v"):
            try:
                return int(version_str[1:])
            except ValueError:
                return 0
        return 0
    
    v1_num = extract_version(v1)
    v2_num = extract_version(v2)
    
    if v1_num < v2_num:
        return -1
    elif v1_num > v2_num:
        return 1
    else:
        return 0
```

### Phase 3: Update Schema Fetching

**File:** `celery_salt/core/decorators.py`

The `@subscribe` decorator already fetches the schema for the specified version. This is correct - each handler validates against its subscribed version, not the message version.

**Current behavior is correct:**
- `@subscribe("user.signup", version="v1")` → fetches v1 schema → validates against v1
- `@subscribe("user.signup", version="v2")` → fetches v2 schema → validates against v2

### Phase 4: Update Dispatcher Filtering

**File:** `celery_salt/integrations/dispatcher.py`

```python
# Filter handlers by version compatibility
handlers = []
for handler_info in all_handlers:
    handler_version = handler_info.get("metadata", {}).get("version", "latest")
    
    if should_call_handler(handler_version, message_version):
        handlers.append(handler_info)
```

---

## Example Scenarios

### Scenario 1: v1 Publisher → v1 Handler

```python
# Publisher
@event("user.signup", version="v1")
class UserSignup:
    user_id: int
    email: str

UserSignup.publish(user_id=123, email="user@example.com")
# Message: {user_id: 123, email: "user@example.com", _tchu_meta: {version: "v1"}}

# Handler
@subscribe("user.signup", version="v1")
def handle_signup(data):
    print(data.user_id, data.email)  # ✅ Works
```

**Result:** ✅ Handler receives message, validates against v1 schema

---

### Scenario 2: v2 Publisher → v1 Handler (Backward Compatibility)

```python
# Publisher (v2)
class UserSignupV2(SaltEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
        phone_number: str  # NEW
    
    class Meta:
        topic = "user.signup"
        version = "v2"

event = UserSignupV2(user_id=123, email="user@example.com", phone_number="555-1234")
event.publish()
# Message: {user_id: 123, email: "user@example.com", phone_number: "555-1234", _tchu_meta: {version: "v2"}}

# Handler (v1 - still in production)
@subscribe("user.signup", version="v1")
def handle_signup(data):
    print(data.user_id, data.email)  # ✅ Works
    # data.phone_number doesn't exist (v1 schema doesn't have it)

# Handler validates against v1 schema:
# - user_id: ✅ Present
# - email: ✅ Present
# - phone_number: ❌ Not in v1 schema, ignored
```

**Result:** ✅ v1 handler receives v2 message, validates against v1 schema, ignores new fields

---

### Scenario 3: v1 Publisher → v2 Handler (Shouldn't Happen)

```python
# Publisher (v1)
@event("user.signup", version="v1")
class UserSignup:
    user_id: int
    email: str

UserSignup.publish(user_id=123, email="user@example.com")
# Message: {user_id: 123, email: "user@example.com", _tchu_meta: {version: "v1"}}

# Handler (v2 - expects new field)
# NOTE: This scenario shouldn't happen because subscribers never run higher version than publishers
# But if it does (edge case), handler should NOT receive the message
@subscribe("user.signup", version="v2")
def handle_signup_v2(data):
    print(data.phone_number)  # ❌ Missing!

# Handler validates against v2 schema:
# - user_id: ✅ Present
# - email: ✅ Present
# - phone_number: ❌ Missing (required in v2) → ValidationError
```

**Result:** ❌ v2 handler should NOT receive v1 messages (validation would fail)

**Implementation:** Handler matching should exclude v2 handlers from v1 messages

**Note:** This scenario is unlikely since subscribers never run higher version than publishers, but we handle it defensively.

---

### Scenario 4: v2 Publisher → v2 Handler

```python
# Publisher (v2)
class UserSignupV2(SaltEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
        phone_number: str
    
    class Meta:
        topic = "user.signup"
        version = "v2"

event = UserSignupV2(user_id=123, email="user@example.com", phone_number="555-1234")
event.publish()

# Handler (v2)
@subscribe("user.signup", version="v2")
def handle_signup_v2(data):
    print(data.user_id, data.email, data.phone_number)  # ✅ All fields available
```

**Result:** ✅ v2 handler receives v2 message, validates against v2 schema

---

## Handler Matching Algorithm

```python
def should_call_handler(handler_version: str, message_version: Optional[str], logger) -> bool:
    """
    Determine if handler should process this message.
    
    Assumes: Subscribers never run higher version than publishers
    
    Args:
        handler_version: Version handler subscribes to ("v1", "v2", "latest", or None)
        message_version: Version of the message ("v1", "v2", etc., or None)
        logger: Logger instance for warnings
    
    Returns:
        True if handler should process message, False otherwise
    """
    # Normalize handler version
    if handler_version is None:
        handler_version = "latest"
    
    # Case 1: Message has no version (legacy/tchu-tchu compatibility)
    if message_version is None:
        # Only handlers with "latest" or no version should receive it
        return handler_version == "latest" or handler_version is None
    
    # Case 2: Handler subscribes to "latest"
    if handler_version == "latest":
        # "latest" handlers receive all messages (they'll get the latest schema)
        # Note: If message version is newer than what "latest" was when handler registered,
        # we should warn (publisher upgraded)
        return True
    
    # Case 3: Handler subscribes to specific version
    # Handler receives messages with same or newer versions (backward compatibility)
    # Handler does NOT receive messages with older versions (shouldn't happen, but handle defensively)
    handler_v_num = _extract_version_number(handler_version)
    message_v_num = _extract_version_number(message_version)
    
    # Handler can process same or newer versions
    can_process = handler_v_num <= message_v_num
    
    # Warn if handler is on older version (subscriber needs to upgrade)
    if can_process and handler_v_num < message_v_num:
        logger.warning(
            f"Handler subscribed to {handler_version} is processing {message_version} message. "
            f"Subscriber is on an older version. Consider upgrading to {message_version}."
        )
    
    return can_process


def _extract_version_number(version_str: str) -> int:
    """Extract numeric version from string like 'v1', 'v2', etc."""
    if version_str.startswith("v"):
        try:
            return int(version_str[1:])
        except ValueError:
            return 0
    return 0
```

---

## Migration Path Example

### Week 1: All services on v1

```python
# Service A (Publisher)
@event("user.signup", version="v1")
class UserSignup:
    user_id: int
    email: str

# Service B (Subscriber)
@subscribe("user.signup", version="v1")
def handle_signup(data):
    ...
```

### Week 2: Service A upgrades to v2, Service B stays on v1

```python
# Service A (Publisher) - UPGRADED
class UserSignupV2(SaltEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
        phone_number: str  # NEW
    
    class Meta:
        topic = "user.signup"
        version = "v2"

# Service B (Subscriber) - STILL ON V1
@subscribe("user.signup", version="v1")
def handle_signup(data):
    # Still works! Receives v2 messages, validates against v1 schema
    print(data.user_id, data.email)  # phone_number ignored
```

### Week 3: Service B upgrades to v2

```python
# Service B (Subscriber) - UPGRADED
@subscribe("user.signup", version="v2")
def handle_signup(data):
    # Now receives v2 messages, validates against v2 schema
    print(data.user_id, data.email, data.phone_number)  # All fields available
```

**Key Benefit:** Zero-downtime migration - services can upgrade independently!

---

## Edge Cases

### Edge Case 1: Handler with "latest" receives v1 message

```python
# Publisher (v1)
@event("user.signup", version="v1")
class UserSignup:
    user_id: int
    email: str

# Handler (latest)
@subscribe("user.signup", version="latest")
def handle_signup(data):
    # Fetches latest schema from registry (might be v2)
    # But message only has v1 fields
    # Validation might fail if v2 schema has required fields not in v1
```

**Solution:** "latest" handlers should validate against the message version, not the latest schema version. Or, we need to handle missing fields gracefully.

**Better Solution:** "latest" handlers should receive the latest schema, but validation should be lenient for missing fields (treat new required fields as optional when message version is older).

### Edge Case 2: Multiple versions in registry

```python
# Registry has:
# - user.signup v1: {user_id, email}
# - user.signup v2: {user_id, email, phone_number}
# - user.signup v3: {user_id, email, phone_number, address}

# Handler subscribes to v1
@subscribe("user.signup", version="v1")
def handle_signup(data):
    ...

# Message arrives with v3
# Handler should receive it, validate against v1 schema
# Only user_id and email are validated, phone_number and address are ignored
```

**Solution:** ✅ Current implementation handles this - handler validates against v1 schema, extra fields ignored.

---

## Implementation Checklist

- [ ] Create `celery_salt/core/versioning.py` with version comparison utilities
- [ ] Update `dispatcher.py` to use backward-compatible handler matching
- [ ] Update handler registration to store version in metadata
- [ ] Update message publishing to include version in `_tchu_meta`
- [ ] Add tests for version matching scenarios
- [ ] Update documentation with versioning examples
- [ ] Consider "latest" handler behavior (should it validate against message version or latest schema?)

---

## Open Questions

1. **"latest" handler behavior**: Should handlers with `version="latest"`:
   - Option A: Always validate against latest schema (might fail on older messages)
   - Option B: Validate against message version (requires fetching message version's schema)
   - Option C: Validate against latest schema, but make new required fields optional for backward compatibility

2. **Version format**: Should we support semantic versioning (v1.0.0) or keep simple (v1, v2)?

3. **Breaking changes**: How do we handle breaking changes (field renamed, type changed)? Should we require a new topic?

---

## Recommended Approach

### For "latest" handlers:

**Option C (Recommended)**: Validate against latest schema, but handle missing fields gracefully.

```python
@subscribe("user.signup", version="latest")
def handle_signup(data):
    # Fetches latest schema (v2) from registry
    # Validates message against v2 schema
    # If message is v1 and missing phone_number:
    #   - If phone_number is required in v2 → ValidationError
    #   - If phone_number is optional in v2 → ✅ Works (None)
```

**Better approach**: "latest" handlers should validate against the **message version's schema**, not the latest schema. This ensures they can handle any version.

```python
# When handler subscribes with version="latest":
# 1. At registration time: Fetch latest schema for validation model creation
# 2. At runtime: Check message version, fetch that version's schema for validation
# 3. This allows "latest" handlers to process any version
```

Actually, this is complex. Let's simplify:

**Simplest approach**: "latest" handlers validate against latest schema. If they need to handle older versions, they should subscribe to a specific version.

---

## Summary

**Core Rules:**
1. **Publisher owns the event**: Publishers control event schemas and versioning
2. **Subscribers never run higher version**: Subscribers are always on same or older version than publishers
3. Handlers with specific version receive same or newer message versions (backward compatible)
4. Handlers with specific version do NOT receive older message versions (defensive check)
5. Handlers with "latest" receive all messages, validate against latest schema
6. Each handler validates against its subscribed schema version, not the message version
7. **Warnings**: Handlers on older versions are warned when receiving newer messages

**Benefits:**
- ✅ Backward compatibility: v1 handlers can process v2 events
- ✅ Publisher control: Publishers manage sunsetting old versions
- ✅ Subscriber awareness: Warnings alert subscribers they're on old versions
- ✅ Gradual migration: Publishers can upgrade first, subscribers upgrade later
- ✅ Type safety: Each handler validates against its expected schema
- ✅ Defensive: Handles edge cases even though they shouldn't occur

**Migration Flow:**
1. Publisher upgrades to v2, starts publishing v2 events
2. v1 subscribers continue working (receive v2, validate against v1, get warning)
3. Subscribers upgrade to v2 when ready (no more warnings)
4. Publisher can eventually stop publishing v1 events (sunset old version)
