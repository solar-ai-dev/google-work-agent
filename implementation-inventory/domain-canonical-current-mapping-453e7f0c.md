# Google Work Agent — Domain Canonical ↔ Current Code Mapping

**Repository:** `solar-ai-dev/google-work-agent`  
**Branch:** `refactor/canonical-architecture-migration`  
**Final investigation SHA:** `453e7f0c3fb5305775f709d91fe001673b5e0651`  
**Current branch HEAD revalidated:** `a03432c8fa6d722c6ef93b54ff8de5aa16eeac0a`  
**HEAD moved since this mapping snapshot:** **YES**  
**Current-head reconciliation:** The historical `453e7f0c` disposition table remains the preservation source, but Issue #104 materially executed the Domain cut-over after `93f03a91`: the bounded 15 model + 39 transition closure is reported `54/54`, `ports/models.py` and broad `domain/enums.py` were removed, concrete Domain barrel exports were eliminated, and exact owner-local model/transition modules now carry production authority. The six added closed-vocabulary rows below are separately rechecked against current HEAD; `STR-354..358` now have owner-local semantic authorities but still use unversioned symbols (`RunStatus`, `ActionStatus`, etc.) rather than the Ledger’s exact `*StatusV1` symbols, while `STR-359 RecoveryReasonV1` is exact. Use the `a03432c8` delta document for current status overrides.
**Mode:** `READ_ONLY_MAPPING`  
**Canonical documents modified:** **NO**

## 1. SHA provenance

| Stage | SHA | Meaning |
|---|---|---|
| Investigation start | `a4e31fbc410db02dba06cd4dabc0b2cfdd9bc6af` | docs update snapshot used for first exhaustive pass |
| Domain reconciliation observed | `cf20a75bf05158db298a16415206a10d33760bd2` | `refactor(#98): reconcile domain state authority`; Recovery/ExecutionAttempt owner moves revalidated |
| Persistence foundation observed | `e3bba4539cf85bd28e8299dd5440347a860da821` | `refactor(#99): close persistence and uow foundation`; Repository shims rechecked |
| Final frozen Domain mapping snapshot | `453e7f0c3fb5305775f709d91fe001673b5e0651` | branch HEAD rechecked and frozen for this mapping |

`e3bba453... → 453e7f0c...` contained no Domain-file or Run/Action lifecycle-port change, so the Domain semantic findings remained valid and were closed on the final SHA.

## 2. Authority and closure basis

Authority order used: `00 Project Source Guide → 04 Domain·Database → 04-A Domain State Transition Contract → applicable 03/06/07/09/11 → 16 Repository Architecture + subordinates → 12-A/12 Test → Phase 1 Ledger → current code/tests`.

This mapping closes **61 formal Domain structural rows**: **STR-001 repository-root ownership + 15 canonical Domain model rows + 39 canonical lifecycle-transition rows + 6 closed-vocabulary rows (STR-354..359)**. The historical model/transition subtotal remains **54**, but the closed vocabularies are now formal mapping rows rather than prose-only side coverage. This mapping is bidirectional: every row in the Domain bounded universe has a current disposition, and current Domain semantic/broad files are reverse-mapped below.

## 2.1 Coverage-field interpretation

The legacy `Semantic` column is retained to avoid rewriting the full validated inventory, but for Phase-2 implementation it must be read as a composite coverage signal, not as “feature completeness.” Where material, rows use `NEAR_FULL / OWNER_PARTIAL` to mean: end-to-end behavior substantially exists, while part of the canonical guard/decision authority still resides in Application/UoW or a broad compatibility path.

For implementation tracking, use these dimensions when updating a row:

- **Behavior Coverage** — end-to-end behavior exists.
- **Canonical Owner Coverage** — behavior is located at the correct semantic owner.
- **Structural Coverage** — exact canonical path/file/symbol exists.
- **Caller Closure** — intended production callers use the canonical authority.
- **Duplicate Authority** — competing old/new production authority remains.
- **Evidence SHA** — code revision on which the disposition was made.

This distinction is preservation-first: `OWNER_PARTIAL` is not permission to rewrite already-correct behavior.

## 3. Canonical Domain models — 15/15 mapped

