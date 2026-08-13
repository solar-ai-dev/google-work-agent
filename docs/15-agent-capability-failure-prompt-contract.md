# Google Work Agent · Agent Capability · Failure · Prompt 공통 계약

> **상태:** Approved v1.10  
> **기준일:** 2026-08-13  
> **대상:** P0 Agent 개별실험, Prompt·Repair·Revision 실험, E2E 통합실험  
> **적용 범위:** Request Understanding, Tool Route, Retrieval, Work Analysis, Planning, Review  
> **비적용 범위:** 승인, Claim, Google Write, GET Verification, UNKNOWN_RESULT 복구, Domain 상태 전이의 최종 판정

## 먼저 읽기 — Prompt가 알아도 되는 것

- Product Prompt는 **사용자 요청, 허용된 Context, Policy Summary, Failure Record 같은 선언된 Runtime 입력만** 본다.
- `gold`, `grader`, `expected_route`, benchmark score는 Product Prompt 입력이 아니다.
- Failure-specific Prompt는 별도 전체 Prompt가 아니라 **Base Slot + Failure Instruction Block**으로 조립한다.
- E06-B의 모델 입력과 Gold는 파일 수준에서도 분리한다.
- 현재 정적 검수 기준 Prompt Bundle은 `0.8.2-r8.3`이며 모든 신규 Slot은 `DRAFT`다. Node DEV/HOLDOUT·Safety Gate 전에는 Runtime 활성화하지 않는다.

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
- Product Runtime Prompt 문구는 `grader`, `gold`, `expected_route`, 평가 점수에 의존하지 않는다. 실험 Grader가 발견한 오류도 Runtime과 동일한 `failure_record` 형태로 투영한 뒤 Prompt에 전달한다.
- Structured Output Schema Repair는 Node Call당 최대 1회다.
- 최초 Retrieval 이후 Additional Retrieval은 최대 2회다.
- Planning Revision은 Run당 최대 2회다.
- 실행·검증·승인·정책 최종 판정에는 LLM Prompt를 사용하지 않는다.
- `UNKNOWN_RESULT`에서는 새 Write Attempt를 만들지 않는다.

### 1.2 충돌 우선순위

```text
01 PRD·01-B 정책
→ 03 Architecture 경계
→ 04 Domain 상태 전이·DB Constraint
→ 07 Tool Registry·Interface
→ 05 Context·Retrieval·06 Agent·Workflow 제품 계약
→ 본 공통 Capability·Failure·Prompt 계약
→ 11 Observability·12 Test·13 Evaluation
→ 개별 Prompt·Dataset Artifact
```

본 계약은 상위 문서의 안전·승인·Domain 규칙을 완화할 수 없다.

---

## 1.2 Agent Subgraph 공통 계약

본 문서에서 **Agent**는 단순 Prompt 호출이나 Python 객체 수가 아니라, Main Supervisor가 호출하는 LangGraph Subgraph를 뜻한다.

필수 속성:
- 안정적인 `agent_role` 책임 계약
- Parent State에서 필요한 입력만 받는 Input Projection
- invocation 범위 `AgentLocalState`
- PromptRef 기반 LLM Node
- 역할상 필요한 결정적 Validation·Read Application Node
- Schema Validation과 허용된 bounded Repair/Revision
- Versioned Typed Result + disposition + 필요한 Typed Workflow Signal 반환
- Agent→Agent 직접 호출 금지
- 장기 Memory 금지

Prompt Slot 수, PromptRef 수, LLM Call 수는 Agent 수와 독립적이다. 같은 Agent 안의 `INITIAL`, `CLARIFY`, `SCHEMA_REPAIR`, `SEMANTIC_REVISION`, `RECHECK`는 하나의 책임 계약을 보조하는 Prompt variant다.

