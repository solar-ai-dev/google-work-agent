# 05. Context · Retrieval 설계서

> **Authority:** Context·Retrieval semantics. Tool Route/Workflow/Domain의 전문 의미는 해당 owner를 직접 소비한다.  
> **상태:** Draft v2.17 · **기준일:** 2026-08-24 · **대상:** P0 MVP

## 1. 목적

확정된 Connector Input Route에서 필요한 자료를 최소 호출로 수집하고, 가져온 자료를 그대로 다음 LLM에 전달하지 않고 **관련 Segment를 RAG로 검색·정렬하여 Evidence만 선별**한다. P0에서는 Google Workspace Connector의 Gmail·Tasks·Calendar를 지원한다. 영구 Vector Index는 P0 필수가 아니며 Run-scoped Retrieval/Reranking을 기본 구조로 사용한다.

## 2. 확정 결정

- `CTX-001`: 요청 시점 Connector 원본 연합 검색. P0 Source는 Google Workspace의 Gmail·Tasks·Calendar다.
- `CTX-002`: IN/OUT Tool Route 선택은 Retrieval 이전 `Tool Route Subgraph`가 소유
- `CTX-003`: Retrieval은 고정된 `input_routes`만 사용하고 Resource·Connector·Tool 종류를 재선택하지 않음. `input_routes`에는 사용자 의미상 필요한 READ뿐 아니라 `01-B` Policy Precondition으로 결정적으로 보강된 필수 READ도 포함될 수 있으며 Retrieval은 `required=true`인 Route를 임의 생략하지 않음. 단 사용자 지정 범위를 벗어나는 Policy Precondition Route는 Tool Route의 `SCOPE_EXPANSION_REQUIRED` Confirmation이 완료된 뒤에만 Input Route로 확정될 수 있으며 Retrieval이 스스로 범위를 확대하지 않음
- `CTX-004`: LLM이 Raw Query·Page Token·MCP Arguments를 직접 실행하지 않음
- `CTX-005`: Query 계획 → 결정적 Query Builder → MCP Read → Normalize/Segment → Run-scoped RAG → Evidence → Sufficiency
- `CTX-006`: 가져온 후보 전체를 Work Analysis·Planning Prompt에 직접 전달하지 않음
- `CTX-007`: 부족 시 같은 IN Route 안에서 추가 Retrieval 최대 2회
- `CTX-007A`: Retrieval self-loop의 raw Provider continuation은 **Run Retrieval Cache의 해당 read-result entry만** memory-only로 소유한다. Retrieval Local State에는 raw token을 복제하지 않고 `read_result_handle`만 둔다.
- `CTX-007B`: Follow-up `plan_query`는 현재 round, prior `QueryAttemptV1`, 미해결 `SufficiencyIssueV2`, bounded read-result summary를 입력 Projection으로 사용한다. Raw Page Token·Provider-native Query·MCP Arguments는 LLM 입력에 포함하지 않는다.
- `CTX-007C`: `NEXT_PAGE`는 결정적 Read Node가 prior `read_result_handle`을 Run Retrieval Cache에서 resolve하고 `run_id + route_id + query_identity_hash` binding을 검증한 뒤 opaque continuation을 MCP Read Arguments에 주입한다. unknown/cross-run/mismatched handle은 fail-closed한다.
- `CTX-007D`: 같은 Query와 같은 continuation 상태의 반복은 새 Retrieval round로 인정하지 않는다. 추가 round는 새 Page, 필요한 Detail Fetch, 또는 미해결 Sufficiency Issue에 근거한 변경 Query처럼 **새 정보 획득 가능성이 있는 bounded read**여야 한다.
- `CTX-008`: 새 Resource/Connector Route가 필요하면 `ROUTE_RECONSIDERATION_REQUIRED`를 Parent에 반환
- `CTX-009`: 일반 Retrieval은 Action Row가 아니라 Trace·Checkpoint·Run Cache 대상
- `CTX-010`: RAG는 구조적 필수 단계다. Backend는 deterministic score/lexical retrieval, Embedding, Reranker, Vector Index 등 교체 가능한 구현 capability로 둘 수 있으며 제품에서 활성화할 구성은 `13 Evaluation`의 비교 결과와 `10 Infrastructure`의 Release Config가 결정한다.

## 3. 전체 흐름

```
RequestIntentV2 + ToolRoutePlanV2.input_plan.input_routes
→ Retrieval Subgraph
  → plan_query
  → build_query                         # deterministic
  → execute_read                        # deterministic
  → [Calendar availability 필요 시] resolve_availability  # deterministic supporting operation, independent Edge 아님
  → normalize_segments                  # deterministic
  → rag_retrieve_rerank
  → select_evidence
  → assess_sufficiency
  → finalize_retrieval                  # deterministic
→ RetrievalResultV1
```

Main Graph에는 Query 후보·Page Token·전체 후보·RAG score를 올리지 않는다.

## 4. Retrieval Subgraph State

```python
class RetrievalStateV2:
    request_intent: RequestIntentV2
    input_route_ref: StateArtifactRefV1
    input_routes: list[InputToolRouteV1]
    query_plan: RetrievalQueryPlanV2 | None
    query_attempts: list[QueryAttemptV1]
    source_statuses: list[SourceRetrievalStatusV1]
    read_result_handles: list[str]
    segment_handles: list[str]
    availability_results: list[AvailableIntervalV1]
    rag_candidates: list[RagCandidateV1]
    exclusion_obligation_segment_ids: list[str]
    pending_user_retrieval_need: RetrievalNeedV1 | None
    evidence_selection: EvidenceSelectionResultV2 | None
    sufficiency: SufficiencyResultV2 | None
    final_result: RetrievalResultV1 | None
```

규칙:

