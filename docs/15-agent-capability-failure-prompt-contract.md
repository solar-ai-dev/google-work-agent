# Google Work Agent · Agent Capability · Failure · Prompt 공통 계약

> **상태:** Draft v0.2 · 사용자 결정 반영 · 내부 정합성 검수 대상  
> **기준일:** 2026-08-07  
> **대상:** P0 Agent 개별실험, Prompt·Repair·Revision 실험, E2E 통합실험  
> **적용 범위:** 요청 이해, API 탐색·수집, Context Retrieval, 업무 분석, 해결책·계획, 계획 검토  
> **비적용 범위:** 승인, Claim, Google Write, GET Verification, UNKNOWN_RESULT 복구, Domain 상태 전이의 최종 판정

## 0. 문서 목적

이 계약은 다음 항목을 하나의 기준으로 고정한다.

1. 각 Agent가 단독 실험에서 대응해야 하는 상황과 결과 범위
2. 실패를 분류하는 공통 `failure_reason_code`
3. 실패 유형별 Repair·Revision·Redirection·Recovery 처리 규칙
4. Prompt Registry, Node Dataset, Query Attempt, Evaluation Item이 공유할 Schema
5. Node DEV·Node HOLDOUT·E2E Dataset의 분리와 Coverage 완료 조건

이 문서는 제품 Runtime 계약을 대체하지 않는다. `05 Context·Retrieval`과 `06 Agent·Workflow`의 제품 계약을 실험 가능한 형태로 정규화하고, `11·12·13`에 필요한 실패·Prompt·Dataset 평가 계약을 제공한다.

---

## 1. 기준 문서와 우선순위

### 1.1 유지하는 확정 계약

- Supervisor는 결정적 Router다.
- LLM Agent는 Google API·MCP Write를 직접 호출하지 않는다.
- 실제 Query·Page Token·Tool Arguments는 결정적 코드가 검증·생성한다.
- Prompt는 Agent별 단일 문자열이 아니라 Node·상태·목적별 `PromptRef`로 선택한다.
- Prompt·Completion 원문은 Graph State·일반 Trace·Audit에 저장하지 않는다.
- Structured Output Schema Repair는 Node Call당 최대 1회다.
- 최초 수집 이후 Additional Acquisition은 최대 2회다.
- Planning Revision은 Run당 최대 2회다.
- 실행·검증·승인·정책 최종 판정에는 LLM Prompt를 사용하지 않는다.
- `UNKNOWN_RESULT`에서는 새 Write Attempt를 만들지 않는다.

### 1.2 충돌 우선순위

```text
PRD·정책
→ Domain 상태 전이·DB Constraint
→ Tool Registry·Interface
→ 05 Context·Retrieval·06 Agent·Workflow 제품 계약
→ 본 공통 Capability·Failure·Prompt 계약
→ 11 Observability·12 Test·13 Evaluation
→ 개별 Prompt·Dataset Artifact
```

본 계약은 상위 문서의 안전·승인·Domain 규칙을 완화할 수 없다.

---

## 2. Agent Registry

| Agent Role | 주 책임 | 주요 입력 | 주요 출력 | 금지 |
|---|---|---|---|---|
| `request_understanding` | 목표·완료 조건·제약·모호성 구조화 | 사용자 요청, Entry Mode, 선택 Resource | `RequestIntent` | Google 조회, Action 생성 |
| `acquisition` | 필요한 Source·순서·Budget·조회 전략 제안 | `RequestIntent`, Entry Mode, Retrieval Budget | `SourceFetchPlan[]` | 검증 없는 Query 실행, Write |
| `context_retriever` | Segment·Evidence 선택, 충분성 판정 | 수집 Resource Handle, 사용자 목표 | `ContextRetrievalResult` | MCP·Google API 직접 호출 |
| `work_analysis` | 관계·누락·중복·충돌·일정 위험 분석 | `ContextBundle`, Evidence | `WorkAnalysisResult` | 정책 최종 판정, 실행 |
| `planning` | Answer-only 또는 Action DAG 초안 | Intent, Evidence, Analysis | `ActionPlanDraft` 또는 Answer | 승인, 실행, Tool 직접 호출 |
| `review` | 목표 충족·Evidence·과잉 Action·모순 검토 | Plan Draft, Evidence, Policy Summary | `PlanReviewResult` | 실행 허용 최종 판정 |

---

## 3. Capability 분류 축

서로 다른 개념을 한 Enum에 섞지 않는다.

