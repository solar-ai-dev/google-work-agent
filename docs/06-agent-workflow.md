# 06. Google Work Agent · Agent · Workflow 설계서

> **문서 기준:** `01 PRD v2.4`, `01-A v2.3`, `01-B v2.3`, `02 UI·UX v2.3`, `03 Architecture v2.6`, `04 Database v1.9`, `05 Retrieval v2.1`, `07 Interface v2.4`, Domain 상태 전이 계약 v1.3과 테스트 매트릭스 v1.3을 기준으로 한다.
>
> **상태:** Draft v5.5 · **DB Schema:** v1.3 · **대상:** P0 MVP
>
> 결정적 Supervisor + 최대 6개 전문 LLM 역할 Node Baseline + 결정적 실행·검증 Engine을 사용한다. Agent 중간 상태는 Checkpoint, 승인·실행·검증 사실은 SQLite Domain Store가 소유한다.

## 1. 확정 사항

- 요청 이해, API 탐색·수집, Context Retrieval, 업무 분석, 해결책·계획, 계획 검토의 6개 역할을 초기 Baseline으로 정의
- 6개 역할의 분리 자체는 제품 불변조건이 아니며 Graph Profile 비교 후 Release Graph 확정
- Supervisor는 결정적 Router
- Handoff는 Versioned Typed State와 Resource·Evidence·Segment ID
- Retrieval API 호출은 Action Row를 만들지 않음
- 승인 이후 LLM이 Tool·Arguments·대상을 변경하지 않음
- Prompt는 Agent별 단일 문자열이 아니라 Node·상태·목적별 PromptRef

## 1.1 Graph Profile

| Profile | 구조 | 목적 |
|---|---|---|
| `SINGLE_BASELINE` | 하나의 통합 LLM Workflow가 요청 이해·Source·Evidence·분석·계획을 생성하고 결정적 Validator가 검토 | 최소 호출 Baseline |
| `THREE_STAGE` | 1. 요청 이해·Source 계획 2. Evidence·분석·계획 3. 계획 검토 | 역할 분리와 비용의 균형 후보 |
| `SIX_ROLE_BASELINE` | 요청 이해, API 탐색·수집, Context Retrieval, 업무 분석, 해결책·계획, 계획 검토 | 현행 최대 분리 Baseline |

공통 불변조건:

- Domain·Policy·승인·Claim·실행·검증·복구 코드는 모든 Profile에서 동일하다.
- Model·Policy·Tool Schema·Fixture·Retrieval 입력을 고정한 상태에서 Graph만 비교한다.
- Agent 제거·Node Skip 실험에서 새로운 휴리스틱 비즈니스 로직을 추가하지 않는다.
- 제거된 Node의 입력은 기존 공통 변환 함수, 이전 Node Output 또는 상한 분석용 Gold 입력으로 연결한다.
- Gold 입력을 사용하는 Oracle 실험은 제품 후보가 아니라 성능 상한 분석으로만 기록한다.

## 1.2 구현 순서

```text
1. Domain 상태 전이·SQLite·Command Receipt
2. Fake Google Gateway·Fixture
3. Answer-only 단일 Workflow
4. READ-only Workflow
5. 단일 WRITE 승인·실행·GET 검증
6. UNKNOWN_RESULT 복구
7. Request Understanding
8. Acquisition·Context Retrieval
9. Analysis·Planning
10. Plan Review
11. THREE_STAGE Profile
12. SIX_ROLE_BASELINE Profile
```

6개 역할과 20개 Prompt를 한 번에 구현하지 않는다. 각 수직 흐름의 Domain·Tool·Trace 계약이 통과한 후 다음 LLM Node를 추가한다.

## 2. 책임

| 구성 | 책임 | 금지 |
|---|---|---|
| Supervisor | Phase·Result·Budget Routing | SQL·Write·계획 내용 생성 |
| 요청 이해 | 목표·완료 조건·제약·모호성 | Google 조회·Action 생성 |
| API 탐색·수집 | 최소 호출 전략·Source·Budget | Raw Query 실행·Write |
| Context Retriever | Segment·Evidence·충분성 | MCP·Google 직접 호출 |
| 업무 분석 | 관계·누락·중복 후보·일정 위험 | 정책 최종 판정 |
| 해결책·계획 | Answer 또는 Action DAG 초안 | 승인·실행 |
| 계획 검토 | 목표·근거·과잉·모순 검토 | 실행 허용 최종 판정 |
| 실행 Engine | 승인 인자 Claim·MCP Write | LLM 재계획 |
| 검증·복구 | Google GET·Comparator·Recovery | LLM 성공 판정 |