- `request_intent`, `input_route_ref`, `input_routes`는 Parent Projection이며 Retrieval이 수정하지 않는다. Retrieval Product Prompt는 raw `user_request`를 별도 권위 입력으로 재주입하지 않고 `RequestIntentV2`의 Canonical 의미를 소비한다.
- 사용자 Context Adjustment는 `07`이 검증한 `ContextAdjustmentV1` 한 개만 Retrieval 재진입 입력으로 받을 수 있다. `EXCLUDE_EVIDENCE`는 current Preview membership이 검증된 stable `segment_id`를 `exclusion_obligation_segment_ids`에 materialize한 뒤 새 selection에서 제외한다. `RETRIEVE_MORE`는 validated `RetrievalNeedV1(reason_codes=[USER_CONTEXT_ADJUSTMENT])`를 `pending_user_retrieval_need`에 materialize한다. 두 semantic obligation 모두 **handoff payload clear 전에 같은 checkpoint에 commit**되며 crash/cache-loss/route-reconsideration 재진입에서도 보존된다. `pending_user_retrieval_need`는 해당 Context Adjustment로 시작된 fresh `RetrievalResultV1` revision이 finalize되는 checkpoint에서만 `None`으로 clear한다. 이 입력은 다른 Agent로 전파되는 장기 업무 사실이 아니다.
- Context Adjustment 후 `RetrievalResultV1`은 새 revision을 발급한다. downstream `WorkAnalysisResultV2`, Plan, Review가 이전 retrieval revision을 `meta.based_on`으로 참조하면 stale이며 재사용하지 않는다. current IN Route로 해결할 수 없는 추가 검색은 기존 `RouteReconsiderationRequiredV1` back-edge를 사용한다.
- `query_plan`, `query_attempts`, `source_statuses`, `read_result_handles`, `segment_handles`, `availability_results`, `rag_candidates`, `exclusion_obligation_segment_ids`, `pending_user_retrieval_need`는 Local State다. `exclusion_obligation_segment_ids`와 `pending_user_retrieval_need`가 user Context Adjustment에서 온 crash-safe semantic obligations이며 raw Provider cache/token이 아니다.
- `read_result_handles`는 현재 Run의 Run Retrieval Cache entry를 가리킨다. Cache entry는 `run_id`, `route_id`, validated `query_identity_hash`, Connector-normalized bounded `ConnectorReadResultV1`과 continuation exhaustion 상태를 결합해 보존한다. `ConnectorReadResultV1.next_page_token`의 opaque continuation은 이 entry 밖으로 복제하지 않는다.
- Parent에는 `RetrievalResultV1`만 병합한다.
- 실제 Connector 원문과 raw continuation은 Run Retrieval Cache Handle로 참조하고 Main State·Checkpoint·Prompt·Trace·Audit·Domain DB에 복제하지 않는다. P0 Google Workspace 원문도 동일 규칙을 따른다.


### 4.1 Restart semantics for memory-only Retrieval cache

Raw Provider continuation을 durable storage에 넣지 않는 원칙은 유지한다. 대신 service restart 후 checkpoint에 남은 `read_result_handle`이 현재 Run Retrieval Cache에서 resolve되지 않으면 **그 handle을 추측·재사용하지 않고 deterministic Retrieval restart**를 수행한다.

```text
RETRIEVING checkpoint load
→ required read_result_handle resolve
→ missing/cross-run/query-binding mismatch
→ current local QueryAttemptV1/read-result/segment handles 폐기
→ durable handoff control = RETRIEVAL_CACHE_RESTART
→ MAIN_CONTROL:RETRIEVAL_ENTRY
→ frozen RequestIntentV2 + current InputRoutePlanV1에서 fresh read 시작
→ 새 RetrievalResultV1 revision 발급
```

- 이것은 `RecoveryReasonV1`을 새로 만드는 경로가 아니다. frozen Route/Request contract와 checkpoint binding이 유효한 한 same-run Retrieval을 처음부터 다시 실행하는 **workflow-local restart**다. binding/contract 자체가 stale이면 기존 `CHECKPOINT_MISMATCH | CONTRACT_VIOLATION` Recovery를 사용한다.
- raw `next_page_token`과 prior memory-only cache는 복원하지 않는다. Provider 데이터가 restart 사이에 바뀌면 새 조회 결과가 current revision의 authority가 된다.
- `RunRetrievalCacheResolveResultV1.status=FOUND|EXHAUSTED`는 모두 **현재 handle entry와 run/route/query binding이 유효함**을 뜻하므로 resume prerequisite를 충족하고 cache restart를 만들지 않는다. `EXHAUSTED`는 `entry.continuation_exhausted=true`인 유효 read-result이며 `NEXT_PAGE`만 Provider 호출 전 `NO_MORE_PAGE`로 종료한다. `MISSING|CROSS_RUN|BINDING_MISMATCH`만 cache-loss restart 대상이다.
- `RunBudgetV2`의 이미 소비된 LLM/read/page/detail counter는 reset하지 않는다. restart가 새 outbound call을 만들면 일반 budget으로 추가 소비하며 hard cap을 넘기지 않는다.
- `EXCLUDE_EVIDENCE` control이 적용되면 handoff payload clear 전에 stable IDs를 `RetrievalStateV2.exclusion_obligation_segment_ids`에 checkpoint-commit한다. `RETRIEVE_MORE`는 같은 control-patch checkpoint에 `ContextAdjustmentV1.retrieval_need`를 `RetrievalStateV2.pending_user_retrieval_need`로 materialize한다. 이후 cache가 유실되거나 handoff가 이미 CONSUMED여도 fresh retrieval은 exclusion obligation과 pending need를 그대로 사용한다. `pending_user_retrieval_need`는 새 Retrieval revision finalize 전에는 clear하지 않는다.
- Retrieval-dependent checkpoint를 commit할 때 checkpointer adapter는 Local State의 현재 handle dependency를 `GraphCheckpointEnvelopeV1.retrieval_cache_requirements: list[RetrievalCacheRequirementV1]`로 bounded projection한다. Application은 opaque `checkpoint_blob`을 열지 않고 이 metadata만 검사한다. handle dependency가 끝난 checkpoint는 빈 list를 저장하며 Confirmation/Reauth가 Retrieval-local continuation으로 복귀하는 동안에는 requirement를 유지한다.
- Confirmation/Reauth suspend 중 process-memory cache가 사라졌다면 해당 owner resume 전에 같은 handle validation을 수행하고, Retrieval local state가 필요한 target이면 위 RETRIEVAL_ENTRY restart로 정상화한다.
- `RETRIEVAL_CACHE_RESTART` handoff trigger는 `system:retrieval-cache-restart:<run_id>:<checkpoint_generation>` 하나다. staging 전 `WorkflowHandoffRepository.get_by_trigger_command_id(trigger)`로 existing PENDING/DISPATCHED/CONSUMED row를 먼저 resolve하며, 같은 trigger에 두 번째 handoff/control을 만들지 않는다. HTTP command replay 계약을 이 system trigger에 적용하지는 않는다.
- Run Retrieval Cache의 production boundary는 `07 RunRetrievalCachePort` 하나이며 P0 concrete binding은 `adapters/system/memory/run_retrieval_cache.py → InMemoryRunRetrievalCache`다. `retrieval.execute_read`가 entry 저장/resolve를 사용하고, Run terminal cleanup은 `discard_run(run_id)`만 호출한다. module-global dict, LangGraph private cache, Domain/Checkpoint raw continuation 저장은 second authority라서 금지한다.
- Cache-loss restart의 Application semantic owner는 `run.reconcile_retrieval_cache_restart → ReconcileRetrievalCacheRestartHandler` 하나다. 이 Handler만 typed checkpoint의 `retrieval_cache_requirements` 각각을 `RunRetrievalCachePort`로 검사하고, invalid/missing이면 위 deterministic trigger를 dedupe한 뒤 `WorkflowHandoffStageV1(control_kind=RETRIEVAL_CACHE_RESTART, target=MAIN_CONTROL:RETRIEVAL_ENTRY)`를 short UoW로 stage하고 기존 `run.schedule_run_execution`을 호출한다. LangGraph Node/Background adapter는 Repository를 직접 쓰지 않는다.

