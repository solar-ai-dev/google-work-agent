# Database migration artifacts

`migrations/` is an executable-artifact mirror for coding and review agents. Behavioral authority remains in [`../canonical/04-domain-database-design.md`](../canonical/04-domain-database-design.md), the lifecycle contract in [`../canonical/04-a-domain-state-transition-contract.md`](../canonical/04-a-domain-state-transition-contract.md), and the repository/test/infrastructure contracts that define migration placement, discovery, checksum, and enforcement.

## Current executable baseline

The supplied original `/docs` and the inspected `refactor/canonical-architecture-migration` production migration directory contain:

```text
0001_initial.sql
0002_action_effect_send_delete.sql
0003_action_cancelled.sql
0004_plan_review_gate.sql
0005_cross_aggregate_invariants.sql
0006_plan_aggregate_invariants.sql
0007_connector_neutral_persistence.sql
0008_resource_ref_connector_identity.sql
```

This mirror uses the production bytes for those artifacts. `0001`–`0007` already matched the original docs mirror exactly; `0008` differed only by a trailing newline in the old docs copy and is normalized here to the production blob.

## Architecture-27 next migration target

Architecture-27 names:

```text
migrations/0009_workflow_handoff_outbox.sql
→ workflow_handoffs table/index/constraints
```

and the test design expects migration discovery through `0009`. However, no executable `0009` file exists in the supplied original `/docs` or the inspected production migration directory. Therefore:

- do **not** invent SQL in this documentation mirror;
- when implementation work creates the canonical production `0009` migration, add it under the production migration package first;
- then mirror the exact production bytes here;
- migration SQL may not create weaker or competing behavioral authority than `04`/State/`16`.

## Rules

- applied migrations are immutable;
- new schema/invariant changes use the next numeric forward migration;
- executable migration bytes in this directory should match production migration bytes;
- startup ordering, checksum mismatch behavior, and contract tests are owned by the applicable `10`/`12`/`16` contracts.
