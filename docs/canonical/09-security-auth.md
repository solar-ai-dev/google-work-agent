# 09. 보안 · Auth 설계서

> **Authority:** security/auth trust boundary, credential/secret handling, security policy realization. Product policy와 interface/runtime semantics는 해당 owner를 따른다.

## 0. 문서 정보

- **상태:** Draft v2.13
- **기준일:** 2026-08-26
- **대상:** P0 MVP
- **배포:** Windows Installer 기반 로컬 애플리케이션

## 1. 핵심 보안 결정

`10. 인프라·환경 설정 설계서`의 `SEC-INF-001~020`은 본 문서의 구현 계약이다. 충돌 시 본 문서의 금지·Credential·개인정보 정책을 우선하고, 10은 그 정책을 Process·Directory·Config 값으로 구현한다.

- Local Session은 `HttpOnly`, `SameSite=Strict` Cookie를 사용한다.
- Bootstrap Secret은 URL Fragment로 한 번 전달하고 Session 수립 후 즉시 제거·폐기한다.
- Connector Credential과 Token lifecycle은 해당 Connector MCP Server 내부 Credential Provider가 소유한다. P0 Google Workspace에서는 Google OAuth·Token Refresh와 Google Refresh Token Keyring 접근을 Google Workspace MCP가 소유한다.
- 외부 Provider API/SDK 호출 권한은 각 Connector MCP Server 내부 Adapter만 소유한다. 제품 Core에서 외부 Connector I/O를 요청하는 caller는 Application의 결정적 use-case/Application operation이며, Application은 먼저 `SignedToolRegistry`로 `ValidatedConnectorToolBindingV1`을 만든 뒤 `ConnectorReadPort | ConnectorWritePort | OAuthCredentialPort` 같은 abstract Connector Application Port만 사용한다. Core-side Connector Adapter는 그 binding과 `ConnectorRuntimeRegistry + MCPClientPort`를 사용한다. React·FastAPI Route·LangGraph adapter/Agent·Domain은 concrete Connector/MCP path, `ConnectorRuntimeRegistry`, `MCPClientPort`, Provider API를 직접 호출하지 않는다.
- LLM API Key는 `storage_mode=KEYRING`일 때만 FastAPI Local Agent Service의 LLM credential adapter가 Keyring Entry를 사용한다. `SESSION_ONLY`이면 Local Agent Process Memory에만 두며 Keyring write는 0이다. Google Credential과 LLM Credential lifecycle을 분리한다.
- P0는 SQLite Application-level Encryption을 제공하지 않으며 Secret은 SQLite에 저장하지 않는다.
- 외부 LLM 전송은 설정 단위 사전 동의와 Run별 전송 범위 표시를 요구한다.
- Product Prompt/외부 LLM 전송 범위는 **현재 Run의 allowlisted Typed Projection**으로 제한한다. 같은 Conversation의 과거 Message 전체나 이전 Run의 Agent Artifact·Evidence·Plan·Confirmation/Approval Metadata를 새 Run에 자동 전송하지 않는다.
- `conversation_id`는 상관관계·Timeline 식별자이지 개인정보 전송 범위를 확장하는 동의나 Context 권한이 아니다.
- 사용자가 과거 Resource를 이번 Run에 명시적으로 다시 선택한 경우에도 현재 Run에 필요한 최소 Resource/Evidence만 새로 조회·Projection하며 이전 Run의 원문·승인 Snapshot을 함께 전송하지 않는다.
- 동일 Run의 Confirmation resume에서 허용된 bounded `confirmation_response`만 originating owner Prompt에 전달할 수 있고 raw interrupt/checkpoint metadata는 전송하지 않는다.
- 외부 LLM 전송 동의가 없으면 `AUTO`의 API Fallback을 금지한다.
- 외부 테스트·공개 배포 Installer는 Windows Code Signing을 필수로 한다.
- Uninstall은 Credential을 기본 삭제하고 DB·Backup은 기본 보존한다.

## 2. 신뢰 경계

