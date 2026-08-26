# Issue #104 Canonical Domain Closure

- Start SHA: `93f03a918cbd9cfd047da1c1b1ee70aca76da8f6`
- Implementation evidence SHA: `c495c12dc919369990440c56efd9fc2fdd8b0c86`
- Bounded inventory: models `15/15`, transitions `39/39`, total `54/54`
- Remaining `OPEN | PARTIAL | OWNER_PARTIAL`: `0`

`C/C/C` means Behavior Coverage, Canonical Owner Coverage, and Structural Coverage are all
`COMPLETE`. Caller is `canonical production caller count / legacy caller count`; `none/0`
means the transition is materialized and tested but no production command currently invokes it.
Duplicate is the remaining production authority count outside the canonical owner.

## Models — 15/15

| Row | Capability | Coverage | Caller | Duplicate | Original implementation source | Disposition | Canonical path/symbol | Canonical test owner | Evidence SHA |
|---|---|---|---|---:|---|---|---|---|---|
| STR-339 | Conversation | C/C/C | imports cut over/0 | 0 | `ports/models.py::ConversationRecord` + existing owner guard | MERGE | `domain/conversation/model.py::Conversation` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-340 | Message | C/C/C | imports cut over/0 | 0 | `ports/models.py::MessageRecord` + size invariant | MERGE | `domain/message/model.py::Message` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-341 | Run | C/C/C | imports cut over/0 | 0 | `ports/models.py::RunRecord/RunCreateRecord` + owner vocabulary | MERGE + TARGETED_CORRECTION | `domain/run/model.py::Run` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-342 | Plan | C/C/C | imports cut over/0 | 0 | `ports/models.py::PlanRecord/PlanStatus/PlanReviewStatus` | MOVE_RENAME + TARGETED_CORRECTION | `domain/plan/model.py::Plan` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-343 | Action | C/C/C | imports cut over/0 | 0 | `ports/models.py::ActionRecord` + `domain/action/model.py` | MERGE + TARGETED_CORRECTION | `domain/action/model.py::Action` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-344 | Approval | C/C/C | imports cut over/0 | 0 | `ports/models.py::ApprovalRecord` + `domain/enums.py` | MOVE_RENAME | `domain/approval/model.py::Approval` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-345 | ExecutionAttempt | C/C/C | imports cut over/0 | 0 | `ports/models.py::ExecutionAttemptRecord` + `domain/enums.py` | MOVE_RENAME | `domain/execution_attempt/model.py::ExecutionAttempt` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-346 | Verification | C/C/C | imports cut over/0 | 0 | `ports/models.py::VerificationRecord` + mixed observation enum | MOVE_RENAME + TARGETED_CORRECTION | `domain/verification/model.py::Verification` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-347 | ResourceRef | C/C/C | imports cut over/0 | 0 | `ports/models.py::ResourceRefRecord/StoredResourceType` | MOVE_RENAME + TARGETED_CORRECTION | `domain/resource_ref/model.py::ResourceRef` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-348 | Evidence | C/C/C | imports cut over/0 | 0 | `ports/models.py::EvidenceRecord/EvidenceOriginType` | MOVE_RENAME | `domain/evidence/model.py::Evidence` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-349 | CommandReceipt | C/C/C | imports cut over/0 | 0 | `ports/models.py::CommandReceiptRecord/Status` | MOVE_RENAME | `domain/command_receipt/model.py::CommandReceipt` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-350 | ActionDependency | C/C/C | persistence edge typed/0 | 0 | `action_dependencies(action_id, depends_on_action_id)` persistence semantics | CREATE | `domain/action/model.py::ActionDependency` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-351 | ActionEvidence | C/C/C | persistence edge typed/0 | 0 | `EvidenceRepository.link_to_action` relation semantics | CREATE | `domain/action/model.py::ActionEvidence` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-352 | TraceEvent | C/C/C | imports cut over/0 | 0 | `ports/models.py::TraceEventRecord` | MOVE_RENAME | `domain/trace_event/model.py::TraceEvent` | `tests/architecture/test_domain_closure.py` | `c495c12d` |
| STR-353 | AuditEvent | C/C/C | imports cut over/0 | 0 | `ports/models.py::AuditEventRecord` | MOVE_RENAME | `domain/audit_event/model.py::AuditEvent` | `tests/architecture/test_domain_closure.py` | `c495c12d` |

