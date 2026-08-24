# 상태 전이 테스트 매트릭스 v1.9

> **선행 읽기:** `00 → 04 Domain·DB → Domain State Transition Contract`  
> **이 문서의 역할:** state-transition normative verification matrix. 선행 문서의 의미를 재정의하지 않는다.


## Authority boundary

이 문서는 `Domain State Transition Contract`와 `04 Domain·DB`의 lifecycle/persistence invariant를 검증하는 normative matrix다. 새 Command·State·Guard를 발명하지 않으며 migration 파일의 특정 SQL 문법을 behavioral authority로 승격하지 않는다.

## Command Receipt·API Trust Boundary

- Receipt·Domain·Audit 원자 Commit.
- 같은 ID·같은 서버 계산 Canonical Hash → 기존 결과.
- 같은 ID·다른 Hash → 409, Domain 변경 0.
- Browser 제공 request_hash·approval_id·idempotency_key·source_snapshot·actor identity는 authority가 아니다.
- RejectAction replay/hash/version conflict에서 child mutation과 Audit 중복 0.

## Run 시작·Planning Back-edge

- StartRun → Run CREATED.
- Request Understanding 전에 `StartAnalysis: CREATED → ANALYZING` 정확히 1회.
- `BeginRetrieval: ANALYZING | PLANNING → RETRIEVING`.
- `BeginPlanning: ANALYZING | RETRIEVING → PLANNING`; published-plan branch는 State Contract의 Review matrix 또는 validated `USER_CONTEXT_ADJUSTMENT` guard에서만 `WAITING_APPROVAL | VERIFYING → PLANNING`을 허용한다.
- 이미 target 상태인 Retrieval local loop/Planning revision에서 동일 Command 반복 0.
- Request `COMPLETE → Tool Route` Edge 누락 0.
- `NO_FETCH_NEEDED`는 SUFFICIENT와 같은 analysis guard.
- `NEEDS_MORE_DATA + budget`은 bounded local loop; budget 소진 후 `NEEDS_CONFIRMATION | PARTIAL | BLOCKED` 정규화.

## Confirmation

- `RequestConfirmation` 적용 후에만 WAITING_CONFIRMATION interrupt 생성.
- `semantic_owner_id + AgentNodeResumeTargetV2 + interrupt_id` checkpoint 보존.
- 사용자 응답 검증 후 `ResumeConfirmation`으로 발생 전 안전 상태 복원.
- same owner checkpoint resume.
- upstream 의미 변경이 없는 Confirmation에서 Request Understanding 공통 재시작 0.

## BlockRun

- Claim 전 상태 + Active/Unknown/미검증 Write Attempt 없음일 때만 허용.
- Plan 존재 시 같은 UoW 순서: 미실행 nonterminal Action `PROPOSED|MODIFIED|APPROVED|EXPIRED → BLOCKED` → ACTIVE Approval `REVOKED` → Plan `CANCELLED` → Run `BLOCKED`. `DEPENDENCY_BLOCKED` 신규 생성은 `RejectAction`만 소유한다.
- `04 Domain·DB`의 `DBI-005` cross-aggregate invariant와 충돌 없이 Commit하며 실제 migration implementation은 이 invariant를 만족해야 한다.
- in-flight Write를 Policy BLOCKED로 덮어쓰기 0.

## WRITE 정상·다중 Action

