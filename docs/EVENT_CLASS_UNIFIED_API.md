# Unified API: SaltEvent In, SaltEvent-Like Out

This document states the design principle for **class-based events** in CelerySalt: when you subscribe with a `SaltEvent` class, you should always receive an instance of that class; when you get an RPC response back, you should get a response object with the same ergonomics (property access, `.payload`).

---

## Design Principle

1. **Subscribe with a SaltEvent class → receive an instance of that SaltEvent.**  
   You can access every field like `event.name`, `event.id`, and use `event.payload` for the serialized dict.

2. **Subscribing = you see the schema (request).**  
   The handler receives the **event instance**: `event.data` is the validated Schema, `event.payload` is the request body as a dict, and `event.<field>` proxies to the schema.

3. **RPC call return = you see the response.**  
   The caller should get a **response object** with the same ergonomics: `.payload` for the JSON-serializable body (dict or list), and attribute access (e.g. `response.result`, `response.root`) for the validated Response/Error model.

So: one consistent shape. **Publishing** uses an event instance (`event.payload`, `event.publish()`). **Subscribing** receives an event instance (`event.payload`, `event.<field>`). **RPC call** returns a response instance (`response.payload`, `response.<field>`).

---

## Current Behavior in CelerySalt

### Subscribing with a SaltEvent class

When you register a handler with a **SaltEvent subclass** as the topic (or as `event_cls`), the handler receives a **full event instance**:

```python
from celery_salt import SaltEvent, subscribe
from pydantic import BaseModel

class UserSignup(SaltEvent):
    class Schema(BaseModel):
        user_id: int
        email: str
    class Meta:
        topic = "user.signup"

@subscribe(UserSignup)  # topic + version inferred from UserSignup.Meta
def send_welcome(evt: UserSignup):
    # evt is an instance of UserSignup
    assert hasattr(evt, "data")   # validated Schema
    assert hasattr(evt, "payload") # dict
    print(evt.user_id, evt.email)  # attribute access
    print(evt.payload)             # {"user_id": 1, "email": "..."}
```

So: **subscribe with event class → receive SaltEvent instance.** Property access and `.payload` work as above.

### Subscribing by topic string only

If you use `@subscribe("user.signup")` **without** passing the event class, the handler receives only the **validated payload** (a Pydantic model created from the schema registry), not a full `UserSignup` instance. You get `.payload`-like data (the model’s fields) but not `.publish()`, `.data` as the event’s Schema, etc. See [TYPING_SUBSCRIBER_EVENTS.md](TYPING_SUBSCRIBER_EVENTS.md) for typing options in that case.

**Recommendation:** When you have the event class (same codebase or shared package), subscribe with the class so the handler always receives a SaltEvent instance.

### RPC: caller side

When you call `event.call()` on an RPC event, CelerySalt returns a **SaltResponse** wrapper that has:

- `response.event` — the SaltEvent instance that made the call  
- `response.data` — the validated Response or Error model  
- `response.payload` — JSON-serializable dict or list (for DRF/JsonResponse; handles `RootModel[list[...]]` as a bare list)  
- Attribute access (e.g. `response.result`, `response.root`) proxied to `response.data`

Usage is symmetric: **publish** with an event instance; **subscribe** with an event instance; **call RPC** and get a **SaltResponse** instance with the same kind of property access and `.payload`.

---

## Summary Table

| Role            | You have                         | You get                            | Access pattern                          |
|----------------|----------------------------------|------------------------------------|-----------------------------------------|
| Publish        | SaltEvent instance               | —                                  | `event.payload`, `event.<field>`, `event.publish()` |
| Subscribe      | Handler registered with EventClass | SaltEvent instance (that class)  | `event.payload`, `event.<field>`         |
| Subscribe      | Handler by topic only            | Validated payload (Pydantic model) | `data.<field>` (no `.payload` on event)  |
| RPC call       | SaltEvent instance               | SaltResponse                       | `response.payload`, `response.<field>`, `response.data` |

The goal is: **if you use the event class (subscribe or call), you always get an object that has `.payload` and attribute access** — event instance when subscribing, response instance when calling RPC.

---

## How FastStream Does It

[FastStream](https://github.com/ag2ai/faststream) is an async framework for Kafka, RabbitMQ, NATS, Redis with Pydantic validation and AsyncAPI docs.

### Request/response shape

- **Handlers receive a single typed message.** You declare the type (e.g. a Pydantic model or primitive); the broker parses the body and injects that type. There is no separate “event class” that wraps Schema + Meta + methods.
- **Example:** `async def handle_msg(data: User) -> str` — `data` is the **Pydantic model** `User`, not a wrapper with `.payload` and `.publish()`.
- **Response:** The return value is what gets published (e.g. string, dict, or another Pydantic model). No built-in “response object” with `.payload`; you just return the value and FastStream serializes it.

So in FastStream:

- You do **not** get a single “event class” that has both request schema and response schema and methods like `.publish()` / `.respond()`.
- You get **request type in, response type out** (functions with typed args and return). Same ergonomics as many RPC/fastapi-style APIs: type in, type out.
- They rely on **Pydantic + type hints** for validation and docs, and on **dependency injection** for context (Logger, etc.), not on a unified Event/Response object API.

### Contrast with CelerySalt

| Aspect              | CelerySalt (goal)                    | FastStream                          |
|---------------------|--------------------------------------|-------------------------------------|
| Request in handler  | SaltEvent instance (Schema + Meta + .payload) | Pydantic model (or primitive)       |
| Response to caller  | Response wrapper (.payload, .data, attrs)     | Return value (serialized by broker)  |
| “Event class”       | One class: Schema, Response, Meta, .publish(), .call(), .respond() | No event class; separate types for in/out |
| Broker              | Celery + RabbitMQ                    | Async (Kafka, RabbitMQ, NATS, Redis) |

So: FastStream keeps **in/out as plain types** (Pydantic or built-ins). CelerySalt’s design is **one event class per topic** with request (Schema) and optional response (Response/Error), and a single object API for both subscribing (event instance) and calling RPC (response instance with the same kind of access).

---

## Recommendation

1. **Subscribe with the SaltEvent class** when you have it, so handlers always receive a SaltEvent instance (`event.<field>`, `event.payload`).
2. **`event.call()` returns a SaltResponse** so callers get `response.payload` and attribute access, mirroring the event API.
3. Keep the current behavior for “topic-only” subscribers (payload only) and document it; optional typing options remain as in TYPING_SUBSCRIBER_EVENTS.md.