## Lifecycle transitions — 39/39

| Row | Capability | Coverage | Caller | Duplicate | Original implementation source | Disposition | Canonical path/symbol | Canonical test owner | Evidence SHA |
|---|---|---|---|---:|---|---|---|---|---|
| STR-399 | run.start_run | C/C/C | 1/0 | 0 | exact transition/guard | KEEP | `domain/run/transitions/start_run.py::transition_start_run` | `tests/unit/domain/run/transitions/test_start_run.py` | `c495c12d` |
| STR-400 | run.start_analysis | C/C/C | 1/0 | 0 | exact transition + broad delegate | KEEP + DELETE COMPAT | `domain/run/transitions/start_analysis.py::transition_start_analysis` | `tests/unit/domain/run/transitions/test_start_analysis.py` | `c495c12d` |
| STR-401 | run.begin_retrieval | C/C/C | 1/0 | 0 | exact transition + broad delegate | KEEP + DELETE COMPAT | `domain/run/transitions/begin_retrieval.py::transition_begin_retrieval` | `tests/unit/domain/run/transitions/test_begin_retrieval.py` | `c495c12d` |
| STR-402 | run.begin_planning | C/C/C | 1/0 | 0 | exact transition/guard + Application child facts | TARGETED_CORRECTION | `domain/run/transitions/begin_planning.py::transition_begin_planning` | `tests/unit/domain/run/transitions/test_begin_planning.py` | `c495c12d` |
| STR-403 | run.request_confirmation | C/C/C | 1/0 | 0 | exact transition/guard + Application checkpoint facts | TARGETED_CORRECTION | `domain/run/transitions/request_confirmation.py::transition_request_confirmation` | `tests/unit/domain/run/transitions/test_request_confirmation.py` | `c495c12d` |
| STR-404 | run.resume_confirmation | C/C/C | 1/0 | 0 | exact transition with incomplete safe restore set | TARGETED_CORRECTION | `domain/run/transitions/resume_confirmation.py::transition_resume_confirmation` | `tests/unit/domain/run/transitions/test_resume_confirmation.py` | `c495c12d` |
| STR-405 | run.complete_answer_only_run | C/C/C | 1/0 | 0 | exact state transition + Application aggregate checks | TARGETED_CORRECTION | `domain/run/transitions/complete_answer_only_run.py::transition_complete_answer_only_run` | `tests/unit/domain/run/transitions/test_complete_answer_only_run.py` | `c495c12d` |
| STR-406 | run.complete_read_only_run | C/C/C | 1/0 | 0 | `application/read_lifecycle.py` + repository lifecycle shim | SPLIT + TARGETED_CORRECTION | `domain/run/transitions/complete_read_only_run.py::transition_complete_read_only_run` | `tests/unit/domain/run/transitions/test_complete_read_only_run.py` | `c495c12d` |
| STR-407 | plan.publish_plan | C/C/C | 1/0 | 0 | misplaced Run transition + Plan/Run repository shims | MOVE_RENAME + TARGETED_CORRECTION | `domain/plan/transitions/publish_plan.py::transition_publish_plan` | `tests/unit/domain/plan/transitions/test_publish_plan.py` | `c495c12d` |
| STR-408 | plan.publish_read_only_plan | C/C/C | 1/0 | 0 | read flow + Plan/Run repository shims | SPLIT + MOVE_RENAME | `domain/plan/transitions/publish_read_only_plan.py::transition_publish_read_only_plan` | `tests/unit/domain/plan/transitions/test_publish_read_only_plan.py` | `c495c12d` |
| STR-409 | run.block_run | C/C/C | 1/0 | 0 | exact transition + broad/repository authority | TARGETED_CORRECTION + DELETE COMPAT | `domain/run/transitions/block_run.py::transition_block_run` | `tests/unit/domain/run/transitions/test_block_run.py` | `c495c12d` |
| STR-410 | run.begin_verification | C/C/C | 6/0 | 0 | broad Run table + repository setter | SPLIT + TARGETED_CORRECTION | `domain/run/transitions/begin_verification.py::transition_begin_verification` | `tests/unit/domain/run/transitions/test_begin_verification.py` | `c495c12d` |
| STR-411 | run.complete_write_run | C/C/C | 3/0 | 0 | exact file + broad/repository authority | TARGETED_CORRECTION + DELETE COMPAT | `domain/run/transitions/complete_write_run.py::transition_complete_write_run` | `tests/unit/domain/run/transitions/test_complete_write_run.py` | `c495c12d` |
| STR-412 | run.request_cancel | C/C/C | 2/0 | 0 | exact transition + broad/repository authority | KEEP + DELETE COMPAT | `domain/run/transitions/request_cancel.py::transition_request_cancel` | `tests/unit/domain/run/transitions/test_request_cancel.py` | `c495c12d` |
| STR-413 | run.finalize_cancel | C/C/C | 2/0 | 0 | exact transition + Application child settlement | TARGETED_CORRECTION | `domain/run/transitions/finalize_cancel.py::transition_finalize_cancel` | `tests/unit/domain/run/transitions/test_finalize_cancel.py` | `c495c12d` |
| STR-414 | run.require_reauth | C/C/C | 3/0 | 0 | exact transition missing cancel source | TARGETED_CORRECTION | `domain/run/transitions/require_reauth.py::transition_require_reauth` | `tests/unit/domain/run/transitions/test_require_reauth.py` | `c495c12d` |
| STR-415 | run.resume_after_reauth | C/C/C | 1/0 | 0 | exact transition with incomplete child matrix | TARGETED_CORRECTION | `domain/run/transitions/resume_after_reauth.py::transition_resume_after_reauth` | `tests/unit/domain/run/transitions/test_resume_after_reauth.py` | `c495c12d` |
| STR-416 | recovery.require_recovery | C/C/C | 7/0 | 0 | owner-local transition + Application durable context | TARGETED_CORRECTION | `domain/recovery/transitions/require_recovery.py::transition_require_recovery` | `tests/unit/domain/recovery/transitions/test_require_recovery.py` | `c495c12d` |
| STR-417 | recovery.resolve_recovery | C/C/C | 1/0 | 0 | owner-local reason-aware transition | KEEP + DELETE COMPAT | `domain/recovery/transitions/resolve_recovery.py::transition_resolve_recovery` | `tests/unit/domain/recovery/transitions/test_resolve_recovery.py` | `c495c12d` |
| STR-418 | action.approve_action | C/C/C | 2/0 | 0 | misplaced Approval transition + Action handlers | MOVE_RENAME + TARGETED_CORRECTION | `domain/action/transitions/approve_action.py::transition_approve_action` | `tests/unit/domain/action/transitions/test_approve_action.py` | `c495c12d` |
| STR-419 | action.modify_action | C/C/C | 3/0 | 0 | exact transition + broad/repository authority | TARGETED_CORRECTION + DELETE COMPAT | `domain/action/transitions/modify_action.py::transition_modify_action` | `tests/unit/domain/action/transitions/test_modify_action.py` | `c495c12d` |
| STR-420 | action.reject_action | C/C/C | 2/0 | 0 | exact transition + broad/repository authority | TARGETED_CORRECTION + DELETE COMPAT | `domain/action/transitions/reject_action.py::transition_reject_action` | `tests/unit/domain/action/transitions/test_reject_action.py` | `c495c12d` |
| STR-421 | action.cancel_pending_action | C/C/C | 3/0 | 0 | exact transition + broad/repository authority | TARGETED_CORRECTION + DELETE COMPAT | `domain/action/transitions/cancel_pending_action.py::transition_cancel_pending_action` | `tests/unit/domain/action/transitions/test_cancel_pending_action.py` | `c495c12d` |
| STR-422 | approval.expire_approval | C/C/C | none/0 | 0 | exact transition + standalone consume/revoke child files | TARGETED_CORRECTION + DELETE DUPLICATES | `domain/approval/transitions/expire_approval.py::transition_expire_approval` | `tests/unit/domain/approval/transitions/test_expire_approval.py` | `c495c12d` |
| STR-423 | action.refresh_expired_action | C/C/C | none/0 | 0 | validators/helpers existed; exact command semantics absent | CREATE | `domain/action/transitions/refresh_expired_action.py::transition_refresh_expired_action` | `tests/unit/domain/action/transitions/test_refresh_expired_action.py` | `c495c12d` |
| STR-424 | action.claim_read_action | C/C/C | 1/0 | 0 | broad Action transition + read lifecycle service | SPLIT | `domain/action/transitions/claim_read_action.py::transition_claim_read_action` | `tests/unit/domain/action/transitions/test_claim_read_action.py` | `c495c12d` |
| STR-425 | action.complete_read_action | C/C/C | 1/0 | 0 | broad Action transition + read lifecycle service | SPLIT | `domain/action/transitions/complete_read_action.py::transition_complete_read_action` | `tests/unit/domain/action/transitions/test_complete_read_action.py` | `c495c12d` |
| STR-426 | action.finalize_read_action | C/C/C | 1/0 | 0 | broad Action transition + read lifecycle service | SPLIT | `domain/action/transitions/finalize_read_action.py::transition_finalize_read_action` | `tests/unit/domain/action/transitions/test_finalize_read_action.py` | `c495c12d` |
| STR-427 | action.fail_read_action | C/C/C | 1/0 | 0 | broad Action transition + read lifecycle service | SPLIT | `domain/action/transitions/fail_read_action.py::transition_fail_read_action` | `tests/unit/domain/action/transitions/test_fail_read_action.py` | `c495c12d` |
| STR-428 | claim.claim_execution | C/C/C | 2/0 | 0 | exact transition/guard + broad Action mapping | TARGETED_CORRECTION + DELETE COMPAT | `domain/claim/transitions/claim_execution.py::transition_claim_execution` | `tests/unit/domain/claim/transitions/test_claim_execution.py` | `c495c12d` |
| STR-429 | execution_attempt.begin_execution_attempt | C/C/C | 1/0 | 0 | pre-dispatch checks embedded in execution services | CREATE + TARGETED CORRECTION | `domain/execution_attempt/transitions/begin_execution_attempt.py::transition_begin_execution_attempt` | `tests/unit/domain/execution_attempt/transitions/test_begin_execution_attempt.py` | `c495c12d` |
| STR-430 | execution_attempt.abort_claimed_execution | C/C/C | 1/0 | 0 | cancellation/failure facts existed without exact pre-dispatch authority | CREATE + TARGETED CORRECTION | `domain/execution_attempt/transitions/abort_claimed_execution.py::transition_abort_claimed_execution` | `tests/unit/domain/execution_attempt/transitions/test_abort_claimed_execution.py` | `c495c12d` |
| STR-431 | execution_attempt.store_success | C/C/C | 2/0 | 0 | Action-only result transition | REWRITE JOINT DECISION | `domain/execution_attempt/transitions/store_success.py::transition_store_success` | `tests/unit/domain/execution_attempt/transitions/test_store_success.py` | `c495c12d` |
| STR-432 | execution_attempt.mark_failed | C/C/C | 2/0 | 0 | Action-only result transition | REWRITE JOINT DECISION | `domain/execution_attempt/transitions/mark_failed.py::transition_mark_failed` | `tests/unit/domain/execution_attempt/transitions/test_mark_failed.py` | `c495c12d` |
| STR-433 | execution_attempt.mark_unknown_result | C/C/C | 2/0 | 0 | Action-only result transition | REWRITE JOINT DECISION | `domain/execution_attempt/transitions/mark_unknown_result.py::transition_mark_unknown_result` | `tests/unit/domain/execution_attempt/transitions/test_mark_unknown_result.py` | `c495c12d` |
| STR-434 | execution_attempt.recover_existing_result | C/C/C | 2/0 | 0 | Action-only recovery result | REWRITE JOINT DECISION | `domain/execution_attempt/transitions/recover_existing_result.py::transition_recover_existing_result` | `tests/unit/domain/execution_attempt/transitions/test_recover_existing_result.py` | `c495c12d` |
| STR-435 | execution_attempt.resolve_as_failed | C/C/C | 2/0 | 0 | Action-only recovery result | REWRITE JOINT DECISION | `domain/execution_attempt/transitions/resolve_as_failed.py::transition_resolve_as_failed` | `tests/unit/domain/execution_attempt/transitions/test_resolve_as_failed.py` | `c495c12d` |
| STR-436 | verification.store_verification | C/C/C | 2/0 | 0 | exact transition coerced every non-VERIFIED observation to MISMATCH | REWRITE FAIL-CLOSED | `domain/verification/transitions/store_verification.py::transition_store_verification` | `tests/unit/domain/verification/transitions/test_store_verification.py` | `c495c12d` |
| STR-437 | action.prepare_write_retry | C/C/C | 2/0 | 0 | exact transition + broad Action delegate | TARGETED_CORRECTION + DELETE COMPAT | `domain/action/transitions/prepare_write_retry.py::transition_prepare_write_retry` | `tests/unit/domain/action/transitions/test_prepare_write_retry.py` | `c495c12d` |

