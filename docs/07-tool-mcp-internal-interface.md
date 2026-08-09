# 07. Google Work Agent · Tool · MCP · 내부 인터페이스 명세서

> **문서 기준:** `01`~`06`의 React + FastAPI Local Agent Service 구조와 `06. Agent·Workflow 설계서 Draft v5.9`을 기준으로 한다. 외부 공개 API가 아니라 설치된 앱 내부의 Local API, MCP Tool, Python 내부 인터페이스 계약을 정의한다.

## 0. 문서 정보

- **상태:** Draft v2.7
- **기준일:** 2026-08-09
- **대상:** P0 MVP
- **배포 형태:** Windows 설치 파일 기반 로컬 애플리케이션

## 1. 범위

이 문서는 세 가지 인터페이스를 정의한다.

1. React Frontend와 FastAPI Local Agent Service 사이의 Local API
2. Python Application·LangGraph·Domain 사이의 내부 Port·Command 계약
3. FastAPI Local Agent Service가 자식 프로세스로 관리하는 Google Work MCP Server의 Tool 계약

다음은 제공하지 않는다.

- 인터넷에 공개되는 REST API
- 원격 Backend 또는 SaaS API
- 원격 MCP Server
- React에서 Google API·SQLite·OS Keyring·MCP를 직접 호출하는 경로

## 2. 설치·Runtime 경계

```text
Windows Installer
→ Launcher
→ FastAPI Local Agent Service
   ├─ React 정적 Build 제공
   ├─ REST·SSE 제공
   ├─ Application·LangGraph 실행
   └─ Google Work MCP Server 자식 프로세스 실행
```

- 사용자는 Python, Node.js, npm, Vite를 별도로 설치하지 않는다.
- 운영 Runtime에서 Vite 개발 서버를 실행하지 않는다.
- Local Service는 `127.0.0.1`의 동적 포트에만 바인딩한다.
- Launcher가 Local Service 시작·Health Check·브라우저 열기·종료를 관리한다.

## 3. Local Agent API

### 3.1 공통 규칙

- Base Path: `/api/v1`
- 운영 UI와 API는 same-origin이다.
- Endpoint별 인증은 20. 인증 Matrix를 따른다. Bootstrap·Health·OAuth Callback은 기존 Local Session을 요구하지 않는다.
- 상태 변경 Command는 `command_id`와 대상 `expected_version`을 포함한다.
- API Handler는 Domain 상태를 직접 수정하지 않고 Application Command를 호출한다.
- 응답 유실·재전송에도 동일 Command를 중복 적용하지 않는다.
- UI 상태와 SSE Event는 실행 사실의 기준점이 아니다.

### 3.2 주요 Endpoint

`/health/*`는 인증 전 Launcher용이며 Base Path 밖에 둔다. 나머지 Endpoint는 모두 `/api/v1` 전체 경로를 사용한다.

| 구분 | Method·Path | 역할 |
|---|---|---|
| Liveness | `GET /health/live` | FastAPI Process 응답 여부 |
| Core Readiness | `GET /health/ready` | Manifest·Asset·API Contract·SQLite·Migration·Domain·Keyring Adapter·MCP Executable·Tool Schema |
| Runtime Detail | `GET /api/v1/runtime` | Local Session 이후 Google Credential·Scope·LLM Provider·Ollama·Model·Recovery 상태 |
| Session | `POST /api/v1/session/bootstrap` | Launcher Bootstrap으로 Local Session 수립 |
| Conversation | `GET/POST /api/v1/conversations` | 대화 조회·생성 |
| Run | `POST /api/v1/runs`, `GET /api/v1/runs/{run_id}` | 요청 시작·현재 Domain 상태 조회 |
| Interrupt | `POST /api/v1/runs/{run_id}/confirm` | 확인 질문 응답으로 Graph 재개 |
| Approval | `POST /api/v1/actions/{action_id}/approve\|modify\|reject` | 승인·수정·거절 Command |
| Retry | `POST /api/v1/actions/{action_id}/prepare-retry` | 실패한 Write를 `MODIFIED`로 전환해 새 승인 준비 |
| Control | `POST /api/v1/runs/{run_id}/cancel\|resume` | 취소 요청·안전 지점 재개 |
| Resource | `GET /api/v1/resources/gmail\|tasks\|calendar` | Sidebar 목록·검색·Page Token 조회 |
| Event | `GET /api/v1/runs/{run_id}/events` | SSE 진행 Projection |