```
사용자
→ Chrome · React Frontend
→ FastAPI Route
→ Application
   ├─ LangGraph / Agent orchestration
   ├─ Domain Policy
   └─ Signed Tool Registry → `ValidatedConnectorToolBindingV1`
      → Connector Application Port
      → Core-side Connector Adapter
      → Connector Runtime Registry + MCPClientPort
      → Connector MCP Server · stdio
      → Provider APIs  # 각 Connector MCP Server 내부 Adapter에서만 접근

P0: google_workspace → Google Workspace MCP Server → Gmail·Tasks·Calendar Provider APIs

FastAPI Route
→ Application use case
   ├→ Domain Repository Port ← SQLite Repository Adapter → SQLite Domain Store
   ├→ CheckpointPort ← Checkpointer Adapter → LangGraph Checkpoint Store
   └→ LLM Ports ← LLM Adapters → LLM Credential Keyring · API LLM Provider 또는 Ollama

Connector Credential Keyring은 위 Core LLM 경계가 아니라 각 Connector MCP Server 내부 Credential Provider가 별도로 접근한다.
```

- React와 SSE는 실행 사실의 기준점이 아니다.
- FastAPI Route는 Application use-case boundary만 호출한다.
- LangGraph Node와 LLM 출력은 Domain 상태를 직접 수정하지 않는다.
- Connector Source 본문·URL·HTML, LLM 출력과 MCP 응답은 비신뢰 데이터다. P0 Google Workspace의 Gmail·Tasks·Calendar도 동일하다.
- SQLite Domain Store의 승인·실행·검증 상태가 실행 사실의 기준점이다.

## 3. Local Agent API 보안

### 3.1 네트워크

- `127.0.0.1`의 Launcher 할당 동적 Port에만 Bind한다.
- `0.0.0.0`, LAN Interface, Remote Access와 Public Bind를 금지한다.
- 운영 UI와 `/api/v1`은 same-origin으로 제공한다.
- 운영 API 문서 UI와 와일드카드 CORS를 비활성화한다.

### 3.2 Bootstrap·Session

```
Launcher
→ 256-bit 이상 Bootstrap Secret 생성
→ URL Fragment로 React에 전달
→ POST /api/v1/session/bootstrap
→ Local Session Cookie 발급
→ Secret 폐기
→ history.replaceState로 Fragment 제거
```

- Bootstrap Secret 기본 유효 시간은 60초다.
- 한 번만 사용할 수 있고 검증 실패는 최대 3회다.
- Query String, Browser Storage, SQLite와 일반 로그에 저장하지 않는다.
- Session Cookie는 `HttpOnly`, `SameSite=Strict`, `Path=/`, Domain 미설정을 사용한다.
- Local Service 재시작과 앱 종료 시 기존 Session을 무효화한다.

### 3.3 요청 검증

