# 07. Google Work Agent · Tool · MCP · 내부 인터페이스 명세서

> **문서 기준:** `01 PRD v2.11`, `01-A Functional v2.18`, `01-B Policy v2.12`, `02 UI·UX v2.14`, `03 Architecture v3.7`, `04 Domain·DB v1.21 / DB Schema v1.9`, `05 Context·Retrieval v2.13`, `06 Agent·Workflow v7.22`을 기준으로 한다. 외부 공개 API가 아니라 설치된 앱 내부의 Local API, Connector MCP Tool, Python 내부 인터페이스 계약을 정의한다.

## 0. 문서 정보

- **상태:** Draft v2.23
- **기준일:** 2026-08-19
- **대상:** P0 MVP
- **배포 형태:** Windows 설치 파일 기반 로컬 애플리케이션

## 1. 범위

이 문서는 세 가지 인터페이스를 정의한다.

1. React Frontend와 FastAPI Local Agent Service 사이의 Local API
2. Python Application·LangGraph·Domain 사이의 내부 Port·Command 계약
3. FastAPI Local Agent Service가 관리하는 Connector MCP Runtime과 Connector별 MCP Server의 Tool 계약. P0 첫 구현은 Google Workspace MCP Server다.

다음은 제공하지 않는다.

- 인터넷에 공개되는 REST API
- 원격 Backend 또는 SaaS API
- 원격 MCP Server
- React에서 Provider API·SQLite·OS Keyring·MCP를 직접 호출하는 경로
- FastAPI Route·Application·LangGraph·Agent·Domain에서 외부 Provider API/SDK를 직접 호출하는 경로. 외부 업무 시스템 접근은 Connector MCP Runtime/Tool 계약을 공통 경계로 사용한다. P0 Google Workspace Provider API는 Google Workspace MCP Server 내부 Adapter만 호출한다.

## 1.1 Connector 접근 공통 경계

- **Local API**는 React와 FastAPI Local Agent Service 사이의 제품 내부 REST/SSE 인터페이스다. Provider API를 직접 호출하기 위한 우회 경로가 아니다.
- FastAPI Route·Application·LangGraph·Agent·Domain은 `Connector Registry → MCP Client/Port → Connector MCP Server` 계약에만 의존한다.
- 각 Provider API/SDK, Credential 적용, raw token/response 해석은 해당 Connector MCP Server 내부 Adapter가 소유한다.
- Retrieval Read, Connector Browse/Count/Detail, Credential 상태 확인, Write dispatch, Verification/Recovery 조회까지 외부 업무 시스템에 닿는 모든 제품 경로는 Connector MCP Tool/Port를 통과해야 한다.
- 테스트에서는 Connector MCP Client/Transport를 Fake로 대체할 수 있다. 제품 Core에 별도 Provider Client를 주입해 MCP를 우회하는 대체 실행 경로를 두지 않는다.
- P0의 첫 Connector는 `google_workspace`이며 Google Workspace MCP Server가 Gmail·Tasks·Calendar와 Google OAuth/Provider Adapter를 소유한다. MCP Server 내부 Provider API 호출은 Connector 구현 세부사항이며 관측 지표는 `connector_id + provider_api_call_count`로 기록한다.

## 2. 설치·Runtime 경계

```text
Windows Installer
→ Launcher
→ FastAPI Local Agent Service
   ├─ React 정적 Build 제공
   ├─ REST·SSE 제공
   ├─ Application·LangGraph 실행
   └─ Connector MCP Runtime
      └─ Google Workspace MCP Server (P0 registered Connector)
```

- 사용자는 Python, Node.js, npm, Vite를 별도로 설치하지 않는다.
- 운영 Runtime에서 Vite 개발 서버를 실행하지 않는다.
- Local Service는 `127.0.0.1`의 동적 포트에만 바인딩한다.
- Launcher가 Local Service 시작·Health Check·브라우저 열기·종료를 관리한다.
- Connector MCP Runtime 계약은 여러 `connector_id` 등록을 허용하지만 P0 설치 Artifact에 포함되는 Connector MCP Server는 Google Workspace 하나다.

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

