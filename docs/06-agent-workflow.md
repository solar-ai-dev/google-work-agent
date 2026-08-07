# 06. Google Work Agent · Agent · Workflow 설계서

> **문서 기준:** `01 PRD v2.3`, `01-A v2.2`, `01-B v2.2`, `02 UI·UX v2.2`, `03 Architecture v2.5`, `04 Database v1.8`, `05 Retrieval v2.0`, `07 Interface v2.3`, Domain 상태 전이 계약 v1.3과 테스트 매트릭스 v1.3을 기준으로 한다.
>
> **상태:** Draft v5.4 · **대상:** P0 MVP
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

6개 역할과 19개 Prompt를 한 번에 구현하지 않는다. 각 수직 흐름의 Domain·Tool·Trace 계약이 통과한 후 다음 LLM Node를 추가한다.

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

초기 Prompt Template 19개:

| Agent | Purpose Key | 수량 |
|---|---|---:|
| 요청 이해 | `classify`, `clarify`, `repair` | 3 |
| API 탐색·수집 | `plan_sources`, `revise_partial`, `repair` | 3 |
| Context Retriever | `select_evidence`, `assess_sufficiency`, `repair` | 3 |
| 업무 분석 | `analyze`, `reassess`, `repair` | 3 |
| 해결책·계획 | `answer_only`, `draft_plan`, `revise_plan`, `repair` | 4 |
| 계획 검토 | `inspect`, `recheck`, `repair` | 3 |

## 7.1 Prompt 구현 우선순위

- **Tier A · 우선 완성·실험:** `request_understanding.classify`, `acquisition.plan_sources`, `context.select_evidence`, `planning.draft_plan`, `review.inspect`
- **Tier B · Baseline 작성:** `context.assess_sufficiency`, `analysis.analyze`, `planning.answer_only`, `planning.revise_plan`, `review.recheck`
- **Tier C · 실패 사례 후 작성:** 모든 `repair`, `reassess`, `revise_partial`

19개 Prompt Manifest와 ID 예약은 유지하지만, Tier C Prompt는 실제 실패 유형과 Trace가 확보되기 전 과도하게 튜닝하지 않는다.

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
plan_draft: ActionPlanDraftV1 | None
plan_review: PlanReviewResultV1 | None
execution_summary: ExecutionSummaryV1 | None
verification_summary: VerificationSummaryV1 | None
user_interrupt: UserInterruptV1 | None
retry_budget: RunBudgetV1
prompt_context: PromptContextV1
trace_context: TraceContextV1
```

## 16. Node Registry

| node_id | agent_role | phase | purpose | output | 주요 결과 | 최대 호출 |
|---|---|---|---|---|---|---:|
| `request_understanding.classify` | request_understanding | REQUEST_ANALYSIS | classify | RequestIntentV1 | COMPLETE·NEEDS_CONFIRMATION·INVALID | 1 |
| `request_understanding.clarify` | request_understanding | WAITING_CONFIRMATION | clarify | ClarificationQuestionV1 | QUESTION_READY | 1 |
| `request_understanding.repair` | request_understanding | REQUEST_ANALYSIS | repair | RequestIntentV1 | COMPLETE·INVALID | 1 |
| `acquisition.plan_sources` | api_discovery_acquisition | SOURCE_PLANNING | plan_sources | SourceFetchPlanV1[] | PLAN_READY·NO_FETCH_NEEDED·CONFIRM·BLOCKED | 1 |
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

## 17. Request Understanding Runtime 계약

현재 구현의 입력 경계는 `src/google_work_agent/ports/workflow_runtime.py`의
`WorkflowStartRequest`다. Request Understanding Node는 별도
`RequestUnderstandingInput` DTO를 만들지 않고 다음 값을 그대로 prompt input으로 투영한다.

```text
run_id
conversation_id
workflow_key
entry_mode
requested_mode
request_text
selected_resource_ids
correlation.request_id
correlation.command_id
correlation.api_contract_version
```

`selected_resource_ids`는 이미 Runtime 입력 계약에 존재하므로 `RequestIntentV1`에
불투명하게 복제하지 않는다. Initialize 단계는 선택 Resource ID를 Graph State의
`prompt_context` 또는 Run-local cache handle로 보존하고, Acquisition·Context 단계가
해당 runtime context를 함께 사용한다. Request Understanding은 선택 ID의 의미를
추론할 수는 있지만 Google 조회나 ID 생성을 수행하지 않는다.

LLM 경계의 Source of Truth는 `src/google_work_agent/application/llm.py`의
`LLMRuntimeService.invoke_structured(...)`와 `src/google_work_agent/ports/llm.py`의
`PromptReference`, `OutputSchemaDefinition`, `StructuredLLMResult`다. Request
Understanding 구현은 새 LLM Port를 만들지 않는다.

참고 원칙:

- OpenAI Structured Outputs는 JSON Schema로 출력 구조를 제한하지만 값의 의미 오류까지
  제거하지는 않는다. 따라서 Schema Validation 뒤에 일반 코드의 semantic validation이
  필요하다. [OpenAI Structured Outputs, 2024](https://openai.com/index/introducing-structured-outputs-in-the-api/)
- Routing workflow는 첫 단계에서 intent·task type을 분류하고 downstream workflow로
  위임하는 데 적합하다. [AWS Prescriptive Guidance - Workflow for routing](https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-patterns/workflow-for-routing.html)
- 장기 실행 Agent는 checkpoint, interrupt/resume, idempotent side effect 경계가 필요하다.
  [LangChain - production agent runtime](https://www.langchain.com/blog/runtime-behind-production-deep-agents)

## 18. RequestIntentV1 Schema

`RequestIntentV1`은 FN-101의 목표·완료 조건·기간·사람·Source·제약·모호성을
실행 가능한 최소 semantic 구조로 보존한다. Google Query, Page Token, MCP Arguments,
Resource ID 생성은 Acquisition·Query Builder 책임이다.

```yaml
request_intent:
  schema_version: 1
  goal:
    summary: string
    user_visible_objective: string
  completion_criteria:
    - string
  semantic_constraints:
    topics:
      - text: string
        source_text: string
    people:
      - mention: string
        role_hint: string | null
        source_text: string
    time:
      - mention: string
        granularity_hint: DATE | DATETIME | RANGE | RELATIVE | UNKNOWN
        source_text: string
    sources:
      - source: GMAIL | TASKS | CALENDAR | UNKNOWN
        mention: string
        confidence: HIGH | MEDIUM | LOW
    status_or_state:
      - mention: string
        source_text: string
    negative_constraints:
      - string
    policy_or_safety_constraints:
      - string
  ambiguity:
    is_ambiguous: boolean
    items:
      - field_path: string
        reason_code: string
        user_question: string
  unsupported_scope:
    is_unsupported: boolean
    reason_code: string | null
    explanation: string | null