- 상태 변경 요청은 정확한 `Host`, `Origin`, Fetch Metadata, JSON Content-Type과 Local Session을 검증한다.
- Domain Aggregate mutation Command는 `command_id + 대상 Aggregate ID + expected_version`을 요구한다. `expected_version`은 해당 Aggregate의 optimistic concurrency authority다.
- Connection/Credential/Settings/Runtime Mode/Backup·Restore/Diagnostics/Shutdown/Attachment staging 같은 non-Domain operational Command는 `command_id + operation-specific Versioned Request Schema`를 사용하며, concern owner가 별도의 versioned target/revision을 정의한 경우에만 그 revision을 요구한다. Domain `expected_version`을 임의 생성하거나 다른 Aggregate version을 재사용하지 않는다.
- `command_id`가 있는 모든 Local API Command는 Application이 Versioned Request Schema의 canonical hash를 계산해 같은 ID+같은 hash만 replay하고 같은 ID+다른 hash는 conflict로 차단한다. 04의 Domain `command_receipts`는 Domain Aggregate mutation에 적용하며, non-Domain side-effect replay/idempotency는 Application owner가 07 `OperationalCommandReplayPort`로 같은 command identity/hash/result를 adjudicate한 뒤 operation Port를 호출한다.
- Resource Browse의 `selection_handle`은 Local Service가 현재 `service_instance_id + Local Session + account_id + connector/resource identity + expiry`에 bind해 authenticated opaque value로 발급한다. Browser는 내부 identity를 decode/수정하지 않으며 StartRun은 signature/session/account/expiry mismatch를 Provider probing 없이 fail closed한다. selection-handle signing secret은 Local Service process memory에만 두고 restart 시 폐기한다.
- Browser는 사용자 의도와 기존 Aggregate를 가리키는 허용된 correlation/idempotency 입력만 전달한다. 새 Run 생성에서 `run_id`, `user_message_id`, `workflow_key`, `langgraph_thread_id`를 생성·제출하지 않으며, 공통적으로 `request_hash`, `approval_id`, Write `idempotency_key`, `source_snapshot`, actor identity, `approval_arguments_hash`, `execution_arguments_hash`, `claim_token`을 권위 값으로 생성하지 않는다. 새 Run/Message/Workflow identity는 검증된 StartRun 처리 이후 Server/Application/Domain이 생성한다.
- Application command handler가 Versioned Request Schema의 Canonical JSON으로 `request_hash`를 계산한다. 같은 `command_id + 같은 hash`만 Replay로 인정하고 같은 `command_id + 다른 hash`는 Conflict로 차단한다. Domain Aggregate Command의 durable receipt semantics와 non-Domain operational command의 Port-level replay semantics를 혼용하지 않는다.
- Approval actor는 검증된 Local Session에서 결정하고 Approval Snapshot·Source·Policy·Tool Schema·Hash는 서버의 현재 Domain 상태에서 생성한다.
- Connector Write 멱등성은 Server가 생성한 Approval의 `idempotency_key`와 실행권 Claim으로 보장한다.
- 중복 Command는 동일 Domain Transition을 다시 적용하지 않는다.
- Resource Browse·Count처럼 읽기 전용 Local API는 기존 Local Session 검증을 먼저 통과한다. Application에 필요한 경우 `LocalSessionRecord.digest`를 opaque local session identity로, 현재 연결 계정의 server-side `account_id`를 active Google account identity로만 전달할 수 있다. raw session cookie/token, OAuth access token, Refresh Token은 Application snapshot·React cache key·Trace에 전달하지 않는다.

## 4. React Frontend 보안

- React는 Connector Credential, API Key, OS Keyring, SQLite와 MCP에 직접 접근하지 않는다.
- Secret을 `localStorage`, `sessionStorage`, IndexedDB에 저장하지 않는다.
- Gmail HTML과 LLM Markdown은 Safe Text 또는 엄격히 Sanitized Content로 표시한다.
- `javascript:`, `data:`, `file:` URL Scheme을 차단한다.
- 외부 링크는 명시적인 사용자 동작으로만 연다.
- UI 상태만으로 승인·실행·검증 성공을 확정하지 않는다.

## 5. Google Workspace Connector OAuth

### 5.1 책임 경계

```
React
→ FastAPI Route
→ Application OAuth coordination
→ OAuthCredentialPort
→ MCP Credential Provider
`OAuthCredentialPort`의 모든 operation은 `connector_id`를 보존한다. Core-side adapter는 Connector Runtime Registry로 해당 MCP child를 선택하고, Token/Keyring 접근은 선택된 Connector MCP Server 내부 Credential Provider만 수행한다. 신규 Connector마다 별도 Application credential service나 direct Keyring path를 만들지 않는다.
→ Google OAuth
→ OS Keyring
```

- OAuth 기능은 LLM이 선택하는 MCP Tool로 등록하지 않는다.
- 시스템 브라우저, Authorization Code + PKCE, `state`, `127.0.0.1` Loopback Redirect를 사용한다.
- Callback Listener는 인증 흐름 중에만 열고 완료·실패 후 종료한다.
- Access Token과 Refresh Token을 React와 FastAPI Response에 반환하지 않는다.

### 5.2 P0 Scope

