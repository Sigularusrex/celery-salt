# Changelog

All notable changes to CelerySalt will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.5] - 2026-02-01

### Fixed
- RPC response validation when handler returns a list: use `model_validate(response)` for non-dict responses so `RootModel[list[...]]` Response schemas receive the list as the root value instead of being wrapped as `{"data": ...}`.

## [1.4.4] - 2026-02-01

### Added
- **SaltResponse**: `event.call()` now returns a `SaltResponse` wrapper (not the raw Pydantic model), mirroring the SaltEvent API. Use `response.event`, `response.data`, `response.payload`, and attribute access (e.g. `response.result`, `response.root`) for RPC responses.
- **SaltEvent.response_payload(response)**: Returns the RPC response as a JSON-serializable dict or list. For `RootModel[list[...]]` Response schemas, returns the bare list (array of dicts) for DRF/JsonResponse.
- **MessageJSONEncoder**: Pydantic `BaseModel` instances (e.g. RPC Response/Error) are now serialized as dicts when using the package JSON encoder.

### Documentation
- [EVENT_CLASS_UNIFIED_API.md](./docs/EVENT_CLASS_UNIFIED_API.md): Design doc for unified API — subscribe with SaltEvent class → receive SaltEvent instance; call RPC → receive SaltResponse with `.payload` and attribute access. Includes comparison with FastStream.

## [1.4.3] - 2026-01-29

### Changed
- Reverted list-of-pairs RPC normalizer (1.4.2). For DRF views, pass a plain dict to `Response()` (e.g. `response.model_dump()` when RPC returns a Pydantic model) so the browser receives correct JSON.

## [1.4.1] - 2026-01-29

### Added
- `SaltEvent.respond(**kwargs)` for RPC handlers: build a validated success response using the event's Response schema (e.g. `return event.respond(result=42, operation="add")`). Only valid when `Meta.mode == "rpc"`.

## [1.0.0] - 2026-01-25

### Added
- Initial release of CelerySalt
- Pydantic-based event schemas with `@event` decorator
- Import-time schema registration for early error detection
- Broadcast (pub/sub) event support with `@subscribe` decorator
- RPC (request/response) support with response/error schema validation
- Protocol compatibility with tchu-tchu package
- Framework-agnostic core library
- Optional Django integration
- Schema registry (in-memory implementation)
- Complete examples for broadcast and RPC patterns
- Docker Compose setup for examples

### Features
- Type-safe event definitions using Pydantic models
- Automatic schema validation on publish and subscribe
- Full Celery integration (retries, time limits, rate limiting, monitoring)
- Protocol compatibility: works with existing tchu-tchu applications
- Response and error schema validation for RPC calls
- Graceful error handling with `RPCError` exception

### Documentation
- Comprehensive README with quick start guide
- Design document explaining architecture
- Implementation context document
- RPC implementation guide
- Publishing guide
- Example documentation

---

## Migration from tchu-tchu

CelerySalt is a complete rewrite of tchu-tchu with a new Pydantic-based API. However, it maintains protocol compatibility, allowing gradual migration.

### Key Differences

1. **New API**: Uses `@event` and `@subscribe` decorators instead of `TchuEvent` class
2. **Pydantic Models**: Event schemas are Pydantic models, not DRF serializers
3. **Import-Time Registration**: Schemas are registered when modules are imported
4. **Framework Agnostic**: Core library doesn't require Django

### Protocol Compatibility

CelerySalt can communicate with tchu-tchu applications:
- Same exchange name: `tchu_events`
- Same message format: `_tchu_meta` field
- Same routing key conventions

This allows:
- Apps using `celery-salt` can publish to apps using `tchu-tchu`
- Apps using `celery-salt` can subscribe to events from `tchu-tchu`
- Gradual migration without breaking changes

### Migration Path

1. **Start with subscribers**: Migrate event handlers first (safer)
2. **Update publishers**: Migrate event publishers after handlers are updated
3. **Remove old code**: Once all apps are migrated, remove tchu-tchu dependencies

See the [Design Document](./CELERYSALT_DESIGN.md) for detailed migration examples.
