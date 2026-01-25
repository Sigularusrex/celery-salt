# Implementation Plan: Generic Serializer Support

## Goal

Create a pluggable serializer adapter system that supports any validation/serialization format:

- **DRF Serializers** (existing)
- **Pydantic Models** (new)
- **Protocol Buffers** (new)
- **Dataclasses** (new)
- **msgspec Structs** (new)
- **Custom adapters** (extensible)

This makes tchu-tchu fully framework-agnostic while maintaining:

1. **Full backward compatibility** - DRF serializers continue to work unchanged
2. **Interoperability** - Services can mix formats freely (JSON wire format)
3. **Authorization support** - Each adapter can implement context injection
4. **Zero migration required** - Opt-in feature, existing code unchanged
5. **Extensibility** - Users can register custom adapters

---

## Key Insight: Wire Format is Just JSON

```
Publisher (Pydantic)  →  JSON  →  Subscriber (DRF)      ✅ Works!
Publisher (DRF)       →  JSON  →  Subscriber (Protobuf) ✅ Works!
Publisher (Dataclass) →  JSON  →  Subscriber (Pydantic) ✅ Works!
```

**Serializers only validate on each end.** The wire format is always JSON - subscribers don't care how publishers validated their data.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      SerializerAdapter (ABC)                    │
│  - can_handle(cls) → bool                                       │
│  - validate(data, context) → dict                               │
│  - inject_authorization(data, context) → dict                   │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  DRFAdapter   │   │ PydanticAdapter │   │ ProtobufAdapter │
└───────────────┘   └─────────────────┘   └─────────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ rest_framework│   │    pydantic     │   │ google.protobuf │
│  .serializers │   │   .BaseModel    │   │    .Message     │
└───────────────┘   └─────────────────┘   └─────────────────┘

                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         TchuEvent                               │
│  serialize_request(data, context)                               │
│      │                                                          │
│      └── adapter = get_adapter(request_serializer_class)        │
│          adapter.validate(data, context) → validated_data       │
│                                                                 │
│  Result: self.validated_data (always a dict)                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation

### Step 1: Base Adapter Protocol

```python
# tchu_tchu/serializers/base.py

from abc import ABC, abstractmethod
from typing import Any, Dict, Type, Optional
import logging

logger = logging.getLogger(__name__)


class SerializerAdapter(ABC):
    """
    Base adapter for any serialization/validation format.
    
    Implement this to add support for new formats like Protobuf, msgspec, etc.
    """
    
    def __init__(self, serializer_class: Type):
        self.serializer_class = serializer_class
    
    @classmethod
    @abstractmethod
    def can_handle(cls, serializer_class: Type) -> bool:
        """
        Return True if this adapter can handle the given class.
        
        This is used for auto-detection. The first adapter that returns True
        will be used.
        """
        pass
    
    @abstractmethod
    def validate(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        skip_authorization: bool = False,
        skip_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate input data and return a dict.
        
        Args:
            data: Input data to validate
            context: Optional context (may contain 'request' for auth)
            skip_authorization: Whether to skip auth validation
            skip_reason: Reason for skipping auth (for logging)
        
        Returns:
            Validated data as a dict
        
        Raises:
            ValidationError: If validation fails
        """
        pass
    
    def inject_authorization(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        skip_authorization: bool = False,
        skip_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Inject authorization fields from context into data.
        
        Override this in subclasses to customize auth injection.
        Default implementation does nothing (for formats without auth support).
        """
        return data
    
    @classmethod
    def extract_id(cls, obj: Any) -> Any:
        """Helper to extract ID from an object."""
        if obj is None:
            return None
        if hasattr(obj, 'id'):
            return obj.id
        if hasattr(obj, 'pk'):
            return obj.pk
        return obj


class ValidationError(Exception):
    """Raised when validation fails."""
    
    def __init__(self, message: str, errors: Optional[Dict] = None):
        super().__init__(message)
        self.errors = errors or {}
```

### Step 2: Adapter Registry