- PublishPlan → Run WAITING_APPROVAL + persisted Plan WAITING_APPROVAL.
- ClaimExecution은 Action APPROVED→EXECUTING + Approval ACTIVE→CONSUMED + 새 Attempt CLAIMED 원자 Commit이며 Receipt/Audit까지 같은 UoW다. `BeginExecutionAttempt`만 Attempt CLAIMED→EXECUTING을 허용하고 그 Commit 전 Connector Write는 0이다.
- Action 실행 중 Run은 기본 WAITING_APPROVAL 유지.
- `EXECUTED` 후 첫 검증에서 `BeginVerification: WAITING_APPROVAL → VERIFYING` 정확히 1회.
- 다중 Action에서 Run이 이미 VERIFYING이면 BeginVerification 재호출 0.
- dependent Action은 predecessor `VERIFIED` 이후에만 Claim.
- 모든 승인 Action final + unresolved 0 + cancel intent false → `CompleteWriteRun: VERIFYING → COMPLETED`, Plan COMPLETED.
- 외부 Write가 0건인 all-rejected/all-cancelled Plan도 모든 Action final + unresolved 0이면 `CompleteWriteRun: WAITING_APPROVAL → COMPLETED`, Plan COMPLETED.
- published Plan Review는 State Contract의 post-review matrix를 따른다. `WAITING_APPROVAL | VERIFYING`에서 `REVISE|RETRIEVE_MORE|ROUTE_RECONSIDERATION → BeginPlanning`, `CONFIRM → RequestConfirmation`, guarded `BLOCK → BlockRun`; 이미 발생한 external effect와 terminal Action fact는 보존한다.
- 사용자 Context Adjustment는 `WAITING_APPROVAL + current Action 전부 PROPOSED|MODIFIED + ACTIVE Approval 0 + in-flight/unknown/unverified execution 0`에서만 `BeginPlanning(USER_CONTEXT_ADJUSTMENT)`을 허용한다. current Preview에 없는 segment 제외, stale expected_retrieval_revision, 승인/실행 이후 조정은 모두 `applied=false`이고 Workflow invoke 0이다.
- `ClaimExecution` Commit만으로 MCP Write 0. `BeginExecutionAttempt` Commit(applied=true) 전 Connector Write 0.
- 유효 Claim Token single-use, Action/Approval/Business Hash/Execution Hash/Nonce 검증.
- Write 후 Effect별 결정적 Verification.

## FAILED·Retry

- `FAILED → EXECUTING` 직접 차단.
- `FAILED + NOT_SENT`는 자동 FINALIZE하지 않는다. dependency 없는 approved/executable Action이 남아 있으면 계속 실행하고, 더 이상 실행할 독립 Action이 없을 때 retry/cancel 대기.
- `PrepareWriteRetry: FAILED → MODIFIED`.
- `MODIFIED → Review → Domain Validation → 새 Approval → 새 Attempt`.
- 기존 Approval·Idempotency Key·Attempt 재사용 0.


## Coupled Action·Approval·Attempt mutation

- `ApproveAction`은 Action `PROPOSED|MODIFIED → APPROVED`와 새 Approval `ACTIVE` 생성을 같은 UoW에서 완료한다. Action만 APPROVED인데 ACTIVE Approval이 없거나 반대 상태면 실패다.
- `ExpireApproval`은 Action `APPROVED → EXPIRED`와 current Approval `ACTIVE → EXPIRED`를 함께 적용한다.
- `ModifyAction | RejectAction | CancelPendingAction`이 ACTIVE Approval을 남기면 실패다.
- `StoreSuccess | MarkFailed | MarkUnknownResult | RecoverExistingResult | ResolveAsFailed`는 Action과 current ExecutionAttempt의 coupled status를 State Contract와 정확히 일치시킨다. partial mutation은 rollback한다.

## Approval expiry refresh

- `ExpireApproval: APPROVED → EXPIRED`.
- direct `EXPIRED → APPROVED`는 항상 거절한다.
- `RefreshExpiredAction: EXPIRED → MODIFIED`는 current Source/Policy/Schema snapshot을 재계산하고 기존 Approval을 재활성화하지 않는다.
- `RefreshExpiredAction` mutation/Receipt/Audit과 `workflow_handoffs(PENDING, MAIN_CONTROL:REVIEW_ENTRY)`는 same UoW로 commit한다. refresh COMMIT 뒤 process가 죽어도 restart/redrive가 fresh Review를 exactly once continuation하고, fresh PASS 전 새 Approval은 0이다.
- Refresh 뒤 Plan review gate는 `REQUIRED`; current revision의 fresh Review PASS가 durable하게 기록된 뒤에만 새 `ApproveAction`이 가능하다.
- Refresh/Review/Approve 사이 version conflict가 발생하면 stale result/Approval 재사용 0.

## UNKNOWN_RESULT·Recovery

