# Google Work Agent — Persistence / Repository / UoW / DB Canonical ↔ Current Mapping

**Repository:** `solar-ai-dev/google-work-agent`  
**Branch:** `refactor/canonical-architecture-migration`  
**Investigation SHA:** `453e7f0c3fb5305775f709d91fe001673b5e0651`  
**Mode:** `READ_ONLY_MAPPING`  
**Canonical documents modified:** **NO**

## 1. Scope closure

Canonical persistence structural universe used in this pass:

- `STR-145..176`: 16 repository Port↔SQLite Adapter pairs + UnitOfWork/SqliteUnitOfWork = **32 rows**
- `STR-330..332`: WorkflowHandoff Port + SQLite adapter + exact migration = **3 rows**
- `STR-360..372`: persistent invariants `DBI-001..DBI-013` = **13 rows**
- `STR-373`: forward numeric migration grammar = **1 row**
- **Total = 49 canonical rows**

Current mapping coverage: **49/49**.

## 2. Canonical → Current mapping — 49/49

| ID | Kind | Canonical target / responsibility | Current implementation | Semantic | Structural | Duplicate / extra authority | Disposition | Required action |
|---|---|---|---|---|---|---|---|---|
| STR-145 | Port | `ports/persistence/conversation_repository.py → ConversationRepository` | exact path/symbol; `create/get/list_keyset/touch_updated_at` exact | **FULL** | **FULL** | NO | **KEEP** | Keep surface; later replace `ports.models.ConversationRecord` import with canonical owner-local model/projection as Domain migration lands. |
| STR-146 | SQLite adapter | `.../conversation_repository.py → SqliteConversationRepository` | exact path/symbol and method surface; keyset implementation present | **FULL** | **FULL** | NO | **KEEP** | Preserve implementation and tests; only type imports may change. |
| STR-147 | Port | `ports/persistence/message_repository.py → MessageRepository` | exact path/symbol; `append_user_message/append_terminal_assistant_message/list_by_conversation_keyset` exact | **FULL** | **FULL** | NO | **KEEP** | Keep. |
| STR-148 | SQLite adapter | `.../message_repository.py → SqliteMessageRepository` | exact path/symbol; role fences + keyset implementation | **FULL** | **FULL** | NO | **KEEP** | Keep; only model import cut-over later. |
| STR-149 | Port | `ports/persistence/run_repository.py → RunRepository` | canonical five methods exist, but file also exposes many live lifecycle command shims | **FULL** | **MIXED** | YES | **KEEP + TARGETED_CORRECTION** | Keep canonical five-method surface; cut callers off `get_by_id/complete_*/block/publish/cancel/reauth/recovery/set_*` shims, then delete those aliases. |
| STR-150 | SQLite adapter | `.../run_repository.py → SqliteRunRepository` | `SQLiteRunRepository`; canonical CAS exists, but adapter calls Domain transition policy and implements command-specific lifecycle methods | **PARTIAL** | **NAME+MIXED** | YES | **RENAME + TARGETED_CORRECTION** | Rename class casing; preserve SQL/CAS/query code; remove lifecycle decision logic and command-specific aliases after caller cut-over. |
| STR-151 | Port | `ports/persistence/plan_repository.py → PlanRepository` | legacy `get_by_id/insert_draft/require_review/store_review_result/activate/wait/complete/cancel/supersede/list_by_run` surface | **PARTIAL** | **FULL_PATH** | YES | **TARGETED_CORRECTION** | Converge to `insert_revision/get_current/load_bundle/record_review_result/update_if_version_and_status`; preserve useful SQL semantics through adapter. |
| STR-152 | SQLite adapter | `.../plan_repository.py → SqlitePlanRepository` | `SQLitePlanRepository`; direct lifecycle setters and corrective-draft behavior | **PARTIAL** | **NAME+MIXED** | YES | **RENAME + TARGETED_CORRECTION** | Preserve draft/review/CAS SQL; realize canonical generic surface; remove direct lifecycle authority. |
| STR-153 | Port | `ports/persistence/action_repository.py → ActionRepository` | broad command-specific lifecycle surface + separate ActionDependencyRepository | **PARTIAL** | **FULL_PATH** | YES | **TARGETED_CORRECTION + MERGE** | Converge to `insert_for_plan/get/list_for_plan/update_if_version_and_status/list_dependents/is_dependency_ready`; merge dependency queries here. |
| STR-154 | SQLite adapter | `.../action_repository.py → SqliteActionRepository` | `SQLiteActionRepository`; imports/calls `transition_action`; command-specific mutations; dependency-ready query partly present | **PARTIAL** | **NAME+MIXED** | YES | **RENAME + TARGETED_CORRECTION + MERGE** | Keep SQL/row mapping/risk serialization; move semantic decisions to Domain/Application; absorb dependency persistence/query behavior. |
| STR-155 | Port | `ports/persistence/approval_repository.py → ApprovalRepository` | `get_by_id/get_active_by_action/insert/mark_consumed/revoke_active_by_action/list_by_action` | **PARTIAL** | **FULL_PATH** | YES | **TARGETED_CORRECTION** | Converge to active-snapshot/read/list-by-plan/conditional-status surface; child effects remain owning command UoW decisions. |
| STR-156 | SQLite adapter | `.../approval_repository.py → SqliteApprovalRepository` | `SQLiteApprovalRepository`; reusable SQL but legacy CRUD/effect method surface | **PARTIAL** | **NAME+MIXED** | YES | **RENAME + TARGETED_CORRECTION** | Preserve SQL; expose canonical conditional persistence only. |
| STR-157 | Port | `ports/persistence/execution_attempt_repository.py → ExecutionAttemptRepository` | has insert/get-active/update terminal methods; lacks canonical `get/list_reconciliation_candidates/update_if_version_and_status` | **PARTIAL** | **FULL_PATH** | YES | **TARGETED_CORRECTION** | Add reconciliation projection + generic CAS; delete result-specific persistence aliases after caller cut-over. |
| STR-158 | SQLite adapter | `.../execution_attempt_repository.py → SqliteExecutionAttemptRepository` | `SQLiteExecutionAttemptRepository`; no startup reconciliation query; result-specific setters | **PARTIAL** | **NAME+MIXED** | YES | **RENAME + TARGETED_CORRECTION** | Preserve attempt row SQL; implement canonical query/CAS surface. |
| STR-159 | Port | `ports/persistence/verification_repository.py → VerificationRepository` | only `insert/list_by_attempt` | **PARTIAL** | **FULL_PATH** | NO | **TARGETED_CORRECTION** | Add `get_latest_for_attempt/list_for_action`; remove alternate public list surface if no longer needed. |
| STR-160 | SQLite adapter | `.../verification_repository.py → SqliteVerificationRepository` | `SQLiteVerificationRepository`; insert/list-by-attempt only | **PARTIAL** | **NAME** | NO | **RENAME + TARGETED_CORRECTION** | Preserve immutable insert SQL; add canonical reads. |
| STR-161 | Port | `ports/persistence/recovery_repository.py → RecoveryRepository` | exact four-method surface; RecoveryContextV1 logical persistence representation | **FULL** | **FULL** | NO | **KEEP** | Keep. Do not duplicate RecoveryContext type family across layers. |
| STR-162 | SQLite adapter | `.../recovery_repository.py → SqliteRecoveryRepository` | exact symbol/surface; version CAS + tombstone currentness + bounded candidates | **FULL** | **FULL** | NO | **KEEP** | Keep. |
| STR-163 | Port | `ports/persistence/resource_ref_repository.py → ResourceRefRepository` | exact `upsert_bound_ref/get/list_for_run_bounded` | **FULL** | **FULL** | NO | **KEEP** | Keep; Domain ResourceRef model/vocabulary import changes later. |
| STR-164 | SQLite adapter | `.../resource_ref_repository.py → SqliteResourceRefRepository` | exact symbol/surface; connector-aware UPSERT identity | **FULL** | **FULL** | NO | **KEEP** | Keep. |
| STR-165 | Port | `ports/persistence/evidence_repository.py → EvidenceRepository` | `insert/link_to_action/list_by_action`; canonical bounded aggregate reads absent | **PARTIAL** | **FULL_PATH** | YES | **TARGETED_CORRECTION** | Converge to `insert_bounded/list_for_run/list_for_action`; retain ActionEvidence relation SQL behind canonical owner surface. |
| STR-166 | SQLite adapter | `.../evidence_repository.py → SqliteEvidenceRepository` | `SQLiteEvidenceRepository`; useful insert/link/list SQL | **PARTIAL** | **NAME+MIXED** | YES | **RENAME + TARGETED_CORRECTION** | Preserve SQL; add bounds/run read; hide standalone relation mutation behind owning transaction. |
| STR-167 | Port | `ports/persistence/command_receipt_repository.py → CommandReceiptRepository` | `get_by_command_id/add_received/finish/finish_json/has_applied_request_cancel`; canonical reserve/replay adjudication absent | **PARTIAL** | **FULL_PATH** | YES | **TARGETED_CORRECTION** | Implement `reserve_or_replay/store_result`; keep cancel-intent as receipt-derived query/helper without a second repository authority. |
| STR-168 | SQLite adapter | `.../command_receipt_repository.py → SqliteCommandReceiptRepository` | `SQLiteCommandReceiptRepository`; `finish_json` overwrites by command_id without final-status CAS fence | **PARTIAL** | **NAME+MIXED** | YES | **RENAME + TARGETED_CORRECTION** | Add same-transaction reserve/replay + immutable final result CAS; refuse overwrite of APPLIED/REJECTED rows. |
| STR-169 | Port | `ports/persistence/retention_repository.py → RetentionRepository` | file/symbol absent; trace/audit adapters contain reusable purge SQL | **NONE** | **NONE** | NO | **CREATE** | Create one `purge_batch(cutoffs,batch_limit)` port; do not create category-specific repository aliases. |
| STR-170 | SQLite adapter | `.../retention_repository.py → SqliteRetentionRepository` | file/symbol absent; reusable purge operations currently split across trace/audit repositories | **NONE** | **NONE** | NO | **CREATE + MERGE** | Build from existing bounded purge SQL and required safe delete ordering; centralize retention write authority. |
| STR-171 | Boundary | `ports/persistence/unit_of_work.py → UnitOfWork` | exists; exposes main repos + extra `action_dependencies`; no Retention; Trace/Audit old types; CheckpointPort is separately typed system boundary | **PARTIAL** | **FULL_PATH** | YES | **TARGETED_CORRECTION** | Merge ActionDependency into ActionRepository, add Retention, align canonical repository types. Do not treat CheckpointPort as a Domain repository. |
| STR-172 | SQLite adapter | `adapters/persistence/sqlite/unit_of_work.py → SqliteUnitOfWork` | exact class; `BEGIN IMMEDIATE`, shared connection, commit/rollback; instantiates extra dependency repo and old Trace/Audit classes, no Retention | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Preserve transaction lifecycle; update member composition to canonical repository set. |
| STR-173 | Port | `ports/persistence/trace_event_repository.py → TraceEventRepository` | canonical file absent; current `trace_repository.py → TraceRepository` with append/cursor/retention methods | **PARTIAL** | **PATH+NAME** | YES | **MOVE_RENAME + TARGETED_CORRECTION** | Move/rename and converge to `append/list_page/purge_before` while preserving bounded cursor semantics. |
| STR-174 | SQLite adapter | `.../trace_event_repository.py → SqliteTraceEventRepository` | current `trace_repository.py → SQLiteTraceRepository`; useful sanitization + append + bounded purge | **PARTIAL** | **PATH+NAME** | YES | **MOVE_RENAME + TARGETED_CORRECTION** | Preserve sanitization/SQL; rename and expose exact canonical surface. |
| STR-175 | Port | `ports/persistence/audit_event_repository.py → AuditEventRepository` | canonical file absent; current `audit_repository.py → AuditRepository` | **PARTIAL** | **PATH+NAME** | YES | **MOVE_RENAME + TARGETED_CORRECTION** | Move/rename to exact owner; preserve append/cursor/purge semantics. |
| STR-176 | SQLite adapter | `.../audit_event_repository.py → SqliteAuditEventRepository` | current `audit_repository.py → SQLiteAuditRepository`; useful sanitization + append/cursor/purge | **PARTIAL** | **PATH+NAME** | YES | **MOVE_RENAME + TARGETED_CORRECTION** | Preserve sanitization/SQL; rename and expose exact canonical surface. |
| STR-330 | Port | `ports/persistence/workflow_handoff_repository.py → WorkflowHandoffRepository` | exact path/symbol and closed handoff/admission/redrive/settlement surface | **FULL** | **FULL** | NO | **KEEP** | Keep. |
| STR-331 | SQLite adapter | `.../workflow_handoff_repository.py → SqliteWorkflowHandoffRepository` | exact adapter; replay identity, run epoch, CAS admission/release, settlement, stale retirement, supersession | **FULL** | **FULL** | NO | **KEEP** | Keep. |
| STR-332 | Migration | `migrations/0009_workflow_handoff_outbox.sql` | exact filename/table/index/constraints present | **FULL** | **FULL** | NO | **KEEP** | Keep immutable as applied/current migration history. |
| STR-360 | Persistent invariant | `DBI-001` — partial UNIQUE open Run per Conversation | schema/migrations + repository/UoW + integration regression evidence | **FULL** | **N/A** | N/A | **KEEP** | Existing schema + SQLite regression enforce one open Run. |
| STR-361 | Persistent invariant | `DBI-002` — partial UNIQUE ACTIVE Approval per Action | schema/migrations + repository/UoW + integration regression evidence | **FULL** | **N/A** | N/A | **KEEP** | Existing schema/tests enforce one ACTIVE Approval. |
| STR-362 | Persistent invariant | `DBI-003` — partial UNIQUE active Attempt per Approval | schema/migrations + repository/UoW + integration regression evidence | **FULL** | **N/A** | N/A | **KEEP** | Existing schema/tests enforce active Attempt uniqueness. |
| STR-363 | Persistent invariant | `DBI-004` — command_id unique + immutable request-hash/result replay | schema/migrations + repository/UoW + integration regression evidence | **PARTIAL** | **N/A** | N/A | **TARGETED_CORRECTION** | UNIQUE/hash constraints exist, but current receipt adapter can overwrite a final row; add reserve/replay adjudication and immutable store-result CAS. |
| STR-364 | Persistent invariant | `DBI-005` — cross-aggregate ownership FK/trigger defense | schema/migrations + repository/UoW + integration regression evidence | **FULL** | **N/A** | N/A | **KEEP** | 0005/0006 and regression tests reject cross-run/cross-plan child writes. |
| STR-365 | Persistent invariant | `DBI-006` — dependency self-edge forbidden + plan position unique | schema/migrations + repository/UoW + integration regression evidence | **FULL** | **N/A** | N/A | **KEEP** | CHECK/UNIQUE and aggregate tests present; full DAG-cycle detection remains Application concern. |
| STR-366 | Persistent invariant | `DBI-007` — versioned Review gate/current revision binding | schema/migrations + repository/UoW + integration regression evidence | **FULL** | **N/A** | N/A | **KEEP** | review_status/review_version + review_disposition and expected-review-version CAS are durable; repository API will be renamed separately. |
| STR-367 | Persistent invariant | `DBI-008` — ResourceRef identity `(run_id,connector_id,resource_type,resource_id)` | schema/migrations + repository/UoW + integration regression evidence | **FULL** | **N/A** | N/A | **KEEP** | 0008 makes connector-aware identity the canonical unique key; integration coverage exists. |
| STR-368 | Persistent invariant | `DBI-009` — persisted Action/ResourceRef has registered connector_id | schema/migrations + repository/UoW + integration regression evidence | **PARTIAL** | **N/A** | N/A | **TARGETED_CORRECTION** | NOT NULL/connector-aware persistence exists, but persistence accepts arbitrary connector IDs; final registered-ID admissibility must be re-proven at registry/Application boundary without inventing a DB FK. |
| STR-369 | Persistent invariant | `DBI-010` — Claim atomic commit | schema/migrations + repository/UoW + integration regression evidence | **FULL** | **N/A** | N/A | **KEEP** | ClaimExecution commits Approval CONSUMED + Action EXECUTING + Attempt CLAIMED + receipt/audit/trace in one UoW and no gateway call; dedicated integration test. |
| STR-370 | Persistent invariant | `DBI-011` — no new Attempt/Write authority while UNKNOWN_RESULT unresolved | schema/migrations + repository/UoW + integration regression evidence | **PARTIAL** | **N/A** | N/A | **TARGETED_CORRECTION** | SQL strongly enforces Action↔Attempt UNKNOWN consistency and active-attempt uniqueness, but no explicit final proof was found that every new Approval/Attempt path is blocked for the same unresolved Action after generic CAS cut-over. |
| STR-371 | Persistent invariant | `DBI-012` — Audit/Receipt + mutation in one short tx; external I/O excluded | schema/migrations + repository/UoW + integration regression evidence | **PARTIAL** | **N/A** | N/A | **TARGETED_CORRECTION** | UoW is short and core Claim proves the pattern, but this is a repository-wide caller property; Persistence-only inspection cannot close all Application handlers. Preserve boundary and add architecture/behavior coverage. |
| STR-372 | Persistent invariant | `DBI-013` — SUPERSEDED Plan has no child execution authority | schema/migrations + repository/UoW + integration regression evidence | **PARTIAL** | **N/A** | N/A | **TARGETED_CORRECTION** | DB blocks supersede with ACTIVE Approval and Claim guard rejects superseded Plan, but broad Action repository mutation aliases do not all enforce parent-currentness; generic CAS/caller cut-over must close it. |
| STR-373 | Migration grammar | `migrations/NNNN_<semantic_change>.sql`; applied migrations immutable | current 0001..0012 forward history; migration engine checks order/name/checksum; populated 0011→0012 upgrade test | **FULL** | **FULL** | NO | **KEEP** | Keep applied files immutable; future persistent invariant changes use new numeric migrations. |