```python
# tchu_tchu/serializers/registry.py

from typing import List, Type, Optional
import logging

from tchu_tchu.serializers.base import SerializerAdapter

logger = logging.getLogger(__name__)

# Global adapter registry (ordered - first match wins)
_adapters: List[Type[SerializerAdapter]] = []


def register_adapter(adapter_class: Type[SerializerAdapter], priority: int = 0):
    """
    Register a serializer adapter.
    
    Args:
        adapter_class: The adapter class to register
        priority: Higher priority adapters are checked first (default 0)
    
    Usage:
        @register_adapter
        class MyCustomAdapter(SerializerAdapter):
            ...
    """
    # Insert at position based on priority
    for i, existing in enumerate(_adapters):
        if priority > getattr(existing, '_priority', 0):
            _adapters.insert(i, adapter_class)
            adapter_class._priority = priority
            logger.debug(f"Registered adapter {adapter_class.__name__} at position {i}")
            return adapter_class
    
    _adapters.append(adapter_class)
    adapter_class._priority = priority
    logger.debug(f"Registered adapter {adapter_class.__name__} at end")
    return adapter_class


def get_adapter(serializer_class: Type) -> Optional[SerializerAdapter]:
    """
    Find an adapter that can handle the given serializer class.
    
    Returns:
        Instantiated adapter, or None if no adapter found
    """
    if serializer_class is None:
        return None
    
    for adapter_cls in _adapters:
        if adapter_cls.can_handle(serializer_class):
            logger.debug(f"Using {adapter_cls.__name__} for {serializer_class.__name__}")
            return adapter_cls(serializer_class)
    
    logger.warning(f"No adapter found for {serializer_class}")
    return None


def list_adapters() -> List[Type[SerializerAdapter]]:
    """Return list of registered adapters in priority order."""
    return _adapters.copy()


def clear_adapters():
    """Clear all registered adapters (useful for testing)."""
    _adapters.clear()
```

### Step 3: DRF Adapter (Existing Logic)

```python
# tchu_tchu/serializers/drf_adapter.py

from typing import Any, Dict, Type, Optional
import logging

from tchu_tchu.serializers.base import SerializerAdapter, ValidationError
from tchu_tchu.serializers.registry import register_adapter

logger = logging.getLogger(__name__)


@register_adapter(priority=10)  # High priority - check first for Django projects
class DRFAdapter(SerializerAdapter):
    """
    Adapter for Django REST Framework serializers.
    
    Supports:
    - Standard DRF validation
    - HiddenField for authorization injection
    - Context passing
    """
    
    @classmethod
    def can_handle(cls, serializer_class: Type) -> bool:
        """Check if class is a DRF serializer."""
        try:
            from rest_framework.serializers import Serializer
            return isinstance(serializer_class, type) and issubclass(serializer_class, Serializer)
        except ImportError:
            return False
    
    def validate(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        skip_authorization: bool = False,
        skip_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate using DRF serializer."""
        serializer_kwargs = {"data": data}
        
        if context:
            serializer_kwargs["context"] = context
        
        # Pass auth skip flags to serializer if supported
        if skip_authorization:
            serializer_kwargs["skip_authorization"] = skip_authorization
            serializer_kwargs["skip_reason"] = skip_reason
        
        try:
            serializer = self.serializer_class(**serializer_kwargs)
        except TypeError:
            # Serializer doesn't accept skip_authorization kwargs
            serializer_kwargs.pop("skip_authorization", None)
            serializer_kwargs.pop("skip_reason", None)
            serializer = self.serializer_class(**serializer_kwargs)
        
        if not serializer.is_valid():
            raise ValidationError(
                f"DRF validation failed: {serializer.errors}",
                errors=serializer.errors
            )
        
        return dict(serializer.validated_data)
```

### Step 4: Pydantic Adapter

