# 14. Google Work Agent · 예외 처리 · 운영 · 트러블슈팅 가이드

> **상태:** Draft v2.2 · **원격 운영 서버:** 없음

## 1. Severity

| 등급 | 기준 | 조치 |
|---|---|---|
| SEV-0 | 보안·무결성·DB 손상·변조 | Write 차단·Safe Mode |
| SEV-1 | UNKNOWN_RESULT·MISMATCH·Recovery | 새 Write 금지·결과 조회 |
| SEV-2 | Google·MCP·LLM·Keyring 장애 | 제한 Retry·Reauth·대체 Runtime |
| SEV-3 | Browser·SSE·표시 | 재연결·Snapshot |

## 2. Triage

```text
오류 감지
→ 신규 Write 차단 여부
→ Domain Run·Action 상태
→ Write 전달 가능성
→ Component Health
→ 제한된 자동 복구
→ Snapshot 복원
→ Diagnostic·Escalation
```

## 3. 자동 복구

- SSE: 재연결·Snapshot, Action 재실행 금지
- MCP Read 전 종료: 1회 Restart·Schema
- Google Read 429·5xx: 제한 Backoff
- LLM: Retry 1·AUTO Fallback 1
- Structured Output: Repair 1
- Write 전달 전 확정 실패: FAILED, 자동 재실행 없음
- 응답 유실: UNKNOWN_RESULT·GET/Search
- SQLite Busy: 5초 후 실패
- Migration: Safe Mode, 자동 재시도 없음

## 4. 금지 안내

DB 직접 편집·상태 SQL 변경·MCP 수동 Write·Wildcard CORS·Public Bind·Token 공유·미서명 Binary 교체·Downgrade Open·UNKNOWN_RESULT 재승인·Backup 없는 데이터 삭제를 안내하지 않는다.

## 5. Startup·Browser

- 기존 Ready Instance가 있으면 기존 UI 열기
- Port는 다른 127.0.0.1 동적 Port만
- Core Readiness: Manifest → ACL → SQLite·Migration·Domain → Keyring Adapter 접근 → MCP Executable·Tool Schema → Assets·API Contract. Google Credential·API Key·Ollama·Model은 `/api/v1/runtime` 진단이며 누락 자체가 Service 시작 실패는 아니다.
- Chrome·Edge 실패 시 Service 유지 가능
- 오래된 Session은 새 Bootstrap으로 교체
- SSE 단절은 Agent 실패가 아님

## 6. OAuth·Keyring

- 필수 Scope 일부 거절: 연결 미완료, Agent Run·Google Tool 차단
- Token Refresh 실패: Checkpoint → REAUTH_REQUIRED → 재로그인 → Source·Version 재검증 → 필요 시 재승인
- Keyring 실패: Plain File Fallback 금지

## 7. Runtime

API_ONLY: Ollama 없음 정상. API Key 없으면 진단·설정만.
LOCAL_CAPABLE: Loopback Ollama·Version·Model·GPU·Smoke·OOM 확인. 제품은 Ollama를 설치·관리하지 않는다.
LOCAL_GPU는 자동 API 전환 금지.

## 8. LLM·Retrieval

- 429·5xx만 제한 Retry
- Schema 실패 Repair 1회
- 추가 수집 2회
- 필수 Source 실패 시 Write Context 충족 금지
- 범위 확대 전 사용자 확인
- Prompt Injection은 POLICY_BLOCKED

## 9. MCP·Google

MCP 검증: Absolute Path → Signature·Hash → Version → Tool Schema → Registry → stdio.
Write 도중 MCP 종료 시 같은 Write 재전송 금지.

Google Write:
```text
미전달 확실 → FAILED
전달 가능성 → UNKNOWN_RESULT
```

## 10. Approval

- APPROVAL_INVALID: Version·Hash·Snapshot·Status·Expiry
- EXPIRED: 최신 Source → MODIFIED → 새 Approval
- Policy Block은 Retry하지 않음

## 11. FAILED

```text
FAILED
→ 원인·최신 Source
→ prepare_write_retry
→ MODIFIED
→ Policy·중복·충돌
→ 새 Approval
→ 새 Attempt
```

기존 Approval·Idempotency Key 재사용 금지.

## 12. UNKNOWN_RESULT

```text
CREATE → Recovery Fingerprint Search
UPDATE → Target GET
확인 → 기존 Attempt EXECUTED → Verification
불명 → RECOVERY_REQUIRED
```