## 3. Graph State

```python
class MultiAgentGraphState:
    schema_version: int
    run_id: str
    conversation_id: str
    thread_id: str
    workflow_phase: str
    request_intent: dict | None
    source_fetch_plans: list[dict]
    acquisition_result: dict | None
    context_result: dict | None
    analysis_result: dict | None
    answer_draft: dict | None
    plan_draft: dict | None
    plan_review: dict | None
    approved_plan_id: str | None
    execution_summary: dict | None
    verification_summary: dict | None
    user_interrupt: dict | None
    retry_budget: dict
    prompt_context: dict
    trace_context: dict
```

대용량 원문은 State에 넣지 않고 Run Cache Handle을 사용한다.

## 4. Workflow Phase

```text
INITIALIZE
REQUEST_ANALYSIS
WAITING_CONFIRMATION
SOURCE_PLANNING
API_ACQUISITION
CONTEXT_RETRIEVAL
CONTEXT_EVALUATION
WORK_ANALYSIS
SOLUTION_PLANNING
PLAN_REVIEW
DOMAIN_VALIDATION
WAITING_APPROVAL
PREFLIGHT
ACTION_EXECUTION
VERIFICATION
RESPONSE_SYNTHESIS
RECOVERY
FINALIZE
```

Run Status는 CREATED, ANALYZING, RETRIEVING, WAITING_CONFIRMATION, PLANNING, WAITING_APPROVAL, EXECUTING, VERIFYING, CANCEL_REQUESTED, CANCELLED, REAUTH_REQUIRED, RECOVERY_REQUIRED, COMPLETED, BLOCKED, FAILED를 사용한다.

## 5. 상위 흐름

```text
Initialize
→ 요청 이해
→ 확인 필요 시 Interrupt
→ API Source 계획·수집
→ Context Retrieval·충분성
→ 업무 분석
→ 해결책·계획
→ 계획 검토
→ Domain Validation
→ Answer-only | READ-only | WAITING_APPROVAL
→ Preflight
→ 실행
→ GET Verification
→ Recovery 또는 Finalize
```

## 6. Node 결과

- 요청 이해: COMPLETE | NEEDS_CONFIRMATION | INVALID
- API 계획: PLAN_READY | NO_FETCH_NEEDED | NEEDS_CONFIRMATION | BLOCKED
- API 수집: COMPLETE | PARTIAL | AUTH_REQUIRED | RATE_LIMITED | BUDGET_EXHAUSTED | FAILED
- Context: SUFFICIENT | NEEDS_MORE_DATA | NEEDS_CONFIRMATION | PARTIAL | BLOCKED
- 분석: COMPLETE | NEEDS_MORE_DATA | NEEDS_CONFIRMATION | BLOCKED
- 계획: ANSWER_ONLY | PLAN_READY | NEEDS_CONFIRMATION | BLOCKED
- 검토: PASS | REVISE | RETRIEVE_MORE | CONFIRM | BLOCK
- Domain: ALLOW_READ | REQUIRE_APPROVAL | BLOCK

`ContextRetrievalResultV1.status == NEEDS_MORE_DATA`,
`WorkAnalysisResultV1.status == NEEDS_MORE_DATA`,
and `PlanReviewResultV1.status == RETRIEVE_MORE`
carry `additional_acquisition_request: AdditionalAcquisitionRequestV1 | None`.
Supervisor uses that structured handoff to route the run back to `SOURCE_PLANNING`
without inferring source choice from free text.

## 7. Prompt Registry

Prompt 선택 Key:

```text
agent_role
subgraph_name
node_name
node_state
purpose
input_schema_version
output_schema_version
```

PromptRef:

```text
prompt_bundle_version
prompt_id
prompt_version
content_hash
agent_role
subgraph_name
node_name
node_state
purpose
input_schema_version
output_schema_version
```

규칙:
- Supervisor는 다음 Node를 결정적으로 Routing하고 Prompt 원문을 읽거나 선택하지 않는다.
- 선택된 Agent·Application Node가 Prompt Registry에서 PromptRef를 확정한 뒤 LLM Adapter를 호출한다.
- LLM Router와 Model은 Prompt를 선택하지 않는다.
- Repair·Revision·Sufficiency는 별도 Prompt ID를 사용한다.
- Prompt 원문은 Graph State·Trace·Audit에 저장하지 않음
- 실행·검증·승인·정책 판정에는 LLM Prompt를 사용하지 않음

초기 Prompt Template 20개:

