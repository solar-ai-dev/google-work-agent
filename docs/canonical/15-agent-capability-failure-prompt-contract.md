# 15. Agent Capability · Failure · Prompt 공통 계약

> **Authority:** Agent capability·normalized failure·Prompt runtime contract. 승인/Claim/Write/Verification/Domain lifecycle의 최종 판정은 해당 owner를 따른다.  
> **상태:** Approved v1.32 · **기준일:** 2026-09-03 · **대상:** P0 Product Agent/Prompt Runtime

## 0. 문서 목적

이 계약은 다음 항목을 하나의 기준으로 고정한다.

1. 각 Agent/Node의 capability와 Typed Result 범위
2. 실패를 분류하는 공통 `failure_reason_code`
3. 실패 유형별 Repair·Revision·Redirection·Recovery 처리 규칙
4. Prompt Registry·PromptRef·Input Contract와 bounded Prompt assembly
5. Query Attempt와 Product Prompt가 공유하는 runtime-safe failure/projection contract

이 문서는 `05 Context·Retrieval`과 `06 Agent·Workflow`의 제품 의미를 Prompt·Failure 관점으로 정규화한다. `12 Test`와 `13 Evaluation`은 여기의 PromptRef·failure/result contract를 검증·평가용으로 소비하지만 Dataset·Grader·candidate selection 의미를 이 문서에 역수입하지 않는다.

---

### 0.1 Product Prompt input boundary

- Product Prompt는 **사용자 요청, 허용된 Context, Policy Summary, Failure Record 같은 선언된 Runtime 입력만** 본다.
- `gold`, `grader`, `expected_route`, benchmark score는 Product Prompt 입력이 아니다.
- Failure-specific Prompt는 별도 전체 Prompt가 아니라 **Base Slot + Failure Instruction Block**으로 조립한다.
- Evaluation diagnostic decomposition에서도 Product Prompt 입력과 Gold/Grader metadata를 파일·schema 수준에서 분리한다.
- Current Prompt Runtime은 `06 Workflow`의 current LLM responsibility set과 본 문서의 PromptRef/Input Contract에서 파생한다. required PromptRef = runtime caller = manifest = source = assembled = input-contract exact-set equality를 만족해야 하며 numeric Slot count나 non-current bundle version을 current authority로 사용하지 않는다. DEV·Holdout·Safety Gate는 구현된 Prompt artifact의 release activation만 결정한다.

### Inference tier input boundary

- Product Prompt에는 concrete provider/model 선택 지시나 installed model 목록을 넣지 않는다.
- Runtime caller가 PromptRef와 별도로 closed `InferenceTierV1 = WORKER | REASONING`을 선택한다. Tier는 Prompt semantic input이 아니라 signed runtime binding metadata다.
- Prompt source·failure instruction·LLM output은 tier/model을 변경하거나 더 큰 모델 재호출을 요구할 수 없다.
- `WORKER`는 13에서 해당 Prompt slot의 bounded extraction/classification 안정성이 검증된 경우에만 허용한다. ambiguity, Tool Routing, Retrieval planning/sufficiency, Analysis, Planning, Review는 기본 `REASONING` 후보다.
- Schema Repair/Semantic Revision/Confirmation resume은 원 invocation tier를 유지한다. allowed fallback/substitution은 Router/Release policy가 결과 Metadata로만 투영한다.
- 현재 반복 Confirmation 결함은 `request.detect_ambiguity`의 Projection→candidate→validator→disposition을 qwen2.5:7b/L1/L2로 비교하는 required evaluation case다.

### Conversation · Run Prompt 입력 경계

- Conversation Timeline은 사용자에게 보여 주는 저장 이력이지 Product Prompt의 자동 Memory가 아니다.
- 새 Run의 Product Prompt는 `prompt-runtime-input-contract-v1`이 허용한 **현재 Run Typed Projection만** 직렬화한다. 같은 Conversation의 과거 USER/ASSISTANT Message 전체, 이전 Run의 RequestIntent·ToolRoute·Retrieval/Evidence·WorkAnalysis·Plan/Review·PromptContext를 숨은 입력으로 붙이지 않는다.
- Request Understanding 최초 invocation은 현재 `RunInputV1.user_request + selected_resource_refs`만 의미 입력으로 사용한다. 사용자가 과거 Resource를 이번 Run에 명시적으로 다시 선택한 경우 그 Resource Ref는 current-run Entry Context로 허용되지만 이전 Run의 Evidence 판정이나 Approval을 함께 가져오지 않는다.
- 새 Run에는 이전 Run의 `confirmation_response`, Policy Confirmation Receipt, interrupt/checkpoint metadata를 승계하지 않는다.
- 같은 Run의 Confirmation resume에서만 Controller가 검증·정규화한 bounded `ConfirmationResponseProjectionV1`을 `confirmation_response` optional Root Field로 **originating owner의 해당 Product Prompt**에 전달할 수 있다. 기존 raw resume metadata 금지 계약은 그대로 유지한다.
- `관련 메일 찾아줘`처럼 이전 Run을 암묵적으로 알아야만 의미가 정해지고 current-run explicit Resource가 없는 요청은 과거 Conversation History를 모델에 주입해 해결하지 않고 Request Understanding의 `NEEDS_CONFIRMATION` 경계로 보낸다.

## 1. 기준 문서와 우선순위

### 1.1 유지하는 확정 계약