공통 Runtime Envelope는 invocation metadata와 failure/repair counter만 보존한다. 업무 데이터는 Subgraph별 Typed Local State에 둔다. Local candidate·Query candidate·RAG score·Prompt 원문은 invocation 종료 후 다른 Agent 호출로 자동 승계하지 않는다. 제품의 장기 사실과 승인·실행·검증은 Main Graph Typed State와 Domain Store 계약을 따른다.

각 Node는 Parent/Main State 전체를 받지 않고 자기 작업에 필요한 Typed Projection만 받는다. 예를 들어 Retrieval Query Planner는 `request_intent + input_routes`, Evidence Selector는 `request_intent + ranked_segments`, Planning Argument Writer는 `output_route + work_analysis + evidence_refs`만 받는다.

외부 READ는 Retrieval Subgraph의 결정적 Application Node가 Query Builder·MCP Read Port를 호출한다. Retrieval LLM Node는 Raw Query·MCP Arguments를 직접 실행하지 않으며 `ToolRoutePlanV2.input_plan.input_routes` 밖의 Tool을 선택하거나 호출하지 않는다.

Graph Profile 간 semantic responsibility parity를 유지한다. 특히 `SINGLE_BASELINE`은 별도 Review Agent를 두지 않더라도 Unified Agent 내부 `self_review` 단계로 계획 품질 점검 책임을 수행한다.


### Policy Precondition·Receipt 공통 계약
- Release Graph의 READ는 Retrieval이 소유하지만 Tool Route 의미 후보 뒤 결정적 `PolicyPreconditionResolver`가 `TASK + CREATE` 중복검사와 `CALENDAR + CREATE` 충돌검사 IN READ를 보강한다. 이는 두 번째 Tool 선택이 아니다.
- 사용자 지정 범위 밖 필수 READ는 `SCOPE_EXPANSION_REQUIRED` Confirmation 전에는 materialize/execute하지 않는다.
- 실제 사용자 응답을 검증한 Application/Confirmation Controller만 `PolicyConfirmationReceiptV1`을 생성한다. Agent/LLM은 Receipt를 생성하거나 승인 결정을 추정할 수 없다.
- 날짜/interval 계산, Registry eligibility, Policy Precondition, Confirmation Receipt context 검증, 중복·충돌 relation 검증, state freshness, DAG cycle, Policy·Approval·Verification은 deterministic code가 소유한다.
- Work Analysis LLM은 중복/충돌 후보만 제안하며 최종 `DUPLICATES`·`CONFLICTS_WITH`와 no-action 판단은 deterministic relation validator를 거친다.


## 2. Agent Registry

<table fit-page-width="true" header-row="true">
	<tr>
		<td>Agent Role</td>
		<td>주 책임</td>
		<td>주요 입력</td>
		<td>주요 출력</td>
		<td>금지</td>
	</tr>
	<tr>
		<td>`request_understanding`</td>
		<td>목표·완료 조건·제약·모호성·analysis requirement 구조화</td>
		<td>`RunInputV1`</td>
		<td>`RequestIntentV2`</td>
		<td>Tool 선택, Google 조회, Action Arguments</td>
	</tr>
	<tr>
		<td>`tool_route`</td>
		<td>IN Resource/Read Tool 범위와 OUT Resource/Effect/Tool 확정</td>
		<td>`RequestIntentV2`, Signed Tool Registry</td>
		<td>`ToolRoutePlanV2`</td>
		<td>Query 작성, Evidence 판단, Arguments 작성</td>
	</tr>
	<tr>
		<td>`retrieval`</td>
		<td>고정 IN Route에서 Query·Read·RAG·Evidence·Sufficiency</td>
		<td>Intent, `input_routes`, Retrieval Budget</td>
		<td>`RetrievalResultV1`</td>
		<td>OUT Tool 변경, Write, Tool 종류 재선택</td>
	</tr>
	<tr>
		<td>`work_analysis`</td>
		<td>필요한 경우 업무 사실·관계·누락·중복·충돌·일정 위험 분석</td>
		<td>Intent, Evidence</td>
		<td>`WorkAnalysisResultV2`</td>
		<td>Tool 선택, Arguments, 정책 최종 판정</td>
	</tr>
	<tr>
		<td>`planning`</td>
		<td>고정 OUT Route의 Answer/Arguments·Dependency 작성</td>
		<td>Intent, `output_routes`, Analysis, Evidence</td>
		<td>`AnswerDraftV2` 또는 `ActionPlanDraftV2`</td>
		<td>Tool 재선택, 승인, 실행</td>
	</tr>
	<tr>
		<td>`review`</td>
		<td>목표 충족·Evidence·과잉 Action·모순·Route 오류 검토</td>
		<td>Plan Draft, Evidence, Policy Summary</td>
		<td>`PlanReviewResultV2`</td>
		<td>Route 직접 변경, 실행 허용 최종 판정</td>
	</tr>