| ID | Owner | Canonical responsibility | Canonical target | Current implementation | Semantic | Structural | Duplicate/misplacement | Disposition | Required action |
|---|---|---|---|---|---|---|---|---|---|
| STR-339 | `conversation` | Conversation | `domain/conversation/model.py → Conversation` | domain/conversation/model.py (guard only) + ports/models.py → ConversationRecord | **PARTIAL** | **MIXED** | NO — entity authority misplaced | **MERGE** | Preserve ConversationRecord fields and existing open-Run guard; merge them into owner-local Conversation. Remove entity authority from ports.models after Port projection cut-over. |
| STR-340 | `message` | Message | `domain/message/model.py → Message` | domain/message/model.py (content-size validator only) + ports/models.py → MessageRecord | **PARTIAL** | **MIXED** | NO — entity authority misplaced | **MERGE** | Preserve MessageRecord + UTF-8 size validation; merge into Message model. Keep USER/final ASSISTANT writes as effects of owning lifecycle UoW, not a second writer. |
| STR-341 | `run` | Run | `domain/run/model.py → Run` | domain/run/model.py (RunCommand/status helpers only) + ports/models.py → RunCreateRecord/RunRecord | **PARTIAL** | **MIXED** | YES — broad command vocabulary/facade | **MERGE + TARGETED_CORRECTION** | Merge RunCreateRecord/RunRecord fields into Run. Preserve terminal/preempting helpers. Split RunCommand so plan/recovery/noncanonical FAIL_RUN/FINALIZE_ACTION_OUTCOMES do not remain mixed Run authority. |
| STR-342 | `plan` | Plan | `domain/plan/model.py → Plan` | domain/plan/ is empty scaffold; ports/models.py → PlanRecord/PlanStatus/PlanReviewStatus | **PARTIAL** | **NONE** | NO — model authority misplaced | **MOVE_RENAME + TARGETED_CORRECTION** | Move/reuse PlanRecord and PlanStatus into Plan; add canonical revision/version/freshness semantics required by current Review binding. Do not keep Plan lifecycle vocabulary in ports.models as semantic authority. |
| STR-343 | `action` | Action | `domain/action/model.py → Action` | domain/action/model.py (cross-owner ActionCommand only) + ports/models.py → ActionRecord + domain/action_risk.py | **PARTIAL** | **MIXED** | YES — cross-owner command vocabulary | **MERGE + TARGETED_CORRECTION** | Merge ActionRecord and reusable risk/value invariants into Action. Split ActionCommand so Approval/Claim/ExecutionAttempt/Verification commands no longer live under Action. |
| STR-344 | `approval` | Approval | `domain/approval/model.py → Approval` | no model.py; ports/models.py → ApprovalRecord; ApprovalStatus in domain/enums.py | **PARTIAL** | **NONE** | NO — misplaced | **MOVE_RENAME** | Move/reuse ApprovalRecord + ApprovalStatus into owner-local Approval model; retain immutable snapshot/hash/TTL/idempotency fields. |
| STR-345 | `execution_attempt` | ExecutionAttempt | `domain/execution_attempt/model.py → ExecutionAttempt` | no model.py; ports/models.py → ExecutionAttemptRecord; status in domain/enums.py | **PARTIAL** | **NONE** | NO — misplaced | **MOVE_RENAME** | Move/reuse current attempt record/status into owner-local model; preserve version/result/error/timing fields and current active-attempt invariants. |
| STR-346 | `verification` | Verification | `domain/verification/model.py → Verification` | no model.py; ports/models.py → VerificationRecord; VerificationStatus includes VERIFIED/MISMATCH/NOT_FOUND/ERROR | **PARTIAL** | **NONE** | YES — observation vocabulary mixed with persisted outcome | **MOVE_RENAME + TARGETED_CORRECTION** | Move VerificationRecord into model. Persisted/lifecycle outcome is VERIFIED|MISMATCH; keep NOT_FOUND/ERROR only in read/observation contracts if needed, not as durable Verification status authority. |
| STR-347 | `resource_ref` | ResourceRef | `domain/resource_ref/model.py → ResourceRef` | empty owner scaffold; ports/models.py → ResourceRefRecord + ResourceSource/StoredResourceType | **PARTIAL** | **NONE** | YES — resource_type vocabulary mismatch | **MOVE_RENAME + TARGETED_CORRECTION** | Move ResourceRefRecord into model; replace StoredResourceType family authority with exact SignedToolRegistryEntryV1.resource_type while preserving connector_id + provider resource_id identity. |
| STR-348 | `evidence` | Evidence | `domain/evidence/model.py → Evidence` | empty owner scaffold; ports/models.py → EvidenceRecord/EvidenceOriginType | **PARTIAL** | **NONE** | NO — misplaced | **MOVE_RENAME** | Move/reuse EvidenceRecord and origin semantics into owner-local model; preserve bounded excerpt/reference semantics. |
| STR-349 | `command_receipt` | CommandReceipt | `domain/command_receipt/model.py → CommandReceipt` | empty owner scaffold; ports/models.py → CommandReceiptRecord/CommandReceiptStatus | **PARTIAL** | **NONE** | NO — misplaced | **MOVE_RENAME** | Move/reuse durable idempotency record/status into owner-local model; preserve command_id/request_hash/result/replay semantics. |
| STR-350 | `action` | ActionDependency | `domain/action/model.py → ActionDependency` | no typed model; persistence exposes action_id/depends_on_action_id edge operations | **PARTIAL** | **NONE** | NO | **CREATE (reuse persistence edge semantics)** | Create the small owner-local typed model from existing dependency edge schema/invariants; do not rewrite persistence behavior. |
| STR-351 | `action` | ActionEvidence | `domain/action/model.py → ActionEvidence` | no typed model; EvidenceRepository link_to_action persists the relation | **PARTIAL** | **NONE** | NO | **CREATE (reuse persistence edge semantics)** | Create the owner-local typed relation from existing Action↔Evidence persistence semantics. |
| STR-352 | `trace_event` | TraceEvent | `domain/trace_event/model.py → TraceEvent` | no domain/trace_event package; ports/models.py → TraceEventRecord/PersistedTraceEventRecord | **PARTIAL** | **NONE** | NO — misplaced | **MOVE_RENAME** | Move/reuse trace payload model to canonical owner; keep persistence-return projection separate from semantic TraceEvent. |
| STR-353 | `audit_event` | AuditEvent | `domain/audit_event/model.py → AuditEvent` | no domain/audit_event package; ports/models.py → AuditEventRecord/PersistedAuditEventRecord | **PARTIAL** | **NONE** | NO — misplaced | **MOVE_RENAME** | Move/reuse append-only audit payload model to canonical owner; keep persistence-return projection separate. |

## 4. Canonical Domain lifecycle transitions — 39/39 mapped