찾지 못해도 즉시 재실행하지 않는다.

## 13. MISMATCH

정규화 가능한 차이만 VERIFIED. 실제 차이는 Expected·Actual·Diff 저장, 자동 Rollback 금지, Recovery Write는 새 Approval.

## 14. SQLite·Migration

확인: Disk → ACL → DB·WAL·SHM → quick_check → Migration → Open Run → Checkpoint.
Domain·Checkpoint 충돌 시 Domain 사실 우선, RECOVERY_REQUIRED.
Integrity·Migration 실패 시 Safe Mode, 자동 DB 초기화 금지.

## 15. Safe Mode

허용: Health, Diagnostic, Backup, Restore, Log, Settings, Shutdown
금지: 새 Run, 승인, Google Write, MCP Write, Migration 반복, DB 초기화

## 16. Backup·Restore

Restore:
```text
앱 종료
→ 현재 DB Backup
→ Manifest·Hash·quick_check·Schema
→ 교체
→ Migration
→ Domain·Checkpoint
→ Restart
```

실패 시 원본과 대상 모두 보존.

## 17. Shutdown·Crash

```text
신규 Command 차단
→ Write 결과 또는 UNKNOWN_RESULT
→ Checkpoint Flush
→ WAL Checkpoint·Close
→ MCP·FastAPI 종료
→ Lock 제거
```

다음 시작에서 Marker·Open Run·EXECUTING·UNKNOWN_RESULT·MISMATCH·Integrity를 검사한다.

## 18. Installer·Uninstall

Repair는 Program File만 복구하고 DB·Backup·Settings 보존.
기본 Uninstall은 OAuth·LLM Credential 삭제, DB·Backup·Settings 보존.
완전 삭제는 모든 사용자 데이터·Log·Diagnostic까지 삭제.

## 19. Security Incident

미승인 Write·Hash 불일치·Secret Leak·Signature 실패·Public Bind·금지 Tool·Credential 오용 의심:

```text
Write 차단
→ Run·Action·Audit 보존
→ Credential 폐기·재발급
→ Build·Manifest 검증
→ Diagnostic
→ Regression Test
→ Release Gate 재검증
```

## 20. 해결 완료

Domain 상태가 허용 Terminal·Recovery이고, Write 결과가 확정되며, 차단 상태가 해소되고, Audit·Trace·사용자 결과가 남아야 한다. 재현 결함은 12 Regression, 모델·Prompt 문제는 13 Failure Taxonomy에 반영한다.

## 21. Command Receipt·Claim Token Runbook

### 중복 Command

- 같은 `command_id`·같은 Hash면 기존 결과를 표시한다.
- 같은 ID·다른 Hash면 Security·Integrity 오류로 Write를 차단한다.
- `RECEIVED` Receipt가 남아 있으면 Aggregate 상태와 Audit을 조회하고 Command를 무조건 반복하지 않는다.

### Claim Token 오류

- 재사용·만료·Binding 불일치는 Google Write 전 차단한다.
- Service 또는 MCP 재시작 후 이전 Token을 재사용하지 않는다.
- Claim Token 오류를 해결하기 위해 Approval을 임의 재활성화하지 않는다.

### OAuth 재인증

- FastAPI Log·Diagnostic에서 Authorization Code·Token 원문을 찾거나 요청하지 않는다.
- MCP Credential Provider의 연결 Metadata와 Keyring Entry 존재 여부만 진단한다.

### 취소 부분 결과

Domain Status는 `CANCELLED`, UI 결과는 `result_kind=PARTIAL`로 표시한다. 성공 Action을 롤백하거나 다시 실행하지 않는다.

## 2026-08-07 v2.2 구현 정합성 진단
- External Adapter 호출 중 SQLite Write Transaction이 열려 있으면 무결성/동시성 결함으로 분류한다.
- 외부 호출 후 저장 Transaction에서 `expected_version`, Action 상태, Attempt 상태를 재검사한다.
- Recovery 상태 변경은 `RequireRecovery`·`ResolveRecovery` Domain Command를 사용한다. Repository 직접 setter는 구현 결함이다.
- 이 수정은 Domain 모델·Command Receipt·Recovery 알고리즘 전면 재설계가 아니라 Application Transaction 경계와 누락된 Domain Command 연결의 정합성 수정이다.
