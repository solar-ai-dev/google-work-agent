# Google Work Agent · LangGraph 구현 인계서 (PR 기준)

> **목적:** `feat/langgraph-runtime` 브랜치에서 현재까지 구현한 LangGraph Workflow / Control Plane 작업을 다음 담당자에게 인계한다.  
> **범위:** 현재 구현 Stage 1~13 완료 지점.  
> **중요:** 이 문서는 구현 Snapshot이며 `01~15` 권위 설계 문서를 대체하지 않는다. 문서와 실제 구현이 다르면 source / test / migration을 함께 확인한다.

---

## 1. 현재 위치 한눈에 보기

현재까지 실제로 구현·검수한 흐름은 아래와 같다.

```text
사용자 요청
→ Request Understanding
→ API Discovery / Acquisition
→ Context Retrieval
→ Work Analysis
→ Solution Planning
→ Plan Review
→ Deterministic Supervisor
→ Domain Validation
→ Approval
→ Execution Preflight / Claim
────────────────────────────────────────
→ 실제 Google Effect Execution        [후속]
→ Deterministic Verification           [후속]
→ Recovery / Finalize                  [후속]
```

현재 Freeze 상태:

```text
Stage 1~10  Agent Workflow + Supervisor      FROZEN
Stage 11    Domain Validation                FROZEN
Stage 12    Approval Boundary                FROZEN
Stage 13    Execution Preflight Boundary     FROZEN

Control Plane through Stage 13               FROZEN
```

Stage 13 pre-commit review 결과:

```text
STAGE13_PRECOMMIT_REVIEW_PASS
STAGE13_EXECUTION_PREFLIGHT_IMPLEMENTATION_COMPLETE
STAGE13_SCOPE_REVIEW_PASS

Execution Preflight Boundary: FROZEN
Control Plane through Stage 13: FROZEN

SAFE_TO_COMMIT
```

Stage 13 구현 기준 전체 테스트는 `457 passed`, Ruff / format / `git diff --check` 모두 통과했다.

---

# 2. 구현 Stage 1~13 요약

| 구현 Stage | 구현 내용 | 상태 |
|---|---|---|
| 1 | Contract / Scope Baseline | FROZEN |
| 2 | Workflow Typed Contract | FROZEN |
| 3 | PromptRef / Structured LLM Boundary | FROZEN |
| 4 | Request Understanding | FROZEN |
| 5 | API Discovery / Acquisition | FROZEN |
| 6 | Context Retrieval | FROZEN |
| 7 | Work Analysis | FROZEN |
| 8 | Solution Planning | FROZEN |
| 9 | Plan Review | FROZEN |
| 10 | Deterministic Supervisor | FROZEN |
| 11 | Domain Validation + Effect Authority | FROZEN |
| 12 | Approval Boundary | FROZEN |
| 13 | Execution Preflight Boundary | FROZEN |

---

# 3. Stage 1~3 — 공통 계약

## Stage 1 — Contract / Scope

확정한 기본 원칙:

- Supervisor는 deterministic router다.
- LLM Agent는 Google Write를 직접 실행하지 않는다.
- Graph Node가 Domain Repository / SQL을 직접 수정하지 않는다.
- 승인·실행·검증 사실은 Domain/Application 계층이 authority다.
- 계약이 문서와 source 양쪽에 없으면 임의로 새 semantics를 만들지 않는다.
- Source / test / migration을 실제 구현 truth로 함께 확인한다.

## Stage 2 — Workflow Typed Contract

주요 `WorkflowPhase`:

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

현재 `MultiAgentGraphState`는 **21 top-level fields**를 유지한다.

Stage 10에서 checkpoint-safe terminal handoff를 위해 `finalize_intent`가 추가됐다.

## Stage 3 — PromptRef / Structured LLM Boundary

기존 runtime contract를 재사용한다.

- `StructuredLLMProvider`
- `LLMRuntimeService.invoke_structured(...)`
- `PromptReference`
- `PromptSelectionKey`
- `PromptRef`
- `StructuredLLMResult`

LLM은 semantic 판단에 사용하고, ID / enum / schema / DAG / budget / approval / execution / verification은 deterministic code가 소유한다.

---

# 4. Stage 4~9 — 6개 전문 역할

## Stage 4 — Request Understanding

`RequestIntentV1`

```text
COMPLETE
NEEDS_CONFIRMATION
INVALID
```