<table fit-page-width="true" header-row="true">
	<tr>
		<td>구분</td>
		<td>Method·Path</td>
		<td>역할</td>
	</tr>
	<tr>
		<td>Liveness</td>
		<td>`GET /health/live`</td>
		<td>FastAPI Process 응답 여부</td>
	</tr>
	<tr>
		<td>Core Readiness</td>
		<td>`GET /health/ready`</td>
		<td>Manifest·Asset·API Contract·SQLite·Migration·Domain·Keyring Adapter·MCP Executable·Tool Schema</td>
	</tr>
	<tr>
		<td>Runtime Detail</td>
		<td>`GET /api/v1/runtime`</td>
		<td>Local Session 이후 Google Credential·Scope·LLM Provider·Ollama·Model·Recovery 상태</td>
	</tr>
	<tr>
		<td>Session</td>
		<td>`POST /api/v1/session/bootstrap`</td>
		<td>Launcher Bootstrap으로 Local Session 수립</td>
	</tr>
	<tr>
		<td>Conversation</td>
		<td>`GET/POST /api/v1/conversations`</td>
		<td>대화 조회·생성</td>
	</tr>
	<tr>
		<td>Run</td>
		<td>`POST /api/v1/runs`, `GET /api/v1/runs/{run_id}`</td>
		<td>요청 시작·현재 Domain 상태 조회</td>
	</tr>
	<tr>
		<td>Interrupt</td>
		<td>`POST /api/v1/runs/{run_id}/confirm`</td>
		<td>확인 질문 응답으로 Graph 재개</td>
	</tr>
	<tr>
		<td>Approval</td>
		<td>`POST /api/v1/actions/{action_id}/approve\|modify\|reject`</td>
		<td>승인·수정·거절 Command</td>
	</tr>
	<tr>
		<td>Retry</td>
		<td>`POST /api/v1/actions/{action_id}/prepare-retry`</td>
		<td>실패한 Write를 `MODIFIED`로 전환해 새 승인 준비</td>
	</tr>
	<tr>
		<td>Control</td>
		<td>`POST /api/v1/runs/{run_id}/cancel\|resume`</td>
		<td>취소 요청·안전 지점 재개</td>
	</tr>
	<tr>
		<td>Resource</td>
		<td>`GET /api/v1/resources/gmail\|tasks\|calendar`</td>
		<td>Sidebar 목록·검색·opaque Local API continuation 조회</td>
	</tr>
	<tr>
		<td>Gmail Detail</td>
		<td>`GET /api/v1/resources/gmail/{resource_id}`</td>
		<td>Local Session으로 Gmail Thread의 최신 Message UI 상세 조회</td>
	</tr>
	<tr>
		<td>Event</td>
		<td>`GET /api/v1/runs/{run_id}/events`</td>
		<td>SSE 진행 Projection</td>
	</tr>
</table>

#### Gmail UI Detail Projection

`GET /api/v1/resources/gmail/{resource_id}`는 Sidebar의 `gmail_thread` ID를 받아 해당 Thread에서 `internalDate` 기준 최신 Message 1개를 표시한다. 응답은 `resource_id`, `message_id`, `sender_name`, `sender_email`, `recipients`, `cc`, `subject`, `received_at`, `body`, `attachments`, `canonical_url`을 포함한다. 본문은 `text/plain`을 우선하고 HTML만 있으면 안전한 readable text로 변환하며 raw HTML을 Browser에 전달하지 않는다.

`canonical_url`의 Gmail P0 의미: RFC822 Message-ID가 있으면 `rfc822msgid:` 기반 Gmail 검색 URL이고, 없으면 Gmail All Mail 목록 fallback이다. Gmail REST `thread_id`/`message_id`로 구성한 direct-open hash URL(`#inbox/{id}`, `#all/{id}` 등)은 cold click에서 신뢰할 수 없어 사용하지 않는다. `canonical_url`은 direct Thread permalink를 보장하지 않는다.

이 계산을 위해 내부 MCP Gmail UI Detail 계약(`GmailThreadDetail`)은 `format=full` 응답에서 프로젝션한 RFC822 `Message-ID` header를 `rfc822_message_id`로 추가 전달한다. 이 필드는 MCP/Port 내부 계약에만 존재하며 위 API response schema(`GmailResourceDetailResponse`)에는 노출하지 않는다.

이 Endpoint는 UI 전용 Application Query다. `gmail_get_thread`, `gmail_get_message`, Agent Context, Retrieval Workflow와 `selected_resources` 계약을 변경하지 않는다.

### 3.2.1 Sidebar Resource Browse·Count 계약

- Gmail·Tasks UI visible page는 `SIDEBAR_PAGE_SIZE=20`이며 Agent Retrieval `RETRIEVAL_PAGE_SIZE=20`과 별도다. Calendar Month View는 visible grid 전체를 materialize하고 numeric pagination을 사용하지 않는다.
- `ResourceListResponse.next_page_token`은 Client 관점의 opaque Local API continuation이다. Frontend는 이를 Google Provider token이나 UI page number로 해석하지 않고 다음 Local API 요청에 그대로 전달한다. Provider raw token은 Adapter 내부 구현 세부사항이다.
- Gmail Browse는 기본 `page_size=20`이고 optional `include_thread_metadata`의 기본값은 `true`다. 아직 표시하지 않을 intermediate page를 통과할 때만 `false`를 사용해 Thread ID/list metadata/continuation만 확보하고 visible target page는 metadata를 hydrate한다. target hydration 중 필요한 Provider Read 하나라도 실패하면 partial placeholder page를 만들지 않고 해당 page Read를 실패 처리한다.
- Gmail 기본 Sidebar scope는 `INBOX + PRIMARY` Thread이며 exact badge count도 같은 scope다. Sidebar 검색은 Primary 제한 없이 일반 mailbox를 검색하되 Spam·Trash를 제외하고 기본 Gmail badge count는 유지한다. Count traversal은 body/attachment/detail N+1 없이 필요한 최소 list metadata만 사용한다.
- Tasks 기본 Browse는 configured/default Task List에 `show_completed=false`, `show_hidden=false`, `show_deleted=false`, Provider `page_size<=100`을 사용한다. Application은 Task metadata batch와 opaque continuation을 반환하고 React Client Session Cache가 이를 UI 20개 page로 slice한다. 100개와 continuation이 있으면 초기에는 1..5 page만 알고, 알려진 마지막 page에서만 다음 batch를 append한다. terminal 뒤 누적 수로 exact total과 마지막 UI page를 확정한다. `tasks.get`은 focus/선택 detail에만 사용한다.
- Tasks `status_scope=incomplete|completed`를 지원하고 기본은 `incomplete`다. completed materialization은 `show_completed=true`, `show_hidden=true`, `show_deleted=false`, `page_size<=100`으로 terminal까지 읽은 뒤 mixed Provider 결과에서 `task_status=completed`만 `resource_id` 기준 dedupe한다. raw Google `completed` timestamp는 존재할 때 `completed_at` metadata로 보존한다.
- Calendar Month Browse는 `monthAnchor`에서 계산한 configured timezone의 explicit `[gridStart, gridEnd)`와 `singleEvents=true`를 사용하며 Provider `page_size<=100`을 terminal까지 순회한다. `time_min/time_max`가 생략된 일반 Upcoming Browse는 configured timezone 기준 현재 시각부터 90일 후까지의 bounded default window를 사용한다.
- Exact Count Read는 Browse와 독립된 Local API Query다. P0 Sidebar startup은 Gmail exact count와 Tasks incomplete 첫 batch만 준비하며 Tasks badge는 그 batch의 terminal/continuation 상태에서 계산한다. Calendar tab에는 numeric badge가 없고 startup·Calendar refresh에서 Calendar Count Read를 호출하지 않는다. Count 실패·timeout은 Browse를 실패시키지 않고 numeric badge만 생략한다.
- React Client Session Cache identity는 active Google `account_id`, source, container(Task List/Calendar), 검색/filter/sort/status scope, continuation/batch generation으로 구성한다. raw Local Session Cookie/token과 OAuth token은 Application snapshot이나 cache key로 전달하지 않는다. Refresh·계정/container/scope/검색/filter/sort 변경·session 종료는 관련 cache를 무효화한다.