| ID | Owner | Capability | Canonical target | Current implementation/evidence | Semantic | Structural | Duplicate | Disposition | Required action |
|---|---|---|---|---|---|---|---|---|---|
| STR-399 | `run` | `run.start_run` | `domain/run/transitions/start_run.py → transition_start_run()` | exact transition + guard_start_run(has_open_run) | **FULL** | **FULL** | NO | **KEEP** | Keep transition/guard. Application/UoW remains responsible for atomic StartRun write-set. |
| STR-400 | `run` | `run.start_analysis` | `domain/run/transitions/start_analysis.py → transition_start_analysis()` | exact file; broad run.py delegates/compat path also exists | **FULL** | **FULL** | COMPAT_FACADE | **KEEP** | Keep exact authority; cut callers off broad transition_run/Domain barrel later. |
| STR-401 | `run` | `run.begin_retrieval` | `domain/run/transitions/begin_retrieval.py → transition_begin_retrieval()` | exact file; broad run.py compatibility path | **FULL** | **FULL** | COMPAT_FACADE | **KEEP** | Keep exact authority; remove broad facade after caller cut-over. |
| STR-402 | `run` | `run.begin_planning` | `domain/run/transitions/begin_planning.py → transition_begin_planning()` | exact transition/guard supports pre-publish, published Review and Context Adjustment; owning Application handler already closes unresolved `EXECUTING|UNKNOWN_RESULT|EXECUTED|MISMATCH` and revision binding | **NEAR_FULL / OWNER_PARTIAL** | **FULL** | COMPAT_FACADE | **KEEP + TARGETED OWNER CORRECTION** | Preserve the existing end-to-end behavior. Move/duplicate no working guard logic: close the remaining current Review/revision freshness and unresolved-effect predicates at the canonical Domain owner boundary, then remove compatibility/broad authority only after caller cut-over. |
| STR-403 | `run` | `run.request_confirmation` | `domain/run/transitions/request_confirmation.py → transition_request_confirmation()` | exact transition/guard; Application handler validates registered resume target, semantic owner, durable WorkflowBinding/checkpoint, graph profile/version, Review disposition, and unresolved `EXECUTING|UNKNOWN_RESULT|EXECUTED|MISMATCH` facts | **NEAR_FULL / OWNER_PARTIAL** | **FULL** | COMPAT_FACADE | **KEEP + TARGETED OWNER/NEGATIVE-CLOSURE CORRECTION** | Preserve the existing handler behavior. Do not rewrite owner/checkpoint binding logic. Close only any remaining predicates that canonical Domain must own, then remove compatibility/broad authority after caller cut-over. |
| STR-404 | `run` | `run.resume_confirmation` | `domain/run/transitions/resume_confirmation.py → transition_resume_confirmation()` | exact file; current safe restore set omits WAITING_APPROVAL/VERIFYING | **PARTIAL** | **FULL** | COMPAT_FACADE | **TARGETED_CORRECTION** | Extend legal pre_confirmation_status to published Review CONFIRM sources and retain same-owner/checkpoint binding. |
| STR-405 | `run` | `run.complete_answer_only_run` | `domain/run/transitions/complete_answer_only_run.py` | exact state transition + broad run table; current guard mainly state-based | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Add no-Plan/no-Action/open-Write/executing-READ/unresolved-Recovery predicates; cut over repository shim. |
| STR-406 | `run` | `run.complete_read_only_run` | `domain/run/transitions/complete_read_only_run.py` | canonical file absent; reusable logic in application/read_lifecycle.py + RunRepository.complete_read_only_run | **PARTIAL** | **NONE** | YES | **SPLIT + TARGETED_CORRECTION** | Extract pure Run+Plan+READ-child terminal decision into canonical transition; preserve existing read lifecycle UoW/message/audit logic and rewire it. |
| STR-407 | `plan` | `plan.publish_plan` | `domain/plan/transitions/publish_plan.py` | current domain/run/transitions/publish_plan.py only returns Run WAITING_APPROVAL; Plan owner scaffold empty | **PARTIAL** | **PATH** | YES | **MOVE_RENAME + TARGETED_CORRECTION** | Move into plan owner and extend decision to Run PLANNING→WAITING_APPROVAL + Plan DRAFT→WAITING_APPROVAL; rewire Application plan publisher. |
| STR-408 | `plan` | `plan.publish_read_only_plan` | `domain/plan/transitions/publish_read_only_plan.py` | canonical file absent; reusable RunRepository.publish_read_only_plan + PlanRepository.activate + legacy read flow | **PARTIAL** | **NONE** | YES | **SPLIT + MOVE_RENAME** | Build owner-local pure transition by extracting existing Run/Plan logic; preserve compatibility READ UoW behavior. |
| STR-409 | `run` | `run.block_run` | `domain/run/transitions/block_run.py` | exact state transition exists; broad run table/repository shim also owns it | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Add VERIFYING Review=BLOCK gate and zero in-flight/UNKNOWN/unverified/MISMATCH predicates; preserve child cleanup in UoW. |
| STR-410 | `run` | `run.begin_verification` | `domain/run/transitions/begin_verification.py` | canonical file absent; broad run.py has BEGIN_VERIFICATION mapping and repository set_verifying path | **PARTIAL** | **NONE** | YES | **SPLIT + TARGETED_CORRECTION** | Extract exact WAITING_APPROVAL|CANCEL_REQUESTED→VERIFYING transition. Remove broad extra sources such as EXECUTING/REAUTH_REQUIRED. |
| STR-411 | `run` | `run.complete_write_run` | `domain/run/transitions/complete_write_run.py` | exact file; broad run table + repository shim remain | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Allow WAITING_APPROVAL|VERIFYING and enforce all-final, unresolved UNKNOWN_RESULT/MISMATCH=0, cancel intent=false, then Plan terminalization in same UoW. |
| STR-412 | `run` | `run.request_cancel` | `domain/run/transitions/request_cancel.py` | exact guard rejects terminal Run; broad run compatibility path/repository shim remain | **FULL** | **FULL** | COMPAT_FACADE | **KEEP** | Keep exact transition. UoW must preserve durable cancel intent and zero new Claim/Write authority; delete broad/shim authority after cut-over. |
| STR-413 | `run` | `run.finalize_cancel` | `domain/run/transitions/finalize_cancel.py` | exact state transition exists; current broad cancellation service/repository owns child settlement | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Require cancel intent + no EXECUTING/UNKNOWN/unverified EXECUTED + ACTIVE Approval=0; preserve pending-action settlement and Plan cancel in UoW. |
| STR-414 | `run` | `run.require_reauth` | `domain/run/transitions/require_reauth.py` | exact file; current guard source set omits CANCEL_REQUESTED | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Add CANCEL_REQUESTED and exact pre_reauth/registered-target child-fact preconditions; no new Reauth for cancel-active legacy READ. |
| STR-415 | `run` | `run.resume_after_reauth` | `domain/run/transitions/resume_after_reauth.py` | exact file; current validation is materially weaker than Reauth child-fact matrix | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Add registered target/graph/current binding + PREFLIGHT/READ_EXECUTION/VERIFICATION/RECOVERY child-fact legality; prohibit replay of dispatched Write. |
| STR-416 | `recovery` | `recovery.require_recovery` | `domain/recovery/transitions/require_recovery.py` | moved correctly by #98; exact file now exists with recovery owner | **PARTIAL** | **FULL** | COMPAT_FACADE | **TARGETED_CORRECTION** | Preserve owner move. Ensure Domain guard/handler consumes validated RecoveryContextV1 reason/scope/required refs/fingerprints rather than terminal-state-only legality. |
| STR-417 | `recovery` | `recovery.resolve_recovery` | `domain/recovery/transitions/resolve_recovery.py` | reason-aware #98 implementation; old run/recovery files removed; broad run compatibility delegates remain | **FULL** | **FULL** | COMPAT_FACADE | **KEEP** | Keep reason-aware decision logic. Cut over broad run/repository compatibility path; owning UoW continues child cleanup/supersession. |
| STR-418 | `action` | `action.approve_action` | `domain/action/transitions/approve_action.py` | current implementation is misplaced at domain/approval/transitions/approve_action.py; Application action/approve_action.py exists | **PARTIAL** | **PATH** | YES | **MOVE_RENAME + TARGETED_CORRECTION** | Move transition/guard to action owner; add current published Plan + current Review PASS + parent Run authority fence while preserving Approval snapshot UoW. |
| STR-419 | `action` | `action.modify_action` | `domain/action/transitions/modify_action.py` | exact file exists; Application use case + broad action.py/repository shim also participate | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Preserve state/version logic; add SUPERSEDED/current-plan fence and ensure Approval revoke + Review REQUIRED effects remain atomic. |
| STR-420 | `action` | `action.reject_action` | `domain/action/transitions/reject_action.py` | exact file exists; broad action.py/repository + Application use case remain | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Add current-plan/SUPERSEDED fence; preserve approval revocation and review/persistence effects. |
| STR-421 | `action` | `action.cancel_pending_action` | `domain/action/transitions/cancel_pending_action.py` | exact file exists; broad action.py/repository shim remain | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Add current-plan/SUPERSEDED parent guard and keep pending-only source states; preserve approval cleanup. |
| STR-422 | `approval` | `approval.expire_approval` | `domain/approval/transitions/expire_approval.py` | exact file exists; Approval owner also has consume/revoke standalone child-effect files | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Preserve APPROVED+ACTIVE→EXPIRED pair; add current-plan/SUPERSEDED and freshness trigger guard. Merge standalone consume/revoke effects into owning commands. |
| STR-423 | `action` | `action.refresh_expired_action` | `domain/action/transitions/refresh_expired_action.py` | canonical file absent; application/write_action_mutation.py explicitly says refresh_expired_action is not yet implemented | **NONE** | **NONE** | NO | **CREATE (reuse existing validators/helpers)** | Create EXPIRED→MODIFIED authority using current mutation/schema/source/policy refresh helpers; old Approval stays EXPIRED, ACTIVE=0, Review→REQUIRED. |
| STR-424 | `action` | `action.claim_read_action` | `domain/action/transitions/claim_read_action.py` | canonical file absent; transition is inside broad domain/action/transitions/action.py; ClaimReadActionService in application/read_lifecycle.py | **PARTIAL** | **NONE** | YES | **SPLIT** | Extract PROPOSED→EXECUTING READ-only transition to exact file; preserve existing receipt/UoW/audit service and rewire. |
| STR-425 | `action` | `action.complete_read_action` | `domain/action/transitions/complete_read_action.py` | canonical file absent; broad action.py + CompleteReadActionService | **PARTIAL** | **NONE** | YES | **SPLIT** | Extract EXECUTING→EXECUTED READ transition; preserve ResourceRef/Evidence persistence and UoW. |
| STR-426 | `action` | `action.finalize_read_action` | `domain/action/transitions/finalize_read_action.py` | canonical file absent; broad action.py + FinalizeReadActionService | **PARTIAL** | **NONE** | YES | **SPLIT** | Extract EXECUTED→VERIFIED READ transition; preserve parent reconciliation/terminal read logic. |
| STR-427 | `action` | `action.fail_read_action` | `domain/action/transitions/fail_read_action.py` | canonical file absent; broad action.py + FailReadActionService | **PARTIAL** | **NONE** | YES | **SPLIT** | Extract EXECUTING→FAILED READ transition and reuse cancellation/restart settlement logic. |
| STR-428 | `claim` | `claim.claim_execution` | `domain/claim/transitions/claim_execution.py` | exact transition+guard and application/write_claim.py exist; broad action.py also contains claim state mapping | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Preserve strong approval/hash/source/version/expiry/dependency checks. Add explicit owning Plan=current published WAITING_APPROVAL and Run∈WAITING_APPROVAL|VERIFYING parent fence; remove broad duplicate. |
| STR-429 | `execution_attempt` | `execution_attempt.begin_execution_attempt` | `domain/execution_attempt/transitions/begin_execution_attempt.py` | canonical file absent; current write_execution validates Attempt=CLAIMED then directly prepares/executes connector write | **NONE** | **NONE** | NO | **CREATE (reuse claim/execution validation)** | Create CLAIMED→EXECUTING pure transition + exact guard. Add Application command/UoW/Audit commit before any connector call. Reuse existing ClaimContext/binding checks. |
| STR-430 | `execution_attempt` | `execution_attempt.abort_claimed_execution` | `domain/execution_attempt/transitions/abort_claimed_execution.py` | canonical file absent; cancellation/execution services have reusable facts but no single pre-dispatch settlement authority | **NONE** | **NONE** | NO | **CREATE (reuse cancellation/attempt persistence)** | Create pre-dispatch-only Attempt CLAIMED→FAILED + Action EXECUTING→CANCELLED|FAILED transition; require no APPLIED Begin receipt/provider dispatch and preserve consumed Approval. |
| STR-431 | `execution_attempt` | `execution_attempt.store_success` | `domain/execution_attempt/transitions/store_success.py` | exact file exists but currently transitions ActionStatus EXECUTING→EXECUTED; Attempt joint transition is not modeled | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Preserve current action-side logic; extend authority to Attempt EXECUTING→SUCCEEDED + Action EXECUTING→EXECUTED as one decision/UoW. |
| STR-432 | `execution_attempt` | `execution_attempt.mark_failed` | `domain/execution_attempt/transitions/mark_failed.py` | exact file exists but primarily Action-side state result | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Extend to Attempt EXECUTING→FAILED + Action EXECUTING→FAILED and enforce deterministic NOT_SENT evidence. |
| STR-433 | `execution_attempt` | `execution_attempt.mark_unknown_result` | `domain/execution_attempt/transitions/mark_unknown_result.py` | exact file exists but primarily Action-side state result | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Extend to Attempt EXECUTING→UNKNOWN_RESULT + Action EXECUTING→UNKNOWN_RESULT; preserve delivery-certainty contract. |
| STR-434 | `execution_attempt` | `execution_attempt.recover_existing_result` | `domain/execution_attempt/transitions/recover_existing_result.py` | moved correctly by #98; exact file exists but operates on ActionStatus result | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Preserve UNKNOWN_RESULT→EXECUTED logic; also close Attempt UNKNOWN_RESULT→SUCCEEDED and forbid new Write/Attempt. |
| STR-435 | `execution_attempt` | `execution_attempt.resolve_as_failed` | `domain/execution_attempt/transitions/resolve_as_failed.py` | moved correctly by #98; exact file exists but operates on ActionStatus result | **PARTIAL** | **FULL** | YES | **TARGETED_CORRECTION** | Preserve unknown-result settlement; also close Attempt UNKNOWN_RESULT→FAILED and require deterministic non-execution proof. |
| STR-436 | `verification` | `verification.store_verification` | `domain/verification/transitions/store_verification.py` | exact file exists; current exact code maps VERIFIED→VERIFIED and every other VerificationStatus→MISMATCH, while broad `domain/action/transitions/action.py` already contains stronger VERIFIED|MISMATCH-only fail-closed validation | **PARTIAL** | **FULL** | YES | **MERGE + TARGETED_CORRECTION** | Reuse the stronger VERIFIED|MISMATCH-only validation already present in broad `action.py`; merge it into the canonical verification transition, preserve immutable Verification persistence + Action EXECUTED→matching final state, then delete the broad duplicate only after caller cut-over. |
| STR-437 | `action` | `action.prepare_write_retry` | `domain/action/transitions/prepare_write_retry.py` | exact file exists; #98 removed duplicate recovery copy; broad action.py still delegates/contains compatibility | **PARTIAL** | **FULL** | COMPAT_FACADE | **TARGETED_CORRECTION** | Keep FAILED→MODIFIED core. Add current-plan/SUPERSEDED fence and preserve fresh Review/new Approval/new Attempt invariant; delete compatibility broad path. |

