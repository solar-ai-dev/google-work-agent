# Database migration artifacts

`migrations/` is an executable-artifact mirror for coding and review agents. Behavioral authority remains in [`../canonical/04-domain-database-design.md`](../canonical/04-domain-database-design.md), the lifecycle contract in [`../canonical/04-a-domain-state-transition-contract.md`](../canonical/04-a-domain-state-transition-contract.md), and the repository/test/infrastructure contracts that define migration placement, discovery, checksum, and enforcement.

## Current executable baseline

The product has no deployed database history. Fresh installation is owned by one current schema:

```text
0001_current_schema.sql
```

This mirror is byte-identical to the production artifact. Historical upgrade SQL remains available from Git history and is not a live Product compatibility authority.

## Rules

- until a Product release exists, schema changes rebaseline this fresh-install artifact;
- after the first deployed release, applied migrations become immutable and later changes use forward migrations;
- executable migration bytes in this directory should match production migration bytes;
- startup ordering, checksum mismatch behavior, and contract tests are owned by the applicable `10`/`12`/`16` contracts.