- UNKNOWN_RESULT에서 새 Attempt·Write 0.
- CREATE search / UPDATE target GET / SEND Sent lookup / DELETE target/absent lookup.
- 기존 결과 recovered → EXECUTED. 이후 Run이 `WAITING_APPROVAL | CANCEL_REQUESTED`이면 `BeginVerification`, 이미 `RECOVERY_REQUIRED`이면 changed external-state fingerprint 기반 `ResolveRecovery(RECHECK)`를 거친 뒤 Verification.
- Run이 이미 `VERIFYING`인 later-DAG recovered result는 `BeginVerification` 재호출 없이 바로 verification reread/`StoreVerification`으로 진행한다.
- lookup이 끝내 불명확할 때만 `RequireRecovery(UNKNOWN_RESULT)`로 Run을 `RECOVERY_REQUIRED`에 둔다.
- Recovery에서 재검증 필요할 때만 VERIFYING 복귀.
- `ResolveRecovery(FAIL)`은 FAILED→FINALIZE 단일 경로.
- `ResolveRecovery(ACCEPT_PARTIAL)`은 cancel intent false에서만 COMPLETED+PARTIAL.
- Recovery reason×resolution은 State Contract의 closed matrix와 exact match해야 한다. `CHECKPOINT_MISMATCH|CONTRACT_VIOLATION` RECHECK가 무조건 VERIFYING으로 가거나 unresolved `UNKNOWN_RESULT`에 ACCEPT_PARTIAL/FAIL을 적용하면 실패다.
- terminal `ResolveRecovery(ACCEPT_PARTIAL|CANCEL|FAIL)`는 State Contract의 pending Action/Approval/Plan coupled cleanup을 같은 UoW에 반영해야 한다.
- `CREATE_CORRECTIVE_PLAN`은 cancel intent false에서만 PLANNING + 새 Plan Revision.
- 기존 MISMATCH Action/Approval/Attempt/Verification 재사용 0.

### Post-Begin process-loss reconciliation

- `BeginExecutionAttempt(applied=true)` COMMIT 뒤 `StoreSuccess | MarkFailed | MarkUnknownResult`가 없고 process가 restart된 `Attempt=EXECUTING`은 `NOT_SENT`로 추정하지 않는다.
- MCP/LLM readiness 뒤 startup-only `execution_attempt.reconcile_inflight_executions` batch Command가 `system:execution-attempt-reconcile:<execution_attempt_id>[:phase]` family를 사용한다. `POST_BEGIN_ORPHAN`은 exactly-once `MarkUnknownResult(MAY_HAVE_BEEN_SENT)`, `UNKNOWN_RESULT_UNRESOLVED`는 existing-result lookup 후 deterministic resolution, `EXECUTED_AWAITING_VERIFICATION`은 BeginVerification/RECHECK + `...:verification` handoff, `FAILED_AWAITING_CONTINUATION`은 필요한 `...:post-failed` PREFLIGHT/CANCEL_RESOLUTION handoff를 보장한다. stable FAILED decision wait는 candidate가 아니다. live loop invocation과 original Connector Write는 각각 0회다.
- existing-result lookup이 mutation을 찾으면 `RecoverExistingResult → Verification`, 미실행을 결정적으로 증명하면 `ResolveAsFailed`, 불명확하면 `RequireRecovery(UNKNOWN_RESULT)`다.
- crash가 Begin 직후, provider 호출 중, provider success 뒤 result persistence 전 어디에서 발생해도 blind resend 0이고 restart 반복으로 새 Attempt가 생기지 않는다.

## Recovery RECHECK boundedness

- 동일 `recovery_fingerprint + external-state fingerprint + verification input`으로 `ResolveRecovery(RECHECK)`를 반복하면 `NO_PROGRESS`, Run `RECOVERY_REQUIRED` 유지, 새 Verification/Connector read/Domain mutation 0이어야 한다.
- changed external state/recovery reason/input이 있는 경우에만 새 RECHECK round를 허용한다. automatic Recovery↔Verification loop는 실패다.

## Cancel