### 3.1 입력 조건 `input_condition`

```text
NORMAL
BOUNDARY
AMBIGUOUS
INSUFFICIENT
LOW_CONFIDENCE
CONFLICTING
NOISY
ADVERSARIAL
```

### 3.2 출력 실패 `output_failure_type`

```text
NONE
SCHEMA_INVALID
SEMANTIC_INVALID
```

### 3.3 복구 처분 `recovery_disposition`

```text
RETRYABLE
REDIRECT
DETERMINISTIC
TERMINAL
NOT_AVAILABLE
```

### 3.4 실패 감지 주체 `detected_by`

```text
RUNTIME_SCHEMA_VALIDATOR
RUNTIME_DOMAIN_VALIDATOR
RUNTIME_POLICY_VALIDATOR
RUNTIME_REVIEW_AGENT
RUNTIME_PROVIDER
EXPERIMENT_DETERMINISTIC_GRADER
EXPERIMENT_SEMANTIC_GRADER
HUMAN_REVIEW
```

실험 Grader가 발견한 실패를 제품 Runtime이 스스로 감지할 수 있다고 가정하지 않는다.

---

## 4. Node Result Taxonomy

기존 결과 Enum을 유지한다.

```text
Request Understanding:
  COMPLETE | NEEDS_CONFIRMATION | INVALID

Acquisition Planning:
  PLAN_READY | NO_FETCH_NEEDED | NEEDS_CONFIRMATION | BLOCKED

Acquisition Execution:
  COMPLETE | PARTIAL | AUTH_REQUIRED | RATE_LIMITED | BUDGET_EXHAUSTED | FAILED

Context Sufficiency:
  SUFFICIENT | NEEDS_MORE_DATA | NEEDS_CONFIRMATION | PARTIAL | BLOCKED

Work Analysis:
  COMPLETE | NEEDS_MORE_DATA | NEEDS_CONFIRMATION | BLOCKED

Planning:
  ANSWER_ONLY | PLAN_READY | NEEDS_CONFIRMATION | BLOCKED

Review:
  PASS | REVISE | RETRIEVE_MORE | CONFIRM | BLOCK

Domain:
  ALLOW_READ | REQUIRE_APPROVAL | BLOCK
```

`PARTIAL`은 Run Status가 아니라 결과 종류다.

```yaml
run_status: COMPLETED
result_kind: PARTIAL
```

장애로 종료되면 `FAILED` 또는 `RECOVERY_REQUIRED`와 함께 기록한다.

---

## 5. Failure Reason Record

```yaml
failure_record:
  schema_version: 1
  failure_id: string
  failure_reason_code: string
  failure_origin: LLM_OUTPUT | QUERY_PLANNING | RETRIEVAL_RESULT | PROVIDER | DOMAIN | POLICY | EXPERIMENT
  detected_by: string
  runtime_disposition: RETRYABLE | REDIRECT | DETERMINISTIC | TERMINAL | NOT_AVAILABLE
  experiment_disposition: COUNT_FAILURE | RUN_REPAIR | RUN_REVISION | REJECT_CANDIDATE | HUMAN_REVIEW
  affected_field_paths: [string]
  evidence_refs: [string]
```

예:

```yaml
failure_reason_code: REVIEW_FALSE_PASS
failure_origin: EXPERIMENT
detected_by: EXPERIMENT_DETERMINISTIC_GRADER
runtime_disposition: NOT_AVAILABLE
experiment_disposition: REJECT_CANDIDATE
```

---

## 6. Failure Reason Taxonomy

### 6.1 공통 Schema 실패

| Code | 기본 Runtime 처리 |
|---|---|
| `SCHEMA_INVALID_JSON` | `SCHEMA_REPAIR` |
| `SCHEMA_REQUIRED_FIELD_MISSING` | `SCHEMA_REPAIR` |
| `SCHEMA_INVALID_ENUM` | `SCHEMA_REPAIR` |
| `SCHEMA_WRONG_TYPE` | `SCHEMA_REPAIR` |
| `SCHEMA_UNSUPPORTED_FIELD` | `SCHEMA_REPAIR` |
| `SCHEMA_VERSION_MISMATCH` | 호출 중단 또는 Schema Repair 1회 |

### 6.2 요청 이해 실패

