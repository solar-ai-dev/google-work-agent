# 상태 전이 테스트 매트릭스 v1.5

> **현재 권위 정합:** `04 Domain·DB v1.21 / DB Schema v1.9`, `06 Workflow v7.22`, `07 Interface v2.23`, `12 Test v3.41`을 따른다. Startup migration discovery는 `google_work_agent.adapters.persistence.migrations` package의 executable `0001~0008`을 version-sort하여 적용한다. `docs/database/migrations/**`는 executable authority가 아니다.

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
- `BeginPlanning: ANALYZING | RETRIEVING → PLANNING`.
- 이미 target 상태인 Retrieval local loop/Planning revision에서 동일 Command 반복 0.
- Request `COMPLETE → Tool Route` Edge 누락 0.
- `NO_FETCH_NEEDED`는 SUFFICIENT와 같은 analysis guard.
- `NEEDS_MORE_DATA + budget`은 bounded local loop; budget 소진 후 `NEEDS_CONFIRMATION | PARTIAL | BLOCKED` 정규화.

## Confirmation

- `RequestConfirmation` 적용 후에만 WAITING_CONFIRMATION interrupt 생성.
- `owner_subgraph + RegisteredResumeTargetRefV1 + interrupt_id` checkpoint 보존.
- 사용자 응답 검증 후 `ResumeConfirmation`으로 발생 전 안전 상태 복원.
- same owner checkpoint resume.
- upstream 의미 변경이 없는 Confirmation에서 Request Understanding 공통 재시작 0.

## BlockRun

- Claim 전 상태 + Active/Unknown/미검증 Write Attempt 없음일 때만 허용.
- Plan 존재 시 같은 UoW 순서: 미실행 Action `BLOCKED/DEPENDENCY_BLOCKED` → ACTIVE Approval `REVOKED` → Plan `CANCELLED` → Run `BLOCKED`.
- `0005_cross_aggregate_invariants.sql` Trigger와 충돌 없이 Commit.
- in-flight Write를 Policy BLOCKED로 덮어쓰기 0.

## WRITE 정상·다중 Action

- PublishPlan → Run WAITING_APPROVAL.
- ClaimExecution은 Action APPROVED→EXECUTING + Approval CONSUMED + Attempt CLAIMED 원자 Commit.
- Action 실행 중 Run은 기본 WAITING_APPROVAL 유지.
- `EXECUTED` 후 첫 검증에서 `BeginVerification: WAITING_APPROVAL → VERIFYING` 정확히 1회.
- 다중 Action에서 Run이 이미 VERIFYING이면 BeginVerification 재호출 0.
- dependent Action은 predecessor `VERIFIED` 이후에만 Claim.
- 모든 승인 Action terminal + unresolved 0 + cancel intent false → `CompleteWriteRun: VERIFYING → COMPLETED`, Plan COMPLETED.
- Claim Commit 전 MCP Write 0.
- 유효 Claim Token single-use, Action/Approval/Business Hash/Execution Hash/Nonce 검증.
- Write 후 Effect별 결정적 Verification.

## FAILED·Retry

- `FAILED → EXECUTING` 직접 차단.
- `FAILED + NOT_SENT`는 자동 FINALIZE하지 않고 retry/cancel 대기.
- `PrepareWriteRetry: FAILED → MODIFIED`.
- `MODIFIED → Review → Domain Validation → 새 Approval → 새 Attempt`.
- 기존 Approval·Idempotency Key·Attempt 재사용 0.

## UNKNOWN_RESULT·Recovery

- UNKNOWN_RESULT에서 새 Attempt·Write 0.
- CREATE search / UPDATE target GET / SEND Sent lookup / DELETE target/absent lookup.
- 기존 결과 recovered → EXECUTED → Verification.
- Recovery에서 재검증 필요할 때만 VERIFYING 복귀.
- `ResolveRecovery(FAIL)`은 FAILED→FINALIZE 단일 경로.
- `ResolveRecovery(ACCEPT_PARTIAL)`은 cancel intent false에서만 COMPLETED+PARTIAL.
- `CREATE_CORRECTIVE_PLAN`은 cancel intent false에서만 PLANNING + 새 Plan Revision.
- 기존 MISMATCH Action/Approval/Attempt/Verification 재사용 0.