### 3.3 상태 변경 API 입력 소유권

브라우저는 사용자 의도와 낙관적 동시성에 필요한 값만 보낸다. Domain 권위 Metadata는 Application이 현재 Domain 상태에서 생성·검증한다.

- Client 입력 허용: `command_id`, 대상 ID, `expected_version`, 사용자 선택·텍스트·수정하려는 허용 필드.
- Server 생성·검증: `request_hash`, `approval_id`, Write `idempotency_key`, `source_snapshot`, 승인 주체 식별, `canonical_arguments_hash`, `claim_token`.
- `request_hash`는 수신 JSON을 그대로 Hash하지 않고 Endpoint별 Versioned Request Schema를 Canonical JSON으로 정규화한 뒤 Application Dispatcher가 SHA-256으로 계산한다. 같은 `command_id + request_hash`는 기존 Result를 반환하고 같은 `command_id + 다른 hash`는 Conflict다.
- Local Session이 승인 주체의 기준이며 Browser가 actor identity를 지정하지 않는다.
- Browser가 보낸 Approval·Source Snapshot·Arguments Hash·Idempotency Key를 실행 권위로 사용하지 않는다.

| Endpoint | Request Schema | 핵심 입력 | Domain/Application 매핑 |
|---|---|---|---|
| `POST /api/v1/runs/{run_id}/confirm` | `ConfirmationResponseV1` | `command_id`, `expected_version`, `interrupt_id`, `response_kind`, option 또는 free text | 확인 응답 저장 후 same-thread resume. 임의 resume payload 금지 |
| `POST /api/v1/actions/{action_id}/approve` | `ApproveActionRequestV2` | `command_id`, `expected_version` | 서버가 최신 Action·Source·Policy·Tool Schema에서 Approval Snapshot·ID·Idempotency Key 생성 |
| `POST /api/v1/actions/{action_id}/modify` | `ModifyActionRequestV2` | `command_id`, `expected_version`, 허용된 `arguments_patch` | `ModifyAction`; 기존 ACTIVE Approval revoke |
| `POST /api/v1/actions/{action_id}/reject` | `RejectActionRequestV2` | `command_id`, `expected_version`, optional reason | `RejectAction` |
| `POST /api/v1/actions/{action_id}/prepare-retry` | `PrepareRetryRequestV2` | `command_id`, `expected_version` | `FAILED → MODIFIED`; 새 Approval Metadata는 서버가 이후 생성 |
| `POST /api/v1/runs/{run_id}/cancel` | `CancelRunRequestV2` | `command_id`, `expected_version`, optional reason | `RequestCancel`; Version/Receipt 판정 후에만 child mutation |
| `POST /api/v1/runs/{run_id}/resume` | `ResumeRunRequestV2` | `command_id`, `expected_version`, `resume_kind` | `REAUTH_COMPLETED | SAFE_CHECKPOINT_RESUME | RECOVERY_RECHECK`만 허용. Confirmation/Approval은 전용 Endpoint 사용 |
| `POST /api/v1/runs/{run_id}/resolve-recovery` | `ResolveRecoveryRequestV1` | `command_id`, `expected_version`, `action_id`, `resolution_kind` | Recovery reason별 허용 Enum만 `ResolveRecovery`로 전달 |

공통 오류: Version/Command Hash 충돌은 `409`, Schema·허용 Enum·상태 precondition 위반은 `422`, 필요한 Local Runtime·MCP·Google 상태가 일시적으로 준비되지 않으면 `503`을 사용한다. 실패 응답 자체가 Domain 사실을 임의 변경하지 않는다.

Verification MISMATCH의 `resolution_kind`는 `ACCEPT_PARTIAL | CREATE_CORRECTIVE_PLAN`이다. 일반 취소는 `/cancel`을 사용한다.

### 3.4 SSE 계약

Event 예:

```text
run_status
phase_changed
source_planning
acquisition_progress
context_progress
confirmation_required
analysis_progress
plan_updated
approval_required
action_status
verification_result
reauth_required
recovery_required
completed
error
```