## 5. Closed vocabulary comparison

| Vocabulary | Canonical | Current @ SHA | Verdict / action |
|---|---|---|---|
| RunStatusV1 | 15 exact states from CREATED through CANCELLED | `domain/enums.py` matches exact state set | **SEMANTIC FULL**, but SPLIT into `run/model.py` |
| ActionStatusV1 | 14 exact states | `domain/enums.py` matches exact state set | **SEMANTIC FULL**, move into `action/model.py` |
| PlanStatus | DRAFT, WAITING_APPROVAL, ACTIVE, SUPERSEDED, CANCELLED, COMPLETED | currently `ports/models.py → PlanStatus` | **SEMANTIC FULL / STRUCTURAL WRONG** |
| ApprovalStatus | ACTIVE, EXPIRED, CONSUMED, REVOKED | current enum matches | **SEMANTIC FULL**, move owner-local |
| ExecutionAttemptStatus | CLAIMED, EXECUTING, SUCCEEDED, FAILED, UNKNOWN_RESULT | current enum matches | **SEMANTIC FULL**, move owner-local |
| RecoveryReasonV1 | UNKNOWN_RESULT, VERIFICATION_MISMATCH, CHECKPOINT_MISMATCH, CONTRACT_VIOLATION | `domain/recovery/model.py` matches | **KEEP** |
| Verification durable outcome | VERIFIED, MISMATCH | current `VerificationStatus` also contains NOT_FOUND, ERROR | **MIXED** — split observation outcomes from durable Verification status; `StoreVerification` must reject non-durable outcomes |
| RunCommand / ActionCommand | owner-local lifecycle commands only | current enums mix other owners and include noncanonical `FAIL_RUN` / `FINALIZE_ACTION_OUTCOMES` | **SPLIT + CLEANUP** |


