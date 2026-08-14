# 05. Google Work Agent · Context · Retrieval 설계서

> **상태:** Draft v2.12 · **기준일:** 2026-08-14 · **대상:** P0 MVP
>
> Retrieval은 `ToolRoutePlanV2.input_plan.input_routes`를 입력으로 받는 하나의 LangGraph Subgraph다. Tool Route는 Main Graph에서 이미 확정되어 있으며 Retrieval은 Tool 종류를 다시 선택하지 않는다. Subgraph 내부에서 Query 계획 → 결정적 Read → Normalize/Segment → Run-scoped RAG → Evidence → Sufficiency를 수행하고 `RetrievalResultV1`과 필요한 Typed `WorkflowSignalV1`만 Parent에 반환한다.

## 1. 목적

고정된 Connector IN Route에서 필요한 자료를 최소 호출로 수집하고, 가져온 자료를 그대로 다음 LLM에 전달하지 않고 **관련 Segment를 RAG로 검색·정렬하여 Evidence만 선별**한다. 영구 Vector Index는 P0 필수가 아니며 Run-scoped Retrieval/Reranking을 기본 구조로 사용한다. P0 첫 Connector는 `google_workspace`이며 Source 전략은 Gmail·Tasks·Calendar에 대해 구체화한다.

## 2. 확정 결정

- `CTX-001`: 요청 시점 Connector 원본 연합 검색
- `CTX-002`: IN/OUT Tool Route 선택은 Retrieval 이전 `Tool Route Subgraph`가 소유
- `CTX-003`:

- `CTX-003A`: `input_routes`에는 사용자 의미상 필요한 READ뿐 아니라 `01-B` Policy Precondition으로 결정적으로 보강된 필수 READ도 포함될 수 있으며 Retrieval은 `required=true` Route를 임의 생략하지 않는다. `TASK + CREATE`는 기존 미완료 Task 중복 후보, `CALENDAR + CREATE`는 Event/FreeBusy 충돌 근거를 수집한다.
- `CTX-003B`: Policy Precondition READ가 사용자 명시 범위 밖이면 Retrieval이 범위를 넓히지 않는다. Tool Route owner의 `SCOPE_EXPANSION_REQUIRED` Confirmation과 APPROVED `PolicyConfirmationReceiptV1` 이후 확정된 Input Route만 실행한다.
 Retrieval은 고정된 `input_routes`만 사용하고 Resource·Connector·Tool 종류를 재선택하지 않음
- `CTX-004`: LLM이 Raw Query·Page Token·MCP Arguments를 직접 실행하지 않음
- `CTX-005`: Query 계획 → 결정적 Query Builder → MCP Read → Normalize/Segment → Run-scoped RAG → Evidence → Sufficiency
- `CTX-006`: 가져온 후보 전체를 Work Analysis·Planning Prompt에 직접 전달하지 않음
- `CTX-007`: 부족 시 같은 IN Route 안에서 추가 Retrieval 최대 2회
- `CTX-007A`: Retrieval self-loop의 raw Provider continuation은 현재 Run의 **Run Retrieval Cache read-result entry**만 memory-only로 소유한다. Retrieval Local State에는 raw token을 복제하지 않고 `read_result_handle`만 둔다.
- `CTX-007B`: raw continuation은 Main State·LangGraph Checkpoint·Domain DB·Prompt·Trace·Audit에 저장하거나 전달하지 않는다. Run 종료 시 Cache entry와 함께 폐기한다.
- `CTX-007C`: Follow-up `retrieval.plan_query`는 이전 Round의 의미 수준 정보만 소비한다. `current_round_no`, prior `QueryAttempt`, unresolved `SufficiencyIssueV2`, bounded read-result summary를 사용할 수 있지만 raw Page Token·Provider-native Query·MCP Arguments를 입력으로 받지 않는다.
- `CTX-007D`: `NEXT_PAGE`는 결정적 Read Node가 prior `read_result_handle`을 resolve해 `run_id + route_id + query identity/hash + continuation exhaustion`을 검증한 뒤 수행한다. unknown/cross-run/mismatched/exhausted handle은 Provider 호출 전에 fail-closed한다. 동일 Query + 동일 continuation state 재실행은 새 Retrieval Round로 인정하지 않는다.
- `CTX-008`: 새 Resource/Connector Route가 필요하면 `ROUTE_RECONSIDERATION_REQUIRED`를 Parent에 반환
- `CTX-009`: 일반 Retrieval은 Action Row가 아니라 Trace·Checkpoint·Run Cache 대상
- `CTX-010`: RAG는 구조적 필수 단계다. 초기 backend는 deterministic score/lexical retrieval을 사용할 수 있고 Embedding·Reranker·Vector Index는 교체 가능한 실험 변수다.