### 4.2 Exclusion obligation checkpoint lifetime

`EXCLUDE_EVIDENCE`는 one-shot handoff payload 자체를 장기 authority로 사용하지 않는다. Application이 current Preview membership과 `expected_retrieval_revision`을 검증한 뒤 stable `segment_id`를 `RetrievalStateV2.exclusion_obligation_segment_ids`에 materialize하고, **handoff payload clear보다 먼저 checkpoint-commit**한다.

- 이 obligation은 해당 same-Run Retrieval lineage가 새 `RetrievalResultV1`을 finalize할 때까지 crash-safe하게 유지한다.
- cache-loss fresh Retrieval은 checkpoint-local `exclusion_obligation_segment_ids`와 current `RetrievalResultV1.excluded_segment_ids`를 합쳐 `select_evidence`에 적용한다.
- finalize된 `RetrievalResultV1.excluded_segment_ids`는 이후 같은 Run의 `RETRIEVE_MORE` 또는 fresh Retrieval 재진입 시 Local State 초기 projection이 된다.
- Route reconsideration 뒤에도 같은 stable `segment_id`가 다시 나타나면 exclusion을 적용한다. source version/content 또는 chunk schema 변화로 새 ID가 된 Evidence를 fuzzy text matching으로 자동 제외하지 않는다.
- stable `segment_id`의 생성·변경 semantics는 §10.1이 소유한다. 이 절은 checkpoint lifetime만 소유한다.

### 4.3 RETRIEVE_MORE obligation checkpoint lifetime

`RETRIEVE_MORE`는 one-shot handoff payload를 Query Planner까지 직접 들고 가지 않는다. control patch가 `ContextAdjustmentV1.retrieval_need`를 `RetrievalStateV2.pending_user_retrieval_need`에 checkpoint-commit한 뒤에만 handoff payload를 clear한다.

- `retrieval.plan_query`의 user-context-adjustment projection은 raw `ContextAdjustmentV1`이 아니라 `pending_user_retrieval_need`를 읽는다.
- Query/Page/Detail self-loop, Confirmation/Reauth suspend, process-memory cache loss, `RETRIEVAL_CACHE_RESTART`, current-route 실패 후 Route reconsideration/re-entry에서도 같은 need를 보존한다.
- current IN Route로 해결할 수 없으면 기존 `RouteReconsiderationRequiredV1`을 사용하되 pending need는 새 Route가 확정되어 fresh RetrievalResult revision이 finalize될 때까지 유지한다.
- `finalize_retrieval`이 새 `RetrievalResultV1` revision을 checkpoint-commit할 때 `pending_user_retrieval_need=None`을 같은 checkpoint에 기록한다. finalize 전 crash는 need를 잃지 않고, finalize 후 crash는 같은 사용자 need를 다시 적용하지 않는다.
- 두 번째 Context Adjustment는 expected retrieval revision guard를 통과한 경우에만 새로운 pending need를 설정하며 stale request가 current obligation을 덮어쓰지 못한다.

## 5. Retrieval 내부 책임 · LangGraph Node + deterministic Application operation

### 5.1 `retrieval.plan_query`

입력:

```
# 모든 Round
request_intent
input_routes
retrieval_budget

# Follow-up Round에서만 추가되는 bounded Local Projection
current_round_no
prior_query_attempts
unresolved_sufficiency_issues
read_result_summaries
```

`read_result_summaries`는 `read_result_handle`, `route_id`, query identity/hash, 이미 확인한 Resource 참조의 bounded summary, `has_next_page`, continuation state hash 같은 **의미·진행 metadata만** 포함한다. Raw `next_page_token`은 포함하지 않는다.

출력:

```python
class TemporalRangeConstraintV1:
    kind: Literal["TEMPORAL_RANGE"]
    axis: Literal["MESSAGE_TIME", "TASK_SCHEDULED_DATE", "EVENT_TIME", "AVAILABILITY_WINDOW"]
    start_local: str | None
    end_local: str | None
    timezone: str

class ParticipantMatchV1:
    role: Literal["ANY", "SENDER", "RECIPIENT", "ATTENDEE"]
    identity: str

class ParticipantConstraintV1:
    kind: Literal["PARTICIPANT"]
    participants: list[ParticipantMatchV1]
    match_mode: Literal["ANY", "ALL"]

class KeywordConstraintV1:
    kind: Literal["KEYWORD"]
    terms: list[str]
    match_mode: Literal["ANY", "ALL", "PHRASE"]

class ResourceRefConstraintV1:
    kind: Literal["RESOURCE_REF"]
    resource_refs: list[str]

class ContainerRefConstraintV1:
    kind: Literal["CONTAINER_REF"]
    container_refs: list[str]

class StatusScopeConstraintV1:
    kind: Literal["STATUS_SCOPE"]
    values: list[Literal["ANY", "INCOMPLETE", "COMPLETED", "DRAFT", "SENT", "CANCELLED", "CONFIRMED", "TENTATIVE"]]

SemanticRetrievalConstraintV1 = (
    TemporalRangeConstraintV1
    | ParticipantConstraintV1
    | KeywordConstraintV1
    | ResourceRefConstraintV1
    | ContainerRefConstraintV1
    | StatusScopeConstraintV1
)

RetrievalConstraintKindV1 = Literal[
    "TEMPORAL_RANGE", "PARTICIPANT", "KEYWORD",
    "RESOURCE_REF", "CONTAINER_REF", "STATUS_SCOPE"
]

class ConstraintDeltaV2:
    upsert_constraints: list[SemanticRetrievalConstraintV1]
    remove_constraint_kinds: list[RetrievalConstraintKindV1]

class InitialSearchSpecV1:
    mode: Literal["INITIAL"]
    constraints: list[SemanticRetrievalConstraintV1]

class ChangedSearchSpecV1:
    mode: Literal["CHANGED"]
    constraint_delta: ConstraintDeltaV2

SearchConstraintSpecV1 = InitialSearchSpecV1 | ChangedSearchSpecV1

class RouteQueryIntentV2:
    route_id: str
    operation: Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]
    reason_codes: list[str]
    search_spec: SearchConstraintSpecV1 | None
    detail_candidate_ref: str | None

class RetrievalQueryPlanV2:
    schema_version: Literal[2]
    route_queries: list[RouteQueryIntentV2]
    required_information: list[str]
    retrieval_order: list[str]
```

