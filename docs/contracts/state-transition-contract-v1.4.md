# Domain 상태 전이 계약 v1.5

> **현재 권위 정합:** `04 Domain·DB v1.21 / DB Schema v1.9`, `06 Workflow v7.22`, `07 Interface v2.23`, `09 Security v2.11`, `12 Test v3.41`을 따른다. Executable migration authority는 `src/google_work_agent/adapters/persistence/migrations/**`의 `0001~0008`이며 적용 Migration을 소급 수정하지 않는다.

## 책임

- LangGraph Supervisor: Node·Edge·Interrupt·bounded loop 선택
- Application: Use Case·Command Receipt·외부 호출 조정, Canonical Request Hash 계산
- Domain: Guard와 허용 전이의 유일한 권위
- Repository: 조건부 UPDATE·필수 Audit·Receipt Transaction
- SQLite: Constraint와 동시성·cross-aggregate invariant 최종 방어

## 공통 Command Result

`applied`, `result_code`, `current_status`, `current_version`, `next_allowed_commands`, `conflict_detail`

`applied=false`를 성공으로 추정하거나 같은 Command를 무조건 재시도하지 않는다. Application은 `current_status + next_allowed_commands`로 재조정한다.

## Command Receipt

모든 상태 변경 Command는 `command_id`와 서버가 Versioned Request Schema에서 계산한 Canonical Request Hash를 사용한다. Receipt 검증은 Domain child mutation보다 먼저 수행하고 Receipt와 Domain 변경은 같은 Transaction으로 완료한다.

- 같은 `command_id + 같은 hash`: 기존 결과 반환
- 같은 `command_id + 다른 hash`: Conflict, Domain 변경 0
- 성공한 `RequestCancel` Receipt는 Run이 `CANCELLED`로 닫힐 때까지 durable cancel intent의 기준점이다.

## Run Command

| Command | 허용 전이·핵심 Guard |
|---|---|
| StartRun | Conversation Open Run 없음 → CREATED |
| StartAnalysis | CREATED → ANALYZING |
| BeginRetrieval | ANALYZING · PLANNING → RETRIEVING. 이미 RETRIEVING인 local loop에서는 반복 호출 금지 |
| BeginPlanning | ANALYZING · RETRIEVING → PLANNING. 이미 PLANNING인 bounded revision에서는 반복 호출 금지 |
| RequestConfirmation | ANALYZING · RETRIEVING · PLANNING → WAITING_CONFIRMATION; owner_subgraph + RegisteredResumeTargetRefV1 + interrupt_id 저장 |
| ResumeConfirmation | WAITING_CONFIRMATION → 발생 전 안전 Domain 상태; same owner checkpoint resume |
| CompleteAnswerOnlyRun | ANALYZING · RETRIEVING · PLANNING → COMPLETED; Open Write/실행 중 READ/미해결 Recovery 없음 |
| PublishPlan | PLANNING → WAITING_APPROVAL |
| PublishReadOnlyPlan | Legacy/호환 READ-only Plan → EXECUTING |
| BlockRun | CREATED · ANALYZING · RETRIEVING · WAITING_CONFIRMATION · PLANNING · WAITING_APPROVAL → BLOCKED; Active/Unknown/미검증 Write Attempt 없음. Plan 존재 시 미실행 Action terminalize → ACTIVE Approval REVOKED → Plan CANCELLED → Run BLOCKED 순서 |
| BeginVerification | WAITING_APPROVAL · CANCEL_REQUESTED → VERIFYING. 정상 승인형 Write는 Action 실행 중 Run을 WAITING_APPROVAL에 유지한다 |
| CompleteWriteRun | VERIFYING → COMPLETED; 모든 승인 Action Terminal + unresolved 0 + cancel_intent_active=false |
| RequestCancel | 비Terminal Run에 취소 요청. APPLIED Receipt로 cancel intent 활성화, 신규 Claim·Write 0 |
| FinalizeCancel | CANCEL_REQUESTED · VERIFYING · REAUTH_REQUIRED → CANCELLED; cancel intent + unresolved in-flight 0 + pending terminal + Approval revoke |
| RequireReauth | ANALYZING · RETRIEVING · PLANNING · WAITING_APPROVAL · EXECUTING · VERIFYING · RECOVERY_REQUIRED → REAUTH_REQUIRED |
| ResumeAfterReauth | REAUTH_REQUIRED → Checkpoint의 안전 Phase; 이미 dispatch된 Write 재전송 금지 |
| RequireRecovery | 비Terminal → RECOVERY_REQUIRED; UNKNOWN_RESULT/MISMATCH/Checkpoint·Contract 불일치 등 reason 보존 |
| ResolveRecovery(RECHECK) | RECOVERY_REQUIRED → VERIFYING |
| ResolveRecovery(ACCEPT_PARTIAL) | RECOVERY_REQUIRED → COMPLETED + PARTIAL, `cancel_intent_active=false` 필요 |
| ResolveRecovery(CREATE_CORRECTIVE_PLAN) | RECOVERY_REQUIRED → PLANNING + 새 Plan Revision, `cancel_intent_active=false` 필요 |
| ResolveRecovery(CANCEL) | RECOVERY_REQUIRED → CANCELLED; cancel intent + terminal snapshot 필요 |
| ResolveRecovery(FAIL) | RECOVERY_REQUIRED → FAILED; 복구 불가 확정 필요 |