```python
# tchu_tchu/serializers/pydantic_adapter.py

from typing import Any, Dict, Type, Optional
import logging

from tchu_tchu.serializers.base import SerializerAdapter, ValidationError
from tchu_tchu.serializers.registry import register_adapter

logger = logging.getLogger(__name__)


@register_adapter(priority=5)
class PydanticAdapter(SerializerAdapter):
    """
    Adapter for Pydantic models.
    
    Supports:
    - Pydantic v2 validation
    - Context passing via model_validate(context=...)
    - Authorization via TchuAuthorizationModel base class
    """
    
    @classmethod
    def can_handle(cls, serializer_class: Type) -> bool:
        """Check if class is a Pydantic model."""
        try:
            from pydantic import BaseModel
            return isinstance(serializer_class, type) and issubclass(serializer_class, BaseModel)
        except ImportError:
            return False
    
    def validate(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        skip_authorization: bool = False,
        skip_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate using Pydantic model."""
        try:
            from pydantic import ValidationError as PydanticValidationError
        except ImportError:
            raise ValidationError("Pydantic is not installed")
        
        # Build validation context
        validation_context = context.copy() if context else {}
        if skip_authorization:
            validation_context['skip_authorization'] = True
            validation_context['skip_reason'] = skip_reason
        
        try:
            validated_model = self.serializer_class.model_validate(
                data,
                context=validation_context
            )
            
            # Convert to dict, excluding None and internal fields
            return validated_model.model_dump(
                exclude_none=True,
                exclude={'_skip_authorization', '_skip_reason'}
            )
            
        except PydanticValidationError as e:
            raise ValidationError(
                f"Pydantic validation failed: {e}",
                errors=e.errors()
            )
```

### Step 5: Protobuf Adapter

```python
# tchu_tchu/serializers/protobuf_adapter.py

from typing import Any, Dict, Type, Optional
import logging

from tchu_tchu.serializers.base import SerializerAdapter, ValidationError
from tchu_tchu.serializers.registry import register_adapter

logger = logging.getLogger(__name__)


@register_adapter(priority=3)
class ProtobufAdapter(SerializerAdapter):
    """
    Adapter for Protocol Buffer messages.
    
    Supports:
    - Protobuf message validation
    - JSON serialization (for wire format compatibility)
    - Binary serialization (for performance)
    
    Note: Authorization must be handled in message definition or manually.
    """
    
    @classmethod
    def can_handle(cls, serializer_class: Type) -> bool:
        """Check if class is a Protobuf message."""
        try:
            from google.protobuf.message import Message
            return isinstance(serializer_class, type) and issubclass(serializer_class, Message)
        except ImportError:
            return False
    
    def validate(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        skip_authorization: bool = False,
        skip_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate by constructing Protobuf message."""
        try:
            from google.protobuf.json_format import MessageToDict, ParseDict
        except ImportError:
            raise ValidationError("protobuf is not installed")
        
        try:
            # Inject authorization if context provided
            if context and not skip_authorization:
                data = self.inject_authorization(data, context, skip_authorization, skip_reason)
            
            # Create message from dict (validates field types)
            message = ParseDict(data, self.serializer_class())
            
            # Convert back to dict for wire format
            return MessageToDict(
                message,
                preserving_proto_field_name=True,
                including_default_value_fields=False
            )
            
        except Exception as e:
            raise ValidationError(f"Protobuf validation failed: {e}")
    
    def inject_authorization(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        skip_authorization: bool = False,
        skip_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Inject auth fields if they exist in the message definition."""
        if not context:
            return data
        
        request = context.get('request')
        if not request:
            return data
        
        # Only inject if fields exist in proto definition
        descriptor = self.serializer_class.DESCRIPTOR
        field_names = {f.name for f in descriptor.fields}
        
        if 'company' in field_names:
            data['company'] = self.extract_id(getattr(request, 'company', None))
        if 'user_company' in field_names:
            data['user_company'] = self.extract_id(getattr(request, 'user_company', None))
        if 'user' in field_names:
            data['user'] = self.extract_id(getattr(request, 'user', None))
        
        return data
```

### Step 6: Dataclass Adapter