책임:

- 이미 허용된 IN Route 안에서 무엇을 어떤 순서로 찾을지 제안
- 사용자 날짜·사람·선택 Resource·업무 제약을 구조화
- Policy Precondition으로 추가된 필수 Route에서는 해당 검사 목적을 충족할 후보를 수집한다. `TASK + CREATE`의 Tasks Route는 기존 미완료 Task 중복 후보를, `CALENDAR + CREATE`의 Calendar Route는 대상 시간대의 Event/FreeBusy 충돌 근거를 확보한다.
- Page·후보·상세 조회 Budget 제안

금지:

- 새로운 Connector/Resource Route 추가
- OUT Tool 선택
- Provider-native Raw Query·시간 형식·Page Token을 임의 생성해 바로 실행. Gmail Query·RFC3339는 P0 Google Workspace의 구체 예다.
- Write

### 5.2 `retrieval.build_query`

결정적 Application Node다.

```
RetrievalQueryPlanV2 + InputToolRouteV1
→ RouteQueryIntentV2 semantic validation
→ INITIAL SEARCH: InitialSearchSpecV1.constraints를 effective constraints로 확정
→ CHANGED SEARCH: prior effective constraints + ConstraintDeltaV2를 결정적으로 merge
→ SourceFetchPlanBuilder → SourceFetchPlanV1
→ Source별 typed query / ValidatedReadQuerySpecV1
→ 날짜·이메일·Resource ID·지원 constraint 검증
→ NEXT_PAGE이면 prior read_result_handle resolve + continuation binding 검증
→ opaque Page Token을 결정적 코드가 주입
→ MCP Read Arguments
```

- `NEXT_PAGE`에서 LLM은 Page Token을 생성·복사·수정하지 않는다.
- 선택된 handle의 `run_id`, `route_id`, query identity/hash가 현재 frozen IN Route와 맞지 않으면 호출하지 않고 fail-closed한다.
- continuation이 소진된 handle에 대해 같은 Page를 재요청하지 않는다.

### 5.2-A Semantic Constraint · changed SEARCH · `SourceFetchPlanV1`

`SEARCH`의 LLM 출력 권위는 Provider Query가 아니라 **typed semantic retrieval constraint**다. Provider-native Gmail query, RFC3339 변환, MCP Arguments, raw continuation은 결정적 Builder/Executor가 소유한다.

```python
class SourceFetchPlanV1:
    schema_version: Literal[1]
    route_id: str
    connector_id: str
    resource_type: str  # exact connector resource_type copied from the frozen InputToolRouteV1 / SignedToolRegistryEntryV1
    operation_kind: Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]
    effective_constraints: list[SemanticRetrievalConstraintV1]
    query_identity_hash: str
    prior_read_result_handle: str | None
    detail_candidate_ref: str | None
```

#### Initial SEARCH

```
InitialSearchSpecV1.constraints
→ route 지원 constraint 검증
→ normalized effective constraints
→ SourceFetchPlanV1
```

`SourceFetchPlanV1.resource_type`은 `EMAIL | TASK | CALENDAR` 같은 별도 semantic-family vocabulary가 아니다. 해당 `route_id`의 frozen `InputToolRouteV1.resource_type`을 그대로 복사하며, 그 값은 selected/allowed `SignedToolRegistryEntryV1.resource_type`과 exact match해야 한다. 한 Input Route의 `allowed_read_tool_ids`는 모두 같은 Registry `resource_type`을 가져야 하며 서로 다른 Connector resource를 조회하려면 별도 Input Route를 사용한다. Retrieval은 Tool 이름 parsing이나 local 문자열 mapper로 resource identity를 변환하지 않는다.

Initial SEARCH에서 `constraints`는 값이 포함된 semantic constraint여야 한다. constraint 이름만 반환하거나 Provider-native Query 문자열을 반환하는 것은 invalid contract다.

#### CHANGED SEARCH

```
prior SourceFetchPlanV1.effective_constraints
+ ConstraintDeltaV2.upsert_constraints
- ConstraintDeltaV2.remove_constraint_kinds
→ deterministic normalize / conflict check
→ next effective constraints
→ new query_identity_hash
→ SourceFetchPlanV1
```

규칙:

- `CHANGED`는 같은 frozen `route_id` 안의 semantic 검색 제약만 바꾼다. Connector·Resource·Tool 재선택이 아니다.
- `upsert_constraints`는 `kind`별로 기존 값을 교체하거나 새 값을 추가한다. P0에서 같은 Route의 effective set은 동일 `kind`를 중복 보유하지 않는다.
- `remove_constraint_kinds`는 해당 `kind` 전체를 제거한다. frozen Route 또는 Policy Precondition이 필수로 요구하는 constraint는 제거할 수 없다.
- merge 뒤 effective constraints가 prior와 의미상 동일하면 `QUERY_UNCHANGED_AFTER_FAILURE`로 fail-closed하며 새 Retrieval Round로 인정하지 않는다.
- 같은 delta 안에서 같은 `kind`를 upsert와 remove에 동시에 넣거나, Route가 지원하지 않는 constraint, 값 없는 constraint, 모순 temporal range는 Provider 호출 전에 차단한다.
- 날짜/시간 문자열은 semantic local value이며 Provider RFC3339/Gmail query syntax가 아니다. `start_local/end_local`은 offset 없는 ISO local date 또는 local datetime이고 `timezone`은 IANA timezone ID다. 파싱·Timezone 해석·interval 계산·Provider 표현 변환은 deterministic code가 수행하며 invalid/ambiguous local value는 Provider 호출 전에 차단한다.
- `ParticipantConstraintV1.participants`는 역할별 identity를 함께 보존하므로 `from A + to B`처럼 서로 다른 participant role을 한 constraint 안에서 표현할 수 있다.
- `ResourceRefConstraintV1.resource_refs`와 `ContainerRefConstraintV1.container_refs`는 현재 Run/Route에서 이미 검증된 내부 ref만 허용하며 raw Provider resource ID를 LLM이 새로 발명하는 권위가 아니다.
- `QueryAttemptV1.added_constraints/removed_constraints` 같은 이름 목록은 관측·follow-up summary다. **다음 실행계획의 값 권위가 아니며** `SourceFetchPlanV1.effective_constraints`를 재구성하는 두 번째 source로 사용하지 않는다.

