# Domain 상태 전이 계약 v1.3

## 책임

- LangGraph Supervisor: Node·Edge 선택
- Application: Use Case·Command Receipt·외부 호출 조정
- Domain: Guard와 허용 전이
- Repository: 조건부 UPDATE·필수 Audit·Receipt Transaction
- SQLite: Constraint와 동시성 최종 방어

## 공통 Command Result

`applied`, `result_code`, `current_status`, `current_version`, `next_allowed_commands`, `conflict_detail`

## Command Receipt

모든 상태 변경 Command는 `command_id`와 Canonical Request Hash를 사용한다. Receipt와 Domain 변경은 같은 Transaction으로 완료한다.

## Run Command

| Command | 허용 전이 |
|---|---|
| StartRun | Conversation Open Run 없음 → CREATED |
| StartAnalysis | CREATED → ANALYZING |
| BeginRetrieval | ANALYZING·WAITING_CONFIRMATION → RETRIEVING |
| RequestConfirmation | ANALYZING·RETRIEVING·PLANNING → WAITING_CONFIRMATION |
| BlockRun | ANALYZING·RETRIEVING·PLANNING → BLOCKED |
| FailRun | ANALYZING·RETRIEVING·PLANNING → FAILED |
| ResumeConfirmation | WAITING_CONFIRMATION → Checkpoint 허용 Phase |
| PublishPlan | PLANNING → WAITING_APPROVAL 또는 EXECUTING |
| CompleteAnswerOnlyRun | ANALYZING·RETRIEVING·PLANNING → COMPLETED |
| RequestCancel | 비Terminal → CANCEL_REQUESTED |
| FinalizeCancel | CANCEL_REQUESTED → CANCELLED |
| RequireReauth | Stage 10 P0: RETRIEVING → REAUTH_REQUIRED |
| ResumeAfterReauth | REAUTH_REQUIRED → Checkpoint 허용 Phase |
| RequireRecovery | 비Terminal → RECOVERY_REQUIRED |
| ResolveRecovery | RECOVERY_REQUIRED → VERIFYING·FAILED·CANCELLED |

## Action·Approval·Attempt Command

| Command | 허용 전이 |
|---|---|
| ApproveAction | PROPOSED·MODIFIED → APPROVED |
| ModifyAction | PROPOSED·APPROVED·EXPIRED·FAILED → MODIFIED |
| RejectAction | PROPOSED·MODIFIED → REJECTED |
| ExpireApproval | APPROVED → EXPIRED |
| ClaimReadAction | READ PROPOSED → EXECUTING |
| CompleteReadAction | READ EXECUTING → EXECUTED |
| FinalizeReadAction | READ EXECUTED → VERIFIED |
| FailReadAction | READ EXECUTING → FAILED |
| ClaimExecution | WRITE APPROVED → EXECUTING + Approval CONSUMED + Attempt CLAIMED |
| StoreSuccess | EXECUTING → EXECUTED + Attempt SUCCEEDED |
| MarkFailed | EXECUTING → FAILED + Attempt FAILED |
| MarkUnknownResult | EXECUTING → UNKNOWN_RESULT + Attempt UNKNOWN_RESULT |
| RecoverExistingResult | UNKNOWN_RESULT → EXECUTED |
| ResolveAsFailed | UNKNOWN_RESULT → FAILED, 기존 결과 미실행 확정 필요 |
| StoreVerification | EXECUTED → VERIFIED·MISMATCH |
| PrepareWriteRetry | FAILED → MODIFIED |

## 금지

- `EXPIRED → APPROVED` 직접 전이
- `FAILED → EXECUTING` 직접 전이
- `UNKNOWN_RESULT → EXECUTING`과 새 Attempt
- READ Approval·ExecutionAttempt·Verification Row
- Version 없는 Mutable UPDATE
- 외부 호출 중 SQLite Transaction
- LangGraph Node·FastAPI Route의 SQL 직접 실행
- Claim Commit 전 MCP Write
- Claim Token 재사용