```text
INTENT_GOAL_MISSING
INTENT_COMPLETION_CRITERIA_MISSING
INTENT_CONSTRAINT_MISSING
INTENT_ENTRY_MODE_WRONG
INTENT_AMBIGUITY_MISSED
INTENT_OVER_CONFIRMATION
INTENT_UNSUPPORTED_SCOPE
```

### 6.3 Acquisition·Query 실패

```text
ACQ_REQUIRED_SOURCE_MISSING
ACQ_FORBIDDEN_SOURCE_INCLUDED
ACQ_NO_FETCH_MISCLASSIFIED
QUERY_USER_CONSTRAINT_MISSING
QUERY_TOO_BROAD
QUERY_TOO_NARROW
QUERY_REPEATED_WITHOUT_CHANGE
QUERY_SCOPE_EXPANSION_REQUIRES_CONFIRMATION
QUERY_LOW_CONFIDENCE_RESULTS
QUERY_NO_RESULTS
QUERY_BUDGET_EXHAUSTED
QUERY_DETAIL_FETCH_FAILED
QUERY_AUTH_REQUIRED
QUERY_RATE_LIMITED
QUERY_PROVIDER_FAILED
```

### 6.4 Context Retrieval 실패

```text
CTX_REQUIRED_EVIDENCE_MISSING
CTX_HARD_NEGATIVE_SELECTED
CTX_STALE_EVIDENCE_SELECTED
CTX_CONFLICT_NOT_REPORTED
CTX_LOW_CONFIDENCE_AUTO_SELECTED
CTX_PROMPT_INJECTION_FOLLOWED
CTX_TOKEN_BUDGET_EXCEEDED
CTX_SUFFICIENCY_WRONG
```

### 6.5 업무 분석 실패

```text
ANALYSIS_UNSUPPORTED_INFERENCE
ANALYSIS_RELATION_MISSING
ANALYSIS_CONFLICT_MISHANDLED
ANALYSIS_DUPLICATE_MISCLASSIFIED
ANALYSIS_SCHEDULE_RISK_MISCLASSIFIED
ANALYSIS_NEEDS_MORE_DATA_MISSED
```

### 6.6 Planning 실패

```text
PLAN_REQUIRED_ACTION_MISSING
PLAN_EXCESS_ACTION
PLAN_WRONG_TOOL
PLAN_WRONG_EFFECT_TYPE
PLAN_WRONG_TARGET
PLAN_REQUIRED_EVIDENCE_MISSING
PLAN_DEPENDENCY_INVALID
PLAN_ARGUMENT_CONSTRAINT_VIOLATION
PLAN_USER_SCOPE_VIOLATION
PLAN_POLICY_RISK
PLAN_ANSWER_ONLY_MISROUTED
```

### 6.7 Review 실패

```text
REVIEW_FALSE_PASS
REVIEW_FALSE_BLOCK
REVIEW_WRONG_ROUTE
REVIEW_ERROR_NOT_LOCALIZED
REVIEW_REPEATED_SAME_FAILURE
```

### 6.8 비-LLM 실패

다음은 Prompt로 복구하지 않는다.

```text
AUTH_REQUIRED
GOOGLE_READ_429
GOOGLE_READ_5XX
GOOGLE_WRITE_FAILED
GOOGLE_WRITE_UNKNOWN_RESULT
VERIFICATION_MISMATCH
VERIFICATION_TIMEOUT
SQLITE_BUSY
SQLITE_DISK_FULL
AUDIT_PERSIST_FAILED
MCP_EXIT
SSE_LOSS
LAUNCHER_SHUTDOWN_TIMEOUT
```

---

## 7. Retry Kind와 처리 주체

| Retry Kind | 정의 | LLM 사용 |
|---|---|---:|
| `NONE` | 성공·종료 또는 재시도 없는 경로 전환 | 아니오 |
| `SCHEMA_REPAIR` | 의미를 유지하며 구조만 교정 | 예 |
| `SEMANTIC_REVISION` | 실패 이유와 허용 범위 안에서 내용을 재판단 | 예 |
| `WORKFLOW_REDIRECTION` | 다른 Node·Interrupt·종료로 이동 | 아니오 |
| `DETERMINISTIC_RETRY` | 네트워크·Provider Read 기술 재시도 | 아니오 |
| `DETERMINISTIC_RECOVERY` | Reauth·Fingerprint Search·GET Verification | 아니오 |

### 7.1 금지 조합