#### Operation별 권위

| Operation | LLM/Planner가 결정 | deterministic code가 결정 |
| --- | --- | --- |
| `SEARCH` | semantic constraint 값, reason | merge, normalize, query identity, Provider query, MCP args |
| `NEXT_PAGE` | 추가 Page 필요성과 reason | handle binding, raw continuation resolve/injection |
| `DETAIL_FETCH` | bounded `detail_candidate_ref`, reason | target/resource/tool binding, MCP args |
| `FREEBUSY` | 필요한 semantic 시간 범위와 reason | timezone/RFC3339, interval arithmetic, MCP args |

이 절의 `RetrievalQueryPlanV2 → SourceFetchPlanV1`가 Release canonical이다. `RetrievalQueryPlanV1/RouteQueryIntentV1` 또는 name-only delta는 기존 Artifact/테스트를 읽기 위한 호환 의미일 수 있으나 새 Release planner output authority로 사용하지 않는다.

### 5.3 `retrieval.execute_read`

결정적 Application Node다.

- `input_routes[].allowed_read_tool_ids` 안의 Tool만 호출한다.
- Retrieval LLM은 Tool을 다시 선택하지 않는다. Query Plan을 실제 Tool 호출 순서로 변환하는 것은 Registry metadata와 Query Builder의 결정적 책임이다.
- Page·Detail Fetch·FreeBusy는 Query Plan과 Route에 따라 결정적으로 호출한다.
- List/Search MCP Read 결과의 opaque continuation은 Adapter/Application 경계에서 정규화한 뒤 현재 Run의 Run Retrieval Cache entry에만 보관한다. Local State에는 새 `read_result_handle`과 `QueryAttemptV1` metadata만 기록한다.
- 다음 Round의 `NEXT_PAGE`는 prior handle을 resolve해 continuation을 재사용하되, 동일 query + 동일 continuation state를 새 round로 반복하지 않는다.
- 401·429·5xx·Timeout은 LLM Repair가 아니라 일반 Retry/Reauth 계약을 따른다.

### 5.4 `retrieval.resolve_availability`

Calendar FreeBusy 또는 Event busy interval이 필요한 요청에서만 실행하는 **Retrieval 내부 deterministic Application operation**이다. 이 책임은 availability 산술·정규화를 소유하지만 별도 Supervisor routing authority나 독립 LangGraph Edge를 만들지 않는다. `06 Workflow`의 Retrieval graph topology 안에서 현재 Route/Read 결과를 소비해 `availability_results` Local State를 채우는 결정적 책임으로 취급한다.

```
사용자 시간 제약 + Timezone + busy intervals
→ interval normalization
→ deterministic intersection/subtraction
→ AvailableIntervalV1[]
```

- LLM은 가능한 시간 구간의 산술·겹침 계산을 수행하지 않는다.
- LLM은 `1시간`, `8월 16일 전`, `오후` 같은 의미 제약만 구조화할 수 있고 실제 시각 계산은 이 Node가 수행한다.
- 여러 가능한 구간 중 업무 의미상 하나를 추천해야 할 때만 Work Analysis가 `AvailableIntervalV1[]`을 소비한다.

### 5.5 `retrieval.normalize_segments`

- Gmail HTML 안전 텍스트 변환
- 인용·서명 제거
- Tasks·Calendar를 공통 WorkItem/SourceDocument/SourceSegment로 정규화
- 모든 SourceSegment는 `SourceContentSecurityMetaV1`을 가져 Source Content가 `DATA_ONLY`인 비신뢰 입력임을 구조적으로 보존한다.
- Chunking·Dedup
- Attachment bytes 제외

```python
class SourceContentSecurityMetaV1:
    trust_class: Literal["UNTRUSTED_SOURCE_CONTENT"]
    content_role: Literal["DATA_ONLY"]
    instruction_like_content_detected: bool
    sanitization_flags: list[str]
```

`instruction_like_content_detected=false`도 신뢰 승격을 뜻하지 않는다. 모든 Google Source Content는 항상 비신뢰 데이터이며 이 필드는 탐지·관측·평가 보조 정보다.

### 5.6 `retrieval.rag_retrieve_rerank`

가져온 Segment를 사용자 요청에 대해 검색·정렬한다. Repository/Workflow mapping에서는 이 책임을 `rag_retrieve_rerank`로 통일한다.

```python
class RagCandidateV1:
    segment_id: str
    resource_ref: str
    retrieval_score: float
    reason_codes: list[str]
```

P0 기본:

1. Exact Resource/participant/date/keyword deterministic score
2. lexical retrieval
3. 선택적 embedding/reranker adapter
4. dedup
5. Context Budget에 맞춘 top candidate

RAG backend는 교체 가능하지만 **“후보 전체를 다음 LLM에 전달”하는 구조는 허용하지 않는다.**

### 5.7 `retrieval.select_evidence`

입력은 `request_intent + top rag candidates`다.

출력:

```python
class EvidenceDraftV1:
    segment_id: str
    role: Literal["SUPPORTS", "CONTRADICTS", "CONTEXT"]
    relevance_reason: str

class EvidenceSelectionResultV2:
    schema_version: Literal[2]
    evidence_drafts: list[EvidenceDraftV1]
    selected_segment_ids: list[str]
    excluded_segment_ids: list[str]
```

업무 사실의 최종 해석은 하지 않는다. 사용자의 요청을 뒷받침하거나 반박하는 관련 Segment/Evidence를 고르는 것까지만 담당한다.

`excluded_segment_ids`는 **Retrieval 내부 Evidence selection 결과**다. Browser가 이 field를 직접 mutate하는 경로는 금지한다. 다만 current P0의 `FN-050 Context Preview`는 `run.adjust_context → ContextAdjustmentV1`이라는 validated Application 경계를 통해 사용자 주도 `EXCLUDE_EVIDENCE | RETRIEVE_MORE`를 지원한다. 이 external control은 same Run Retrieval owner로만 전달되고 Browser/Agent가 Main State나 Evidence row를 직접 수정하지 않는다.

### 5.8 `retrieval.assess_sufficiency`

입력은 `request_intent + selected evidence`다.

```python
class SufficiencyResultV2:
    schema_version: Literal[2]
    status: Literal[
        "SUFFICIENT", "NEEDS_MORE_DATA", "NEEDS_CONFIRMATION",
        "ROUTE_RECONSIDERATION_REQUIRED", "PARTIAL", "BLOCKED"
    ]
    issues: list[SufficiencyIssueV2]
```