</table>

Tool Route 내부에서는 Resource·Effect 의미 판단과 Registry Binding을 분리한다. 실제 Tool 후보는 Signed Tool Registry가 결정적으로 산출하고, 후보가 여러 개일 때만 Route 선택 Node가 등록 후보 중 하나를 선택한다.

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

Tool Route:
  ROUTE_READY | NO_TOOL_NEEDED | NEEDS_CONFIRMATION | BLOCKED

Retrieval:
  SUFFICIENT | NO_FETCH_NEEDED | NEEDS_MORE_DATA | NEEDS_CONFIRMATION |
  ROUTE_RECONSIDERATION_REQUIRED | PARTIAL | BLOCKED

Work Analysis:
  COMPLETE | NEEDS_MORE_DATA | NEEDS_CONFIRMATION | ROUTE_RECONSIDERATION_REQUIRED | BLOCKED

Planning:
  ANSWER_ONLY | PLAN_READY | NEEDS_CONFIRMATION | ROUTE_RECONSIDERATION_REQUIRED | BLOCKED

Review:
  PASS | REVISE | RETRIEVE_MORE | ROUTE_RECONSIDERATION | CONFIRM | BLOCK

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

<table fit-page-width="true" header-row="true">
	<tr>
		<td>Code</td>
		<td>기본 Runtime 처리</td>
	</tr>
	<tr>
		<td>`SCHEMA_INVALID_JSON`</td>
		<td>`SCHEMA_REPAIR`</td>
	</tr>
	<tr>
		<td>`SCHEMA_REQUIRED_FIELD_MISSING`</td>
		<td>`SCHEMA_REPAIR`</td>
	</tr>
	<tr>
		<td>`SCHEMA_INVALID_ENUM`</td>
		<td>`SCHEMA_REPAIR`</td>
	</tr>
	<tr>
		<td>`SCHEMA_WRONG_TYPE`</td>
		<td>`SCHEMA_REPAIR`</td>
	</tr>
	<tr>
		<td>`SCHEMA_UNSUPPORTED_FIELD`</td>
		<td>`SCHEMA_REPAIR`</td>
	</tr>
	<tr>
		<td>`SCHEMA_VERSION_MISMATCH`</td>
		<td>호출 중단 또는 Schema Repair 1회</td>
	</tr>
</table>

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

### 6.3 Tool Route 실패

```text
TOOL_ROUTE_REQUIRED_INPUT_MISSING
TOOL_ROUTE_FORBIDDEN_INPUT_INCLUDED
TOOL_ROUTE_REQUIRED_OUTPUT_MISSING
TOOL_ROUTE_FORBIDDEN_OUTPUT_INCLUDED
TOOL_ROUTE_UNREGISTERED_TOOL
TOOL_ROUTE_EFFECT_MISMATCH
TOOL_ROUTE_OUTPUT_MODE_WRONG
TOOL_ROUTE_OVERCONFIRMATION
```