## 5.1 Formal Domain root + closed-vocabulary rows — 7/7

These rows were present in the Phase-1 Ledger but were previously only implied by prose. They are now first-class mapping rows.

| ID | Canonical responsibility | Canonical target | Snapshot/current evidence | Behavior | Structural | Disposition | Required action |
|---|---|---|---|---|---|---|---|
| STR-001 | Repository root / Domain semantic ownership | `domain/` | `src/google_work_agent/domain/` exists at snapshot and current HEAD. | N/A | **FULL** | **KEEP** | Preserve top-level Domain ownership; child semantic closure is tracked by the owner-local rows below. |
| STR-354 | `RunStatusV1` closed vocabulary | owner-local Domain contract → `RunStatusV1` | 453e: `domain/enums.py::RunStatus`; a034: `domain/run/model.py::RunStatus` owns the exact values after `domain/enums.py` removal. | **FULL** | **OWNER_FULL / SYMBOL_PARTIAL** | **MOVE_RENAME EXECUTED; TARGETED_RENAME REMAINS** | Preserve the current owner-local values and close the Ledger’s exact `RunStatusV1` symbol contract without creating a second authority. |
| STR-355 | `ActionStatusV1` closed vocabulary | owner-local Domain contract → `ActionStatusV1` | 453e: `domain/enums.py::ActionStatus`; a034: `domain/action/model.py::ActionStatus` owns the exact values after root-enum removal. | **FULL** | **OWNER_FULL / SYMBOL_PARTIAL** | **MOVE_RENAME EXECUTED; TARGETED_RENAME REMAINS** | Preserve values and close the exact `ActionStatusV1` symbol contract in the Action owner. |
| STR-356 | `PlanStatusV1` closed vocabulary | owner-local Domain contract → `PlanStatusV1` | 453e: `ports/models.py::PlanStatus`; a034: `domain/plan/model.py::PlanStatus`, while `ports/models.py` is removed. | **FULL** | **OWNER_FULL / SYMBOL_PARTIAL** | **MOVE_RENAME EXECUTED; TARGETED_RENAME REMAINS** | Preserve the owner-local Plan status values and close the exact `PlanStatusV1` symbol contract. |
| STR-357 | `ApprovalStatusV1` closed vocabulary | owner-local Domain contract → `ApprovalStatusV1` | 453e: `domain/enums.py::ApprovalStatus`; a034: `domain/approval/model.py::ApprovalStatus`. | **FULL** | **OWNER_FULL / SYMBOL_PARTIAL** | **MOVE_RENAME EXECUTED; TARGETED_RENAME REMAINS** | Preserve values and close the exact `ApprovalStatusV1` symbol contract. |
| STR-358 | `ExecutionAttemptStatusV1` closed vocabulary | owner-local Domain contract → `ExecutionAttemptStatusV1` | 453e: `domain/enums.py::ExecutionAttemptStatus`; a034: `domain/execution_attempt/model.py::ExecutionAttemptStatus`. | **FULL** | **OWNER_FULL / SYMBOL_PARTIAL** | **MOVE_RENAME EXECUTED; TARGETED_RENAME REMAINS** | Preserve values and close the exact `ExecutionAttemptStatusV1` symbol contract. |
| STR-359 | `RecoveryReasonV1` closed vocabulary | owner-local recovery contract → `RecoveryReasonV1` | 453e and a034: `domain/recovery/model.py::RecoveryReasonV1` carries the exact four-value contract. | **FULL** | **FULL** | **KEEP** | Keep the exact owner-local type; do not reintroduce broad barrel or duplicate vocabulary authority. |

