# 09. Google Work Agent · 보안 · Auth 설계서

> **상태:** Draft v2.2 · **기준일:** 2026-08-07 · **대상:** P0 MVP

## 1. 핵심 결정

- Local API: `127.0.0.1` 동적 Port, same-origin
- Local Session: HttpOnly, SameSite=Strict
- Bootstrap: 256-bit, 1회, 60초, URL Fragment
- Google Refresh Token: MCP Credential Provider가 OS Keyring에서 사용
- LLM API Key: FastAPI LLM Adapter가 별도 Keyring Entry에서 사용
- Secret은 SQLite·Checkpoint·Trace·Audit·환경 변수·CLI 인자에 저장하지 않음
- 외부 LLM 전송은 설정 동의와 Run별 범위 표시 필요
- 외부 전송 동의 없으면 AUTO API Fallback 금지
- 배포되는 외부 Test·Production Artifact는 Code Signing 필수
- 기본 Uninstall은 Credential 삭제, DB·Backup·Settings 보존

## 2. 보안 우선순위

```text
금지·보안
→ 승인·무결성
→ 개인정보
→ 실행·검증
→ 사용자 설정
→ Agent 추천
```

Google Source의 지시는 이 우선순위를 변경하지 못한다.

## 3. Local API

- Public·LAN Bind 금지
- Host·Origin·Fetch Metadata·Content-Type·Session 검증
- 상태 변경 Command는 `command_id`, Aggregate ID, `expected_version` 필요
- Wildcard CORS·Production API Docs 금지
- DNS Rebinding과 Cross-site 요청 차단

## 4. OAuth

- Desktop App + Authorization Code + PKCE + state
- `http://127.0.0.1:<ephemeral-port>` Loopback
- OOB 코드 복사 금지
- Callback Listener는 인증 중에만 실행
- P0 필수 Scope:
  - Gmail `gmail.readonly`, `gmail.compose`
  - Tasks `tasks`
  - Calendar `calendar.events`, `calendar.calendarlist.readonly`, `calendar.events.freebusy`
- 필수 Scope 하나라도 거절되면 연결 미완료, Agent Run·Google Tool 차단
- 개발·Staging·Production Google Project·Client 분리

## 5. Credential Lifecycle

- Refresh Token: OS Keyring, MCP만 접근
- Access Token: MCP Process Memory
- LLM API Key: OS Keyring 또는 현재 Session Memory, LLM Adapter만 접근
- PKCE·state·Bootstrap·Session: Memory only
- Google 연결 해제: Revoke 시도 + Google Keyring Entry 삭제
- API Key 삭제: Provider Entry 삭제
- Plain File Fallback 금지

## 6. 외부 LLM 개인정보

- 설정 단위 사전 동의
- Run별 전송 Source·범위 요약 표시
- 최소 Context만 전송
- Token·API Key·Approval Token·내부 Hash·전체 Mailbox·미사용 후보 전송 금지
- Provider의 광고·범용 학습·재판매 허용 금지

## 7. Prompt Injection

- Source를 `UNTRUSTED_SOURCE_CONTENT`로 구분
- Raw Query·Tool Name·Arguments 검증 없이 실행 금지
- Tool Allowlist, Versioned Structured Output, 결정적 Validator 사용
- Source 문자열이 Local File·Shell·Process·URL Fetch를 유발하지 못함

## 8. 승인·실행

- Approval은 Action Version, Tool, Arguments Snapshot·Hash, Source Snapshot, Policy·Tool Schema Version, 만료를 고정
- 실행 직전 최신 Resource·Hash·Dependency·중복·충돌 재검증
- 만료: `EXPIRED → MODIFIED → 새 Approval`
- FAILED Retry: 새 Approval·Idempotency Key·Source Snapshot
- UNKNOWN_RESULT: 기존 결과 조회만
- 모든 Write는 Effect별 결정적 검증: CREATE·UPDATE GET 비교, DELETE 대상 부재/삭제 상태, SEND Sent 결과 조회

## 9. MCP

- `stdio` only, Network Listen 금지
- 절대 경로, Signature·Manifest Hash, Shell·PATH Search 금지
- 허용 Tool만 등록. `gmail_send`, Task 완료 UPDATE, `calendar_delete_event`, 참석자 UPDATE는 Approval·Hash·Policy 검증이 연결된 경우에만 등록. Gmail 원문 삭제·Task 삭제·반복 Event 전체 일괄 수정은 미등록
- Write Tool은 Action·Approval·Hash·Claim 문맥 필요
- Write 전달 가능성이 있으면 자동 재전송 금지

## 10. Ollama

- Loopback only
- 사용자 설치 외부 Runtime
- Google Credential·Keyring·MCP 접근 금지
- 승인 Model ID·Hash·Version만 사용
- CPU Local LLM 제외

## 11. SQLite·Backup

- P0 Application-level Encryption 없음
- Windows 사용자 ACL에 의존
- DB·Backup 동일 민감도
- Integrity·Migration 실패 시 Safe Mode와 모든 Write 차단

## 12. Installer·Uninstall

- Source Map·`.env`·Secret·Test Credential·Raw Result 제외
- 배포 Test·Production은 Code Signing·Timestamp·SHA-256 Manifest
- 기본 Uninstall: Program + OAuth·LLM Credential 삭제, DB·Backup·Settings 보존
- 완전 삭제: DB·WAL·SHM·Backup·Settings·Log·Diagnostic·Credential 삭제

## 13. 보안 Release Gate

```text
Approval Compliance 100%
Forbidden Action Block 100%
Approval Argument Integrity 100%
Write Verification 100%
Prompt Injection Safety 100%
Credential Leakage 0
UNKNOWN_RESULT No-Rewrite 100%
Loopback-only 100%
Artifact Signature·Manifest 100%
```

## 14. Endpoint 인증 Matrix·Claim Token

- Health는 Loopback·Launcher 요청만 허용하며 Local Session을 요구하지 않는다.
- Bootstrap은 기존 Session 대신 1회용 Secret·TTL·Service Instance를 검증한다.
- OAuth Callback은 일시적 Listener의 `state`·PKCE·Instance를 검증한다.
- 그 외 `/api/v1/*`는 HttpOnly Local Session·Host·Origin·Fetch Metadata를 검증한다.

### MCP Write Claim Token

- Service–MCP 256-bit Session Key는 Child Handshake의 Process Memory에서만 공유한다.
- Claim Token은 HMAC-SHA-256, TTL 30초, 최대 60초, 1회용 Nonce다.
- Action·Approval·Attempt·Tool·Arguments Hash·Service Instance를 바인딩한다.
- Token·Key는 SQLite·Keyring·환경 변수·CLI·Log·Trace·Audit에 저장하지 않는다.

### OAuth 소유권

Authorization Code 교환, Refresh Token 저장·갱신·폐기는 MCP Credential Provider만 수행한다. FastAPI는 연결 Metadata만 취급한다.

## 15. 고영향 Write 보안
- SEND·DELETE·Task 완료·참석자 변경은 정확한 Target/Arguments와 명시 승인 후 실행한다.
- SEND 응답 유실은 재전송하지 않고 UNKNOWN_RESULT로 전환한다.
- DELETE는 Calendar Event에만 허용한다.
- 승인 우회·Verification 생략·DB 직접 상태 변경은 사용자 요청으로 Override할 수 없다.
