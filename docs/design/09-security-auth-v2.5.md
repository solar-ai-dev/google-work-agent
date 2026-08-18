# 09. Google Work Agent · 보안 · Auth 설계서

> **2026-08-19 Canonical Sync — Prompt/LLM 전송 범위**
>
> 외부 LLM 전송은 현재 Run의 allowlisted Typed Projection으로 제한한다. 같은 Conversation의 과거 Message 전체나 이전 Run의 Agent Artifact·Evidence·Plan·Confirmation/Approval Snapshot·Checkpoint를 새 Run Prompt에 자동 전송하지 않는다. 과거 Resource를 사용자가 이번 Run에 명시적으로 다시 선택해도 현재 Run에 필요한 최소 Resource/Evidence만 새로 조회·Projection한다.

> **상태:** Draft v2.11 · **기준일:** 2026-08-19 · **대상:** P0 MVP

## 1. 핵심 결정

- Local API: `127.0.0.1` 동적 Port, same-origin
- Local Session: HttpOnly, SameSite=Strict
- Bootstrap: 256-bit, 1회, 60초, URL Fragment
- Google Refresh Token: MCP Credential Provider가 OS Keyring에서 사용
- Gmail·Tasks·Calendar Provider API/SDK 호출 권한은 Google Work MCP Server 내부 Adapter만 소유한다. React·FastAPI Route·Application·LangGraph·Agent·Domain은 MCP Client/Tool 계약만 사용하고 Provider API를 직접 호출하지 않는다.
- LLM API Key: FastAPI LLM Adapter가 별도 Keyring Entry에서 사용
- 사용자 Credential·OAuth Token·LLM API Key 등 Confidential Secret은 SQLite·Checkpoint·Trace·Audit·환경 변수·CLI 인자에 저장하지 않음
- 예외: DEV Desktop OAuth Client가 실제 Google Token Endpoint 호환을 위해 `client_secret`을 요구하는 경우, 해당 값은 사용자 Credential 또는 Confidential Security Boundary가 아닌 **Google OAuth Protocol Compatibility Client Credential**로 취급하며 repo-root `.env.local`에서 MCP Credential Provider만 읽을 수 있음
- 외부 LLM 전송은 설정 동의와 Run별 범위 표시 필요
- 외부 전송 동의 없으면 AUTO API Fallback 금지
- 배포되는 외부 Test·Production Artifact는 Code Signing 필수
- 기본 Uninstall은 Credential 삭제, DB·Backup·Settings 보존

## 1.1 Google Workspace 신뢰 경계

```text
사용자
→ React Frontend
→ FastAPI Local Agent Service
→ Application · LangGraph · Domain Policy
→ MCP Client
→ Connector MCP Server · stdio
→ Provider APIs  # 각 Connector MCP Server 내부 Adapter에서만 접근

P0: google_workspace → Google Workspace MCP Server → Gmail·Tasks·Calendar APIs
```

- Local API는 React와 FastAPI 사이의 제품 내부 REST/SSE 계약이며 Google Provider API 우회 경로가 아니다.
- Sidebar Browse/Count/Detail, Retrieval Read, OAuth 상태, Write, Verification, Recovery 조회는 모두 MCP Client/Tool 경계를 통과한다.
- MCP unavailable·Tool Schema invalid 상황에서도 제품 Core가 Google Provider Client를 직접 구성하거나 Provider API로 fallback하지 않는다.
- Provider raw continuation/token/response 해석과 OAuth Access Token 적용은 MCP 내부 Adapter/Credential Provider 책임이다.

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
- Browser는 `request_hash`, `approval_id`, idempotency key, source snapshot, actor identity, canonical arguments hash, claim token을 권위 값으로 지정하지 못한다. 해당 값은 Application·Domain이 생성·검증한다.
- Wildcard CORS·Production API Docs 금지
- DNS Rebinding과 Cross-site 요청 차단
- FastAPI Route·Application·LangGraph·Agent·Domain의 Gmail·Tasks·Calendar Provider API/SDK 직접 호출·직접 Provider Client 구성 금지

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
- Desktop OAuth Client가 `client_secret`을 발급하고 실제 Token Endpoint가 이를 요구하는 경우, `client_secret`은 PKCE·`state`·loopback을 대체하는 보안 수단이 아니다.
- DEV에서는 MCP Credential Provider만 `GOOGLE_OAUTH_CLIENT_SECRET`을 읽고 authorization-code grant와 refresh-token grant의 protocol compatibility field로 사용할 수 있다.
- `client_secret`은 React/Vite, FastAPI API payload, SQLite, Log, Trace, Diagnostic, OS Keyring으로 전달·저장하지 않는다.
- Production에서는 `.env.local`, 일반 환경 변수, CLI를 통한 provisioning을 금지하며 배포 Credential provisioning 계약을 별도로 따른다.

## 5. Credential Lifecycle

