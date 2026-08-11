# Domain 상태 전이 계약 v1.4

## 책임

- LangGraph Supervisor: Node·Edge 선택과 deterministic insufficient-data guard
- Application: Use Case·Command Receipt·외부 호출 조정, Canonical Request Hash 계산
- Domain: Guard와 허용 전이
- Repository: 조건부 UPDATE·필수 Audit·Receipt Transaction
- SQLite: Constraint와 동시성 최종 방어

## 공통 Command Result

`applied`, `result_code`, `current_status`, `current_version`, `next_allowed_commands`, `conflict_detail`

## Command Receipt

모든 상태 변경 Command는 `command_id`와 **서버가 Versioned Request Schema에서 계산한 Canonical Request Hash**를 사용한다. Receipt 검증은 Approval·Plan·Action 변경보다 먼저 완료하며 Receipt와 실제 Domain 변경은 같은 Transaction으로 완료한다.

- 같은 `command_id + 같은 hash`: 기존 결과 반환
- 같은 `command_id + 다른 hash`: Conflict, Domain 변경 0

## Run Command

| Command | 허용 전이 |
|---|---|
| StartRun | Conversation Open Run 없음 → CREATED |
| StartAnalysis | CREATED → ANALYZING |
| BeginRetrieval | ANALYZING·WAITING_CONFIRMATION → RETRIEVING |
| RequestConfirmation | ANALYZING·RETRIEVING·PLANNING → WAITING_CONFIRMATION |
| ResumeConfirmation | WAITING_CONFIRMATION → Checkpoint 허용 Phase |
| PublishPlan | PLANNING → WAITING_APPROVAL 또는 EXECUTING |
| CompleteAnswerOnlyRun | ANALYZING·RETRIEVING·PLANNING → COMPLETED |
| BeginVerification | WAITING_APPROVAL·EXECUTING·CANCEL_REQUESTED → VERIFYING. 승인형 Write는 Domain Run이 EXECUTING을 거치지 않고 WAITING_APPROVAL에 머무르므로 이 경로가 실제 지배적 경로다. CANCEL_REQUESTED에서는 취소 확정 전 이미 EXECUTED된 결과의 재확인용 |
| CompleteWriteRun | VERIFYING → COMPLETED |
| RequestCancel | 비Terminal → CANCEL_REQUESTED. 성공 후 새 Claim·Write 금지 |
| FinalizeCancel | CANCEL_REQUESTED → CANCELLED. in-flight 결과가 모두 확정되어야 함 |
| RequireReauth | RETRIEVING·WAITING_APPROVAL·EXECUTING → REAUTH_REQUIRED |
| ResumeAfterReauth | REAUTH_REQUIRED → Checkpoint 허용 Phase |
| RequireRecovery | 비Terminal → RECOVERY_REQUIRED |
| ResolveRecovery(verification-recheck) | RECOVERY_REQUIRED → VERIFYING |
| ResolveRecovery(accept-partial) | RECOVERY_REQUIRED → COMPLETED + result_kind PARTIAL |
| ResolveRecovery(corrective-plan) | RECOVERY_REQUIRED → PLANNING + 새 Plan Revision |
| ResolveRecovery(cancel) | RECOVERY_REQUIRED → CANCELLED |
| ResolveRecovery(fail) | RECOVERY_REQUIRED → FAILED |

## Action·Approval·Attempt Command