- RequestCancel Version Conflict/다른 Hash Replay → Approval·Plan·Action 변경 0.
- APPLIED RequestCancel Receipt에서 durable cancel intent 복원.
- cancel intent 활성 이후 신규 Claim·Write 0.
- 미실행 `PROPOSED|MODIFIED|APPROVED|EXPIRED` Action은 **각각 `CancelPendingAction`** Receipt/UoW로 → CANCELLED, 해당 ACTIVE Approval REVOKED, Attempt·Verification 생성 0. 숨은 plural/batch lifecycle command를 만들지 않는다.
- in-flight Action을 취소 요청만으로 CANCELLED로 덮어쓰기 0.
- 승인형 Write는 결과를 `EXECUTED | UNKNOWN_RESULT | FAILED`로 먼저 확정.
- **Legacy READ cancel:** `PROPOSED`면 `CancelPendingAction`; `EXECUTING`이면 RequestCancel 이후 새 ConnectorRead/READ_EXECUTION reauth/retry 0. 미dispatch·failure·AUTH_EXPIRED·restart-uncertain은 `FailReadAction → FAILED`, 이미 도착한 typed success는 `CompleteReadAction → FinalizeReadAction → VERIFIED`, `EXECUTED`면 `FinalizeReadAction`; 그 뒤에만 `FinalizeCancel`. ExecutionAttempt row 생성은 항상 0.
- EXECUTED → `CANCEL_REQUESTED → BeginVerification → VERIFYING` + Verification 후 FinalizeCancel.
- UNKNOWN_RESULT → RECOVERY_REQUIRED; 결과 terminal snapshot이면 ResolveRecovery(CANCEL), recheck면 VERIFYING 후 FinalizeCancel.
- Reauth 중에도 cancel intent 유지.
- cancel intent 활성인데 CompleteWriteRun→COMPLETED로 종료 0.
- 성공 Write rollback 0; 일부 성공 취소는 Domain CANCELLED + Projection PARTIAL 가능.

## Reauth

- `RequireReauth`는 Retrieval/Planning/Approval/Legacy READ/Verification/Cancel/Recovery 안전 checkpoint를 보존하며 `pre_reauth_status`와 registered target을 저장한다. target 선택은 Run status만이 아니라 current Action/ExecutionAttempt/delivery fact를 함께 본다. cancel intent가 활성인 상태에서 resume 후 신규 Claim·Write가 생기거나 cancel intent가 사라지면 실패다.
- `WAITING_APPROVAL + no in-flight Write Attempt + BeginExecutionAttempt 전 credential failure → MAIN_CONTROL:PREFLIGHT`.
- `WAITING_APPROVAL + Attempt EXECUTING/UNKNOWN_RESULT/EXECUTED-awaiting-verification → PREFLIGHT 금지`; delivery/existing-result reconciliation 뒤 `VERIFICATION | RECOVERY`.
- `EXECUTING + Legacy READ Action EXECUTING + ExecutionAttempt row 0 + AUTH_EXPIRED + cancel_intent_active=false → MAIN_CONTROL:READ_EXECUTION`; OAuth 완료 후 같은 non-mutating READ만 재개하고 Approval/Attempt/Write 생성 0. cancel intent가 active면 READ_EXECUTION/Reauth를 시작하지 않고 Legacy READ cancel settlement로 `FAILED|VERIFIED`를 확정한 뒤 `FinalizeCancel`.
- `VERIFYING → MAIN_CONTROL:VERIFICATION`, `RECOVERY_REQUIRED → MAIN_CONTROL:RECOVERY`.
- ResumeAfterReauth는 저장된 안전 phase와 child execution predicate가 모두 여전히 유효할 때만 복귀한다.
- OAuth 성공 후 workflow resume 전에 `ResumeAfterReauth`가 반드시 `applied=true`여야 한다. Domain이 `REAUTH_REQUIRED`인 채 LangGraph만 직접 resume하면 실패다.
- 이미 dispatch된 Write 재전송 0.
- Checkpoint 유실 → RECOVERY_REQUIRED.
- cancel intent는 Reauth를 통과해 유지.


## Plan Supersession Child Authority