## 3. 전체 흐름

```text
RequestIntentV2 + ToolRoutePlanV2.input_plan.input_routes
→ Retrieval Subgraph
  → plan_query
  → deterministic query builder
  → validated MCP Read
  → Metadata / detail fetch
  → normalize + segment
  → Run-scoped RAG retrieve/rerank
  → select_evidence
  → assess_sufficiency
  → finalize
→ RetrievalResultV1
```

Main Graph에는 Query 후보·Page Token·전체 후보·RAG score를 올리지 않는다.

## 4. Retrieval Subgraph State

```python
class RetrievalStateV1:
    request_intent: RequestIntentV2
    input_routes: list[InputToolRouteV1]
    query_plan: RetrievalQueryPlanV1 | None
    query_attempts: list[QueryAttempt]
    read_result_handles: list[str]
    segment_handles: list[str]
    rag_candidates: list[RagCandidateV1]
    evidence_selection: EvidenceSelectionResultV2 | None
    sufficiency: SufficiencyResultV2 | None
    final_result: RetrievalResultV1 | None
```

규칙:

- `request_intent`, `input_routes`는 Parent Projection이며 Retrieval이 수정하지 않는다.
- `query_plan`, `query_attempts`, `read_result_handles`, `segment_handles`, `rag_candidates`는 Local State다. `read_result_handle`은 현재 Run Cache entry를 가리키며 raw continuation 자체를 포함하지 않는다.
- Parent에는 `RetrievalResultV1`만 병합한다.
- 실제 Connector 원문과 raw pagination continuation은 Run Retrieval Cache Handle로 참조하고 Main State·Checkpoint·Domain DB·Prompt·Trace·Audit에 복제하지 않는다.

## 5. Node별 책임

### 5.1 `retrieval.plan_query`

입력:

```text
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

출력:

```python
class RetrievalQueryPlanV1:
    schema_version: int
    route_queries: list[RouteQueryIntentV1]
    required_information: list[str]
    retrieval_order: list[str]
```

`RouteQueryIntentV1` is the Retrieval-local semantic proposal for exactly one
frozen IN Route. It is used for both the initial query plan and a follow-up
round; it is not a Connector or MCP argument DTO.

```python
class ConstraintDeltaV1:
    added_constraints: list[str]
    removed_constraints: list[str]

class RouteQueryIntentV1:
    route_id: str
    operation_kind: Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]
    reason_codes: list[str]
    constraint_delta: ConstraintDeltaV1 | None
    detail_candidate_ref: str | None