### 3.3 상태 변경 API 입력 소유권

브라우저는 사용자 의도와 낙관적 동시성에 필요한 값만 보낸다. Domain 권위 Metadata는 Application이 현재 Domain 상태에서 생성·검증한다.

- Client 입력 허용: `command_id`, 대상 ID, `expected_version`, 사용자 선택·텍스트·수정하려는 허용 필드.
- Server 생성·검증: `request_hash`, `approval_id`, Write `idempotency_key`, `source_snapshot`, 승인 주체 식별, `canonical_arguments_hash`, `claim_token`.
- `request_hash`는 수신 JSON을 그대로 Hash하지 않고 Endpoint별 Versioned Request Schema를 Canonical JSON으로 정규화한 뒤 Application Dispatcher가 SHA-256으로 계산한다. 같은 `command_id + request_hash`는 기존 Result를 반환하고 같은 `command_id + 다른 hash`는 Conflict다.
- Local Session이 승인 주체의 기준이며 Browser가 actor identity를 지정하지 않는다.
- Browser가 보낸 Approval·Source Snapshot·Arguments Hash·Idempotency Key를 실행 권위로 사용하지 않는다.

<table fit-page-width="true" header-row="true">
	<tr>
		<td>Endpoint</td>
		<td>Request Schema</td>
		<td>핵심 입력</td>
		<td>Domain/Application 매핑</td>
	</tr>
	<tr>
		<td>`POST /api/v1/runs/{run_id}/confirm`</td>
		<td>`ConfirmationResponseV1`</td>
		<td>`command_id`, `expected_version`, `interrupt_id`, `response_kind`, option 또는 free text</td>
		<td>`interrupt_id`가 가리키는 `owner_subgraph + RegisteredResumeTargetRefV1` checkpoint에서 same-thread resume. `resume_target`은 compiled Graph Registry가 발급·검증하며 LLM 자유 문자열로 수신하지 않는다. 모든 확인을 Request Understanding으로 되돌리는 공통 재시작 금지</td>
	</tr>
	<tr>
		<td>`POST /api/v1/actions/{action_id}/approve`</td>
		<td>`ApproveActionRequestV2`</td>
		<td>`command_id`, `expected_version`</td>
		<td>서버가 최신 Action·Source·Policy·Tool Schema에서 Approval Snapshot·ID·Idempotency Key 생성</td>
	</tr>
	<tr>
		<td>`POST /api/v1/actions/{action_id}/modify`</td>
		<td>`ModifyActionRequestV2`</td>
		<td>`command_id`, `expected_version`, 허용된 `arguments_patch`</td>
		<td>`ModifyAction`; 기존 ACTIVE Approval revoke</td>
	</tr>
	<tr>
		<td>`POST /api/v1/actions/{action_id}/reject`</td>
		<td>`RejectActionRequestV2`</td>
		<td>`command_id`, `expected_version`, optional reason</td>
		<td>`RejectAction`</td>
	</tr>
	<tr>
		<td>`POST /api/v1/actions/{action_id}/prepare-retry`</td>
		<td>`PrepareRetryRequestV2`</td>
		<td>`command_id`, `expected_version`</td>
		<td>`FAILED → MODIFIED`; 새 Approval Metadata는 서버가 이후 생성</td>
	</tr>
	<tr>
		<td>`POST /api/v1/runs/{run_id}/cancel`</td>
		<td>`CancelRunRequestV2`</td>
		<td>`command_id`, `expected_version`, optional reason</td>
		<td>`RequestCancel`; Version/Receipt 판정 후에만 child mutation</td>
	</tr>
	<tr>
		<td>`POST /api/v1/runs/{run_id}/resume`</td>
		<td>`ResumeRunRequestV2`</td>
		<td>`command_id`, `expected_version`, `resume_kind`</td>
		<td>`REAUTH_COMPLETED</td>
	</tr>
	<tr>
		<td>`POST /api/v1/runs/{run_id}/resolve-recovery`</td>
		<td>`ResolveRecoveryRequestV1`</td>
		<td>`command_id`, `expected_version`, `action_id`, `resolution_kind`</td>
		<td>Recovery reason별 허용 Enum만 `ResolveRecovery`로 전달</td>
	</tr>
</table>

공통 오류: Version/Command Hash 충돌은 `409`, Schema·허용 Enum·상태 precondition 위반은 `422`, 필요한 Local Runtime·MCP·Google 상태가 일시적으로 준비되지 않으면 `503`을 사용한다. 실패 응답 자체가 Domain 사실을 임의 변경하지 않는다.

Verification MISMATCH의 `resolution_kind`는 `ACCEPT_PARTIAL | CREATE_CORRECTIVE_PLAN`이다. 일반 취소는 `/cancel`을 사용한다.

### 3.4 SSE 계약

Event 예:

```text
run_status
phase_changed
tool_routing
retrieval_progress
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
start_run
start_analysis
begin_retrieval
begin_planning
request_confirmation
resume_confirmation
complete_answer_only_run
publish_plan
publish_read_only_plan
block_run
claim_read_action
complete_read_action
finalize_read_action
fail_read_action
approve_action
modify_action
reject_action
expire_approval
refresh_expired_action
claim_action_execution
store_execution_success
mark_execution_failed
mark_unknown_result
recover_existing_result
resolve_as_failed
store_verification
begin_verification
complete_write_run
prepare_write_retry
request_cancel
cancel_pending_action
finalize_cancel
require_reauth
resume_after_reauth
require_recovery
resolve_recovery
```

규칙:

- `applied=false`이면 MCP Write를 호출하지 않는다.
- Mutable Aggregate Command는 `expected_version`을 요구한다.
- 영향 Row가 정확히 1개가 아니면 성공 처리하지 않는다.
- Route와 LangGraph Node는 SQL을 직접 실행하지 않는다.
- LangGraph는 Command Result로 Conditional Edge를 선택한다.

## 5. Agent 내부 인터페이스

`ToolRoutePlanV2`는 `InputRoutePlanV1`과 `OutputPlanV1`을 분리해 독립 revision/freshness 단위로 관리한다. OUT-only 변경은 기존 Retrieval을 자동 stale 처리하지 않고 Planning/Review만 재생성한다.

Main Graph와 Agent Subgraph는 Versioned Typed State로 연결한다. Main State는 공식 결과만 누적하고 Subgraph 내부 Query candidate·LLM candidate·RAG score는 Local State 또는 Run Cache에 둔다.

```text
RunInputV1
RequestIntentV2
ToolRoutePlanV2
RetrievalResultV1
WorkAnalysisResultV2
AnswerDraftV2 | ActionPlanDraftV2
PlanReviewResultV2
```

`RoutingDecision`은 Agent Output이 아니라 결정적 Supervisor의 결과다. Agent는 다음 Agent를 직접 선택·호출하지 않고 `SubgraphReturnV2(typed_result, disposition, workflow_signal)`을 반환한다.

경계:

- Tool Route Subgraph가 IN Resource/Connector/허용 Read Tool 범위와 OUT Resource/Effect/Tool을 한 번 확정한다.
- Tool ID·Scope·Effect·Schema Version 결합은 Signed Tool Registry를 기준으로 수행한다.
- Tool Route LLM은 먼저 IN/OUT Resource·Effect만 판단하고, Registry 후보 결합은 결정적 코드가 수행한다. 후보가 여러 개일 때만 Route Subgraph 내부 선택 Node를 사용한다.
- Retrieval Subgraph는 `ToolRoutePlanV2.input_plan.input_routes`를 읽고 그 안의 `allowed_read_tool_ids`만 사용한다. Connector/Tool 종류를 LLM이 다시 선택하지 않는다.
- 실제 Query·Page Token·MCP Arguments는 Retrieval Subgraph의 결정적 Application Node가 확정하고 Read Port를 호출한다.
- Retrieval은 Query→Read→Normalize/Segment→Run-scoped RAG→Evidence→Sufficiency를 완료한 뒤 `RetrievalResultV1`과 필요한 Typed `WorkflowSignalV1`만 Parent에 반환한다.
- Planning Subgraph는 `ToolRoutePlanV2.output_plan.output_routes`의 `selected_tool_id`를 소비하며 Tool을 재선택하지 않는다. Tool별 Arguments만 작성하고 결정적 Assembler가 `ActionPlanDraftV2`를 만든다.
- Agent 간 대용량 원문 전달 대신 Cache Handle·Resource·Evidence·Segment ID를 사용한다.
- `SINGLE_BASELINE`은 동일 의미 책임을 Unified Subgraph 안에서 수행할 수 있으나 Main/Local State와 Tool Route 단일 권위 계약은 동일하다.


### PolicyPreconditionResolver · Confirmation Receipt Interface
- 의미 Route 후보 뒤 결정적 Resolver가 `TASK + CREATE → Tasks duplicate READ`, `CALENDAR + CREATE → Event/FreeBusy conflict READ`를 보강한다.
- 사용자의 명시적 Source·기간·Resource 범위를 벗어나면 `SCOPE_EXPANSION_REQUIRED` Confirmation을 반환하고 승인 전에는 Route를 materialize/execute하지 않는다.
- 실제 사용자 응답을 검증한 Application/Confirmation Controller만 `PolicyConfirmationReceiptV1`을 생성한다. Agent·LLM·MCP는 Receipt 생성 권한이 없다.
- `DUPLICATE_OVERRIDE`/`CONFLICT_OVERRIDE` Write는 WorkAnalysis receipt refs와 Approval Snapshot의 receipt ID/context hash가 일치해야 하며 Preflight에서 stale/DECLINED/missing Receipt를 차단한다. Receipt 자체는 MCP Write Payload에 넣지 않고 Application이 Claim 발급 전에 검증한다.


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
tasks_delete_task
```