## 6. Current → Canonical reverse map: Domain root / broad / misplaced authority

| Current path | Current responsibility | Canonical destination/meaning | Disposition | Required action |
|---|---|---|---|---|
| `domain/__init__.py` | Concrete barrel re-exports Domain transitions, policy, registries, helpers | 16 import/export rule: __init__ empty by default; concrete authority direct-imported | **DELETE concrete exports; retain empty package init** | Cut all production callers to canonical owner modules first. |
| `domain/enums.py` | Run/Action/Approval/Attempt/Verification statuses + registry/policy enums + ResultCode mixed | Owner-local models + SignedToolRegistryEntryV1 + shared CommandResult | **SPLIT** | Move lifecycle vocabularies to owner models; registry effect/approval/verification/recovery policy vocab to application/tool_registry contract; keep ResultCode with shared result contract. |
| `domain/exceptions.py` | Broad unrelated Domain + Policy errors | owner-local <subject>_<condition>_error.py grammar | **SPLIT** | Move policy error out of Domain and split unrelated error authorities; broad exceptions.py cannot remain final business error bucket. |
| `domain/action_risk.py` | Action risk canonicalization/size/parse invariants | Action model/value semantics | **MERGE** | Merge reusable risk value-object helpers into action owner; no rewrite. |
| `domain/calendar_conflict.py` | Pure interval/conflict evaluator | deterministic Policy + validated Work Analysis facts | **SPLIT + MERGE** | Move final allow/warn/block semantics into action.evaluate_action_policy; move pure interval normalization/arithmetic to the owner-local deterministic operation that consumes it. Merge with application/calendar_conflicts.py, then remove Domain authority. |
| `domain/feasibility.py` | Pure feasibility/time-window evaluator | Work Analysis validated facts + deterministic Action policy | **SPLIT + MERGE** | Candidate/risk facts stay Work Analysis; execution-gating decision belongs deterministic action policy. Merge with application/feasibility.py. |
| `domain/task_duplicate.py` | Pure Task duplicate evaluator | validated relation facts + deterministic duplicate/override policy | **SPLIT + MERGE** | LLM only proposes candidates; deterministic validation/policy owns final duplicate decision. Merge with application/task_duplicates.py. |
| `domain/policy.py` | EvidencePolicyInput, ApprovalIntegrityInput, policy validators | action.evaluate_action_policy + owning lifecycle guards | **SPLIT + MERGE** | Evidence/product policy → Application action policy; approval freshness/hash/version checks → owner-local Approve/Claim guards. |
| `domain/tool_registry.py` | SignedToolRegistry + ToolRegistryEntry + ConnectorToolCatalog + build_p0_tool_registry compat wrapper | application/tool_registry/* + adapters/connectors/runtime/connector_runtime_registry.py | **SPLIT + MOVE + MERGE** | Move semantic registry to canonical Application registry; connector runtime catalog to runtime registry; delete build_p0_tool_registry compatibility wrapper after callers cut over. |
| `domain/google_workspace_tool_registry.py` | Hard-coded Google tool registry rows | signed-tool-registry manifest + loader/projection | **MERGE** | Preserve current tool metadata as manifest migration input; do not keep provider-specific second registry authority in Domain. |
| `domain/google_workspace_tool_contracts.py` | JSON input/output schemas, hashing and MCP pre/post validation | SignedToolRegistry manifest/schema refs + Google MCP server project_registry/dispatch boundary | **SPLIT + MERGE** | No standalone schema authority is source-closed. Reuse schema definitions while realizing the canonical manifest + MCP boundary; remove Domain MCP contract authority. |
| `domain/claim_contract.py` | ClaimContext TTL constants/validation | 07/09 ClaimContextV2 + claim.build_claim_context + MCP validate_claim_context | **MOVE/MERGE** | Preserve 30s default/60s max; merge issuance validation into build_claim_context and verification into MCP boundary. |
| `domain/canonical.py` | Canonical JSON serialization/hash helper | 04 CanonicalArguments/ArgumentsHash + 07 execution hash invariants | **KEEP as shared non-authority helper** | Direct-import only; do not expose through concrete barrel. If later owner-localized, preserve byte-for-byte semantics. |
| `domain/results.py` | Generic CommandResult shape | 04-A command result contract | **KEEP as shared stable contract** | Keep shared result value type; direct import, no concrete authority barrel. |
| `domain/version_validation.py` | Shared non-negative version invariant | 04 aggregate version invariant | **KEEP as shared non-authority helper** | Reuse from owner guards; direct import only. |
| `domain/run/transitions/run.py` | Broad Run transition table + compatibility policy | 39 operation-per-file lifecycle grammar | **SPLIT/MERGE → DELETE** | Merge compatible logic into exact owner files, rewire callers, delete broad transition authority. |
| `domain/action/transitions/action.py` | Broad Action/Approval/Claim/Attempt/Verification transition table | operation-per-file owner grammar | **SPLIT/MERGE → DELETE** | Extract READ operations and remaining reusable logic; remove duplicate command table. |
| `domain/run/transitions/publish_plan.py` | Plan lifecycle operation placed under Run | plan.publish_plan | **MOVE_RENAME + TARGETED_CORRECTION** | Move to domain/plan/transitions/publish_plan.py and include Plan status side. |
| `domain/approval/transitions/approve_action.py` | ApproveAction under Approval owner | action.approve_action | **MOVE_RENAME + TARGETED_CORRECTION** | Move to action owner; Approval creation remains required child effect in Action command UoW. |
| `domain/approval/transitions/consume_approval.py` | Standalone child-effect transition | ClaimExecution atomic child effect | **MERGE → DELETE standalone authority** | Merge into ClaimExecution decision/UoW; no externally invokable ConsumeApproval capability. |
| `domain/approval/transitions/revoke_approval.py` | Standalone child-effect transition | Modify/Reject/Cancel/Supersede child effect | **MERGE → DELETE standalone authority** | Merge into owning lifecycle commands; no standalone production capability. |
| `domain/policy_confirmation_receipt/` | Empty scaffold | PolicyConfirmationReceiptV1 checkpoint/audit/Approval snapshot value | **DELETE empty scaffold** | 04 explicitly says no separate Domain table/entity authority. Keep typed receipt in owning checkpoint/wire/snapshot contracts. |
| `domain/recovery/model.py` | RecoveryReasonV1 owner-local vocabulary | Recovery value-object contract | **KEEP** | Retain and extend only with source-closed Recovery value semantics; do not duplicate persistence representation. |

## 7. Hidden Domain authority outside `domain/`

| Current location | Finding | Disposition | Required closure |
|---|---|---|---|
| `ports/persistence/run_repository.py` | RunRepository still exposes command-specific lifecycle shims (complete/block/publish/cancel/reauth/recovery/set_*). | **CUTOVER** | Repository should persist a Domain decision through canonical generic/owner surface; command semantics must not remain repository authority. |
| `ports/persistence/action_repository.py` | ActionRepository still exposes claim/read/approve/modify/execution/retry/verification transition methods. | **CUTOVER** | Keep conditional persistence/CAS, remove lifecycle decision authority after Application callers use exact Domain transitions. |
| `application/read_lifecycle.py` | Owns four legacy READ action lifecycle services and parent read completion orchestration. | **SPLIT/REWIRE** | Preserve UoW/receipt/audit/ResourceRef/Evidence logic; point to four exact Domain action transitions and canonical Application use-case files. |
| `application/write_claim.py` | Strong Claim logic + Approval consume + Attempt CLAIMED + claim token creation; older broad Application authority. | **PRESERVE/SPLIT** | Use as primary reuse source for canonical claim.claim_execution and claim.build_claim_context; add missing parent Plan/Run fence. |
| `application/write_execution.py` | Validates CLAIMED attempt/Claim token then calls connector directly. | **TARGETED_CORRECTION** | Insert canonical BeginExecutionAttempt committed command before connector dispatch; later split dispatch/classify operations per manifest. |
| `application/write_action_mutation.py` | Rich Modify validators; explicitly states refresh_expired_action is not implemented. | **PRESERVE/SPLIT** | Reuse validators/helpers for canonical modify/refresh/evaluate policy operations; no wholesale rewrite. |
| `application/write_cancellation.py` | Broad cancel flow uses RunRepository command methods and set_recovery/set_verifying shortcuts. | **SPLIT/REWIRE** | Preserve cancellation sequencing but route all lifecycle decisions through exact Domain/Application authorities; add AbortClaimedExecution path. |
| `application/calendar_conflicts.py / feasibility.py / task_duplicates.py` | Application broad deterministic validator modules coexist with Domain pure kernels. | **MERGE/SPLIT** | Owner-localize into canonical Action policy / Work Analysis deterministic responsibilities; final application root should contain __init__.py only. |

## 8. Test ownership mapping

| Area | Current evidence | Canonical gap/action |
|---|---|---|
| Run | Many exact transition tests exist under tests/unit/domain/run/transitions/ | Missing canonical begin_verification + complete_read_only_run; publish_plan test is under Run instead of Plan. |
| Action | tests/unit/domain/action/test_action_approval_claim_transitions.py + only test_prepare_write_retry.py under transitions/ | Broad mixed-owner test must split into canonical action/approval/claim paths; READ four, refresh, approve/modify/reject/cancel tests missing exact mirror ownership. |
| ExecutionAttempt | Five exact tests for store/mark/recover/resolve | begin_execution_attempt + abort_claimed_execution tests absent. |
| Recovery | Exact require_recovery and resolve_recovery tests now exist after #98 | Keep; add/retain reason matrix + durable-context integration coverage. |
| Verification | Current transition exists but canonical owner test mirror is not closed in the inspected owner tree | Add exact test_store_verification.py with NOT_FOUND/ERROR fail-closed cases. |
| Models/vocab | Root tests test_enums/test_action_risk/etc target legacy/root authority | Move/split tests with model/policy relocation; architecture tests must assert old barrels/root semantic authorities absent. |

## 9. Highest-risk semantic defects confirmed

1. **BeginExecutionAttempt is absent.** Current write execution validates an Attempt in `CLAIMED` and can proceed toward connector execution without the required committed `CLAIMED → EXECUTING` Domain/Application command cut. This is a crash/delivery-certainty boundary defect, not a naming issue.
2. **AbortClaimedExecution is absent.** There is no single pre-dispatch authority that atomically settles `Attempt CLAIMED → FAILED` and `Action EXECUTING → CANCELLED|FAILED` while proving provider dispatch=0.
3. **Repository lifecycle shims remain live.** `RunRepository` and `ActionRepository` still expose command-specific transition methods, so Domain/Application/Repository authority is not yet singular.
4. **Run/Action broad transition authorities remain.** `domain/run/transitions/run.py` and `domain/action/transitions/action.py` coexist with operation-per-file transitions and are still imported through the Domain barrel.
5. **Verification coercion is unsafe.** Current `StoreVerification` maps every non-VERIFIED `VerificationStatus` to MISMATCH; current contracts require durable outcome to be exactly VERIFIED|MISMATCH and observation NOT_FOUND/ERROR to be handled separately/fail-closed.
6. **Plan model/transition owner is mostly empty.** `domain/plan/` is scaffold-only while Plan model/status and publish semantics remain in `ports.models`, Run transition code and repository/application paths.
7. **Claim parent-authority fence is incomplete.** Current Claim guard has strong approval/hash/version/dependency checks, but does not itself require owning Plan=current published `WAITING_APPROVAL` and Run exactly `WAITING_APPROVAL|VERIFYING`.
8. **Concrete Domain barrel remains.** `domain/__init__.py` re-exports broad transitions, policy and registries, hiding concrete callers and preventing final negative-closure proof.

## 10. Preservation-first implementation order for Domain

1. **Models first:** materialize the 15 canonical model rows by moving/merging `ports.models` records and current Domain helpers into owner-local models. Do not delete reusable record definitions before callers are rewired.
2. **Split vocabularies:** move lifecycle statuses to owner models; remove cross-owner command enums; split durable Verification outcome from observation outcomes.
3. **Close missing transition files:** `complete_read_only_run`, `begin_verification`, Plan publish pair, `refresh_expired_action`, READ four, `begin_execution_attempt`, `abort_claimed_execution`.
4. **Move misplaced transitions:** `run.publish_plan → plan.publish_plan`; `approval.approve_action → action.approve_action`; retain #98 Recovery/ExecutionAttempt owner moves.
5. **Targeted guard corrections:** published Review gates, child-fact fences, SUPERSEDED Plan fence, Reauth matrix, RecoveryContext, joint Action/Attempt transitions, Verification fail-closed.
6. **Rewire Application callers** to exact Domain operation files. Preserve current UoW/receipt/audit/ResourceRef/Evidence/Claim validation logic wherever compatible.
7. **Reduce Repository to persistence/CAS:** command-specific lifecycle semantics must stop being a second authority.
8. **Delete broad/compat authority only after cut-over:** `run.py`, `action.py`, concrete Domain barrel exports, standalone consume/revoke child-effect authorities, misplaced provider/tool-policy Domain files.
9. **Move/split tests** to canonical mirror paths and add negative architecture assertions for old paths/imports/exports.
10. **Final Domain closure scan:** canonical→current unmapped=0; current→canonical unmapped=0; old concrete callers/imports/exports=0; duplicate production authority=0.

## 11. Disposition summary

Primary disposition count (compound dispositions counted by their first action):

- **CREATE: 5**
- **KEEP: 5**
- **MERGE: 4**
- **MOVE_RENAME: 11**
- **SPLIT: 7**
- **TARGETED_CORRECTION: 22**

### Mapping verdict

**DOMAIN PHASE-2 STRUCTURAL INVENTORY COVERAGE = COMPLETE @ `453e7f0c3fb5305775f709d91fe001673b5e0651`**

Meaning: the corrected bounded **61-row Domain structural inventory** (1 repository root + 15 models + 39 lifecycle transitions + 6 closed vocabularies) and the inspected current Domain semantic/broad authorities are mapped to explicit preservation-first dispositions with no intentional unmapped Domain row in that universe.

**DOMAIN IMPLEMENTATION CLOSURE = NOT COMPLETE**

**DOMAIN SINGLE-PRODUCTION-AUTHORITY CLOSURE = NOT COMPLETE**

Current production still has duplicate/broad lifecycle authority, missing exact canonical operations/models, live repository transition shims and incomplete test/caller cut-over. Therefore **DOMAIN FROZEN = NO** at this SHA.

## 12. Current-head override — Issue #104 Domain closure @ `a03432c8`

The historical mapping above remains the preservation record for `453e7f0c`. Current code materially supersedes its implementation-status findings. At implementation evidence `c495c12dc919369990440c56efd9fc2fdd8b0c86` (recorded in repository at `a03432c8fa6d722c6ef93b54ff8de5aa16eeac0a`), the repository reports the bounded Domain model/transition closure as **15/15 models + 39/39 transitions = 54/54**, with zero remaining `OPEN | PARTIAL | OWNER_PARTIAL` rows in that bounded #104 set.

Current reverse-authority facts independently rechecked at `a03432c8fa6d722c6ef93b54ff8de5aa16eeac0a`:

- `ports/models.py` is removed; owner-local Domain records are imported by Persistence/Application.
- `domain/enums.py` is removed; status vocabularies live under their aggregate models.
- `domain/__init__.py` exposes no concrete authority (`__all__ = ()`).
- broad `domain/run/transitions/run.py` and `domain/action/transitions/action.py` are removed.
- canonical owner-local model/transition files exist for the #104 54-row bounded set.
- the repaired vocabulary rows remain distinct from the #104 54-row closure: `STR-354..358` have correct owner-local values but still require the Ledger’s exact `*StatusV1` symbol closure; `STR-359` is exact.

**Current Domain interpretation:** #104 core model/transition migration is **CLOSED**; the corrected 61-row mapping inventory is **CLOSED**, but the full 61-row implementation should not be called structurally frozen until the five exact `*StatusV1` vocabulary symbols and cross-layer negative proof are closed.
