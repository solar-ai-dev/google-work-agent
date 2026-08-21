# Single Authority & Legacy Policy

## Single production authority

Every semantic capability has exactly one live production owner.

Required authority record:

```text
Capability
Production owner module
Production caller
Domain aggregate
Port
Adapter
```

More than one live owner is an architecture failure.

## Migration completeness

A migration is complete only when:

```text
new owner live
AND all production callers moved
AND old owner deleted
AND compatibility wrapper deleted
AND tests use new owner
```

"Implemented" is not "active".

## Compatibility

Temporary compatibility is allowed only under `_compat/`.

Each compat module must declare:
- what it replaces,
- why it exists,
- removal condition,
- intended lifetime.

No permanent public export may point to `_compat`.

## Forbidden final forms

```text
legacy runtime
→ canonical runtime
→ canonical planning runtime
→ canonical response runtime
→ canonical freshness runtime
```

Subclass patch-stacks are migration scaffolding, not final architecture.

## Authority collision

When equivalent implementations are found:

```text
SEMANTIC_AUTHORITY_COLLISION
```

Stop new implementation work and resolve ownership first.