- Supervisor는 결정적 Router다.
- LLM Agent는 외부 Provider API·MCP Write를 직접 호출하지 않는다. P0 Google Workspace Provider도 동일하다.
- 실제 Raw Query·Page Token·MCP Read Arguments는 결정적 코드가 생성·검증한다. Retrieval pagination의 raw Provider continuation은 `05 Retrieval` current contract가 정의한 Run Retrieval Cache read-result entry에만 memory-only로 존재하며 Product Prompt·Main State·Checkpoint·Domain DB·Trace·Audit에 복제하지 않는다. Release Graph의 READ는 고정된 IN Route를 사용하는 Retrieval만 소유한다. Tool Route는 의미 Route 후보 뒤에 결정적 Policy Precondition Resolver를 적용해 `TASK + CREATE`의 기존 미완료 Task 중복 검사와 `CALENDAR + CREATE`의 Event/FreeBusy 충돌 검사에 필요한 IN READ를 보강한다. 이는 두 번째 Tool 선택이 아니며 OUT Tool을 변경하지 않는다. 단 사용자 지정 Source·기간·Resource 범위를 벗어나는 필수 READ는 `SCOPE_EXPANSION_REQUIRED` Confirmation 전에는 materialize하거나 실행하지 않는다. 실제 사용자 응답을 검증한 Application/Confirmation Controller만 `PolicyConfirmationReceiptV1`을 만들 수 있고 Agent/LLM은 Receipt를 생성할 수 없다. 사용자가 범위 확장을 거절하면 필수 검사를 생략한 Write로 진행하지 않는다. Write/Action Tool Arguments는 Planning LLM이 이미 고정된 OUT Tool Schema 안에서 작성하고 결정적 코드가 검증·조립하며, Tool identity는 Output Route에서 결정적 Assembler가 복사한다. Planning LLM은 Tool을 다시 선택하지 않는다.
- Prompt는 Agent별 단일 문자열이 아니라 Node·상태·목적별 `PromptRef`로 선택한다.
- Prompt·Completion 원문은 Graph State·일반 Trace·Audit에 저장하지 않는다.
- Product Runtime Prompt 문구는 `grader`, `gold`, `expected_route`, 평가 점수에 의존하지 않는다. 실험 Grader가 발견한 오류도 Runtime과 동일한 `failure_record` 형태로 투영한 뒤 Prompt에 전달한다.
- Structured Output Schema Repair는 Node Call당 최대 1회다.
- Product LLM Call hard cap은 Run당 24다. `NORMAL` Profile은 최대 14, `RETRIEVAL_HEAVY`는 최대 20, `REVISION_HEAVY`는 최대 18 호출을 허용한다. Profile budget을 맞추기 위해 서로 다른 semantic responsibility를 다시 거대 Prompt로 합치지 않는다.
- 최초 Retrieval 이후 Additional Retrieval은 최대 2회다.
- Planning Revision은 Run당 최대 2회다.
- 실행·검증·승인·정책 최종 판정에는 LLM Prompt를 사용하지 않는다.
- `UNKNOWN_RESULT`에서는 새 Write Attempt를 만들지 않는다.

### 1.2 Concern Authority 적용

문서 번호를 하나의 global priority chain으로 해석하지 않는다. 충돌은 `01 PRD §1.1` / Project Source Guide의 **Concern Owner 규칙**으로 해소한다.

```
제품 목표·범위            → 01 PRD
안전·금지·승인 정책       → 01-B Policy
시스템·레이어 경계         → 03 Architecture
Domain lifecycle semantics → Domain State Transition Contract
Domain persistence/DB      → 04 Domain·DB + 04 Domain·DB required DB invariant contract
Retrieval                  → 05 Context·Retrieval
Agent·Workflow runtime     → 06 Agent·Workflow
Tool·MCP·내부 Interface   → 07 Interface
Prompt·Failure             → 본 문서 15
```

`11 Observability`는 관측 계약, `12 Test`는 제품 회귀 검증, `13 Evaluation`은 후보 비교·실험을 소유하며 위 behavioral/runtime 의미를 재정의하지 않는다. 개별 Prompt·Dataset Artifact도 해당 owner 계약을 따라야 한다. 본 계약은 다른 Concern Owner의 안전·승인·Domain·Tool·Workflow 의미를 완화하거나 대체할 수 없다.

---

### 1.3 Agent Subgraph 공통 계약

본 문서에서 **Agent**는 단순 Prompt 호출이나 Python 객체 수가 아니라, Main Supervisor가 호출하는 LangGraph Subgraph를 뜻한다.

필수 속성:

- 안정적인 `agent_role` 책임 계약
- Parent State에서 필요한 입력만 받는 Input Projection
- invocation 범위 Subgraph별 Typed Local State
- PromptRef 기반 LLM Node
- 역할상 필요한 결정적 Validation·Read Application Node
- Schema Validation과 허용된 bounded Repair/Revision
- Versioned Typed Result + disposition + 필요한 Typed Workflow Signal 반환
- Agent→Agent 직접 호출 금지
- 장기 Memory 금지

Prompt Slot 수, PromptRef 수, LLM Call 수는 Agent 수와 독립적이다. 같은 Agent 안의 `INITIAL`, `CLARIFY`, `SCHEMA_REPAIR`, `SEMANTIC_REVISION`, `RECHECK`는 하나의 책임 계약을 보조하는 Prompt variant다.

**Atomic responsibility rule:** Local SLLM 기본 Profile에서는 서로 다른 semantic 판단을 한 Product LLM 호출로 fuse하지 않는다. Canonical atomic responsibilities는 최소 다음처럼 분리한다.

```
Work Analysis:
  extract_work_facts
  resolve_entity_relations                   # conditional
  resolve_temporal_dependencies              # conditional
  detect_duplicate_conflict_candidates       # conditional
  validate_relations                         # deterministic
  assess_information_gaps
  assess_operational_risks                   # conditional
  assemble_work_analysis                     # deterministic
  validate_work_analysis                     # deterministic

Planning shared:
  choose_answer_or_action_from_route          # deterministic

Planning ANSWER:
  outline_answer
  compose_answer

Planning ACTION (per frozen OutputToolRouteV1):
  draft_action_objective_per_output_route
  compose_arguments_per_output_route
  build_dependencies                         # deterministic
  assemble_plan                              # deterministic
  validate_plan                              # deterministic

Review:
  inspect_goal_and_evidence
  inspect_action_scope_and_route             # ACTION only
  inspect_constraints_and_policy_summary     # conditional
  aggregate_review_findings                  # deterministic
  validate_review                            # deterministic
  recheck_affected_dimensions                # conditional, REVISE only
```

더 강한 Runtime에서 인접 LLM Node를 fuse하는 것은 허용할 수 있으나, fused call이 위 atomic candidate들의 Typed Output 의미를 모두 재현하고 `12 Test / 13 Evaluation`의 parity·failure-isolation gate를 통과해야 한다. Fusion은 Agent 책임 경계를 바꾸거나 Tool/Policy/Domain authority를 LLM에 추가하는 근거가 아니다.