Semantic INVALID와 provider/schema/runtime failure를 분리한다.

## Stage 5 — API Discovery / Acquisition

주요 계약:

```text
PLAN_READY
NO_FETCH_NEEDED
NEEDS_CONFIRMATION
BLOCKED
```

Acquisition:

```text
COMPLETE
PARTIAL
AUTH_REQUIRED
RATE_LIMITED
BUDGET_EXHAUSTED
FAILED
```

`NO_FETCH_NEEDED`는 Google Search를 실행하지 않고 canonical empty acquisition result를 생성한 뒤 Context Retrieval로 이동한다.

## Stage 6 — Context Retrieval

`ContextRetrievalResultV1`

```text
SUFFICIENT
NEEDS_MORE_DATA
NEEDS_CONFIRMATION
PARTIAL
BLOCKED
```

## Stage 7 — Work Analysis

`WorkAnalysisResultV1`

```text
COMPLETE
NEEDS_MORE_DATA
NEEDS_CONFIRMATION
BLOCKED
```

## Stage 8 — Solution Planning

출력:

- `AnswerDraftV1`
- `ActionPlanDraftV1`

불변조건:

```text
ANSWER_ONLY → answer_draft != None, plan_draft == None
PLAN_READY  → plan_draft != None, answer_draft == None
```

`revise_answer`, `revise_plan` 경계를 제공한다.

## Stage 9 — Plan Review

`PlanReviewResultV1`

```text
PASS
REVISE
RETRIEVE_MORE
CONFIRM
BLOCK
```

Plan Review는 실행 승인 자체가 아니며, 이후 deterministic Domain Validation이 실행 가능 여부를 판정한다.

---

# 5. Stage 10 — Deterministic Supervisor

Stage 10에서 Stage 4~9의 결과를 처음 하나의 deterministic routing contract로 연결했다.

핵심 보강:

### Retrieval Redirection

```text
Context NEEDS_MORE_DATA
Analysis NEEDS_MORE_DATA
Review RETRIEVE_MORE
→ SOURCE_PLANNING
```

`AdditionalAcquisitionRequestV1`을 사용하며 메시지 문자열 파싱으로 redirect하지 않는다.

### Confirmation / Resume Contract

- `ClarificationQuestionV1`
- `ConfirmationResponseV1`
- `UserInterruptV1`
- exact `origin_target`

Supervisor가 confirmation routing과 `WAITING_CONFIRMATION`을 소유한다.

### Typed Budget

`RunBudgetV1`, `BudgetDecisionV1`, `BudgetReasonCode`를 사용해 additional acquisition / revision / review recheck 상한을 결정적으로 관리한다.

### Terminal / Recovery

Terminal:

```text
COMPLETED
CANCELLED
FAILED
BLOCKED
```

Non-terminal:

```text
REAUTH_REQUIRED
RECOVERY_REQUIRED
```

Supervisor는 RunStatus를 직접 mutate하지 않는다.

### `finalize_intent`

Terminal intent를 checkpoint 이후에도 안전하게 전달하는 persisted handoff다.

대표 커밋:

```text
c0dc599 feat: 결정적 Supervisor 라우팅 구현
```

---

# 6. Stage 11 — Domain Validation / Effect Authority

Effect Authority는 다음 5개로 고정했다.

```text
READ
CREATE
UPDATE
SEND
DELETE
```

P0 Registry 주요 추가:

```text
gmail_send            → SEND
calendar_delete_event → DELETE
```

P0 금지:

- Gmail Message / Thread 삭제
- Task 삭제
- 반복 Event 전체에 대한 광범위 DELETE

Task 완료는 `UPDATE`, Calendar attendee 변경 역시 `UPDATE`로 취급한다.

Effect별 정책:

| Effect | Approval | Verification | Recovery |
|---|---|---|---|
| READ | NONE | NONE | NONE |
| CREATE | REQUIRED | GET_COMPARE | RESOURCE_SEARCH |
| UPDATE | REQUIRED | GET_COMPARE | GET_TARGET |
| SEND | REQUIRED | SENT_LOOKUP | MESSAGE_SEARCH |
| DELETE | REQUIRED | GET_ABSENT | GET_TARGET |

Domain Validation Result:

```text
ALLOW_READ
REQUIRE_APPROVAL
BLOCK
```

DB는 `0002_action_effect_send_delete.sql` migration으로 SEND / DELETE를 지원한다.

대표 커밋:

```text
bb1dfbd feat: effect 권위 및 도메인 검증 구현
```

---

# 7. Stage 12 — Approval Boundary

새 Approval subsystem을 만들지 않고 기존 Domain/Application authority를 Workflow에 연결했다.

Approval authority는 **Plan-level이 아니라 Action-level**이다.

Canonical authority:

- `ApprovalRecord`
- `ApproveWriteActionService`
- `RejectWriteActionService`
- `validate_approval_integrity(...)`

ApprovalRecord는 Action과 다음 정보를 바인딩한다.

```text
action_id
action_version
arguments_snapshot_json
source_snapshot_json
canonical_arguments_hash
source_snapshot_hash
policy_version
tool_schema_version
idempotency_key
recovery_fingerprint
```

## `approved_plan_id` 주의

Graph State의 `approved_plan_id`는 Action-level Approval authority가 아니다.

금지:

```text
approved_plan_id != None
→ 모든 WRITE Action 승인 완료
```

실제 승인 여부는 Domain Store의 각 Action `ApprovalRecord` 및 integrity contract가 authority다.

ApprovalRecord를 Graph State에 복제하지 않는다.

Routing:

```text
ALLOW_READ       → PREFLIGHT
REQUIRE_APPROVAL → WAITING_APPROVAL
BLOCK            → FINALIZE(BLOCKED intent)
```

대표 커밋:

```text
dc62c72 feat: approval workflow 경계 구현
```

---

# 8. Stage 13 — Execution Preflight Boundary

별도 `PreflightService`를 새로 만들지 않고 기존 Claim/Application boundary를 재사용했다.

READ:

```text
ClaimReadActionService
```

WRITE:

```text
ClaimWriteActionService
validate_approval_integrity(...)
```

Routing:

```text
PREFLIGHT + valid claim
→ ACTION_EXECUTION

PREFLIGHT + typed auth problem
→ REAUTH

PREFLIGHT + deterministic claim rejection
→ FINALIZE(BLOCKED intent)
```

Technical exception을 semantic `BLOCKED`로 변환하지 않는다.

중요한 regression contract:

```text
approved_plan_id 존재
≠ WRITE approval authority
```

Action-level valid ApprovalRecord가 없으면 WRITE preflight를 통과할 수 없다.

Stage 13은 실제 Google Effect를 호출하지 않는다.

Write claim 이후 Stage 14가 사용할 주요 identity:

```text
approval_id
attempt_id
claim_token
```

Stage 13 구현 기준 검증:

```text
tests/unit/application/workflows/test_supervisor.py   25 passed
tests/unit/application/workflows                     168 passed
tests/unit/application                               176 passed
tests/integration/persistence                         59 passed
full pytest                                          457 passed

ruff check src tests                                 PASS
ruff format --check src tests                        PASS
git diff --check                                     PASS
```

---

# 9. 이번 PR에 아직 포함하지 않는 것

다음은 의도적으로 후속 작업이다.

- 실제 LangGraph `StateGraph` 조립
- `add_node`, conditional edges, `compile()`
- LangGraph Checkpointer 연결
- 실제 `interrupt()/resume` 실행
- Runtime Provider 최종 연결
- 실제 Google CREATE / UPDATE / SEND / DELETE 실행
- Stage 15 Verification
- `FAILED` Retry
- `UNKNOWN_RESULT` Recovery
- Stage 16 Response / Recovery / Finalize
- `SINGLE_BASELINE / THREE_STAGE / SIX_ROLE_BASELINE` Graph Profile
- 최종 E2E / 전체 Runtime 검수

따라서 이번 PR은 **“완성된 LangGraph Runtime”이 아니라, 실제 Runtime 조립 전에 Agent Node 계약과 deterministic Control Plane을 먼저 고정한 PR**이다.

---

# 10. 다음 작업 — Stage 14 Execution + Stage 15 Verification 통합 계약 확인

다음 담당자는 **Stage 14와 Stage 15를 따로 Preflight하지 않는다.**

실제 외부 Effect 실행과 그 결과 검증은 하나의 safety boundary이므로 먼저 **한 번에 계약 확인**한다.

```text
Stage 13 Claim / Preflight
        ↓
Stage 14 External Effect
        ↓
Execution Result
        ↓
Stage 15 Deterministic Verification
        ↓
Verified / Failed / Unknown / Recovery handoff
```

## 반드시 같이 확인할 항목

### 1. Effect별 실제 Tool / Policy