- published Plan `BeginPlanning(REVISE|RETRIEVE_MORE|ROUTE_RECONSIDERATION)`과 `ResolveRecovery(CREATE_CORRECTIVE_PLAN)`은 old Plan의 `ACTIVE` Approval을 `REVOKED`로 만든 뒤 같은 UoW에서 Plan `SUPERSEDED`를 commit한다. 둘 중 하나만 commit되는 snapshot 0.
- supersession commit 뒤 old Plan의 `PROPOSED|MODIFIED|APPROVED|EXPIRED` Action은 history-only다. `ApproveAction|ModifyAction|RejectAction|CancelPendingAction|ExpireApproval|RefreshExpiredAction|PrepareWriteRetry|ClaimExecution` replay/late arrival은 applied=false, new Approval/Attempt/Write 0.
- `ClaimExecution`은 Action/Approval/version/hash 외에 owning Plan=current published `WAITING_APPROVAL` + Run=`WAITING_APPROVAL|VERIFYING` + cancel intent false를 같은 UoW에서 검증한다.
- `Plan SUPERSEDED COMMIT → crash/restart → stale ClaimExecution(A_old, Approval_old)`에서 Attempt 0, Connector Write 0.
- concurrent `BeginPlanning` vs `ClaimExecution`은 두 linearization만 허용한다: supersession-first → stale Claim applied=false/Write 0; claim-first → Action EXECUTING/Attempt CLAIMED를 BeginPlanning in-flight guard가 관측해 supersession applied=false. 두 UoW가 모두 성공하는 결과 0.
- 새 Plan revision은 old Approval/idempotency/Attempt를 재사용하지 않고 fresh Review/Approval/Claim을 요구한다.

## External Control Handoff / Crash Contract

- continuation-required lifecycle mutation과 `workflow_handoffs(PENDING)` insert가 same UoW다; 둘 중 하나만 commit되는 snapshot 0.
- Confirmation/ContextAdjustment payload는 typed control envelope으로만 전달되고 raw HTTP/interrupt/checkpoint metadata Prompt injection 0.
- Approve→PREFLIGHT, Modify/PrepareRetry/RefreshExpiredAction→REVIEW_ENTRY, Reject→PREFLIGHT, Context Adjustment→RETRIEVAL_ENTRY, Cancel→CANCEL_RESOLUTION exact target.
- submit same `admission_id` replay는 idempotent ACCEPTED이며 active admission release=0. `ALREADY_RUNNING`은 different-admission conflict만 의미한다. non-ACCEPTED release 시 Run authority epoch가 unchanged면 pending latch를 보존하고, newer Cancel/Reauth/Recovery/terminal로 stale이면 NORMAL old head를 SUPERSEDED 처리하여 후행 authority를 막지 않는다. `SHUTTING_DOWN`도 same authority epoch에서는 pending 유지.
- `BINDING_MISMATCH`는 guessed resume 0 + checkpoint mismatch Recovery. valid post-commit handoff에서 `NOT_COMMITTED`은 invariant failure이며 Domain replay 0.
- crash after commit/before submit, after submit/before consume, after control-apply checkpoint/before owner node 모두 restart에서 duplicate control patch/Domain command 0.
- OAuth callback success alone Run resume 0; explicit REAUTH_COMPLETED command required.
- Recovery RECHECK reason별 target/NO_PROGRESS no-handoff matrix exact.
- `RetrievalHeadV1` stale CAS/restart CAS exact; Application checkpoint_blob deserialize 0.
- `GraphCheckpointEnvelopeV1.retrieval_cache_requirements`는 required `read_result_handle + route_id + query_identity_hash`만 포함하고 raw continuation/content는 0이다. Application checkpoint_blob deserialize=0. required Retrieval `read_result_handle`의 raw continuation은 `RunRetrievalCachePort → InMemoryRunRetrievalCache`에만 있고 Domain/Main State/Checkpoint/Prompt/Trace/Audit에는 없다. cross-run/route/query binding mismatch와 missing handle은 Provider 호출 0이다.
- resume prerequisite에서 `FOUND|EXHAUSTED`는 valid dependency다. `EXHAUSTED`는 restart 0이며 NEXT_PAGE Provider call 0이다. required handle이 missing/cross-run/binding-mismatched인 경우에만 `run.reconcile_retrieval_cache_restart`가 `system:retrieval-cache-restart:<run_id>:<checkpoint_generation>` trigger를 dedupe하고 `RETRIEVAL_CACHE_RESTART → MAIN_CONTROL:RETRIEVAL_ENTRY`를 stage한다. Background/LangGraph adapter의 direct Repository write와 raw continuation 복원은 0이다.
- cache restart는 frozen RequestIntent/InputRoute, consumed RunBudget, `exclusion_obligation_segment_ids`, `pending_user_retrieval_need`를 보존하고 새 RetrievalResult revision을 만든다. terminal `discard_run(run_id)` 뒤 old handle resolve는 MISSING이다.