공통 Runtime Envelope는 invocation metadata와 failure/repair counter만 보존한다. 업무 데이터는 Subgraph별 Typed Local State에 둔다. Local candidate·Query candidate·RAG score·Prompt 원문은 invocation 종료 후 다른 Agent 호출로 자동 승계하지 않는다. 제품의 장기 사실과 승인·실행·검증은 Main Graph Typed State와 Domain Store 계약을 따른다.

각 Node는 Parent/Main State 전체를 받지 않고 자기 작업에 필요한 Typed Projection만 받는다. **Conversation history나 previous-run artifact는 이 Projection의 암묵적 공통 필드가 아니다.** `conversation_id`는 Trace/상관관계 식별에 사용할 수 있지만 과거 Message 또는 이전 Run State를 Product Prompt에 직렬화할 권한을 만들지 않는다. 공식 Main State Artifact는 단일 Owner만 새 revision을 만들며 downstream은 upstream Artifact를 read-only로 소비한다. Subgraph 반환은 owner field와 허용된 workflow signal만 patch merge하고 다른 Main State field를 `None` 또는 누락 값으로 초기화하지 않는다. **Confirmation으로 재개된 invocation에 한해**, Confirmation Controller가 검증·정규화한 `ConfirmationResponseProjectionV1`을 `confirmation_response`라는 optional Root Field로 **originating owner의 해당 Product Prompt에만** 추가할 수 있다. Raw resume payload, `interrupt_id`, checkpoint metadata, `RegisteredResumeTargetRefV2`은 Product Prompt 입력이 아니다. 다른 Agent 호출로 이 응답을 자동 승계하지 않는다. 응답이 upstream Intent 의미를 바꿔야 하면 현재 owner가 Typed Back-edge를 반환하고, Prompt가 다른 Agent 책임을 직접 수행하지 않는다. 예를 들어 Retrieval **초기 Round** Query Planner는 `request_intent + input_routes + retrieval_budget`만 받고, follow-up Round에서는 여기에 `current_round_no + prior QueryAttemptV1 + unresolved SufficiencyIssueV2 + bounded read-result summary`만 추가로 받을 수 있다. Retrieval Product Prompt는 raw `user_request`를 별도 권위 입력으로 재주입하지 않는다. Raw Page Token·Provider-native Query·RFC3339·MCP Arguments는 어느 Round의 Product Prompt에도 전달하지 않는다. Evidence Selector는 `request_intent + ranked_segments`만 받는다. Work Analysis atomic node는 각자 필요한 최소 Projection만 받으며 facts/entity-relations/temporal-dependencies/duplicate-conflict-candidates/gaps/risks를 한 번에 요구하지 않는다. Planning `draft_action_objective_per_output_route`는 `user_request + OutputToolRouteV1 1개 + optional work_analysis + evidence_refs`를 받고 Tool Schema serialization을 하지 않는다. `compose_arguments_per_output_route`는 같은 frozen Output Route + validated action objective + 해당 Tool Schema만 받아 Arguments 표현만 작성한다.

외부 READ는 Retrieval Subgraph의 결정적 Application Node가 `connector_id`에 맞는 Query Builder와 `ConnectorReadPort`를 호출한다. Retrieval LLM Node는 Raw Query·MCP Arguments를 직접 실행하지 않으며 `ToolRoutePlanV2.input_plan.input_routes` 밖의 Tool을 선택하거나 호출하지 않는다. Release Retrieval planner output은 `05 Retrieval`의 current `RetrievalQueryPlanV2 / RouteQueryIntentV2`를 사용한다. `SEARCH`에서는 Provider query 대신 typed `SemanticRetrievalConstraintV1`을 출력하고, follow-up changed SEARCH는 값이 포함된 `ConstraintDeltaV2`를 반환해야 한다. constraint 이름만 있는 delta, Provider-native Query 문자열, raw continuation, MCP Arguments를 planner authority로 반환하면 contract invalid다. 결정적 `SourceFetchPlanBuilder`만 prior effective constraints와 delta를 merge하고 `SourceFetchPlanV1` 및 query identity를 materialize한다.

Graph Profile 간 semantic responsibility parity를 유지한다. 특히 `SINGLE_BASELINE`은 별도 Review Agent를 두지 않더라도 Unified Agent 내부 `self_review` 단계로 계획 품질 점검 책임을 수행한다.

### 1.4 Local SLLM Responsibility·Complexity 계약

P0 Local current comparison baseline은 `qwen2.5:7b`다. 방향 승인 후보는 Signed Local Model Profile `WORKER=qwen3.5:4b`, `REASONING=qwen3.5:9b`이며 13 Gate/Release 서명 전에는 active product binding이 아니다. 모델 크기를 이유로 업무 의미를 heuristic으로 삭제하거나 등록 Tool을 임의 shortlist하지 않는다. 대신 각 LLM Node가 한 번에 해결해야 하는 **semantic branching과 Output Schema 복잡도**를 작게 유지하고, 실제 허용 한계는 Model·Runtime별 Contract Complexity Gate에서 측정한다.

설계 원칙:

- LLM Node는 원칙적으로 하나의 의미 판단 또는 하나의 구조화 작성 책임을 가진다. 서로 다른 의미 판단을 하나의 거대 Schema에 합치지 않는다.
- 안정적으로 닫을 수 있는 값은 `Literal`/Enum/discriminated union을 사용하고 자유 `dict` 출력은 금지한다.
- 같은 의미를 `status + requires_confirmation + blockers`처럼 여러 상호의존 필드에 중복 표현하지 않는다. 한 discriminator가 유효 branch를 결정하게 한다.
- 날짜 계산, interval 교집합·차집합, Registry eligibility, Policy Precondition Read 보강, 실제 사용자 Confirmation→`PolicyConfirmationReceiptV1` 생성/Context Hash 검증, 중복·충돌 relation 검증, state freshness, DAG cycle, Policy·Approval·Verification은 deterministic code가 소유한다.
- Tool Route에서 signed Registry 전체를 정보 손실 없이 사용할 수 있으나 LLM에는 현재 판단에 필요한 eligible candidate projection만 전달한다. Eligibility filtering은 Resource·Effect·Schema 적합성의 결정적 규칙이어야 하며 모델 부담 감소만을 이유로 의미 가능한 Tool을 제거하지 않는다.
- Planning Argument Writer는 `OutputToolRouteV1` 하나와 해당 Tool Schema 하나를 소비한다. 여러 Output Route의 Arguments를 하나의 LLM Schema로 동시에 생성하지 않는다.
- 다중 Action Dependency의 생성·정규화·cycle 검증은 deterministic Planning Application Node가 소유한다. Product Runtime에는 `planning.compose_dependencies` PromptRef를 추가하지 않는다. Active PromptRef 수를 유지하기 위해 atomic responsibility를 합치지 않는다. P0에서는 Business Arguments에 이미 존재하는 안정적 외부 Resource identity가 같은 Action만 frozen route 순서에 따라 연결하고, CREATE나 서로 다른 Resource에 dependency를 추정하지 않는다.
- Structured/Constrained Output은 문법 유효성을 높이는 수단이며 의미 정답을 보장하지 않는다. Schema Validator와 Semantic Validator의 책임을 분리한다.
- Tool Calling과 별도 JSON Schema constrained decoding을 동시에 사용하는 Runtime 조합은 독립 Candidate로 검증한 뒤 채택한다. 한쪽 Contract Gate 성공을 다른 조합의 성공으로 간주하지 않는다.