`tasks_update_task`는 승인된 완료 상태 변경을 지원한다. `tasks_delete_task`는 정확한 Task ID를 대상으로 하는 승인형 `DELETE`이며 Claim V2 검증 후 실행하고 `GET_ABSENT`로 대상 부재를 검증한다.

Google Tasks Adapter의 raw `due`는 제품 내부 `scheduled_date`의 Provider 매핑값이다. 현재 Tool Schema의 `due?` 표기는 Google API 경계의 raw argument이며, Local API·Application·UI Projection은 `scheduled_date`와 정규화된 `task_status`를 소비하도록 후속 구현에서 정합해야 한다. `business_deadline`은 Google Task Write의 구조화 Argument가 아니며 `due`로 자동 매핑하지 않는다. Task 시간 구간도 현재 Tool 계약의 필드가 아니다.

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

<table fit-page-width="true" header-row="true">
	<tr>
		<td>내부 Read Port</td>
		<td>MCP Tool</td>
	</tr>
	<tr>
		<td>`list_gmail`</td>
		<td>`gmail_search_threads`</td>
	</tr>
	<tr>
		<td>`get_gmail_threads`</td>
		<td>`gmail_get_thread`, 필요 시 `gmail_get_message`</td>
	</tr>
	<tr>
		<td>`list_tasks`</td>
		<td>`tasks_list_tasks`</td>
	</tr>
	<tr>
		<td>`get_tasks`</td>
		<td>`tasks_get_task`</td>
	</tr>
	<tr>
		<td>`list_calendar_events`</td>
		<td>`calendar_list_events`</td>
	</tr>
	<tr>
		<td>`get_calendar_events`</td>
		<td>`calendar_get_event`</td>
	</tr>
	<tr>
		<td>`get_freebusy`</td>
		<td>`calendar_query_freebusy`</td>
	</tr>