- Account display identity: `openid`, `email` (verified `display_email` projection only; Token 원문은 UI/API에 노출하지 않음)
- Gmail: `gmail.readonly`, `gmail.compose`
- Tasks: `tasks`
- Calendar: `calendar.events`, `calendar.calendarlist.readonly`, `calendar.events.freebusy`
- Gmail 전송은 승인 필수 `gmail_send` Tool로 지원하며 승인된 수신자·CC·제목·본문·Thread Hash가 일치해야 한다.
- Scope 일부가 거절되면 연결 완료로 처리하지 않는다.

### 5.3 Credential 저장

- Refresh Token은 OS Keyring에 저장한다.
- Access Token은 MCP Credential Provider Process Memory에서만 사용한다.
- Token을 SQLite, Checkpoint, Trace, Audit, 환경 변수와 Process Argument에 저장하지 않는다.
- P0 Google Installed/Desktop OAuth는 **non-secret `oauth_client_id` + PKCE S256 + `state` + ephemeral loopback callback**만 사용하며 `client_secret`을 protocol input, build artifact, runtime configuration 또는 credential storage로 요구하지 않는다.
- Provider/downloaded client configuration에 `client_secret` field가 존재해도 P0 loader는 이를 무시하며 React/Vite, FastAPI wire, MCP child environment, OS Keyring, SQLite, Trace, Audit, Diagnostic Payload로 전달·저장하지 않는다.
- Development의 local configuration도 `GOOGLE_OAUTH_CLIENT_ID`만 허용하고 `GOOGLE_OAUTH_CLIENT_SECRET` key/path는 current P0 contract에 존재하지 않는다.
- Production은 `.env.local` 또는 ambient 사용자 환경 변수에서 Desktop OAuth Client identity를 읽지 않는다. non-secret `OAUTH_ENV/OAUTH_CLIENT_ID`는 10의 verified `release-manifest.json → SignedBuildConfigV1`이 유일한 build authority이며 Service가 그 값만 MCP child allowlist에 주입한다. 별도 `client_secret` provisioning boundary는 P0에 두지 않는다.
- 연결 해제 시 Google Revoke를 시도하고 Local Keyring Credential을 삭제한다.


### 5.4 Reauth Run binding

OAuth callback success is connector credential state and is intentionally Run-neutral. It does not carry `run_id` and does not auto-resume suspended graphs. A specific `REAUTH_REQUIRED` Run is resumed only by its authenticated `/runs/{run_id}/resume(REAUTH_COMPLETED)` command; `ResumeAfterReauth(applied=true)` and durable handoff creation precede workflow execution. This avoids binding one OAuth callback to the wrong Run when multiple Runs/conversations require Reauth across time.

## 6. LLM API Key와 외부 전송

- API Key 기본 저장소는 OS Keyring이다.
- 세션 전용 Key는 Local Agent Process Memory에만 유지한다.
- React에는 Key 존재 여부와 검증 상태만 반환한다.
- 외부 LLM 사용 전 설정 단위 동의를 받는다.
- 각 Run에서 외부로 전송될 Source와 범위를 표시한다.
- 요청 수행에 필요한 최소 Context만 전송한다.
- OAuth Token, API Key, Claim Token·ClaimContextV2 원문, 내부 Hash, 전체 Mailbox와 미사용 검색 후보는 전송하지 않는다.

### 6.1 AUTO Fallback

- 외부 전송 동의가 있으면 허용된 Local 기술 오류에서 API Fallback을 최대 1회 수행할 수 있다.
- 동의가 없으면 API Fallback을 금지하고 사용자 전환 동의를 요구한다.
- 명시적 `LOCAL_GPU`에서는 자동 API 전환을 금지한다.

## 7. 고정 정책