새 Resource/Connector가 필요하면 `ROUTE_RECONSIDERATION_REQUIRED`를 반환한다. 같은 Route 안에서 Query/Page/Detail을 늘리면 Local Retrieval Round로 처리한다.

### 5.9 `retrieval.finalize_retrieval`

결정적 finalization 책임이다.

```
validated source_statuses
+ selected evidence
+ sufficiency
+ availability_results when applicable
→ RetrievalResultV1
→ final Retrieval disposition
→ optional typed WorkflowSignalV1
```

규칙:

- 새 Query·Resource·Connector·Tool을 선택하지 않는다.
- Evidence를 새로 판단하거나 RAG를 다시 수행하지 않는다.
- `assess_sufficiency`까지 검증된 Local State만 공식 `RetrievalResultV1`으로 조립한다.
- `NEEDS_MORE_DATA`의 same-route bounded loop, `ROUTE_RECONSIDERATION_REQUIRED`, `NEEDS_CONFIRMATION`, `PARTIAL`, `BLOCKED` 의미를 임의로 바꾸지 않는다.
- Parent에는 공식 `RetrievalResultV1`과 필요한 Typed `WorkflowSignalV1`만 반환한다.

## 6. Parent 반환

```python
class MissingInformationV1:
    code: str
    description: str
    required_for: Literal["RETRIEVAL", "ANALYSIS", "PLANNING", "USER_CONFIRMATION"]

class SourceRetrievalStatusV1:
    route_id: str
    resource_type: str
    status: Literal["COMPLETE", "PARTIAL", "FAILED", "NOT_ATTEMPTED"]
    evidence_refs: list[str]
    failure_kind: Literal[
        "AUTH", "SCOPE", "RATE_LIMIT", "TIMEOUT", "PROVIDER",
        "NOT_FOUND", "BUDGET", "OTHER"
    ] | None

class AvailableIntervalV1:
    start: RFC3339
    end: RFC3339
    timezone: str
    derived_from_resource_refs: list[str]

class RetrievalResultV1:
    schema_version: Literal[1]
    meta: StateArtifactMetaV1
    coverage: Literal["SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"]
    context_bundle_ref: str | None
    evidence_refs: list[str]
    selected_segment_ids: list[str]
    excluded_segment_ids: list[str]
    source_resource_refs: list[str]
    source_statuses: list[SourceRetrievalStatusV1]
    availability_results: list[AvailableIntervalV1]
    missing_information: list[MissingInformationV1]
    retrieval_rounds: int
```

`RetrievalResultV1.excluded_segment_ids`는 current Retrieval lineage의 stable segment exclusion obligation을 공식 artifact로 보존한다. `finalize_retrieval`은 `EvidenceSelectionResultV2.excluded_segment_ids + RetrievalStateV2.exclusion_obligation_segment_ids`를 stable dedup하여 기록한다. `RetrievalResultV1`은 다음 Work Analysis 또는 Planning이 소비할 최소 공식 Handoff다. 복수 IN Route에서는 `source_statuses`가 각 Source의 확인 성공·부분 성공·실패·미시도를 보존해야 하며, downstream은 전체 `coverage`만 보고 모든 Source를 확인했다고 추론하지 않는다. `NEEDS_MORE_DATA`, `NEEDS_CONFIRMATION`, `ROUTE_RECONSIDERATION_REQUIRED`, `BLOCKED`는 `RetrievalResultV1`의 상태값이 아니라 `SubgraphReturnV2.disposition`과 Typed `WorkflowSignalV1`로 전달한다. 이미 확보한 Evidence가 독립적으로 유효하면 `coverage=PARTIAL` 결과와 redirection signal을 함께 반환할 수 있다.

## 7. 진입 방식

### RESOURCE_SELECTED

- Tool Route의 IN Resource를 사용자 선택 Resource에 고정
- 선택 ID를 검색 Query로 다시 추측하지 않고 최신 상세 GET
- 후보 점수와 무관하게 강제 포함
- 추가 Resource Route가 필요하면 Tool Route 재검토 또는 사용자 확인

### AGENT_SEARCH

- `RequestIntentV2` + frozen `input_routes` + `retrieval_budget` 기반 Source-native 검색. raw `run_input.user_request`는 Retrieval Local State/Prompt에 별도 Projection하지 않는다.
- Metadata Page에서 후보 축소
- RAG로 관련 Segment를 재선택
- 부족할 때만 같은 Route의 다음 Page·상세 조회 추가

## 8. Connector·Source 전략

Retrieval Core는 `connector_id + resource_type + allowed_read_tool_ids`에 따라 결정적 Query Builder와 `ConnectorReadPort`를 선택하며, Connector별 Source 전략은 Adapter/Tool 계약으로 구체화한다.

P0 Google Workspace Connector:

- Gmail: Thread 검색 → 참여자·제목·시각·Snippet 필터 → 상위 Thread 상세 → Message 시간순 정리 → Segment RAG
- Tasks: Task List 결정 → 목록 → 예정일·상태·Keyword 필터 → 필요한 상세 → Segment RAG
- Calendar: Calendar 결정 → 기간 Event 목록 → 필요한 상세 → 필요할 때 FreeBusy → Segment RAG

추가 Connector는 동일 Retrieval State·Evidence·Sufficiency 계약을 사용하되 Provider-native query/pagination/detail 전략만 Connector별로 확장한다.

### Tasks 시간 의미

- `TASK + CREATE`의 Policy Precondition Route는 기존 미완료 Task를 조회해 중복 판정에 필요한 후보와 Evidence를 Work Analysis에 제공한다. Retrieval 자체는 업무상 최종 중복 여부나 `action_necessity`를 확정하지 않는다.
- Google Task `due`는 Retrieval·WorkItem에서 `scheduled_date`로 정규화한다.
- 실제 업무 `business_deadline`은 Gmail·사용자 요청·Evidence에서 확인한 경우에만 별도 Evidence로 사용한다.
- Task `due`를 업무 마감 Evidence로 승격하거나 둘을 자동 동일시하지 않는다.
- 예정일 경과는 Provider 완료 상태의 근거가 아니다.

### Calendar Typed Query 계약

Calendar Route는 §5의 Release-canonical `RouteQueryIntentV2 + SemanticRetrievalConstraintV1 → SourceFetchPlanV1`을 그대로 사용한다. 별도 `calendar_read_mode`나 `temporal_query` DTO를 current contract로 만들지 않는다.