```python
# tchu_tchu/serializers/dataclass_adapter.py

from typing import Any, Dict, Type, Optional
import logging
import dataclasses

from tchu_tchu.serializers.base import SerializerAdapter, ValidationError
from tchu_tchu.serializers.registry import register_adapter

logger = logging.getLogger(__name__)


@register_adapter(priority=1)  # Low priority - check last
class DataclassAdapter(SerializerAdapter):
    """
    Adapter for Python dataclasses.
    
    Provides basic validation by attempting to construct the dataclass.
    For full validation, use Pydantic's dataclass decorator instead.
    """
    
    @classmethod
    def can_handle(cls, serializer_class: Type) -> bool:
        """Check if class is a dataclass."""
        return dataclasses.is_dataclass(serializer_class) and isinstance(serializer_class, type)
    
    def validate(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        skip_authorization: bool = False,
        skip_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate by constructing dataclass instance."""
        try:
            # Inject authorization if needed
            if context and not skip_authorization:
                data = self.inject_authorization(data, context, skip_authorization, skip_reason)
            
            # Get expected fields
            fields = {f.name for f in dataclasses.fields(self.serializer_class)}
            
            # Filter data to only include valid fields
            filtered_data = {k: v for k, v in data.items() if k in fields}
            
            # Construct instance (validates types if using Python 3.10+ strict mode)
            instance = self.serializer_class(**filtered_data)
            
            # Convert back to dict
            return dataclasses.asdict(instance)
            
        except TypeError as e:
            raise ValidationError(f"Dataclass validation failed: {e}")
    
    def inject_authorization(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        skip_authorization: bool = False,
        skip_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Inject auth fields if they exist in the dataclass."""
        if not context:
            return data
        
        request = context.get('request')
        if not request:
            return data
        
        fields = {f.name for f in dataclasses.fields(self.serializer_class)}
        
        if 'company' in fields:
            data['company'] = self.extract_id(getattr(request, 'company', None))
        if 'user_company' in fields:
            data['user_company'] = self.extract_id(getattr(request, 'user_company', None))
        if 'user' in fields:
            data['user'] = self.extract_id(getattr(request, 'user', None))
        
        return data
```

### Step 7: Pydantic Authorization Base Model

```python
# tchu_tchu/serializers/pydantic_models.py

import logging
from typing import Optional, Any, Dict
from pydantic import BaseModel, model_validator, ConfigDict

logger = logging.getLogger(__name__)


class TchuAuthorizationModel(BaseModel):
    """
    Pydantic base model with authorization support.
    
    Equivalent to DRF's EventAuthorizationSerializer pattern:
    - Injects company, user, user_company from request context
    - Validates authorization fields are present
    - Supports skip_authorization for system events
    
    Usage:
        class MyEventRequest(TchuAuthorizationModel):
            my_field: str
            another_field: int
    """
    model_config = ConfigDict(extra='allow')
    
    # Authorization fields - injected from context
    company: Optional[Any] = None
    user_company: Optional[Any] = None
    user: Optional[Any] = None
    
    @model_validator(mode='before')
    @classmethod
    def inject_authorization(cls, data: Dict[str, Any], info) -> Dict[str, Any]:
        """
        Inject authorization from context and validate.
        
        Context can contain:
        - request: Object with .company, .user, .user_company attributes
        - skip_authorization: bool - Skip auth validation
        - skip_reason: str - Reason for skipping (for logging)
        """
        context = info.context or {}
        skip_auth = context.get('skip_authorization', False)
        skip_reason = context.get('skip_reason')
        
        if skip_auth:
            cls._log_skipped_authorization(data, skip_reason)
            data['company'] = None
            data['user_company'] = None
            data['user'] = None
            return data
        
        # Inject from request context
        request = context.get('request')
        if request:
            data['company'] = cls._extract_id(getattr(request, 'company', None))
            data['user_company'] = cls._extract_id(getattr(request, 'user_company', None))
            data['user'] = cls._extract_id(getattr(request, 'user', None))
        
        # Validate required fields
        missing = []
        if not data.get('company'):
            missing.append('company')
        if not data.get('user_company'):
            missing.append('user_company')
        if not data.get('user'):
            missing.append('user')
        
        if missing:
            raise ValueError(
                f"Authorization fields required in request context: {', '.join(missing)}"
            )
        
        return data
    
    @staticmethod
    def _extract_id(obj: Any) -> Any:
        """Extract ID from object or return as-is."""
        if obj is None:
            return None
        if hasattr(obj, 'id'):
            return obj.id
        if hasattr(obj, 'pk'):
            return obj.pk
        return obj
    
    @classmethod
    def _log_skipped_authorization(cls, data: Dict, reason: Optional[str]):
        """Log when authorization is intentionally skipped."""
        logger.warning(
            f"SECURITY: Authorization skipped for {cls.__name__}. "
            f"Reason: {reason or 'Not provided'}. "
            f"Data keys: {list(data.keys())}"
        )


class TchuModel(BaseModel):
    """
    Simple Pydantic base model without authorization.
    
    Use this for events that don't require authorization context.
    
    Usage:
        class SimpleEventRequest(TchuModel):
            my_field: str
    """
    model_config = ConfigDict(extra='forbid')
```

