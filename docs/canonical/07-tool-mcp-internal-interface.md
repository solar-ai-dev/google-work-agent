# 07. Tool · MCP · 내부 인터페이스 명세서

> **Authority:** Local API, Connector MCP Tool, 내부 Port·Command/Query typed interface. Domain/Workflow/Retrieval behavior와 repository placement는 해당 owner를 따른다.

## 0. 문서 정보

- **상태:** Draft v2.34
- **기준일:** 2026-09-03
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

### 1.1 Connector 접근 공통 경계

- **Local API**는 React와 FastAPI Local Agent Service 사이의 제품 내부 REST/SSE 인터페이스다. Provider API를 직접 호출하기 위한 우회 경로가 아니다.
- 외부 Connector I/O의 직접 제품 caller는 **Application의 결정적 use-case/Application operation**다. Application은 먼저 Application-side `SignedToolRegistry`에서 Tool identity/effect/schema를 검증해 `ValidatedConnectorToolBindingV1`을 materialize한 뒤 `ConnectorReadPort | ConnectorWritePort | OAuthCredentialPort` 같은 **abstract Connector Application Port만 호출**한다. Core-side Connector Adapter는 Application concrete Registry를 import하지 않고 전달받은 validated binding + `ConnectorRuntimeRegistry + MCPClientPort`만 사용해 exact Connector MCP Server에 dispatch한다. FastAPI Route·LangGraph adapter/Agent·Domain은 `ConnectorRuntimeRegistry`, `MCPClientPort`, concrete Connector Adapter/MCP path를 직접 호출하거나 소유하지 않고 Application 경계를 통해 Command/Result를 주고받는다.
- 각 Provider API/SDK, Credential 적용, raw token/response 해석은 해당 Connector MCP Server 내부 Adapter가 소유한다.
- Retrieval Read, Connector Browse/Count/Detail, Credential 상태 확인, Write dispatch, Verification/Recovery 조회까지 외부 업무 시스템에 닿는 모든 제품 경로는 Connector MCP Tool/Port를 통과해야 한다.
- 테스트에서는 Connector MCP Client/Transport를 Fake로 대체할 수 있다. 제품 Core에 별도 Provider Client를 주입해 MCP를 우회하는 대체 실행 경로를 두지 않는다.
- P0의 첫 Connector는 `google_workspace`이며 Google Workspace MCP Server가 Gmail·Tasks·Calendar와 Google OAuth/Provider Adapter를 소유한다.
- MCP Server 내부 Provider API 호출은 Connector 구현 세부사항이며 관측 지표는 `connector_id`와 Provider request count를 함께 기록한다.

### 1.2 Retrieval Read Continuation 경계

- Connector List/Search Read는 결과 Resource와 함께 **opaque continuation (`next_page_token | null`)**을 반환할 수 있다. Provider raw response 형식은 Connector MCP Server 내부 Adapter가 해석하고 Core에는 표준 continuation 의미만 노출한다.
- Retrieval self-loop에서 raw continuation의 유일한 Runtime owner는 `05 Retrieval`의 current **Run Retrieval Cache read-result entry**다. 이 entry는 현재 `run_id`, `route_id`, validated query identity/hash와 continuation을 결합해 저장하고 `read_result_handle`로만 참조한다.
- Retrieval Local State·Main State·LangGraph Checkpoint·Domain DB·Prompt·Trace·Audit에는 raw continuation을 복제하지 않는다. `QueryAttemptV1`/관측에는 hash·operation kind·bounded metadata만 남긴다.
- `NEXT_PAGE` 호출은 결정적 Retrieval Node가 Application `retrieval.execute_read` operation을 호출하고, 그 operation이 `read_result_handle`을 resolve하여 `run_id + route_id + query identity/hash` binding과 continuation 미소진 상태를 검증한 뒤 해당 opaque continuation을 `ConnectorReadPort`의 `page_token` 인자에 주입한다.
- unknown handle, cross-run handle, route/query mismatch, 이미 소진된 continuation은 Provider 호출 전에 fail-closed한다. LLM·사용자·Supervisor가 raw `page_token`을 생성·전달·수정할 수 없다.
- Sidebar `ResourceListResponseV1.next_page_token`과 Retrieval Run Cache continuation은 서로 다른 lifetime/consumer 계약이다. 동일 문자열 형식일 수 있어도 Sidebar Client continuation을 Retrieval local loop authority로 재사용하지 않는다.

Canonical process-memory cache wire:

```python
class RunRetrievalCacheEntryV1:
    schema_version: Literal[1]
    read_result_handle: str
    run_id: str
    route_id: str
    query_identity_hash: str
    read_result: ConnectorReadResultV1  # Connector-normalized bounded result; opaque next_page_token remains inside this cache entry
    continuation_exhausted: bool

class RunRetrievalCacheResolveResultV1:
    schema_version: Literal[1]
    status: Literal["FOUND", "MISSING", "CROSS_RUN", "BINDING_MISMATCH", "EXHAUSTED"]
    entry: RunRetrievalCacheEntryV1 | None

class ReconcileRetrievalCacheRestartCommandV1:
    schema_version: Literal[1]
    run_id: str

class ReconcileRetrievalCacheRestartResultV1:
    schema_version: Literal[1]
    outcome: Literal["NO_RESTART_REQUIRED", "RESTART_STAGED", "EXISTING_RESTART"]
    checkpoint_generation: int
    handoff_id: str | None
```

`read_result_handle`은 process-local opaque handle이며 durable identity가 아니다. Cache loss는 handle을 재생성하거나 raw continuation을 복원하지 않고 `run.reconcile_retrieval_cache_restart`로 넘긴다. Handler는 latest typed checkpoint와 current Run을 다시 읽고 stale caller input으로 checkpoint generation/target을 발명하지 않는다.

`RunRetrievalCacheResolveResultV1`의 closed semantics는 다음과 같다. `FOUND`는 valid bound entry + continuation not exhausted, `EXHAUSTED`는 valid bound entry + `continuation_exhausted=true`다. 두 status 모두 checkpoint resume dependency를 충족하며 `entry`가 반드시 존재한다. `EXHAUSTED`는 cache loss가 아니므로 `RETRIEVAL_CACHE_RESTART`를 stage하지 않고 `NEXT_PAGE`만 `NO_MORE_PAGE`로 Provider 호출 0회 종료한다. `MISSING|CROSS_RUN|BINDING_MISMATCH`는 `entry=None`이고 restart prerequisite의 invalid dependency다.

### 1.3 Authority boundary

07은 Local API, internal typed interface, Port/MCP Tool schema의 owner다. Domain lifecycle/state는 State Contract, workflow edge/target은 `06`, security policy는 `09`, repository path/file/symbol은 `16`을 직접 참조한다. 다른 Concern의 의미를 wire 예시로 재정의하지 않는다.

## 2. 설치·Runtime 경계