| Command | 허용 전이 |
|---|---|
| ApproveAction | PROPOSED·MODIFIED → APPROVED |
| ModifyAction | PROPOSED·APPROVED·EXPIRED·FAILED → MODIFIED |
| RejectAction | PROPOSED·MODIFIED → REJECTED |
| CancelPendingAction | PROPOSED·MODIFIED·APPROVED·EXPIRED → CANCELLED; ACTIVE Approval REVOKED; 새 Attempt·Verification 0 |
| ExpireApproval | APPROVED → EXPIRED |
| ClaimReadAction | READ PROPOSED → EXECUTING |
| CompleteReadAction | READ EXECUTING → EXECUTED |
| FinalizeReadAction | READ EXECUTED → VERIFIED |
| FailReadAction | READ EXECUTING → FAILED |
| ClaimExecution | WRITE APPROVED → EXECUTING + Approval CONSUMED + Attempt CLAIMED |
| StoreSuccess | EXECUTING → EXECUTED + Attempt SUCCEEDED |
| MarkFailed | EXECUTING → FAILED + Attempt FAILED, `delivery_certainty=NOT_SENT` 필요 |
| MarkUnknownResult | EXECUTING → UNKNOWN_RESULT + Attempt UNKNOWN_RESULT |
| RecoverExistingResult | UNKNOWN_RESULT → EXECUTED |
| ResolveAsFailed | UNKNOWN_RESULT → FAILED, 기존 결과 미실행 확정 필요 |
| StoreVerification | EXECUTED → VERIFIED·MISMATCH; MISMATCH면 Run RECOVERY_REQUIRED |
| PrepareWriteRetry | FAILED → MODIFIED |

## Verification MISMATCH Recovery

- Action `MISMATCH`와 기존 Verification은 terminal·immutable이다.
- `ACCEPT_PARTIAL`: 기존 Google 상태를 수용하고 미실행 Action은 `CANCELLED`; 새 Write 0; Run `COMPLETED` + `PARTIAL`.
- `CREATE_CORRECTIVE_PLAN`: Run `PLANNING`; 실제 Google 상태를 새 Source Snapshot으로 사용해 새 Plan Revision 생성.
- 교정 Write는 새 Approval·Claim·Attempt·Verification을 요구한다.
- 기존 MISMATCH Action을 `EXECUTING`으로 되돌리거나 자동 Rollback하지 않는다.

## Write Delivery Classification

`NOT_SENT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST`

- `NOT_SENT`만 Google 미변경이 확정된 실패로 `FAILED` 처리할 수 있다.
- dispatch 이후 Timeout·5xx·response loss·전달 여부 불명 transport/process exit는 미전달 보장이 없으면 `UNKNOWN_RESULT`다.
- `UNKNOWN_RESULT`에서 새 Attempt·blind resend를 금지한다.

## 취소 불변조건

- RequestCancel의 Receipt/Version 판정 전 Approval revoke·Plan cancel·Action mutation 0.
- `CANCEL_REQUESTED` 이후 새 Claim·Write 0.
- `EXECUTING`은 결과 확정 전 취소 상태로 덮어쓰지 않는다.
- `EXECUTED`는 Verification 후 취소를 마무리한다.
- `UNKNOWN_RESULT`가 남으면 `RECOVERY_REQUIRED`; 결과 확정 후 cancel intent를 이어간다.
- 성공한 Google Write는 rollback하지 않는다.

## 정보 부족 Supervisor Guard

우선순위:

1. required safety/POLICY issue → BLOCKED
2. required USER issue → NEEDS_CONFIRMATION
3. required GOOGLE issue + budget → RETRIEVE_MORE
4. budget exhausted + evidence-supported read-only → PARTIAL
5. Write 필수 정보 부족 → USER가 해결 가능하면 NEEDS_CONFIRMATION, 아니면 BLOCKED

모든 Graph Profile이 동일 Guard를 사용한다.

## 금지

- `EXPIRED → APPROVED` 직접 전이
- `FAILED → EXECUTING` 직접 전이
- `UNKNOWN_RESULT → EXECUTING`과 새 Attempt
- MISMATCH Action 재실행·자동 수정·자동 Rollback
- READ Approval·ExecutionAttempt·Verification Row
- Version 없는 Mutable UPDATE
- Browser 제공 `request_hash`·Approval authority metadata 신뢰
- 외부 호출 중 SQLite Transaction
- LangGraph Node·FastAPI Route의 SQL 직접 실행
- Claim Commit 전 MCP Write
- Claim Token 재사용

## ClaimContextV2 실행권 검증 경계

`ClaimExecution`의 Domain 상태 전이 의미와 v1.4 Command 결과는 유지한다. `ClaimContextV2`는 Claim Commit **이후 외부 MCP Write 직전**의 실행권 전달·인자 무결성 계약이며 새로운 Action/Run 상태를 추가하지 않는다. 상세 필드와 서명 규칙은 `07 Interface v2.10`, 보안 규칙은 `09 Security v2.5`가 소유한다.