### Step 8: Package __init__.py

```python
# tchu_tchu/serializers/__init__.py

from tchu_tchu.serializers.base import SerializerAdapter, ValidationError
from tchu_tchu.serializers.registry import (
    register_adapter,
    get_adapter,
    list_adapters,
    clear_adapters,
)

# Import adapters to register them
# Each adapter auto-registers via @register_adapter decorator
try:
    from tchu_tchu.serializers.drf_adapter import DRFAdapter
except ImportError:
    pass  # DRF not installed

try:
    from tchu_tchu.serializers.pydantic_adapter import PydanticAdapter
    from tchu_tchu.serializers.pydantic_models import TchuAuthorizationModel, TchuModel
except ImportError:
    pass  # Pydantic not installed

try:
    from tchu_tchu.serializers.protobuf_adapter import ProtobufAdapter
except ImportError:
    pass  # Protobuf not installed

try:
    from tchu_tchu.serializers.dataclass_adapter import DataclassAdapter
except ImportError:
    pass  # Should always work (stdlib)

__all__ = [
    # Base
    "SerializerAdapter",
    "ValidationError",
    # Registry
    "register_adapter",
    "get_adapter",
    "list_adapters",
    "clear_adapters",
    # Pydantic models (if available)
    "TchuAuthorizationModel",
    "TchuModel",
]
```

### Step 9: Update events.py

```python
# In tchu_tchu/events.py - modify serialize_request()

from tchu_tchu.serializers import get_adapter, ValidationError as AdapterValidationError

def serialize_request(
    self,
    data: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    skip_authorization: bool = False,
    skip_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate and serialize request data.
    
    Automatically detects serializer type (DRF, Pydantic, Protobuf, etc.)
    and uses the appropriate adapter.
    """
    try:
        if self.request_serializer_class is None:
            # No serializer - pass through
            self.validated_data = data if isinstance(data, dict) else loads_message(data)
        else:
            # Get appropriate adapter
            adapter = get_adapter(self.request_serializer_class)
            
            if adapter is None:
                raise SerializationError(
                    f"No adapter found for serializer type: {self.request_serializer_class}. "
                    f"Install the appropriate package (pydantic, protobuf, etc.) or "
                    f"register a custom adapter."
                )
            
            # Validate using adapter
            self.validated_data = adapter.validate(
                data=data,
                context=context,
                skip_authorization=skip_authorization,
                skip_reason=skip_reason,
            )
        
        self.context = context
        return self.validated_data
        
    except AdapterValidationError as e:
        logger.error(f"Validation failed: {e}", exc_info=True)
        raise SerializationError(f"Validation failed: {e}")
    except Exception as e:
        logger.error(f"Request serialization failed: {e}", exc_info=True)
        raise SerializationError(f"Failed to serialize request: {e}")
```