Frozen authority:

| Effect | Approval | Verification | Recovery |
|---|---|---|---|
| CREATE | REQUIRED | GET_COMPARE | RESOURCE_SEARCH |
| UPDATE | REQUIRED | GET_COMPARE | GET_TARGET |
| SEND | REQUIRED | SENT_LOOKUP | MESSAGE_SEARCH |
| DELETE | REQUIRED | GET_ABSENT | GET_TARGET |

특히:

```text
SEND   → SENT_LOOKUP
DELETE → GET_ABSENT
```

가 Registry / Port / Adapter / test에서 실제로 구현 가능한지 확인한다.

### 2. `FAILED` vs `UNKNOWN_RESULT`

외부 호출 결과를 반드시 분리한다.

```text
FAILED
= 외부 Effect가 전달되지 않았음이 보장되는 실패

UNKNOWN_RESULT
= 요청이 전달됐을 가능성이 있어 실제 Effect 발생 여부를 확정할 수 없음
```

`UNKNOWN_RESULT`를 단순 `FAILED`로 낮추면 안 된다.

### 3. `UNKNOWN_RESULT` 자동 재실행 금지

특히 SEND / DELETE:

```text
UNKNOWN_RESULT
→ 새 Write Attempt 금지
→ 동일 요청 자동 재전송 금지
→ Recovery 조회로 실제 Effect 여부 확인
```

SEND는 `MESSAGE_SEARCH`, DELETE는 `GET_TARGET` recovery contract를 따른다.

### 4. FAILED Retry

재시도가 허용되는 경우에도 기존 Approval/Attempt를 단순 재활성화하지 않는다.

현재 권위 계약과 source를 함께 확인해 다음을 확정한다.

- 어떤 실패만 retryable인가
- 새 Approval 필요 여부
- 새 idempotency key 규칙
- 새 ExecutionAttempt 발급 규칙
- retry count / version guard
- dependency Action 영향

### 5. Verification Policy

CREATE / UPDATE:

```text
GET_COMPARE
```

SEND:

```text
SENT_LOOKUP
```

DELETE:

```text
GET_ABSENT
```

Verification은 LLM 판단이 아니라 deterministic policy다.

`MISMATCH` 발생 시 자동 수정 / 자동 rollback / LLM 재계획으로 보내지 않는다.

### 6. Stage 14 → 15 Handoff

확인할 최소 identity:

```text
action_id
approval_id
attempt_id
claim_token
execution result / snapshot
effect
verification policy
expected state
```

실제로 이미 존재하는 DTO / record를 우선 재사용한다.

### 7. External I/O Transaction Boundary

Google / MCP 호출 동안 SQLite write transaction을 열어두지 않는다.

목표 구조:

```text
Transaction A
→ Claim / snapshot / version 확정
→ COMMIT

External Google/MCP call

Transaction B
→ expected_version / Action / Attempt 재검증
→ result / audit 저장
→ COMMIT
```

### 8. Stage 15 → Stage 16 Handoff

Verification 결과가 Stage 16의:

```text
Response
Recovery
Finalize
```

중 어디로 연결되는지 한 번에 확인한다.

특히:

- VERIFIED
- MISMATCH
- FAILED
- UNKNOWN_RESULT
- recovery success / failure

의 exact state transition을 확인한다.

---

# 11. Stage 14~15 통합 Preflight에서 답해야 할 핵심 질문

다음 질문에 모두 답한 뒤 구현을 시작한다.

1. CREATE / UPDATE / SEND / DELETE의 실제 MCP Tool과 Port는 무엇인가?
2. Stage 13 `claim_token`을 Stage 14가 어떻게 소비하는가?
3. ExecutionAttempt 생성 owner는 현재 누구인가?
4. 외부 호출 전 마지막 version / approval / claim 검증은 어디에서 수행되는가?
5. 외부 호출 성공 결과 DTO는 무엇인가?
6. `FAILED`와 `UNKNOWN_RESULT`를 어떤 typed result/code로 구분하는가?
7. SEND 전달 여부가 불명확할 때 자동 재전송이 확실히 금지되는가?
8. DELETE 결과 불명확 시 어떤 GET으로 recovery하는가?
9. CREATE / UPDATE / SEND / DELETE 각각 어떤 Verification Tool을 호출하는가?
10. Verification `MISMATCH`의 다음 상태는 무엇인가?
11. FAILED Retry에서 기존 Approval을 재사용하는가, 새 Approval을 만드는가?
12. Retry 시 새 Attempt / idempotency / version 규칙은 무엇인가?
13. Google/MCP I/O 동안 DB write transaction이 열려 있지 않은가?
14. Execution result와 Verification result의 authoritative persistence owner는 누구인가?
15. Stage 15 결과를 Stage 16이 어떤 typed handoff로 소비하는가?