### 6.4 Retrieval·Query·RAG 실패

```text
RETRIEVAL_ROUTE_SCOPE_VIOLATION
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
RAG_REQUIRED_SEGMENT_MISSING
RAG_HARD_NEGATIVE_SELECTED
RAG_STALE_EVIDENCE_SELECTED
RAG_PROMPT_INJECTION_FOLLOWED
RAG_CONTEXT_BUDGET_EXCEEDED
CTX_CONFLICT_NOT_REPORTED
CTX_LOW_CONFIDENCE_AUTO_SELECTED
CTX_SUFFICIENCY_WRONG
RETRIEVAL_ROUTE_RECONSIDERATION_MISSED
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
PLAN_ROUTE_TOOL_MISMATCH
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
REVIEW_ROUTE_RECONSIDERATION_MISSED
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

<table fit-page-width="true" header-row="true">
	<tr>
		<td>Retry Kind</td>
		<td>정의</td>
		<td>LLM 사용</td>
	</tr>
	<tr>
		<td>`NONE`</td>
		<td>성공·종료 또는 재시도 없는 경로 전환</td>
		<td>아니오</td>
	</tr>
	<tr>
		<td>`SCHEMA_REPAIR`</td>
		<td>의미를 유지하며 구조만 교정</td>
		<td>예</td>
	</tr>
	<tr>
		<td>`SEMANTIC_REVISION`</td>
		<td>실패 이유와 허용 범위 안에서 내용을 재판단</td>
		<td>예</td>
	</tr>
	<tr>
		<td>`WORKFLOW_REDIRECTION`</td>
		<td>다른 Node·Interrupt·종료로 이동</td>
		<td>아니오</td>
	</tr>
	<tr>
		<td>`DETERMINISTIC_RETRY`</td>
		<td>네트워크·Provider Read 기술 재시도</td>
		<td>아니오</td>
	</tr>
	<tr>
		<td>`DETERMINISTIC_RECOVERY`</td>
		<td>Reauth·Fingerprint Search·GET Verification</td>
		<td>아니오</td>
	</tr>
</table>

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
Additional Retrieval: 최초 Retrieval 이후 최대 2회
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
- `RETRIEVAL_HEAVY`는 `NEEDS_MORE_DATA` 또는 Additional Retrieval이 실제 발생한 경우에만 선택한다.
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

### 9.1 Prompt Runtime Slot 선택 Key

```text
agent_role
subgraph_name
node_name
node_state
purpose
input_schema_version
output_schema_version
```

`failure_reason_code`는 Runtime Prompt Slot 식별 Key가 아니다. 이미 선택된 Base Prompt에 결합할 Failure-specific Instruction Block을 선택하는 metadata다. 조립 완료 후 최종 Prompt의 `content_hash`를 계산한다.

### 9.2 PromptRef

```yaml
prompt_ref:
  prompt_bundle_version: string
  prompt_slot_id: string
  prompt_id: string
  prompt_version: string
  content_hash: string
  agent_role: string
  subgraph_name: string
  node_name: string
  node_state: string
  purpose: string
  failure_reason_code: string | null  # assembly/trace metadata; not Runtime Slot Key
  input_schema_version: integer
  output_schema_version: integer
  activation_status: DRAFT | DEV_VALIDATED | HOLDOUT_VALIDATED | RUNTIME_ACTIVE | RETIRED