Event 필드:

```text
event_id
run_id
action_id?
occurred_at
event_type
payload
projection_version
schema_version
```

- 연결 단절 시 React는 `Last-Event-ID`로 재연결한다.
- Cursor를 복원할 수 없으면 `GET /api/v1/runs/{run_id}`로 Snapshot을 다시 조회한다.
- SSE 누락 자체를 Workflow 실패로 처리하지 않는다.

## 4. Application·Domain 내부 계약

```text
FastAPI Route
→ Application Command·Query
→ Domain Transition Service
→ Repository 조건부 UPDATE
→ Audit Event
→ Command Result
```

공통 Command Result:

```text
applied
result_code
current_status
current_version
next_allowed_commands
conflict_detail
```

필수 Command:

```text
complete_answer_only_run
publish_read_only_plan
claim_read_action
complete_read_action
finalize_read_action
fail_read_action
approve_action
modify_action
reject_action
refresh_expired_action
claim_action_execution
store_execution_success
mark_execution_failed
mark_unknown_result
recover_existing_result
resolve_as_failed
store_verification
prepare_write_retry
request_cancel
finalize_cancel
```

규칙:

- `applied=false`이면 MCP Write를 호출하지 않는다.
- Mutable Aggregate Command는 `expected_version`을 요구한다.
- 영향 Row가 정확히 1개가 아니면 성공 처리하지 않는다.
- Route와 LangGraph Node는 SQL을 직접 실행하지 않는다.
- LangGraph는 Command Result로 Conditional Edge를 선택한다.

## 5. Agent 내부 인터페이스

Agent는 Parent에 Versioned Structured Output만 반환한다. 다만 Agent Subgraph 내부에는 LLM Node 외에 책임 수행에 필요한 결정적 Validation·Read Application Node가 존재할 수 있다.

```text
RequestIntent
SourceFetchPlan[]
AcquisitionResult
ContextRetrievalResult
WorkAnalysisResult
ActionPlanDraft
PlanReviewResult
```

`RoutingDecision`은 Agent Output이 아니라 결정적 Supervisor의 결과다. Agent는 다음 Agent를 직접 선택·호출하지 않고 자신의 Typed Result와 disposition을 반환한다.

경계:

- API 탐색·수집 Agent의 **LLM Node**는 Source·순서·Budget만 제안한다.
- 실제 Query·Page Token·MCP Arguments는 **같은 Acquisition Subgraph 내부의 결정적 Application Node**가 확정하고 Read Port를 호출한다.
- Acquisition Subgraph는 `SourceFetchPlan[]`과 최종 `AcquisitionResult`를 Parent에 함께 반환한다. Read 중 Subgraph invocation을 종료하지 않는다.
- Context Retriever Agent는 MCP·Google API를 직접 호출하지 않는다.
- Agent 간 대용량 원문 전달 대신 Cache Handle·Resource·Evidence·Segment ID를 사용한다.
- `SINGLE_BASELINE`은 하나의 Unified Agent Subgraph 안에서 요청 이해 → Source 계획 → 결정적 Read → Evidence → 분석 → 계획 → self-review를 수행할 수 있다. 이때 복수 LLM Call이 발생해도 Agent invocation은 1개다.

## 6. MCP 연결

- Transport: `stdio`
- MCP Server는 Local Agent Service가 관리하는 자식 프로세스다.
- MCP Client Adapter가 허용 Tool을 Application Port에 연결한다.
- MCP Server는 LLM·LangGraph·Domain 상태 전이를 포함하지 않는다.
- MCP 종료 시 Local Service가 최대 1회 재시작하고 Tool 목록·Schema Version을 다시 검증한다.
- Write 전달 가능성이 있으면 자동 재전송하지 않고 `UNKNOWN_RESULT`로 전환한다.
- MCP Client Adapter는 실패를 단순 Timeout/Error Name이 아니라 `delivery_certainty`와 함께 반환한다. `NOT_SENT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST`를 사용하며 `NOT_SENT`만 Google 변경이 없다고 확정할 수 있다.

## 7. Gmail Tool

