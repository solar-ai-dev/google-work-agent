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