```

Follow-up invariants:

- `route_id` must name a member of frozen `input_routes`; an unknown route
  requires `ROUTE_RECONSIDERATION_REQUIRED` and is never locally executed.
- `reason_codes` must bind an unresolved `SufficiencyIssueV2`.
- follow-up `SEARCH` requires a non-empty `constraint_delta`; unchanged search
  is rejected before a Connector read.
- `DETAIL_FETCH.detail_candidate_ref` is one opaque candidate reference from
  the bounded read-result summary. It is resolved by Run Retrieval Cache; it
  is not a provider resource ID.
- `NEXT_PAGE` has neither `constraint_delta` nor `detail_candidate_ref` and
  never contains a raw continuation or page token.
- `FREEBUSY` retains its fixed CALENDAR-route meaning and has neither
  follow-up-only field.

책임:

- 이미 허용된 IN Route 안에서 무엇을 어떤 순서로 찾을지 제안
- 사용자 날짜·사람·선택 Resource·업무 제약을 구조화
- Page·후보·상세 조회 Budget 제안

Follow-up 입력 규칙:

- `prior_query_attempts`는 이전 Search/Page/Detail의 정규화된 의미·hash·결과 요약만 전달한다.
- `unresolved_sufficiency_issues`는 같은 frozen IN Route에서 추가 획득이 가능한 부족 정보만 전달한다.
- `read_result_summaries`는 `has_next_page`, exhaustion, result count, 이미 확인한 Resource 식별용 bounded metadata만 허용한다.
- raw Provider continuation, Provider-native Query 문자열, MCP Arguments는 LLM Prompt 입력이 아니다.

금지:

- 새로운 Connector/Resource Route 추가
- OUT Tool 선택
- Raw Gmail Query·RFC3339·Page Token을 임의 생성해 바로 실행
- Write

### 5.2 `retrieval.build_query`

결정적 Application Node다.

```text
RetrievalQueryPlanV1 + InputToolRouteV1
→ Source별 typed query
→ 날짜·이메일·Resource ID·Page Token 검증
→ MCP Read Arguments
```

### 5.3 `retrieval.execute_read`

결정적 Application Node다.

- `input_routes[].allowed_read_tool_ids` 안의 Tool만 호출한다.
- Retrieval LLM은 Tool을 다시 선택하지 않는다. Query Plan을 실제 Tool 호출 순서로 변환하는 것은 Registry metadata와 Query Builder의 결정적 책임이다.
- Page·Detail Fetch·FreeBusy는 Query Plan과 Route에 따라 결정적으로 호출한다.
- `NEXT_PAGE`는 prior `read_result_handle`을 Run Retrieval Cache에서 resolve하고 handle의 `run_id + route_id + query identity/hash`가 현재 frozen IN Route와 일치하며 continuation이 미소진일 때만 raw token을 MCP Read Argument에 주입한다.
- unknown handle, cross-run handle, route/query mismatch, exhausted continuation은 Provider 호출 전에 fail-closed한다.
- 401·429·5xx·Timeout은 LLM Repair가 아니라 일반 Retry/Reauth 계약을 따른다.

### 5.4 `retrieval.normalize_segments`

- Gmail HTML 안전 텍스트 변환
- 인용·서명 제거
- Tasks·Calendar를 공통 WorkItem/SourceDocument/SourceSegment로 정규화
- Chunking·Dedup
- Attachment bytes 제외


### 5.4A `retrieval.resolve_availability`
Calendar FreeBusy 또는 Event busy interval이 필요한 요청에서 실행하는 결정적 Application Node다. 사용자 시간 제약과 timezone, busy intervals를 정규화하고 interval intersection/subtraction으로 `AvailableIntervalV1[]`을 계산한다. LLM은 가능한 시간 구간 산술을 수행하지 않으며, 여러 구간 중 업무 의미상 추천이 필요할 때만 Work Analysis가 결과를 소비한다.


### 5.5 `retrieval.rag_retrieve`

가져온 Segment를 사용자 요청에 대해 검색·정렬한다.

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

### 5.6 `retrieval.select_evidence`

입력은 `request_intent + top rag candidates`다.

출력:

```python
class EvidenceSelectionResultV2:
    schema_version: int
    evidence_drafts: list[dict]
    selected_segment_ids: list[str]
    excluded_segment_ids: list[str]
```

업무 사실의 최종 해석은 하지 않는다. 사용자의 요청을 뒷받침하거나 반박하는 관련 Segment/Evidence를 고르는 것까지만 담당한다.

### 5.7 `retrieval.assess_sufficiency`

입력은 `request_intent + selected evidence`다.

```python
class SufficiencyResultV2:
    schema_version: int
    status: Literal[
        "SUFFICIENT", "NEEDS_MORE_DATA", "NEEDS_CONFIRMATION",
        "ROUTE_RECONSIDERATION_REQUIRED", "PARTIAL", "BLOCKED"
    ]
    issues: list[SufficiencyIssue]