- `AUTH_REQUIRED`에 LLM Repair·Revision을 호출하지 않는다.
- 429·5xx·Timeout에 같은 Agent Prompt를 재호출하지 않는다.
- `UNKNOWN_RESULT`에 Planning Revision 또는 Write 재호출을 하지 않는다.
- Verification `MISMATCH`에 LLM 자동 수정·Rollback을 하지 않는다.
- 사용자 범위 확대가 필요한 경우 자동 Query 확장을 하지 않는다.
- Schema Repair에서 Goal·Evidence·Action 의미를 변경하지 않는다.
- Runtime에서 차단된 Prompt Injection 결과를 Revision Prompt로 우회하지 않는다.

---

## 8. Retry Decision Contract

```yaml
retry_decision:
  schema_version: 1
  decision_id: string
  node_call_id: string
  failure_reason_codes: [string]
  retry_kind: NONE | SCHEMA_REPAIR | SEMANTIC_REVISION | WORKFLOW_REDIRECTION | DETERMINISTIC_RETRY | DETERMINISTIC_RECOVERY
  next_prompt_slot_id: string | null
  next_node_id: string | null
  attempt_no: integer
  max_attempts: integer
  changed_fields_allowed: [json_pointer]
  required_route: string | null
  stop_reason: string | null
```

### 8.1 확정 Budget

```text
Schema Repair: Node Call당 최대 1회
Semantic Revision: 동일 Node·동일 Failure Signature당 최대 1회
Planning Revision: Run당 최대 2회
Review Recheck: 각 Planning Revision 결과마다 최대 1회
Additional Acquisition: 최초 수집 이후 최대 2회
```

### 8.2 Route별 LLM 호출 Budget Profile

사용자 결정 `1-B`를 적용한다.

```text
NORMAL_MAX_LLM_CALLS=8
RETRIEVAL_HEAVY_MAX_LLM_CALLS=14
REVISION_HEAVY_MAX_LLM_CALLS=12
ABSOLUTE_MAX_LLM_CALLS=16
```

- 기본 Profile은 `NORMAL`이다.
- `RETRIEVAL_HEAVY`는 `NEEDS_MORE_DATA` 또는 Additional Acquisition이 실제 발생한 경우에만 선택한다.
- `REVISION_HEAVY`는 Review가 `REVISE`를 반환하고 Domain·Policy가 Revision을 허용한 경우에만 선택한다.
- Profile 승격은 Supervisor의 결정적 규칙으로 수행한다.
- `ABSOLUTE_MAX_LLM_CALLS`를 넘으면 Prompt를 더 호출하지 않는다.

### 8.3 Budget 소진 처리

Budget 소진을 `COMPLETED`로 숨기지 않는다.

```text
result_kind: PARTIAL
또는
run_status: WAITING_CONFIRMATION | BLOCKED | FAILED | RECOVERY_REQUIRED
```

---

## 9. Prompt Registry Contract

### 9.1 Prompt 선택 Key

```text
agent_role
subgraph_name
node_name
node_state
purpose
input_schema_version
output_schema_version
```

Runtime Prompt 선택 Key는 `src/google_work_agent/application/workflows/contracts.py`의
`PromptSelectionKey` 필드를 Source of Truth로 삼는다. `failure_reason_code`는
Prompt Registry·Manifest가 후보 Prompt를 고르는 metadata로 사용할 수 있지만 Runtime
Prompt 선택 Key 필드로 확정하지 않는다.

### 9.2 PromptRef

Runtime `PromptReference`는 `src/google_work_agent/ports/llm.py`와
`src/google_work_agent/application/workflows/contracts.py`의 `PromptRef` 필드가 Source of
Truth다.

```yaml
prompt_ref:
  prompt_bundle_version: string
  prompt_id: string
  prompt_version: string
  content_hash: string
  agent_role: string
  subgraph_name: string
  node_name: string
  node_state: string
  purpose: string
  input_schema_version: string
  output_schema_version: string
```

`prompt_slot_id`, `failure_reason_code`, `activation_status`는 Prompt Registry·Manifest
metadata다. 이 문서는 해당 metadata의 평가·운영 의미를 설명할 수 있지만, Runtime
`PromptReference` 포트를 대체하거나 확장하지 않는다. Failure-specific Prompt가 필요하면
Registry가 다른 `prompt_id` 또는 `prompt_version`을 선택하고, LLM 호출에는 Runtime
`PromptReference`만 전달한다.

### 9.3 Prompt 종류

```text
INITIAL
CLARIFY
ASSESS
SCHEMA_REPAIR
SEMANTIC_REVISION
RECHECK
```