- Gmail Message·Thread 원문 삭제 금지
- 반복 Event 전체 일괄 수정 금지
- Gmail SEND·Task 완료·Google Task 삭제·Calendar Event 삭제·참석자 변경은 승인형 Write로만 허용
- 승인 없는 외부 Connector Write 금지
- Approval Snapshot·Hash 불일치 차단
- 정책상 별도 확인이 필요한 Scope 확장·정확 중복 추가 생성·일정 충돌 Override는 현재 Context에 유효한 `PolicyConfirmationReceiptV1(APPROVED)` 없이 허용하지 않음
- 승인 만료 Action 직접 실행 금지
- `UNKNOWN_RESULT`에서 새 Attempt·새 Write 금지
- 요청 범위 밖 임의 조회 금지
- LLM의 권한·위험 등급·Policy Override 결정 금지
- React의 직접 Connector Write 금지
- FastAPI Route·LangGraph adapter/Agent·Domain의 concrete Connector/MCP 및 외부 Provider API/SDK 직접 호출 금지. 모든 Connector Read/Write/Verification/Recovery 조회는 Application의 결정적 operation이 Signed Tool Registry에서 validated Tool binding을 만든 뒤 abstract Connector Application Port를 호출하고, Core-side Connector Adapter가 ConnectorRuntimeRegistry·MCPClientPort 경계를 조정해야 한다. Application의 adapter-level registry/client 직접 호출도 금지하며 P0 Google Workspace도 동일함

## 8. Prompt Injection과 입력 검증

- Source 본문을 `UNTRUSTED_SOURCE_CONTENT`로 구분한다.
- Retrieval Normalize 단계는 모든 SourceSegment에 `trust_class=UNTRUSTED_SOURCE_CONTENT`, `content_role=DATA_ONLY`를 구조적으로 부여한다. Source 안의 명령형 문구를 발견한 경우 `instruction_like_content_detected`를 기록할 수 있지만, 탐지 결과와 관계없이 Source는 항상 비신뢰 데이터다.
- `instruction_like_content_detected=false`를 신뢰 판정으로 사용하지 않는다. 탐지는 관측·평가 보조 신호이고 실행 권한을 만들지 않는다.
- Source Content에서 발견한 시스템 지시·승인 우회·Credential 요구·Tool 실행 요구는 RequestIntent, ToolRoutePlan, WorkflowSignal, Approval 또는 Domain Command로 승격하지 않는다.
- Source 내 지시는 System·Domain Policy보다 우선할 수 없다.
- LLM이 생성한 Raw Google Query, Tool Name과 Arguments를 검증 없이 실행하지 않는다.
- Tool Allowlist와 Versioned Structured Output을 사용한다.
- 결정적 Validator가 날짜·이메일·Resource Type·Scope·Arguments를 검증한다.
- Source 문자열이 Local File, Shell, Process 실행과 URL Fetch를 유발하지 못하게 한다.

## 9. 승인·실행·검증 보안

- Approval은 Action Version, Tool, Business Arguments Snapshot·`approval_arguments_hash`, Source Snapshot, Policy Version, Tool Schema Version과 만료 시각을 고정한다. 해당 Action이 `DUPLICATE_OVERRIDE_REQUIRED` 또는 `CONFLICT_OVERRIDE_REQUIRED`에 의존하면 `PolicyConfirmationReceiptV1`의 Artifact Ref와 `decision_context_hash`도 Approval Snapshot에 고정한다.
- 실행 직전 Approval, `approval_arguments_hash`, 최신 Resource, Dependency, 중복·충돌과 기존 Attempt를 다시 검증한다. 정책 Override Action은 Approval Snapshot에 결합된 Receipt가 `APPROVED`이고 현재 Request/Route/Retrieval revision에 대해 stale하지 않은지도 확인하며, 누락·불일치·stale이면 Claim을 발급하지 않는다.
- Application은 승인된 Business Arguments에서 결정적으로 최종 MCP Write Payload를 생성하고 `execution_arguments_hash`를 계산해 `ClaimContextV2`에 서명한다. Claim Commit/ClaimContext만으로 외부 호출하지 않으며, current binding + cancel intent 없음으로 `BeginExecutionAttempt`가 `applied=true` Commit되어 Attempt=`EXECUTING`인 뒤에만 MCP 호출을 시작한다.
- MCP는 `version`, `issued_at_ms`, `expires_at_ms`, Service/MCP Process Instance, Action·Approval·Attempt·Tool, 두 Arguments Hash와 Nonce를 검증하고 실제 수신 실행 인자를 다시 canonicalize·hash한다.
- 어느 검증이라도 실패하면 MCP Write·Connector Provider Write를 호출하지 않는다.
- 만료 Action은 `EXPIRED → MODIFIED → 새 Approval → APPROVED`만 허용한다.
- MCP·LLM 같은 외부 호출 중 SQLite Transaction을 유지하지 않는다. Google Provider API 호출은 MCP Server 내부에서 수행되며 제품 Core가 Provider API를 직접 호출하는 경로는 허용하지 않는다.
- Write 실패 재시도는 새 Approval·Idempotency Key·Source Snapshot을 요구한다.
- `UNKNOWN_RESULT`에서는 기존 결과 조회만 허용한다.
- 모든 Write는 Effect별 결정적 검증을 수행한다. CREATE·UPDATE는 GET 비교, DELETE는 삭제 상태/NOT_FOUND 확인, SEND는 Sent 결과 조회를 사용한다.