### Release Write Run 불변조건

- Action `EXECUTING`을 이유로 Run을 자동 `EXECUTING`으로 바꾸지 않는다.
- 첫 `EXECUTED` 결과 검증에서만 `BeginVerification`을 적용한다.
- 다중 Action DAG에서 Run이 이미 VERIFYING이면 다음 Action마다 BeginVerification을 반복하지 않는다.
- predecessor가 `VERIFIED`되기 전 dependent Action을 Claim하지 않는다.
- cancel intent가 활성인 경우 `CompleteWriteRun`보다 `FinalizeCancel`/Recovery cancel resolution이 우선한다.

## Action·Approval·Attempt Command

| Command | 허용 전이 |
|---|---|
| ApproveAction | PROPOSED·MODIFIED → APPROVED; Plan review gate PASSED 필요 |
| ModifyAction | PROPOSED·APPROVED·EXPIRED·FAILED·MODIFIED → MODIFIED; 인자 변경 시 ACTIVE Approval REVOKED + Plan review REQUIRED |
| RejectAction | PROPOSED·MODIFIED·APPROVED → REJECTED; ACTIVE Approval REVOKED; 미실행 dependent DEPENDENCY_BLOCKED |
| CancelPendingAction | PROPOSED·MODIFIED·APPROVED·EXPIRED → CANCELLED; ACTIVE Approval REVOKED; Attempt·Verification 0 |
| ExpireApproval | APPROVED → EXPIRED |
| ClaimReadAction | READ PROPOSED → EXECUTING; Approval·Attempt 없음 |
| CompleteReadAction | READ EXECUTING → EXECUTED |
| FinalizeReadAction | READ EXECUTED → VERIFIED |
| FailReadAction | READ EXECUTING → FAILED |
| ClaimExecution | WRITE APPROVED → EXECUTING + Approval CONSUMED + Attempt CLAIMED |
| StoreSuccess | EXECUTING → EXECUTED + Attempt SUCCEEDED |
| MarkFailed | EXECUTING → FAILED + Attempt FAILED; delivery_certainty=NOT_SENT 필요 |
| MarkUnknownResult | EXECUTING → UNKNOWN_RESULT + Attempt UNKNOWN_RESULT |
| RecoverExistingResult | UNKNOWN_RESULT → EXECUTED |
| ResolveAsFailed | UNKNOWN_RESULT → FAILED; 미실행 확정 필요 |
| StoreVerification | EXECUTED → VERIFIED·MISMATCH; MISMATCH면 RequireRecovery |
| PrepareWriteRetry | FAILED → MODIFIED; Review → Domain Validation → 새 Approval 필수 |

## Verification MISMATCH Recovery

- Action `MISMATCH`와 기존 Verification은 terminal·immutable이다.
- `ACCEPT_PARTIAL`: cancel intent가 없을 때만 기존 실제 외부 상태를 수용하고 새 Write 0, Run `COMPLETED + PARTIAL`.
- `CREATE_CORRECTIVE_PLAN`: cancel intent가 없을 때만 실제 외부 상태를 새 Source Snapshot으로 사용해 새 Plan Revision 생성.
- Corrective Write는 새 Approval·Claim·Attempt·Verification을 요구한다.
- cancel intent가 활성인 Recovery는 `ResolveRecovery(CANCEL)` 또는 recheck→VERIFYING→`FinalizeCancel`로 닫는다.
- 기존 MISMATCH Action을 재실행·자동 수정·자동 Rollback하지 않는다.