```

새 Resource/Connector가 필요하면 `ROUTE_RECONSIDERATION_REQUIRED`를 반환한다. 같은 Route 안에서 Query/Page/Detail을 늘리면 Local Retrieval Round로 처리한다.

## 6. Parent 반환

```python
class RetrievalResultV1:
    schema_version: int
    meta: StateArtifactMetaV1
    coverage: Literal["SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"]
    context_bundle_ref: str | None
    evidence_refs: list[str]
    selected_segment_ids: list[str]
    source_resource_refs: list[str]
    missing_information: list[dict]
    retrieval_rounds: int
```

`RetrievalResultV1`은 다음 Work Analysis가 소비할 최소 공식 Handoff다. `NEEDS_MORE_DATA`, `NEEDS_CONFIRMATION`, `ROUTE_RECONSIDERATION_REQUIRED`, `BLOCKED`는 `RetrievalResultV1`의 상태값이 아니라 `SubgraphReturnV2.disposition`과 Typed `WorkflowSignalV1`로 전달한다. 이미 확보한 Evidence가 독립적으로 유효하면 `coverage=PARTIAL` 결과와 redirection signal을 함께 반환할 수 있다.

## 7. 진입 방식

### RESOURCE_SELECTED

- Tool Route의 IN Resource를 사용자 선택 Resource에 고정
- 선택 ID를 검색 Query로 다시 추측하지 않고 최신 상세 GET
- 후보 점수와 무관하게 강제 포함
- 추가 Resource Route가 필요하면 Tool Route 재검토 또는 사용자 확인

### AGENT_SEARCH

- RequestIntent와 고정 IN Route 기반 Source-native 검색
- Metadata Page에서 후보 축소
- RAG로 관련 Segment를 재선택
- 부족할 때만 같은 Route의 다음 Page·상세 조회 추가

## 8. Source 전략

- Gmail: Thread 검색 → 참여자·제목·시각·Snippet 필터 → 상위 Thread 상세 → Message 시간순 정리 → Segment RAG
- Tasks: Task List 결정 → 목록 → 예정일·상태·Keyword 필터 → 필요한 상세 → Segment RAG
- Calendar: Calendar 결정 → 기간 Event 목록 → 필요한 상세 → 필요할 때 FreeBusy → Segment RAG

### Tasks 시간 의미

- Google Task `due`는 Retrieval·WorkItem에서 `scheduled_date`로 정규화한다.
- 실제 업무 `business_deadline`은 Gmail·사용자 요청·Evidence에서 확인한 경우에만 별도 Evidence로 사용한다.
- Task `due`를 업무 마감 Evidence로 승격하거나 둘을 자동 동일시하지 않는다.
- 예정일 경과는 Provider 완료 상태의 근거가 아니다.

### Tasks Policy Precondition
`TASK + CREATE`에서는 기존 미완료 Task를 조회해 중복 판정 후보와 Evidence를 Work Analysis에 제공한다. Retrieval 자체는 최종 중복 여부나 `action_necessity`를 확정하지 않는다.


### Calendar Typed Query 계약

Calendar Route Query는 자유형 문자열 대신 다음 Typed 필드를 사용한다.

```python
calendar_read_mode: "EVENTS_ONLY" | "EVENTS_AND_FREEBUSY"

temporal_query:
  schema_version: 1
  relation: "RELATIVE" | "ABSOLUTE"
  relative_unit: "DAY" | "WEEK" | null
  relative_offset: integer | null
  weekday: "MON" | "TUE" | "WED" | "THU" | "FRI" | "SAT" | "SUN" | null
  daypart: "MORNING" | "AFTERNOON" | "EVENING" | null
  absolute_start: RFC3339 | null
  absolute_end: RFC3339 | null
```

- `calendar_read_mode` 판단은 `retrieval.plan_query`가 고정 CALENDAR Route 안에서 수행한다.
- 실제 RFC3339 계산과 Timezone 적용은 결정적 코드가 전담한다.
- Daypart는 사용자 Timezone 기준 `MORNING 06:00–12:00`, `AFTERNOON 12:00–18:00`, `EVENING 18:00–21:00`이다.
- 다른 Resource의 `business_deadline`을 Calendar Query 기준점으로 쓰려면 Work Analysis 결과를 받아 Additional Retrieval로 재진입해야 한다.

## 9. 후보 점수 초기값

```text
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