`WORKFLOW_REDIRECTION`, `DETERMINISTIC_RETRY`, `DETERMINISTIC_RECOVERY`에는 PromptRef가 없어야 한다.

### 9.4 조립 규칙

```text
Base Role Contract
+ Node Purpose Instruction
+ Failure-specific Instruction Block(optional)
+ Allowed Change Scope
+ Output Schema
```

실패 원인별 Prompt 전체 복제를 금지한다. Base와 Failure Block을 조립하고 최종 조립 결과의 Hash를 기록한다.

### 9.5 Runtime 활성화 Gate

사용자 결정 `4-A`를 적용한다.

```text
DRAFT
→ Node DEV 통과
→ Node HOLDOUT 통과
→ Safety Gate 통과
→ Prompt Manifest 승인
→ RUNTIME_ACTIVE
```

검증되지 않은 Prompt는 Artifact로 존재할 수 있으나 Runtime에서 선택할 수 없다.

---

## 10. Prompt Execution Record

```yaml
prompt_execution:
  schema_version: 1
  llm_call_id: string
  run_id: string
  evaluation_item_id: string | null
  prompt_ref: object
  attempt_no: integer
  retry_kind: string
  failure_reason_codes: [string]
  previous_llm_call_id: string | null
  validator_codes: [string]
  input_hash: string
  output_hash: string
  changed_field_paths: [string]
  result_status: string
  stop_reason: string | null
```

Prompt·Completion 원문은 Trace에 저장하지 않는다. 합성 Dataset Artifact에서만 원문을 관리한다.

---

## 11. Query Attempt Contract

```yaml
query_attempt:
  schema_version: 1
  query_attempt_id: string
  run_id: string
  acquisition_round: 0 | 1 | 2
  operation_kind: SEARCH | NEXT_PAGE | DETAIL_FETCH | FREEBUSY
  source: GMAIL | TASKS | CALENDAR
  entry_mode: RESOURCE_SELECTED | AGENT_SEARCH
  normalized_intent_constraints:
    topic_terms: [string]
    people: [object]
    date_range: object | null
    status_filters: [string]
    selected_resource_ids: [string]
    allowed_sources: [string]
  previous_query_hash: string | null
  query_hash: string | null
  page_token_hash: string | null
  query_spec: object
  added_constraints: [string]
  removed_constraints: [string]
  change_reason_code: string | null
  candidate_count: integer
  top_candidate_score: number | null
  second_candidate_score: number | null
  score_margin: number | null
  confidence_band: HIGH | MEDIUM | LOW | NONE
  selected_candidate_ids: [string]
  retrieval_config_version: string
  score_config_version: string
  threshold_config_version: string
  stop_reason: SUFFICIENT | NEEDS_DETAIL | NEEDS_MORE_DATA | NEEDS_CONFIRMATION | PARTIAL | BUDGET_EXHAUSTED | AUTH_REQUIRED | FAILED
```

### 11.1 반복 검색 판정

- 같은 Query와 새로운 Page Token을 사용하는 `NEXT_PAGE`는 정상이다.
- 실패 후 같은 Query·같은 Page 상태로 `SEARCH`를 반복하면 `QUERY_REPEATED_WITHOUT_CHANGE`다.
- `DETAIL_FETCH`는 Resource ID와 Run Cache를 기준으로 중복 호출을 판정한다.
- Query 변경 여부와 Pagination 여부를 하나의 Hash 비교로 판단하지 않는다.

### 11.2 사용자 의도 반영 판정

- 사용자 날짜·사람·이메일·선택 Resource가 `query_spec`에 반영됐는지 결정적 Grader가 검사한다.
- Round 1·2에서 제약 변경 이유가 없으면 실패다.
- 한 Round에서 여러 제약을 무제한 완화하지 않는다.
- 사용자 범위 밖 확대는 `NEEDS_CONFIRMATION`으로 전환한다.

### 11.3 Confidence와 `RESOURCE_SELECTED`

- Confidence Band는 `HIGH·MEDIUM·LOW·NONE`으로 고정한다.
- 실제 Threshold 값은 중앙 Retrieval Config가 소유한다.
- `AGENT_SEARCH`의 저신뢰 후보는 자동 확정하지 않는다.
- `RESOURCE_SELECTED`는 사용자가 고른 ID를 점수와 관계없이 상세 GET한다.

---

## 12. Node Evaluation Item Schema

