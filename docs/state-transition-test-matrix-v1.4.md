# 상태 전이 테스트 매트릭스 v1.4

## Command Receipt·API Trust Boundary

- RejectAction same-command replay는 Action·Approval·Dependency·Audit을 추가 변경하지 않는다.
- RejectAction hash/version conflict는 child mutation과 `ACTION_REJECTED` Audit이 0이다.
- Reject upstream의 미실행 transitive dependent는 `DEPENDENCY_BLOCKED`, ACTIVE Approval은 `REVOKED`이며 terminal Action은 보존한다.

- `TST-DB-101`: Receipt·Domain·Audit 원자 Commit
- `TST-API-101`: 같은 ID·같은 서버 계산 Canonical Hash → 기존 결과
- `TST-API-102`: 같은 ID·다른 Hash → 409, Domain 변경 0
- Browser 제공 request_hash·approval_id·idempotency_key·source_snapshot·actor identity를 authority로 사용하지 않음
- `TST-E2E-101`: 응답 유실·재시작 후 Run·Approval·Attempt 중복 0

## Run·Cancel

- CREATED→ANALYZING→RETRIEVING→PLANNING 정상 경로
- WAITING_CONFIRMATION Checkpoint 저장·같은 Thread 재개
- Answer-only Plan·Action 없이 COMPLETED
- RequestCancel: 모든 비Terminal → CANCEL_REQUESTED
- Cancel Version Conflict/다른 Hash Replay → Approval·Plan·Action 변경 0
- CANCEL_REQUESTED 이후 새 Claim·Write 0
- 미실행 Action `PROPOSED|MODIFIED|APPROVED|EXPIRED → CANCELLED`
- APPROVED 취소 시 ACTIVE Approval REVOKED, Attempt·Verification 생성 0
- EXECUTING 취소는 결과 확정 전 상태 보존
- EXECUTED 취소는 Verification 선행
- UNKNOWN_RESULT 취소는 RECOVERY_REQUIRED, blind resend 0
- 일부 Action 성공 취소 시 Domain CANCELLED·Projection PARTIAL·rollback 0
- REAUTH_REQUIRED·RECOVERY_REQUIRED 안전 재개
- Conversation당 Open Run 1개

## READ-only

- 승인 없이 Plan ACTIVE
- READ Claim 경쟁 하나만 성공
- Approval·Attempt·Verification Row 0
- Output Schema 실패 EXECUTING→FAILED

## WRITE

- 승인 Snapshot·Hash·Source Snapshot
- Claim Transaction 성공 전 MCP Write 0
- 유효 Claim Token 1회만 Write
- Token 재사용·만료·Action·Hash 불일치 차단
- Write 후 Effect별 결정적 Verification (CREATE·UPDATE GET, DELETE 대상 부재/삭제 상태, SEND Sent 결과 조회)
- MISMATCH 자동 수정·rollback 0

## Retry·Delivery·Recovery

- FAILED→EXECUTING 직접 차단
- FAILED→MODIFIED→새 Approval→새 Attempt 허용
- 기존 Approval·Idempotency Key 재사용 차단
- UNKNOWN_RESULT에서 새 Attempt·Write 차단
- `NOT_SENT` 확정 실패만 FAILED 가능
- dispatch 이후 Timeout → UNKNOWN_RESULT
- 미전달 보장 없는 5xx → UNKNOWN_RESULT
- response loss → SENT_RESPONSE_LOST → UNKNOWN_RESULT
- MCP exit/transport failure에서 dispatch 여부 불명 → UNKNOWN_RESULT
- CREATE Resource Search · UPDATE GET Target · SEND Message/Sent Search · DELETE GET Target/부재 확인

## Verification MISMATCH

- StoreVerification MISMATCH → Action MISMATCH + Run RECOVERY_REQUIRED
- 기존 Verification append-only 보존
- ACCEPT_PARTIAL → 새 Write 0, 미실행 Action CANCELLED, Run COMPLETED + PARTIAL
- CREATE_CORRECTIVE_PLAN → Run PLANNING, 새 Plan Revision
- Corrective Write → 새 Approval·Claim·Attempt·Verification
- 기존 MISMATCH Action/Approval/Attempt 재사용 0

## Insufficient Data Guard

- safety-critical/POLICY required issue → BLOCKED
- USER required issue → NEEDS_CONFIRMATION
- GOOGLE required issue + budget → RETRIEVE_MORE
- budget exhausted + evidence-supported Read-only → PARTIAL
- Write 필수 정보 부족은 PARTIAL 금지
- SINGLE/THREE/SIX 동일 semantic guard

## Agent·Interface

- Agent·Context Retriever MCP 직접 호출 0
- Node Registry 외 Edge 0
- `/health/*`와 Bootstrap 인증 예외 Matrix
- 일반 `/api/v1/*` Session 필수
- typed confirm/cancel/resume/prepare-retry/resolve-recovery schema
- arbitrary resume payload 차단
- OAuth Token 원문 FastAPI·DB·Log 미노출

## Claim V2 추가 Contract Test 경계

기존 `ClaimExecution` 테스트의 “Claim Commit before MCP write”, “claim single-use”, “Action/Approval/Hash mismatch 차단” 의미는 유지한다. Signature·TTL·Process Instance·`execution_arguments_hash`·Nonce·MCP 실제 인자 재해시의 세부 Contract Test는 `12 Test v3.5`에서 추가 검증한다.