### Durable multi-handoff ordering / recovery

- same Run의 concurrent Approve/Modify/Reject handoff는 server-owned `run_sequence` commit order를 사용하며 lower unsettled sequence를 건너뛰지 않는다.
- lower sequence가 CONSUMED/SUPERSEDED이고 current target guard가 여전히 유효할 때만 newer checkpoint generation으로 ordered rebind 가능; target 변경·rewind 0.
- Cancel/terminal resolution은 `supersede_unconsumed_for_run`로 **execution admission이 없는** PENDING/DISPATCHED/BLOCKED_BINDING obsolete handoff를 replacement stage 전에 same-UoW SUPERSEDED로 만든다. 이미 admission이 linearize된 row는 소급 revoke하지 않고 next safe boundary까지 먼저 settle되며 cancel intent 이후 new Claim/Write=0이다. Admission 없는 BLOCKED_BINDING을 preempt한 경우 별도 CHECKPOINT_MISMATCH Recovery=0.
- CREATED + no checkpoint에서 START admission이 아직 없으면 PENDING/BLOCKED_BINDING START를 SUPERSEDED하고 new RESUME=0, `run.continue_cancel_resolution`로 Agent/LLM/Connector/LangGraph=0이다. START admission이 이미 linearize된 DISPATCHED branch는 row를 소급 supersede하지 않으며 initialization이 cancel intent를 Agent/LLM/Connector보다 먼저 처리한다. 두 branch 모두 external effect=0, second click=0.
- execution-admission CAS: NORMAL PENDING dispatch head는 WEP 전에 `claim_execution_admission`으로 DISPATCHED+admission이 되고, CONSUMED recovery는 status를 유지한 채 latest RESUME binding admission을 저장한다. WEP ACCEPTED 뒤 persistence write=0. same-admission replay=ACCEPTED. non-ACCEPTED `release_execution_admission`은 current Run authority epoch도 재검사하여 equal epoch에서만 NORMAL PENDING/BLOCKED를 복구하고, stale epoch에서는 NORMAL을 SUPERSEDED로 retire한다; recovery는 CONSUMED 유지+admission clear다.
- BLOCKED_BINDING→RequireRecovery 사이 crash 및 live runtime mismatch는 deterministic `system:handoff-binding-recovery:<handoff_id>`로 exactly-once reconciliation 후 SUPERSEDED; process restart가 없어도 live reconciler가 수렴.
- CONSUMED continuation crash recovery는 checkpoint `active_handoff_id/run_sequence` lineage를 initial entry와 1+/2+ descendant checkpoint에서 유지하고 `CONSUMED_CONTINUATION_RECOVERY`를 사용한다. generic SAFE_CHECKPOINT_RESUME가 아니며 payload reinjection 0.
- Domain-progress fence: `REAUTH_REQUIRED|RECOVERY_REQUIRED|terminal|cancel-incompatible CANCEL_REQUESTED`가 **admission claim 전** durable이면 old admission/resume=0. Admission claim 뒤 상태가 바뀌되 owner settlement 전이면 `mark_consumed_and_clear_payload` / `complete_recovery_admission`의 Run-version CAS가 `AUTHORITY_STALE_RETIRED`를 반환하고 old owner I/O=0; NORMAL stale handoff는 같은 settlement transaction에서 SUPERSEDED, recovery admission은 clear되며 Application reconciliation이 state-specific coordinator를 선택한다. Settlement가 먼저 commit된 뒤의 later control은 다음 durable guard에서 적용되고 cancel 이후 new Claim/Write=0. Current Action/Attempt/delivery facts와 registered target guard가 admission 시점에 불일치하면 claim 자체가 실패한다.

## Startup Safe Checkpoint Resume