| Agent | Purpose Key | 수량 |
|---|---|---:|
| 요청 이해 | `classify`, `clarify`, `repair` | 3 |
| API 탐색·수집 | `plan_sources`, `revise_partial`, `repair` | 3 |
| Context Retriever | `select_evidence`, `assess_sufficiency`, `repair` | 3 |
| 업무 분석 | `analyze`, `reassess`, `repair` | 3 |
| 해결책·계획 | `answer_only`, `draft_plan`, `revise_plan`, `repair` | 4 |
| 계획 검토 | `inspect`, `recheck`, `repair` | 3 |

## 7.1 Prompt 구현 우선순위

`solution_planning` Prompt set은 `answer_only`, `draft_plan`, `revise_answer`, `revise_plan`, `repair` 5개를 기준으로 한다.

- **Tier A · 우선 완성·실험:** `request_understanding.classify`, `acquisition.plan_sources`, `context.select_evidence`, `planning.draft_plan`, `review.inspect`
- **Tier B · Baseline 작성:** `context.assess_sufficiency`, `analysis.analyze`, `planning.answer_only`, `planning.revise_answer`, `planning.revise_plan`, `review.recheck`
- **Tier C · 실패 사례 후 작성:** 모든 `repair`, `reassess`, `revise_partial`

20개 Prompt Manifest와 ID 예약은 유지하지만, Tier C Prompt는 실제 실패 유형과 Trace가 확보되기 전 과도하게 튜닝하지 않는다.

## 8. Budget

```text
Structured Output Repair: 호출당 최대 1회
추가 수집: 최대 2회
계획 Revision: 최대 2회
기본 LLM 호출: Run당 최대 8회
```

하드 상한 초과 시 Partial·Confirmation·Blocked 중 하나로 종료한다.

## 9. Answer-only

```text
ANALYZING | RETRIEVING | PLANNING
→ complete_answer_only_run
→ COMPLETED
```

Plan·Action 없이 Assistant Message·Trace·Run Terminal을 원자 저장한다.

## 10. READ-only

```text
publish_read_only_plan
→ claim_read_action
→ complete_read_action
→ finalize_read_action
```

READ Action은 Approval·ExecutionAttempt·Verification Row를 만들지 않는다.

## 11. WRITE

```text
PROPOSED | MODIFIED
→ approve_action
→ APPROVED
→ claim_action_execution
→ EXECUTING
→ MCP Write
→ EXECUTED | FAILED | UNKNOWN_RESULT
→ GET Verification
→ VERIFIED | MISMATCH
```

Claim 전 Write 금지. 승인 이후 인자를 LLM이 재생성하지 않는다.

## 12. Retry와 Recovery

FAILED:
```text
FAILED → prepare_write_retry → MODIFIED → 새 승인 → 새 Attempt
```

UNKNOWN_RESULT:
```text
CREATE → Recovery Fingerprint Search
UPDATE → Target GET
```

UNKNOWN_RESULT에서 새 Attempt·Write를 금지한다.

## 13. Interrupt

- WAITING_CONFIRMATION
- WAITING_APPROVAL
- REAUTH_REQUIRED
- RECOVERY_REQUIRED

Interrupt 전에 Checkpoint를 저장하고 같은 Thread로 재개한다.

## 14. Runtime

- API_ONLY: API Provider만
- LOCAL_CAPABLE: API Provider + Ollama Adapter
- AUTO: Local 기술 실패 시 외부 전송 동의가 있을 때 API Fallback 최대 1회
- LOCAL_GPU: 자동 API 전환 금지
- 실행·검증은 LLM 미사용


## 15. Typed State 계약

Graph State의 주요 필드는 범용 `dict`가 아니라 Versioned Schema를 사용한다.

```python
request_intent: RequestIntentV1 | None
source_fetch_plans: list[SourceFetchPlanV1]
acquisition_result: AcquisitionResultV1 | None
evidence_selection_result: EvidenceSelectionResultV1 | None
sufficiency_result: SufficiencyResultV1 | None
analysis_result: WorkAnalysisResultV1 | None
answer_draft: AnswerDraftV1 | None
plan_draft: ActionPlanDraftV1 | None
plan_review: PlanReviewResultV1 | None
execution_summary: ExecutionSummaryV1 | None
verification_summary: VerificationSummaryV1 | None
user_interrupt: UserInterruptV1 | None
retry_budget: RunBudgetV1
prompt_context: PromptContextV1
trace_context: TraceContextV1
```