```

규칙:

- `schema_version`은 정수 `1`이다.
- `goal.summary`는 내부 요약이고, `goal.user_visible_objective`는 사용자에게 되돌려도
  되는 목표 문장이다.
- `time`은 semantic time constraint만 보존한다. 실제 Gmail·Calendar·Tasks query date
  range 변환은 Acquisition·Query Builder가 수행한다.
- `people`은 사용자가 표현한 semantic mention을 보존한다. Google contact, attendee,
  sender, assignee 후보 검색은 이후 단계 책임이다.
- `sources`는 명시 또는 강한 암시만 담는다. Source를 확정할 수 없으면
  `UNKNOWN` 또는 낮은 confidence를 사용하고, 실제 Source 선택은 downstream validator가
  결정한다.
- `selected_resource_ids`와 `entry_mode`는 Runtime 입력·Graph context의 계약이며
  `RequestIntentV1`에 중복 저장하지 않는다.

## 19. 모호성 책임 경계

Request Understanding이 처리하는 모호성은 사용자 문장 자체의 정보 부족이다.

```text
예: "그 사람이랑 이야기했던 일정 정리해줘"
문장 안에 "그 사람"을 식별할 단서가 없음
→ NEEDS_CONFIRMATION 가능
```

Google 조회 결과에서 후보가 여러 개 발견되는 모호성은 Request Understanding 책임이
아니다.

```text
예: 사용자는 "민수"라고 명확히 말했지만 Google Resource 검색 결과 민수가 여러 명
→ Acquisition/Retrieval 단계에서 후보 ambiguity 처리
```

Request Understanding은 다음을 하지 않는다.

- Google/MCP 조회
- Google Resource ID 생성
- 검색 후보 사전 추측
- 사용자 범위를 넘어선 자동 scope 확장

명령이 clear, ambiguous, infeasible로 나뉠 수 있음을 명시적으로 모델링하는 연구는
과도한 실행을 막기 위한 보조 근거다. 이 프로젝트에서는 해당 원칙을 Google 조회 전
semantic boundary에만 적용한다. [CLARA, IEEE RA-L 2024](https://clararobot.github.io/)

## 20. Request Understanding Node Output

현재 코드의 결과 Enum은 `RequestUnderstandingResult`를 그대로 사용한다.

```yaml
request_understanding_output:
  schema_version: 1
  result: COMPLETE | NEEDS_CONFIRMATION | INVALID
  request_intent: RequestIntentV1 | null
  clarification: ClarificationQuestionV1 | null
  failure: RequestUnderstandingFailureV1 | null
  validator_codes:
    - string
```

LLM은 `RequestIntentV1` 후보를 만든다. 일반 코드는 Schema Validation과 Semantic
Validation을 수행한 뒤 `COMPLETE`, `NEEDS_CONFIRMATION`, `INVALID`를 결정한다.
LLM이 최종 Workflow result를 단독 결정하지 않는다.

### 20.1 COMPLETE

```text
result = COMPLETE
request_intent != null
clarification = null
failure = null
ambiguity.is_ambiguous = false
unsupported_scope.is_unsupported = false
```

COMPLETE는 다음 단계가 Acquisition 또는 Answer-only planning으로 진행할 수 있는
semantic 조건이 갖춰졌다는 뜻이다. Source query 가능성이나 Google 후보 존재 여부를
보장하지 않는다.

### 20.2 NEEDS_CONFIRMATION

```yaml
clarification:
  schema_version: 1
  question: string
  affected_field_paths:
    - string
  reason_code: string
  known_context_summary: string