</table>

### 12.1 Retrieval continuation 경계

- List Read 결과의 Provider-native `next_page_token`은 Core public state로 승격하지 않는다. Application의 결정적 Retrieval Read Node가 해당 결과를 **Run Retrieval Cache read-result entry**에 memory-only로 보관하고 Retrieval Local State에는 `read_result_handle`만 반환한다.
- `NEXT_PAGE` 호출은 Application의 결정적 Retrieval Read Node가 `read_result_handle`을 resolve한 뒤 `run_id + route_id + query identity/hash`가 현재 frozen IN Route와 일치하고 continuation이 미소진임을 검증한 경우에만 raw token을 해당 Connector MCP Read Argument에 전달한다.
- unknown handle, cross-run handle, route/query mismatch, exhausted continuation은 MCP/Provider 호출 전에 fail-closed한다.
- raw Provider continuation은 Main State·LangGraph Checkpoint·Domain DB·Prompt·Trace·Audit에 저장하거나 노출하지 않는다. Trace에는 11 Observability가 허용한 안전 hash/상태 metadata만 남긴다.
- Sidebar Local API continuation과 Agent Retrieval continuation은 서로 다른 계약이다. Sidebar continuation은 Frontend용 opaque Local API token이고, Agent Retrieval continuation은 Run Retrieval Cache 내부 handle로만 소비한다.

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

<table fit-page-width="true" header-row="true">
	<tr>
		<td>Endpoint</td>
		<td>기존 Local Session</td>
		<td>추가 검증</td>
	</tr>
	<tr>
		<td>`GET /health/live`</td>
		<td>없음</td>
		<td>Loopback·Method 제한</td>
	</tr>
	<tr>
		<td>`GET /health/ready`</td>
		<td>없음</td>
		<td>Loopback·Launcher 요청 제한</td>
	</tr>
	<tr>
		<td>`POST /api/v1/session/bootstrap`</td>
		<td>없음</td>
		<td>1회용 Bootstrap Secret·TTL·Service Instance</td>
	</tr>
	<tr>
		<td>OAuth Loopback Callback</td>
		<td>없음</td>
		<td>`state`·PKCE·Listener Instance</td>
	</tr>
	<tr>
		<td>`GET /api/v1/runtime`</td>
		<td>필수</td>
		<td>Session·Origin·Host</td>
	</tr>
	<tr>
		<td>나머지 `/api/v1/*`</td>
		<td>필수</td>
		<td>Session·Origin·Host·Fetch Metadata·Schema</td>
	</tr>
</table>

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