각 LLM Node는 최소 다음 Complexity Metadata를 실험에 노출한다.

```
schema_required_field_count
schema_optional_field_count
schema_max_depth
schema_union_branch_count
schema_max_enum_cardinality
tool_candidate_count
input_projection_estimated_tokens
output_token_budget
```

이 값에 대한 **전역 고정 상한은 문서에 선험적으로 두지 않는다.** `13 Evaluation`의 Complexity Sweep에서 Node·Model·Runtime별 안정 구간을 찾고, Release Candidate Config가 그 측정 범위를 벗어나면 새 Contract Gate를 요구한다.

Local Node Contract Stability의 기본 Gate는 적용 Case N=50에서 `final_contract_valid >= 49/50`, uncaught exception 0, repair budget 초과 0이며, 의미 품질은 별도 Gold/Node Accuracy Gate에서 판정한다. Contract Gate 통과는 업무 정답을 의미하지 않는다.

### 1.5 Evaluation isolation reference

Product Prompt와 Runtime failure/retry contract는 평가 Harness의 Gold·Grader·Simulator·Candidate metadata를 입력 authority로 사용하지 않는다. 구체적인 Evaluation artifact와 Simulator/feedback isolation 규칙은 `13 Evaluation`이 소유하고, 본 문서 §12는 Runtime이 허용하는 소비 경계만 정의한다.

### 1.6 Runtime fixed values

```yaml
llm_budget_policy: ROUTE_PROFILE
normal_max_llm_calls: 14
retrieval_heavy_max_llm_calls: 20
revision_heavy_max_llm_calls: 18
absolute_max_llm_calls: 24
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

### 1.7 Responsibility-Split Prompt Topology

목표는 LLM authority를 늘리는 것이 아니라 **한 LLM 호출이 담당하는 semantic responsibility를 줄이는 것**이다. 6개 `SemanticAgentOwnerIdV1` 책임 경계는 유지하되, physical compiled Agent Subgraph 수는 selected Graph Profile의 1/3/6 exact binding을 따른다.

### Work Analysis LLM split

Work Analysis는 사람·업무·시간·dependency·duplicate/conflict 판단을 atomic responsibility로 분리한다.

```
work_analysis.extract_work_facts                         LLM
work_analysis.resolve_entity_relations                    LLM/conditional
work_analysis.resolve_temporal_dependencies               LLM/conditional
work_analysis.detect_duplicate_conflict_candidates        LLM/conditional
work_analysis.validate_relations                          deterministic
work_analysis.assess_information_gaps                     LLM
work_analysis.assess_operational_risks                    LLM/conditional
work_analysis.assemble_work_analysis                      deterministic
work_analysis.validate_work_analysis                      deterministic
```

- `resolve_entity_relations`: 사람·업무·Resource identity·ownership/reference 관계만 소유한다.
- `resolve_temporal_dependencies`: 날짜·기간·선후·dependency 후보만 소유한다.
- `detect_duplicate_conflict_candidates`: duplicate/conflict **candidate**만 제안한다.
- 실제 `DUPLICATES | CONFLICTS_WITH` 확정은 deterministic relation validator가 계속 소유한다.

### Review LLM split

Review는 goal/evidence/action/route/constraint/policy 검사를 atomic inspector responsibility로 분리한다.

```
review.inspect_goal_and_evidence               LLM
review.inspect_action_scope_and_route           LLM/conditional, ACTION only
review.inspect_constraints_and_policy_summary  LLM
review.aggregate_review_findings               deterministic
review.validate_review                          deterministic
review.recheck_affected_dimensions              LLM/conditional
```

- `inspect_goal_and_evidence`: goal fit, evidence adequacy, unsupported claim/contradiction만 검사한다.
- `inspect_action_scope_and_route`: action necessity, frozen Tool Route consistency, scope expansion만 검사한다.
- `inspect_constraints_and_policy_summary`: user constraints + supplied policy summary만 검사한다. 새 정책을 생성하지 않는다.
- 세 inspector는 `06 Workflow`의 `ReviewInspectorResultV1` typed intermediate만 반환한다. free-form dimension/object를 반환하지 않으며 `ReviewDimensionIdV1` closed set 밖 값은 deterministic validator가 거절한다.
- `aggregate_review_findings`가 typed finding을 deterministic precedence로 합성해 최종 Review disposition을 만든다. LLM finding category 자체가 routing authority가 아니다.
- Revision 후에는 `affected_dimensions`만 재검사하며 dimension-only issue는 action/route identity 없이 보존한다.

### Prompt slot accounting

Current required PromptRef 집합은 아래 current LLM responsibilities에서 파생한다. Active Slot 수를 별도 설계 상수로 두지 않으며 manifest/source/caller/input-contract exact-set equality로 계산한다.

새 Active PromptRef:

```
work_analysis.resolve_entity_relations
work_analysis.resolve_temporal_dependencies
work_analysis.detect_duplicate_conflict_candidates
review.inspect_goal_and_evidence
review.inspect_action_scope_and_route
review.inspect_constraints_and_policy_summary
review.recheck_affected_dimensions
```

Current runtime에서 사용하지 않는 broad predecessor PromptRef:

```
work_analysis.resolve_relations
review.inspect
review.recheck
```

Current PromptRef 집합은 broad predecessor ID의 수를 보존하기 위해 만들지 않는다. 각 current LLM responsibility에 실제 caller가 존재하는 PromptRef만 manifest/source/input-contract에 포함한다.

### Safety boundary

- Subgraph 간 authority는 바뀌지 않는다.
- Tool Route, Approval, Claim, external WRITE, Verification, Recovery authority는 바뀌지 않는다.
- LLM 결과는 candidate/finding일 뿐 Domain mutation이나 routing authority가 아니다.
- DEV → Holdout → Safety Gate 전에는 current Prompt manifest를 Runtime Active로 승격하지 않는다.

### Planning ACTION Responsibility Split

Planning ACTION은 frozen Output Route별로 다음 책임을 분리한다.

```
planning.draft_action_objective_per_output_route    LLM
planning.compose_arguments_per_output_route         LLM/tool-schema
planning.build_dependencies                         deterministic
planning.assemble_plan                              deterministic
planning.validate_plan                              deterministic
```

`draft_action_objective_per_output_route`는 사용자 목표와 frozen Output Route의 target semantics만 작성한다. Tool identity/effect/arguments를 변경하지 않는다. `compose_arguments_per_output_route`는 확정 objective와 selected Tool Schema를 받아 business arguments만 직렬화한다. dependency 생성은 계속 deterministic authority다.

## 2. Agent Registry

| Agent Role | 주 책임 | 주요 입력 | 주요 출력 | 금지 |
| --- | --- | --- | --- | --- |
| `request_understanding` | 목표·완료 조건·제약·모호성 구조화 | 사용자 요청, Entry Mode, 선택 Resource | `RequestIntent` | Connector 조회, Action 생성 |
| `tool_route` | IN Resource/Read Tool 범위와 OUT Resource/Effect/Tool 확정 | `RequestIntentV2`, Signed Tool Registry | `ToolRoutePlanV2` | Query 작성, Evidence 판단, Arguments 작성 |
| `retrieval` | 고정 IN Route에서 Query·Read·RAG·Evidence·Sufficiency | `RequestIntentV2`, frozen `input_routes`, Retrieval Budget | `RetrievalResultV1` | OUT Tool 변경, Write, Tool 종류 재선택 |
| `work_analysis` | 필요한 경우 업무 사실·관계·누락·중복·충돌·일정 위험 분석. LLM은 관계 후보를 제안할 수 있으나 `DUPLICATES`·`CONFLICTS_WITH`와 그에 따른 no-action 판단은 결정적 relation validator 검증을 거친다. 정확 중복의 추가 생성이나 검증된 일정 충돌 Override는 각각 `DUPLICATE_OVERRIDE_REQUIRED` / `CONFLICT_OVERRIDE_REQUIRED` 2차 Confirmation을 요구하며 승인 후 결과는 현재 Context에 유효한 Receipt ref를 포함한다. | User Request, Intent, optional Evidence | `WorkAnalysisResultV2` 또는 Work Analysis 소유 Confirmation signal | 정책 최종 판정, 실행, LLM 단독 중복·충돌 확정, Confirmation 없는 Override |
| `planning` | 고정 OUT Route의 Answer/Arguments·Dependency 작성 | User Request, Intent, `OutputPlanV1`, optional Analysis, Evidence | `AnswerDraftV2` 또는 `ActionPlanDraftV2` | Tool 재선택, 승인, 실행 |
| `review` | 목표 충족·Evidence·과잉 Action·모순·Route 오류 검토 | Plan Draft, Evidence, Policy Summary | `PlanReviewResultV2` | Route 직접 변경, 실행 허용 최종 판정 |

---

## 3. Capability 분류 축

서로 다른 개념을 한 Enum에 섞지 않는다.

### 3.1 입력 조건 `input_condition`

```
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