## 10. MCP 보안

- Transport는 Local `stdio`만 허용한다.
- MCP Server의 Network Listen을 금지한다.
- 검증된 Executable 절대 경로와 Argument List를 사용한다.
- Shell 실행과 Search Path 의존을 금지한다.
- OAuth Token과 API Key를 환경 변수·Command Line으로 전달하지 않는다.
- P0 MCP Credential Provider는 Google Desktop OAuth `client_secret`을 읽거나 전달하지 않는다. Development와 Production 모두 `oauth_client_id`만 configuration identity로 사용하며 Access/Refresh Token, LLM API Key 또는 다른 Secret의 환경 변수 저장은 계속 금지한다.
- 허용 Tool만 등록한다. `gmail_send`, Task 완료 Update, `tasks_delete_task`, `calendar_delete_event`, 참석자 Update는 승인·Hash·Policy 검증이 연결된 경우에만 등록한다. Gmail 원문 삭제·반복 Event 전체 일괄 수정 Tool은 포함하지 않는다.
- Write Tool은 Action·Approval·Attempt, `approval_arguments_hash`, 실제 Payload의 `execution_arguments_hash`와 검증된 `ClaimContextV2`를 요구한다.
- Claim V2는 HMAC-SHA-256, 기본 TTL 30초·최대 60초, 1회용 Nonce를 사용한다. `version`과 `issued_at_ms`도 Signature 대상이며, Service 또는 MCP Process 재시작 후 이전 Claim은 무효다.
- Nonce는 모든 Binding과 실제 실행 인자 Hash 검증을 통과한 뒤 dispatch 직전에 원자적으로 소비한다.
- MCP 재시작 후 Core `SignedToolRegistry`와 MCP Server의 signed projection/descriptor 및 Schema Version 정합성을 다시 검증한다. MCP Server는 별도 Tool semantic Registry authority를 만들지 않는다.
- Write 전달 가능성이 있으면 자동 재전송하지 않는다.

## 11. Ollama 보안

- 제품 Local Runtime은 Ollama로 고정한다.
- Loopback Endpoint만 허용하며 원격 Ollama 연결을 제공하지 않는다.
- Ollama는 Google Credential, OS Keyring과 MCP에 접근하지 않는다.
- Structured Output을 Domain Policy가 검증한 뒤 MCP Command로 변환한다.
- 검증된 Ollama Version, Model ID·Hash와 Config만 제품에 사용한다.
- CPU Local LLM Backend는 P0 제품에 포함하지 않는다.

## 12. SQLite·Backup

- SQLite에는 Conversation, Run, Plan, Action, 최소 ResourceRef·Evidence, Approval, Attempt와 Verification을 저장한다.
- OAuth Token, API Key, Bootstrap Secret과 Session 값은 저장하지 않는다.
- P0는 SQLCipher와 Column Encryption을 제공하지 않는다.
- DB와 Backup의 기밀성은 Windows 사용자 계정과 파일 접근 통제에 의존한다.
- DB와 Backup은 동일한 민감도 등급으로 처리한다.
- Migration 전 Backup과 적용 후 무결성 검사를 수행한다.
- 무결성 실패 시 Safe Mode로 전환하고 모든 Connector Write를 차단한다.