```text
Round 0 정확 검색
Round 1 같은 IN Route에서 제약 하나 완화 또는 다음 Page/Detail
Round 2 같은 IN Route의 마지막 표적 확장
```

- 같은 IN Route 내부 확장은 Retrieval Subgraph가 소유한다.
- Additional Retrieval은 `NEXT_PAGE`, `DETAIL_FETCH`, 또는 unresolved `SufficiencyIssueV2`에 근거한 changed `SEARCH`처럼 새 정보 획득 가능성이 있어야 한다. 동일 Query + 동일 continuation state 재실행은 Round를 소비하지 않는다.
- self-loop 중 raw continuation은 Parent/Supervisor로 반환하지 않고 `read_result_handle → Run Retrieval Cache` 경계에서만 소비한다.
- 사용자 지정 범위를 벗어나는 기간 확장은 확인을 우선한다.
- 새로운 Resource/Connector가 필요하면 `RouteReconsiderationRequiredV1`과 함께 `ROUTE_RECONSIDERATION_REQUIRED`를 Parent에 반환한다.
- 동명이인·대상 복수·사용자만 해결 가능한 정보는 추가 Google 조회보다 확인 질문을 우선한다.

## 13. 초기 API Budget

```text
RETRIEVAL_PAGE_SIZE=20
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
- Run Retrieval Cache: 현재 Run Memory, Run 종료 시 폐기. read-result entry가 raw Provider continuation의 유일한 Runtime owner다.
- Main Graph State: `RetrievalResultV1`과 Cache/Evidence Reference만 저장
- 강제 최신 조회: RESOURCE_SELECTED 시작, Plan 확정 전, 승인 후 실행 전, 실행 후 Verification
- 저장 금지: 전체 Sidebar 목록, **Run Retrieval Cache memory-only continuation 예외를 제외한 raw Page Token**, 미사용 후보, Gmail 전체 원문, FreeBusy 전체 응답, RAG 후보 전체와 score 전체
- 저장 허용: 실제 사용 ResourceRef, 최소 Evidence excerpt, Action 연결

## 15. 실험 연결

Fixture Snapshot과 평가 Case는 다음을 고정한다.

```text
fixture_snapshot_id
case_id
user_prompt_id
retrieval_config_version
required_resource_ids
required_evidence
```

Embedding·Reranker·Vector Index를 비교할 때 `ToolRoutePlanV2`은 고정하고 RAG backend만 바꾼다.

## 16. 평가 연결 계약

```text
case_id
user_prompt_id
fixture_snapshot_id
retrieval_config_version
required_resource_ids
required_evidence
evaluation_item_id
```

하나의 Case는 여러 User Prompt를 가질 수 있다. Retrieval 평가는 `evaluation_item_id` 단위로 기록한다.

## 17. QueryAttempt·Confidence·재검색 계약

이 절은 `15. Agent Capability · Failure · Prompt 공통 계약 v1.21`를 적용한다.

### 17.1 QueryAttempt

```python
class QueryAttempt:
    schema_version: int
    query_attempt_id: str
    run_id: str
    route_id: str
    round_no: int
    attempt_no: int
    resource_type: Literal["EMAIL", "TASK", "CALENDAR"]
    connector_id: str
    operation_kind: Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]
    normalized_intent_constraints: dict
    query_spec: dict
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

### 17.2 반복과 Pagination

- 같은 Query와 **새로운 continuation state**를 사용하는 `NEXT_PAGE`는 정상 Pagination이다. raw token은 QueryAttempt에 저장하지 않고 `page_state_hash`/안전 hash만 남긴다.
- 실패 뒤 같은 Query와 같은 Page 상태로 `SEARCH`를 반복하면 `QUERY_UNCHANGED_AFTER_FAILURE`다.
- `DETAIL_FETCH` 재호출은 Run Cache 또는 Provider 기술 재시도 규칙을 따른다.
- 추가 Retrieval 시 최소 하나의 제약 변경 또는 같은 Route의 **새 Page/Detail 확장**이 있어야 한다. 동일 Query + 동일 continuation state 반복은 추가 Retrieval로 인정하지 않는다.
- 새로운 Resource Route를 Local Retry로 몰래 추가하지 않는다.

