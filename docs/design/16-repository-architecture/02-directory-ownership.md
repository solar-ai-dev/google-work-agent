# Directory Ownership Contract

## `domain/`

Owns:
- aggregate models,
- deterministic commands/transitions,
- invariants,
- value objects,
- domain errors.

Never owns:
- database technology,
- LangGraph,
- HTTP,
- provider SDK,
- MCP transport,
- LLM.

Target:

```text
domain/
  run/
  plan/
  action/
  approval/
  claim/
  execution/
  verification/
  recovery/
  resource/
  policy/
```

## `application/agents/`

Owns the six semantic Agent roles.

It owns semantic agent processing, not LangGraph mechanics.

## `application/use_cases/`

Owns application commands/queries coordinating Domain + Ports.

One independent lifecycle capability per file.

## `application/orchestration/`

Owns coordination among use cases.

Does not duplicate transition rules.

## `ports/`

Owns interfaces required by inner layers.

No technology implementation.

## `adapters/langgraph/`

Owns:
- graph composition,
- typed state,
- projection,
- node binding,
- routing binding,
- checkpoint/resume integration.

Does not own:
- SQL/repository mutations,
- approval policy,
- plan persistence semantics,
- external write policy,
- recovery business rules.

## `adapters/persistence/sqlite/`

Owns SQLite mechanics and concrete repository implementations.

Repository implementations split by aggregate/contract.

## `adapters/connectors/`

Owns external provider effects, organized by provider/product/resource/operation.

## `api/`

Owns transport/auth/session/request-response projection.

No business transition.

## `launcher/`

Only composition root.

May know all concrete classes, but makes no business decisions.

## `evaluation/`

May consume public production contracts.

Production source must not import it.