```
NONE
SCHEMA_INVALID
SEMANTIC_INVALID
```

### 3.3 복구 처분 `recovery_disposition`

```
RETRYABLE
REDIRECT
DETERMINISTIC
TERMINAL
NOT_AVAILABLE
```

### 3.4 실패 감지 주체 `detected_by`

```
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

```
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

| Code | 기본 Runtime 처리 |
| --- | --- |
| `SCHEMA_INVALID_JSON` | `SCHEMA_REPAIR` |
| `SCHEMA_REQUIRED_FIELD_MISSING` | `SCHEMA_REPAIR` |
| `SCHEMA_INVALID_ENUM` | `SCHEMA_REPAIR` |
| `SCHEMA_WRONG_TYPE` | `SCHEMA_REPAIR` |
| `SCHEMA_UNSUPPORTED_FIELD` | `SCHEMA_REPAIR` |
| `SCHEMA_VERSION_MISMATCH` | 호출 중단 또는 Schema Repair 1회 |

추가 Local SLLM 운영 실패 코드는 다음을 사용한다.

```
SLLM_SCHEMA_COMPLEXITY_OUT_OF_PROFILE
SLLM_PROJECTION_BUDGET_EXCEEDED
SLLM_TOOL_CANDIDATE_AMBIGUITY
```

이 코드는 모델이 작다는 이유만으로 발생시키지 않는다. 승인된 Candidate Config의 측정 Complexity Profile을 벗어났거나 Contract Gate에서 해당 복잡도 구간의 안정성이 입증되지 않았을 때 실험·배포 Gate에서 사용한다.

### 6.2 요청 이해 실패

```
INTENT_GOAL_MISSING
INTENT_COMPLETION_CRITERIA_MISSING
INTENT_CONSTRAINT_MISSING
INTENT_ENTRY_MODE_WRONG
INTENT_AMBIGUITY_MISSED
INTENT_OVER_CONFIRMATION
INTENT_UNSUPPORTED_SCOPE
```

### 6.3 Tool Route 실패

```
TOOL_ROUTE_REQUIRED_INPUT_MISSING
TOOL_ROUTE_FORBIDDEN_INPUT_INCLUDED
TOOL_ROUTE_REQUIRED_OUTPUT_MISSING
TOOL_ROUTE_FORBIDDEN_OUTPUT_INCLUDED
TOOL_ROUTE_UNREGISTERED_TOOL
TOOL_ROUTE_EFFECT_MISMATCH
TOOL_ROUTE_OUTPUT_MODE_WRONG
TOOL_ROUTE_READ_IN_OUTPUT
TOOL_ROUTE_OVERCONFIRMATION
SLLM_TOOL_CANDIDATE_AMBIGUITY
```