```text
gmail_search_threads
gmail_get_thread
gmail_get_message
gmail_create_draft
gmail_update_draft
gmail_get_draft
gmail_send
```

`gmail_send`는 승인 필수 `SEND` Effect다. 승인된 수신자·CC·제목·본문·Thread Hash와 일치할 때만 실행하며 전달 여부가 불명확하면 자동 재전송하지 않는다. Gmail Message·Thread 삭제 Tool은 등록하지 않는다.

## 8. Tasks Tool

```text
tasks_list_tasklists
tasks_list_tasks
tasks_get_task
tasks_create_task
tasks_update_task
```

`tasks_update_task`는 승인된 완료 상태 변경을 지원한다. Task 삭제 Tool은 등록하지 않는다.

## 9. Calendar Tool

```text
calendar_list_calendars
calendar_list_events
calendar_query_freebusy
calendar_get_event
calendar_create_event
calendar_update_event
calendar_delete_event
```

`calendar_update_event`는 승인된 참석자 추가·수정을 지원한다. `calendar_delete_event`는 승인 필수 DELETE Effect다. 반복 Event 전체 일괄 수정은 등록하지 않는다.

## 10. 내부 결정 인터페이스

다음은 결정적 Python Service로 유지하고 MCP Tool로 공개하지 않는다.

- 날짜·Timezone 정규화
- Source-native Query Compiler
- Metadata 후보 필터·점수·중복 제거
- 가용 Slot 계산
- Event 충돌 검사
- Task 중복 검사
- Resource 관계 연결
- Canonical Arguments 생성과 Hash 계산
- Expected·Actual 정규화·비교
- Verification Diff 생성
- Policy·Approval·Version·Dependency 검증

## 11. Tool 공통 계약

각 Tool은 다음을 정의한다.

- Typed Pydantic Input·Output
- `schema_version`
- Timeout
- Error Enum
- Latency·Request ID
- Effect Type (`READ | CREATE | UPDATE | SEND | DELETE`)
- 허용 Scope
- Retry 가능 여부
- 전달 여부 판정 가능성

Write Tool은 다음 값을 요구한다.

```text
action_id
approval_id
tool_name
canonical_arguments_hash
claim_token
```

브라우저는 Approval Token을 생성하거나 Write Tool을 직접 호출하지 않는다.

## 12. 읽기 Port 계약

```text
list_gmail(query, page_token, page_size)
get_gmail_threads(thread_ids)
list_tasks(filter, page_token, page_size)
get_tasks(task_ids)
list_calendar_events(filter, page_token, page_size)
get_calendar_events(event_ids)
get_freebusy(calendars, time_range)
```

내부 Read Port와 MCP Tool의 고정 매핑:

| 내부 Read Port | MCP Tool |
|---|---|
| `list_gmail` | `gmail_search_threads` |
| `get_gmail_threads` | `gmail_get_thread`, 필요 시 `gmail_get_message` |
| `list_tasks` | `tasks_list_tasks` |
| `get_tasks` | `tasks_get_task` |
| `list_calendar_events` | `calendar_list_events` |
| `get_calendar_events` | `calendar_get_event` |
| `get_freebusy` | `calendar_query_freebusy` |

- 일반 Retrieval 호출은 Action Row를 만들지 않는다.
- 사용자에게 표시·재개가 필요한 명시적 READ Plan만 READ Action 계약을 사용한다.
- READ Action은 Approval·ExecutionAttempt·Verification Row를 만들지 않는다.
- READ Output Schema 실패는 `fail_read_action`으로 `FAILED` 처리한다.

## 13. 승인·실행 계약

- Approval은 Tool Name, Arguments Hash, Action Version, Source Snapshot, Policy Version, Tool Schema Version과 만료 시각을 연결한다.
- 실행 직전 최신 Resource·Hash·Dependency·중복·충돌을 다시 검증한다.
- 만료·원본 변경·Hash 불일치 시 Write를 호출하지 않는다.
- 만료 Action은 `EXPIRED → MODIFIED → 새 승인`을 거친다.
- 기존 Approval을 다시 `ACTIVE`로 만들지 않는다.
- 승인 이후 LLM은 Tool·Arguments·대상 Resource를 변경하지 않는다.

## 14. Answer-only·READ-only 계약