```yaml
node_evaluation_item:
  schema_version: 1
  evaluation_item_id: string
  source_case_id: string | null
  fixture_snapshot_id: string
  split: DEV | HOLDOUT | STRESS
  failure_family_id: string
  target_agent_role: string
  target_node_id: string
  input_conditions: [string]
  input_mode: ORACLE | LIVE | MUTATED
  mutation_profile_id: string | null
  initial_prompt_slot_id: string
  expected_result_status: string
  injected_failure_reason_codes: [string]
  expected_failure_reason_codes: [string]
  expected_retry_kind: string
  expected_retry_prompt_slot_id: string | null
  max_attempts: integer
  expected_recovery: SUCCESS | REDIRECT | STOP | NOT_APPLICABLE
  expected_next_node_id: string | null
  forbidden_transitions: [string]
  deterministic_graders: [string]
  semantic_rubric_id: string | null
```

Dataset은 Prompt Version을 소유하지 않는다. 실제 Prompt Version은 Experiment Candidate Config와 Prompt Manifest가 소유한다.

### 12.1 입력 모드

- `ORACLE`: Gold Upstream State로 대상 Node 자체 능력을 평가한다.
- `LIVE`: 실제 Upstream Output으로 Handoff 저하를 평가한다.
- `MUTATED`: 특정 실패를 주입해 Repair·Revision·Routing을 평가한다.

---

## 13. Node DEV·HOLDOUT 계약

사용자 결정 `2-A`, `3-A`를 적용한다.

### 13.1 Split

```text
Node DEV: 약 80%
Node HOLDOUT: 약 20%
```

- Node HOLDOUT은 Canonical E2E Holdout과 별도다.
- 같은 `failure_family_id`, `scenario_family_id`, `fixture_relation_family`는 DEV와 HOLDOUT에 나누지 않는다.
- Node HOLDOUT Gold는 Prompt 작성·수정 과정에서 공개하지 않는다.

### 13.2 최소 Item 수

모든 적용 가능한 Failure Reason마다 최소 다음을 둔다.

```text
DEV 대표 실패 1
DEV 경계 변형 1
DEV 표현·구조 변형 1
HOLDOUT 비공개 변형 1
```

즉, 기본 최소는 `DEV 3 + HOLDOUT 1`이다.

예외:

- 비-LLM Provider Fault는 Failure Profile별 결정적 테스트 수량을 별도 정의한다.
- 동일한 Failure Reason이라도 Source 또는 Effect에 따라 결과가 달라지면 별도 Family로 나눈다.

---

## 14. Agent별 최소 Capability Coverage

### 14.1 요청 이해

```text
명확한 Answer-only
명확한 Write
복합 요청
RESOURCE_SELECTED
인물·기간·대상 Resource 모호성
제약 누락 위험
불필요한 확인 질문
범위 밖·금지 요청
Paraphrase·혼합 언어
```

### 14.2 Acquisition

```text
단일·복수 Source
NO_FETCH_NEEDED
RESOURCE_SELECTED 직접 GET
날짜·사람·이메일·상태 제약
결과 없음
저신뢰 후보
Query 과대·과소
동일 Search 반복
정상 Pagination
부분 Source 실패
Round 1·2 Revision
Budget 소진
범위 확대 전 확인
```

### 14.3 Context Retrieval

```text
Required Evidence 선택
Hard Negative 배제
최신 합의 선택
상충 Evidence
긴 Thread·서명·인용 Noise
저신뢰 후보
NEEDS_MORE_DATA
NEEDS_CONFIRMATION
PARTIAL
BLOCKED
Prompt Injection
Context Budget
```

### 14.4 Work Analysis

```text
담당·일정 연결
누락 업무
Task·Event 중복
가용성·충돌
상충 Evidence
부분 Source
Evidence 없는 추론 차단
NEEDS_MORE_DATA
NEEDS_CONFIRMATION
```

### 14.5 Planning

```text
ANSWER_ONLY
단일 CREATE
단일 UPDATE
복합 DAG
부분 승인
Evidence 연결
CREATE·UPDATE Target 규칙
불필요 Action 차단
금지 Tool 차단
확인 질문 전환
BLOCK 전환
```

### 14.6 Review

```text
정상 PASS
REVISE
RETRIEVE_MORE
CONFIRM
BLOCK
False PASS
False Block
오류 위치 특정
Revision 후 Recheck
동일 실패 반복 종료
```

---

## 15. Coverage 완료 조건

### 15.1 개별 Agent