### 17.3 저신뢰 후보

- Confidence Band는 `HIGH`, `MEDIUM`, `LOW`, `NONE`으로 고정한다.
- 실제 점수와 Threshold는 중앙 Retrieval Config가 소유한다.
- `AGENT_SEARCH`에서 `LOW` 또는 `NONE` 후보만 존재하면 자동 확정하지 않는다.
- `RESOURCE_SELECTED`는 사용자가 고른 Resource ID를 점수와 관계없이 상세 GET한다.
- 후보 1위와 2위의 점수 차이가 설정된 Margin보다 작으면 확인 또는 추가 Retrieval로 전환한다.

### 17.4 결정적 평가

다음 항목은 LLM Judge가 아니라 코드 Grader가 우선한다.

- ToolRoute의 허용 Read Tool 밖 호출 여부
- 사용자 날짜·사람·이메일·선택 Resource가 Query Spec에 반영됐는지
- 같은 실패 Query가 반복됐는지
- 추가 Retrieval 횟수와 Source Page Budget 준수
- 저신뢰 후보를 임의로 확정했는지
- RAG Top Candidate 밖 Evidence를 근거 없이 생성했는지

## 18. Clarification · Overbroad Retrieval

- 요청 자체에서 드러나는 모호성은 Request Understanding에서 확인한다.
- Tool Route가 불명확하면 Tool Route Subgraph가 확인한다.
- 동명이인·복수 Resource·저신뢰 후보처럼 검색 후 드러나는 모호성은 후보·차이와 함께 `NEEDS_CONFIRMATION`으로 보낸다.
- 전체 Mailbox·장기간 무제한 원문·모든 Workspace Source 전체 조회는 `BLOCKED`다.
- Calendar 시간 overlap은 conflict와 분리하며 관계 근거를 Work Analysis에 전달한다.

## 19. 정보 부족 분류와 결정적 종료 Guard

### 19.1 Sufficiency Issue

```python
class SufficiencyIssue:
    slot: str
    issue_type: Literal["MISSING", "CONFLICT"]
    required: bool
    resolution_source: Literal["USER", "GOOGLE", "POLICY", "ROUTE"]
    safety_critical: bool
    reason_codes: list[str]
```

### 19.2 결정적 종료 Guard

1. `required=true`이면서 safety-critical 또는 `resolution_source=POLICY`면 `BLOCKED`.
2. `resolution_source=USER`면 추가 Google 조회보다 `NEEDS_CONFIRMATION` 우선.
3. `resolution_source=ROUTE`면 `ROUTE_RECONSIDERATION_REQUIRED`.
4. `resolution_source=GOOGLE`이고 같은 Route의 Budget이 남으면 `NEEDS_MORE_DATA`.
5. Budget 소진 + Read-only + 근거 있는 부분 답변 가능이면 `PARTIAL`.
6. Write 필수 Target/Argument/Evidence 부족은 사용자 해결 가능하면 `NEEDS_CONFIRMATION`, 아니면 `BLOCKED`.

LLM confidence 하나로 안전 Route를 결정하지 않는다. 모든 Graph Profile은 동일 Guard를 사용한다.

## Gmail Attachment Retrieval 경계

- Gmail Message 상세의 첨부파일은 `filename`, `mime_type`, `size_bytes`, Google `attachment_id` Metadata까지만 Retrieval 후보 정보로 사용할 수 있다.
- `get_gmail_attachment(message_id, attachment_id)`는 사용자 다운로드 또는 결정적 파일 전달 요청에서만 실행한다.
- 첨부파일 bytes는 Retrieval Cache·SourceSegment·EvidenceDraft·ContextBundle에 넣지 않는다.
- 첨부파일 내용을 읽어 Evidence로 만드는 기능은 P0 범위 밖이다.
- Attachment Download는 LLM 재검색·추가 Retrieval Budget과 분리된 결정적 READ I/O다.