### Answer-only

```text
complete_answer_only_run
ANALYZING | RETRIEVING | PLANNING → COMPLETED
```

Plan·Action 없이 Assistant Message·Trace·Run Terminal을 원자 저장한다.

### READ-only Plan

```text
publish_read_only_plan
Plan DRAFT → ACTIVE
Run → EXECUTING
```

READ 실행:

```text
claim_read_action
complete_read_action
finalize_read_action
fail_read_action
```

## 15. Write 실패·재시도 계약

Write가 Google을 변경하지 않았음이 확실한 경우:

```text
mark_execution_failed
Action EXECUTING → FAILED
Attempt → FAILED
```

재시도 준비:

```text
prepare_write_retry
Action FAILED → MODIFIED
```

필수 조건:

- 새 Approval
- 새 Idempotency Key
- 최신 Source Snapshot
- 새 ExecutionAttempt ID와 새 Approval 내부 `attempt_no = 1`

금지:

```text
FAILED → EXECUTING
UNKNOWN_RESULT → EXECUTING
기존 Approval 재활성화
```

## 16. 검증·UNKNOWN_RESULT 계약

- Write Tool은 Resource ID와 최소 응답 Metadata를 반환한다.
- CREATE·UPDATE·Task 완료·참석자 변경은 대응 GET으로 재조회한다.
- DELETE는 대상 GET의 NOT_FOUND/삭제 상태를 확인한다.
- SEND는 Message/Thread 식별자 또는 결정적 전송 식별자로 Sent 결과를 조회한다.
- 일반 코드가 Effect별 expected·actual을 정규화하고 `VerificationResult`를 만든다.
- `UNKNOWN_RESULT`에서는 새 Attempt·Write를 금지한다.
- CREATE는 Recovery Fingerprint 기반 Resource Search, UPDATE는 GET Target으로 기존 결과를 확인한다.
- `NOT_FOUND` 또는 `ERROR` 한 번만으로 실패를 즉시 확정하지 않는다.

## 17. 오류 Enum

```text
AUTH_EXPIRED
RATE_LIMITED
UPSTREAM_5XX
NOT_FOUND
INVALID_ARGUMENT
POLICY_BLOCKED
APPROVAL_INVALID
VERSION_CONFLICT
DUPLICATE_COMMAND
TIMEOUT
MCP_UNAVAILABLE
LOCAL_SESSION_INVALID
VERIFICATION_MISMATCH
UNKNOWN_RESULT
BUDGET_EXHAUSTED
OUTPUT_SCHEMA_INVALID
```

공통 오류 응답:

```text
error_code
user_message
retryable
current_state
request_id
detail_code?
```

Stack Trace·SQL·Secret은 Frontend에 반환하지 않는다.

## 18. LLM Provider Adapter

공통 인터페이스:

```text
invoke_structured(prompt_ref, input, output_schema, runtime_policy, trace_context)
```

반환:

```text
structured_output
provider
model
actual_runtime
input_tokens
output_tokens
latency_ms
fallback_reason?
```

- `API_ONLY`: API Provider만 활성화한다.
- `LOCAL_CAPABLE`: API Provider와 Ollama Adapter를 포함한다.
- 명시적 `LOCAL_GPU` 실패 시 자동 API 전환을 금지한다.
- `AUTO`는 기술적 실패에서 API fallback 최대 1회다.
- 반환 Trace Metadata에는 `prompt_bundle_version`, `prompt_id`, `prompt_version`, `content_hash`, `agent_role`, `subgraph_name`, `node_name`, `node_state`, `purpose`, `input_schema_version`, `output_schema_version`을 포함하되 Prompt 원문은 포함하지 않는다.

## 19. 08 제공 계약

`08. 시퀀스 설계서`는 본 문서의 Endpoint, Command, Event, Port와 Tool 이름을 사용한다. 다음 흐름을 반드시 포함한다.

- AGENT_SEARCH·RESOURCE_SELECTED
- 추가 수집·사용자 확인
- Answer-only·READ-only·WRITE Plan
- 승인·수정·만료·일부 승인
- Write 실패 재시도
- `UNKNOWN_RESULT` 복구
- OAuth 재인증
- SSE 재연결·앱 재시작
- MCP 장애