- Refresh Token: OS Keyring, MCP만 접근
- Access Token: MCP Process Memory
- LLM API Key: OS Keyring 또는 현재 Session Memory, LLM Adapter만 접근
- PKCE·state·Bootstrap·Session: Memory only
- Google 연결 해제: Revoke 시도 + Google Keyring Entry 삭제
- API Key 삭제: Provider Entry 삭제
- Plain File Fallback 금지
- Desktop OAuth `client_secret`은 Refresh Token·Access Token과 같은 사용자 Credential Lifecycle에 포함하지 않는다. DEV compatibility credential은 MCP 설정 경계에서만 사용한다.

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
- Google Workspace 외부 접근의 유일한 제품 경계다. 실제 Gmail·Tasks·Calendar Provider API/SDK 호출과 raw Provider 응답 해석은 MCP Server 내부 Adapter에서만 수행한다.
- MCP 장애 시 Core의 직접 Google Provider API fallback을 금지한다.
- 절대 경로, Signature·Manifest Hash, Shell·PATH Search 금지
- 허용 Tool만 등록. `gmail_send`, Task 완료 UPDATE, `tasks_delete_task`, `calendar_delete_event`, 참석자 UPDATE는 Approval·Hash·Policy 검증이 연결된 경우에만 등록. Gmail 원문 삭제·반복 Event 전체 일괄 수정은 미등록
- Write Tool은 Action·Approval·Hash·Claim 문맥 필요
- Write 전달 가능성이 있으면 자동 재전송 금지
- Write Adapter는 `NOT_SENT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST`를 보존하며 `NOT_SENT`만 FAILED 후보로 인정한다.

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

Authorization Code 교환, Refresh Token 저장·갱신·폐기는 MCP Credential Provider만 수행한다. Desktop OAuth Client가 protocol compatibility를 위해 `client_secret`을 요구하는 경우 해당 값의 로드·사용도 MCP Credential Provider가 소유한다. FastAPI와 React는 연결 Metadata만 취급하며 Client Secret 원문을 전달받지 않는다.

## 15. 고영향 Write 보안
- SEND·Google Task DELETE·Calendar Event DELETE·Task 완료·참석자 변경은 정확한 Target/Arguments와 명시 승인 후 실행한다.
- SEND 응답 유실은 재전송하지 않고 UNKNOWN_RESULT로 전환한다.
- DELETE는 정확한 Target·Arguments와 사용자 승인을 전제로 Google Task와 Calendar Event에 허용한다.
- 승인 우회·Verification 생략·DB 직접 상태 변경은 사용자 요청으로 Override할 수 없다.
- FastAPI Route·Application·LangGraph·Agent·Domain의 Gmail·Tasks·Calendar Provider API/SDK 직접 호출은 금지하며 모든 Google Workspace Read/Write/Verification/Recovery 조회는 MCP Client/Tool 경계를 통과한다.

## 16. Runtime Command Trust Boundary

- `request_hash`는 Browser가 전달한 값을 신뢰하지 않고 Endpoint별 Versioned Request Schema의 Canonical JSON에서 서버가 계산한다.
- Approval ID, Approval Snapshot, Write Idempotency Key, Source Snapshot, 승인 주체와 Arguments Hash는 현재 Domain 상태에서 서버가 생성한다.
- Local Session이 사용자/승인 주체의 기준이며 Browser가 actor identity를 지정하지 않는다.
- `/resume`는 허용된 typed `resume_kind`만 받고 임의 dict payload를 허용하지 않는다.
- Verification `MISMATCH` Recovery는 `ACCEPT_PARTIAL | CREATE_CORRECTIVE_PLAN`만 허용하며, 교정 Write는 새 승인 경계를 통과한다.
- dispatch 이후 Timeout·5xx·connection loss는 미전달이 보장되지 않으면 `UNKNOWN_RESULT`로 처리한다.

## ClaimContextV2·Gmail 첨부파일 보안 경계

### ClaimContextV2
- HMAC-SHA-256, `claim_version=2`, 기본 TTL 30초·최대 60초, 1회용 Nonce.
- Service Instance와 MCP Process Instance에 모두 바인딩한다.
- Action·Approval·ExecutionAttempt·Tool·`approval_arguments_hash`·`execution_arguments_hash`를 서명 범위에 포함한다.
- Claim Token 원문은 Log·Trace·Audit에 기록하지 않는다.
- MCP가 실제 수신 인자를 재해시해 일치시키기 전에는 Write를 수행하지 않는다.

### Gmail 첨부파일
- 기존 `gmail.readonly`는 수신 첨부파일 조회, `gmail.compose`는 Draft/Send MIME 첨부를 수용하므로 R8.4에서 새 OAuth Scope를 추가하지 않는다.
- 발신 파일은 Browser가 임의 Local Path를 실행 인자로 지정하지 않는다. Local Service가 bytes를 받아 사용자 전용 Staging ID와 SHA-256을 발급한다.
- Approval Snapshot에는 raw bytes가 아니라 Descriptor와 SHA-256을 고정한다.
- Local Service와 MCP는 실행 직전 실제 bytes의 크기·SHA-256을 재검증한다.
- 파일 bytes·Local Path는 LLM·SQLite·Trace·Diagnostic Bundle에 노출하지 않는다.



## Policy Confirmation Receipt 보안 경계
- `PolicyConfirmationReceiptV1`은 LLM·Agent·Browser가 권위 값으로 생성하지 않는다. 검증된 Local Session의 실제 사용자 응답을 Application/Confirmation Controller가 canonicalize해 생성한다.
- `SCOPE_EXPANSION`, `DUPLICATE_OVERRIDE`, `CONFLICT_OVERRIDE` Receipt는 `meta.based_on`과 `decision_context_hash`가 현재 Route/Evidence/Action revision에 맞아야 한다. upstream 변경 후 stale Receipt 재사용을 금지한다.
- Approval Snapshot은 필요한 Receipt ID·Context Hash를 고정한다. Domain Validation/Preflight는 누락·DECLINED·stale·hash mismatch를 Claim 발급 전에 차단한다. Receipt는 MCP Write payload의 권위 확장 수단이 아니며 ClaimContextV2의 execution hash 역할과 분리한다.