- `SAFE_CHECKPOINT_RESUME`는 lifecycle Command가 아니라 State Contract의 closed source-state gate를 사용하는 Application operation이다.
- `CREATED | ANALYZING | RETRIEVING | PLANNING`에서만 Domain/Checkpoint/RegisteredResumeTarget/graph_version exact match + cancel intent false + unresolved `EXECUTING|UNKNOWN_RESULT` Write fact 0일 때 허용한다.
- `WAITING_CONFIRMATION`은 snapshot/interrupt restore only이며 전용 `ResumeConfirmation` 전 LangGraph resume 0.
- `WAITING_APPROVAL`은 snapshot restore only이며 사용자 Approval/Modify/Reject/Cancel 전 generic resume 0.
- `REAUTH_REQUIRED`에서 `ResumeAfterReauth(applied=true)` 전 `SAFE_CHECKPOINT_RESUME` 0.
- `RECOVERY_REQUIRED`에서 `ResolveRecovery`/Reauth 외 generic resume 0.
- `CANCEL_REQUESTED`는 cancel-resolution coordinator만 계속하며 generic resume 0.
- `EXECUTING | VERIFYING`은 persisted execution/verification fact reconciliation이 먼저이며 dispatch/verification node generic replay 0.
- terminal Run은 snapshot 반환만 하며 resume 0.
- checkpoint/registered target/graph version mismatch는 `RequireRecovery(CHECKPOINT_MISMATCH)`로 fail closed한다.

## Retrieval·Answer-only Terminalization

- `Retrieval.PARTIAL + usable Evidence 없음`이 비Terminal Run에서 직접 FINALIZE로 가지 않음.
- 처리 불가 안내를 저장하는 `CompleteAnswerOnlyRun → COMPLETED`가 먼저 적용됨.
- Answer-only Run은 Plan·Action 없이 final ASSISTANT Message + Run terminal mutation + required Audit를 같은 UoW로 원자 저장한다. Diagnostic Trace/SSE는 post-commit이며 terminal UoW rollback 대상이 아니다.

## READ Action lifecycle

- `ClaimReadAction`: READ Action `PROPOSED → EXECUTING`; Approval/ExecutionAttempt/Verification row 생성 0.
- `CompleteReadAction`: READ Action `EXECUTING → EXECUTED`; typed Read Output Schema validation 성공 뒤에만 적용.
- `FinalizeReadAction`: successful READ Action `EXECUTED → VERIFIED`; Write Verification row를 만들지 않는다.
- `FailReadAction`: READ Action `EXECUTING → FAILED`; 같은 Action을 성공으로 위장하거나 무한 자동 retry하지 않는다.
- 모든 READ Action terminal 후 `CompleteReadOnlyRun`이 Plan/Run을 닫고, 실패 Action이 하나라도 있으면 result kind PARTIAL이다.

## Verification persistence

- `StoreVerification`: WRITE Action `EXECUTED → VERIFIED | MISMATCH`와 immutable Verification append만 같은 UoW로 commit한다.
- `MISMATCH` persistence와 Run Recovery entry를 같은 hidden mutation으로 합치지 않는다. `StoreVerification(...MISMATCH)` commit 뒤 별도 `RequireRecovery(VERIFICATION_MISMATCH)`만 `RECOVERY_REQUIRED`를 만든다.

## Legacy READ-only completion

- `PublishReadOnlyPlan → Run EXECUTING + Plan ACTIVE` 뒤 모든 READ Action이 `VERIFIED | FAILED`가 되면 `CompleteReadOnlyRun`만 Run/Plan을 COMPLETED로 닫는다.
- READ Action이 하나라도 FAILED면 result kind PARTIAL, 전부 VERIFIED면 SUCCESS다.
- `Run EXECUTING`에서 Domain Command 없이 FINALIZE하거나 `CompleteAnswerOnlyRun/CompleteWriteRun`으로 닫으면 실패다.

## Unknown Contract

- Unknown Enum/Version/Disposition → bounded repair 1회.
- 여전히 invalid이면 `RequireRecovery(CONTRACT_VIOLATION) → RECOVERY_REQUIRED`.
- 추측 Routing·다음 Agent·MCP Write·직접 FINALIZE 0.
- 복구 불가 확정 후에만 ResolveRecovery(FAIL) → FAILED.