---

## 20. 문서 권위 규칙

문서 번호 순서가 아니라 `01 PRD §1.1`의 **Concern Owner 규칙**을 따른다. 이 문서는 자신의 책임 범위만 구체화하며 01-B 안전 정책, 04 Domain·상태 전이, 07 Tool 계약 같은 전문 권위 계약을 완화하지 않는다.


## 21. Health·PromptRef 계약

- 인증 전 최소 상태: `GET /health/live`, `GET /health/ready`
- Local Session 이후 상세 Runtime: `GET /api/v1/runtime`
- LLM Adapter: `invoke_structured(prompt_ref, input, output_schema, runtime_policy, trace_context)`
- PromptRef는 Bundle·ID·Version·Hash·Agent·Subgraph·Node·State·Purpose·Schema Version을 포함한다.
- Prompt 원문은 Trace·Audit·Error Response에 포함하지 않는다.


## 22. 인증 Matrix

| Endpoint | 기존 Local Session | 추가 검증 |
|---|---:|---|
| `GET /health/live` | 없음 | Loopback·Method 제한 |
| `GET /health/ready` | 없음 | Loopback·Launcher 요청 제한 |
| `POST /api/v1/session/bootstrap` | 없음 | 1회용 Bootstrap Secret·TTL·Service Instance |
| OAuth Loopback Callback | 없음 | `state`·PKCE·Listener Instance |
| `GET /api/v1/runtime` | 필수 | Session·Origin·Host |
| 나머지 `/api/v1/*` | 필수 | Session·Origin·Host·Fetch Metadata·Schema |

Bootstrap 오류: `BOOTSTRAP_EXPIRED`, `BOOTSTRAP_REUSED`, `BOOTSTRAP_INSTANCE_MISMATCH`.

## 23. Command Receipt 계약

모든 상태 변경 Endpoint는 다음 Envelope를 사용한다.

```text
command_id: UUID
expected_version: int?
request_schema_version: int
```

Application Dispatcher는 Canonical Request Hash를 생성하고 `command_receipts`와 Domain 변경을 같은 Transaction에 저장한다.

- 동일 ID·동일 Hash·완료: 기존 `CommandResponse` 반환
- 동일 ID·다른 Hash: HTTP 409 `DUPLICATE_COMMAND`
- 다른 ID·오래된 Version: HTTP 409 `VERSION_CONFLICT`

## 24. Local API Schema Catalog

### 24.1 공통

```text
CommandResponseV1
- applied: bool
- result_code: str
- aggregate_id: str?
- current_status: str?
- current_version: int?
- next_allowed_commands: list[str]
- snapshot: object?
- request_id: str

ErrorEnvelopeV1
- error_code: str
- user_message: str
- retryable: bool
- current_state: str?
- request_id: str
- detail_code: str?
```

### 24.2 Run

```text
StartRunRequestV1
- command_id
- conversation_id
- expected_version?
- entry_mode: AGENT_SEARCH | RESOURCE_SELECTED
- user_request: 1..65536 UTF-8
- selected_resources: list[SelectedResourceRefV1], max 20
- requested_mode: AUTO | LOCAL_GPU | API_LLM

StartRunResponseV1
- run_id
- conversation_id
- langgraph_thread_id
- status
- version
- event_stream_url

RunSnapshotResponseV1
- run
- messages
- current_plan?
- actions
- pending_interrupt?
- result_kind: COMPLETE | PARTIAL | NONE
- projection_version
```

### 24.3 Action

```text
ApproveActionRequestV1
- command_id
- expected_version
- approval_scope: ACTION | SYSTEM | PLAN
- acknowledged_warnings: list[str]

ModifyActionRequestV1
- command_id
- expected_version
- arguments: Tool별 Versioned Schema

RejectActionRequestV1
- command_id
- expected_version
- reason_code?
```

### 24.4 Connection·Settings·Operation Endpoint