### 6.4 Retrieval·Query·RAG 실패

```
RETRIEVAL_ROUTE_SCOPE_VIOLATION
QUERY_USER_CONSTRAINT_MISSING
QUERY_TOO_BROAD
QUERY_TOO_NARROW
QUERY_UNCHANGED_AFTER_FAILURE
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

```
ANALYSIS_UNSUPPORTED_INFERENCE
ANALYSIS_RELATION_MISSING
ANALYSIS_CONFLICT_MISHANDLED
ANALYSIS_DUPLICATE_MISCLASSIFIED
ANALYSIS_SCHEDULE_RISK_MISCLASSIFIED
ANALYSIS_NEEDS_MORE_DATA_MISSED
```

### 6.6 Planning 실패

```
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

```
REVIEW_FALSE_PASS
REVIEW_FALSE_BLOCK
REVIEW_ROUTE_RECONSIDERATION_MISSED
REVIEW_ERROR_NOT_LOCALIZED
REVIEW_REPEATED_SAME_FAILURE
```

### 6.8 비-LLM 실패

다음은 Prompt로 복구하지 않는다. 비-LLM 실패는 **소유 Concern의 canonical code/state를 그대로 보존**하며, 본 문서가 Provider별 별도 공통 Error Enum을 만들지 않는다.

Connector/MCP 실패는 `07 Interface`의 Error Enum을 사용한다.

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
```

`AUTH_EXPIRED`는 Workflow/Domain에서 필요한 경우 `REAUTH_REQUIRED` 흐름으로 조정한다. `UNKNOWN_RESULT`는 Connector 오류 코드가 아니라 `04 Domain`의 실행 결과 불명 상태이며 새 Write Attempt를 만들지 않는다. Provider-specific `GOOGLE_READ_*` / `GOOGLE_WRITE_*` 이름은 공통 `failure_reason_code` 권위를 갖지 않는다.

그 밖의 비-LLM failure/운영 코드는 해당 owner 계약을 따른다.

```
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
| --- | --- | --- |
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

```
Schema Repair: Node Call당 최대 1회
Semantic Revision: 동일 Node·동일 Failure Signature당 최대 1회
Planning Revision: Run당 최대 2회
Review Recheck: 각 Planning Revision 결과마다 최대 1회
Additional Retrieval: 최초 Retrieval 이후 최대 2회
```

### 8.2 Route별 LLM 호출 Budget Profile

현재 확정 Route Profile Budget을 적용한다.

```
NORMAL_MAX_LLM_CALLS=14
RETRIEVAL_HEAVY_MAX_LLM_CALLS=20
REVISION_HEAVY_MAX_LLM_CALLS=18
ABSOLUTE_MAX_LLM_CALLS=24
```

- 기본 Profile은 `NORMAL`이다.
- `RETRIEVAL_HEAVY`는 `NEEDS_MORE_DATA` 또는 Additional Retrieval이 실제 발생한 경우에만 선택한다.
- `REVISION_HEAVY`는 Review가 `REVISE`를 반환하고 Domain과 deterministic Policy가 Revision을 허용한 경우에만 선택한다.
- Profile 승격은 Supervisor의 결정적 규칙으로 수행한다.
- `ABSOLUTE_MAX_LLM_CALLS`를 넘으면 Prompt를 더 호출하지 않는다.

### 8.3 Budget 소진 처리

Budget 소진을 `COMPLETED`로 숨기지 않는다.

```
result_kind: PARTIAL
또는
run_status: WAITING_CONFIRMATION | BLOCKED | FAILED | RECOVERY_REQUIRED
```

---

## 9. Prompt Registry Contract

### 9.0 Current runtime gate

- Current Prompt Runtime은 `06 Workflow`의 current LLM responsibility와 이 문서의 PromptRef contract에서 파생한다.
- Runtime 활성화 전 required PromptRef / caller / manifest / source / assembled / input-contract exact-set equality와 DEV → Holdout → Safety Gate를 통과해야 한다.
- Prompt Slot 숫자나 non-current candidate identity는 topology authority가 아니며, Product Prompt assembler는 current slot allowlist만 직렬화한다. Evaluation Projection 전체를 Prompt Input으로 전달하지 않는다.

### 9.1 Prompt Runtime Slot 선택 Key

