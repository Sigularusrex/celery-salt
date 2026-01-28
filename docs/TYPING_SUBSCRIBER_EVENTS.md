# Typing Events When the Subscribing App Doesn't Have the Class

When you subscribe to an event in an app that **does not** define (or import) the publisher's event class, the handler still receives a **Pydantic model instance**—but that model is created at runtime from the schema registry, so you don't have its type in your codebase. Here are practical ways to type it.

## Can I type with the full event class?

**No.** The handler receives only the **payload** (the validated event data), not an instance of the full event class.

- The **full event class** (e.g. `UserSignup` as a `SaltEvent` subclass or `@event` class) has: `.publish()`, `.Schema`, `.Meta`, `.data`, etc.
- The **handler** receives a plain Pydantic model instance with just the event fields (`user_id`, `email`, …). It does not have `.publish()`, `.data`, or other event methods/attributes.

So typing as `def handler(data: UserSignup)` is wrong: `data` is never a `UserSignup` instance. You should type the **payload/schema** only.

**When you do have the event class** (e.g. shared package or same codebase), use the **schema type** from it:

- **Class-based API (SaltEvent):** Use the nested `Schema` model — that *is* the payload type.

  ```python
  from my_events import UserSignup  # SaltEvent subclass
  from celery_salt import subscribe

  @subscribe("user.signup.completed")
  def send_welcome_email(data: UserSignup.Schema) -> str:
      return f"Welcome to {data.email}"  # full autocomplete
  ```

- **Decorator API (@event):** The payload type is the Pydantic model created by the decorator (stored as `_celerysalt_model`). You can type with a matching Pydantic model or Protocol (Options 1–2 below), or use a type alias if you have the event class:

  ```python
  from my_events import UserSignup  # @event class
  from celery_salt import subscribe

  # Payload type is the decorator's internal model
  UserSignupPayload = UserSignup._celerysalt_model

  @subscribe("user.signup.completed")
  def send_welcome_email(data: UserSignupPayload) -> str:
      return f"Welcome to {data.email}"
  ```

So: type the **payload** (schema), not the full event class. Use `UserSignup.Schema` for SaltEvent, or a matching model / Protocol / `_celerysalt_model` for the decorator.

## Option 1: Define a Matching Pydantic Model (recommended)

Define a Pydantic model in the subscriber with the **same fields** as the event. Use it only for type hints. At runtime the handler receives a dynamically-created model from the registry; it has the same shape, so your type checker and IDE are happy.

```python
from pydantic import BaseModel
from celery_salt import subscribe

# Subscriber-only: type stub matching the event schema (same topic/version as publisher)
class UserSignupData(BaseModel):
    user_id: int
    email: str
    company_id: int
    signup_source: str = "web"

@subscribe("user.signup.completed")
def send_welcome_email(data: UserSignupData) -> str:
    # Full type hints and autocomplete
    return f"Welcome to {data.email}"
```

- **Pros:** Strong typing, IDE autocomplete, same shape as runtime object.
- **Note:** `isinstance(data, UserSignupData)` is `False` at runtime (the real class is created from the registry). Use the type only for annotations.

---

## Option 2: Use a Protocol (structural typing)

If you don't want a Pydantic model in the subscriber, use a `Protocol` that describes the attributes. The runtime object is still a Pydantic model; the protocol only describes its shape for the type checker.

```python
from typing import Protocol
from celery_salt import subscribe

class UserSignupData(Protocol):
    user_id: int
    email: str
    company_id: int
    signup_source: str

@subscribe("user.signup.completed")
def send_welcome_email(data: UserSignupData) -> str:
    return f"Welcome to {data.email}"
```

- **Pros:** No Pydantic in the subscriber, pure structural typing.
- **Cons:** No runtime validation from this type; validation is already done by the dispatcher using the schema.

---

## Option 3: Shared Schema Package

When publisher and subscriber are separate services, define the event schema once in a **shared package** (or shared module in a monorepo) and use it in both:

- **Publisher:** uses the shared model for the event (e.g. `@event` + that model or a class that references it).
- **Subscriber:** imports the same model and uses it as the type of `data`.

```python
# shared_events/schemas.py (used by both apps)
from pydantic import BaseModel

class UserSignupData(BaseModel):
    user_id: int
    email: str
    company_id: int
    signup_source: str = "web"
```

```python
# subscriber app
from celery_salt import subscribe
from shared_events.schemas import UserSignupData

@subscribe("user.signup.completed")
def send_welcome_email(data: UserSignupData) -> str:
    return f"Welcome to {data.email}"
```

- **Pros:** Single source of truth, same type in both apps.
- **Cons:** Requires a shared dependency and keeping it in sync with the schema registry.

---

## Option 4: No type (or generic)

You can leave the parameter untyped or use a generic type. You lose static typing but the code still runs; the dispatcher still validates payloads against the schema.

```python
@subscribe("user.signup.completed")
def send_welcome_email(data):  # or data: Any
    return f"Welcome to {data.email}"
```

---

## Summary

| Approach              | Typing | Runtime check | Shared dependency |
|-----------------------|--------|----------------|-------------------|
| Matching Pydantic     | ✅     | ❌*            | No                |
| Protocol              | ✅     | ❌             | No                |
| Shared schema package | ✅     | ❌*            | Yes               |
| No type               | ❌     | N/A            | No                |

\*The object is already validated by the dispatcher using the schema registry; you don't need `isinstance` on your type stub.

**Recommendation:** Use **Option 1** (matching Pydantic model in the subscriber) when you want good typing without a shared package; use **Option 3** when you can maintain a shared schema package.
