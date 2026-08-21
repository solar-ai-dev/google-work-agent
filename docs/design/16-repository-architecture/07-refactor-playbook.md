# Structural Refactor Playbook

## Objective

Refactor structure without accidentally changing semantic behavior.

## Phase 1 — Semantic census

Inventory every production symbol.

Required table:

| Current path | Symbol | Semantic capability | Caller | Live? | Target path | Action |
|---|---|---|---|---|---|---|

Actions:

```text
KEEP
MOVE
SPLIT
MERGE
DELETE
ISOLATE_COMPAT
ISOLATE_EVALUATION
```

## Phase 2 — Authority freeze

For each capability:
1. list every implementation,
2. identify actual production caller,
3. choose one canonical target owner,
4. prohibit new parallel implementations.

## Phase 3 — Mechanical structure normalization

Prefer no semantic changes.

```text
MOVE
SPLIT
redirect imports
redirect callers
```

## Phase 4 — Remove duplicates

After all callers move:
- delete old implementation,
- delete wrapper,
- delete stale export,
- delete stale tests or rewrite them against the new owner.

## Phase 5 — LangGraph cutover

Graph packages become orchestration-only.

Move:
- persistence semantics → Application/Persistence owners,
- recovery semantics → Application/Domain owners,
- write execution semantics → Application use cases.

## Phase 6 — Enforcement

Enable architecture CI gates.

## Definition of Done

- every file has one semantic reason to change,
- every capability has one production authority,
- current production authority is discoverable from one composition root,
- no production migration-generation filenames remain,
- no permanent patch-stack runtime,
- repository files split by aggregate,
- connector files split by operation,
- state fields have one writer,
- dependency gates pass,
- `/docs` and production structure agree.

## Important

Do not mix large semantic redesign with structural movement unless a separate Finding explicitly requires it.