```

`NEEDS_CONFIRMATION`은 사용자에게 무엇을 확인해야 하는지와 `RequestIntentV1`의 어느
부분이 모호한지를 전달하기 위한 상태다. UI 선택지 전체, Google 후보 목록, Interrupt
Resume 구현 방식은 이 계약에 포함하지 않는다.

### 20.3 INVALID

```yaml
failure:
  schema_version: 1
  reason_code: string
  user_safe_message: string
  diagnostic: string
```

`INVALID`는 valid structured payload를 얻은 뒤에도 사용자 요청 자체가 제품 범위에서
처리 불가능할 때 사용한다. `request_intent`는 `null`이며 `clarification`도 `null`이다.
사용자가 정보를 더 주면 처리 가능한 경우는 `INVALID`가 아니라 `NEEDS_CONFIRMATION`이다.

## 21. Schema Repair와 INVALID의 차이

Schema JSON 오류, required field 누락, type 오류, enum 오류는 `INVALID`가 아니다.
이들은 `LLMRuntimeService.invoke_structured(...)` 내부의 schema validation 실패이며
`RuntimePolicy.structured_output_repair_budget = 1`에 따라 최대 1회 repair 대상이다.

Repair 후에도 schema가 맞지 않으면 LLM invocation failure로 처리한다. `INVALID`는
schema가 맞는 payload를 일반 코드가 semantic validation한 뒤 결정하는 Request
Understanding 결과다.

## 22. Typed Handoff 방식

첫 구현에서는 별도 Handoff DTO를 만들지 않는다. LangGraph Node는 다음 partial state
update만 반환한다.

```yaml
request_intent: RequestIntentV1 | null
user_interrupt: ClarificationQuestionV1 | RequestUnderstandingFailureV1 | null
workflow_phase: REQUEST_ANALYSIS | WAITING_CONFIRMATION | FINALIZE
trace_context:
  request_understanding_result: COMPLETE | NEEDS_CONFIRMATION | INVALID
  validator_codes: list[string]
```

금지 invariant:

- `COMPLETE`에서 `request_intent`가 `null`이면 안 된다.
- `COMPLETE`에서 `user_interrupt`가 있으면 안 된다.
- `NEEDS_CONFIRMATION`에서 `clarification` 없이 진행하면 안 된다.
- `INVALID`에서 downstream Acquisition·Context·Write 경로로 진행하면 안 된다.
- Schema Repair 실패를 `INVALID`로 위장하면 안 된다.

## 23. Request Understanding Prompt 사용 계약

- `request_understanding.classify`: 첫 Request Understanding 구현에 필요한 유일한
  runtime prompt artifact다. `WorkflowStartRequest`에서 투영한 입력으로
  `RequestIntentV1` 후보를 생성한다.
- `request_understanding.clarify`: 현재 manifest에 예약되어 있다. classify 결과와
  deterministic validator만으로 사용자 질문을 만들 수 없을 때 이후 단계에서 작성한다.
- `request_understanding.repair`: semantic retry가 아니라 structured output schema repair
  전용이다. 현재 `LLMRuntimeService`의 repair budget은 1회이며, prompt artifact는 실제
  failure trace가 생긴 뒤 작성한다.

`prompts/agent/request_understanding/classify.md`와
`prompts/agent/manifest.yaml`의 `request_understanding.classify`가 현재 존재하는
Prompt artifact다. `clarify`, `repair`는 예약 상태이므로 첫 구현 blocker가 아니다.

---

## 24. 2026-08-07 Agent Failure·Prompt·Budget 계약 보강

이 절은 `15. Agent Capability · Failure · Prompt 공통 계약 v0.2`를 적용한다.

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

Runtime Prompt 선택 Key는 `src/google_work_agent/application/workflows/contracts.py`의
`PromptSelectionKey` 필드를 Source of Truth로 삼는다.

```text
agent_role + subgraph_name + node_name + node_state + purpose
+ input_schema_version + output_schema_version
```

`failure_reason_code`는 Prompt Registry·Manifest가 후보 Prompt를 고르는 metadata로 사용할
수 있지만 Runtime `PromptSelectionKey` 또는 `PromptReference` 필드로 확정하지 않는다.
Failure-specific Prompt가 필요하면 Registry가 다른 `prompt_id` 또는 `prompt_version`을
선택하고, LLM 호출에는 현재 Runtime `PromptReference` 필드만 전달한다.

Prompt는 Base Role Contract, Node Purpose, Failure-specific Block, Allowed Change Scope, Output Schema를 조립한다. Node DEV, Node HOLDOUT, Safety Gate, Prompt Manifest 승인을 통과한 Prompt만 `RUNTIME_ACTIVE`가 된다.