- 적용 가능한 모든 Result Enum에 Item이 있다.
- 적용 가능한 모든 입력 조건에 Item이 있다.
- 모든 LLM-retryable Failure Reason에 `DEV 3 + HOLDOUT 1`이 있다.
- 모든 Non-retryable Failure에 올바른 Redirection·Stop Item이 있다.
- First-pass와 After-repair·After-revision을 별도로 측정한다.
- ORACLE·LIVE·MUTATED 결과를 분리한다.
- 동일 Failure Signature 반복 시 Budget 종료를 검증한다.
- Over-confirmation·Overblocking을 측정한다.
- Prompt Version별 회귀가 가능하다.

### 15.2 E2E

- Answer-only, READ-only, WRITE 경로가 존재한다.
- Additional Acquisition 0·1·2회가 존재한다.
- Confirmation·Approval·Reauth·Recovery Interrupt가 존재한다.
- `COMPLETED`, `BLOCKED`, `FAILED`, `CANCELLED`, `RECOVERY_REQUIRED`가 존재한다.
- `PARTIAL` 결과 종류가 정상·장애 상태와 올바르게 조합된다.
- Review의 PASS·REVISE·RETRIEVE_MORE·CONFIRM·BLOCK 경로가 존재한다.
- LLM Prompt 경로와 결정적 Recovery 경로가 혼동되지 않는다.
- Safety Critical 오류는 가중 점수가 아닌 Gate다.

---

## 16. Dataset Layer Contract

| Layer | 목적 | 주요 단위 |
|---|---|---|
| `canonical_e2e` | 현실 업무와 전체 Workflow | Canonical Case |
| `node_capability_dev` | Agent Prompt 개발·오류 분석 | Node Evaluation Item |
| `node_capability_holdout` | Agent Prompt 과적합 검증 | 잠긴 Node Item |
| `prompt_repair_revision` | 실패 원인별 복구 | Mutated Node Item |
| `query_retrieval` | Query·후보·Confidence·Round | Query Attempt Item |
| `fault_safety` | 비-LLM 장애·정책 Gate | Fault Profile |
| `paraphrase_robustness` | 사용자 표현 변화 | Prompt Variant |
| `canonical_holdout` | 최종 E2E 후보 검증 | 잠긴 Canonical Family |

하나의 Canonical Fixture에서 여러 Node·Mutation Item을 파생할 수 있다.

---

## 17. Prompt·Node 실험 분해

### 17.1 E02

```text
E02-A Initial Prompt Quality
E02-B Structured Output Schema Repair
E02-C Failure-specific Semantic Revision
E02-D Retry Selection and Stop Policy
```

### 17.2 E03

```text
E03-A ORACLE Node Capability
E03-B LIVE Handoff Robustness
E03-C MUTATED Upstream Input
E03-D Error Propagation Attribution
```

한 Run에서 원칙적으로 하나의 독립 변수만 변경한다.

---

## 18. Grader Contract

### 18.1 결정적 Grader

```text
Schema Validity
Result Enum
Required·Forbidden Source
Tool Name·Effect
Query Constraint 반영
Query 반복과 정상 Pagination 구분
Required Evidence ID
Allowed·Forbidden Action
CREATE·UPDATE Target
Dependency DAG
Route·Node Skip
Retry Count·Budget Profile
End-state와 result_kind
```

### 18.2 의미 Grader

```text
Goal 충족
Evidence 충실성
요약 과장 여부
확인 질문 명확성
분석 유용성
정상 Plan 과잉 차단
```

LLM Judge는 보조 지표로만 사용한다.

---

## 19. Trace·Artifact Contract

Trace 추가 필드:

```text
failure_reason_codes
failure_origin
detected_by
runtime_disposition
retry_kind
attempt_no
previous_llm_call_id
validator_codes
changed_field_paths
stop_reason
query_attempt_id
budget_profile
```

저장 금지:

```text
실제 사용자 Prompt 원문
Google 원문 전체
Prompt Template 원문
LLM Completion 원문
Credential
Holdout Gold 원문
```

---

## 20. 문서 영향