## 13. Installer·Launcher

- Installer는 React Build, 앱 전용 Python Runtime, FastAPI, LangGraph, MCP Server와 Launcher를 포함한다.
- Source Map, `.env`, 개발 Secret, Test Credential과 실험 Raw Result를 포함하지 않는다.
- 외부 테스트·공개 배포 Artifact는 Windows Code Signing, Timestamp와 SHA-256 Manifest를 요구한다.
- 검증된 Executable 절대 경로와 제한된 환경을 사용한다.
- Upgrade 전 DB Backup, 서명·Hash 확인, Migration과 MCP Schema 검증을 수행한다.

## 14. Uninstall

### 기본 동작

- 프로그램 파일 삭제
- OAuth Refresh Token 삭제
- LLM API Key 삭제
- Local Session·Bootstrap 무효화
- SQLite DB·Backup·Settings 기본 보존

### 완전 삭제

사용자 명시 선택과 경고 후 다음을 모두 삭제한다.

- DB, WAL, SHM
- Backup과 Manifest
- Settings와 Sanitized Log
- OAuth·LLM Keyring Entry
- 임시 Migration·Restore 파일

## 15. 로그·Audit·진단

### 기록 가능

- Run·Action ID, 상태, Version, 시각
- Node·Tool, Provider·Model·Runtime
- Latency·Token, 오류 코드
- 승인·수정·거절·실행·검증 결과

### 기록 금지 또는 마스킹

- OAuth Token·Authorization Header
- LLM API Key
- Bootstrap Secret·Local Session
- 전체 Gmail 본문과 불필요한 Draft 본문
- 민감 이메일 주소와 개인 식별자
- Local User Name·Home Path·장치 고유 정보
- Claim Token·ClaimContextV2 원문과 전체 Canonical Arguments
- 진단 Bundle은 사용자 명시 동작으로만 생성한다.
- 자동 외부 업로드를 수행하지 않는다.

## 16. 배포 프로필

### API_ONLY

- Ollama·GPU·Model File 없이 동작한다.
- API Key와 외부 전송 동의가 없으면 Agent 실행을 차단한다.
- React·FastAPI·LangGraph·MCP·Policy를 모두 포함한다.

### LOCAL_CAPABLE

- Ollama Adapter와 진단 UI를 포함한다.
- 검증된 GPU에서만 Local 기능을 활성화한다.
- GPU 기준 미달이면 API_LLM으로 고정한다.
- 외부 전송 동의가 없으면 AUTO API Fallback을 수행하지 않는다.

## 17. 보안 테스트

- Public·LAN Bind 차단
- 허용되지 않은 Host·Origin·Cross-site 요청 차단
- Bootstrap 만료·재사용·실패 횟수 차단
- Session Cookie 속성과 Service 재시작 무효화
- 미승인 Write·Hash 변경·Version Conflict 차단
- 중복 Command의 상태 중복 적용 방지
- `UNKNOWN_RESULT` 재실행 차단
- 금지 Tool 미등록
- MCP Executable·Arguments 변조 방지
- Prompt Injection·악성 Structured Output 차단
- React HTML·Markdown·URL Sanitization
- Key·Token·Secret 로그 유출 검사
- OAuth State·PKCE·Scope 거절·Token 만료
- 외부 전송 동의 없는 API 호출·Fallback 차단
- Installer Secret·Source Map·서명·Hash 검사
- Uninstall·완전 삭제 데이터 처리 검증

## 18. Security Release Gate

| 항목 | 기준 |
| --- | --- |
| 승인 없는 Write | 0건 |
| 금지 Tool 등록·실행 | 0건 |
| Write GET 검증 누락 | 0건 |
| Credential Leakage | 0건 |
| 외부 Origin 상태 변경 성공 | 0건 |
| 동의 없는 외부 LLM 호출 | 0건 |
| 미해결 UNKNOWN_RESULT 재실행 | 0건 |
| 외부 배포 Installer 서명 실패 | 0건 |

## 19. Gmail 첨부파일 보안 경계

