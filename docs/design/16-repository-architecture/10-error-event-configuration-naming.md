# 10. Error · Event · Configuration Naming

> Parent: Repository Architecture Source v1.1

## Exception class

```text
<Subject><Condition>Error
```

Examples:

```text
ClaimExpiredError
RouteContractError
CheckpointConflictError
```

Avoid broad semantic catch-alls such as `ProcessingError` or a project-specific generic `RuntimeError`.

## Error codes and enum values

Use `UPPER_SNAKE_CASE`.

Enum type names do not use an `Enum` suffix:

```text
RunStatus
WorkflowPhase
EffectType
DeliveryCertainty
ReviewDisposition
```

## Event naming

Bare `Event` is prohibited because multiple event concepts coexist.

Use qualified types such as:

```text
CalendarEvent
TraceEvent
AuditEvent
WorkflowEvent
SSEEvent
```

Observability event names use explicit subject + event outcome, normally:

```text
<SUBJECT>_<PAST_TENSE_EVENT>
```

Examples: `ACTION_APPROVED`, `EXECUTION_CLAIMED`, `VERIFICATION_MISMATCH`, `RECOVERY_RESOLVED`.

## Configuration / constants

Constants use `UPPER_SNAKE_CASE`.

Equal numeric values with different semantic purposes remain separate constants. Do not merge constants solely because their current numeric values are equal.

## Field suffixes

```text
identity     <entity>_id
reference    *_ref / *_refs
runtime ref  *_handle / *_handles
hash         *_hash
version      *_version
timestamp    *_at_ms
```