```
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

```
INITIAL
CLARIFY
ASSESS
SCHEMA_REPAIR
SEMANTIC_REVISION
RECHECK
```

`WORKFLOW_REDIRECTION`, `DETERMINISTIC_RETRY`, `DETERMINISTIC_RECOVERY`에는 PromptRef가 없어야 한다.

### 9.3-A Current PromptRef exact-set identity

Current Prompt Runtime의 exact-set equality는 **`prompt_slot_id`를 set identity key로 사용**한다. `prompt_version`, `content_hash`, `activation_status`, per-invocation `failure_reason_code`는 같은 slot의 release/runtime metadata이며 별도 PromptRef set cardinality를 만들지 않는다. `SCHEMA_REPAIR`·`SEMANTIC_REVISION`은 별도 전체 Prompt source를 복제하지 않고 같은 Base Slot에 Failure/Allowed-Change block을 조립한다.

Current required Product-LLM Prompt Slot set은 정확히 아래 21개다. 각 current slot에서 `prompt_id == prompt_slot_id`이며 broad predecessor ID를 alias로 유지하지 않는다.

```text
request_understanding.identify_goal
request_understanding.detect_ambiguity
tool_routing.determine_io_resources
tool_routing.select_tool_if_needed
retrieval.plan_query
retrieval.select_evidence
retrieval.assess_sufficiency
work_analysis.extract_work_facts
work_analysis.resolve_entity_relations
work_analysis.resolve_temporal_dependencies
work_analysis.detect_duplicate_conflict_candidates
work_analysis.assess_information_gaps
work_analysis.assess_operational_risks
planning.outline_answer
planning.compose_answer
planning.draft_action_objective_per_output_route
planning.compose_arguments_per_output_route
review.inspect_goal_and_evidence
review.inspect_action_scope_and_route
review.inspect_constraints_and_policy_summary
review.recheck_affected_dimensions
```

Current runtime caller mapping은 06의 Node Registry를 그대로 소비한다.

```text
request.identify_goal                           → request_understanding.identify_goal
request.detect_ambiguity                        → request_understanding.detect_ambiguity
route.determine_resources                       → tool_routing.determine_io_resources
route.select_tool                               → tool_routing.select_tool_if_needed
retrieval.plan_query                            → retrieval.plan_query
retrieval.select_evidence                       → retrieval.select_evidence
retrieval.assess_sufficiency                    → retrieval.assess_sufficiency
analysis.extract_facts                          → work_analysis.extract_work_facts
analysis.resolve_entity_relations               → work_analysis.resolve_entity_relations
analysis.resolve_temporal_dependencies          → work_analysis.resolve_temporal_dependencies
analysis.detect_duplicate_conflict_candidates   → work_analysis.detect_duplicate_conflict_candidates
analysis.assess_information_gaps                → work_analysis.assess_information_gaps
analysis.assess_operational_risks               → work_analysis.assess_operational_risks
planning.outline_answer                         → planning.outline_answer
planning.compose_answer                         → planning.compose_answer
planning.draft_action_objective_per_output_route→ planning.draft_action_objective_per_output_route
planning.compose_arguments_per_output_route     → planning.compose_arguments_per_output_route
review.inspect_goal_and_evidence                → review.inspect_goal_and_evidence
review.inspect_action_scope_route               → review.inspect_action_scope_and_route
review.inspect_constraints_policy               → review.inspect_constraints_and_policy_summary
review.recheck                                  → review.recheck_affected_dimensions
```

`prompt_version`은 current manifest가 slot별로 선택하는 version identity이고, `content_hash`는 9.4 조립 규칙으로 materialize된 immutable prompt artifact의 SHA-256이다. `activation_status`는 9.5/13 Evaluation Gate가 승격한다. 이 세 값의 **구체 Release 값은 canonical prompt source identity가 아니며** repository/source filename set을 늘리지 않는다. Current manifest는 각 required slot에 정확히 하나의 selected current version row를 가져야 한다.

`prompt-runtime-input-contract-v1`은 위 21개 `prompt_slot_id`와 exact-set equality를 이루며, 각 row가 06/15가 허용한 current Typed Projection의 `input_schema_version`, allowlisted root fields, output schema version을 참조한다. Conversation history, previous-run artifact, raw Provider/MCP continuation, Gold/Grader metadata를 새 field로 추가할 수 없다. Repository path/loader/test realization은 16 Repository Architecture가 소유한다.

Current input-contract artifact의 logical schema는 다음으로 닫는다.

```yaml
prompt_runtime_input_contract:
  schema_version: 1
  entries:
    - prompt_slot_id: string
      runtime_node_id: string
      input_schema_version: integer
      required_root_fields: [string]
      optional_root_fields: [string]
      output_schema_version: integer
```

`entries[].prompt_slot_id`는 위 21개 exact set과 같고 `runtime_node_id`는 위 caller mapping과 exact match한다. Field allowlist의 semantic 내용은 06/15 current projection contract를 소비하며, 이 JSON artifact가 새로운 Product Prompt 입력 field를 발명할 수 없다.

### 9.4 조립 규칙

```
Base Role Contract
+ Node Purpose Instruction
+ Failure-specific Instruction Block(optional)
+ Allowed Change Scope
+ Output Schema
```

실패 원인별 Prompt 전체 복제를 금지한다. Base와 Failure Block을 조립하고 최종 조립 결과의 Hash를 기록한다.

### 9.5 Runtime 활성화 Gate

사용자 결정 `4-A`를 적용한다.

```
DRAFT
→ Node DEV 통과
→ Node HOLDOUT 통과
→ Safety Gate 통과
→ Prompt Manifest 승인
→ RUNTIME_ACTIVE
```

검증되지 않은 Prompt는 Artifact로 존재할 수 있으나 Runtime에서 선택할 수 없다.

### 9.5 Prompt execution scope와 release evidence

Prompt 실행 Scope는 다음 closed vocabulary만 사용한다.

- `PRODUCT_RELEASE`: `SIGNED_RELEASE_MANIFEST` composition만 선택한다. 모든 current Slot이 `RUNTIME_ACTIVE`이고 DEV·HOLDOUT·Safety·Manifest Approval flag와 immutable evidence metadata가 완전해야 한다. `DRAFT`, `DEV_VALIDATED`, `HOLDOUT_VALIDATED`, `RETIRED`는 신규 실행을 fail closed한다. 환경 변수로 이 Scope를 변경할 수 없다.
- `DEVELOPMENT_SMOKE`: `EXPLICIT_DEVELOPMENT` composition만 선택한다. 실험 전 `DRAFT` baseline의 실제 Product workflow smoke를 허용하지만 release activation이나 Prompt 품질 통과를 뜻하지 않는다. Readiness는 `UNVALIDATED_BASELINE`을 명시한다. `RETIRED`는 신규 실행할 수 없다.
- `EVALUATION`: offline candidate evaluation 전용이다. Product user runtime과 분리하고 Gold·Grader·expected output·evaluation identity를 Product Prompt input에 넣지 않는다.

`RUNTIME_ACTIVE`/`RETIRED` entry의 activation evidence metadata는 target model identity와 artifact hash, Prompt source hash, input/output schema version, Dataset artifact path/hash, Grader artifact path/hash/version, 실행 UTC timestamp, Node DEV/HOLDOUT/Safety 결과 artifact path/hash, Manifest Approval artifact path/hash를 포함한다. 모든 path는 Prompt bundle 내부 상대 경로이며 manifest가 고정한 SHA-256과 실제 bytes가 일치해야 한다. Flag나 status 문자열만으로 release evidence를 주장할 수 없다. Signed Release bundle은 21개 exact Slot의 source hash와 이 evidence chain을 packaging 전에 검증한다.

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

`QueryAttemptV1`의 **필드·enum·schema_version·identity authority는 05 Retrieval §16 하나만 소유**한다. 이 문서는 Prompt/Failure consumer로서 그 타입을 복제하지 않는다. Retrieval Prompt/validator가 참조할 수 있는 값은 05의 current `QueryAttemptV1` bounded projection뿐이며 Provider-native query/token/raw response는 포함하지 않는다.

### 11.1 반복 검색 판정

- `NEXT_PAGE`는 05의 `read_result_handle + page_state_hash`가 새 continuation 상태를 증명할 때만 정상 round다.
- 실패 후 merge/normalize된 effective constraints와 page state가 prior attempt와 동일한 `SEARCH`는 canonical failure code `QUERY_UNCHANGED_AFTER_FAILURE`이며 Provider 호출과 round 증가가 모두 0이다.
- `DETAIL_FETCH` 중복 판정은 05의 current Run Retrieval Cache + bounded candidate reference를 사용한다. Query 변경 여부와 Pagination 여부를 하나의 hash로 합치지 않는다.

### 11.2 사용자 의도·Confidence 소비

- 사용자 날짜·사람·Resource constraint 반영 판정은 `QueryAttemptV1.normalized_intent_constraints + query_spec`를 05 semantics 그대로 읽는다.
- `confidence_band`는 `HIGH | MEDIUM | LOW | NONE`; Threshold 값은 중앙 Retrieval Config authority가 소유한다.
- 이 문서의 legacy `retrieval_round/source/entry_mode/query_hash/page_token_hash/selected_candidate_ids` 형태는 Release schema가 아니며 새 코드·Prompt·Trace 계약에 사용하지 않는다.

---

## 12. Evaluation consumption boundary

`13 Evaluation`은 본 문서의 current Runtime contract를 **read-only evaluation input contract**로 소비한다. Evaluation artifact가 새로운 Product Prompt field, failure code, retry path, Agent capability, Tool/Policy/Domain authority를 정의할 수 없다.

허용되는 Runtime reference는 06의 current node/owner identity, `FailureReasonRecordV1`, `retry_kind`, PromptRef/manifest/input contract, `QueryAttemptV1`, result/status vocabulary, bounded repair/revision budget과 allowed change scope다. Dataset·Gold·Grader·Simulator·Candidate promotion의 schema와 절차는 13에만 둔다.

## 13. Agent별 Capability Coverage

### 13.1 요청 이해

```
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