## Cancel

- RequestCancel Version Conflict/다른 Hash Replay → Approval·Plan·Action 변경 0.
- APPLIED RequestCancel Receipt에서 durable cancel intent 복원.
- cancel intent 활성 이후 신규 Claim·Write 0.
- 미실행 Action → CANCELLED, ACTIVE Approval REVOKED, Attempt·Verification 생성 0.
- in-flight Action을 취소 요청만으로 CANCELLED로 덮어쓰기 0.
- 결과를 `EXECUTED | UNKNOWN_RESULT | FAILED`로 먼저 확정.
- EXECUTED → `CANCEL_REQUESTED → BeginVerification → VERIFYING` + Verification 후 FinalizeCancel.
- UNKNOWN_RESULT → RECOVERY_REQUIRED; 결과 terminal snapshot이면 ResolveRecovery(CANCEL), recheck면 VERIFYING 후 FinalizeCancel.
- Reauth 중에도 cancel intent 유지.
- cancel intent 활성인데 CompleteWriteRun→COMPLETED로 종료 0.
- 성공 Write rollback 0; 일부 성공 취소는 Domain CANCELLED + Projection PARTIAL 가능.

## Reauth

- `RequireReauth`는 Retrieval/Planning/Approval/Execution/Verification/Recovery 안전 checkpoint를 보존.
- ResumeAfterReauth는 저장된 안전 phase로 복귀.
- 이미 dispatch된 Write 재전송 0.
- Checkpoint 유실 → RECOVERY_REQUIRED.
- cancel intent는 Reauth를 통과해 유지.

## Retrieval·Answer-only Terminalization

- `Retrieval.PARTIAL + usable Evidence 없음`이 비Terminal Run에서 직접 FINALIZE로 가지 않음.
- 처리 불가 안내를 저장하는 `CompleteAnswerOnlyRun → COMPLETED`가 먼저 적용됨.
- Answer-only Run은 Plan·Action 없이 Message·Trace·Run Terminal 원자 저장.

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
- Browse/Count/Detail/Retrieval/Write/Verification/Recovery 조회는 Connector Registry + MCP 경계 통과.
- Connector MCP unavailable/Schema invalid 때 Core direct Provider fallback 0.

## Insufficient Data Guard

- safety-critical/POLICY required issue → BLOCKED.
- USER required issue → NEEDS_CONFIRMATION.
- external-source required issue + budget → RETRIEVE_MORE.
- budget exhausted + usable Evidence → PARTIAL.
- budget exhausted + usable Evidence 없음 → CompleteAnswerOnlyRun.
- Write 필수 정보 부족은 PARTIAL로 실행 진행 금지.
- SINGLE/THREE/SIX 동일 semantic guard.

## Claim V2 추가 Contract Test 경계

기존 `ClaimExecution`의 “Claim Commit before MCP write”, “claim single-use”, “Action/Approval/Hash mismatch 차단” 의미를 유지한다. Signature·TTL·Process Instance·`execution_arguments_hash`·Nonce·MCP 실제 인자 재해시는 `12 Test v3.41`에서 추가 검증한다.

## DB Migration·Connector Identity Regression

- `0006_plan_aggregate_invariants.sql`: cross-run/conversation/plan aggregate invariant를 검증한다.
- `0007_connector_neutral_persistence.sql`: Action/ResourceRef `connector_id` backfill·persistence identity를 검증한다.
- `0008_resource_ref_connector_identity.sql`: `(run_id, connector_id, resource_type, resource_id)` ResourceRef uniqueness 단일 권위를 검증한다.
- Startup discovery는 executable `0001~0008` 전체를 적용하고 checksum mismatch를 fail-close한다.
- 적용된 executable migration `0001~0008`은 regression repair를 위해 소급 수정하지 않는다.