```
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
- **Domain Aggregate mutation Command**는 `command_id + 대상 Aggregate ID + expected_version`을 포함한다. `expected_version`은 해당 Domain Aggregate의 optimistic concurrency authority다.
- **Non-Domain operational Command**(Connection/Credential/Settings/Runtime Mode/Local Runtime Provisioning/Backup·Restore/Diagnostics/Shutdown/Attachment staging)는 `command_id + operation-specific Versioned Request Schema`를 사용한다. Concern owner가 별도의 versioned target/revision을 정의한 경우에만 그 revision을 요구하며, Domain `expected_version`을 임의 생성·재사용하지 않는다.
- `command_id`가 있는 Local API Command는 Application에서 Versioned Request Schema를 canonicalize해 request hash를 계산한다. 같은 ID+같은 hash는 같은 operation result로 replay하고 같은 ID+다른 hash는 conflict다. Domain Aggregate mutation만 04의 durable `command_receipts` 계약을 사용하며, non-Domain side effect의 replay/idempotency는 해당 Application owner가 **`OperationalCommandReplayPort`**로 동일 command identity/hash/result를 adjudicate한 뒤 operation Port를 호출하는 단일 경로로 보장한다.
- API Handler는 Domain 상태를 직접 수정하거나 concrete Port/Adapter를 직접 호출하지 않고 Application Command를 호출한다.
- 응답 유실·재전송에도 동일 Command의 side effect를 중복 적용하지 않는다.
- UI 상태와 SSE Event는 실행 사실의 기준점이 아니다.

### 3.2 주요 Endpoint

`/health/*`는 인증 전 Launcher용이며 Base Path 밖에 둔다. 나머지 Endpoint는 모두 `/api/v1` 전체 경로를 사용한다.

| 구분 | Method·Path | 역할 |
| --- | --- | --- |
| Liveness | `GET /health/live` | FastAPI Process 응답 여부 |
| Core Readiness | `GET /health/ready` | Manifest·Asset·API Contract·SQLite·Migration·Domain·Keyring Adapter·MCP Executable·Tool Schema |
| Runtime Detail | `GET /api/v1/runtime` | `RuntimeDetailResponseV2`: Connector별 Credential·Scope/Permission·LLM Provider·Ollama·signed Local profile·provisioning summary·Recovery 상태. P0에는 Google Workspace 상태를 포함 |
| Local Runtime Provisioning | `POST /api/v1/runtime/local/provision` | `LOCAL_CAPABLE`에서 Release-approved Ollama와 Signed Local Model Profile 준비를 시작·reconcile하는 non-Domain operational Command |
| Session | `POST /api/v1/session/bootstrap` | Launcher Bootstrap으로 Local Session 수립 |
| Conversation | `GET/POST /api/v1/conversations` | 대화 조회·생성 |
| Conversation History | `GET /api/v1/conversations/{conversation_id}/history` | 저장된 Message·Run Timeline 조회. Agent 새 Run Context 입력용이 아님 |
| Run | `POST /api/v1/runs`, `GET /api/v1/runs/{run_id}` | 요청 시작·현재 Domain 상태 조회 |
| Context Adjustment | `POST /api/v1/runs/{run_id}/context-adjustments` | 승인 전 selected Evidence 제외 또는 추가 Retrieval 요청 |
| Interrupt | `POST /api/v1/runs/{run_id}/confirm` | 확인 질문 응답으로 Graph 재개 |
| Approval | `POST /api/v1/actions/{action_id}/approve` | 승인 Command |
| Action Modify | `POST /api/v1/actions/{action_id}/modify` | 수정 Command |
| Action Reject | `POST /api/v1/actions/{action_id}/reject` | 거절 Command |
| Retry | `POST /api/v1/actions/{action_id}/prepare-retry` | 실패한 Write를 `MODIFIED`로 전환해 새 승인 준비 |
| Cancel | `POST /api/v1/runs/{run_id}/cancel` | 취소 요청 |
| Resume | `POST /api/v1/runs/{run_id}/resume` | REAUTH/Safe Checkpoint/Recovery RECHECK의 discriminated resume |
| Recovery Resolution | `POST /api/v1/runs/{run_id}/resolve-recovery` | 명시적 Recovery resolution |
| Resource | `GET /api/v1/resources/{source}` where `source ∈ {gmail,tasks,calendar}` | Sidebar 목록·검색·opaque Local API continuation 조회 |
| Task List Containers | `GET /api/v1/resources/task-lists` | Default Task List 선택용 bounded container 목록 |
| Calendar Containers | `GET /api/v1/resources/calendars` | Default Calendar 선택용 bounded container 목록 |
| Gmail Exact Count | `GET /api/v1/resources/gmail/count` | Sidebar용 exact Gmail count. Browse continuation과 독립된 read-only Query |
| Gmail Detail | `GET /api/v1/resources/gmail/{resource_id}` | Local Session으로 Gmail Thread의 최신 Message UI 상세 조회 |
| Task Detail | `GET /api/v1/resources/tasks/{resource_id}` | required `selection_handle` 검증 후 Task focus 상세 조회 |
| Calendar Detail | `GET /api/v1/resources/calendar/{resource_id}` | required `selection_handle` 검증 후 Event focus 상세 조회 |
| Gmail Attachment | `GET /api/v1/gmail/messages/{message_id}/attachments/{attachment_id}` | bounded attachment bytes 조회 |
| Attachment Staging | `POST /api/v1/attachments/stage` | bounded local staging descriptor 생성 |
| Event | `GET /api/v1/runs/{run_id}/events` | SSE 진행 Projection |

### 3.2-0 Versioned Local API Query/Bootstrap schemas

현재 주요 Query/Bootstrap wire는 다음 versioned contract를 사용한다. URL query parameter는 해당 Request schema의 transport projection이며 Browser가 server-owned identity를 생성하지 않는다.

```python
JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

class ConnectorRuntimeStatusV1:
    schema_version: Literal[1]
    connector_id: str
    connection_status: Literal["CONNECTING", "CONNECTED", "DISCONNECTED", "REAUTH_REQUIRED", "UNAVAILABLE"]
    account_ref: str | None
    scope_status: Literal["READY", "INSUFFICIENT", "UNKNOWN"]
    retry_at_ms: int | None

class LlmRuntimeStatusV1:
    schema_version: Literal[1]
    provider: str
    configured: bool
    availability: Literal["READY", "UNAVAILABLE", "DISABLED"]
    model_id: str | None
    error_code: str | None

# ComponentCircuitKeyV1 shape owner: 10 Infrastructure §8.21
class ComponentCircuitStatusV1:
    schema_version: Literal[1]
    key: ComponentCircuitKeyV1
    state: Literal["CLOSED", "OPEN"]
    retry_at_ms: int | None

class RunBudgetSummaryV1:
    schema_version: Literal[1]
    profile: Literal["NORMAL", "RETRIEVAL_HEAVY", "REVISION_HEAVY"]
    llm_calls_used: int
    llm_call_limit: int
    connector_calls_used: int
    max_connector_calls: int
    source_page_calls_used: int
    max_source_page_calls: int
    detail_fetches_used: int
    max_detail_fetches: int
    context_tokens_used: int
    max_context_tokens: int
    retry_attempts_used: int
    max_retry_attempts: int
    elapsed_ms: int
    max_execution_ms: int

class GmailListItemV1:
    schema_version: Literal[1]
    selection_handle: str          # server-issued opaque authenticated resource identity
    resource_id: str               # Gmail Thread resource id
    subject: str
    sender_name: str | None
    sender_email: str | None
    received_at: str | None
    snippet: str | None
    has_attachments: bool

class TaskListItemV1:
    schema_version: Literal[1]
    selection_handle: str
    resource_id: str
    title: str
    task_status: Literal["incomplete", "completed"]
    scheduled_date: str | None
    completed_at: str | None
    tasklist_id: str

class CalendarListItemV1:
    schema_version: Literal[1]
    selection_handle: str
    resource_id: str
    title: str
    start: str
    end: str
    timezone: str
    calendar_id: str
    location: str | None

ResourceListItemV1 = GmailListItemV1 | TaskListItemV1 | CalendarListItemV1

class GmailResourceListFilterV1:
    schema_version: Literal[1]
    include_thread_metadata: bool = True

class TaskResourceListFilterV1:
    schema_version: Literal[1]
    tasklist_id: str | None
    status_scope: Literal["incomplete", "completed"] = "incomplete"
    sort: Literal["provider_default", "scheduled_date"] = "provider_default"

class CalendarResourceListFilterV1:
    schema_version: Literal[1]
    calendar_id: str | None
    time_min: str | None
    time_max: str | None
    timezone: str

ResourceListFilterV1 = GmailResourceListFilterV1 | TaskResourceListFilterV1 | CalendarResourceListFilterV1

class AttachmentMetadataV1:
    schema_version: Literal[1]
    attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int | None

class RuntimeDetailResponseV2:
    schema_version: Literal[2]
    service_instance_id: str
    connectors: list[ConnectorRuntimeStatusV1]
    llm_providers: list[LlmRuntimeStatusV1]
    component_circuits: list[ComponentCircuitStatusV1]
    active_run_budget: RunBudgetSummaryV1 | None
    recovery_required: bool
    release_version: str
    frontend_build_version: str
    api_contract_version: str
    deployment_profile: str
    runtime_mode: RuntimeModeStatusV1
    database_status: Literal["READY", "DEGRADED", "UNAVAILABLE"]
    migration_status: Literal["READY", "PENDING", "FAILED"]
    sse_status: Literal["READY", "DEGRADED", "UNAVAILABLE"]
    recent_sanitized_error_code: str | None
    launcher_status: Literal["READY", "DEGRADED", "UNAVAILABLE"]
    manifest_status: Literal["VALID", "INVALID", "UNAVAILABLE"]
    session_status: Literal["ESTABLISHED", "NOT_ESTABLISHED"]
    safe_mode: bool
    last_backup_status: str | None
    last_migration_status: str | None
    local_runtime_provisioning: "LocalRuntimeProvisioningStatusV1"

class SessionBootstrapRequestV1:
    schema_version: Literal[1]
    bootstrap_secret: str
    frontend_api_contract_version: str

class SessionBootstrapResponseV1:
    schema_version: Literal[1]
    session_established: bool
    service_instance_id: str
    api_contract_version: str
    compatibility: Literal["COMPATIBLE", "INCOMPATIBLE"]

class ConversationListRequestV1:
    schema_version: Literal[1]
    cursor: str | None
    page_size: int = 50        # 1..50
    search: str | None         # normalized bounded text

class ConversationItemV1:
    schema_version: Literal[1]
    conversation_id: str
    title: str | None
    latest_message_at_ms: int | None
    open_run_id: str | None

class ConversationListResponseV1:
    schema_version: Literal[1]
    items: list[ConversationItemV1]
    next_cursor: str | None

class CreateConversationRequestV1:
    schema_version: Literal[1]
    command_id: str
    title: str | None

class ResourceListRequestV1:
    schema_version: Literal[1]
    source: Literal["gmail", "tasks", "calendar"]
    query: str | None
    next_page_token: str | None
    page_size: int | None
    filters: ResourceListFilterV1

class ResourceListResponseV1:
    schema_version: Literal[1]
    items: list[ResourceListItemV1]
    next_page_token: str | None
    total_count: int | None
    projection_version: str

class ResourceCountResponseV1:
    schema_version: Literal[1]
    source: Literal["gmail", "tasks", "calendar"]
    exact_count: int
    as_of_ms: int

class GmailResourceDetailResponseV1:
    schema_version: Literal[1]
    resource_id: str
    message_id: str
    sender_name: str | None
    sender_email: str
    recipients: list[str]
    cc: list[str]
    subject: str
    received_at: str
    body: str
    attachments: list[AttachmentMetadataV1]
    canonical_url: str

class TaskResourceDetailResponseV1:
    schema_version: Literal[1]
    resource_id: str
    title: str
    task_status: Literal["incomplete", "completed"]
    scheduled_date: str | None
    completed_at: str | None
    tasklist_id: str
    notes: str | None

class CalendarResourceDetailResponseV1:
    schema_version: Literal[1]
    resource_id: str
    title: str
    start: str
    end: str
    timezone: str
    calendar_id: str
    attendees: list[str]
    location: str | None
    description: str | None
```

- `GET /api/v1/conversations`는 `ConversationListRequestV1 → ConversationListResponseV1`이며 04의 `(timestamp_ms,id)` keyset cursor를 opaque `cursor`로 노출한다. `search`는 title/message-index read projection의 bounded query이며 Agent Prompt 입력이 아니다.
- `POST /api/v1/conversations`는 `CreateConversationRequestV1 → ConversationItemV1`이다.
- `GET /api/v1/runtime`은 `RuntimeDetailResponseV2`, `POST /api/v1/session/bootstrap`은 `SessionBootstrapRequestV1 → SessionBootstrapResponseV1`이다. bootstrap secret은 성공/실패와 무관하게 응답·Log·DB에 저장하지 않는다.
- `GET /api/v1/resources/{source}`는 `ResourceListRequestV1 → ResourceListResponseV1`이며 Provider raw page token을 Browser contract로 노출하지 않는다. Local API continuation은 opaque다. `source`와 filter union variant가 일치하지 않으면 `INVALID_RESOURCE_FILTER`로 fail closed한다. Gmail/Tasks Browser page size는 configured `SIDEBAR_PAGE_SIZE`의 bounded value를 사용하고 Calendar는 explicit time window/grid contract를 사용한다.
- `ComponentCircuitStatusV1`은 connector-neutral `key`, `state`, `retry_at_ms?`만 노출한다. `key.kind=CONNECTOR`이면 `connector_id`가 필수이고 `llm_runtime=None`; `key.kind=LLM_RUNTIME`이면 `llm_runtime=API_LLM|LOCAL_GPU`가 필수이고 `connector_id=None`이다. Provider 이름을 Core circuit enum으로 추가하지 않는다. `RunBudgetSummaryV1`은 limit/used/remaining 및 `max_execution_ms`의 bounded operational projection이다. raw secret/Prompt/Provider payload는 Runtime Detail에 포함하지 않는다.

### 3.2-A Conversation History Query

`GET /api/v1/conversations/{conversation_id}/history`는 오른쪽 Conversation 선택 시 중앙 Timeline을 복원하기 위한 **read-only UI Projection**이다.

```
ConversationHistoryResponseV1
schema_version: Literal[1]
conversation: ConversationItemV1
messages: list[ConversationMessageV1]      # <= configured HISTORY_MESSAGE_LIMIT
runs: list[ConversationHistoryRunV1]      # <= configured HISTORY_RUN_LIMIT
truncated: bool                         # message configured bound 초과 시 true
api_contract_version: str

ConversationMessageV1
schema_version: Literal[1]
id
run_id?
role
content
created_at_ms

ConversationHistoryRunV1
schema_version: Literal[1]
run_id
status
started_at_ms
finished_at_ms?
```

- Query는 한 Conversation에 대해 bounded query로 동작하며 최신 Message configured replay/query bound와 Run configured replay/query bound를 가져온 뒤 Timeline 소비용 시간 오름차순으로 반환한다.
- Message가 configured `HISTORY_MESSAGE_LIMIT`을 초과하면 최신 configured bound만 유지하고 `truncated=true`로 표시한다. Run projection은 configured `HISTORY_RUN_LIMIT`을 따른다. 이 제한은 Prompt/RAG token budget이 아니라 **UI history projection bound**이며 exact 숫자는 `10 Infrastructure` configuration만 소유한다.
- unknown `conversation_id`는 `404`다.
- History Query는 Domain 상태 변경, LangGraph resume, Prompt input materialization을 수행하지 않는다. Frontend가 화면에 History를 복원한 뒤 새 요청을 보내도 History 배열 자체를 `POST /api/v1/runs` Payload에 포함하지 않는다.

### 3.2-B Run 생성 · Conversation 경계

```python
class WorkflowBindingV1:
    schema_version: Literal[1]
    workflow_key: str
    run_id: str
    langgraph_thread_id: str
    graph_profile: GraphProfileIdV1
    graph_version: str
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    created_at_ms: int
```

`WorkflowBindingV1`은 **server-owned same-Run workflow identity**다. `graph_profile`은 06의 `GraphProfileIdV1`을 import/reference하고 이 문서에서 새 Profile vocabulary를 만들지 않는다. binding은 Checkpoint store가 관리하며 Domain business truth가 아니다.

`POST /api/v1/runs`는 기존 Conversation을 재사용할 수 있지만 **항상 새 Run을 생성하는 Command**다. `conversation_id`는 Run을 어떤 Conversation Timeline에 귀속할지 지정하는 상관관계 값이며 과거 Run State를 상속시키는 Key가 아니다.

`StartRunRequestV1`의 브라우저 입력은 다음 current-run 사용자 의도와 idempotency/correlation 값으로 제한한다.

```
command_id
conversation_id
request_text: 1..65536 UTF-8
entry_mode: AGENT_SEARCH | RESOURCE_SELECTED
selected_resource_handles: list[str], max 20
requested_mode: AUTO | LOCAL_GPU | API_LLM
```

- Browser는 새 Aggregate/Workflow identity인 `run_id`, `user_message_id`, `workflow_key`, `langgraph_thread_id`를 생성하거나 Wire Request로 제출하지 않는다. `command_id`는 **한 번의 사용자 Submit 의도마다 Frontend가 생성해 동일 transport retry에서 그대로 재사용하는 idempotency identity**이고 `conversation_id`는 기존 Timeline Aggregate를 지정하는 값이다. 새 사용자 Submit은 새 `command_id`를 사용하며 같은 사용자 의도의 네트워크 재시도에서 새 ID를 발급하면 안 된다. `workflow_key`는 StartRun 성공 후 Application/Workflow가 생성하는 opaque server-owned workflow-binding identity이며 Browser 입력/표시 authority가 아니다.
- Application이 server-owned `run_id + user_message_id + workflow_key + langgraph_thread_id`를 먼저 생성한다. `command_id + canonical request hash + conversation_id`와 Open Run Guard를 검증한 뒤 `StartRun`을 적용하며, **Run + USER Message + WorkflowBindingV1 + START `WorkflowHandoffV1(PENDING)`을 같은 SQLite UnitOfWork로 commit**한다. commit 후에만 `run.schedule_run_execution(handoff_id)`을 호출한다. 따라서 StartRun commit 뒤 scheduler 전 crash도 startup redrive로 복구하며 Terminal 이전 Run의 workflow/thread identity를 재사용하지 않는다.
- Application은 Wire의 `request_text + selected_resource_handles + requested_mode`를 검증·resolve하여 `RunInputV1.user_request + selected_resource_refs + requested_mode` current-run Projection으로 materialize한다. 각 handle은 Resource List Query가 발급한 **opaque authenticated selection handle**이며 Browser가 내부 connector/resource identity를 구성하지 않는다. HTTP Wire 이름과 Agent Typed State 이름을 혼용하지 않는다. 같은 Conversation에 비Terminal Run이 있으면 두 번째 Run을 시작하지 않고 Conflict로 처리한다.
- Terminal 이전 Run의 `langgraph_thread_id`, Checkpoint, Main State, Agent Artifact를 새 Run에 재사용·복사하지 않는다.
- StartRun 입력에 `conversation_history`, 과거 Message 배열, 이전 RequestIntent/Route/Evidence/Plan/Review, Approval·Confirmation Receipt, prior checkpoint를 Semantic Context로 받는 필드를 두지 않는다.
- `GET /api/v1/conversations`와 Conversation detail/history 조회는 UI Timeline 복원용 Query다. 이 조회 결과를 서버나 Frontend가 StartRun Prompt Context에 자동 주입하지 않는다.
- 사용자가 과거 Resource를 이번 Run에 다시 명시적으로 선택한 경우 해당 `SelectedResourceRefV1`만 current-run Entry Context가 된다. 기존 Evidence·Approval·Confirmation 결과는 함께 승계되지 않는다.

`SelectedResourceRefV1`은 Browser의 opaque `selected_resource_handles`를 Application이 검증해 materialize한 **current-run typed projection**이다. 별도 server-side Sidebar Resource index를 만들지 않는다.

각 List Item의 `selection_handle: str`은 opaque authenticated wire value다. 그 내부 signed payload의 current schema는 다음 하나다.

```python
class ResourceSelectionHandlePayloadV1:
    schema_version: Literal[1]
    service_instance_id: str
    session_digest: str
    account_id: str
    connector_id: str
    resource_type: str
    resource_id: str
    parent_resource_id: str | None
    version_token: str | None
    issued_at_ms: int
    expires_at_ms: int
```

Resource Browse Application operation은 이 payload를 authenticated envelope로 encode해 `selection_handle`을 발급한다. Browser는 envelope를 decode/수정하지 않는다. Application `resource.resolve_selection_handle`만 현재 Service instance, Local Session, account, expiry, signature를 검증하고 내부 identity를 반환한다. Service restart/session/account 변경/expiry/signature mismatch는 fail closed하며 Provider cross-source probing으로 handle을 복구하지 않는다.

```python
class SelectedResourceRefV1:
    schema_version: Literal[1]
    resource_ref_id: str
    connector_id: str
    resource_type: str
    resource_id: str
    parent_resource_id: str | None
```

Browser는 위 내부 field를 직접 제출하지 않는다. Handle 검증 뒤 Domain `StartRun` UoW가 새 `run_id`를 확정하면서 선택된 identity를 `(run_id, connector_id, resource_type, resource_id)` `ResourceRef`로 materialize하고 server-owned `resource_ref_id`를 발급한다. 이 selected ResourceRef들은 USER Message/Run과 같은 StartRun transaction에서 commit되어 `RunInputV1` 생성 전에 durable identity가 된다. connector/resource/account/session binding이 불일치하면 StartRun은 fail closed한다.
- `POST /api/v1/runs/{run_id}/confirm` / `POST /api/v1/runs/{run_id}/resume`는 위 새 Run 생성과 다른 계약이다. 비Terminal **동일 Run**의 등록된 `langgraph_thread_id`/Checkpoint를 안전하게 resume한다.

#### Gmail UI Detail Projection

`GET /api/v1/resources/gmail/{resource_id}`는 Sidebar의 `gmail_thread` ID를 받아 해당 Thread에서 `internalDate` 기준 최신 Message 1개를 표시한다. 응답은 `resource_id`, `message_id`, `sender_name`, `sender_email`, `recipients`, `cc`, `subject`, `received_at`, `body`, `attachments`, `canonical_url`을 포함한다. 본문은 `text/plain`을 우선하고 HTML만 있으면 안전한 readable text로 변환하며 raw HTML을 Browser에 전달하지 않는다.

`canonical_url`의 Gmail P0 의미: RFC822 Message-ID가 있으면 `rfc822msgid:` 기반 Gmail 검색 URL이고, 없으면 Gmail All Mail 목록 fallback이다. Gmail REST `thread_id`/`message_id`로 구성한 direct-open hash URL(`#inbox/{id}`, `#all/{id}` 등)은 cold click에서 신뢰할 수 없어 사용하지 않는다. `canonical_url`은 direct Thread permalink를 보장하지 않는다.

이 계산을 위해 내부 MCP Gmail UI Detail 계약(`GmailThreadDetail`)은 `format=full` 응답에서 프로젝션한 RFC822 `Message-ID` header를 `rfc822_message_id`로 추가 전달한다. 이 필드는 MCP/Port 내부 계약에만 존재하며 위 API response schema(`GmailResourceDetailResponseV1`)에는 노출하지 않는다.

이 Endpoint는 UI 전용 Application Query다. `gmail_get_thread`, `gmail_get_message`, Agent Context, Retrieval Workflow와 `selected_resources` 계약을 변경하지 않는다.

#### Tasks / Calendar UI Detail Projection

- `GET /api/v1/resources/tasks/{resource_id}`는 현재 Row의 required `selection_handle`을 query parameter로 받아 `resource_id`/Task List/account binding을 검증한 뒤 `resource.get_task_resource_detail → tasks_get_task`으로 `TaskResourceDetailResponseV1`을 반환한다.
- `GET /api/v1/resources/calendar/{resource_id}`도 required `selection_handle`을 검증해 Calendar parent/account binding을 확정한 뒤 `resource.get_calendar_resource_detail → calendar_get_event`로 `CalendarResourceDetailResponseV1`을 반환한다.
- 두 detail Query는 UI focus projection이며 Agent Evidence/ResourceRef를 자동 생성하거나 Retrieval을 시작하지 않는다. React가 MCP Tool을 직접 호출하는 경로는 0이다.

### 3.2.1 Sidebar Resource Browse·Count 계약

- Gmail·Tasks UI visible page는 configured `SIDEBAR_PAGE_SIZE`, Agent Retrieval은 configured `RETRIEVAL_PAGE_SIZE`를 사용하며 lifetime·consumer·continuation 계약은 별도다. Calendar Month View는 visible grid 전체를 materialize하고 numeric pagination을 사용하지 않는다.
- `ResourceListResponseV1.next_page_token`은 Client 관점의 opaque Local API continuation이다. Frontend는 이를 Google Provider token이나 UI page number로 해석하지 않고 다음 Local API 요청에 그대로 전달한다. Provider raw token은 Adapter 내부 구현 세부사항이다.
- Gmail Browse는 configured `page_size` default이고 optional `include_thread_metadata`의 기본값은 `true`다. 아직 표시하지 않을 intermediate page를 통과할 때만 `false`를 사용해 Thread ID/list metadata/continuation만 확보하고 visible target page는 metadata를 hydrate한다. target hydration 중 필요한 Provider Read 하나라도 실패하면 partial placeholder page를 만들지 않고 해당 page Read를 실패 처리한다.
- Gmail 기본 Sidebar scope는 `INBOX + PRIMARY` Thread이며 exact badge count도 같은 scope다. Sidebar 검색은 Primary 제한 없이 일반 mailbox를 검색하되 Spam·Trash를 제외하고 기본 Gmail badge count는 유지한다. Count traversal은 body/attachment/detail N+1 없이 필요한 최소 list metadata만 사용한다.
- Tasks 기본 Browse는 configured/default Task List에 `show_completed=false`, `show_hidden=false`, `show_deleted=false`, Provider `page_size<=100`을 사용한다. Application은 Task metadata batch와 opaque continuation을 반환하고 React Client Session Cache가 이를 configured `SIDEBAR_PAGE_SIZE` page로 slice한다. continuation이 있으면 현재 materialized batch에서 계산되는 page 범위만 알고, 알려진 마지막 page에서만 다음 batch를 append한다. terminal 뒤 누적 수로 exact total과 마지막 UI page를 확정한다. `tasks.get`은 focus/선택 detail에만 사용한다.
- Tasks `status_scope=incomplete|completed`를 지원하고 기본은 `incomplete`다. completed materialization은 `show_completed=true`, `show_hidden=true`, `show_deleted=false`, `page_size<=100`으로 terminal까지 읽은 뒤 mixed Provider 결과에서 `task_status=completed`만 `resource_id` 기준 dedupe한다. raw Google `completed` timestamp는 존재할 때 `completed_at` metadata로 보존한다.
- Calendar Month Browse는 `monthAnchor`에서 계산한 configured timezone의 explicit `[gridStart, gridEnd)`와 `singleEvents=true`를 사용하며 Provider `page_size<=100`을 terminal까지 순회한다. `time_min/time_max`가 생략된 일반 Upcoming Browse는 configured timezone 기준 현재 시각부터 90일 후까지의 bounded default window를 사용한다.
- `ResourceCountResponseV1.source`는 Sidebar/API projection의 source-family vocabulary(`gmail|tasks|calendar`)이며, `SignedToolRegistryEntryV1.resource_type`과 다른 개념이다. Connector resource identity가 필요한 내부 Route/Retrieval/Persistence에서는 canonical Registry `resource_type`을 exact-copy하며, Count projection에서 `resource_type`이라는 이름으로 source family를 재사용하지 않는다.
- Exact Count Read는 Browse와 독립된 Local API Query다. P0 Gmail Sidebar count는 `GET /api/v1/resources/gmail/count → resource.get_resource_count → ConnectorReadPort`로 수행하고 `ResourceCountResponseV1(source="gmail", exact_count, as_of_ms)`만 반환한다. Frontend가 Provider page를 순회해 exact count를 계산하지 않는다. P0 Sidebar startup은 Gmail exact count와 Tasks incomplete 첫 batch만 준비하며 Tasks badge는 그 batch의 terminal/continuation 상태에서 계산한다. Calendar tab에는 numeric badge가 없고 startup·Calendar refresh에서 Calendar Count Read를 호출하지 않는다. Count 실패·timeout은 Browse를 실패시키지 않고 numeric badge만 생략한다.
- React Client Session Cache identity는 active Google `account_id`, source, container(Task List/Calendar), 검색/filter/sort/status scope, continuation/batch generation으로 구성한다. raw Local Session Cookie/token과 OAuth token은 Application snapshot이나 cache key로 전달하지 않는다. Refresh·계정/container/scope/검색/filter/sort 변경·session 종료는 관련 cache를 무효화한다.

### 3.3 상태 변경 API 입력 소유권

브라우저는 사용자 의도와 낙관적 동시성에 필요한 값만 보낸다. Domain 권위 Metadata는 Application이 현재 Domain 상태에서 생성·검증한다.

- Client 입력 허용: `command_id`, 대상 ID, `expected_version`, 사용자 선택·텍스트·수정하려는 허용 필드.
- Server 생성·검증: `request_hash`, `approval_id`, Write `idempotency_key`, `source_snapshot`, 승인 주체 식별, `approval_arguments_hash`, `execution_arguments_hash`, `claim_token`. Approval 시점 Business Snapshot과 실제 MCP dispatch 인자 Hash를 구분한다.
- `request_hash`는 수신 JSON을 그대로 Hash하지 않고 Endpoint별 Versioned Request Schema를 Canonical JSON으로 정규화한 뒤 Application command handler가 SHA-256으로 계산한다. 같은 `command_id + request_hash`는 기존 Result를 반환하고 같은 `command_id + 다른 hash`는 Conflict다.
- Local Session이 승인 주체의 기준이며 Browser가 actor identity를 지정하지 않는다.
- Browser가 보낸 Approval·Source Snapshot·Arguments Hash·Idempotency Key를 실행 권위로 사용하지 않는다.

| Endpoint | Request Schema | 핵심 입력 | Domain/Application 매핑 |
| --- | --- | --- | --- |
| `POST /api/v1/runs/{run_id}/confirm` | `ConfirmationResponseV1` | `command_id`, `expected_version`, `interrupt_id`, `response_kind`, option 또는 free text | 확인 응답 저장 후 `interrupt_id`가 가리키는 `semantic_owner_id + AgentNodeResumeTargetV2` checkpoint에서 same-thread resume. `resume_target`은 `ResumeTargetRegistry`가 `NodeRegistry`의 current graph_version/node entry를 근거로 발급·검증하며 LLM 자유 문자열로 수신하지 않는다. 모든 확인을 Request Understanding으로 되돌리는 공통 재시작 금지 |
| `POST /api/v1/runs/{run_id}/context-adjustments` | `ContextAdjustmentRequestV1` | `command_id`, `expected_version`, `expected_retrieval_revision`, discriminated adjustment payload | `run.adjust_context`. 조정 가능 precondition을 검증한 뒤 existing `BeginPlanning`의 `USER_CONTEXT_ADJUSTMENT` branch로 current Plan을 `SUPERSEDED`하고, normalized `ContextAdjustmentV1`을 same Run Retrieval owner에 전달해 새 Retrieval revision을 생성한다. Approval/Execution이 시작된 상태에서는 적용 0 |
| `POST /api/v1/actions/{action_id}/approve` | `ApproveActionRequestV2` | `command_id`, `expected_version` | 서버가 최신 Action·Source·Policy·Tool Schema에서 Approval Snapshot·ID·Idempotency Key 생성 |
| `POST /api/v1/actions/{action_id}/modify` | `ModifyActionRequestV2` | `command_id`, `expected_version`, 허용된 `arguments_patch` | `ModifyAction`; 기존 ACTIVE Approval revoke |
| `POST /api/v1/actions/{action_id}/reject` | `RejectActionRequestV2` | `command_id`, `expected_version`, optional reason | `RejectAction` |
| `POST /api/v1/actions/{action_id}/prepare-retry` | `PrepareRetryRequestV2` | `command_id`, `expected_version` | `FAILED → MODIFIED`; 새 Approval Metadata는 서버가 이후 생성 |
| `POST /api/v1/runs/{run_id}/cancel` | `CancelRunRequestV2` | `command_id`, `expected_version`, optional reason | `RequestCancel`; Version/Receipt 판정 후에만 child mutation |
| `POST /api/v1/runs/{run_id}/resume` | `ResumeRunRequestV2` | `command_id`, `expected_version`, `resume_kind` | `REAUTH_COMPLETED | SAFE_CHECKPOINT_RESUME | RECOVERY_RECHECK`만 허용. `REAUTH_COMPLETED → run.resume_after_reauth`, `RECOVERY_RECHECK → recovery.resolve_recovery(RECHECK)`, `SAFE_CHECKPOINT_RESUME → run.resume_safe_checkpoint`. `resume_safe_checkpoint`와 `resume_after_reauth`는 동일 `run_id + langgraph_thread_id + checkpoint + RegisteredResumeTargetRefV2`의 Domain/Checkpoint 정합성, target kind, semantic-owner/profile/compiled-subgraph 또는 main-stage identity, active `graph_version`을 검증한다. 추가로 `SAFE_CHECKPOINT_RESUME`는 Domain State Transition Contract의 startup source-state matrix에서 **ALLOWED**인 durable status에만 적용한다. FORBIDDEN status는 snapshot/reconciliation/전용 lifecycle command를 사용하며 generic LangGraph resume 0. stale/unknown target은 추측하지 않고 Recovery로 fail closed한다. Confirmation/Approval은 전용 Endpoint 사용 |
| `POST /api/v1/runs/{run_id}/resolve-recovery` | `ResolveRecoveryRequestV1` | `command_id`, `expected_version`, discriminated `target`, `resolution_kind` | `target=RUN` 또는 `target=ACTION(action_id)`만 허용. Persisted RecoveryContext의 reason/scope/target과 exact match 후 하나의 internal `ResolveRecoveryCommandV1`로 materialize |

`SAFE_CHECKPOINT_RESUME`는 Domain lifecycle command가 아니므로 request replay/conflict는 `OperationalCommandReplayPort`가 판정한다. New reservation은 same command identity로 `WorkflowHandoffV1(PENDING)`을 stage한 뒤 result_ref=`handoff_id`를 저장한다. HTTP response loss 후 same ID/hash replay가 `RESERVED|UNCERTAIN`이면 `WorkflowHandoffRepository.get_by_trigger_command_id(command_id)`로 existing handoff를 회수하여 같은 result를 완성하고 새 handoff/control을 만들지 않는다. lookup 결과가 없으면 prior handoff commit이 없었던 것으로만 취급하고 current checkpoint/binding/source-state를 다시 검증한 뒤 같은 reserved command에서 한 번 stage할 수 있다; unique trigger + replay reservation이 두 번째 committed handoff를 차단한다. same ID/different hash는 409이며 raw SQLite lookup은 금지다.

`ConfirmationResponseV1`은 **외부 Local API wire request**다. Confirmation Controller는 `command_id`, `expected_version`, `interrupt_id`와 checkpoint/option 범위를 검증한 뒤 control metadata를 제거하고 내부 `ConfirmationResponseProjectionV1(response_kind, selected_option?, free_text?)`로 one-way projection한다. `ConfirmationResponseProjectionV1`만 originating owner의 resumed Product Prompt에 전달할 수 있으며 `interrupt_id`, checkpoint, resume target은 포함하지 않는다.

```python
class ConfirmationResponseV1:
    schema_version: Literal[1]
    command_id: str
    expected_version: int
    interrupt_id: str
    response_kind: Literal["OPTION", "FREE_TEXT", "DECLINE"]
    selected_option: str | None
    free_text: str | None

class ConfirmationResponseProjectionV1:
    schema_version: Literal[1]
    response_kind: Literal["OPTION", "FREE_TEXT", "DECLINE"]
    selected_option: str | None
    free_text: str | None

class PendingInterruptResponseV1:
    schema_version: Literal[1]
    interrupt_id: str
    semantic_owner_id: SemanticAgentOwnerIdV1
    question: str
    options: list[str]
    response_mode: Literal["OPTION", "FREE_TEXT"]
```

Validation rules: `OPTION`은 current interrupt option set에 존재하는 `selected_option` 하나만 허용하고 `free_text=None`; `FREE_TEXT`는 bounded non-empty `free_text`만 허용하고 `selected_option=None`; `DECLINE`은 두 payload field 모두 `None`이다. Wire의 `command_id/expected_version/interrupt_id`는 Product Prompt projection으로 절대 복사하지 않는다.

`PendingInterruptResponseV1`은 internal `ConfirmationRequiredV1`에서 `resume_target`/checkpoint metadata를 제거한 deterministic API projection이다. `options=[]`이면 `response_mode=FREE_TEXT`, 하나 이상이면 `response_mode=OPTION`이다. Browser에는 `RegisteredResumeTargetRefV2`나 checkpoint blob을 노출하지 않는다. `RunSnapshotResponseV1.pending_interrupt`의 exact wire type은 이 타입 하나다.

공통 오류: Version/Command Hash 충돌은 `409`, Schema·허용 Enum·상태 precondition 위반은 `422`, 필요한 Local Runtime·MCP·Google 상태가 일시적으로 준비되지 않으면 `503`을 사용한다. 실패 응답 자체가 Domain 사실을 임의 변경하지 않는다.

`RecoveryResolutionKindV1` / `ResolveRecoveryRequestV1.resolution_kind`의 wire enum은 `RECHECK | ACCEPT_PARTIAL | CREATE_CORRECTIVE_PLAN | CANCEL | FAIL` 하나만 사용한다. `recovery.project_recovery_options`가 persisted `RecoveryContextV1`과 State Contract reason×disposition matrix를 읽어 `ProjectRecoveryOptionsResultV1(reason_code, target, allowed_resolution_kinds)`를 만드는 **유일한 Application derivation authority**다. API schema는 이를 `RecoveryUiProjectionV1`로 one-way serialization만 한다. **Browser는 reason에서 허용 resolution을 재계산하지 않고 이 subset만 표시**하며 별도 reason-specific enum/mapping table을 만들지 않는다. 일반 업무 취소 요청의 진입점은 `/cancel`이며, 이미 `RECOVERY_REQUIRED`인 cancel-intent flow의 terminal resolution만 `CANCEL`을 사용한다.
`RecoveryTargetV1`은 reason scope를 표현한다. `UNKNOWN_RESULT | VERIFICATION_MISMATCH`는 `ACTION(action_id)`가 persisted `RecoveryContextV1.action_id`와 일치해야 하고, `CHECKPOINT_MISMATCH | CONTRACT_VIOLATION`은 `RUN` target만 허용한다. `/resume`의 `RECOVERY_RECHECK`는 Browser target을 새로 받지 않고 persisted RecoveryContext에서 동일 target을 materialize하여 **같은 internal `ResolveRecoveryCommandV1`**를 호출한다. nullable/sentinel action ID나 별도 recovery handler family를 만들지 않는다.

```text
ProjectRecoveryOptionsQueryV1
- run_id

ProjectRecoveryOptionsResultV1
- reason_code: RecoveryReasonV1
- target: RecoveryTargetV1
- allowed_resolution_kinds: list[RecoveryResolutionKindV1]
```

`ProjectRecoveryOptionsResultV1`은 durable RecoveryContext + State Contract matrix의 read-only derivation이며 DB/Domain/Workflow mutation 0이다. Run Snapshot과 `recovery_required` SSE projection은 이 결과만 wire projection으로 소비한다.

### 3.3-C Terminal response durable input

```python
TerminalMessageSourceKindV1 = Literal[
    "ANSWER_DRAFT", "WRITE_VERIFICATION_SUMMARY", "POLICY_BLOCK",
    "CANCEL_RESULT", "RECOVERY_RESULT", "INVALID_REQUEST"
]

class BuildTerminalMessageQueryV1:
    schema_version: Literal[1]
    run_id: str
    expected_run_version: int
    source_kind: TerminalMessageSourceKindV1
    result_kind: Literal["SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"]
    answer_text: str | None         # ANSWER_DRAFT에서만 non-null; 이미 검증된 AnswerDraftV2 content
    reason_codes: list[str]         # max 16, 각 code max 64 chars

class TerminalAssistantMessageInputV1:
    schema_version: Literal[1]
    result_kind: Literal["SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"]
    content: str                 # UTF-8, 1..65536 bytes
    reason_codes: list[str]     # bounded, machine-owned; may be empty for SUCCESS
```

`TerminalCommitIntentV1`의 exact shape/kind owner는 06 Workflow current contract다. 07은 그 intent가 호출하는 lifecycle handler의 Application/Domain interface만 제공하고 별도 terminal kind를 발명하지 않는다.

이 타입은 Browser Wire Request가 아니다. `BuildTerminalMessageHandler`가 `BuildTerminalMessageQueryV1`을 받아 UoW **전에** 만든 Application input이다. P0 terminal response synthesis는 deterministic이다: `ANSWER_DRAFT`는 이미 검증된 `answer_text`를 그대로 사용하고, WRITE/Block/Cancel/Recovery는 persisted typed Run·Plan·Action·Verification projection과 bounded `reason_codes`를 고정 템플릿으로 포맷한다. 이 단계에서 새 LLM call은 하지 않으며 lifecycle/policy/outcome을 재판정하지 않는다. `message_id`, `conversation_id`, `run_id`, `created_at_ms`는 server-owned aggregate/context에서 채우며 Product Prompt가 생성하지 않는다. Terminal lifecycle handler는 이 값을 Domain transition·Receipt·required Audit와 같은 UoW에 stage한다.

### 3.4 SSE 계약

Event 예:

```
run_status
phase_changed
tool_routing
retrieval_progress
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

Event schema:

```python
class RunStatusSsePayloadV1:
    status: RunStatusV1
    snapshot_version: int

class PhaseChangedSsePayloadV1:
    phase: WorkflowPhaseV2

class ToolRoutingSsePayloadV1:
    route_revision: int
    input_route_count: int
    output_mode: Literal["ANSWER", "ACTION"]

class RetrievalProgressSsePayloadV1:
    coverage: Literal["NONE", "PARTIAL", "SUFFICIENT"]
    completed_sources: int
    total_sources: int

class ConfirmationRequiredSsePayloadV1:
    interrupt_id: str
    question: str
    options: list[str]

class AnalysisProgressSsePayloadV1:
    completed_stage: str

class PlanUpdatedSsePayloadV1:
    plan_id: str | None
    revision_no: int

class ApprovalRequiredSsePayloadV1:
    action_ids: list[str]

class ActionStatusSsePayloadV1:
    action_id: str
    status: ActionStatusV1

class VerificationResultSsePayloadV1:
    action_id: str
    outcome: Literal["VERIFIED", "MISMATCH"]

class ReauthRequiredSsePayloadV1:
    connector_id: str

ErrorUiActionKindV1 = Literal[
    "PREPARE_RETRY",
    "REAUTHENTICATE_GOOGLE",
    "RESUME_SAFE_CHECKPOINT",
    "OPEN_SETTINGS",
    "OPEN_DIAGNOSTICS"
]

class ErrorUiActionV1:
    kind: ErrorUiActionKindV1
    action_id: str | None
    resume_kind: Literal["SAFE_CHECKPOINT_RESUME"] | None

class ErrorUiProjectionV1:
    schema_version: Literal[1]
    error_code: str
    message: str
    actions: list[ErrorUiActionV1]

class ContextPreviewItemV1:
    segment_id: str  # 05 deterministic stable SourceSegment identity; random/retrieval-scoped ID 금지
    role: Literal["SUPPORTS", "CONTRADICTS", "CONTEXT"]
    source: Literal["gmail", "tasks", "calendar"]
    resource_type: str
    resource_id: str
    display_label: str
    excerpt: str | None

ContextAdjustmentKindV1 = Literal["EXCLUDE_EVIDENCE", "RETRIEVE_MORE"]

class ContextPreviewResponseV1:
    schema_version: Literal[1]
    items: list[ContextPreviewItemV1]
    gmail_count: int
    tasks_count: int
    calendar_count: int
    adjustment_allowed: bool
    allowed_adjustments: list[ContextAdjustmentKindV1]
    retrieval_revision: int

class ContextAdjustmentRequestV1:
    schema_version: Literal[1]
    command_id: str
    expected_version: int
    expected_retrieval_revision: int
    adjustment_kind: ContextAdjustmentKindV1
    segment_ids: list[str] | None
    requested_information: str | None

class ContextAdjustmentResponseV1:
    schema_version: Literal[1]
    accepted: bool
    current_version: int
    next_phase: Literal["RETRIEVAL"] | None

`ContextPreviewItemV1.resource_type`은 current `ResourceRef.resource_type`/`SignedToolRegistryEntryV1.resource_type` exact vocabulary를 재사용하고 source-family(`gmail|tasks|calendar`)와 혼용하지 않는다. `excerpt`는 bounded/sanitized display projection이며 raw Provider payload authority가 아니다.

`ContextPreviewResponseV1.adjustment_allowed`는 `run.project_context_preview`가 durable Run/Plan/Action/Approval/execution fact에서 계산한다. `allowed_adjustments`는 허용되는 `ContextAdjustmentKindV1`의 exact subset이며 Browser가 별도 policy를 재구성하지 않는다. P0에서 조정 가능 조건은 `Run=WAITING_APPROVAL`, current Plan 존재, 모든 current Action=`PROPOSED|MODIFIED`, ACTIVE Approval=0, in-flight/unknown/unverified execution fact=0이다.

`ContextAdjustmentRequestV1`은 `EXCLUDE_EVIDENCE`일 때 current Preview에 존재하는 `segment_ids` 1개 이상과 `requested_information=null`을 요구한다. `RETRIEVE_MORE`일 때 `segment_ids`는 비어 있고 bounded non-empty `requested_information`을 요구한다. `expected_retrieval_revision` mismatch나 조정 가능 조건 불충족은 `accepted=false`이며 Workflow invoke 0이다.

`retrieval_revision`의 단일 Application-readable authority는 `CheckpointPort.load_retrieval_head(run_id) → RetrievalHeadV1`이다. `run.project_context_preview`와 `run.adjust_context` 모두 같은 head를 읽는다. Application/Route는 `GraphCheckpointEnvelopeV1.checkpoint_blob`을 deserialize하지 않고 Plan revision/Run version을 retrieval revision으로 대체하지 않는다.

```python
class RetrievalHeadV1:
    schema_version: Literal[1]
    run_id: str
    langgraph_thread_id: str
    retrieval_revision: int
    retrieval_artifact_id: str
    checkpoint_id: str
    checkpoint_generation: int
```

RecoveryResolutionKindV1 = Literal[
    "RECHECK", "ACCEPT_PARTIAL", "CREATE_CORRECTIVE_PLAN", "CANCEL", "FAIL"
]

class RecoveryUiProjectionV1:
    reason_code: Literal[
        "UNKNOWN_RESULT", "VERIFICATION_MISMATCH",
        "CHECKPOINT_MISMATCH", "CONTRACT_VIOLATION"
    ]
    target: RecoveryTargetV1
    allowed_resolution_kinds: list[RecoveryResolutionKindV1]

class RecoveryRequiredSsePayloadV1:
    recovery: RecoveryUiProjectionV1

class CompletedSsePayloadV1:
    status: Literal["COMPLETED", "BLOCKED", "FAILED", "CANCELLED"]
    result_kind: Literal["SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"]

class ErrorSsePayloadV1:
    error_code: str
    recoverable: bool

SsePayloadV1 = (
    RunStatusSsePayloadV1 | PhaseChangedSsePayloadV1 | ToolRoutingSsePayloadV1 |
    RetrievalProgressSsePayloadV1 | ConfirmationRequiredSsePayloadV1 |
    AnalysisProgressSsePayloadV1 | PlanUpdatedSsePayloadV1 |
    ApprovalRequiredSsePayloadV1 | ActionStatusSsePayloadV1 |
    VerificationResultSsePayloadV1 | ReauthRequiredSsePayloadV1 |
    RecoveryRequiredSsePayloadV1 | CompletedSsePayloadV1 | ErrorSsePayloadV1
)

class RunSseEventV1:
    schema_version: Literal[1]
    event_id: str
    run_id: str
    action_id: str | None
    occurred_at_ms: int
    event_type: Literal[
        "run_status", "phase_changed", "tool_routing", "retrieval_progress",
        "confirmation_required", "analysis_progress", "plan_updated",
        "approval_required", "action_status", "verification_result",
        "reauth_required", "recovery_required", "completed", "error"
    ]
    payload: SsePayloadV1
    projection_version: int

class SseEventPageV1:
    schema_version: Literal[1]
    events: list[RunSseEventV1]     # <= configured SSE_REPLAY_PAGE_MAX per query
    next_event_id: str | None
    cursor_status: Literal["OK", "CURSOR_EXPIRED"]
```

`event_type`과 payload concrete type은 1:1 closed mapping이다. mismatch/unknown payload는 publish하지 않고 local contract error로 기록한다. Payload는 raw Prompt, raw Provider body, Credential/Token, checkpoint blob을 포함하지 않는다.

- `RunSseEventV1`의 field는 위 `event_id/run_id/action_id?/occurred_at/event_type/payload/projection_version/schema_version` closed shape를 사용한다. `event_id`는 한 프로세스 안에서 Run별 monotonic opaque ID다.
- `SseEventBufferPort.append(event)`, `list_after(run_id, last_event_id, limit)`, `clear_run(run_id)`가 bounded replay buffer의 abstract contract다. P0 concrete implementation은 process-local `InMemorySseEventBuffer`이며 capacity/terminal-retention/query-bound의 exact numeric default는 10 Infrastructure configuration이 소유한다. process restart 시 전체 buffer는 소실될 수 있다. Domain truth/Checkpoint/Audit 저장소가 아니다.
- `sse_event.project_run_event`만 typed Domain/Workflow/Application fact를 `RunSseEventV1`로 투영해 Buffer에 append한다. API Route는 Event meaning을 만들지 않는다.
- 연결 단절 시 React는 `Last-Event-ID`로 재연결한다. Buffer에 cursor가 남아 있으면 `sse_event.list_run_events`가 누락 projection을 반환한다.
- Cursor를 복원할 수 없거나 Service 재시작으로 Buffer가 비었으면 `CURSOR_EXPIRED`를 반환하고 React는 `GET /api/v1/runs/{run_id}` Snapshot을 다시 조회한 뒤 새 SSE cursor로 연결한다.
- SSE 누락/Buffer 손실 자체를 Workflow 실패로 처리하지 않는다.

## 4. Application·Domain 내부 계약

```
FastAPI Route
→ Application Command·Query
→ Domain lifecycle operation
→ Repository 조건부 UPDATE
→ Audit Event
→ Command Result
```

공통 Command Result:

```
applied
result_code
current_status
current_version
next_allowed_commands
conflict_detail
```

필수 Command:

```
start_run
start_analysis
begin_retrieval
begin_planning
request_confirmation
resume_confirmation
publish_plan
complete_answer_only_run
approve_action
modify_action
reject_action
expire_approval
refresh_expired_action
cancel_pending_action
claim_execution
begin_execution_attempt
store_success
mark_failed
mark_unknown_result
recover_existing_result
resolve_as_failed
store_verification
prepare_write_retry
request_cancel
finalize_cancel
block_run
begin_verification
complete_write_run
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

#### 4.1-0A Signed Tool Registry closed authority

`SignedToolRegistryEntryV1`이 Connector Tool metadata의 **단일 Core-side current authority**다. MCP Server의 handshake descriptor는 이 entry의 signed projection일 뿐 별도 Policy/Registry authority가 아니다. Startup/connector restart마다 Core는 `connector_id`별 descriptor의 `registry_entry_hash + schema refs`를 current Signed Tool Registry와 exact 비교하며 mismatch이면 해당 Connector를 NOT_READY로 둔다.

| Effect | retry_class | verification_strategy | recovery_strategy |
|---|---|---|---|
| `READ` | `READ_BOUNDED` | `NONE` | `NONE` |
| `CREATE` | `WRITE_NO_AUTO_RETRY` | `GET_COMPARE` | `RESOURCE_SEARCH` |
| `UPDATE` | `WRITE_NO_AUTO_RETRY` | `GET_COMPARE` | `GET_TARGET` |
| `SEND` | `WRITE_NO_AUTO_RETRY` | `SENT_LOOKUP` | `MESSAGE_SEARCH` |
| `DELETE` | `WRITE_NO_AUTO_RETRY` | `GET_ABSENT` | `GET_TARGET` |

`SignedToolRegistry`의 current callable surface는 `get_required(connector_id, tool_id)`, `select_candidates(connector_id, resource_type, effect)`, `bind_required(connector_id, tool_id, expected_effect) -> ValidatedConnectorToolBindingV1`, `descriptor_expectations(connector_id) -> list[MCPToolDescriptorV1]`로 닫는다. Application/Tool Routing만 semantic lookup/binding을 호출한다. Connector Adapter는 `SignedToolRegistry`를 import/call하지 않는다.

`SignedToolRegistryEntryV1.resource_type`은 Connector resource identity의 canonical vocabulary source다. 별도 Core-wide `EMAIL|TASK|CALENDAR` enum을 두지 않는다. P0 값은 아래 current Registry rows로 닫히며, 신규 Connector/resource는 concern-owned Tool contract와 Signed Tool Registry row를 추가해 확장한다. Route/Retrieval/Persistence projection은 이 문자열을 exact-copy하며 Tool 이름에서 추론하거나 별도 mapper authority를 만들지 않는다.

Current P0 registry rows are exactly the 21 Tool IDs in §27, all with `connector_id=google_workspace`. Canonical resource binding is:

```text
gmail_search_threads→gmail_thread; gmail_get_thread→gmail_thread; gmail_get_message→gmail_message; gmail_get_attachment→gmail_attachment
gmail_create_draft→gmail_draft; gmail_update_draft→gmail_draft; gmail_get_draft→gmail_draft; gmail_send→gmail_message
tasks_list_tasklists→task_list; tasks_list_tasks→task; tasks_get_task→task; tasks_create_task→task; tasks_update_task→task; tasks_delete_task→task
calendar_list_calendars→calendar; calendar_list_events→calendar_event; calendar_query_freebusy→calendar_freebusy; calendar_get_event→calendar_event
calendar_create_event→calendar_event; calendar_update_event→calendar_event; calendar_delete_event→calendar_event
```

`required_scopes`, input/output schema refs는 §27 row와 exact match하고 effect profile은 위 table과 exact match한다. Tool Routing은 `(connector_id, resource_type, effect)`로 candidate를 만들며 Tool 이름 parsing으로 connector/resource/effect를 추론하지 않는다. Verification/Recovery도 별도 switch/registry authority를 만들지 않고 selected Registry entry의 strategy identifier를 소비한다.

Runtime artifact chain은 다음 하나로 닫는다.

```text
07 current Registry rows (semantic design authority)
→ implementation mirror manifest
→ release packaging canonicalization
→ installed signed-tool-registry-v1.json
→ verified release-manifest sha256 chain
→ load_signed_tool_registry()
→ SignedToolRegistry
```

`SignedToolRegistryManifestV1`은 `schema_version=1`, `contract_version`, `entries: list[SignedToolRegistryEntryV1]`, `entries_hash`만 가진다. Runtime manifest가 07의 current Tool ID/resource/effect/schema set과 다르면 architecture/build test가 실패한다. Manifest는 semantic authority를 새로 만들지 않는다. 서명 신뢰는 10의 `release-manifest.sig → release-manifest.json → signed-tool-registry-v1.json sha256` chain으로만 얻는다.

Connector MCP child가 소비하는 것은 Registry 자체가 아니라 `MCPToolProjectionManifestV1(connector_id, registry_manifest_hash, tools: list[MCPToolDescriptorV1])`이다. 이 projection은 connector별 subset의 transport descriptor만 포함하며 effect/scope/retry/verification/recovery semantic authority를 재정의하지 않는다. Child `project_registry`는 installed Connector Manifest가 가리키는 projection file hash를 검증하고 descriptor를 노출하며, Core는 handshake의 `registry_entry_hash + schema refs`를 Application에서 미리 materialize한 expected descriptor projection과 exact 비교한다.

### 4.1 Canonical outbound Port capability manifest

아래는 현재 Interface가 요구하는 **logical Port capabilities**다. Repository path/file/symbol placement는 `16 Repository Architecture`가 소유한다.

| Boundary | Required Port capability |
| --- | --- |
| Connector | `ConnectorReadPort`, `ConnectorWritePort`, `OAuthCredentialPort`, `MCPClientPort` |
| LLM | `StructuredInferencePort`, `LlmCredentialPort`, `LlmRuntimeStatusPort` |
| Keyring | `SecretStorePort` |
| System | `CheckpointPort`, `WorkflowExecutionPort`, `OperationalCommandReplayPort`, `SettingsPort`, `RuntimeModePort`, `BackupPort`, `DiagnosticsPort`, `ShutdownPort`, `AttachmentStagingPort`, `ClockPort`, `UUIDPort`, `HardwareProbePort`, `BrowserLauncherPort`, `ComponentCircuitStatePort`, `SseEventBufferPort` |
| Persistence | owner별 Domain Repository abstraction + Application-control `WorkflowHandoffRepository`; `CheckpointPort`와 논리 분리 |

Port는 abstraction이고 concrete Adapter가 아니다. FastAPI Route·Agent·Domain이 concrete SQLite/Checkpointer/Provider SDK/Keyring implementation을 직접 호출하는 경로는 허용하지 않는다.

#### 4.1-0 Transport-only shared contracts

아래 타입은 MCP transport/checkpoint **boundary metadata만** 소유하며 Product semantic artifact나 Domain truth가 아니다.

```python
class SignedToolRegistryEntryV1:
    schema_version: Literal[1]
    connector_id: str
    resource_type: str
    tool_id: str
    effect: Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]
    required_scopes: list[str]
    input_schema_ref: str
    output_schema_ref: str
    retry_class: Literal["READ_BOUNDED", "WRITE_NO_AUTO_RETRY"]
    verification_strategy: Literal["NONE", "GET_COMPARE", "GET_ABSENT", "SENT_LOOKUP"]
    recovery_strategy: Literal["NONE", "GET_TARGET", "RESOURCE_SEARCH", "MESSAGE_SEARCH"]

class ValidatedConnectorToolBindingV1:
    schema_version: Literal[1]
    connector_id: str
    resource_type: str
    tool_id: str
    effect: Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]
    input_schema_ref: str
    output_schema_ref: str
    registry_entry_hash: str

class SignedToolRegistryManifestV1:
    schema_version: Literal[1]
    contract_version: str
    entries_hash: str
    entries: list[SignedToolRegistryEntryV1]

class MCPToolDescriptorV1:
    # MCP handshake projection only; semantic authority is SignedToolRegistryEntryV1.
    schema_version: Literal[1]
    connector_id: str
    tool_id: str
    input_schema_ref: str
    output_schema_ref: str
    registry_entry_hash: str

class MCPToolProjectionManifestV1:
    schema_version: Literal[1]
    connector_id: str
    registry_manifest_hash: str
    tools: list[MCPToolDescriptorV1]

class MCPToolCallResultV1:
    schema_version: Literal[1]
    tool_id: str
    transport_status: Literal["OK", "ERROR", "TIMEOUT", "DISCONNECTED"]
    payload: JSONValue | None
    error_code: str | None

class MCPRestartResultV1:
    schema_version: Literal[1]
    restarted: bool
    reason_code: str | None

class RetrievalCacheRequirementV1:
    schema_version: Literal[1]
    read_result_handle: str
    route_id: str
    query_identity_hash: str

class GraphCheckpointEnvelopeV1:
    schema_version: Literal[1]
    checkpoint_id: str
    checkpoint_generation: int
    run_id: str
    langgraph_thread_id: str
    graph_profile: GraphProfileIdV1
    graph_version: str
    owner_scope: str
    registered_resume_target: RegisteredResumeTargetRefV2 | None
    applied_handoff_id: str | None
    execution_admission_id: str | None
    active_handoff_id: str | None
    active_handoff_run_sequence: int | None
    retrieval_cache_requirements: list[RetrievalCacheRequirementV1]
    created_at_ms: int
    checkpoint_blob: bytes
```

```python
class RunExecutionRefV1:
    schema_version: Literal[1]
    execution_kind: Literal["START", "RESUME"]
    run_id: str
    langgraph_thread_id: str
    graph_profile: GraphProfileIdV1
    graph_version: str
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    resume_target: RegisteredResumeTargetRefV2 | None

class ConfirmationResumeControlV1:
    kind: Literal["CONFIRMATION_RESPONSE"]
    confirmation_response: ConfirmationResponseProjectionV1
    policy_confirmation_receipt: PolicyConfirmationReceiptV1 | None

class ContextAdjustmentControlV1:
    kind: Literal["CONTEXT_ADJUSTMENT"]
    adjustment: ContextAdjustmentV1

class RetrievalCacheRestartControlV1:
    kind: Literal["RETRIEVAL_CACHE_RESTART"]
    lost_checkpoint_id: str
    lost_handle_fingerprint: str

WorkflowControlEnvelopeV1 = (
    ConfirmationResumeControlV1
    | ContextAdjustmentControlV1
    | RetrievalCacheRestartControlV1
)

class WorkflowHandoffStageV1:
    schema_version: Literal[1]
    handoff_id: str
    trigger_command_id: str
    execution: RunExecutionRefV1
    checkpoint_id: str | None
    checkpoint_generation: int  # observed at command commit
    control_kind: Literal["NONE", "CONFIRMATION_RESPONSE", "CONTEXT_ADJUSTMENT", "RETRIEVAL_CACHE_RESTART"]
    control: WorkflowControlEnvelopeV1 | None
    control_payload_hash: str | None

class WorkflowExecutionBindingV1:
    schema_version: Literal[1]
    execution_kind: Literal["START", "RESUME"]
    run_id: str
    langgraph_thread_id: str
    graph_profile: GraphProfileIdV1
    graph_version: str
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    checkpoint_id: str | None
    checkpoint_generation: int
    resume_target: RegisteredResumeTargetRefV2 | None

class WorkflowExecutionAdmissionV1:
    schema_version: Literal[1]
    admission_id: str
    handoff_id: str
    handoff_run_sequence: int
    submission_kind: Literal["NORMAL_HANDOFF", "CONSUMED_CONTINUATION_RECOVERY"]
    effective_binding: WorkflowExecutionBindingV1
    expected_run_version: int

class WorkflowHandoffV1:
    schema_version: Literal[1]
    handoff_id: str
    trigger_command_id: str
    execution: RunExecutionRefV1
    checkpoint_id: str | None
    checkpoint_generation: int
    run_sequence: int
    control_kind: Literal["NONE", "CONFIRMATION_RESPONSE", "CONTEXT_ADJUSTMENT", "RETRIEVAL_CACHE_RESTART"]
    control: WorkflowControlEnvelopeV1 | None
    control_payload_hash: str | None
    status: Literal["PENDING", "DISPATCHED", "CONSUMED", "BLOCKED_BINDING", "SUPERSEDED"]
    last_submit_reason: Literal["ALREADY_RUNNING", "NOT_COMMITTED", "BINDING_MISMATCH", "SHUTTING_DOWN"] | None
    execution_admission: WorkflowExecutionAdmissionV1 | None
    applied_checkpoint_id: str | None
    applied_checkpoint_generation: int | None
    version: int

class WorkflowExecutionSubmissionV2:
    schema_version: Literal[2]
    admission: WorkflowExecutionAdmissionV1

class RunExecutionAcceptedV1:
    schema_version: Literal[1]
    accepted: bool
    reason_code: Literal["ACCEPTED", "ALREADY_RUNNING", "NOT_COMMITTED", "BINDING_MISMATCH", "SHUTTING_DOWN"]

WorkflowExecutionReleaseReasonV1 = Literal[
    "ALREADY_RUNNING",
    "NOT_COMMITTED",
    "BINDING_MISMATCH",
    "SHUTTING_DOWN",
    "AUTHORITY_EPOCH_CHANGED",
]

class WorkflowExecutionSettlementV1:
    schema_version: Literal[1]
    outcome: Literal["SETTLED", "AUTHORITY_STALE_RETIRED"]
    handoff: WorkflowHandoffV1
```

Typed execution-binding invariants are exact. `WorkflowExecutionBindingV1.execution_kind=START` requires `checkpoint_id=None`, `checkpoint_generation=0`, and `resume_target=None`. `execution_kind=RESUME` requires a non-null checkpoint id, `checkpoint_generation>=1`, and a non-null registered resume target. `CONSUMED_CONTINUATION_RECOVERY` admissions are always `RESUME` and their effective binding is built from the latest authorized descendant checkpoint; the original handoff `execution` remains immutable historical intent and is never recovery wire authority. `WorkflowExecutionAdmissionV1.handoff_id/run_sequence` must exact-match the persisted handoff row, and its `expected_run_version` is the Run authority epoch used by both admission claim and pre-owner settlement CAS.

`WorkflowExecutionSettlementV1.outcome=SETTLED`만 semantic owner I/O를 허가한다. `AUTHORITY_STALE_RETIRED`는 current Run authority epoch가 admission과 달라 stale continuation을 durable하게 retire/clear했다는 뜻이며 owner Node/LLM/Connector I/O는 0이다. `WorkflowExecutionReleaseReasonV1.AUTHORITY_EPOCH_CHANGED`는 Scheduler/reconciler가 **WEP 호출 전** 같은 mismatch를 발견했을 때 사용하는 release cause다. NORMAL stale settlement는 handoff를 SUPERSEDED로 만들고 recovery stale settlement는 CONSUMED를 유지한 채 recovery admission을 clear한다. 이 outcome은 `RunExecutionAcceptedV1.reason_code`나 persisted `last_submit_reason`의 새 값이 아니며 Audit/Trace의 settlement reason으로 투영한다. `AUTHORITY_EPOCH_CHANGED`도 WEP submit result가 아니므로 `last_submit_reason`에 저장하지 않고 release Audit/Trace reason으로만 남긴다.

`checkpoint_blob`은 LangGraph adapter가 생성한 opaque serialization이다. `retrieval_cache_requirements`는 blob을 열지 않고 resume prerequisite를 판정하기 위한 **bounded typed metadata**이며 raw Connector content/token을 포함하지 않는다. Retrieval-dependent checkpoint는 semantic owner I/O 전에 필요한 각 `read_result_handle + route_id + query_identity_hash`만 투영하고, handle 의존성이 끝난 checkpoint에서는 빈 list를 저장한다. Confirmation/Reauth가 Retrieval-local continuation으로 복귀하는 경우 requirement를 유지한다. `checkpoint_generation`은 same `run_id + langgraph_thread_id`에서 committed checkpoint마다 1씩 증가하는 server-owned monotonic CAS identity이며 START 전 binding은 0을 사용한다. `applied_handoff_id`는 one-shot external control dedupe metadata, `execution_admission_id`는 WEP-visible execution이 사용한 durable admission의 checkpoint-side settlement evidence, `active_handoff_id + active_handoff_run_sequence`는 CONSUMED 이후 descendant checkpoint에 승계되는 typed continuation-lineage metadata다. 모두 Product Prompt field가 아니다. Application/Domain/Prompt가 blob 내부 field를 해석하지 않으며, `run_id + langgraph_thread_id + graph_profile + graph_version` mismatch 또는 stale generation은 load/resume 전에 fail closed한다.

#### 4.1-A Canonical Port callable contract

Port 이름만 선언하고 callable shape를 Adapter 구현에 맡기지 않는다. 아래 method family가 현재 abstract boundary다. operation-specific typed Request/Result는 concern owner schema를 사용한다.

| Port | Canonical callable surface |
| --- | --- |
| `ConnectorReadPort` | `execute_read(binding: ValidatedConnectorToolBindingV1, tool_arguments) -> ConnectorReadResultV1`; Application이 `SignedToolRegistry.bind_required(..., expected_effect=READ)`로 만든 binding만 허용 |
| `ConnectorWritePort` | `execute_write(binding: ValidatedConnectorToolBindingV1, tool_arguments, claim_token) -> ConnectorWriteResultV1`; 오직 `execution_attempt.dispatch_connector_write`가 same-Attempt `BeginExecutionAttempt(applied=true)`와 current Attempt=`EXECUTING`을 확인하고 Application-side `SignedToolRegistry.bind_required(..., expected_effect=<WRITE_EFFECT>)`로 만든 binding을 전달한 뒤 호출 |
| `OAuthCredentialPort` | 모든 Core-facing callable이 `connector_id`를 첫 identity로 사용: `start_authorization(connector_id, environment, requested_scopes, operation_ref)`, `reconcile_authorization_start(connector_id, operation_ref) -> OperationalReconcileResultV1`, `refresh_access(connector_id, account_id)`, `get_connection_status(connector_id)`, `revoke_connection(connector_id, account_id, operation_ref)`, `reconcile_revoke_connection(connector_id, account_id, operation_ref) -> OperationalReconcileResultV1`. Loopback callback의 `code/state/PKCE/token exchange`는 MCP Credential Provider 내부 operation이며 Core-facing Port callable이 아니다 |
| `MCPClientPort` | `list_tools(connector_id) -> list[MCPToolDescriptorV1]`; `call_tool(connector_id, tool_id, arguments: JSONValue, timeout_ms: int) -> MCPToolCallResultV1`; `restart_once(connector_id) -> MCPRestartResultV1`. restart/health는 해당 Connector child process만 대상으로 함 |
| `StructuredInferencePort` | `infer(requested_mode, inference_tier, prompt_ref, input_projection, output_schema_ref) -> StructuredInferenceResultV2`; `inference_tier=WORKER|REASONING`, concrete provider/model 선택은 Router 내부 authority |
| `LlmCredentialPort` | `store_credential(provider, secret, storage_mode, operation_ref) -> LlmCredentialStatusV1`; `delete_credential(provider, operation_ref) -> LlmCredentialStatusV1`; `get_credential_status(provider) -> LlmCredentialStatusV1`; `reconcile_credential(operation_ref, provider, target_state, storage_mode?) -> OperationalReconcileResultV1`. Secret 원문은 reconciliation result/journal에 저장하지 않으며 same-command overwrite/delete의 bounded read-back/marker로 COMPLETED 또는 SAFE_TO_RETRY를 증명한다 |
| `LlmRuntimeStatusPort` | `get_status(provider) -> LlmRuntimeStatusV1` |
| `SecretStorePort` | `put(key: str, secret_bytes: bytes) -> None`; `get(key: str) -> bytes | None`; `delete(key: str) -> None` |
| `CheckpointPort` | `create_workflow_binding(binding: WorkflowBindingV1) -> None`; `load_workflow_binding(run_id) -> WorkflowBindingV1 | None`; `store_same_run_checkpoint(checkpoint) -> None`; `load_same_run_checkpoint(run_id, thread_id) -> GraphCheckpointEnvelopeV1 | None`; `store_retrieval_head(head: RetrievalHeadV1) -> None`; `load_retrieval_head(run_id) -> RetrievalHeadV1 | None`; `store_external_llm_scope(scope: ExternalLlmTransferScopeV1) -> None`; `load_external_llm_scope(run_id) -> ExternalLlmTransferScopeV1 | None`; `flush() -> None`; `delete_run_checkpoints(run_id) -> None`. RetrievalHead/scope는 typed metadata이며 checkpoint_blob deserialize API가 아니다 |
| `RunRetrievalCachePort` | `put_read_result(entry: RunRetrievalCacheEntryV1) -> str`; `resolve_read_result(read_result_handle, run_id, route_id, query_identity_hash) -> RunRetrievalCacheResolveResultV1`; `discard_run(run_id) -> None`. raw continuation의 유일한 runtime storage boundary이며 process restart 후 missing handle을 durable storage에서 복원하지 않는다 |
| `WorkflowExecutionPort` | `submit(submission: WorkflowExecutionSubmissionV2) -> RunExecutionAcceptedV1`; `begin_shutdown() -> None`; `await_drained(deadline_ms) -> bool`; submission은 persisted `WorkflowExecutionAdmissionV1`만 허용한다. **동일 `admission_id` replay가 이미 accepted/active이면 새 worker/queue entry를 만들지 않고 idempotent `ACCEPTED`를 반환하며 `ALREADY_RUNNING`을 반환하지 않는다.** `ALREADY_RUNNING`은 다른 admission이 same-Run execution slot을 점유하여 submitted admission이 worker에 채택되지 않은 경우에만 사용한다. WEP는 lifecycle/admission persistence를 만들지 않고 admission의 exact effective binding만 실행한다 |
| `WorkflowHandoffRepository` | `stage_pending(stage: WorkflowHandoffStageV1) -> WorkflowHandoffV1`; `get(handoff_id) -> WorkflowHandoffV1 | None`; `get_by_trigger_command_id(trigger_command_id) -> WorkflowHandoffV1 | None`; `get_dispatch_head(run_id) -> WorkflowHandoffV1 | None`; `list_redriveable(limit) -> list[WorkflowHandoffV1]`; `list_blocked_binding(limit) -> list[WorkflowHandoffV1]`; `claim_execution_admission(handoff_id, expected_version, admission: WorkflowExecutionAdmissionV1) -> WorkflowHandoffV1`; `release_execution_admission(handoff_id, expected_version, admission_id, reason_code: WorkflowExecutionReleaseReasonV1) -> WorkflowHandoffV1`; `mark_consumed_and_clear_payload(handoff_id, expected_version, admission_id, applied_checkpoint_id, applied_checkpoint_generation) -> WorkflowExecutionSettlementV1`; `complete_recovery_admission(handoff_id, expected_version, admission_id, admission_checkpoint_id, admission_checkpoint_generation) -> WorkflowExecutionSettlementV1`; `mark_superseded(handoff_id, expected_version, reason_code) -> WorkflowHandoffV1`; `supersede_unconsumed_for_run(run_id, reason_code) -> list[WorkflowHandoffV1]`. `claim_execution_admission` atomically checks persisted handoff version + owning Run authority version; NORMAL PENDING head becomes DISPATCHED, CONSUMED recovery stays CONSUMED. `release_execution_admission` also atomically checks the persisted admission `expected_run_version`: `AUTHORITY_EPOCH_CHANGED` is legal only when that epoch is actually stale; WEP non-ACCEPTED reasons are legal for their matching submit result. Equal epoch applies ordinary non-ACCEPTED release; stale epoch retires NORMAL directly to SUPERSEDED **with payload body cleared and `superseded_at_ms` set** (or clears only a recovery admission while keeping CONSUMED), never resurrecting a stale lower-sequence head. Both settlement methods apply the same Run-version fence and return `AUTHORITY_STALE_RETIRED` after performing that durable stale retirement. `supersede_unconsumed_for_run` retires only rows without an active execution admission |
| `OperationalCommandReplayPort` | `reserve_or_replay(context: OperationalCommandContextV1) -> OperationalReplayDecisionV2`; `mark_uncertain(context, recovery_ref) -> None`; `store_result(context, result_ref, bounded_result) -> None`; the reservation creates/persists one opaque server-owned `operation_ref` before side effect and returns the same ref on same-command recovery; non-Domain command crash/replay only, Domain lifecycle receipt 0 |
| `SettingsPort` | `get_settings() -> SettingsViewV1`; `update_settings(settings_patch: SettingsPatchV1, operation_ref: str) -> SettingsViewV1`; `reconcile_settings(operation_ref: str, settings_patch: SettingsPatchV1) -> OperationalReconcileResultV1`. Settings file update와 non-secret operation marker는 adapter가 같은 atomic replace에 기록한다 |
| `RuntimeModePort` | `get_requested_mode() -> Literal["AUTO","LOCAL_GPU","API_LLM"]`; `set_requested_mode(requested_mode, operation_ref) -> Literal["AUTO","LOCAL_GPU","API_LLM"]`; `reconcile_update(operation_ref, requested_mode) -> OperationalReconcileResultV1`. current Service process-local requested-mode의 단일 mutable authority이며 Settings/Run/StructuredInferenceRouter 내부 field가 아니다 |
| `LocalRuntimeProvisioningPort` | `provision(operation_ref, model_manifest: ModelManifestV2, product_decision: LocalModelProductDecisionV2) -> LocalRuntimeProvisioningStatusV1`; `get_status() -> LocalRuntimeProvisioningStatusV1`; `reconcile_provision(operation_ref, model_manifest: ModelManifestV2, product_decision: LocalModelProductDecisionV2) -> OperationalReconcileResultV1`. Download/install/process invocation/model-pull/digest verification은 concrete Adapter 내부에만 존재한다. |
| `BackupPort` | `create_backup(operation_ref) -> BackupMetadataV1`; `reconcile_backup(operation_ref) -> OperationalReconcileResultV1`; `restore_backup(backup_ref, operation_ref) -> RestoreResultV1`; `reconcile_restore(backup_ref, operation_ref) -> OperationalReconcileResultV1`; `list_backups() -> list[BackupMetadataV1]` |
| `DiagnosticsPort` | `create_bundle(scope, run_id?, operation_ref) -> DiagnosticBundleMetadataV1`; `reconcile_bundle(operation_ref) -> OperationalReconcileResultV1` |
| `ShutdownPort` | `request_shutdown(operation_ref) -> ShutdownAcceptedV1`; `reconcile_shutdown(operation_ref) -> OperationalReconcileResultV1`. Adapter는 process exit trigger 전에 operation_ref bounded acceptance marker를 durable하게 기록해 restart 후 previous shutdown completion을 판정한다 |
| `AttachmentStagingPort` | `stage(operation_ref, file_bytes, filename, mime_type) -> StagedAttachmentDescriptorV1`; `reconcile_stage(operation_ref) -> OperationalReconcileResultV1`; `open_bytes(staged_attachment_id) -> bytes`; `delete(staged_attachment_id)` |
| `ClockPort` | `now_ms() -> int` |
| `UUIDPort` | `new_uuid() -> str` |
| `HardwareProbePort` | `probe() -> HardwareProfileV1` — shape owner: 10 Infrastructure §8.20-A |
| `BrowserLauncherPort` | `open_url(url: str) -> None` |
| `ComponentCircuitStatePort` | `get_state(key: ComponentCircuitKeyV1) -> ComponentCircuitStateV1`; `record_technical_failure(key, failure_code, now_ms) -> ComponentCircuitStateV1`; `record_success(key, now_ms) -> ComponentCircuitStateV1` — key/shape owner: 10 Infrastructure §8.21 |
| `SseEventBufferPort` | `append(event: RunSseEventV1) -> None`; `list_after(run_id, last_event_id, limit) -> SseEventPageV1`; `clear_run(run_id) -> None` — bounded process-local replay only |

For `StartRun`, `CheckpointPort.create_workflow_binding(...)` is used through the SQLite transaction-scoped adapter bound to the **same `SqliteUnitOfWork` connection** as Run/Message persistence and `WorkflowHandoffRepository.stage_pending(...)`; it MUST NOT perform an independent commit. This is the only place where initial WorkflowBinding creation is coupled to Domain-row creation. Later LangGraph checkpoint writes remain checkpointer-owned transactions.

Port method는 concrete Adapter class/path를 소유하지 않는다. 입력 size/range, secret redaction, timeout/retry/idempotency는 각 07/09/10 owner contract와 16 Adapter mapping을 함께 따른다.

## 5. Agent 내부 인터페이스

Main Graph와 Agent Subgraph는 Versioned Typed State로 연결한다. Main State는 공식 결과만 누적하고 Subgraph 내부 Query candidate·LLM candidate·RAG score는 Local State/Run Cache에 둔다.

```
RunInputV1
RequestIntentV2
ToolRoutePlanV2
RetrievalResultV1
WorkAnalysisResultV2
AnswerDraftV2 | ActionPlanDraftV2
PlanReviewResultV2
WorkflowSignalV1
```

`RoutingDecision`은 Agent Output이 아니라 결정적 Supervisor의 결과다. Agent는 다음 Agent를 직접 선택·호출하지 않고 `SubgraphReturnV2(typed_result, disposition, workflow_signal)`을 반환한다.

경계:

- Tool Route Subgraph가 IN Resource/Connector/허용 Read Tool 범위와 OUT Resource/Effect/Tool을 한 번 확정하되 `InputRoutePlanV1`과 `OutputPlanV1`은 독립 revision/based_on을 가진다. OUT 변경만으로 기존 IN Retrieval을 무효화하지 않는다. Release Graph에서 READ Tool은 `InputRoutePlanV1`에만 배치하고 `OutputPlanV1`의 Action Route는 `CREATE | UPDATE | SEND | DELETE`만 허용한다. Domain의 `READ` Effect 지원은 호환 계약으로 유지하지만 새 Planning 결과가 READ Action을 생성하는 근거로 사용하지 않는다. Registry binding은 signed registry의 Resource·Effect·Schema 적합성에 따른 결정적 eligibility filtering만 수행하며 모델 편의를 위한 heuristic shortlist로 등록 Tool을 임의 제거하지 않는다.
- Tool Route에는 결정적 `PolicyPreconditionResolver` 경계를 둔다. LLM의 의미 Route 후보와 `01-B` 정책을 입력으로 필수 사전 READ를 IN 후보에 합성한 뒤 Registry binding한다. P0 고정 규칙은 `TASK + CREATE → 기존 미완료 Task 중복 검사`, `CALENDAR + CREATE → 대상 Calendar Event/FreeBusy 충돌 검사`다. 이 Resolver는 OUT Tool을 바꾸거나 새로운 사용자 목표를 추론하지 않는다. 사용자의 명시적 Source·기간·Resource 범위를 벗어나는 필수 READ가 필요하면 즉시 Route에 합치지 않고 `SCOPE_EXPANSION_REQUIRED` Confirmation 계약을 생성한다. 실제 사용자 응답을 받은 Application만 `PolicyConfirmationReceiptV1`을 만들 수 있으며 `APPROVED` Receipt의 `decision_context_hash`가 현재 Route Context와 일치할 때만 승인된 범위 확장을 Input Route로 materialize한다. 거절·누락·stale Receipt 상태에서 필수 검사를 우회한 Write는 금지한다.
- Tool ID·Scope·Effect·Schema Version 결합은 Signed Tool Registry를 기준으로 수행한다.
- Tool Route LLM은 먼저 IN/OUT Resource·Effect만 판단하고, Policy Precondition 합성과 Registry 후보 결합은 결정적 코드가 수행한다. 후보가 여러 개일 때만 Route Subgraph 내부 선택 Node를 사용한다.
- Retrieval Subgraph는 `ToolRoutePlanV2.input_plan.input_routes`를 읽고 그 안의 `allowed_read_tool_ids`만 사용한다. Connector/Tool 종류를 LLM이 다시 선택하지 않는다.
- 실제 Query·Page Token·MCP Arguments는 Retrieval Subgraph의 결정적 Application Node가 확정하고 `ConnectorReadPort`를 호출한다.
- Retrieval은 Normalize/Segment와 Run-scoped RAG를 거쳐 `RetrievalResultV1`을 Parent에 반환한다.
- Planning Subgraph는 `ToolRoutePlanV2.output_plan`이 `ActionOutputPlanV1`인 경우 그 `output_routes[].selected_tool_id`를 그대로 사용하고 Tool을 다시 선택하지 않는다. `selected_tool_id`와 route identity는 결정적 Plan Assembler가 Action에 materialize하며 Argument Writer의 LLM 출력 Schema에는 Tool 재선택 필드를 두지 않는다. 각 Argument Node에는 `user_request + OutputToolRouteV1` 1개와 해당 Tool Schema, optional Work Analysis, Evidence Reference만 Projection한다.
- Agent 간 대용량 원문 전달 대신 Cache Handle·Resource·Evidence·Segment ID를 사용한다.
- `SINGLE_BASELINE`은 동일 의미 책임을 Unified Subgraph 안에서 수행할 수 있으나 Main/Local State와 Tool Route 단일 권위 계약은 동일하다.

## 6. MCP 연결

- Transport: `stdio`
- MCP Server는 Local Agent Service가 관리하는 자식 프로세스다.
- MCP Client Adapter가 허용 Tool을 Application Port에 연결한다.
- MCP Server는 LLM·LangGraph·Domain 상태 전이를 포함하지 않는다.
- MCP 종료 시 Local Service가 최대 1회 재시작하고 Tool 목록·Schema Version을 다시 검증한다.
- Write 전달 가능성이 있으면 자동 재전송하지 않고 `UNKNOWN_RESULT`로 전환한다.
- MCP Client Adapter는 실패를 단순 Timeout/Error Name이 아니라 `delivery_certainty`와 함께 반환한다. `NOT_SENT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST`를 사용하며 `NOT_SENT`만 Google 변경이 없다고 확정할 수 있다.
- 제품 Runtime은 **registered connector_id당 하나의 active stdio MCP child process**를 가진다. P0에는 `google_workspace` 하나만 있으므로 process가 하나다. `MCPClientPort`의 list/call/restart와 ConnectorRead/Write/OAuthCredential Port는 connector_id를 잃지 않으며 concrete runtime registry가 해당 connector의 process handle로 resolve한다. target 없는 `restart_once()`는 금지한다.

## 7. Gmail Tool

```
gmail_search_threads
gmail_get_thread
gmail_get_message
gmail_get_attachment
gmail_create_draft
gmail_update_draft
gmail_get_draft
gmail_send
```

`gmail_send`는 승인 필수 `SEND` Effect다. 승인된 수신자·CC·제목·본문·Thread Hash와 일치할 때만 실행하며 전달 여부가 불명확하면 자동 재전송하지 않는다. Gmail Message·Thread 삭제 Tool은 등록하지 않는다.

## 8. Tasks Tool

```
tasks_list_tasklists
tasks_list_tasks
tasks_get_task
tasks_create_task
tasks_update_task
tasks_delete_task
```

`tasks_update_task`는 승인된 완료 상태 변경을 지원한다. `tasks_delete_task`는 정확한 Task ID를 대상으로 하는 승인형 `DELETE`이며 Claim V2 검증 후 실행하고 `GET_ABSENT`로 대상 부재를 검증한다.

Google Tasks Adapter의 raw `due`는 제품 내부 `scheduled_date`의 Provider 매핑값이다. **제품 Core의 Local API·Application·Agent·UI 계약은 `scheduled_date`를 canonical 의미 필드로 사용하고, Google Workspace MCP Server 내부 Tasks Provider Adapter가 outbound `scheduled_date → due`와 inbound `due → scheduled_date` 변환을 결정적으로 수행한다.** Connector Tool wire/schema에 Provider 호환 `due?`가 노출되는 경우에도 이는 Adapter 경계의 표현이며 Product Prompt나 Core Domain 의미를 `due`로 재정의하지 않는다. `business_deadline`은 Google Task Write의 구조화 Argument가 아니며 `due`로 자동 매핑하지 않는다. Task 시간 구간도 현재 Tool 계약의 필드가 아니다.

## 9. Calendar Tool

```
calendar_list_calendars
calendar_list_events
calendar_query_freebusy
calendar_get_event
calendar_create_event
calendar_update_event
calendar_delete_event
```

`calendar_update_event`는 승인된 참석자 추가·수정을 지원한다. `calendar_delete_event`는 승인 필수 DELETE Effect다. 반복 Event 전체 일괄 수정은 등록하지 않는다.

### 9-A. Local Runtime provisioning wire contract

```python
InferenceTierV1 = Literal["WORKER", "REASONING"]

class LocalProvisioningComponentV1:
    component_kind: Literal["OLLAMA_RUNTIME", "WORKER_MODEL", "REASONING_MODEL"]
    status: Literal["PENDING", "DOWNLOADING", "INSTALLING", "VERIFYING", "READY", "FAILED"]
    progress_percent: int | None
    downloaded_bytes: int | None
    total_bytes: int | None
    error_code: str | None

class LocalRuntimeProvisioningStatusV1:
    schema_version: Literal[1]
    overall_status: Literal["NOT_REQUIRED", "NOT_STARTED", "IN_PROGRESS", "READY", "REPAIR_REQUIRED", "FAILED"]
    runtime_origin: Literal["NONE", "PREEXISTING", "PRODUCT_PROVISIONED"]
    active_profile_id: str | None
    components: list[LocalProvisioningComponentV1]
    retryable: bool

class ProvisionLocalRuntimeRequestV1:
    schema_version: Literal[1]
    command_id: str

class ProvisionLocalRuntimeResponseV1:
    schema_version: Literal[1]
    operation_ref: str
    status: LocalRuntimeProvisioningStatusV1
```

- Browser는 URL, installer path, version, model ID, digest 또는 shell argument를 보내지 않는다.
- Application은 `OperationalCommandReplayPort`로 command/hash/result를 판정하고 verified `ModelManifestV2 + LocalModelProductDecisionV2`의 hash/profile binding을 검증한 뒤 `LocalRuntimeProvisioningPort`만 호출한다.
- same command replay는 같은 `operation_ref`와 현재 status를 반환하며, unresolved reservation은 Adapter reconciliation 후에만 재개한다.
- `RuntimeDetailResponseV2.local_runtime_provisioning`이 current operation/profile/component progress를 bounded projection한다. V1 response에 필드를 소급 추가하지 않는다.
- `API_ONLY`에서는 `NOT_REQUIRED`이며 provisioning Command는 deterministic unsupported result를 반환하고 side effect 0이다.

## 10. 내부 결정 인터페이스

다음 책임은 MCP Tool이 아니라 **각 semantic owner의 결정적 Application operation**으로 유지한다. 하나의 generic `service.py`/`manager.py`/`helper.py`로 합치지 않고 16 Repository Architecture의 owner-local operation-per-file 규칙으로 배치한다.

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

Write Tool 호출은 Tool별 실제 Arguments와 서버가 발급한 `claim_token`(`ClaimContextV2`)을 사용한다. **Application은 same Attempt의 `BeginExecutionAttempt(applied=true)`가 확인된 뒤에만 이 호출을 시작한다.** `ClaimExecution` 자체도 Action/Approval/version/hash뿐 아니라 owning Plan이 current published `WAITING_APPROVAL`이고 parent Run이 `WAITING_APPROVAL | VERIFYING`인지 같은 UoW에서 확인한다. `SUPERSEDED` Plan child는 Claim/Attempt authority가 아니다. 실행권 식별자와 Hash를 Browser 입력으로 다시 받지 않는다.

```
tool_arguments
claim_token   # signed ClaimContextV2
```

`ClaimContextV2`는 `action_id`, `approval_id`, `execution_attempt_id`, `tool_name`, `approval_arguments_hash`, `execution_arguments_hash`, Service/MCP Process binding, TTL, Nonce를 결합한다. 이는 Claim 무결성 증명이지 단독 dispatch authority가 아니다.

**Post-Begin process-loss contract:** `BeginExecutionAttempt(applied=true)` commit은 actual provider call 여부를 증명하는 marker가 아니라 **dispatch-intent uncertainty cut**이다. 그 commit 이후 `StoreSuccess|MarkFailed|MarkUnknownResult`가 durable해지기 전에 process가 사라지면 restart에서 `NOT_SENT`를 추정하지 않는다. Startup-only `execution_attempt.reconcile_inflight_executions` batch Command가 durable phase candidates를 reconcile하며 original Connector Write를 재호출하지 않는다. Live workflow reconciliation은 이 operation을 호출하지 않는다.

```python
ExecutionReconciliationCandidateKindV1 = Literal[
    "POST_BEGIN_ORPHAN",
    "UNKNOWN_RESULT_UNRESOLVED",
    "EXECUTED_AWAITING_VERIFICATION",
    "FAILED_AWAITING_CONTINUATION",
]

class ExecutionReconciliationCandidateV1:
    schema_version: Literal[1]
    kind: ExecutionReconciliationCandidateKindV1
    execution_attempt_id: str
    action_id: str
    run_id: str

class ReconcileInflightExecutionsCommand:
    schema_version: Literal[1]
    limit: int

class ReconcileInflightExecutionsResult:
    schema_version: Literal[1]
    processed_count: int
    progressed_count: int
    has_more: bool
```

이 **Command/Result**는 startup Application reconciliation contract이며 Connector dispatch callable이 아니다. `limit`은 `1..256` bounded이며 `has_more=true`면 startup lifespan이 같은 injected Handler를 다시 호출할 수 있다. `ExecutionAttemptRepository.list_reconciliation_candidates(limit)`의 phase는 durable facts로만 정해진다. `POST_BEGIN_ORPHAN`은 `system:execution-attempt-reconcile:<execution_attempt_id>`로 `MarkUnknownResult(MAY_HAVE_BEEN_SENT)`를 apply/replay한다. `UNKNOWN_RESULT_UNRESOLVED`는 existing-result lookup을 반복 가능하게 수행하고 `RecoverExistingResult | ResolveAsFailed | RequireRecovery(UNKNOWN_RESULT)`를 deterministic sub-command identity로 apply/replay한다. matching `RECOVERY_REQUIRED` context가 이미 durable하면 이 candidate는 완료로 본다. `EXECUTED_AWAITING_VERIFICATION`은 current Run 상태에 따라 `BeginVerification` 또는 `ResolveRecovery(RECHECK)`를 apply/replay한 뒤 `system:execution-attempt-reconcile:<execution_attempt_id>:verification` trigger로 `MAIN_CONTROL:VERIFICATION` durable handoff를 stage/reuse한다. `FAILED_AWAITING_CONTINUATION`은 reconciliation의 deterministic `ResolveAsFailed` receipt가 존재하고 cancel intent 또는 다른 approved/executable Action 때문에 자동 continuation이 실제 필요한 경우에만 생성되며, `:post-failed` trigger로 `CANCEL_RESOLUTION | PREFLIGHT` 중 current guard가 허용한 하나를 stage/reuse한다. retry/user-decision을 기다리는 stable FAILED는 candidate가 아니다. Reconciliation이 stage하는 `VERIFICATION | CANCEL_RESOLUTION | PREFLIGHT` handoff는 latest same-run typed checkpoint의 run/thread/profile/graph-version과 `ResumeTargetRegistry`의 exact registered target을 사용하며 arbitrary latest-target guessing은 금지한다; binding이 유효하지 않으면 기존 `CHECKPOINT_MISMATCH` Recovery를 사용한다. 각 phase commit 직후 crash가 나도 다음 startup이 새 durable state에서 다시 candidate를 계산하므로 synchronous call-stack을 recovery authority로 사용하지 않는다.

Core가 `BeginExecutionAttempt(applied=true)`를 통과한 뒤 MCP는 실제 수신 Tool Arguments를 같은 Canonical 규칙으로 재해시해 `execution_arguments_hash`와 일치할 때만 Provider Write를 호출한다. Browser는 `claim_token`을 생성하거나 Write Tool을 직접 호출하지 않는다.

## 12. 읽기 Port 계약

`ConnectorReadPort`는 Provider별 메서드를 증식시키지 않고 **registered READ Tool invocation 하나**만 소유한다. Application의 Retrieval/Browse/Verification/Recovery operation이 §27 Registry에서 Tool을 선택하고 입력 Schema를 검증한 뒤 호출한다.

`ConnectorReadResultV1`의 exact field shape는 §17.1이 한 번만 정의한다. Port callable은 다음 하나다.

```python
class ConnectorReadPort(Protocol):
    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JSONValue],
    ) -> ConnectorReadResultV1: ...
```

- Application은 Port 호출 전에 `SignedToolRegistry.bind_required(connector_id, tool_id, expected_effect=READ)`를 수행하며, `execute_read`는 그 결과인 `ValidatedConnectorToolBindingV1`을 Port boundary에서 끝까지 보존한다. `tool_id`만 전달하거나 Adapter가 `application/tool_registry/**`를 재조회하는 경로는 금지한다.
- `tool_arguments`는 `binding`이 가리키는 §27 Tool Input Schema를 통과한 값만 허용하고, output도 같은 binding의 Tool Output Schema 검증을 통과한 뒤 `ConnectorReadResultV1`으로 반환한다.
- Provider raw response/token은 Connector MCP Server 내부 Adapter에만 존재한다.
- Gmail/Tasks/Calendar별 capability 이름은 §27의 MCP Tool ID가 canonical name이며 Core Port에 별도 `list_gmail` 같은 두 번째 API vocabulary를 만들지 않는다.
- 일반 Retrieval 호출은 Action Row를 만들지 않는다.
- Connector READ는 Retrieval 내부에서만 실행하며 Action Row를 만들지 않는다.
- READ Output Schema 실패는 Retrieval failure/disposition으로 닫고 별도 READ Action lifecycle로 투영하지 않는다.

## 13. 승인·실행 계약

- Approval은 Tool Name, Arguments Hash, Action Version, Source Snapshot, Policy Version, Tool Schema Version과 만료 시각을 연결한다.
- 실행 직전 최신 Resource·Hash·Dependency·중복·충돌을 다시 검증한다.
- Approval TTL 만료 또는 current Source/Policy/Tool-Schema/approval business snapshot binding이 승인 시점과 달라 기존 Approval을 재사용할 수 없으면 Write를 호출하지 않고 `ExpireApproval → RefreshExpiredAction → fresh Review PASS → new ApproveAction` 순서로 간다.
- current deterministic Policy가 `DENY`이면 stale-refresh로 우회하지 않고 Claim 전에 `BlockRun`을 적용한다.
- `BeginExecutionAttempt(applied=true)` 이후 MCP pre-provider validation에서 `CLAIM_ARGUMENTS_MISMATCH`가 발생하면 Provider Write는 0이며 delivery certainty=`NOT_SENT`; `MarkFailed`로 Attempt/Action을 `FAILED`로 기록하고 자동 재전송하지 않는다.
- 기존 Approval을 다시 `ACTIVE`로 만들지 않는다.
- 승인 이후 LLM은 Tool·Arguments·대상 Resource를 변경하지 않는다.
- Action modify/retry/expired-refresh 뒤 fresh Review PASS가 필요한 durable gate는 current Plan/Action revision에 bind된다. 06의 deterministic `validate_review`가 끝난 뒤 Application persistence operation `plan.record_review_result(RecordReviewResultCommandV1)`만 이 결과를 durable gate에 기록한다. command는 `command_id + plan_id + expected_plan_version + review_artifact_id + review_version + disposition + based_on_action_versions`를 포함하며 current revision mismatch는 conflict다. `PASS`만 `PASSED` gate를 열 수 있고 `REVISE | RETRIEVE_MORE | ROUTE_RECONSIDERATION | CONFIRM | BLOCK`은 모두 durable fact로 기록하되 Approval gate를 열지 않는다. Published Plan의 `ROUTE_RECONSIDERATION`과 `CONFIRM` Domain guard는 이 동일 durable writer의 current disposition을 읽는다. 이 operation은 Approval/Action lifecycle transition을 수행하지 않으며 FastAPI/Workflow의 DB 직접 write와 SQL semantic invention은 금지한다.

```python
class RecordReviewResultCommandV1:
    schema_version: Literal[1]
    command_id: str
    plan_id: str
    expected_plan_version: int
    review_artifact_id: str
    review_version: int
    disposition: Literal["PASS", "REVISE", "RETRIEVE_MORE", "ROUTE_RECONSIDERATION", "CONFIRM", "BLOCK"]
    based_on_action_versions: dict[str, int]

class RecordReviewResultResultV1:
    schema_version: Literal[1]
    applied: bool
    current_plan_version: int
    recorded_review_version: int | None
    review_gate: Literal["REQUIRED", "PASSED"]
    result_code: str
```

`record_review_result`는 external I/O와 Action/Approval mutation을 하지 않는다. stale Plan/Action version에서는 `applied=false`이며 이전 PASS를 새 revision에 승계하지 않는다.

## 14. Answer-only 계약

```
complete_answer_only_run
ANALYZING | RETRIEVING | PLANNING → COMPLETED
```

Plan·Action 없이 **final ASSISTANT Message + Run terminal mutation + required Audit**를 같은 Application UoW로 원자 저장한다. Diagnostic Trace와 SSE Projection은 commit 이후 별도 best-effort/post-commit 경계에서 기록·전달하며 terminal transaction의 원자성에 포함하지 않는다.

일반 Connector READ는 `InputRoutePlanV1 → Retrieval`이 소유한다. 내부 호환 READ Plan/Action Command 또는 별도 READ lifecycle은 없다.

## 15. Write 실패·재시도 계약

Write가 Google을 변경하지 않았음이 확실한 경우:

```
mark_failed
Action EXECUTING → FAILED
Attempt → FAILED
```

재시도 준비:

```
prepare_write_retry
Action FAILED → MODIFIED
```

필수 조건:

- 새 Approval
- 새 Idempotency Key
- 최신 Source Snapshot
- 새 ExecutionAttempt ID와 새 Approval 내부 `attempt_no = 1`

금지:

```
FAILED → EXECUTING
UNKNOWN_RESULT → EXECUTING
기존 Approval 재활성화
```

## 16. 검증·UNKNOWN_RESULT 계약

- Write Tool은 Resource ID와 최소 응답 Metadata를 반환한다.
- CREATE·UPDATE·Task 완료·참석자 변경은 대응 GET으로 재조회한다.
- DELETE는 대상 GET의 NOT_FOUND/삭제 상태를 확인한다.
- SEND는 Message/Thread 식별자 또는 결정적 전송 식별자로 Sent 결과를 조회한다.
- 일반 코드가 Effect별 expected·actual을 정규화하고 `VerificationResultV1`을 만든다.
- `UNKNOWN_RESULT`에서는 새 Attempt·Write를 금지한다.
- CREATE는 `RESOURCE_SEARCH`로 Recovery Fingerprint 기반 Resource Search를 수행한다.
- UPDATE는 `GET_TARGET`으로 기존 Target 상태를 조회한다.
- SEND는 `MESSAGE_SEARCH`로 기존 전송 결과 후보를 찾고, 후보가 식별되면 `SENT_LOOKUP` 검증으로 연결한다.
- DELETE는 `GET_TARGET`으로 대상 상태를 조회하고, 대상 부재/삭제 상태가 확인되면 `GET_ABSENT` 검증으로 연결한다.
- `NOT_FOUND` 또는 `ERROR` 한 번만으로 실패를 즉시 확정하지 않는다.

## 17. 오류 Enum

```
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

```
error_code
user_message
retryable
current_state
request_id
detail_code?
```

Stack Trace·SQL·Secret은 Frontend에 반환하지 않는다.

### 17.0 Run Budget · Component Circuit Application contracts

10 Infrastructure가 limit/circuit semantics와 `ComponentCircuitStateV1`을 소유하고, 06 Workflow가 current `RunBudgetV2` state를 소유한다. Application callable schema는 이 Interface 문서가 다음처럼 고정한다.

```python
RunBudgetOperationKindV1 = Literal[
    "LLM_CALL", "CONNECTOR_CALL", "SOURCE_PAGE", "DETAIL_FETCH",
    "RETRY_ATTEMPT", "CONTEXT_MATERIALIZATION"
]

class RunBudgetDeltaV1:
    schema_version: Literal[1]
    operation_kind: RunBudgetOperationKindV1
    units: int                      # >= 1, CONTEXT_MATERIALIZATION은 token count

class GuardRunBudgetQueryV1:
    schema_version: Literal[1]
    run_id: str
    current_budget: RunBudgetV2
    requested_delta: RunBudgetDeltaV1
    now_ms: int

class GuardRunBudgetResultV1:
    schema_version: Literal[1]
    allowed: bool
    reason_code: Literal[
        "OK", "MAX_EXECUTION_TIME", "LLM_LIMIT", "CONNECTOR_LIMIT",
        "SOURCE_PAGE_LIMIT", "DETAIL_FETCH_LIMIT", "RETRY_LIMIT", "CONTEXT_LIMIT"
    ]
    remaining_units: int
    elapsed_ms: int

class CheckComponentCircuitQueryV1:
    schema_version: Literal[1]
    key: ComponentCircuitKeyV1
    now_ms: int

class CheckComponentCircuitResultV1:
    schema_version: Literal[1]
    key: ComponentCircuitKeyV1
    allowed: bool
    state: Literal["CLOSED", "OPEN"]
    retry_at_ms: int | None
    reason_code: Literal["OK", "CIRCUIT_OPEN"]

class RecordComponentCallResultCommandV1:
    schema_version: Literal[1]
    key: ComponentCircuitKeyV1
    outcome: Literal["SUCCESS", "TECHNICAL_FAILURE"]
    failure_code: str | None
    now_ms: int

class RecordComponentCallResultResultV1:
    schema_version: Literal[1]
    key: ComponentCircuitKeyV1
    state: ComponentCircuitStateV1
    transition: Literal["UNCHANGED", "OPENED", "CLOSED", "REOPENED"]
```

- `guard_run_budget`는 허용 여부만 계산하며 counter mutation은 owning Workflow/Application state update에서 한 번만 반영한다. 거절된 delta는 사용량에 더하지 않는다.
- outbound LLM/Connector call 직전에는 `guard_run_budget`와 해당 `check_component_circuit`를 모두 통과해야 한다.
- Connector call의 circuit key는 항상 `ComponentCircuitKeyV1(kind=CONNECTOR, connector_id=<route connector_id>)`이다. 두 번째 Connector 추가 시 Core enum을 수정하지 않는다. LLM call은 `kind=LLM_RUNTIME, llm_runtime=API_LLM|LOCAL_GPU`를 사용한다. MCP Server 내부 Provider별 더 세밀한 circuit이 필요하면 Connector 내부 구현 세부사항이며 Core `ComponentCircuitStatePort`의 competing authority가 아니다.
- Circuit에는 **technical failure만** 기록한다. Policy deny, schema invalid, user cancel, semantic mismatch를 component failure로 세지 않는다.
- `TECHNICAL_FAILURE`이면 `failure_code`는 필수, `SUCCESS`이면 `failure_code=None`이다. `record_component_call_result`는 process-local `ComponentCircuitStatePort`만 변경하고 Domain/Run status를 변경하지 않는다.

### 17.1 Port result value contracts

```python
class ConnectorReadResultV1:
    schema_version: Literal[1]
    tool_id: str
    request_id: str
    output: dict[str, JSONValue]
    next_page_token: str | None
    total_count: int | None

class ConnectorWriteResultV1:
    schema_version: Literal[1]
    success: bool
    delivery_certainty: Literal["NOT_SENT", "MAY_HAVE_BEEN_SENT", "SENT_RESPONSE_LOST"] | None
    provider_request_id: str | None
    response_metadata: dict[str, JSONScalar] | None
    error_code: str | None

class StructuredInferenceRequestV2:
    schema_version: Literal[2]
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    inference_tier: InferenceTierV1
    prompt_ref: PromptRefV1
    input_projection: JSONValue
    output_schema_ref: str

class StructuredInferenceResultV2:
    schema_version: Literal[2]
    structured_output: dict[str, JSONValue]
    provider: str
    model: str
    inference_tier: InferenceTierV1
    local_model_profile_id: str | None
    actual_runtime: Literal["LOCAL_GPU", "API_LLM"]
    input_tokens: int
    output_tokens: int
    latency_ms: int
    fallback_reason: str | None

AccessContextHandle = str  # opaque, process-local handle; raw OAuth token이 아님
```

- successful Connector Write에서는 `delivery_certainty=None`이며 `success=true`가 confirmed response를 뜻한다. 오류/response-loss에서는 §30의 delivery classification을 반드시 채우며 exception class만으로 값을 추론하지 않는다.


### Execution · Verification · UNKNOWN_RESULT Application boundary

External I/O orchestration과 Domain persistence를 같은 operation/file에 합치지 않는다. 16 Repository Architecture가 exact path/symbol을 소유하며 이 문서는 callable contract를 소유한다.

```python
class DispatchConnectorWriteCommandV1:
    action_id: str
    approval_id: str
    execution_attempt_id: str
    tool_id: str
    tool_arguments: dict[str, object]
    claim_context: ClaimContextV2

class DispatchConnectorWriteResultV1:
    connector_result: ConnectorWriteResultV1

class ClassifyDispatchResultQueryV1:
    schema_version: Literal[1]
    dispatch_result: DispatchConnectorWriteResultV1

class DispatchPersistenceDecisionV1:
    schema_version: Literal[1]
    disposition: Literal["STORE_SUCCESS", "MARK_FAILED", "MARK_UNKNOWN_RESULT"]
    delivery_certainty: Literal["NOT_SENT", "MAY_HAVE_BEEN_SENT", "SENT_RESPONSE_LOST"] | None
    reason_code: str | None

class VerifyEffectQueryV1:
    run_id: str
    action_id: str
    execution_attempt_id: str
    effect: Literal["CREATE", "UPDATE", "DELETE", "SEND"]
    expected_effect: dict[str, object]
    target_resource_ref: SelectedResourceRefV1 | None

class VerificationResultV1:
    status: Literal["VERIFIED", "MISMATCH"]
    strategy: Literal["GET_COMPARE", "GET_ABSENT", "SENT_LOOKUP"]
    expected_normalized: dict[str, object]
    actual_normalized: dict[str, object] | None
    evidence_refs: list[str]
    reason_codes: list[str]

class LookupUnknownResultQueryV1:
    run_id: str
    action_id: str
    execution_attempt_id: str
    effect: Literal["CREATE", "UPDATE", "DELETE", "SEND"]
    recovery_fingerprint: str
    target_resource_ref: SelectedResourceRefV1 | None

class UnknownResultLookupResultV1:
    disposition: Literal["MUTATION_FOUND", "MUTATION_NOT_FOUND", "UNRESOLVED"]
    strategy: Literal["RESOURCE_SEARCH", "GET_TARGET", "MESSAGE_SEARCH"]
    candidate_resource_refs: list[str]
    evidence_refs: list[str]
    reason_codes: list[str]
```

Deterministic ownership:

- `execution_attempt.dispatch_connector_write`의 precondition은 **same Attempt에 대한 successful `BeginExecutionAttempt` Receipt/Result가 `applied=true`, current `execution_attempt.status == EXECUTING`, current Claim/Approval/`ClaimContextV2` binding 유효, 그리고 그 Claim이 current non-SUPERSEDED published Plan authority에서 발급됨**이다. `BeginExecutionAttempt` adjudication 자체가 `cancel_intent_active == false`를 검사하므로 `ClaimExecution` Commit만으로는 이 precondition을 만족하지 않는다. Handler는 이 eligibility를 read-only로 검증하고 최종 approved-vs-execution argument hash를 재검증한 뒤에만 `ConnectorWritePort.execute_write`를 정확히 한 번 호출해 `DispatchConnectorWriteResultV1`을 반환한다. 어느 precondition이라도 실패하면 external call은 0이며 DB mutation/Verification도 하지 않는다. **`BeginExecutionAttempt` Commit 뒤에 새 `RequestCancel`이 APPLIED되면 이미 시작된 Attempt를 소급 무효화하지 않고 in-flight cancel 규칙으로 결과를 확정한다; 그 cancel intent는 이후 신규 Claim/Write를 차단한다.**
- `execution_attempt.classify_dispatch_result`는 `ClassifyDispatchResultQueryV1(dispatch_result=DispatchConnectorWriteResultV1)`만 입력으로 받아 `DispatchPersistenceDecisionV1`을 만든다. `success=true → STORE_SUCCESS`; `success=false + delivery_certainty=NOT_SENT → MARK_FAILED`; `MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST → MARK_UNKNOWN_RESULT`. exception class·HTTP status 이름만으로 `MARK_FAILED`를 선택하지 않는다. external I/O/DB mutation 0이다.
- `execution_attempt.store_success | mark_failed | mark_unknown_result`만 위 decision에 따라 dispatch 결과를 Domain/Repository에 기록한다. External call 중 SQLite transaction은 0이다.
- `verification.verify_effect`는 Effect별 strategy를 결정적으로 선택해 `ConnectorReadPort`로 재조회하고 `VerificationResultV1`을 만든다. Domain 상태를 직접 변경하지 않는다.
- Verification normalization은 01-A FN-071의 **representation-preserving category**만 소비한다: 의미가 같은 공백/줄바꿈, 동일 instant의 timezone 표현, 계약된 초 단위 정밀도, Connector가 명시적으로 제공하는 의미-중립 default. Connector별 canonicalization algorithm/data structure는 00의 implementation choice이며 새 Port/owner가 아니다. 사용자 의미·대상·참석자·상태·날짜 의미 같은 business field 차이를 normalization으로 숨기면 contract failure다.
- `verification.store_verification`만 `VerificationResultV1`을 durable Verification과 Action fact에 반영한다. `MISMATCH`가 Recovery를 요구하면 Run 전이는 별도 `recovery.require_recovery(VERIFICATION_MISMATCH)`가 소유하며 Verification persistence와 같은 operation/UoW에 숨겨 합치지 않는다.
- `recovery.lookup_unknown_result`는 새 Write 없이 `ConnectorReadPort`로 기존 외부 결과만 찾고 `UnknownResultLookupResultV1`을 반환한다. `MUTATION_FOUND`면 `execution_attempt.recover_existing_result` 뒤 Run이 `WAITING_APPROVAL | CANCEL_REQUESTED`이면 `BeginVerification`, 이미 `RECOVERY_REQUIRED`이면 changed external-state fingerprint 기반 `ResolveRecovery(RECHECK)`를 먼저 적용한 후 `verification.verify_effect`로 간다. `MUTATION_NOT_FOUND`가 외부 미변경을 결정적으로 증명할 때만 `execution_attempt.resolve_as_failed`, `UNRESOLVED`면 `RequireRecovery(UNKNOWN_RESULT)`로 suspend하거나 이미 Recovery면 그 상태를 유지한다.

- `response_metadata`는 bounded metadata만 허용하고 Provider raw body/secret/token을 보존하지 않는다.
- `StructuredInferenceResultV1.structured_output`은 요청된 `output_schema_ref` 검증을 통과한 JSON-compatible object다. Schema 검증 실패는 이 Result의 성공 payload가 아니라 15의 bounded repair/failure path다.

## 18. LLM Provider Adapter

공통 인터페이스:

```
invoke_structured(prompt_ref, input, output_schema, runtime_policy, trace_context)
```

반환:

```
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
- Answer-only·Legacy/호환 READ-only·WRITE Plan
- 승인·수정·만료·일부 승인
- Write 실패 재시도
- `UNKNOWN_RESULT` 복구
- OAuth 재인증
- SSE 재연결·앱 재시작
- MCP 장애

---


## 20. Health·PromptRef 계약

- 인증 전 최소 상태: `GET /health/live`, `GET /health/ready`
- Local Session 이후 상세 Runtime: `GET /api/v1/runtime`
- LLM Adapter: `invoke_structured(prompt_ref, input, output_schema, runtime_policy, trace_context)`
- PromptRef는 Bundle·ID·Version·Hash·Agent·Subgraph·Node·State·Purpose·Schema Version을 포함한다.
- Prompt 원문은 Trace·Audit·Error Response에 포함하지 않는다.

## 21. 인증 Matrix

| Endpoint | 기존 Local Session | 추가 검증 |
| --- | --- | --- |
| `GET /health/live` | 없음 | Loopback·Method 제한 |
| `GET /health/ready` | 없음 | Loopback·Launcher 요청 제한 |
| `POST /api/v1/session/bootstrap` | 없음 | 1회용 Bootstrap Secret·TTL·Service Instance |
| OAuth Loopback Callback | 없음 | `state`·PKCE·Listener Instance |
| `GET /api/v1/runtime` | 필수 | Session·Origin·Host |
| 나머지 `/api/v1/*` | 필수 | Session·Origin·Host·Fetch Metadata·Schema |

Bootstrap 오류: `BOOTSTRAP_EXPIRED`, `BOOTSTRAP_REUSED`, `BOOTSTRAP_INSTANCE_MISMATCH`.

## 22. Command Replay·Receipt 계약

`command_id`가 있는 상태 변경 Endpoint는 다음 Envelope를 사용한다. **Domain Aggregate lifecycle mutation과 non-Domain operational side effect의 durable replay authority는 서로 다르다.**

```
command_id: UUID
expected_version: int?
request_schema_version: int
```

Application command handler는 Canonical Request Hash를 생성한다. Domain Aggregate lifecycle mutation은 04 SQLite `command_receipts`와 Domain 변경을 같은 Transaction에 저장한다. Connection/Credential/Settings/Runtime Mode/Backup·Restore/Diagnostics/Shutdown/Attachment staging 같은 non-Domain command는 §OperationalCommandReplayPort로 adjudicate하며 Domain SQLite receipt를 사용하지 않는다.

- 동일 ID·동일 Hash·완료: 해당 authority가 저장한 기존 bounded result 반환
- 동일 ID·다른 Hash: HTTP 409 `DUPLICATE_COMMAND`
- 다른 ID·오래된 Version: HTTP 409 `VERSION_CONFLICT`


### 23.1 Non-Domain operational command replay authority

Domain lifecycle mutation만 04 SQLite `command_receipts`를 사용한다. Connection/Credential/Settings/Runtime Mode/Backup/Restore/Diagnostics/Shutdown/Attachment staging 같은 non-Domain operational Command는 별도 `OperationalCommandReplayPort` 하나를 사용한다.

```python
class OperationalCommandContextV1:
    command_id: str
    operation_kind: str
    canonical_request_hash: str

class OperationalReplayDecisionV2:
    decision: Literal["PROCEED_NEW", "REPLAY_COMPLETED", "RECOVER_RESERVED", "CONFLICT"]
    reservation_status: Literal["RESERVED", "UNCERTAIN", "COMPLETED"] | None
    operation_ref: str | None
    stored_result_ref: str | None
    recovery_ref: str | None

class OperationalReconcileResultV1:
    status: Literal["COMPLETED", "SAFE_TO_RETRY", "UNCERTAIN"]
    result_ref: str | None
    bounded_result: JSONValue | None

class OperationalCommandReplayPort(Protocol):
    def reserve_or_replay(self, context: OperationalCommandContextV1) -> OperationalReplayDecisionV2: ...
    def mark_uncertain(self, context: OperationalCommandContextV1, recovery_ref: str) -> None: ...
    def store_result(self, context: OperationalCommandContextV1, result_ref: str, bounded_result: JSONValue) -> None: ...
```

`OperationalCommandReplayPort`는 side effect 전에 opaque server-owned `operation_ref`를 reserve하고 unresolved replay에서 `RECOVER_RESERVED`를 반환한다. `RECOVER_RESERVED`는 blind side-effect replay 권한이 아니며 아래 closed reconciliation callable 중 하나의 `OperationalReconcileResultV1`을 먼저 요구한다. `COMPLETED`는 기존 bounded result를 재사용하고, `SAFE_TO_RETRY`만 같은 `operation_ref`로 재시도를 허용하며, `UNCERTAIN`은 fail closed한다. same ID+different hash는 `CONFLICT`다. Reservation store의 concrete placement/durability는 `10 Infrastructure`와 `16 Repository Architecture`가 소유한다. `SAFE_CHECKPOINT_RESUME`의 stored/result ref는 `handoff_id`이며 unresolved reservation recovery는 existing handoff identity만 재사용한다.

### 23.2 Non-Domain replay result identities

| Operation | Durable replay result identity |
|---|---|
| connection start/disconnect | callback/connection bounded result id |
| credential store/delete | provider + resulting `LlmCredentialStatusV1` (secret 0) |
| settings update | canonical settings-result hash + bounded `SettingsViewV1` |
| runtime mode update | service instance + resulting `RuntimeModeStatusV1` |
| backup create | `backup_ref` |
| restore | selected `backup_ref` + bounded restore result |
| diagnostic bundle | `bundle_ref` |
| shutdown | service instance + accepted result |
| attachment staging | `staged_attachment_id` + descriptor only |

Operation-specific `RECOVER_RESERVED` surface is closed as follows; handler가 임의 `get_*`를 recovery authority로 승격하거나 raw adapter state를 탐색하지 않는다.

| Operation family | Canonical reconciliation callable |
|---|---|
| OAuth authorization start | `OAuthCredentialPort.reconcile_authorization_start(connector_id, operation_ref)` |
| Google disconnect/revoke | `OAuthCredentialPort.reconcile_revoke_connection(connector_id, account_id, operation_ref)` |
| LLM credential store/delete | `LlmCredentialPort.reconcile_credential(operation_ref, provider, target_state, storage_mode?)` |
| Settings update | `SettingsPort.reconcile_settings(operation_ref, settings_patch)` |
| Runtime mode update | `RuntimeModePort.reconcile_update(operation_ref, requested_mode)` |
| Backup / Restore | `BackupPort.reconcile_backup(operation_ref)` / `reconcile_restore(backup_ref, operation_ref)` |
| Diagnostics | `DiagnosticsPort.reconcile_bundle(operation_ref)` |
| Shutdown | `ShutdownPort.reconcile_shutdown(operation_ref)` |
| Attachment staging | `AttachmentStagingPort.reconcile_stage(operation_ref)` |

Application invokes an underlying side-effect Port only on `PROCEED_NEW`, passing the reservation's stable `operation_ref` to every mutable operation Port listed above. Filesystem Backup/Diagnostic/Attachment adapters derive their temp/final artifact identity from `operation_ref`; Restore writes/reads its pre-restore marker under the same ref. `REPLAY_COMPLETED` returns the stored bounded result without repeating the side effect. `RECOVER_RESERVED` calls only the operation-specific `reconcile_*` callable with that same `operation_ref`; Application does not scan raw filesystem paths. Only `OperationalReconcileResultV1.status=SAFE_TO_RETRY` permits a new effect attempt with the **same** operation_ref. `COMPLETED` is stored/replayed, `UNCERTAIN` remains fail-closed. `CONFLICT` returns 409. These four decisions are the complete non-Domain replay policy.

## 23. Local API Schema Catalog

### 24.1 공통

```
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

```
StartRunRequestV1
- command_id: str
- conversation_id: str
- entry_mode: AGENT_SEARCH | RESOURCE_SELECTED
- request_text: 1..65536 UTF-8
- selected_resource_handles: list[str], max 20
- requested_mode: AUTO | LOCAL_GPU | API_LLM

# server-owned; request에서 수신하지 않음
run_id
user_message_id
workflow_key
langgraph_thread_id

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
- context_preview?: ContextPreviewResponseV1
- pending_interrupt?: PendingInterruptResponseV1
- recovery?: RecoveryUiProjectionV1
- error?: ErrorUiProjectionV1
- external_llm_transfer_scope?: ExternalLlmTransferScopeV1
- terminal_result_kind: SUCCESS | PARTIAL | BLOCKED | FAILED | CANCELLED | NONE
- projection_version

`RunSnapshotResponseV1.context_preview`는 `run.project_context_preview`가 current selected Evidence/ResourceRef에서 만드는 deterministic projection이다. 기본은 read-only이며, `adjustment_allowed=true`일 때 Browser는 `allowed_adjustments`에 포함된 조정만 `POST /api/v1/runs/{run_id}/context-adjustments`로 보낸다. Browser는 Evidence/Plan/Run 상태를 직접 mutate하지 않는다.

`RunSnapshotResponseV1.error`는 `run.project_error_actions`의 deterministic projection이다. Browser는 error code/status에서 Action을 자체 추론하지 않는다.

- `PREPARE_RETRY`는 current Action=`FAILED`이고 latest dispatch `delivery_certainty=NOT_SENT`인 경우에만 `action_id`와 함께 포함한다.
- `UNKNOWN_RESULT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST`에는 `PREPARE_RETRY`를 절대 포함하지 않는다. 해당 경우는 `recovery` projection/Recovery flow만 사용한다.
- `REAUTHENTICATE_GOOGLE`은 durable Run=`REAUTH_REQUIRED`인 P0 Google connector flow에서만 포함한다.
- `RESUME_SAFE_CHECKPOINT`는 State Contract startup matrix가 현재 durable Run에 `SAFE_CHECKPOINT_RESUME`를 허용하고 binding/target/version 검증이 가능한 경우에만 포함한다.
- `OPEN_SETTINGS | OPEN_DIAGNOSTICS`는 navigation-only action이며 Domain mutation이 없다.
- generic `계획 다시 생성`, blind `다시 시도`, arbitrary `/resume` action은 current Error projection에 존재하지 않는다.

CancelRunRequestV2
- command_id
- expected_version
- reason?

ResumeRunRequestV2
- command_id
- expected_version
- resume_kind: REAUTH_COMPLETED | SAFE_CHECKPOINT_RESUME | RECOVERY_RECHECK

`SAFE_CHECKPOINT_RESUME` wire request는 status를 Browser가 지정하지 않는다. Server가 current durable Run snapshot을 읽어 State Contract matrix를 적용한다. `CREATED|ANALYZING|RETRIEVING|PLANNING` 외 status에서 이 resume_kind를 보내면 `RESUME_NOT_ALLOWED`로 fail closed하며 Domain mutation/Graph invocation 0이다.

RunRecoveryTargetV1
- target_kind: RUN

ActionRecoveryTargetV1
- target_kind: ACTION
- action_id

RecoveryTargetV1 = RunRecoveryTargetV1 | ActionRecoveryTargetV1

ResolveRecoveryCommandV1
- run_id
- expected_version
- target: RecoveryTargetV1
- resolution_kind: RECHECK | ACCEPT_PARTIAL | CREATE_CORRECTIVE_PLAN | CANCEL | FAIL
- recovery_context_version
- command_id

ResolveRecoveryRequestV1
- command_id
- expected_version
- target: RecoveryTargetV1
- resolution_kind: RECHECK | ACCEPT_PARTIAL | CREATE_CORRECTIVE_PLAN | CANCEL | FAIL
```

`ResolveRecoveryCommandV1`은 Local API의 `/resolve-recovery`와 `/resume`의 `RECOVERY_RECHECK`가 공통으로 materialize하는 단일 Application command shape다. Application은 durable `RecoveryContextV1`의 `reason + scope + target_ref + context_version` binding을 검증하며 Browser가 recovery reason/target authority를 새로 지정하지 못한다.

### 24.3 Action

```
ApproveActionRequestV2
- command_id
- expected_version

ModifyActionRequestV2
- command_id
- expected_version
- arguments_patch: Tool별 허용 Patch Schema

RejectActionRequestV2
- command_id
- expected_version
- reason?

PrepareRetryRequestV2
- command_id
- expected_version
```

### 24.4 Connection·Settings·Operation Endpoint

| Method·Path | 역할 |
| --- | --- |
| `POST /api/v1/connections/google/start` | MCP Credential Provider OAuth 시작 |
| `GET /api/v1/connections/google/status` | 계정·Scope·연결 상태 |
| `POST /api/v1/connections/google/disconnect` | Revoke 시도·Keyring 삭제 |
| `PUT /api/v1/credentials/llm/{provider}` | API Key 저장·세션 사용 |
| `DELETE /api/v1/credentials/llm/{provider}` | API Key 삭제 |
| `GET /api/v1/credentials/llm/{provider}` | 비밀을 노출하지 않는 configured/storage_mode/validation_status 조회 |
| `GET /api/v1/resources/task-lists` | Task List container 선택용 bounded 목록 |
| `GET /api/v1/resources/calendars` | Calendar container 선택용 bounded 목록 |
| `GET/PUT /api/v1/settings` | 비밀 아닌 설정 조회·변경 |
| `POST /api/v1/runtime/mode` | Active Run 없을 때 Mode 변경 |
| `GET /api/v1/backups` | Safe Mode 포함 eligible Backup 목록 조회 |
| `POST /api/v1/backups` | Backup 생성 |
| `POST /api/v1/restore` | Safe Mode Restore 시작 |
| `POST /api/v1/diagnostics/bundles` | Sanitized Bundle 생성 |
| `POST /api/v1/control/shutdown` | Graceful Shutdown 요청 |

### 24.5 Operational Local API Request·Response 계약

아래 계약은 03/09/10의 기존 behavior를 Local API wire에 고정한다. 모두 Local Session·Origin·Host·Fetch Metadata 검증 후 FastAPI Route가 해당 Application Handler를 호출한다. Domain `expected_version`은 사용하지 않는다.

| Method·Path | Request | Response | Application |
| --- | --- | --- | --- |
| `POST /api/v1/connections/google/start` | `StartAuthorizationRequestV1(command_id)` | `AuthorizationStartV1(authorization_url, callback_id)` | `connection.start_authorization(connector_id=google_workspace)` |
| `GET /api/v1/connections/google/status` | 없음 | `ConnectionMetadataV1` bounded account/scope/status metadata | `connection.get_connection_status` |
| `POST /api/v1/connections/google/disconnect` | `RevokeConnectionRequestV1(command_id)` | `RevokeResultV1` | `connection.revoke_connection` |
| `PUT /api/v1/credentials/llm/{provider}` | `StoreLlmCredentialRequestV1(command_id, api_key, storage_mode)` where `storage_mode = KEYRING | SESSION_ONLY` | `LlmCredentialStatusV1(provider, configured, storage_mode, validation_status)` | `llm_credential.store_llm_credential` |
| `DELETE /api/v1/credentials/llm/{provider}` | `DeleteLlmCredentialRequestV1(command_id)` | `LlmCredentialStatusV1` | `llm_credential.delete_llm_credential` |
| `GET /api/v1/credentials/llm/{provider}` | 없음 | `LlmCredentialStatusV1` | `llm_credential.get_llm_credential_status` |
| `GET /api/v1/resources/task-lists` | 없음 | `TaskListContainerListResponseV1` | `resource.list_task_lists` → `tasks_list_tasklists` |
| `GET /api/v1/resources/calendars` | 없음 | `CalendarContainerListResponseV1` | `resource.list_calendars` → `calendar_list_calendars` |
| `GET /api/v1/settings` | 없음 | `SettingsViewV1` — 10의 non-secret settings allowlist만 | `setting.get_settings` |
| `PUT /api/v1/settings` | `UpdateSettingsRequestV1(command_id, settings_patch: SettingsPatchV1)` | `SettingsViewV1` | `setting.update_settings` |
| `POST /api/v1/runtime/mode` | `UpdateRuntimeModeRequestV1(command_id, requested_mode)` | `RuntimeModeStatusV1` | `runtime_mode.update_runtime_mode` |
| `GET /api/v1/backups` | 없음 | `BackupListResponseV1` | `backup.list_backups` |
| `POST /api/v1/backups` | `CreateBackupRequestV1(command_id)` | `BackupMetadataV1` — opaque backup identity + bounded creation/manifest metadata | `backup.create_backup` |
| `POST /api/v1/restore` | `RestoreBackupRequestV1(command_id, backup_ref)` | `RestoreResultV1` | `backup.restore_backup` |
| `POST /api/v1/diagnostics/bundles` | `CreateDiagnosticBundleRequestV1(command_id, scope, run_id?)`, `scope = LAST_24H | RUN` | `DiagnosticBundleMetadataV1` — opaque bundle identity/size/created time only | `diagnostic_bundle.create_diagnostic_bundle` |
| `POST /api/v1/control/shutdown` | `RequestShutdownRequestV1(command_id)` | `ShutdownAcceptedV1` | `shutdown.request_shutdown` |
| `POST /api/v1/attachments/stage` | multipart `StageAttachmentRequestV1(command_id, file)` | `StagedAttachmentDescriptorV1(staged_attachment_id, filename, mime_type, size_bytes, sha256)` | `attachment.create_staged_attachment` |

### 24.5-A Operational wire schema definitions

§24.5에서 사용하는 Request/Response 이름은 아래 field set을 가진다. 이 절은 09 Security와 10 Infrastructure의 existing behavior를 wire schema로 고정할 뿐 새 secret/persistence authority를 만들지 않는다.

```python
class StartAuthorizationRequestV1:
    schema_version: Literal[1]
    command_id: str

class AuthorizationStartV1:
    schema_version: Literal[1]
    authorization_url: str
    callback_id: str

class ConnectionMetadataV1:
    schema_version: Literal[1]
    connector_id: str
    account_id: str | None
    display_email: str | None
    connection_status: Literal["CONNECTING", "CONNECTED", "DISCONNECTED", "REAUTH_REQUIRED", "UNAVAILABLE"]
    granted_scopes: list[str]
    missing_required_scopes: list[str]

class RevokeConnectionRequestV1:
    schema_version: Literal[1]
    command_id: str

class RevokeResultV1:
    schema_version: Literal[1]
    revocation_attempted: bool
    local_credential_deleted: bool
    connection_status: Literal["DISCONNECTED", "UNAVAILABLE"]

class StoreLlmCredentialRequestV1:
    schema_version: Literal[1]
    command_id: str
    api_key: str                       # transient input; never persisted outside allowed credential store
    storage_mode: Literal["KEYRING", "SESSION_ONLY"]

class DeleteLlmCredentialRequestV1:
    schema_version: Literal[1]
    command_id: str

class LlmCredentialStatusV1:
    schema_version: Literal[1]
    provider: str
    configured: bool
    storage_mode: Literal["KEYRING", "SESSION_ONLY"] | None
    validation_status: Literal["VALID", "INVALID", "UNAVAILABLE", "NOT_CONFIGURED"]

class TaskListContainerItemV1:
    schema_version: Literal[1]
    tasklist_id: str
    title: str

class TaskListContainerListResponseV1:
    schema_version: Literal[1]
    items: list[TaskListContainerItemV1]
    next_page_token: str | None

class CalendarContainerItemV1:
    schema_version: Literal[1]
    calendar_id: str
    title: str
    primary: bool

class CalendarContainerListResponseV1:
    schema_version: Literal[1]
    items: list[CalendarContainerItemV1]
    next_page_token: str | None

class PanelPreferencesV1:
    schema_version: Literal[1]
    right_panel_default_open: bool
    right_panel_default_tab: Literal["CONVERSATIONS", "RESOURCES"]

class SettingsPatchV1:
    schema_version: Literal[1]
    timezone: str | None = None
    default_tasklist_id: str | None = None
    default_calendar_id: str | None = None
    preferred_llm_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"] | None = None
    external_llm_consent: bool | None = None
    retention_days: int | None = None  # P0: 1..30, default 30
    theme: Literal["LIGHT", "DARK"] | None = None
    panel_preferences: PanelPreferencesV1 | None = None
    working_day_start_local: str | None = None   # validated HH:MM
    working_day_end_local: str | None = None     # validated HH:MM
    include_weekends: bool | None = None
    calendar_buffer_minutes: int | None = None
    max_run_execution_ms: int | None = None
    max_connector_calls_per_run: int | None = None
    max_source_page_calls_per_run: int | None = None
    max_detail_fetches_per_run: int | None = None
    max_context_tokens_per_run: int | None = None
    max_retry_attempts_per_run: int | None = None
    circuit_failure_threshold: int | None = None
    circuit_open_duration_ms: int | None = None

class SettingsViewV1:
    schema_version: Literal[1]
    timezone: str
    default_tasklist_id: str | None
    default_calendar_id: str | None
    preferred_llm_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    external_llm_consent: bool
    retention_days: int  # P0 current value: 1..30
    theme: Literal["LIGHT", "DARK"]
    panel_preferences: PanelPreferencesV1
    working_day_start_local: str
    working_day_end_local: str
    include_weekends: bool
    calendar_buffer_minutes: int
    max_run_execution_ms: int
    max_connector_calls_per_run: int
    max_source_page_calls_per_run: int
    max_detail_fetches_per_run: int
    max_context_tokens_per_run: int
    max_retry_attempts_per_run: int
    circuit_failure_threshold: int
    circuit_open_duration_ms: int

class UpdateSettingsRequestV1:
    schema_version: Literal[1]
    command_id: str
    settings_patch: SettingsPatchV1

class UpdateRuntimeModeRequestV1:
    schema_version: Literal[1]
    command_id: str
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]

class RuntimeModeStatusV1:
    schema_version: Literal[1]
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    actual_runtime: Literal["LOCAL_GPU", "API_LLM", "MIXED"] | None
    fallback_reason: str | None

class CreateBackupRequestV1:
    schema_version: Literal[1]
    command_id: str

class BackupMetadataV1:
    schema_version: Literal[1]
    backup_ref: str                    # opaque server-owned identity
    created_at_ms: int
    size_bytes: int
    manifest_hash: str

class BackupListResponseV1:
    schema_version: Literal[1]
    items: list[BackupMetadataV1]

class RestoreBackupRequestV1:
    schema_version: Literal[1]
    command_id: str
    backup_ref: str

class RestoreResultV1:
    schema_version: Literal[1]
    backup_ref: str
    status: Literal["RESTORED", "REJECTED"]
    detail_code: str | None

class CreateDiagnosticBundleRequestV1:
    schema_version: Literal[1]
    command_id: str
    scope: Literal["LAST_24H", "RUN"]
    run_id: str | None

class DiagnosticBundleMetadataV1:
    schema_version: Literal[1]
    bundle_ref: str                    # opaque server-owned identity
    scope: Literal["LAST_24H", "RUN"]
    created_at_ms: int
    size_bytes: int

class RequestShutdownRequestV1:
    schema_version: Literal[1]
    command_id: str

class ShutdownAcceptedV1:
    schema_version: Literal[1]
    accepted: bool

class StageAttachmentRequestV1:
    schema_version: Literal[1]
    command_id: str
    file: bytes                        # multipart transient payload

class StagedAttachmentDescriptorV1:
    schema_version: Literal[1]
    staged_attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    expires_at_ms: int
```

`SettingsPatchV1`은 **partial patch**다. `None`은 “변경 없음”을 뜻하며 secret field는 존재하지 않는다. field set/meaning은 10 §10.3과 exact-copy다. `timezone`은 IANA timezone, working-day field는 valid local `HH:MM` + start<end, `calendar_buffer_minutes>=0`, P0 `retention_days`는 **1 <= value <= 30**만 허용한다. 이 값은 01-B/04가 닫은 Conversation·Message·terminal Run 소유 데이터와 owning Checkpoint 보존 창에만 적용하며 Audit 90일·Secret·Session Cache에는 적용하지 않는다. runtime budget/circuit Positive/bounded validation과 Retrieval hard bound는 10 §8.21을 따른다. `preferred_llm_mode`는 persisted default preference이며 `POST /api/v1/runtime/mode`가 이를 암묵 수정하지 않는다. 알 수 없는 Settings key를 Browser/API/Adapter가 임의 확장하지 않는다.

규칙:

- `api_key`와 attachment bytes는 request 처리에 필요한 transient payload일 뿐 Log/Trace/DB/Checkpoint에 복제하지 않는다.
- Runtime mode 변경은 07/10의 Active Run 없음 Guard를 통과해야 한다.
- Restore는 10의 Safe Mode/backup integrity 절차를 통과한 selected `backup_ref`만 허용한다. Browser가 파일 경로나 임의 DB path를 제출하지 않는다.
- Diagnostic Bundle은 11의 **configured recent-window 또는 explicit Run scope**, configured `DIAGNOSTIC_BUNDLE_MAX_BYTES`, secret/source exclusion 계약을 그대로 적용한다. exact 숫자는 `10 Infrastructure` configuration만 소유한다.
- Attachment staging은 실제 bytes를 받아 server-side Descriptor를 계산한다. Browser가 `sha256`, `size_bytes`, `staged_attachment_id`를 권위 값으로 제출하지 않는다.
- 같은 `command_id + canonical request hash` replay는 같은 bounded result를 반환해야 하며 같은 ID+다른 hash는 conflict다.

## 24. OAuthCredentialPort

```
start_authorization(connector_id, environment, requested_scopes, operation_ref) -> AuthorizationStartV1
reconcile_authorization_start(connector_id, operation_ref) -> OperationalReconcileResultV1
refresh_access(connector_id, account_id) -> AccessContextHandle
revoke_connection(connector_id, account_id, operation_ref) -> RevokeResultV1
reconcile_revoke_connection(connector_id, account_id, operation_ref) -> OperationalReconcileResultV1
get_connection_status(connector_id) -> ConnectionMetadataV1
```

Repository/Application mapping is connector-neutral:

```
POST /api/v1/connections/google/start
→ connection.start_authorization(connector_id=google_workspace)
→ OperationalCommandReplayPort.reserve_or_replay(...) → operation_ref
→ OAuthCredentialPort.start_authorization(connector_id=google_workspace, ..., operation_ref)

GET /api/v1/connections/google/status
→ connection.get_connection_status(connector_id=google_workspace)
→ OAuthCredentialPort.get_connection_status(connector_id=google_workspace)

POST /api/v1/connections/google/disconnect
→ connection.revoke_connection(connector_id=google_workspace)
→ OAuthCredentialPort.revoke_connection(connector_id=google_workspace, ...)
```

The P0 `google` path segment fixes the registered Connector identity; it does not create `application/use_cases/google/**` or authorize FastAPI Route to call the MCP Credential Provider directly.

Loopback callback의 `code/state` 수신, PKCE/state 검증, Token 교환, Refresh Token Keyring I/O는 MCP Credential Provider Process 내부 operation이 수행한다. Core-facing `OAuthCredentialPort`에는 raw callback payload를 노출하지 않는다. `start_authorization` 후 UI/Application의 완료 관측 authority는 기존 `GET /api/v1/connections/google/status → connection.get_connection_status → OAuthCredentialPort.get_connection_status` 하나다. UI는 returned `callback_id`를 화면-local correlation으로만 보존하고 bounded polling/refresh로 `CONNECTING → CONNECTED | DISCONNECTED | REAUTH_REQUIRED | UNAVAILABLE`을 관측한다. UI가 loopback authorization 시작 URL에 `return_to`를 보낼 때 MCP는 query/fragment/user-info가 없는 exact `http://127.0.0.1:{app_port}/`만 허용하고, 성공 callback 뒤 그 주소로 `303` 이동할 수 있다. 이 이동은 status 조회를 대신하거나 새 completion authority를 만들지 않는다. P0는 connector별 active authorization session을 최대 1개만 허용하며 새 safe-to-retry start는 이전 incomplete callback state를 invalidate한 뒤 교체한다. 별도 MCP→Application reverse notification/event Port는 P0에 없다.

## 25. Claim Token 계약

`ClaimExecution`이 `applied=true`로 Commit된 뒤 Application Claim handler가 현재 Domain/Attempt와 서버 생성 실행 Metadata로 `ClaimContextV2`를 구성하고 HMAC-SHA-256으로 보호한다.

```python
class ClaimContextV2:
    claim_version: Literal[2]
    service_instance_id: str
    mcp_process_instance_id: str
    action_id: str
    approval_id: str
    execution_attempt_id: str
    tool_name: str
    approval_arguments_hash: str       # 64-char SHA-256 hex
    execution_arguments_hash: str      # actual dispatch args canonical hash
    issued_at_ms: int
    expires_at_ms: int
    nonce: str
    signature: str                     # HMAC-SHA-256 over canonical unsigned fields
```

- TTL 기본 30초, 최대 60초
- Service–MCP 전용 256-bit Session Key는 MCP Child Handshake에서 Process Memory로만 전달
- MCP는 Signature·TTL·Service Instance·Binding·Nonce를 검증
- Nonce는 1회 소비하며 재사용 시 `CLAIM_TOKEN_REUSED`
- Service 또는 MCP 재시작 시 기존 Token 무효
- Token·Session Key는 Log·Trace·Audit·DB·CLI·환경 변수에 저장 금지

## 26. MCP Tool Schema Catalog

공통 Output:

```
schema_version
request_id
resource_id?
next_page_token?
items?
total_count?
metadata
```

| Tool | 핵심 Input | Output | Scope | Timeout | Retry |
| --- | --- | --- | --- | --- | --- |
| `gmail_search_threads` | query&lt;=2048, page_token?, page_size 1..100 | ThreadMetadata[] | gmail.readonly | configured connector timeout | Read 429·5xx 1회 |
| `gmail_get_thread` | thread_id | ThreadDetail | gmail.readonly | configured connector timeout | Read 1회 |
| `gmail_get_message` | message_id | MessageDetail | gmail.readonly | configured connector timeout | Read 1회 |
| `gmail_get_attachment` | message_id, attachment_id | `GmailAttachmentReadResultV1` | gmail.readonly | configured connector timeout | Read 1회 |
| `gmail_create_draft` | recipients&lt;=50, subject&lt;=998, body&lt;=65536, thread_id? + claim context | DraftMetadata | gmail.compose | configured connector timeout | 전달 불명 시 금지 |
| `gmail_update_draft` | draft_id, mutable fields + claim context | DraftMetadata | gmail.compose | configured connector timeout | 전달 불명 시 금지 |
| `gmail_get_draft` | draft_id | DraftDetail | gmail.compose | configured connector timeout | Read 1회 |
| `gmail_send` | recipients<=50, cc?, subject<=998, body<=65536, thread_id? + claim context | MessageMetadata | gmail.compose | configured connector timeout | 전달 불명 시 자동 retry 금지 |
| `tasks_list_tasklists` | page_token?, page_size | TaskListMetadata[] | tasks | configured connector timeout | Read 1회 |
| `tasks_list_tasks` | tasklist_id, filter, page_token?, page_size | TaskMetadata[] + exact `total_count` when requested by Sidebar | tasks | configured connector timeout | Read 1회 |
| `tasks_get_task` | tasklist_id, task_id | TaskDetail | tasks | configured connector timeout | Read 1회 |
| `tasks_create_task` | tasklist_id, title, notes?, due? + claim context | TaskMetadata | tasks | configured connector timeout | 전달 불명 시 금지 |
| `tasks_update_task` | tasklist_id, task_id, 허용 필드 + claim context | TaskMetadata | tasks | configured connector timeout | 전달 불명 시 금지 |
| `tasks_delete_task` | tasklist_id, task_id + claim context | DeleteResult(resource_id) | tasks | configured connector timeout | 전달 불명 시 자동 retry 금지 |
| `calendar_list_calendars` | page_token?, page_size | CalendarMetadata[] | calendarlist.readonly | configured connector timeout | Read 1회 |
| `calendar_list_events` | calendar_id, time_min, time_max, query?, page_token? | EventMetadata[] + opaque continuation | `calendar.events` | configured connector timeout | Read 1회 |
| `calendar_query_freebusy` | calendar_ids&lt;=20, time_min, time_max | BusyInterval[] | `calendar.events.freebusy` | configured connector timeout | Read 1회 |
| `calendar_get_event` | calendar_id, event_id | EventDetail | `calendar.events` | configured connector timeout | Read 1회 |
| `calendar_create_event` | calendar_id, title, start, end, description? + claim context | EventMetadata | `calendar.events` | configured connector timeout | 전달 불명 시 금지 |
| `calendar_update_event` | calendar_id, event_id, 허용 필드 + claim context | EventMetadata | `calendar.events` | configured connector timeout | 전달 불명 시 금지 |
| `calendar_delete_event` | calendar_id, event_id + claim context | DeleteResult(resource_id) | `calendar.events` | configured connector timeout | 전달 불명 시 자동 retry 금지 |
- 모든 ID·Page Token은 길이 1..2048, 제어문자 금지.
- 날짜·시간은 RFC3339와 명시 Timezone을 사용한다.
- Write Tool의 `claim context`는 Action·Approval·Attempt·Hash·Token을 포함한다.
- `tasks_create_task`의 raw `due?`는 Google Adapter 경계에서만 `scheduled_date`와 대응한다. `business_deadline`·작업 시간은 새 Task Tool Argument로 추가하지 않으며, 업무 마감 의미 보존은 승인된 `notes`와 Evidence·Approval Projection을 따른다.

### 27.1 Sidebar Query Projection 계약

이 절의 Google Tool 표는 §3.2.1의 **단일 Sidebar Browse·Count 계약**을 소비하며 같은 목록을 다시 정의하지 않는다. Calendar Sidebar 호출은 selected `monthAnchor`에서 계산한 explicit `[gridStart, gridEnd)`를 사용하고, `time_min/time_max` 생략 시 90일 기본값은 Sidebar가 아닌 generic Upcoming Browse에만 적용한다. Count·continuation·cache lifetime은 §3.2.1을 그대로 따른다.

## 27. Verification·Recovery 계약

`GET_COMPARE`, `GET_ABSENT`, `SENT_LOOKUP`, `GET_TARGET`, `RESOURCE_SEARCH`, `MESSAGE_SEARCH`는 이 계약에서 **verification/recovery strategy identifiers**다. Connector production operation/path 이름을 새로 정의하는 vocabulary가 아니며 실제 Read는 registered Connector Read Tool을 통해 수행한다.

- CREATE·UPDATE: GET_COMPARE.
- DELETE: `GET_ABSENT` 정책으로 대상 GET에서 NOT_FOUND/삭제 상태를 확인한다.
- SEND: `SENT_LOOKUP` 정책으로 반환된 Message/Thread 식별자 또는 결정적 전송 식별자를 조회한다.
- SEND 전달 여부가 불명확하면 `UNKNOWN_RESULT`로 전환하고 자동 재전송하지 않는다.
- 모든 외부 MCP/Google 호출은 SQLite Write Transaction 밖에서 수행한다.

## 28. Agent Subgraph 내부 인터페이스

Parent Graph와 Agent Subgraph 사이의 인터페이스는 자유 텍스트 대화가 아니라 Typed Projection·Typed Local State·Typed Result로 고정한다.

```
Main Graph Typed State
→ Subgraph Input Projection
→ Subgraph Typed Local State
→ Node별 최소 Projection
→ Versioned Typed Result + disposition + optional WorkflowSignal
→ Main Graph State update
```

- Node는 전체 Main State를 받지 않고 선언된 입력 필드만 받는다.
- Local State는 invocation 범위 단편 상태이며 장기 Memory가 아니다.
- Agent가 다른 Agent를 직접 호출하는 내부 Port는 제공하지 않는다.
- Agent Subgraph는 `ConnectorWritePort`나 concrete MCP/Provider Write adapter를 직접 받지 않는다.
- Retrieval Subgraph는 Connector Port를 직접 받지 않는다. 결정적 Retrieval Node는 Retrieval owner의 `execute_read` Application operation을 호출하고, 그 operation만 `ConnectorReadPort`를 사용한다. 정확한 repository path/file/symbol은 `16 Repository Architecture`가 소유한다. `ToolRoutePlanV2.input_plan.input_routes[].allowed_read_tool_ids` 밖의 Tool 호출은 Application operation에서 Provider 호출 전에 거절한다.
- Planning Subgraph는 `OutputPlanV1`을 그대로 소비한다. `ActionOutputPlanV1`일 때만 `output_routes[].selected_tool_id`를 사용하며 다른 Tool을 제안할 수 없고, `AnswerOutputPlanV1`에는 Action Tool Route가 존재하지 않는다.
- 앞 단계 State 수정이 필요하면 `ROUTE_RECONSIDERATION_REQUIRED`, `RETRIEVE_MORE` 같은 disposition을 반환하고 Main Supervisor가 Back-edge를 선택한다.
- Query candidate·Page Token·RAG score·LLM candidate는 Main State에 승격하지 않는다.

## 29. Write Delivery Classification

Write Adapter와 `MCPClientPort` 경계는 Error Code와 함께 전달 확실성을 보존한다.

```
NOT_SENT
MAY_HAVE_BEEN_SENT
SENT_RESPONSE_LOST
```

| 실패 시점 | delivery_certainty | Domain 결과 |
| --- | --- | --- |
| Schema/Policy/Preflight 실패, dispatch 전 process unavailable | `NOT_SENT` | `FAILED` 가능, 자동 Write 재실행은 하지 않고 retry 준비 계약 사용 |
| connect/transport 오류에서 실제 dispatch 여부를 증명할 수 없음 | `MAY_HAVE_BEEN_SENT` | `UNKNOWN_RESULT` |
| request bytes dispatch 후 Timeout | `MAY_HAVE_BEEN_SENT` | `UNKNOWN_RESULT` |
| Provider 5xx에서 미전달 보장이 없음 | `MAY_HAVE_BEEN_SENT` | `UNKNOWN_RESULT` |
| 요청 전달 후 response 유실·connection lost | `SENT_RESPONSE_LOST` | `UNKNOWN_RESULT` |
| MCP process exit가 dispatch 이후일 수 있음 | `MAY_HAVE_BEEN_SENT` | `UNKNOWN_RESULT` |

Exception class 하나만으로 `NOT_SENT`를 추론하지 않는다. `UNKNOWN_RESULT`에서는 기존 결과 GET/Search만 허용하며 새 Attempt·blind resend를 금지한다.

## 30. ClaimContextV2 계약

### Deterministic Write validation value contracts

```python
class ValidateActionArgumentsQueryV1:
    schema_version: Literal[1]
    action_id: str
    action_version: int
    tool_id: str
    tool_schema_version: str
    arguments: dict[str, object]

class ActionArgumentsSchemaValidationResultV1:
    schema_version: Literal[1]
    valid: bool
    tool_id: str
    tool_schema_version: str
    arguments_hash: str
    error_codes: list[str]
    error_paths: list[str]

class EvaluateActionPolicyQueryV1:
    schema_version: Literal[1]
    run_id: str
    action_id: str
    action_version: int
    tool_id: str
    effect: str
    arguments_hash: str
    source_snapshot_ref: str
    policy_confirmation_receipt_refs: list[str]

class ActionPolicyEvaluationResultV1:
    schema_version: Literal[1]
    decision: Literal["ALLOW", "DENY", "CONFIRMATION_REQUIRED"]
    policy_version: str
    reason_codes: list[str]
    confirmation_kind: Literal["SCOPE_EXPANSION", "DUPLICATE_OVERRIDE", "CONFLICT_OVERRIDE"] | None

class BuildClaimContextQueryV1:
    schema_version: Literal[1]
    action_id: str
    approval_id: str
    execution_attempt_id: str
    tool_name: str
    approval_arguments_hash: str
    final_tool_arguments: dict[str, object]
    service_instance_id: str
    mcp_process_instance_id: str
```

`ActionArgumentsSchemaValidationResultV1.arguments_hash`는 입력 `arguments` 자체의 Canonical JSON SHA-256이며 validator가 arguments를 수정했다는 뜻이 아니다. `EvaluateActionPolicyQueryV1`은 raw Source body/Prompt text를 받지 않고 current bounded snapshot/reference만 받는다. `BuildClaimContextQueryV1` handler는 `ClockPort`/`UUIDPort`와 process-memory signing key를 사용해 `execution_arguments_hash`, issued/expires time, nonce, signature를 계산하되 DB mutation·Connector I/O는 하지 않는다.

### Deterministic Write validation chain

Canonical chain:

```text
Planning candidate arguments
→ ValidateActionArgumentsQueryV1 / ActionArgumentsSchemaValidationResultV1
→ EvaluateActionPolicyQueryV1 / ActionPolicyEvaluationResultV1
→ current Review PASS freshness
→ ApproveAction Domain guard/mutation
→ ClaimExecution atomic commit
→ BuildClaimContextQueryV1 / ClaimContextV2
→ DispatchConnectorWriteCommandV1
→ ConnectorWritePort
```

`ActionArgumentsSchemaValidationResultV1`은 schema validity/error path만, `ActionPolicyEvaluationResultV1`은 `ALLOW | DENY | CONFIRMATION_REQUIRED`와 policy reason codes만 소유한다. 둘 다 Domain mutation이나 Connector I/O를 하지 않는다. `BuildClaimContextQueryV1`은 이미 commit된 Claim/Attempt와 서버 최종 dispatch args만 입력으로 받아 signed `ClaimContextV2`를 만들며 DB write/MCP call을 하지 않는다.

### Signed Claim Context

```
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
- `DUPLICATE_OVERRIDE_REQUIRED` 또는 `CONFLICT_OVERRIDE_REQUIRED`에 의존하는 Write는 Domain Validation에서 현재 Context에 유효한 `PolicyConfirmationReceiptV1(APPROVED)`를 요구한다. Approval Snapshot은 해당 `receipt_id + decision_context_hash`를 Canonical Business Snapshot에 포함하며, Claim/Preflight는 이 Receipt binding이 누락·변경·stale이면 실행을 차단한다. Receipt 질문/응답 원문은 Snapshot·Claim에 넣지 않는다.
- Application이 서버 생성 Metadata까지 포함한 최종 MCP 인자를 Canonicalize하여 `execution_arguments_hash`를 계산한다.
- MCP는 Signature·Version·TTL·Service/MCP Process Instance·Action·Approval·Attempt·Tool·Approval Hash를 검증한다.
- MCP는 실제 수신 Tool Arguments를 같은 Canonical 규칙으로 재해시하여 `execution_arguments_hash`가 다르면 `CLAIM_ARGUMENTS_MISMATCH`로 거절한다.
- 모든 검증 성공 후에만 Nonce를 원자적으로 소비하고 Connector Provider Write를 호출한다. P0 Google Workspace에서도 동일한 경계를 적용한다.

### Gmail 첨부파일 Local API·MCP

```
GET  /api/v1/gmail/messages/{message_id}/attachments/{attachment_id}
POST /api/v1/attachments/stage
```

MCP Read:

```
gmail_get_attachment(message_id, attachment_id)
```

```python
class GmailAttachmentReadResultV1:
    message_id: str
    attachment_id: str
    filename: str | None
    mime_type: str | None
    size_bytes: int
    sha256: str
    content_bytes: bytes
```

`content_bytes`는 current request memory를 벗어나 Domain DB/Checkpoint/Trace/Audit/Prompt에 저장하지 않는다. MCP stdio에서 binary를 표현하는 exact serialization/base64 framing과 exact numeric byte limit은 adapter/runtime configuration의 implementation choice이며 별도 canonical 타입을 만들지 않는다. 단, effective limit 검증은 Provider 호출 전/수신 직후 fail closed하고 Local API·staging 경계와 일관되어야 한다.

Attachment Descriptor 최소 필드:

```
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

## 31. Planning Default Container Binding 계약

Planning LLM이 `tasklist_id`, `calendar_id` 같은 Runtime container ID를 숨은 값으로 추측하는 것을 금지한다.

```
OutputToolRouteV1 + selected resource/context
→ deterministic DefaultContainerResolver
→ selected resource parent/container 우선
→ 없으면 app settings의 default_tasklist_id/default_calendar_id
→ bound Tool Schema Projection(const/immutable field)
→ Planning Argument Writer
→ deterministic Plan/Argument Assembler
```

- `tasks_create_task | tasks_update_task | tasks_delete_task`에 필요한 `tasklist_id`는 대상 Resource의 parent Task List가 있으면 이를 우선하고, 그렇지 않으면 설정된 `default_tasklist_id`를 결정적으로 바인딩한다.
- `calendar_create_event | calendar_update_event | calendar_delete_event`의 `calendar_id`도 대상 Event의 parent Calendar가 있으면 이를 우선하고, 그렇지 않으면 설정된 `default_calendar_id`를 사용한다.
- 바인딩된 container field는 LLM이 변경할 수 없는 `const/immutable` Tool Schema Projection으로 노출하거나 LLM writable field에서 제외한다.
- 필수 container를 결정적으로 해석할 수 없으면 Argument Writer를 호출하지 않고 사용자 소유 container 선택/확인 요구로 전환한다.
- 최종 Action Arguments는 deterministic Assembler가 bound field와 LLM semantic arguments를 병합한 뒤 Tool Schema로 다시 검증한다.
- Product Prompt에는 Gold가 아니라 실제 Runtime에서 해석된 binding metadata만 전달할 수 있다.

### 32.1 Default container selection validation

`default_tasklist_id` and `default_calendar_id` are saved only after Application validates the submitted ID against the current connected account's container discovery result (or an equivalent same-account ConnectorRead lookup) through the `resource` owner. Browser-provided title/source metadata is not authority. Account change/disconnect invalidates a default that no longer resolves; Planning then requires a fresh container selection rather than guessing.

## 32. Frontend/API bootstrap compatibility contract

`POST /api/v1/session/bootstrap`은 `frontend_api_contract_version`과 server `api_contract_version`을 비교해 `compatibility`를 반환한다. `INCOMPATIBLE`이면 session mutation admission/SSE subscription은 열리지 않는다. Browser는 Conversation 조회 등 후행 API에서 version을 추론하지 않는다. compatibility algorithm/version-range authority는 Release/API contract configuration이 소유하고 Route alias를 만들지 않는다.


## 33. Durable Workflow Handoff contract

이 절은 durable handoff의 **interface projection**만 고정한다. Persistence invariant는 `04 §workflow_handoffs`, workflow target/one-shot semantics는 `06`, interaction order는 `08`, startup/live driving은 `10`을 따른다.

Canonical types와 callable은 이미 본 문서의 Port 계약에 정의된 다음 집합이다.

```text
WorkflowHandoffStageV1
WorkflowHandoffV1
WorkflowExecutionBindingV1
WorkflowExecutionAdmissionV1
WorkflowExecutionSubmissionV2
WorkflowExecutionSettlementV1
WorkflowControlEnvelopeV1
WorkflowHandoffRepository
WorkflowExecutionPort
```

Interface-level invariants:

- `WorkflowExecutionPort.submit`은 persisted `WorkflowExecutionAdmissionV1`만 받는다. Adapter-private binding이나 raw checkpoint payload를 execution authority로 전달하지 않는다.
- 동일 `admission_id`가 이미 accepted/active인 submit replay는 새 worker entry 없이 idempotent `ACCEPTED`다. `ALREADY_RUNNING`은 다른 admission과의 slot conflict에만 사용한다.
- Repository admission claim/release/settlement는 typed version/Run-authority fence 결과를 반환한다. Caller가 raw SQL 결과를 해석해 PENDING/SUPERSEDED/BLOCKED_BINDING을 임의 결정하지 않는다.
- `ACCEPTED` 이후 Application이 성공을 기록하기 위한 별도 handoff status write를 추가하지 않는다. Worker-side pre-owner settlement 결과가 semantic owner I/O 가능 여부를 결정한다.
- settled handoff에서 control body가 지워져도 typed projection은 historical `control_kind/hash`와 status를 표현할 수 있어야 한다.
- `RedriveWorkflowHandoffsHandler`가 소비하는 repository/query surface와 WEP submission은 위 typed contract만 사용한다. Reconciliation precedence 자체는 06/10에서 소비한다.

Control payload mapping은 07 concern에 필요한 범위만 유지한다. Exact registered continuation target은 `06 §External-control handoff target matrix`가 소유한다.

| Control family | 07 typed control payload | target authority |
| --- | --- | --- |
| Confirmation response | `ConfirmationResumeControlV1` | 06 saved owner target |
| Context `EXCLUDE_EVIDENCE / RETRIEVE_MORE` | `ContextAdjustmentControlV1` | 06 main-control target |
| Approval / Modify / Reject / PrepareRetry / expired refresh | no user payload body | 06 target matrix |
| Reauth / Recovery / SAFE resume / Cancel | no user payload body | State Contract + 06 target matrix |
| terminal Recovery resolution | no business-resume payload | terminal projection only |

OAuth connection success 자체는 특정 Run continuation payload가 아니며 Run-neutral connection result다.

따라서 이 절은 handoff lifecycle diagram, cancel race, checkpoint-rebind algorithm, startup precedence를 다시 복제하지 않는다.

## 34. Runtime projections · external LLM disclosure contract

### 35.1 Runtime/read-model projection invariants

- `RuntimeModePort` is the sole process-local mutable authority for the current Service requested mode. `runtime_mode.update_runtime_mode` uses `OperationalCommandReplayPort` then `RuntimeModePort.set_requested_mode`; `runtime_status.get_runtime_status` reads `RuntimeModePort.get_requested_mode` and combines it with LLM runtime status to project `RuntimeModeStatusV1`. No Application module global, Settings field, or `StructuredInferenceRuntimeRouter` private mutable field is a second authority.
- StartRun persists exact `requested_mode` on Run and projects it into `RunInputV1`, `WorkflowBindingV1`, `RunExecutionRefV1`; same-Run resume never substitutes `preferred_llm_mode` or process runtime mode.
- `external_llm_consent` is the only prior-consent fact. `ExternalLlmTransferScopeV1` is a display projection, not authority.
- Default Task List/Calendar choosers use `GET /api/v1/resources/task-lists` and `/calendars`; React never calls MCP directly and empty containers remain discoverable.
- Safe Mode Restore uses `GET /api/v1/backups` to obtain opaque `backup_ref`; raw path/latest-backup guessing is forbidden.
- Settings re-entry reads LLM credential status through `GET /api/v1/credentials/llm/{provider}`.
- Google account UI uses `ConnectionMetadataV1.display_email`; `account_id` remains opaque.
- P0 diagnostics UI consumes expanded protected `GET /api/v1/runtime` bounded projection; Launcher-only health endpoint is not a Browser substitute.

### 35.2 `ExternalLlmTransferScopeV1`

```python
class ExternalLlmTransferScopeV1:
    schema_version: Literal[1]
    run_id: str
    scope_revision: int
    scope_hash: str
    source_kinds: list[str]
    data_classes: list[Literal["USER_REQUEST", "RESOURCE_METADATA", "EVIDENCE_EXCERPT", "PLAN_CONTEXT"]]
```

`RunSnapshotResponseV1`/Run UI projection may include this bounded object when external LLM use is possible. It never contains source body, secret, token, or raw credential.

### 35.3 Pre-call disclosure ordering

P0는 별도 Browser ACK를 consent로 요구하지 않는다. 01-B의 “external call 전에 표시”의 enforceable 의미는 **exact input projection에서 계산한 current `ExternalLlmTransferScopeV1`을 server-side Run projection/checkpoint metadata에 먼저 저장하고 `EXTERNAL_LLM_SCOPE_PUBLISHED` SSE를 append한 뒤에만 external provider adapter를 호출**하는 것이다. 실제 Browser paint/network timing은 security authority가 아니다.

`StructuredInferenceRuntimeRouter`의 API branch는 매 호출마다 `(1) current external_llm_consent=true`, `(2) caller가 `run.project_external_llm_transfer_scope`로 exact input projection scope를 만들었음`, `(3) CheckpointPort에 같은 scope hash가 publish됨`을 확인한다. 셋 중 하나라도 없으면 external provider call 0이다. AUTO→API fallback도 동일하다. 이후 Retrieval/Route 변화로 source/data-class set이 달라지면 새 scope hash/revision을 publish한 뒤에만 다음 external call을 허용한다.

## 35. AbortClaimedExecution internal contract

```python
class AbortClaimedExecutionCommandV1:
    schema_version: Literal[1]
    command_id: str
    action_id: str
    execution_attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    abort_reason: Literal[
        "CANCEL_INTENT",
        "RESTART_RECONCILIATION",
        "CLAIM_CONTEXT_INVALID",
        "PRE_BEGIN_CREDENTIAL_FAILURE",
        "PRE_BEGIN_SECURITY_FAILURE",
    ]

class AbortClaimedExecutionResultV1:
    schema_version: Literal[1]
    applied: bool
    action_status: Literal["CANCELLED", "FAILED"] | None
    attempt_status: Literal["FAILED"] | None
    result_code: str
```

이 command는 same Attempt의 APPLIED `BeginExecutionAttempt`가 **없고** current Attempt=`CLAIMED`인 경우에만 적용한다. `CANCEL_INTENT`이면 Action=`CANCELLED`, 나머지는 Action=`FAILED`; Attempt는 모두 `FAILED`다. external Write=0, Approval `CONSUMED` 유지. `BeginExecutionAttempt`와 동일 expected-version/status CAS에서 경쟁하므로 둘 다 APPLIED될 수 없다.