## Closure evidence

- Canonical owner-local models: 15 symbols, with `ActionDependency` and `ActionEvidence`
  sharing the Action owner as required.
- Exact lifecycle tree: 39 production transition files and 39 exact mirrored test files.
- Removed authority: `ports/models.py`, `ports/repositories.py`, `domain/enums.py`, broad
  `run/transitions/run.py`, broad `action/transitions/action.py`, misplaced Plan/Action
  transitions, and standalone Approval child-effect transition files.
- Repository boundary: Run, Plan, Action, Approval, ExecutionAttempt, and Verification
  repositories expose persistence/query/CAS only; command-specific lifecycle methods are absent
  from both Ports and SQLite adapters.
- Domain dependency boundary: Domain imports to Application/Adapters/API/Ports are zero;
  `domain/__init__.py` exports no concrete authority.
- Safety: Claim commit remains separate; `BeginExecutionAttempt(applied=true)` is committed before
  connector prepare/execute; `AbortClaimedExecution` is pre-dispatch only and performs zero
  connector writes. Current Plan/Run/cancel/hash/token/Approval/Attempt facts are revalidated.
- Verification durable vocabulary is exactly `VERIFIED | MISMATCH`; read observations such as
  `NOT_FOUND | ERROR` fail closed and are not persisted as MISMATCH.

## Preservation justification

- CREATE was limited to two typed join models and exact transition authorities whose reusable
  semantics existed only as persistence edges, broad tables, or Application checks. Existing
  validators, CAS operations, receipts, audits, and connector boundaries were retained.
- REWRITE was limited to unsafe semantics: five Action-only Attempt decisions became joint
  Action+ExecutionAttempt decisions, and Verification stopped coercing indeterminate observations
  to MISMATCH.
- DELETE occurred only after import/caller cut-over. Deleted broad/misplaced/barrel/repository
  facades contained no remaining independent behavior; preserved behavior now resides in the
  exact owner transition plus Application UoW orchestration and persistence CAS.