---

## Usage Examples

### Example 1: DRF Serializer (Existing - Unchanged)

```python
from rest_framework import serializers
from cs_common.events.helpers import EventAuthorizationSerializer
from tchu_tchu import TchuEvent


class DataExchangeRequest(EventAuthorizationSerializer):
    model_identifier = serializers.CharField(max_length=100)
    file_path = serializers.CharField(max_length=500)


class DataExchangeEvent(TchuEvent):
    class Meta:
        topic = "coolset.data_exchange.initiated"
        request_serializer_class = DataExchangeRequest
```

### Example 2: Pydantic Model

```python
from pydantic import Field
from tchu_tchu import TchuEvent
from tchu_tchu.serializers import TchuAuthorizationModel


class DataExchangeRequest(TchuAuthorizationModel):
    model_identifier: str = Field(max_length=100)
    file_path: str = Field(max_length=500)


class DataExchangeEvent(TchuEvent):
    class Meta:
        topic = "coolset.data_exchange.initiated"
        request_serializer_class = DataExchangeRequest
```

### Example 3: Protocol Buffers

```protobuf
// data_exchange.proto
syntax = "proto3";

message DataExchangeRequest {
    string model_identifier = 1;
    string file_path = 2;
    int32 company = 3;
    int32 user = 4;
    int32 user_company = 5;
}
```

```python
from my_protos.data_exchange_pb2 import DataExchangeRequest
from tchu_tchu import TchuEvent


class DataExchangeEvent(TchuEvent):
    class Meta:
        topic = "coolset.data_exchange.initiated"
        request_serializer_class = DataExchangeRequest  # Protobuf message!
```

### Example 4: Python Dataclass

```python
from dataclasses import dataclass
from typing import Optional
from tchu_tchu import TchuEvent


@dataclass
class DataExchangeRequest:
    model_identifier: str
    file_path: str
    company: Optional[int] = None
    user: Optional[int] = None
    user_company: Optional[int] = None


class DataExchangeEvent(TchuEvent):
    class Meta:
        topic = "coolset.data_exchange.initiated"
        request_serializer_class = DataExchangeRequest
```

### Example 5: Custom Adapter (msgspec)

```python
from tchu_tchu.serializers import SerializerAdapter, register_adapter, ValidationError


@register_adapter(priority=4)
class MsgspecAdapter(SerializerAdapter):
    """Adapter for msgspec Structs."""
    
    @classmethod
    def can_handle(cls, serializer_class):
        try:
            import msgspec
            return isinstance(serializer_class, type) and issubclass(serializer_class, msgspec.Struct)
        except ImportError:
            return False
    
    def validate(self, data, context=None, skip_authorization=False, skip_reason=None):
        import msgspec
        try:
            instance = msgspec.convert(data, self.serializer_class)
            return msgspec.to_builtins(instance)
        except msgspec.ValidationError as e:
            raise ValidationError(f"msgspec validation failed: {e}")


# Usage
import msgspec

class DataExchangeRequest(msgspec.Struct):
    model_identifier: str
    file_path: str

class DataExchangeEvent(TchuEvent):
    class Meta:
        topic = "coolset.data_exchange.initiated"
        request_serializer_class = DataExchangeRequest
```

---

## Interoperability Matrix

| Publisher | Subscriber | Wire Format | Works? |
|-----------|------------|-------------|--------|
| DRF | DRF | JSON | ✅ |
| DRF | Pydantic | JSON | ✅ |
| DRF | Protobuf | JSON | ✅ |
| DRF | Dataclass | JSON | ✅ |
| Pydantic | DRF | JSON | ✅ |
| Pydantic | Pydantic | JSON | ✅ |
| Pydantic | Protobuf | JSON | ✅ |
| Protobuf | DRF | JSON | ✅ |
| Protobuf | Pydantic | JSON | ✅ |
| Protobuf | Protobuf | JSON | ✅ |
| Dataclass | Any | JSON | ✅ |
| None | Any | JSON | ✅ |

