# Google Work Agent — Persistence Delta Reconciliation after #100

**Base mapping SHA:** `453e7f0c3fb5305775f709d91fe001673b5e0651`  
**Reconciled HEAD:** `6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d`  
**Commit:** `refactor: close canonical #100 lifecycle authorities`

## Result

The #100 commit changes Persistence evidence but does **not** change the canonical 49-row universe and does not reverse any primary preservation-first disposition from the 453e mapping.

Material delta:

- new forward migration `0013_resource_ref_registry_type.sql` makes persisted `ResourceRef.resource_type` the exact signed-registry string family; this strengthens the existing ResourceRef/DBI mapping and updates migration-history evidence from `0001..0012` to `0001..0013`;
- `SqliteResourceRefRepository` now persists/reads `resource_type` as a string rather than the old `StoredResourceType` enum projection;
- `SqlitePlanRepository.store_review_result()` narrows its CAS predicate from `review_status <> PASSED` to `review_status = REQUIRED`; this is a safety improvement but the repository still has noncanonical command/effect surface;
- `SQLiteRunRepository` adds richer canonical read fields and conversation queries but still explicitly retains broad lifecycle shims and calls `transition_run()`; therefore its targeted-correction disposition remains;
- WorkflowHandoff repository/admission behavior receives additional closure changes but remains the canonical persistence authority; KEEP remains correct;
- CommandReceipt immutable-finality defect, Retention absence, Action repository lifecycle authority, old Trace/Audit owner paths, ActionDependency second authority, and UoW canonical-set gaps remain unresolved.

## Current-head persistence verdict

```text
CANONICAL PERSISTENCE ROW UNIVERSE = unchanged (49)
PRIMARY DISPOSITION REVERSALS      = 0
MAPPING DELTA RECONCILED           = YES
CURRENT EVIDENCE SHA               = 6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d

PERSISTENCE MAPPING                = VALIDATED WITH DELTA RECONCILIATION
PERSISTENCE IMPLEMENTATION         = NOT COMPLETE
PERSISTENCE SINGLE AUTHORITY       = NOT CLOSED
PERSISTENCE FROZEN                 = NO
```
## Current-head continuation to 93f03a91

`6ec3ff49 → 93f03a91` further strengthens ExecutionAttempt reconciliation, WorkflowHandoff settlement/CAS and SQLite checkpoint behavior. No preservation-first disposition reversal is required. The base Persistence mapping now also formally owns `NPA-015..019` and `NPA-045..053`. Current migration history includes later forward migrations (including `0013_resource_ref_registry_type.sql`) without changing the immutability/disposition of NPA-045..053.


## Current-head continuation to a03432c8

`93f03a91 → a03432c8` materially executes the Domain/Persistence side of #104. `ports/models.py` is removed and SQLite repositories now import owner-local Domain records. `SQLiteRunRepository` is narrowed to create/read/query/generic CAS instead of command-specific lifecycle mutation, and `SQLiteActionRepository` similarly exposes persistence/query/CAS rather than owning Approve/Modify/Reject transition semantics. This **supersedes** the 6ec statement that Run/Action repository lifecycle authority remains a blocker for the #104 path.

The base 453e preservation evidence remains useful for migration history, but current implementation status must be read through `phase2-mapping-delta-reconciliation-a03432c8.md`. Persistence-wide closure is still not declared here because CommandReceipt/Retention/UoW/NPA and full caller/import/test negative proof are separate bounded concerns.