- Event 조회는 `RouteQueryIntentV2.operation=SEARCH|DETAIL_FETCH`, FreeBusy가 실제로 필요할 때만 `operation=FREEBUSY`를 사용한다. 한 Retrieval round에서 둘 다 필요하면 Query Planner가 typed Route intent를 순서대로 발급하고 deterministic `SourceFetchPlanBuilder`가 각각 materialize한다.
- 시간 범위는 `TemporalRangeConstraintV1(axis=EVENT_TIME|AVAILABILITY_WINDOW, start_local, end_local, timezone)`로 표현한다. relative weekday/daypart 해석은 Request Understanding/typed intent의 bounded semantics를 소비하고 실제 RFC3339 계산·Timezone 적용·interval arithmetic은 deterministic builder가 전담한다.
- Daypart canonical window는 사용자 Timezone 기준 `MORNING 06:00–12:00`, `AFTERNOON 12:00–18:00`, `EVENING 18:00–21:00`이다.
- 다른 Resource의 `business_deadline`을 Calendar Query 기준점으로 쓰려면 Work Analysis 결과를 받아 Additional Retrieval로 재진입해야 한다.

## 9. 후보 점수 초기값

```
정확 Resource·Thread 관계 +40
이메일·참여자 일치       +25
날짜 범위 겹침           +20
제목 정확 구문           +20
Keyword                   최대 +15
상태 적합성               +10
관련 Resource Link        +15
최신성                     최대 +10
```

점수는 Policy가 아니라 중앙 Retrieval Config와 평가 대상이다.

## 10. Segment·Evidence

### 10.1 Stable SourceSegment identity

`segment_id`는 UI row용 임의 UUID가 아니라 **same provider source version을 다시 normalize/chunk했을 때 동일하게 재생성되는 deterministic Evidence identity**다. `05 Retrieval`이 이 identity semantics의 단일 owner다.

```python
class SourceSegmentIdentityV1:
    schema_version: Literal[1]
    connector_id: str
    source_kind: Literal["gmail", "tasks", "calendar"]
    resource_type: str
    resource_id: str
    source_version_ref: str | None
    chunk_schema_version: int
    chunk_ordinal: int
    normalized_content_sha256: str
```

`segment_id = "seg_" + SHA256(canonical_json(SourceSegmentIdentityV1))`로 생성한다. `source_version_ref`는 Provider가 stable revision/version/etag를 제공하면 사용하고, 없으면 `normalized_content_sha256 + deterministic chunk_ordinal`이 version evidence를 대신한다. Normalize/Chunk algorithm과 `chunk_schema_version`은 같은 입력에 deterministic해야 한다. Random UUID, retrieval revision 번호, query/page ordinal, process-memory handle을 `segment_id` authority로 사용하지 않는다.

- 같은 Provider resource version + 같은 normalized content + 같은 chunk schema/boundary면 fresh Retrieval에서도 같은 `segment_id`를 생성한다.
- Provider source version/content 또는 chunk schema가 바뀌어 Evidence 의미가 달라지면 새 `segment_id`를 발급한다. 과거 exclusion을 변경된 content에 임의 승계하지 않는다.
- `EXCLUDE_EVIDENCE`는 선택 당시 current Preview의 stable `segment_id`만 허용한다. Application은 `expected_retrieval_revision` membership을 검증한다.

### 10.2 Segment·Evidence size · trust boundary

- Gmail Chunk 목표 600 Token, 최대 900 Token, Overlap 80 Token
- Token은 Provider-independent deterministic estimated token 단위다.
- Evidence excerpt UTF-8 8 KiB 이하
- Source 원문은 비신뢰 데이터
- 실제 계획에 사용된 최소 Evidence만 Domain Store에 저장

## 11. Context Budget

- System·Policy·Tool Schema 최대 15%
- 사용자 요청·대화 최대 15%
- 검색 Context 목표 50~55%
- Structured Output Reserve 최소 10%
- Safety Margin 최소 10%

Node Projection 규칙 때문에 Tool Route 전체·Registry 전체·후보 전체를 모든 Retrieval LLM 호출에 반복 삽입하지 않는다.

## 12. 추가 Retrieval

```
Round 0 정확 검색
Round 1 같은 IN Route에서 제약 하나 완화 또는 다음 Page/Detail
Round 2 같은 IN Route의 마지막 표적 확장
```

- 같은 IN Route 내부 확장은 Retrieval Subgraph가 소유한다.
- 사용자 지정 범위를 벗어나는 기간 확장은 확인을 우선한다.
- 새로운 Resource/Connector가 필요하면 `RouteReconsiderationRequiredV1`과 함께 `ROUTE_RECONSIDERATION_REQUIRED`를 Parent에 반환한다.
- 동명이인·대상 복수·사용자만 해결 가능한 정보는 추가 Google 조회보다 확인 질문을 우선한다.

## 13. 초기 API Budget

```
RETRIEVAL_PAGE_SIZE=<configured>
MAX_RETRIEVAL_ROUNDS=3
MAX_ADDITIONAL_RETRIEVAL_ROUNDS=2
MAX_PAGES_PER_SOURCE_PER_ROUND=2
MAX_TOTAL_SOURCE_PAGES=8
MAX_METADATA_CANDIDATES_PER_SOURCE=40
MAX_DETAIL_FETCH_PER_SOURCE=5
MAX_TOTAL_DETAIL_RESOURCES=12
```

## 14. Cache와 영속 경계

- Sidebar Cache: React Session Memory
- Run Retrieval Cache: 현재 Run Memory, Run 종료 시 폐기
- Main Graph State: `RetrievalResultV1`과 Cache/Evidence Reference만 저장
- 강제 최신 조회: RESOURCE_SELECTED 시작, Plan 확정 전, 승인 후 실행 전, 실행 후 Verification
- 저장 금지: 전체 Sidebar 목록, **Main State·Checkpoint·Domain DB·Trace·Audit·Prompt의 Raw Provider Page Token**, 미사용 후보, Gmail 전체 원문, FreeBusy 전체 응답, RAG 후보 전체와 score 전체

예외: Retrieval local pagination을 위한 raw Provider continuation은 **현재 Run의 Run Retrieval Cache read-result entry 내부에서만 memory-only**로 보관할 수 있다. Local State에는 raw token이 아니라 `read_result_handle`과 continuation state hash만 남기며 Run 종료 시 함께 폐기한다.

- 저장 허용: 실제 사용 ResourceRef, 최소 Evidence excerpt, Action 연결

## 15. Evaluation consumption boundary

`05 Retrieval`은 제품 Retrieval semantics와 runtime artifact만 소유한다. Dataset·Case·Fixture·Gold·`evaluation_item_id`·Candidate 비교 schema는 `13 Evaluation`이 소유하며 이 문서에서 복제하지 않는다.