<table fit-page-width="true" header-row="true">
	<tr>
		<td>Method·Path</td>
		<td>역할</td>
	</tr>
	<tr>
		<td>`POST /api/v1/connections/google/start`</td>
		<td>MCP Credential Provider OAuth 시작</td>
	</tr>
	<tr>
		<td>`GET /api/v1/connections/google/status`</td>
		<td>계정·Scope·연결 상태</td>
	</tr>
	<tr>
		<td>`POST /api/v1/connections/google/disconnect`</td>
		<td>Revoke 시도·Keyring 삭제</td>
	</tr>
	<tr>
		<td>`PUT /api/v1/credentials/llm/{provider}`</td>
		<td>API Key 저장·세션 사용</td>
	</tr>
	<tr>
		<td>`DELETE /api/v1/credentials/llm/{provider}`</td>
		<td>API Key 삭제</td>
	</tr>
	<tr>
		<td>`GET/PUT /api/v1/settings`</td>
		<td>비밀 아닌 설정 조회·변경</td>
	</tr>
	<tr>
		<td>`POST /api/v1/runtime/mode`</td>
		<td>Active Run 없을 때 Mode 변경</td>
	</tr>
	<tr>
		<td>`POST /api/v1/backups`</td>
		<td>Backup 생성</td>
	</tr>
	<tr>
		<td>`POST /api/v1/restore`</td>
		<td>Safe Mode Restore 시작</td>
	</tr>
	<tr>
		<td>`POST /api/v1/diagnostics/bundles`</td>
		<td>Sanitized Bundle 생성</td>
	</tr>
	<tr>
		<td>`POST /api/v1/control/shutdown`</td>
		<td>Graceful Shutdown 요청</td>
	</tr>