## 3. Current → Canonical reverse mapping — extra / compatibility persistence authority

| Current path | Finding | Disposition | Required closure |
|---|---|---|---|
| `ports/persistence/action_dependency_repository.py + sqlite adapter` | Standalone ActionDependencyRepository is outside canonical repository decomposition. | **MERGE → DELETE AFTER CUTOVER** | Move add/list dependency behavior into ActionRepository's canonical dependency methods; rewire callers. |
| `adapters/persistence/cancel_intent_repository.py` | Subclassed CommandReceipt repository for one cancel-intent query; creates a second persistence authority around receipts. | **MERGE → DELETE AFTER CUTOVER** | Keep durable cancel-intent query semantics inside canonical CommandReceipt boundary/helper. |
| `adapters/persistence/corrective_plan_repository.py` | CorrectiveAwareSQLitePlanRepository compatibility subclass duplicates behavior already present in current plan adapter. | **MERGE → DELETE AFTER CUTOVER** | Retain safe reserved corrective-DRAFT reuse in canonical PlanRepository; remove subclass. |
| `adapters/persistence/secret_boundary.py` | SecretBoundaryAudit/Trace subclasses re-sanitize even though base SQLite Audit/Trace repositories already sanitize; not used by current UoW. | **MERGE → DELETE** | Keep one persistence-side sanitization authority in canonical Trace/Audit adapters. |
| `adapters/persistence/__init__.py` | Concrete barrel re-exports repositories and UoW. | **TARGETED_CORRECTION** | Cut callers to direct canonical modules; leave package init minimal. |
| `adapters/persistence/connection.py` | SQLite connection helper sets foreign_keys=ON, WAL, synchronous=FULL, busy_timeout=5000. | **KEEP** | Preserve byte/pragma semantics. |
| `adapters/persistence/migration.py` | Migration discovery/checksum/application/integrity gate. | **KEEP** | Preserve; this is implementation-local infrastructure, not competing Domain authority. |
| `adapters/persistence/persistence_exceptions.py` | Migration/persistence-local error helpers. | **KEEP / later naming check** | No business semantic authority found in this pass; keep unless 16/10 error naming pass requires splitting. |