## READ-only Legacy Compatibility

- 일반 Release Retrieval READ는 Action Row 생성 0.
- Legacy READ-only Plan은 Approval·ExecutionAttempt·Verification Row 0.
- READ Claim 경쟁 하나만 성공.
- Output Schema 실패 EXECUTING→FAILED.
- READ `VERIFIED`는 Write Verification 통계에 포함되지 않음.

## Connector Boundary

- React·FastAPI Route·Application·LangGraph·Agent·Domain의 Provider API/SDK 직접 호출 0.
- Browse/Count/Detail/Retrieval/Write/Verification/Recovery 조회는 `Application operation → Application SignedToolRegistry binding → Connector Application Port → Core-side Connector Adapter → ConnectorRuntimeRegistry + MCPClientPort → MCP` 경계를 통과하며 Application의 adapter-level registry/client 직접 호출은 0.
- Connector MCP unavailable/Schema invalid 때 Core direct Provider fallback 0.

## Insufficient Data Guard

- safety-critical/POLICY required issue → BLOCKED.
- USER required issue → NEEDS_CONFIRMATION.
- external-source required issue + budget → RETRIEVE_MORE.
- budget exhausted + usable Evidence → PARTIAL.
- budget exhausted + usable Evidence 없음 → CompleteAnswerOnlyRun.
- Write 필수 정보 부족은 PARTIAL로 실행 진행 금지.
- SINGLE/THREE/SIX 동일 semantic guard.

## Claim V2 Contract Test 경계

기존 `ClaimExecution`의 “Claim은 필요조건이지만 dispatch authority가 아님”, “claim single-use”, “Action/Approval/Hash mismatch 차단” 의미를 유지하고, 외부 Write의 유일한 lifecycle pre-dispatch gate는 `BeginExecutionAttempt` Commit(applied=true)로 검증한다. Signature·TTL·Process Instance·`execution_arguments_hash`·Nonce·MCP 실제 인자 재해시는 `12 Test` current security/execution regression contract에서 추가 검증한다.

### AbortClaimedExecution matrix cases

- `Action EXECUTING + Attempt CLAIMED + no APPLIED BeginExecutionAttempt + cancel intent → AbortClaimedExecution → Action CANCELLED + Attempt FAILED`.
- same state + restart/ClaimContext/credential pre-dispatch failure without cancel → `Action FAILED + Attempt FAILED`.
- APPLIED BeginExecutionAttempt exists → Abort forbidden; in-flight classification path only.
- Abort APPLIED → subsequent Begin/Connector Write 0.

## Workflow execution admission linearization

- `WorkflowExecutionPort.submit` 이전에 durable `WorkflowExecutionAdmissionV1`이 존재해야 한다. NORMAL은 current PENDING dispatch head를 DISPATCHED로 claim하고, CONSUMED recovery는 status를 유지하며 latest descendant checkpoint를 RESUME effective binding으로 저장한다.
- Admission claim은 handoff expected version과 owning Run authority version을 같은 SQLite transaction에서 검증한다. continuation legality를 바꾸는 child mutation도 Run version을 increment해야 한다.
- WEP `ACCEPTED` 이후 handoff persistence write는 0이다. crash after admission/before submit, after ACCEPTED/before worker, worker start before any Application callback은 모두 같은 persisted admission으로 복구한다.
- Domain Reauth/Recovery/Cancel/terminal commit이 admission claim보다 먼저면 old admission=0. Admission claim이 먼저여도 later control이 settlement 전 commit되면 settlement Run-version CAS=`AUTHORITY_STALE_RETIRED`, old owner I/O=0, NORMAL stale admitted row는 SUPERSEDED로 retire되고 recovery admission은 clear되어 후행 state-specific authority가 head blocking 없이 진행된다. Settlement가 먼저 commit되면 later control은 이미 linearize된 pure workflow segment를 소급 revoke하지 않지만 cancel intent 이후 new Claim/Write=0.
- Original START/PREFLIGHT/REVIEW binding과 latest descendant recovery binding을 혼동하지 않는다. CONSUMED recovery submission은 always existing-checkpoint RESUME이며 original START replay=0.