```

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

Node DEV·Node HOLDOUT·Safety Gate는 고정 Sampling 조건에서 Item당 1회 평가한다(`12` 18.2). Temperature는 Gate Configuration에서 명시적으로 고정하고, Seed는 Provider가 지원함이 확인된 경우에만 고정한다 — 완전한 bit-identical Determinism을 보장하는 것은 아니며 best-effort 재현성이다. 반복 Trial Consistency·평균·분산·Bootstrap Confidence Interval 평가는 `13` Evaluation 소관이며 Gate로 옮기지 않는다.

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
  retrieval_round: 0 | 1 | 2
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

### 14.2 Tool Route

```text
ANSWER without external Tool
IN-only Read Answer
IN→OUT 복합 요청
복수 IN Route
복수 OUT Route
CREATE·UPDATE·SEND·DELETE Effect
Registered Tool binding
Unregistered Tool 차단
Required Route 누락
Forbidden Route 포함
Route 모호성 → NEEDS_CONFIRMATION
```

### 14.3 Retrieval

```text
단일·복수 Input Route
RESOURCE_SELECTED 직접 GET
날짜·사람·이메일·상태 제약
결과 없음
저신뢰 후보
Query 과대·과소
동일 Search 반복
정상 Pagination
부분 Source 실패
Round 1·2 Additional Retrieval
Budget 소진
범위 확대 전 확인
Run-scoped RAG Required Segment 선택
Hard Negative 배제
최신 합의 선택
상충 Evidence
긴 Thread·서명·인용 Noise
Prompt Injection
Context Budget
ROUTE_RECONSIDERATION_REQUIRED
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
고정 OutputRoute의 단일 CREATE
고정 OutputRoute의 단일 UPDATE
SEND·DELETE Arguments
복합 DAG
Evidence 연결
CREATE·UPDATE Target 규칙
불필요 Action 차단
Route Tool 재선택 차단
Tool Schema Argument 작성
확인 질문 전환
ROUTE_RECONSIDERATION_REQUIRED
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
- Additional Retrieval 0·1·2회가 존재한다.
- Confirmation·Approval·Reauth·Recovery Interrupt가 존재한다.
- `COMPLETED`, `BLOCKED`, `FAILED`, `CANCELLED`, `RECOVERY_REQUIRED`가 존재한다.
- `PARTIAL` 결과 종류가 정상·장애 상태와 올바르게 조합된다.
- Review의 PASS·REVISE·RETRIEVE_MORE·CONFIRM·BLOCK 경로가 존재한다.
- LLM Prompt 경로와 결정적 Recovery 경로가 혼동되지 않는다.
- Safety Critical 오류는 가중 점수가 아닌 Gate다.

---

## 16. Dataset Layer Contract

<table fit-page-width="true" header-row="true">
	<tr>
		<td>Layer</td>
		<td>목적</td>
		<td>주요 단위</td>
	</tr>
	<tr>
		<td>`canonical_e2e`</td>
		<td>현실 업무와 전체 Workflow</td>
		<td>Canonical Case</td>
	</tr>
	<tr>
		<td>`node_capability_dev`</td>
		<td>Agent Prompt 개발·오류 분석</td>
		<td>Node Evaluation Item</td>
	</tr>
	<tr>
		<td>`node_capability_holdout`</td>
		<td>Agent Prompt 과적합 검증</td>
		<td>잠긴 Node Item</td>
	</tr>
	<tr>
		<td>`prompt_repair_revision`</td>
		<td>실패 원인별 복구</td>
		<td>Mutated Node Item</td>
	</tr>
	<tr>
		<td>`query_retrieval`</td>
		<td>Query·후보·Confidence·Round</td>
		<td>Query Attempt Item</td>
	</tr>
	<tr>
		<td>`ambiguity_clarification`</td>
		<td>후보·관계·동작 모호성 해소</td>
		<td>Clarification Item</td>
	</tr>
	<tr>
		<td>`risky_user_requests`</td>
		<td>승인 우회·금지 동작·검증 생략 등 위험 사용자 요청</td>
		<td>Safety Request Item</td>
	</tr>
	<tr>
		<td>`adversarial_source_content`</td>
		<td>Source 내부 Prompt Injection·정책 우회 지시</td>
		<td>Adversarial Source Item</td>
	</tr>
	<tr>
		<td>`fault_write_integrity`</td>
		<td>비-LLM 장애·UNKNOWN_RESULT·MISMATCH·Write 무결성</td>
		<td>Fault Profile</td>
	</tr>
	<tr>
		<td>`paraphrase_robustness`</td>
		<td>사용자 표현 변화</td>
		<td>Prompt Variant</td>
	</tr>
	<tr>
		<td>`canonical_holdout`</td>
		<td>최종 E2E 후보 검증</td>
		<td>잠긴 Canonical Family</td>
	</tr>
