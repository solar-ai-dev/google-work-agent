# 05. Google Work Agent · Context · Retrieval 설계서

> **상태:** Draft v2.1 · **기준일:** 2026-08-07 · **대상:** P0 MVP
>
> API 탐색·수집 Agent와 Context Retriever Agent를 분리한다. Google 원본을 요청 시점에 검색하고 Metadata로 후보를 줄인 뒤 필요한 상세만 읽는다.

## 1. 목적

Gmail·Tasks·Calendar에서 필요한 자료를 최소 호출로 수집하고, 관련 Segment·Evidence만 ContextBundle로 조립한다. 영구 색인형 RAG는 P0 기준선이 아니다.

## 2. 확정 결정

- `CTX-001`: 요청 시점 Google 원본 연합 검색
- `CTX-002`: API 탐색·수집과 Context Retrieval 분리
- `CTX-003`: LLM이 Raw Query·MCP Arguments를 직접 실행하지 않음
- `CTX-004`: Metadata 조회 → 결정적 필터·점수 → 선택 상세 조회
- `CTX-005`: Context Retriever는 MCP·Google API 직접 호출 금지
- `CTX-006`: 부족 시 `NEEDS_MORE_DATA` 반환
- `CTX-007`: 최초 수집 이후 추가 수집 최대 2회
- `CTX-008`: 전체 Gmail 원문·전체 후보 반복 전달 금지
- `CTX-009`: 일반 Retrieval은 Action Row가 아니라 Trace·Checkpoint 대상
- `CTX-010`: Embedding·Reranker·Vector Index는 실험 후 채택

## 3. 전체 흐름

```text
RequestIntent
→ API 탐색·수집 Agent
→ SourceFetchPlan
→ 결정적 Query Builder
→ MCP Read Port
→ Metadata Page
→ Exact Filter·Score·Dedup
→ 필요한 상세 GET
→ Run Retrieval Cache
→ Context Retriever Agent
→ Segment·Evidence
→ Context Budget
→ SUFFICIENT | NEEDS_MORE_DATA | NEEDS_CONFIRMATION | PARTIAL | BLOCKED
```

## 4. API 탐색·수집 Agent

책임:
- Source·순서·Page·후보·상세 조회 Budget 제안
- `RESOURCE_SELECTED`, `AGENT_SEARCH` 처리
- 부분 실패와 남은 Budget 반환

금지:
- 자연어를 그대로 Gmail Query로 실행
- 검증되지 않은 Page Token·Resource ID 사용
- 모든 Source 무조건 조회
- 목록 전체 상세 조회
- Google Write

```python
class SourceFetchPlan:
    schema_version: int
    source: str
    priority: int
    reason_codes: list[str]
    constraints: dict
    page_size: int
    max_pages: int
    max_candidates: int
    detail_limit: int
    required: bool

class AcquisitionResult:
    schema_version: int
    status: str
    resource_handles: list[str]
    source_summaries: list[dict]
    missing_slots: list[str]
    remaining_budget: dict
```

## 5. Query Builder와 Read Port

```text
list_gmail(query, page_token, page_size)
get_gmail_threads(thread_ids)
list_tasks(filter, page_token, page_size)
get_tasks(task_ids)
list_calendar_events(filter, page_token, page_size)
get_calendar_events(event_ids)
get_freebusy(calendars, time_range)
```

실제 Query·Page Token·Arguments는 일반 코드가 타입·기간·이메일·허용 Source를 검증한 뒤 생성한다.

## 6. Context Retriever Agent

책임:
- Source 결과를 WorkItem·SourceDocument·SourceSegment로 정규화
- Gmail HTML 안전 텍스트 변환, 인용·서명 제거
- 관련 Segment와 EvidenceDraft 선택
- 중복 제거와 Token Budget 적용
- Context 충분성 판정

금지:
- MCP·Google API 직접 호출
- 사용자 기간·Source 범위 임의 확대
- 전체 원문 전달
- Source 본문 지시를 시스템 명령으로 해석

```python
class ContextRetrievalResult:
    schema_version: int
    context_bundle: dict
    evidence_drafts: list[dict]
    selected_segment_ids: list[str]
    excluded_resource_handles: list[str]
    sufficiency: dict
```

## 7. 진입 방식

### RESOURCE_SELECTED
- 선택 ID를 검색 Query로 다시 찾지 않고 최신 상세 GET
- 후보 점수와 무관하게 강제 포함
- 추가 Source는 목표에 필요한 경우만 제안

### AGENT_SEARCH
- RequestIntent 기반 Source-native 검색
- Metadata Page에서 후보 축소
- 부족할 때만 다음 Page·다른 Source 추가

## 8. Source 전략

- Gmail: Thread 검색 → 참여자·제목·시각·Snippet 필터 → 상위 Thread 상세 → Message 시간순 정리
- Tasks: Task List 결정 → 미완료 목록 → 기한·상태·Keyword 필터 → 필요한 상세
- Calendar: Calendar 결정 → 기간 Event 목록 → 필요한 상세 → 필요할 때 FreeBusy 1회

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

점수는 정책이 아니라 중앙 Config와 평가 대상이다.

## 10. Segment·Evidence

