# 10. Error · Event · Configuration Naming

**Normative detail of the current Repository Architecture Source.**

Exceptions: `<Subject><Condition>Error` in owner-local `<subject>_<condition>_error.py`. Broad business errors such as `ProcessingError` and broad multi-authority `errors.py` buckets are prohibited.

Wire/domain error codes and enum values use `UPPER_SNAKE_CASE`. Enum type names do not use an `Enum` suffix.

Bare `Event` is prohibited because Calendar/Trace/Audit/SSE events coexist. Use qualified names such as `CalendarEvent`, `TraceEvent`, `AuditEvent`, `WorkflowEvent`/`SSEEvent`.

Observability event names use `<SUBJECT>_<PAST_TENSE_EVENT>` where applicable.

Configuration constants use `UPPER_SNAKE_CASE`; equal numeric values with different semantic purposes are separate constants. Configuration modules are owner-local and semantic: `<concern>_config.py` for runtime/build configuration and `<concern>_settings.py` only for persisted/user settings when the owning contract makes that distinction. Generic production `config.py` is prohibited.

Identity fields use canonical `<entity>_id`; references use `_ref/_refs`; runtime handles use `_handle/_handles`; hashes use `_hash`; persisted epoch-millisecond timestamps use `_at_ms`.