| 문서 | 필수 변경 |
|---|---|
| `05 Context·Retrieval` | QueryAttempt, Confidence, Search 반복·Pagination 구분, Config Version |
| `06 Agent·Workflow` | Retry Kind, Failure Record, Prompt 선택 Key, Route별 Budget Profile |
| `11 Observability` | Failure·Retry·Attempt·Query·Budget Trace 필드 |
| `12 Test` | 금지 Retry, 저신뢰 자동 선택, 반복 Search, Holdout 누수 회귀 |
| `13 Evaluation` | E02·E03 분해, Dataset Layer, Node DEV·HOLDOUT, Item 최소 수 |
| `04 Domain·DB` | `terminal_reason_code`, `recovery_reason_code` 저장 필요 여부만 검토 |

---

## 21. 확정 결정

```yaml
llm_budget_policy: ROUTE_PROFILE
normal_max_llm_calls: 8
retrieval_heavy_max_llm_calls: 14
revision_heavy_max_llm_calls: 12
absolute_max_llm_calls: 16
node_holdout: SEPARATE
failure_reason_min_items:
  dev: 3
  holdout: 1
prompt_runtime_activation: VALIDATION_GATED
semantic_revision_same_failure_max: 1
planning_revision_run_max: 2
review_recheck_per_revision_max: 1
additional_acquisition_max: 2
confidence_bands: [HIGH, MEDIUM, LOW, NONE]
threshold_owner: RETRIEVAL_CONFIG
failure_reason_prompt_key: REGISTRY_METADATA
prompt_assembly: BASE_PLUS_FAILURE_BLOCK
```

---

## 22. 승인 상태

```yaml
contract_version: 0.2.0-draft
user_decisions: APPROVED
internal_consistency_review: PENDING
notion_updated: false
repository_docs_updated: false
schemas_generated: false
prompts_generated: false
node_datasets_generated: false
```

## 23. Request Understanding 확정 계약

본 문서의 Request Understanding failure·prompt 계약은 `06. Agent Workflow`의
`RequestIntentV1`과 Node Output 계약을 따른다.

### 23.1 Capability 범위

Request Understanding은 다음만 수행한다.

- 사용자 요청의 목표와 완료 조건 구조화
- 기간·사람·Source·상태·제약의 semantic mention 보존
- 사용자 문장 자체의 모호성 표시
- 제품 범위 밖 요청의 semantic invalid 표시

Request Understanding은 다음을 수행하지 않는다.

- Google/MCP 조회
- Google Resource ID 생성
- Gmail/Calendar/Tasks query 또는 date range 확정
- Google 조회 결과의 복수 후보 disambiguation
- Action, Plan, Approval 생성

### 23.2 Failure Reason 적용

요청 이해 실패 reason은 다음처럼 사용한다.

- `INTENT_GOAL_MISSING`: 목표 자체가 비어 있거나 실행 가능한 업무 목표가 없음
- `INTENT_COMPLETION_CRITERIA_MISSING`: 완료 조건을 만들 수 없고 사용자 확인이 필요함
- `INTENT_CONSTRAINT_MISSING`: 사용자 문장 안의 필수 제약이 빠짐
- `INTENT_AMBIGUITY_MISSED`: 문장 자체의 모호성을 놓침
- `INTENT_OVER_CONFIRMATION`: downstream 조회로 해결할 수 있는 후보 ambiguity를 과도하게 사용자 확인으로 돌림
- `INTENT_UNSUPPORTED_SCOPE`: 제품 범위 밖 요청

Google 조회 결과의 동명이인·복수 후보는 `INTENT_AMBIGUITY_MISSED`가 아니라
Acquisition·Retrieval failure family에서 다룬다.

### 23.3 Schema Repair와 INVALID

Schema JSON 오류, required field 누락, enum 오류, type 오류는 Request Understanding
`INVALID`가 아니다. 이는 `LLMRuntimeService.invoke_structured(...)`의 structured output
schema failure이며 Node Call당 최대 1회 `SCHEMA_REPAIR` 대상이다.

`INVALID`는 schema가 맞는 payload를 일반 코드가 semantic validation한 뒤 사용자 요청
자체가 제품 범위에서 처리 불가능하다고 판단할 때만 사용한다.

### 23.4 classify / clarify / repair Prompt

- `request_understanding.classify`: 첫 구현에 필요한 runtime prompt다.
- `request_understanding.clarify`: 현재 예약 상태다. classify output과 deterministic
  validator만으로 clarification payload를 만들 수 없을 때 이후 작성한다.
- `request_understanding.repair`: structured output schema repair 전용이며 semantic
  rewrite prompt가 아니다. 실제 failure trace와 dataset item이 생긴 뒤 작성한다.

Prompt artifact가 예약 상태라는 이유로 Request Understanding 구현을 막지 않는다.