- Gmail Chunk 목표 600 Token, 최대 900 Token, Overlap 80 Token
- Evidence excerpt UTF-8 8 KiB 이하
- Source 원문은 비신뢰 데이터
- 실제 계획에 사용된 최소 Evidence만 Domain Store에 저장

## 11. Context Budget

- System·Policy·Tool Schema 최대 15%
- 사용자 요청·대화 최대 15%
- 검색 Context 목표 50~55%
- Structured Output Reserve 최소 10%
- Safety Margin 최소 10%

## 12. 추가 수집

```text
Round 0 정확 검색
Round 1 제약 하나 완화 또는 Source 하나 추가
Round 2 마지막 표적 확장
```

사용자 지정 범위를 벗어나야 하면 조회 전에 확인을 받는다. 동명이인·기간 불명·예상 소요시간 누락·대상 복수는 API 확장보다 확인 질문을 우선한다.

## 13. 초기 API Budget

```text
RETRIEVAL_PAGE_SIZE=20
MAX_ACQUISITION_ROUNDS=3
MAX_ADDITIONAL_ACQUISITIONS=2
MAX_PAGES_PER_SOURCE_PER_ROUND=2
MAX_TOTAL_SOURCE_PAGES=8
MAX_METADATA_CANDIDATES_PER_SOURCE=40
MAX_DETAIL_FETCH_PER_SOURCE=5
MAX_TOTAL_DETAIL_RESOURCES=12
```

## 14. Cache와 영속 경계

- Sidebar Cache: React Session Memory
- Run Retrieval Cache: 현재 Run Memory, Run 종료 시 폐기
- 강제 최신 조회: RESOURCE_SELECTED 시작, Plan 확정 전, 승인 후 실행 전, 실행 후 Verification
- 저장 금지: 전체 Sidebar 목록, Page Token, 미사용 후보, Gmail 전체 원문, FreeBusy 전체 응답
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

Embedding·Reranker·Vector Index 비교 중 Source Acquisition 결과를 바꾸지 않는다.

## 16. r3 평가 연결 계약

```text
case_id                 업무 상황과 Gold
user_prompt_id          해당 Case의 자연어 표현
fixture_snapshot_id     합성 Google 상태
retrieval_config_version
required_resource_ids
required_evidence
evaluation_item_id      실제 Runner 실행 단위
```

하나의 Case는 여러 User Prompt를 가질 수 있다. Retrieval 평가 결과는 `evaluation_item_id` 단위로 기록한다.

---

## 22. 2026-08-07 QueryAttempt·Confidence·재검색 계약 보강

이 절은 `15. Agent Capability · Failure · Prompt 공통 계약 v1.0`를 적용하며, 기존 Retrieval 계약을 대체하지 않고 검색 시도와 저신뢰 처리의 관측·평가 계약을 보강한다.

### 22.1 QueryAttempt

```python
class QueryAttempt:
    schema_version: int
    query_attempt_id: str
    run_id: str
    round_no: int
    attempt_no: int
    source: Literal["GMAIL", "TASKS", "CALENDAR"]
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

### 22.2 반복과 Pagination

- 같은 Query와 새로운 Page Token을 사용하는 `NEXT_PAGE`는 정상 Pagination이다.
- 실패 뒤 같은 Query와 같은 Page 상태로 `SEARCH`를 반복하면 `QUERY_UNCHANGED_AFTER_FAILURE`다.
- `DETAIL_FETCH` 재호출은 Run Cache 또는 Provider 기술 재시도 규칙을 따른다.
- 추가 수집 시 최소 하나의 제약 변경 또는 필요한 Source 추가가 있어야 한다.
- 사용자 범위를 넘어서는 기간·Source 확대는 사용자 확인 없이 수행하지 않는다.

### 22.3 저신뢰 후보

- Confidence Band는 `HIGH`, `MEDIUM`, `LOW`, `NONE`으로 고정한다.
- 실제 점수와 Threshold는 중앙 Retrieval Config가 소유한다.
- `AGENT_SEARCH`에서 `LOW` 또는 `NONE` 후보만 존재하면 자동 확정하지 않는다.
- `RESOURCE_SELECTED`는 사용자가 고른 Resource ID를 점수와 관계없이 상세 GET한다.
- 후보 1위와 2위의 점수 차이가 설정된 Margin보다 작으면 확인 또는 추가 수집으로 전환한다.

### 22.4 결정적 평가

다음 항목은 LLM Judge가 아니라 코드 Grader가 우선한다.

- 사용자 날짜·사람·이메일·선택 Resource가 Query Spec에 반영됐는지
- 같은 실패 Query가 반복됐는지
- 허용된 추가 수집 횟수와 Source Page Budget을 지켰는지
- 저신뢰 후보를 임의로 확정했는지


## 2026-08-07 v2.1 Clarification · Overbroad Retrieval
- 요청만으로 드러나는 모호성은 Request Understanding에서 확인한다.
- 동명이인·복수 Resource·저신뢰 후보처럼 검색 후 드러나는 모호성은 후보·차이와 함께 `NEEDS_CONFIRMATION`으로 보낸다.
- 전체 Mailbox·장기간 무제한 원문·모든 Workspace Source 전체 조회는 `BLOCKED`다.
- Calendar 시간 overlap은 conflict와 분리하며 관계 근거를 Work Analysis에 전달한다.