`RESOURCE_SELECTED`의 선택 Resource identity는 `RequestIntentV1`에 중복 저장하지 않는다.
Runtime 입력과 `prompt_context`는 `selected_resource_ids` 호환 필드와 함께
`SelectedResourceRefV1[]` projection을 보존한다. Stage 5는 이 projection의
`source`, `resource_type`, `resource_id`, `parent_resource_id`로만 선택 Resource 상세 GET
경로를 결정한다.

## 16. Node Registry

| node_id | agent_role | phase | purpose | output | 주요 결과 | 최대 호출 |
|---|---|---|---|---|---|---:|
| `request_understanding.classify` | request_understanding | REQUEST_ANALYSIS | classify | RequestIntentV1 | COMPLETE·NEEDS_CONFIRMATION·INVALID | 1 |
| `request_understanding.clarify` | request_understanding | WAITING_CONFIRMATION | clarify | ClarificationQuestionV1 | QUESTION_READY | 1 |
| `request_understanding.repair` | request_understanding | REQUEST_ANALYSIS | repair | RequestIntentV1 | COMPLETE·INVALID | 1 |
| `acquisition.plan_sources` | api_discovery_acquisition | SOURCE_PLANNING | plan_sources | SourceFetchPlanV1[] | PLAN_READY·NO_FETCH_NEEDED·NEEDS_CONFIRMATION·BLOCKED | 1 |
| `acquisition.revise_partial` | api_discovery_acquisition | SOURCE_PLANNING | revise_partial | SourceFetchPlanV1[] | PLAN_READY·PARTIAL·BLOCKED | 1 |
| `acquisition.repair` | api_discovery_acquisition | SOURCE_PLANNING | repair | SourceFetchPlanV1[] | PLAN_READY·BLOCKED | 1 |
| `context.select_evidence` | context_retriever | CONTEXT_RETRIEVAL | select_evidence | EvidenceSelectionResultV1 | SELECTED·PARTIAL·BLOCKED | 1 |
| `context.assess_sufficiency` | context_retriever | CONTEXT_EVALUATION | assess_sufficiency | SufficiencyResultV1 | SUFFICIENT·NEEDS_MORE_DATA·NEEDS_CONFIRMATION·PARTIAL·BLOCKED | 1 |
| `context.repair` | context_retriever | CONTEXT_EVALUATION | repair | ContextRetrievalResultV1 | SUFFICIENT·BLOCKED | 1 |
| `analysis.analyze` | work_analysis | WORK_ANALYSIS | analyze | WorkAnalysisResultV1 | COMPLETE·NEEDS_MORE_DATA·NEEDS_CONFIRMATION·BLOCKED | 1 |
| `analysis.reassess` | work_analysis | WORK_ANALYSIS | reassess | WorkAnalysisResultV1 | COMPLETE·BLOCKED | 1 |
| `analysis.repair` | work_analysis | WORK_ANALYSIS | repair | WorkAnalysisResultV1 | COMPLETE·BLOCKED | 1 |
| `planning.answer_only` | solution_planning | SOLUTION_PLANNING | answer_only | AnswerDraftV1 | ANSWER_ONLY·NEEDS_CONFIRMATION·BLOCKED | 1 |
| `planning.draft_plan` | solution_planning | SOLUTION_PLANNING | draft_plan | ActionPlanDraftV1 | PLAN_READY·NEEDS_CONFIRMATION·BLOCKED | 1 |
| `planning.revise_plan` | solution_planning | SOLUTION_PLANNING | revise_plan | ActionPlanDraftV1 | PLAN_READY·BLOCKED | 2 |
| `planning.repair` | solution_planning | SOLUTION_PLANNING | repair | ActionPlanDraftV1 | PLAN_READY·BLOCKED | 1 |
| `review.inspect` | plan_review | PLAN_REVIEW | inspect | PlanReviewResultV1 | PASS·REVISE·RETRIEVE_MORE·CONFIRM·BLOCK | 1 |
| `review.recheck` | plan_review | PLAN_REVIEW | recheck | PlanReviewResultV1 | PASS·BLOCK | 1 |
| `review.repair` | plan_review | PLAN_REVIEW | repair | PlanReviewResultV1 | PASS·BLOCK | 1 |

- `purpose`를 Prompt Manifest·Trace의 공통 필드명으로 사용한다.
- `repair_prompt_id`는 Node Registry에서 연결한다.
- Supervisor는 Registry의 허용 Edge만 선택하고 Agent가 임의 Node를 호출하지 않는다.

---

## 24. 2026-08-07 Agent Failure·Prompt·Budget 계약 보강

이 절은 `15. Agent Capability · Failure · Prompt 공통 계약 v1.0`를 적용한다.