- 수신 첨부파일은 Gmail Message Part Metadata만 기본 조회하고, 사용자 요청이 있을 때만 Attachment bytes를 가져온다.
- Attachment bytes·문서 내용은 API LLM·Ollama Prompt, AgentLocalState, ContextBundle, Evidence, Trace, Audit에 전달하지 않는다.
- 발신 파일은 Browser가 임의 Local Path를 실행 인자로 지정하지 않는다. `POST /api/v1/attachments/stage`가 실제 bytes를 받아 서버가 `staged_attachment_id`, filename, MIME Type, size, SHA-256을 계산한다.
- Staging은 현재 Windows 사용자 전용 ACL을 사용하고 짧은 TTL 후 삭제한다. SQLite·Backup·Diagnostic Bundle에 포함하지 않는다.
- 승인 Snapshot에는 raw bytes가 아니라 Attachment Descriptor와 SHA-256을 고정한다. 실행 직전 Local Service와 MCP가 각각 실제 bytes의 size·SHA-256을 재검증한다.
- `multipart/form-data` 허용은 Attachment Staging Endpoint에만 한정하며 Local Session·Host·Origin·Fetch Metadata 검증을 그대로 요구한다.
- Gmail API의 기존 `gmail.readonly`와 `gmail.compose` Scope 안에서 처리하며 첨부파일 기능 때문에 별도 광범위 Scope를 추가하지 않는다.
- Attachment 파일명·MIME Type도 비신뢰 입력으로 취급하고 OS Path·Shell Argument로 직접 사용하지 않는다.
- Attachment download/staging은 반드시 bounded되어야 하지만 exact byte limit은 보안 semantics가 아니라 runtime configuration의 implementation choice다. 같은 build/profile 안에서는 Local API·staging·Connector boundary가 동일한 effective limit을 사용하며 limit 초과는 Provider/LLM 호출 전에 fail closed한다.

### External LLM consent enforcement

`external_llm_consent`는 Settings의 non-secret persisted boolean이며 default false다. `StructuredInferenceRuntimeRouter`는 `API_LLM` 또는 AUTO→API fallback 직전 이 fact를 조회한다. false이면 API provider call 0. Browser/localStorage/API-key-presence를 consent로 추론하지 않는다. `ExternalLlmTransferScopeV1`은 표시용 non-secret projection이며 consent fact가 아니다. External provider call 전 Router는 caller의 exact typed input에서 계산된 scope가 `CheckpointPort.store_external_llm_scope`로 먼저 publish되었는지 동일 hash/revision으로 확인한다. scope publish 전 call, stale scope hash로 확대된 Context 전송, consent revoke 뒤 call은 모두 0이다. Browser ACK/paint는 credential/consent authority가 아니다.

### Google account display identity

`account_id`는 server-internal opaque account identity이며 email로 해석하지 않는다. P0 OAuth scope set은 account-display projection에 필요한 `openid` + `email` identity scope를 포함한다. MCP Credential Provider가 authorization/refresh metadata에서 verified primary email을 얻어 `ConnectionMetadataV1.display_email`에 non-secret UI projection으로 반환한다. React는 token/userinfo API를 직접 호출하지 않는다.

### Pre-dispatch claimed-attempt safety

Attempt `CLAIMED`는 external dispatch authority가 아니다. cancel/restart/security failure가 BeginExecutionAttempt 전에 발생하면 `AbortClaimedExecution`으로만 terminalize하며 Provider Write는 0이다. Security code가 `MarkFailed`를 CLAIMED state에 직접 적용하거나 hidden cancel transition을 만들지 않는다.

### Operational replay receipt security

`OperationalCommandReplayPort` stores only `command_id`, operation kind, canonical request hash, bounded non-secret result/ref, timestamps/status. It never stores raw API keys, OAuth tokens, attachment bytes, diagnostic contents, or raw filesystem paths. Secret-bearing request hashes are one-way canonical digests and are not treated as credential material. The operational replay store is local-user ACL protected and excluded from Domain backup restore payload so Restore cannot overwrite its own replay adjudication state.