## 4. DB / migration findings

### Strongly reusable / already canonical

- SQLite connection PRAGMAs are already correct: `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL`, `busy_timeout=5000ms`.
- `0005_cross_aggregate_invariants.sql` + `0006_plan_aggregate_invariants.sql` provide strong NFR-019 cross-aggregate and lifecycle final defenses.
- `0008_resource_ref_connector_identity.sql` removes the earlier compatibility identity and closes connector-aware ResourceRef identity.
- `0009_workflow_handoff_outbox.sql` is the exact source-closed WorkflowHandoff migration and should remain immutable.
- `0010_plan_review_disposition.sql`, `0011_recovery_context.sql`, `0012_recovery_context_currentness.sql` are legitimate forward migrations; they must not be rewritten merely because the original Ledger correction referenced history through 0009.
- RecoveryContext clear/recreate version history is preserved with tombstones.
- ClaimExecution atomicity is already implemented and directly regression-tested.

### Gaps that block Persistence freeze

1. **RetentionRepository / SqliteRetentionRepository are absent.** Existing Trace/Audit purge SQL is reusable, but there is no single retention persistence authority or `application/maintenance/purge_retention.py` caller yet.
2. **CommandReceipt replay finality is not immutable at adapter level.** `finish_json()` can update a receipt by `command_id` regardless of its current final status.
3. **Run/Action repositories still own lifecycle semantics.** Their adapters call Domain transition functions and expose command-specific mutation aliases; canonical repositories must persist decisions, not choose them.
4. **Plan/Approval/ExecutionAttempt/Verification/Evidence Port surfaces do not match the source-closed callable surfaces.**
5. **Trace/Audit exact owner paths and symbols are not realized.** Current `trace_repository.py` / `audit_repository.py` must move/rename without losing sanitization/purge behavior.
6. **ActionDependencyRepository is a second noncanonical persistence authority.** Dependency storage/readiness belongs to ActionRepository.
7. **Exact repository test ownership is incomplete.** Only five exact canonical repository tests are present in the inspected mirror directory.

