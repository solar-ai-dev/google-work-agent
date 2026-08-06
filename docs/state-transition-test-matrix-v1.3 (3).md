# 상태 전이 테스트 매트릭스 v1.3

## Command Receipt

- `TST-DB-101`: Receipt·Domain·Audit 원자 Commit
- `TST-API-101`: 같은 ID·같은 Hash 기존 결과
- `TST-API-102`: 같은 ID·다른 Hash 차단
- `TST-E2E-101`: 응답 유실·재시작 후 Run·Approval·Attempt 중복 0

## Run

- CREATED→ANALYZING→RETRIEVING→PLANNING 정상 경로
- WAITING_CONFIRMATION Checkpoint 저장·같은 Thread 재개
- Answer-only Plan·Action 없이 COMPLETED
- CANCEL_REQUESTED→CANCELLED
- 일부 Action 성공 취소 시 Domain CANCELLED·Projection PARTIAL
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
- Write 후 GET Verification
- MISMATCH 자동 수정 금지

## Retry·Recovery

- FAILED→EXECUTING 직접 차단
- FAILED→MODIFIED→새 Approval→새 Attempt 허용
- 기존 Approval·Idempotency Key 재사용 차단
- UNKNOWN_RESULT에서 새 Attempt·Write 차단
- CREATE Search·UPDATE GET Target

## Agent·Interface

- Agent·Context Retriever MCP 직접 호출 0
- Node Registry 외 Edge 0
- `/health/*`와 Bootstrap 인증 예외 Matrix
- 일반 `/api/v1/*` Session 필수
- OAuth Token 원문 FastAPI·DB·Log 미노출