### 13.2 Tool Route

```
단일·복수 IN Route
단일·복수 OUT Route
ANSWER vs ACTION
RESOURCE_SELECTED Resource 고정
READ / CREATE / UPDATE / SEND / DELETE Effect
Registered Tool Binding
후보 1개 deterministic auto-select
후보 복수 registered-candidate selection
Forbidden Route·Tool 배제
Unregistered Tool 0
Resource·Effect·Tool Schema 일치
NEEDS_CONFIRMATION
BLOCKED
```

### 13.3 Retrieval

```
고정 IN Route 안 Query 계획
allowed_read_tool_ids 밖 호출 0
RESOURCE_SELECTED 직접 GET
날짜·사람·이메일·상태 제약
Query 과대·과소·동일 Search 반복 금지
정상 Pagination·Detail Fetch
Round 1·2 Additional Retrieval
Run-scoped RAG Required Segment Recall
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

### 13.4 Work Analysis

```
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

### 13.5 Planning

```
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

### 13.6 Review

```
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

## 14. Capability completeness contract

- 각 Agent가 소유하는 current Result/Disposition vocabulary는 06의 runtime topology와 exact match한다.
- LLM-retryable Failure는 bounded Repair/Revision 경로와 `retry_kind`가 정의되어야 한다.
- Non-retryable Failure는 deterministic Redirection/Stop/Recovery owner가 정의되어야 한다.
- 같은 failure signature의 무한 반복은 금지하고 budget 종료가 결정적이어야 한다.
- Over-confirmation·Overblocking을 막기 위해 정상 PASS/CONTINUE 경계와 CONFIRM/BLOCK 경계를 모두 정의한다.
- Answer-only, compatibility READ-only, WRITE, Additional Retrieval, Confirmation, Approval, Reauth, Recovery의 Prompt/Failure 책임은 각각 owning workflow/domain contract를 침범하지 않는다.
- 실제 Dataset coverage 수량·DEV/HOLDOUT split·trial 반복성은 `13 Evaluation`이 검증한다.

## 15. Prompt release activation boundary

Dataset·Grader·scoring·Candidate 비교와 release evidence는 `13 Evaluation`이 소유한다. 본 문서는 그 결과를 받아 **이미 정의된 PromptRef/manifest/input/failure contract의 activation 상태를 결정하는 경계**만 제공한다.

- Evaluation 결과가 새 Prompt field, failure code, retry path, Agent capability를 직접 생성할 수 없다. 그런 Runtime 의미가 필요하면 먼저 owning 06/15 contract를 수정한다.
- Prompt artifact가 활성화되더라도 Product Prompt는 Gold/Grader/score/expected route/end-state를 입력으로 받지 않는다.
- Prompt Registry는 current manifest/source/input-contract set과 일치하는 artifact만 activation 대상으로 취급한다.

## 16. Trace·Artifact Contract

Trace 추가 필드:

```
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

```
실제 사용자 Prompt 원문
Google 원문 전체
Prompt Template 원문
LLM Completion 원문
Credential
Holdout Gold 원문
```

---



## 17. Clarification Capability

- 모호성은 기본 BLOCK이 아니라 `NEEDS_CONFIRMATION → ConfirmationRequiredV1 → RequestConfirmation → same-owner interrupt/resume`다.
- 후보가 있으면 후보·차이·선택지를 제공하고, 후보가 없으면 최소 누락 정보만 질문한다.
- `처리/진행/시작/정리/마무리`는 문맥으로 의미가 단일하면 질문하지 않는다.
- `답장/회신/보내줘`는 SEND 의도이며 Draft ambiguity가 아니다.
- 요청/검색/분석 중 실제 모호성이 관측된 단계에서 Redirection한다.

## 18. Attachment Capability 경계

- Gmail 첨부파일 I/O는 Agent Semantic Capability가 아니다.
- Product Prompt에 첨부파일 bytes·파일 내용·Local Path를 넣지 않는다.
- Agent는 필요 시 파일명·MIME Type·크기·Attachment Descriptor만 사용한다.
- Download/Stage/Hash Verification/MIME 조립/Claim V2 검증 실패는 `DETERMINISTIC` 또는 `TERMINAL` Runtime 처리이며 LLM Repair·Semantic Revision 대상으로 바꾸지 않는다.
- Claim V2와 Attachment integrity는 제품 Runtime 안전 계약이므로 Agent Profile 실험의 독립변수로 변경하지 않는다.