## Write Delivery Classification

`NOT_SENT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST`

- `NOT_SENT`만 외부 미변경이 확정된 실패로 `FAILED` 처리할 수 있다.
- dispatch 이후 Timeout·5xx·response loss·process exit에서 미전달 보장이 없으면 `UNKNOWN_RESULT`다.
- `UNKNOWN_RESULT`에서 새 Attempt·blind resend를 금지한다.
- `FAILED + NOT_SENT`는 사용자의 명시적 `prepare-retry` 또는 cancel 결정을 기다린다.

## 취소 불변조건

- RequestCancel의 Receipt/Version 판정 전 Approval revoke·Plan cancel·Action mutation 0.
- APPLIED RequestCancel Receipt가 `cancel_intent_active=true`의 영속 기준이다.
- cancel intent 이후 신규 Claim·Write 0.
- in-flight Action은 먼저 `EXECUTED | UNKNOWN_RESULT | FAILED`로 확정한다.
- EXECUTED는 Verification, UNKNOWN_RESULT는 Recovery, Credential 문제는 Reauth를 완료한다.
- 이 과정에서 Run.status가 바뀌어도 cancel intent를 잃지 않는다.
- 성공한 외부 Write는 rollback하지 않는다.

## Confirmation 불변조건

- 공식 `NEEDS_CONFIRMATION` 이후 Domain `RequestConfirmation`이 적용되기 전 interrupt를 만들지 않는다.
- checkpoint에는 `owner_subgraph + RegisteredResumeTargetRefV1 + interrupt_id`를 저장한다.
- 응답 검증 후 `ResumeConfirmation`으로 발생 전 안전 Domain 상태를 복원하고 같은 owner checkpoint에서 재개한다.
- 사용자 응답이 upstream 의미를 바꾸는 경우에만 해당 State Owner로 Back-edge한다.

## 정보 부족 Supervisor Guard

우선순위:

1. required safety/POLICY issue → BLOCKED
2. required USER issue → NEEDS_CONFIRMATION
3. required external-source issue + budget → RETRIEVE_MORE
4. budget exhausted + usable Evidence → PARTIAL
5. budget exhausted + usable Evidence 없음 → CompleteAnswerOnlyRun 후 종료
6. Write 필수 정보 부족 → USER가 해결 가능하면 NEEDS_CONFIRMATION, 아니면 BLOCKED

모든 Graph Profile이 동일 Guard를 사용한다.

## Unknown Contract Fail-Closed

알 수 없는 Enum·Schema Version·Disposition은 bounded repair 뒤 추측 Edge로 보내지 않는다. `RequireRecovery(CONTRACT_VIOLATION) → RECOVERY_REQUIRED`로 suspend하고, 복구 불가가 확정된 경우에만 `ResolveRecovery(FAIL) → FAILED`로 닫는다.

## 금지

- `EXPIRED → APPROVED` 직접 전이
- `FAILED → EXECUTING` 직접 전이
- `UNKNOWN_RESULT → EXECUTING`과 새 Attempt
- MISMATCH Action 재실행·자동 수정·자동 Rollback
- 승인형 Write Action 실행 중 Run을 자동 EXECUTING으로 덮어쓰기
- cancel intent 활성 상태에서 새 Claim/Write·CompleteWriteRun
- 비Terminal Run의 Domain Command 없는 FINALIZE
- READ Approval·ExecutionAttempt·Verification Row
- Version 없는 Mutable UPDATE
- Browser 제공 authority metadata 신뢰
- 외부 호출 중 SQLite Transaction
- LangGraph Node·FastAPI Route의 SQL 직접 실행
- Claim Commit 전 MCP Write
- Claim Token 재사용

## ClaimContextV2 실행권 검증 경계

`ClaimExecution`의 Domain 상태 전이 의미와 v1.5 Command 결과는 유지한다. `ClaimContextV2`는 Claim Commit **이후 외부 MCP Write 직전**의 실행권 전달·인자 무결성 계약이며 새로운 Action/Run 상태를 추가하지 않는다. 상세 필드와 서명 규칙은 `07 Interface v2.23`, 보안 규칙은 `09 Security v2.11`가 소유한다.