**All combinations work** because:
1. Validation happens independently on each side
2. Wire format is always JSON dict
3. `validated_data` is always a Python dict

---

## Authorization Support by Format

| Format | Auth Method | Auto-inject | Validation |
|--------|-------------|-------------|------------|
| **DRF** | `HiddenField` + `validate()` | ✅ | ✅ |
| **Pydantic** | `TchuAuthorizationModel` | ✅ | ✅ |
| **Protobuf** | Field definitions | ✅ (if fields exist) | ❌ Manual |
| **Dataclass** | Field definitions | ✅ (if fields exist) | ❌ Manual |
| **msgspec** | Custom adapter | ⚠️ Implement yourself | ⚠️ Implement yourself |

---

## Performance Comparison

| Format | Validation Speed | Serialization | Schema Evolution |
|--------|------------------|---------------|------------------|
| **DRF** | Slow (~10ms) | JSON | Python code |
| **Pydantic** | Fast (~1ms) | JSON | Python code |
| **Protobuf** | Very Fast (~0.5ms) | JSON/Binary | .proto files |
| **Dataclass** | Fast (~1ms) | JSON | Python code |
| **msgspec** | Fastest (~0.1ms) | JSON/MessagePack | Python code |

---

## Files to Create

```
tchu_tchu/
├── serializers/
│   ├── __init__.py           # Package exports
│   ├── base.py               # SerializerAdapter ABC
│   ├── registry.py           # Adapter registry
│   ├── drf_adapter.py        # DRF support
│   ├── pydantic_adapter.py   # Pydantic support
│   ├── pydantic_models.py    # TchuAuthorizationModel, TchuModel
│   ├── protobuf_adapter.py   # Protobuf support
│   └── dataclass_adapter.py  # Dataclass support
```

## Files to Modify

```
tchu_tchu/
├── __init__.py               # Export TchuAuthorizationModel, TchuModel
├── events.py                 # Use adapter registry in serialize_request()
```

---

## Migration Path

### Phase 1: Add Adapter System (v3.1.0)
- Create `serializers/` package with all adapters
- Modify `events.py` to use adapter registry
- **Zero breaking changes** - DRF continues to work

### Phase 2: Documentation & Examples
- Update README with examples for each format
- Add migration guide for teams wanting Pydantic

### Phase 3: Optional Dependencies
- Update `pyproject.toml` with optional dependency groups:
  ```toml
  [project.optional-dependencies]
  drf = ["djangorestframework>=3.14"]
  pydantic = ["pydantic>=2.0"]
  protobuf = ["protobuf>=4.0"]
  all = ["djangorestframework>=3.14", "pydantic>=2.0", "protobuf>=4.0"]
  ```

---

## Testing Plan

### Unit Tests

1. **Adapter Detection**
   - `is_drf_serializer()` correctly identifies DRF classes
   - `is_pydantic_model()` correctly identifies Pydantic classes
   - `is_protobuf_message()` correctly identifies Protobuf classes
   - Detection fails gracefully when library not installed

2. **Validation**
   - Each adapter validates correctly
   - Validation errors are properly formatted
   - Invalid data raises `ValidationError`

3. **Authorization**
   - Context injection works for each format
   - `skip_authorization` bypasses validation
   - Missing auth fields raise appropriate error

### Integration Tests

1. **Cross-format Communication**
   - DRF publisher → Pydantic subscriber
   - Pydantic publisher → DRF subscriber
   - Protobuf publisher → DRF subscriber

2. **Real Events**
   - Publish event with each format
   - Subscribe and validate with different format

---

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Supported formats** | DRF only | DRF, Pydantic, Protobuf, Dataclass, Custom |
| **Django dependency** | Required | Optional |
| **Authorization** | DRF HiddenField | Format-specific adapters |
| **Extensibility** | None | Custom adapter registration |
| **Breaking changes** | N/A | None |
| **Performance** | DRF speed | Choose your speed |
