# 11. Structural Refactor Playbook

> Parent: Repository Architecture Source v1.1

Structural refactoring preserves behavioral semantics unless a separate concern-specific canonical contract explicitly requires a behavior change.

## Per-capability workflow

```text
DISCOVER
→ CLASSIFY
→ MAP CANONICAL OWNER
→ MOVE / SPLIT / MERGE
→ REWIRE ALL PRODUCTION CALLERS
→ DELETE OLD AUTHORITY
→ DELETE TRANSIENT COMPAT
→ MOVE / REPOINT TESTS
→ STRUCTURAL ENFORCEMENT
→ BEHAVIOR REGRESSION
```

## Discover

Search semantically, not just by filename. Inspect Domain writers, state writers, repository mutations, external effects, transition/result handling, exports, caller chains, and tests.

## Classify

Each discovered implementation is one of:

```text
CANONICAL_TO_KEEP
MOVE
SPLIT
MERGE
DELETE_DUPLICATE
TRANSIENT_COMPAT
TEST_ONLY
HISTORICAL_ARTIFACT
```

## Rewire

The new owner is not “live” until all production callers use it.

## Delete

Do not leave old implementations as undocumented fallback or safety copies.

## Scope rule

No feature development, new V3 behavior, Prompt activation, or behavioral redesign is performed merely to satisfy this structural refactor.