Answer-only review revision contract:

- `planning.answer_only`가 `ANSWER_ONLY`를 반환하면 `answer_draft`를 기록하고 `plan_draft`는 `None`으로 비운다.
- `planning.draft_plan`이 `PLAN_READY`를 반환하면 `plan_draft`를 기록하고 `answer_draft`는 `None`으로 비운다.
- Answer-only 경로에서 `review.inspect`가 `REVISE`를 반환하면 `planning.revise_answer`가 수정된 `AnswerDraftV1`을 생성하고 `answer_draft`를 교체한 뒤 `review.recheck`로 진행한다.

### 24.1 Failure Record

```python
class AgentFailureRecord:
    failure_reason_code: str
    failure_origin: str
    detected_by: str
    runtime_disposition: Literal[
        "RETRYABLE", "REDIRECT", "DETERMINISTIC", "TERMINAL", "NOT_AVAILABLE"
    ]
    experiment_disposition: str
    affected_field_paths: list[str]
```

실험 Grader가 발견한 오류와 제품 Runtime이 자체 감지 가능한 오류를 구분한다. `REVIEW_FALSE_PASS` 같은 평가 오류를 Runtime이 자동으로 감지한다고 가정하지 않는다.

### 24.2 Retry Kind

```text
SCHEMA_REPAIR
SEMANTIC_REVISION
WORKFLOW_REDIRECTION
DETERMINISTIC_RETRY
DETERMINISTIC_RECOVERY
```

- Schema Repair는 구조만 교정하며 Goal·Evidence·Action 의미를 바꾸지 않는다.
- Semantic Revision은 실패 이유와 변경 허용 범위를 입력으로 받는다.
- Workflow Redirection은 Supervisor가 다른 Node·Interrupt·종료 Edge를 선택하는 것이다.
- 401·429·5xx·Timeout은 일반 코드 Retry·Reauth 대상이며 LLM Repair 대상이 아니다.
- `UNKNOWN_RESULT`와 Verification `MISMATCH`는 LLM 재계획 대상이 아니다.

### 24.3 확정 Budget Profile

```text
SCHEMA_REPAIR_PER_NODE_CALL=1
SEMANTIC_REVISION_SAME_FAILURE=1
PLANNING_REVISION_PER_RUN=2
REVIEW_RECHECK_PER_PLANNING_REVISION=1
MAX_ADDITIONAL_ACQUISITIONS=2
NORMAL_MAX_LLM_CALLS=8
RETRIEVAL_HEAVY_MAX_LLM_CALLS=14
REVISION_HEAVY_MAX_LLM_CALLS=12
ABSOLUTE_MAX_LLM_CALLS=16
```

단일 `MAX_LLM_CALLS=8`을 모든 Route에 적용하지 않는다. Budget Profile 승격은 Supervisor의 결정적 규칙으로 수행하며 절대 상한 16회를 넘지 않는다.

### 24.4 Prompt 선택과 활성화

Prompt 선택 Key에는 선택적으로 `failure_reason_code`를 포함한다.

```text
agent_role + subgraph_name + node_name + node_state + purpose
+ failure_reason_code? + input_schema_version + output_schema_version
```

Prompt는 Base Role Contract, Node Purpose, Failure-specific Block, Allowed Change Scope, Output Schema를 조립한다. Node DEV, Node HOLDOUT, Safety Gate, Prompt Manifest 승인을 통과한 Prompt만 `RUNTIME_ACTIVE`가 된다.


## 2026-08-07 v5.5 승인형 Effect · Clarification
- Planning Effect는 `READ | CREATE | UPDATE | SEND | DELETE`다.
- SEND는 Gmail 실제 전송, DELETE는 Calendar Event 삭제, Task 완료·Calendar 참석자 변경은 UPDATE다.
- 승인 후 Tool·Effect·Arguments·Target을 LLM이 변경하지 않는다.
- `UNKNOWN_RESULT`의 SEND/DELETE 자동 재실행은 금지한다.

### 모호성 발견 시점
```text
요청 자체에서 명확 → Request Understanding → NEEDS_CONFIRMATION
검색 후 후보 복수/저신뢰 → Acquisition/Context → NEEDS_CONFIRMATION
분석 후 관계/충돌 불명 → Work Analysis → NEEDS_CONFIRMATION
```
모든 경로는 `request_understanding.clarify`에서 후보·차이·선택지를 만들고 같은 Run·Thread를 Resume한다. Request Understanding이 검색 전부터 후보 수를 안다고 가정하지 않는다.