</table>

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


## 18.3 Prompt와 Evaluator 격리

- Prompt 입력은 선언된 Input Schema만 사용한다. Gold·grader result·score field를 모델 입력에 넣지 않는다.
- `failure_reason_code`는 Base Prompt Slot 선택 Key가 아니라 Failure Block 조립 metadata다.
- Experiment-only feedback은 `failure_record`로 정규화하며 Product Prompt 문구에 “grader가 틀렸다고 했다” 같은 표현을 넣지 않는다.
- E06-B는 model input과 grader Gold를 물리적으로 분리한다.

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

<table fit-page-width="true" header-row="true">
	<tr>
		<td>문서</td>
		<td>필수 변경</td>
	</tr>
	<tr>
		<td>`05 Context·Retrieval`</td>
		<td>QueryAttempt, Confidence, Search 반복·Pagination 구분, Config Version</td>
	</tr>
	<tr>
		<td>`06 Agent·Workflow`</td>
		<td>Retry Kind, Failure Record, Prompt 선택 Key, Route별 Budget Profile</td>
	</tr>
	<tr>
		<td>`11 Observability`</td>
		<td>Failure·Retry·Attempt·Query·Budget Trace 필드</td>
	</tr>
	<tr>
		<td>`12 Test`</td>
		<td>금지 Retry, 저신뢰 자동 선택, 반복 Search, Holdout 누수 회귀</td>
	</tr>
	<tr>
		<td>`13 Evaluation`</td>
		<td>E02·E03 분해, Dataset Layer, Node DEV·HOLDOUT, Item 최소 수</td>
	</tr>
	<tr>
		<td>`04 Domain·DB`</td>
		<td>`terminal_reason_code`, `recovery_reason_code` 저장 필요 여부만 검토</td>
	</tr>
</table>

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
additional_retrieval_max: 2
confidence_bands: [HIGH, MEDIUM, LOW, NONE]
threshold_owner: RETRIEVAL_CONFIG
failure_reason_prompt_key: ASSEMBLY_METADATA
prompt_assembly: BASE_PLUS_FAILURE_BLOCK
```

## 22. Clarification Capability
- 모호성은 기본 BLOCK이 아니라 `NEEDS_CONFIRMATION → request_understanding.clarify`다.
- 후보가 있으면 후보·차이·선택지를 제공하고, 후보가 없으면 최소 누락 정보만 질문한다.
- `처리/진행/시작/정리/마무리`는 문맥으로 의미가 단일하면 질문하지 않는다.
- `답장/회신/보내줘`는 SEND 의도이며 Draft ambiguity가 아니다.
- 요청/검색/분석 중 실제 모호성이 관측된 단계에서 Redirection한다.

## Attachment Capability 경계

- Gmail 첨부파일 I/O는 Agent Semantic Capability가 아니다.
- Product Prompt에 첨부파일 bytes·파일 내용·Local Path를 넣지 않는다.
- Agent는 필요 시 파일명·MIME Type·크기·Attachment Descriptor만 사용한다.
- Download/Stage/Hash Verification/MIME 조립/Claim V2 검증 실패는 `DETERMINISTIC` 또는 `TERMINAL` Runtime 처리이며 LLM Repair·Semantic Revision 대상으로 바꾸지 않는다.
- Claim V2와 Attachment integrity는 제품 Runtime 안전 계약이므로 Agent Profile 실험의 독립변수로 변경하지 않는다.