계약이 문서와 source에서 충분하면 그대로 Stage 14 → Stage 15 구현한다.

정면 충돌이 있을 때만 `CONTRACT_CHANGE_REQUIRED`로 멈춘다.

---

# 12. 남은 Stage 14~20 절차

현재 Stage 13까지 완료했으며, 이후에는 아래 순서로 진행한다.

| Stage | 남은 작업 | 핵심 내용 |
|---|---|---|
| **14** | **Execution** | Stage 14~15 통합 계약 확인 후 실제 Google/MCP `CREATE / UPDATE / SEND / DELETE` 실행 경계를 구현한다. `FAILED`와 `UNKNOWN_RESULT`를 구분하고 외부 I/O transaction 경계를 지킨다. |
| **15** | **Verification** | `GET_COMPARE / SENT_LOOKUP / GET_ABSENT` 기반 deterministic verification을 구현한다. `MISMATCH` 및 verification failure의 다음 상태를 고정한다. |
| **16** | **Response / Recovery / Finalize** | `FAILED` retry, `UNKNOWN_RESULT` recovery, `REAUTH_REQUIRED / RECOVERY_REQUIRED`, 최종 응답 및 terminal finalize 경계를 연결한다. |
| **17** | **LangGraph Runtime Integration** | 실제 `StateGraph`, node/edge 연결, Checkpointer, `interrupt()/resume`, Runtime Provider를 구현한다. 기존 Frozen Domain/Application authority를 Graph State로 복제하지 않는다. |
| **18** | **Graph Profile** | 동일 Dataset/Model/Policy/Retrieval 조건에서 `SINGLE_BASELINE / THREE_STAGE / SIX_ROLE_BASELINE` 프로필을 구성한다. |
| **19** | **E2E / 전체 검수** | 실제 graph compile/invoke/resume, approval/write/verification/recovery, restart/checkpoint, 전체 regression 및 실험 진입 조건을 검증한다. |
| **20** | **최종 인수인계 / 문서 정리** | 구현 결과, Frozen 계약, 테스트 결과, 남은 제한사항을 문서화하고 최종 clean commit/PR 인계 상태로 정리한다. |

진행 순서:

```text
Stage 14~15 통합 Contract Preflight
        ↓
Stage 14 Execution
        ↓
Stage 15 Verification
        ↓
Stage 16 Response / Recovery / Finalize
        ↓
Stage 17 LangGraph Runtime Integration
        ↓
Stage 18 SINGLE / THREE / SIX Graph Profile
        ↓
Stage 19 E2E / 전체 검수
        ↓
Stage 20 최종 인수인계 / 문서 정리
```

---

# 13. 다음 담당자 주의사항

1. Stage 1~13 Frozen contract를 편의상 다시 설계하지 않는다.
2. `approved_plan_id`를 WRITE approval authority로 사용하지 않는다.
3. Approval authority는 Action-level `ApprovalRecord`다.
4. Supervisor는 deterministic route만 담당한다.
5. Technical exception을 semantic `BLOCKED`로 변환하지 않는다.
6. Graph State는 현재 21 fields를 기본 유지한다.
7. `trace_context`는 observability 용도이며 semantic authority가 아니다.
8. SEND / DELETE는 UNKNOWN_RESULT 자동 재실행 금지가 특히 중요하다.
9. 승인·실행·검증 사실의 authority는 Domain Store이며 Checkpoint가 아니다.
10. 실제 StateGraph Runtime이 아직 없다는 점을 숨기지 않는다.

---

## 참고 권위 문서

- `01-requirements-prd.md`
- `01-b-policy-definition.md`
- `03-system-architecture.md`
- `04-domain-database-design.md`
- `06-agent-workflow.md`
- `07-tool-mcp-internal-interface.md`
- `08-sequence-design.md`
- `09-security-auth.md`
- `12-test-design.md`
- `15-agent-capability-failure-prompt-contract.md`
- `state-transition-contract-v1.3.md`
- `state-transition-test-matrix-v1.3.md`