| Method·Path | 역할 |
|---|---|
| `POST /api/v1/connections/google/start` | MCP Credential Provider OAuth 시작 |
| `GET /api/v1/connections/google/status` | 계정·Scope·연결 상태 |
| `POST /api/v1/connections/google/disconnect` | Revoke 시도·Keyring 삭제 |
| `PUT /api/v1/credentials/llm/{provider}` | API Key 저장·세션 사용 |
| `DELETE /api/v1/credentials/llm/{provider}` | API Key 삭제 |
| `GET/PUT /api/v1/settings` | 비밀 아닌 설정 조회·변경 |
| `POST /api/v1/runtime/mode` | Active Run 없을 때 Mode 변경 |
| `POST /api/v1/backups` | Backup 생성 |
| `POST /api/v1/restore` | Safe Mode Restore 시작 |
| `POST /api/v1/diagnostics/bundles` | Sanitized Bundle 생성 |
| `POST /api/v1/control/shutdown` | Graceful Shutdown 요청 |

## 25. OAuth Credential Port

```text
start_authorization(environment, requested_scopes) -> AuthorizationStartV1
complete_authorization(callback_id, code, state) -> ConnectionMetadataV1
refresh_access(account_id) -> AccessContextHandle
revoke_connection(account_id) -> RevokeResultV1
get_connection_status() -> ConnectionMetadataV1
```

`complete_authorization`와 Refresh Token Keyring I/O는 MCP Credential Provider Process가 수행한다. FastAPI에는 Token 원문 대신 Metadata만 반환한다.

## 26. Claim Token 계약

Claim 성공 후 `ExecutionClaimService`가 다음 Payload를 HMAC-SHA-256으로 보호한다.

```text
version
service_instance_id
action_id
approval_id
execution_attempt_id
tool_name
canonical_arguments_hash
issued_at_ms
expires_at_ms
nonce
```

- TTL 기본 30초, 최대 60초
- Service–MCP 전용 256-bit Session Key는 MCP Child Handshake에서 Process Memory로만 전달
- MCP는 Signature·TTL·Service Instance·Binding·Nonce를 검증
- Nonce는 1회 소비하며 재사용 시 `CLAIM_TOKEN_REUSED`
- Service 또는 MCP 재시작 시 기존 Token 무효
- Token·Session Key는 Log·Trace·Audit·DB·CLI·환경 변수에 저장 금지

## 27. MCP Tool Schema Catalog

공통 Output:

```text
schema_version
request_id
resource_id?
next_page_token?
items?
metadata
```

| Tool | 핵심 Input | Output | Scope | Timeout | Retry |
|---|---|---|---|---:|---|
| `gmail_search_threads` | query<=2048, page_token?, page_size 1..100 | ThreadMetadata[] | gmail.readonly | 30s | Read 429·5xx 1회 |
| `gmail_get_thread` | thread_id | ThreadDetail | gmail.readonly | 30s | Read 1회 |
| `gmail_get_message` | message_id | MessageDetail | gmail.readonly | 30s | Read 1회 |
| `gmail_create_draft` | recipients<=50, subject<=998, body<=65536, thread_id? + claim context | DraftMetadata | gmail.compose | 30s | 전달 불명 시 금지 |
| `gmail_update_draft` | draft_id, mutable fields + claim context | DraftMetadata | gmail.compose | 30s | 전달 불명 시 금지 |
| `gmail_get_draft` | draft_id | DraftDetail | gmail.compose | 30s | Read 1회 |
| `tasks_list_tasklists` | page_token?, page_size | TaskListMetadata[] | tasks | 30s | Read 1회 |
| `tasks_list_tasks` | tasklist_id, filter, page_token?, page_size | TaskMetadata[] | tasks | 30s | Read 1회 |
| `tasks_get_task` | tasklist_id, task_id | TaskDetail | tasks | 30s | Read 1회 |
| `tasks_create_task` | tasklist_id, title, notes?, due? + claim context | TaskMetadata | tasks | 30s | 전달 불명 시 금지 |
| `tasks_update_task` | tasklist_id, task_id, 허용 필드 + claim context | TaskMetadata | tasks | 30s | 전달 불명 시 금지 |
| `calendar_list_calendars` | page_token?, page_size | CalendarMetadata[] | calendarlist.readonly | 30s | Read 1회 |
| `calendar_list_events` | calendar_id, time_min, time_max, query?, page_token? | EventMetadata[] | calendar.events | 30s | Read 1회 |
| `calendar_query_freebusy` | calendar_ids<=20, time_min, time_max | BusyInterval[] | calendar.events.freebusy | 30s | Read 1회 |
| `calendar_get_event` | calendar_id, event_id | EventDetail | calendar.events | 30s | Read 1회 |
| `calendar_create_event` | calendar_id, title, start, end, description? + claim context | EventMetadata | calendar.events | 30s | 전달 불명 시 금지 |
| `calendar_update_event` | calendar_id, event_id, 허용 필드 + claim context | EventMetadata | calendar.events | 30s | 전달 불명 시 금지 |