## 5. Test mapping

| Area | Current evidence | Required action |
|---|---|---|
| Conversation / Message | Exact repository mirror tests exist | KEEP |
| Recovery / ResourceRef / WorkflowHandoff | Exact repository mirror tests exist | KEEP |
| Run / Plan / Action / Approval / ExecutionAttempt / Verification / Evidence / CommandReceipt / Retention / TraceEvent / AuditEvent | Exact canonical repository mirror tests are absent from inspected repository-test directory | CREATE/MOVE tests with canonical surface; do not rely only on integration tests |
| DB invariants | `test_schema_constraints.py`, `test_plan_aggregate_invariants.py`, Claim/ResourceRef/Handoff/migration tests are extensive | KEEP and extend negative closure for DBI-004/009/011/012/013 |
| Migration | `test_migration.py` validates 12 migrations, checksums, idempotency, CRLF normalization, populated upgrades | KEEP |

## 6. Preservation-first implementation order

1. **Keep proven foundations untouched first:** connection PRAGMAs, migration engine, applied 0001..0012 history, RecoveryRepository, ResourceRefRepository, WorkflowHandoffRepository, Conversation/Message repositories, Claim atomicity.
2. **Materialize missing Retention Port/Adapter** by reusing the existing Trace/Audit purge SQL and canonical retention ordering.
3. **Correct CommandReceipt boundary** to `reserve_or_replay/store_result` with immutable final-state CAS; merge cancel-intent query behavior and delete subclass authority.
4. **Converge Plan/Action/Approval/Attempt/Verification/Evidence repository Ports** to the exact callable manifest. Preserve row mapping and SQL.
5. **Strip lifecycle semantics from Run/Action SQLite adapters:** keep generic CAS/query code, rewire Application to exact Domain decisions, then delete command-specific repository aliases.
6. **Merge ActionDependency into ActionRepository.**
7. **Move/rename Trace/Audit repositories** to exact `trace_event_repository.py` / `audit_event_repository.py` and `Sqlite*EventRepository` symbols; keep persistence-side sanitization.
8. **Normalize UnitOfWork composition** to the canonical repository set. Preserve short shared-connection transaction semantics and keep Checkpoint as a distinct typed system boundary, not a Domain repository.
9. **Add exact repository mirror tests** for the missing canonical pairs and DBI-004/009/011/012/013 negative closure.
10. **Caller/import/barrel closure:** direct-import canonical persistence modules, remove `adapters/persistence` concrete exports and compatibility subclasses only after zero callers.

## 7. Disposition summary

- **CREATE: 2**
- **KEEP: 21**
- **MOVE_RENAME: 4**
- **RENAME: 8**
- **TARGETED_CORRECTION: 14**

## 8. Mapping verdict

**PERSISTENCE MAPPING COMPLETE @ `453e7f0c3fb5305775f709d91fe001673b5e0651`**

Meaning: all 49 source-closed Persistence/Repository/UoW/DB rows have a current-code mapping and an explicit preservation-first disposition, and the inspected extra persistence authorities have reverse dispositions.

```text
PERSISTENCE MAPPING              = COMPLETE
CANONICAL -> CURRENT             = CLOSED (49/49 mapped)
CURRENT -> CANONICAL             = CLOSED for inspected persistence authority scope

PERSISTENCE IMPLEMENTATION       = NOT COMPLETE
PERSISTENCE SINGLE AUTHORITY     = NOT CLOSED
PERSISTENCE FROZEN               = NO
INVESTIGATION SHA                = 453e7f0c3fb5305775f709d91fe001673b5e0651
```