</table>

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
total_count?
metadata
```

<table fit-page-width="true" header-row="true">
	<tr>
		<td>Tool</td>
		<td>핵심 Input</td>
		<td>Output</td>
		<td>Scope</td>
		<td>Timeout</td>
		<td>Retry</td>
	</tr>
	<tr>
		<td>`gmail_search_threads`</td>
		<td>query<=2048, page_token?, page_size 1..100</td>
		<td>ThreadMetadata[]</td>
		<td>gmail.readonly</td>
		<td>30s</td>
		<td>Read 429·5xx 1회</td>
	</tr>
	<tr>
		<td>`gmail_get_thread`</td>
		<td>thread_id</td>
		<td>ThreadDetail</td>
		<td>gmail.readonly</td>
		<td>30s</td>
		<td>Read 1회</td>
	</tr>
	<tr>
		<td>`gmail_get_message`</td>
		<td>message_id</td>
		<td>MessageDetail</td>
		<td>gmail.readonly</td>
		<td>30s</td>
		<td>Read 1회</td>
	</tr>
	<tr>
		<td>`gmail_create_draft`</td>
		<td>recipients<=50, subject<=998, body<=65536, thread_id? + claim context</td>
		<td>DraftMetadata</td>
		<td>gmail.compose</td>
		<td>30s</td>
		<td>전달 불명 시 금지</td>
	</tr>
	<tr>
		<td>`gmail_update_draft`</td>
		<td>draft_id, mutable fields + claim context</td>
		<td>DraftMetadata</td>
		<td>gmail.compose</td>
		<td>30s</td>
		<td>전달 불명 시 금지</td>
	</tr>
	<tr>
		<td>`gmail_get_draft`</td>
		<td>draft_id</td>
		<td>DraftDetail</td>
		<td>gmail.compose</td>
		<td>30s</td>
		<td>Read 1회</td>
	</tr>
	<tr>
		<td>`tasks_list_tasklists`</td>
		<td>page_token?, page_size</td>
		<td>TaskListMetadata[]</td>
		<td>tasks</td>
		<td>30s</td>
		<td>Read 1회</td>
	</tr>
	<tr>
		<td>`tasks_list_tasks`</td>
		<td>tasklist_id, filter, page_token?, page_size</td>
		<td>TaskMetadata[] + exact `total_count` when requested by Sidebar</td>
		<td>tasks</td>
		<td>30s</td>
		<td>Read 1회</td>
	</tr>
	<tr>
		<td>`tasks_get_task`</td>
		<td>tasklist_id, task_id</td>
		<td>TaskDetail</td>
		<td>tasks</td>
		<td>30s</td>
		<td>Read 1회</td>
	</tr>
	<tr>
		<td>`tasks_create_task`</td>
		<td>tasklist_id, title, notes?, due? + claim context</td>
		<td>TaskMetadata</td>
		<td>tasks</td>
		<td>30s</td>
		<td>전달 불명 시 금지</td>
	</tr>
	<tr>
		<td>`tasks_update_task`</td>
		<td>tasklist_id, task_id, 허용 필드 + claim context</td>
		<td>TaskMetadata</td>
		<td>tasks</td>
		<td>30s</td>
		<td>전달 불명 시 금지</td>
	</tr>
	<tr>
		<td>`calendar_list_calendars`</td>
		<td>page_token?, page_size</td>
		<td>CalendarMetadata[]</td>
		<td>calendarlist.readonly</td>
		<td>30s</td>
		<td>Read 1회</td>
	</tr>
	<tr>
		<td>`calendar_list_events`</td>
		<td>calendar_id, time_min, time_max, query?, page_token?</td>
		<td>EventMetadata[] + exact `total_count` when requested by Sidebar</td>
		<td>calendar.events</td>
		<td>30s</td>
		<td>Read 1회</td>
	</tr>
	<tr>
		<td>`calendar_query_freebusy`</td>
		<td>calendar_ids<=20, time_min, time_max</td>
		<td>BusyInterval[]</td>
		<td>calendar.events.freebusy</td>
		<td>30s</td>
		<td>Read 1회</td>
	</tr>
	<tr>
		<td>`calendar_get_event`</td>
		<td>calendar_id, event_id</td>
		<td>EventDetail</td>
		<td>calendar.events</td>
		<td>30s</td>
		<td>Read 1회</td>
	</tr>
	<tr>
		<td>`calendar_create_event`</td>
		<td>calendar_id, title, start, end, description? + claim context</td>
		<td>EventMetadata</td>
		<td>calendar.events</td>
		<td>30s</td>
		<td>전달 불명 시 금지</td>
	</tr>
	<tr>
		<td>`calendar_update_event`</td>
		<td>calendar_id, event_id, 허용 필드 + claim context</td>
		<td>EventMetadata</td>
		<td>calendar.events</td>
		<td>30s</td>
		<td>전달 불명 시 금지</td>
	</tr>
</table>

- 모든 ID·Page Token은 길이 1..2048, 제어문자 금지.
- 날짜·시간은 RFC3339와 명시 Timezone을 사용한다.
- Write Tool의 `claim context`는 Action·Approval·Attempt·Hash·Token을 포함한다.
- `tasks_create_task`의 raw `due?`는 Google Adapter 경계에서만 `scheduled_date`와 대응한다. `business_deadline`·작업 시간은 새 Task Tool Argument로 추가하지 않으며, 업무 마감 의미 보존은 승인된 `notes`와 Evidence·Approval Projection을 따른다.

### 27.1 Sidebar Query Projection 계약

- Gmail·Tasks visible UI page size는 `SIDEBAR_PAGE_SIZE=20`이다. Agent Retrieval `RETRIEVAL_PAGE_SIZE=20`과 숫자는 같지만 독립 계약이다. Calendar Month View는 visible grid를 materialize하며 numeric pagination을 사용하지 않는다.
- Local API `next_page_token`은 opaque continuation이다. Frontend는 Provider raw token이나 page number로 해석하지 않는다.
- Tasks Sidebar 기본 범위는 **미완료 Task 전체**이며 Provider batch는 최대 100개, UI는 20개씩 slice한다. 완료 Task는 사용자가 완료 상태 필터를 명시한 경우에만 별도 materialize한다.
- Calendar Month Browse는 visible grid의 explicit `[gridStart, gridEnd)`를 사용한다. 일반 Upcoming Browse는 사용자 Timezone 기준 현재부터 90일까지 bounded window를 사용한다.
- Gmail exact badge는 기본 `INBOX + PRIMARY` scope에서 실제 exact count가 확정된 경우만 표시한다. Provider 추정치를 exact로 승격하지 않는다. Tasks badge는 incomplete batch의 terminal/continuation 상태에서 계산하고 terminal 도달 시 exact total을 확정한다. **Calendar tab에는 numeric badge가 없고 startup·Calendar refresh에서 Calendar Count Read를 호출하지 않는다.**
- Frontend가 exact count를 만들기 위해 전체 Page를 순회하거나 hard-code하지 않는다. 필요한 Count Query는 Local API/Application이 MCP Read Tool 경계를 통해 수행한다.

## 28. Verification·Recovery 계약
- CREATE·UPDATE: GET_COMPARE.
- DELETE: `GET_ABSENT` 정책으로 대상 GET에서 NOT_FOUND/삭제 상태를 확인한다.
- SEND: `SENT_LOOKUP` 정책으로 반환된 Message/Thread 식별자 또는 결정적 전송 식별자를 조회한다.
- SEND 전달 여부가 불명확하면 `UNKNOWN_RESULT`로 전환하고 자동 재전송하지 않는다.
- 모든 외부 MCP Tool·MCP 내부 Google Provider 호출은 SQLite Write Transaction 밖에서 수행한다.

## 29. Agent Subgraph 내부 인터페이스

Parent Graph와 Agent Subgraph 사이의 인터페이스는 자유 텍스트 대화가 아니라 Typed Input Projection과 Typed Result로 고정한다.

```text
Main Graph Typed State
→ Subgraph Input Projection
→ Subgraph Typed Local State
→ Node별 최소 Projection
→ Versioned Typed Result + disposition + optional WorkflowSignal
→ Main Graph State update
```

- Main State의 공식 Artifact Owner는 `Request → Tool Route → Retrieval → Work Analysis → Planning → Review` 순서로 고정한다.
- Subgraph Input Projection은 해당 Role에 필요한 Main State 필드만 포함한다.
- Subgraph 내부에서도 Node마다 입력 계약이 다르다. 예: Query Planner는 `request_intent + input_routes`, Evidence Selector는 `request_intent + ranked_segments`, Planning Argument Writer는 `output_route + work_analysis + evidence_refs`만 받는다.
- 공통 Runtime Envelope와 업무 Local State를 분리한다. 범용 `dict` 하나에 모든 후보를 몰지 않는다.
- Agent가 다른 Agent를 직접 호출하는 내부 Port는 제공하지 않는다.
- Agent Subgraph는 MCP/Google Write Port를 직접 받지 않는다.
- Retrieval Subgraph만 검증된 MCP Read Port를 사용하며 `ToolRoutePlanV2.input_plan.input_routes[].allowed_read_tool_ids` 밖의 Tool 호출은 거절한다.
- Planning Subgraph는 `output_routes[].selected_tool_id`를 그대로 사용하며 다른 Tool을 제안할 수 없다.
- 앞 단계 State 수정이 필요하면 `ROUTE_RECONSIDERATION_REQUIRED`, `RETRIEVE_MORE` 같은 disposition을 반환하고 Main Supervisor가 Back-edge를 선택한다.

## 30. Write Delivery Classification

Write Adapter와 MCP Port는 Error Code와 함께 전달 확실성을 보존한다.

```text
NOT_SENT
MAY_HAVE_BEEN_SENT
SENT_RESPONSE_LOST
```

<table fit-page-width="true" header-row="true">
	<tr>
		<td>실패 시점</td>
		<td>delivery_certainty</td>
		<td>Domain 결과</td>
	</tr>
	<tr>
		<td>Schema/Policy/Preflight 실패, dispatch 전 process unavailable</td>
		<td>`NOT_SENT`</td>
		<td>`FAILED` 가능, 자동 Write 재실행은 하지 않고 retry 준비 계약 사용</td>
	</tr>
	<tr>
		<td>connect/transport 오류에서 실제 dispatch 여부를 증명할 수 없음</td>
		<td>`MAY_HAVE_BEEN_SENT`</td>
		<td>`UNKNOWN_RESULT`</td>
	</tr>
	<tr>
		<td>request bytes dispatch 후 Timeout</td>
		<td>`MAY_HAVE_BEEN_SENT`</td>
		<td>`UNKNOWN_RESULT`</td>
	</tr>
	<tr>
		<td>Provider 5xx에서 미전달 보장이 없음</td>
		<td>`MAY_HAVE_BEEN_SENT`</td>
		<td>`UNKNOWN_RESULT`</td>
	</tr>
	<tr>
		<td>요청 전달 후 response 유실·connection lost</td>
		<td>`SENT_RESPONSE_LOST`</td>
		<td>`UNKNOWN_RESULT`</td>
	</tr>
	<tr>
		<td>MCP process exit가 dispatch 이후일 수 있음</td>
		<td>`MAY_HAVE_BEEN_SENT`</td>
		<td>`UNKNOWN_RESULT`</td>
	</tr>
</table>

Exception class 하나만으로 `NOT_SENT`를 추론하지 않는다. `UNKNOWN_RESULT`에서는 기존 결과 GET/Search만 허용하며 새 Attempt·blind resend를 금지한다.

## ClaimContextV2 계약

### Signed Claim Context

```text
claim_version = 2
service_instance_id
mcp_process_instance_id
action_id
approval_id
execution_attempt_id
tool_name
approval_arguments_hash
execution_arguments_hash
issued_at_ms
expires_at_ms
nonce
signature
```

규칙:
- HMAC-SHA-256, 기본 TTL 30초·최대 60초, 1회용 Nonce.
- Application은 Claim 발급 전 `approval_arguments_hash`가 현재 Approval Snapshot과 일치하는지 확인한다.
- Application이 서버 생성 Metadata까지 포함한 최종 MCP 인자를 Canonicalize하여 `execution_arguments_hash`를 계산한다.
- MCP는 Signature·Version·TTL·Service/MCP Process Instance·Action·Approval·Attempt·Tool·Approval Hash를 검증한다.
- MCP는 실제 수신 Tool Arguments를 같은 Canonical 규칙으로 재해시하여 `execution_arguments_hash`가 다르면 `CLAIM_ARGUMENTS_MISMATCH`로 거절한다.
- 모든 검증 성공 후에만 Nonce를 원자적으로 소비하고 Google Write를 호출한다.

### Gmail 첨부파일 Local API·MCP

```text
GET  /api/v1/gmail/messages/{message_id}/attachments/{attachment_id}
POST /api/v1/attachments/stage
```

MCP Read:
```text
get_gmail_attachment(message_id, attachment_id)
```

Attachment Descriptor 최소 필드:
```text
staged_attachment_id
filename
mime_type
size_bytes
sha256
```

- 수신 bytes는 FastAPI Download Stream으로 전달하고 LLM에 보내지 않는다.
- 발신 bytes는 Local Staging에서 읽고 MIME message를 조립한다.
- Draft CREATE/UPDATE·SEND의 Canonical Business Arguments에는 Attachment Descriptor를 포함하고, 실제 bytes의 size/SHA-256을 실행 직전 재검증한다.
- Browser가 임의 Local Path를 MCP Argument로 지정할 수 없다.

## PHASE 7.5 · Planning Default Container Binding

`tasklist_id`, `calendar_id`처럼 Connector Write Tool이 요구하지만 사용자 문장에 직접 나타나지 않을 수 있는 container ID는 LLM이 추측하지 않는다.

```text
OutputToolRouteV1
+ selected resource/container parent if explicitly bound
+ AppSettings.default_tasklist_id / default_calendar_id
→ DefaultContainerResolver          # deterministic
→ BoundSelectedToolSchemaV1         # container field is immutable/const
→ Planning Argument Writer
→ Deterministic Argument Assembler
```

규칙:

- 명시적으로 선택된 target/container가 있으면 configured default보다 우선한다.
- 필요한 default가 없으면 Planning LLM에 숨은 ID를 추측시키지 않고 `NEEDS_CONFIRMATION` 또는 설정/route 계약의 명시적 실패로 보낸다.
- Planning LLM은 bound Tool Schema에 이미 고정된 `tasklist_id/calendar_id`를 변경할 수 없다.
- 승인 Snapshot/Arguments Hash에는 deterministic binding이 완료된 최종 Business Arguments를 사용한다.