- 모든 ID·Page Token은 길이 1..2048, 제어문자 금지.
- 날짜·시간은 RFC3339와 명시 Timezone을 사용한다.
- Write Tool의 `claim context`는 Action·Approval·Attempt·Hash·Token을 포함한다.

## 28. Verification·Recovery 계약
- CREATE·UPDATE: GET_COMPARE.
- DELETE: `GET_ABSENT` 정책으로 대상 GET에서 NOT_FOUND/삭제 상태를 확인한다.
- SEND: `SENT_LOOKUP` 정책으로 반환된 Message/Thread 식별자 또는 결정적 전송 식별자를 조회한다.
- SEND 전달 여부가 불명확하면 `UNKNOWN_RESULT`로 전환하고 자동 재전송하지 않는다.
- 모든 외부 MCP/Google 호출은 SQLite Write Transaction 밖에서 수행한다.

## 29. Agent Subgraph 내부 인터페이스

Parent Graph와 Agent Subgraph 사이의 인터페이스는 자유 텍스트 대화가 아니라 Typed Input Projection과 Typed Result로 고정한다.

```text
Parent Graph State
→ AgentInputProjection
→ Agent Subgraph Local State
→ Versioned Typed Result + disposition
→ Parent Graph State update
```

- `AgentInputProjection`은 해당 Role에 필요한 필드와 Resource·Evidence·Segment ID만 포함한다.
- `AgentLocalState`는 invocation 범위 단편 상태이며 장기 Memory가 아니다.
- Agent가 다른 Agent를 직접 호출하는 내부 Port는 제공하지 않는다.
- Agent 내부에서 사용할 수 있는 재호출은 PromptRef 기반 bounded Schema Repair·Semantic Revision에 한정한다.
- Agent Subgraph는 MCP/Google Write Port를 직접 받지 않는다.
- 실제 Google Read가 필요한 Acquisition 경로는 Subgraph 내부에서 `SourceFetchPlan`을 결정적 Query Builder에 넘기고 MCP Read Port를 실행한 뒤, 같은 invocation에서 `AcquisitionResult`까지 확정해 Parent에 반환한다.

## 30. Write Delivery Classification

Write Adapter와 MCP Port는 Error Code와 함께 전달 확실성을 보존한다.

```text
NOT_SENT
MAY_HAVE_BEEN_SENT
SENT_RESPONSE_LOST
```

| 실패 시점 | delivery_certainty | Domain 결과 |
|---|---|---|
| Schema/Policy/Preflight 실패, dispatch 전 process unavailable | `NOT_SENT` | `FAILED` 가능, 자동 Write 재실행은 하지 않고 retry 준비 계약 사용 |
| connect/transport 오류에서 실제 dispatch 여부를 증명할 수 없음 | `MAY_HAVE_BEEN_SENT` | `UNKNOWN_RESULT` |
| request bytes dispatch 후 Timeout | `MAY_HAVE_BEEN_SENT` | `UNKNOWN_RESULT` |
| Provider 5xx에서 미전달 보장이 없음 | `MAY_HAVE_BEEN_SENT` | `UNKNOWN_RESULT` |
| 요청 전달 후 response 유실·connection lost | `SENT_RESPONSE_LOST` | `UNKNOWN_RESULT` |
| MCP process exit가 dispatch 이후일 수 있음 | `MAY_HAVE_BEEN_SENT` | `UNKNOWN_RESULT` |

Exception class 하나만으로 `NOT_SENT`를 추론하지 않는다. `UNKNOWN_RESULT`에서는 기존 결과 GET/Search만 허용하며 새 Attempt·blind resend를 금지한다.