평가가 Retrieval을 비교할 때는 current owner contract의 `ToolRoutePlanV2`, `RetrievalResultV1`, `QueryAttemptV1`, Evidence/Resource reference와 configured Retrieval identity를 소비한다. Backend 비교는 동일한 입력 Route·Fixture 조건을 유지하고 비교하려는 backend/config만 변경한다. Evaluation metadata는 Product Prompt, Main State, Checkpoint, Domain DB의 새로운 authority field가 될 수 없다.

## 16. QueryAttempt·Confidence·재검색 계약

이 절은 `15 Agent Capability · Failure · Prompt` current contract를 적용한다.

### 16.1 QueryAttemptV1

`QueryAttemptV1`은 이 문서가 소유하는 **유일한 Release current schema**다. `15 Prompt/Failure`는 이 타입을 소비·검증할 뿐 별도 `schema_version=1` payload를 정의하지 않는다.

```python
class ValidatedReadQuerySpecV1:
    tool_id: str
    tool_schema_version: str
    canonical_arguments: CanonicalArguments

class QueryAttemptV1:
    schema_version: Literal[1]
    query_attempt_id: str
    run_id: str
    route_id: str
    round_no: int
    attempt_no: int
    resource_type: str  # exact connector resource_type copied from the frozen InputToolRouteV1 / SignedToolRegistryEntryV1
    connector_id: str
    operation_kind: Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]
    normalized_intent_constraints: list[SemanticRetrievalConstraintV1]
    query_spec: ValidatedReadQuerySpecV1
    previous_query_hash: str | None
    page_state_hash: str | None
    added_constraints: list[str]
    removed_constraints: list[str]
    change_reason_code: str | None
    candidate_count: int | None
    top_score: float | None
    score_margin: float | None
    confidence_band: Literal["HIGH", "MEDIUM", "LOW", "NONE"] | None
    retrieval_config_version: str
    score_config_version: str
    threshold_config_version: str
    stop_reason: str | None
```

### 16.2 반복과 Pagination

- 같은 Query와 새로운 Page Token을 사용하는 `NEXT_PAGE`는 정상 Pagination이다.
- 실패 뒤 같은 Query와 같은 Page 상태로 `SEARCH`를 반복하면 `QUERY_UNCHANGED_AFTER_FAILURE`다.
- `DETAIL_FETCH` 재호출은 Run Cache 또는 Provider 기술 재시도 규칙을 따른다.
- 추가 Retrieval 시 최소 하나의 제약 변경 또는 같은 Route의 Page/Detail 확장이 있어야 한다.
- 새로운 Resource Route를 Local Retry로 몰래 추가하지 않는다.

### 16.3 저신뢰 후보

- Confidence Band는 `HIGH`, `MEDIUM`, `LOW`, `NONE`으로 고정한다.
- 실제 점수와 Threshold는 중앙 Retrieval Config가 소유한다.
- `AGENT_SEARCH`에서 `LOW` 또는 `NONE` 후보만 존재하면 자동 확정하지 않는다.
- `RESOURCE_SELECTED`는 사용자가 고른 Resource ID를 점수와 관계없이 상세 GET한다.
- 후보 1위와 2위의 점수 차이가 설정된 Margin보다 작으면 확인 또는 추가 Retrieval로 전환한다.

### 16.4 결정적 평가

다음 항목은 LLM Judge가 아니라 코드 Grader가 우선한다.

- ToolRoute의 허용 Read Tool 밖 호출 여부
- 사용자 날짜·사람·이메일·선택 Resource가 Query Spec에 반영됐는지
- 같은 실패 Query가 반복됐는지
- 추가 Retrieval 횟수와 Source Page Budget 준수
- 저신뢰 후보를 임의로 확정했는지
- RAG Top Candidate 밖 Evidence를 근거 없이 생성했는지

## 17. Clarification · Overbroad Retrieval

- 요청 자체에서 드러나는 모호성은 Request Understanding에서 확인한다.
- Tool Route가 불명확하면 Tool Route Subgraph가 확인한다.
- 동명이인·복수 Resource·저신뢰 후보처럼 검색 후 드러나는 모호성은 후보·차이와 함께 `NEEDS_CONFIRMATION`으로 보낸다.
- 전체 Mailbox·장기간 무제한 원문·모든 Workspace Source 전체 조회는 `BLOCKED`다.
- Calendar 시간 overlap은 conflict와 분리하며 관계 근거를 Work Analysis에 전달한다.

## 18. 정보 부족 분류와 결정적 종료 Guard

### 18.1 Sufficiency Issue

```python
class SufficiencyIssueV2:
    schema_version: Literal[2]
    slot: str
    issue_type: Literal["MISSING", "CONFLICT"]
    required: bool
    resolution_source: Literal["USER", "GOOGLE", "POLICY", "ROUTE"]
    safety_critical: bool
    reason_codes: list[str]
```

### 18.2 결정적 종료 Guard

1. `required=true`이면서 safety-critical 또는 `resolution_source=POLICY`면 `BLOCKED`.
2. `resolution_source=USER`면 추가 Google 조회보다 `NEEDS_CONFIRMATION` 우선.
3. `resolution_source=ROUTE`면 `ROUTE_RECONSIDERATION_REQUIRED`.
4. `resolution_source=GOOGLE`이고 같은 Route의 Budget이 남으면 `NEEDS_MORE_DATA`.
5. Budget 소진 + Read-only + 근거 있는 부분 답변 가능이면 `PARTIAL`.
6. Write 필수 Target/Argument/Evidence 부족은 사용자 해결 가능하면 `NEEDS_CONFIRMATION`, 아니면 `BLOCKED`.

LLM confidence 하나로 안전 Route를 결정하지 않는다. 모든 Graph Profile은 동일 Guard를 사용한다.

## 19. Gmail Attachment Retrieval 경계

- Gmail Message 상세의 첨부파일은 `filename`, `mime_type`, `size_bytes`, Google `attachment_id` Metadata까지만 Retrieval 후보 정보로 사용할 수 있다.
- `gmail_get_attachment(message_id, attachment_id)`는 사용자 다운로드 또는 결정적 파일 전달 요청에서만 실행한다.
- 첨부파일 bytes는 Retrieval Cache·SourceSegment·EvidenceDraft·ContextBundle에 넣지 않는다.
- 첨부파일 내용을 읽어 Evidence로 만드는 기능은 P0 범위 밖이다.
- Attachment Download는 LLM 재검색·추가 Retrieval Budget과 분리된 결정적 READ I/O다.
