# 08. 시퀀스 설계서

> **Authority:** cross-layer participant interaction order와 crash/replay cut. State/Workflow/API/Infrastructure semantics는 해당 owner를 따른다.  
> **상태:** Draft v3.27 · **기준일:** 2026-08-24 · **대상:** P0 MVP

## 1. 목적과 범위

이 문서는 주요 Use Case에서 React, FastAPI, Application, LangGraph Supervisor, 전문 Agent, Domain, Connector MCP Runtime, Provider API와 SQLite가 **어떤 순서로 상호작용하는지** 정의한다. P0 구체 시퀀스는 Google Workspace Connector를 사용한다.

이 문서가 소유하는 내용:

- 요청 시작과 SSE 연결 순서
- Tool Route와 Retrieval/RAG 순서
- 사용자 확인 Interrupt와 재개
- Answer-only, WRITE Plan 분기와 Legacy/호환 READ-only Plan 경계
- 승인·수정·거절·만료
- Action DAG·부분 승인·부분 실패
- Write 실패 재시도와 `UNKNOWN_RESULT` 복구
- OAuth 재인증, 취소, 새로고침, 앱 재시작, MCP 장애
- 외부 호출과 DB Transaction의 분리

이 문서가 소유하지 않는 내용:

- LangGraph Node·상태 Schema 상세 → `06`
- REST·MCP Pydantic Schema 상세 → `07`
- Domain lifecycle command·허용 source state·guard·transition semantics → `Domain State Transition Contract`
- Domain 영속 사실·Table·Index·persistence realization → `04`; exact DB enforcement → 04 Domain·DB required DB invariant contract
- 운영자 대응 절차 → `14`

따라서 이 문서의 Domain Command/상태 표기는 **호출 순서와 상호작용 시퀀스의 reference**이며 lifecycle semantics를 새로 정의하지 않는다.

### 1.1 Authority boundary

시퀀스는 **상호작용 순서와 crash/replay cut**만 소유한다. State/guard는 State Contract, Workflow target/edge는 `06`, typed schema/Port는 `07`, process lifecycle은 `10`, repository placement는 `16`을 직접 소비한다. 이 문서의 sequence 예시는 해당 owner 계약을 재정의하지 않는다.

## 2. 공통 참여자

| 표기 | 구성 | 책임 |
| --- | --- | --- |
| U | 사용자 | 요청, 확인, 승인, 수정, 거절, 복구 선택 |
| FE | React 프런트엔드 | REST Command·Query, SSE Projection, Inline Card |
| API | FastAPI 로컬 에이전트 서비스 | Local Session·Schema 검증, Route·SSE Adapter |
| APP | Application | Use Case·Transaction·`WorkflowExecutionPort`를 통한 LangGraph invoke/resume handoff 조정 |
| SUP | 결정적 Supervisor | Phase·Agent Result·Domain Result 기반 Routing |
| LLM | Prompt Registry·LLM Router | Agent·Application Node가 확정한 PromptRef와 입력 Schema로 API LLM 또는 Ollama Structured Output 호출 |
| POL | deterministic Policy | 01-B allow/deny/confirmation requirement 계산. 상태 전이·DB mutation·외부 I/O 없음 |
| DOM | Domain | Aggregate guard, lifecycle 상태 전이, version/freshness invariant 판정. Product Policy를 재정의하지 않음 |
| DB | SQLite Domain Store | 영속 Domain 사실·Receipt·Audit·Read Model 저장 |
| CP | CheckpointPort | Graph 재개 위치·checkpoint 저장/조회 추상 경계. concrete LangGraph Checkpointer Adapter는 이 Port 뒤에 있으며 Domain Store transaction과 별도다. |
| MCP | Connector Application Ports · Registry · MCP Runtime | Application에는 ConnectorReadPort / ConnectorWritePort / OAuthCredentialPort를 노출하고, 그 뒤에서 MCP Client/Server를 조정한다. P0 concrete Server는 Google Workspace MCP Server다. |
| G | Google Provider APIs | Gmail·Tasks·Calendar 원본 시스템. 시퀀스에서 G에 직접 연결할 수 있는 참여자는 Google Workspace MCP Server 내부 Provider Adapter뿐이다. |

## 3. 공통 순서 원칙

1. React는 Google API, MCP, SQLite를 직접 호출하지 않는다.
2. FastAPI Route는 SQL과 Domain 상태 전이를 직접 수행하지 않는다.
3. Agent는 다른 Agent를 직접 호출하지 않고 Supervisor로 결과를 반환한다.
4. LLM Agent는 MCP Tool을 직접 호출하지 않는다. 검증된 Application Node가 Port를 호출한다.
5. Google API·LLM·MCP 외부 호출 중 SQLite Transaction을 유지하지 않는다.
6. 상태 변경은 Domain Command Result가 `applied=true`일 때만 다음 단계로 진행한다.
7. SSE 전송 실패는 Domain 실패가 아니다.
8. 승인 이후 LLM은 Tool·Arguments·대상 Resource·Dependency를 변경하지 않는다.
9. 일반 Retrieval 호출은 Action Row를 만들지 않는다.
10. **Legacy/호환 READ Action**은 Approval·ExecutionAttempt·Verification Row를 만들지 않는다. 현재 Release Graph의 일반 READ는 `InputRoutePlanV1 → Retrieval`이 소유하며 새 표준 Answer/Write 준비 경로에서 READ Action을 생성하지 않는다.
11. Supervisor는 Node만 Routing하며, 선택된 Agent·Application Node가 각 LLM 호출 전에 `agent_role + subgraph_name + node_name + node_state + purpose`로 PromptRef를 확정한다.
12. Repair·Revision은 원 호출 Prompt를 묵시적으로 재사용하지 않고 등록된 별도 PromptRef를 사용할 수 있다.
13. Confirmation은 공통 재시작이 아니라 LangGraph interrupt다. `interrupt_id`가 `semantic_owner_id + AgentNodeResumeTargetV2`를 보존하며 응답 후 selected Graph Profile의 exact compiled Subgraph checkpoint에서 재개한다. `resume_target`은 LLM 자유 문자열이 아니라 `ResumeTargetRegistry`가 NodeRegistry + semantic-owner/profile→compiled-subgraph binding으로 발급·검증한다. 응답이 upstream 의미를 변경할 때만 Supervisor가 State Owner로 Back-edge한다.
14. 모든 공식 Subgraph disposition은 정확히 하나의 Supervisor Edge·Interrupt·Terminal 경로를 가진다. 알 수 없는 Enum·Version·disposition은 bounded repair 뒤에도 유효하지 않으면 다음 Agent/Tool로 추측 Routing하지 않고 `RequireRecovery(CONTRACT_VIOLATION) → RECOVERY_REQUIRED`로 suspend한다. 복구 불가가 확정된 경우에만 `ResolveRecovery(FAIL) → FAILED`로 닫는다.
15. 외부 Connector 호출의 직접 제품 caller는 Application의 결정적 use-case/Application operation이다. 순서는 `Workflow/FastAPI Route → Application canonical operation → Application SignedToolRegistry binding → Connector Application Port → Core-side Connector Adapter → ConnectorRuntimeRegistry + MCPClientPort → Connector MCP Server → Provider API`이며 Workflow/LangGraph는 Application operation을 통해서만 Connector I/O를 요청한다. Application operation은 adapter-level `ConnectorRuntimeRegistry`/`MCPClientPort`를 직접 import/call하지 않는다. React·FastAPI Route·Application·LangGraph·Agent·Domain이 Provider API를 직접 호출하는 시퀀스는 금지한다. Local `/api/v1`은 Frontend용 제품 API이며 Provider API 우회 경로가 아니다. P0 Google Workspace는 이 공통 순서를 따른다.
16. Preflight/Claim 결과가 `applied=false`이면 MCP Write로 fall-through하거나 즉시 FINALIZE하지 않는다. Domain Result의 `current_status + next_allowed_commands`를 재조회해 재승인·Recovery·Reauth·Cancel/in-flight resolution·이미 Terminal 중 하나로 결정적으로 조정한다. Policy Block은 Claim 전 `BlockRun`이 실제 적용된 경우에만 Terminal이며 같은 Claim의 무조건 자동 재시도는 금지한다.
17. Recovery는 기존 결과 회수·재검증이 필요한 경우에만 Verification으로 돌아간다. Domain이 `RECOVERY_REQUIRED`이면 같은 상태에서 명시적 resolve/re-auth를 기다리고, 실패가 확정되면 terminal result를 반환한다. 무조건 `Recovery → Verification` 반복은 금지한다.
18. `FINALIZE`는 Run 상태를 임의 변경하지 않는다. Answer-only는 `CompleteAnswerOnlyRun`, Policy 차단은 `BlockRun`, 정상 Write 완료는 `CompleteWriteRun`, 취소는 `FinalizeCancel`, Recovery 종료는 terminal `ResolveRecovery(...)` Application handler가 **Run terminal mutation + final ASSISTANT Message + required Audit**를 같은 UoW로 commit한다. 그 뒤 FINALIZE는 diagnostic Trace와 SSE Projection만 publish한다. 비Terminal Run을 FINALIZE가 직접 덮어쓰거나 Message를 재삽입하지 않는다.
19. `REAUTH_REQUIRED`와 `CANCEL_REQUESTED`는 업무 Agent Edge와 별개인 전역 Domain suspend/resume 상태다. 재인증은 현재 안전 checkpoint로 복귀하고, 실행 중 취소는 in-flight 결과 확정·필요 Verification/Recovery 뒤에만 `FinalizeCancel`한다.

### 3.0-A Conversation · Run 시작/재개 구분

- **Terminal Run 뒤 새 USER 요청:** 같은 `conversation_id`를 유지할 수 있지만 Browser는 새 Run/Message/Workflow identity를 제출하지 않는다. Domain `StartRun`이 새 Run과 USER Message를 생성해 `run_id`를 확정한 뒤, 성공 결과를 받은 Application/Workflow가 해당 Run 전용 새 `langgraph_thread_id`/workflow binding과 `RunInputV1`을 구성한다. 과거 `langgraph_thread_id`/Checkpoint/Main State를 이어받지 않는다.
- **비Terminal 동일 Run 재개:** confirmation·reauth·recovery·명시적 `/resume`만 기존 `run_id + langgraph_thread_id + checkpoint`를 사용한다.
- Conversation Timeline 복원은 UI Query이며 Graph resume 자체가 아니다. 과거 Message가 화면에 표시돼도 새 Run Request Understanding/Prompt 입력으로 자동 전달하지 않는다.
- 같은 Conversation에 Open Run이 있으면 새 `StartRun`을 병렬 생성하지 않는다.

### 3.1 공통 Confirmation Interrupt·Resume

Agent Subgraph의 `NEEDS_CONFIRMATION`은 같은 Domain/Checkpoint machinery를 사용하지만 **pre-publish와 published-Plan re-review의 source Run status를 구분**한다. `SCOPE_EXPANSION_REQUIRED`, `DUPLICATE_OVERRIDE_REQUIRED`, `CONFLICT_OVERRIDE_REQUIRED`와 일반 사용자 모호성 확인에 동일한 registered resume-target 규칙을 적용한다.

```text
PRE-PUBLISH CONFIRMATION
Subgraph NEEDS_CONFIRMATION
→ Supervisor가 semantic_owner_id + AgentNodeResumeTargetV2 확정
→ Application: RequestConfirmation
→ Domain: ANALYZING | RETRIEVING | PLANNING → WAITING_CONFIRMATION
→ Checkpoint에 interrupt_id + owner + resume target 저장

PUBLISHED-PLAN REVIEW CONFIRM
published Review disposition = CONFIRM
→ current Run = WAITING_APPROVAL | VERIFYING
→ Application: guarded RequestConfirmation
→ Domain: WAITING_APPROVAL | VERIFYING → WAITING_CONFIRMATION
→ 같은 Review owner checkpoint를 registered target으로 보존

공통 resume
→ 사용자 응답
→ Application/Confirmation Controller가 응답·Policy Receipt 검증
→ Domain: ResumeConfirmation → 발생 전 안전 Domain 상태 복원
→ 같은 owner Subgraph checkpoint resume
```

- `RequestConfirmation.applied=false`이면 interrupt를 새로 만들지 않고 현재 Domain 상태를 재조정한다.
- `ResumeConfirmation.applied=false`이면 Agent를 재호출하지 않고 Conflict/Recovery를 처리한다.
- Policy Confirmation은 검증된 실제 사용자 응답에서만 `PolicyConfirmationReceiptV1`과 Audit을 만들며 Agent/LLM이 Receipt를 생성하지 않는다.
- 사용자 응답이 upstream 의미를 변경하는 경우에만 resume 후 해당 State Owner로 명시적 Back-edge한다.
- API raw resume payload는 Confirmation Controller가 `interrupt_id`와 option 범위를 검증한 뒤 bounded `ConfirmationResponseProjectionV1`으로 one-way projection한다. 같은 owner의 resumed invocation에만 `confirmation_response` Projection으로 전달하며, 다른 Agent·Main State·일반 Trace로 자동 승계하지 않는다. Raw payload·checkpoint metadata·resume target 자체는 Product Prompt 입력이 아니다.

### 3.2 Local SLLM atomic Subgraph 호출 순서

Agent 간 순서는 바꾸지 않지만, Local SLLM Profile에서는 책임이 큰 Subgraph 내부 LLM 호출을 다음처럼 세분화한다.

```
Work Analysis
  extract_work_facts LLM
  → resolve_entity_relations LLM (필요 시)
  → resolve_temporal_dependencies LLM (필요 시)
  → detect_duplicate_conflict_candidates LLM (필요 시)
  → deterministic validate_relations
  → assess_information_gaps LLM
  → assess_operational_risks LLM (필요 시)
  → deterministic assemble_work_analysis
  → deterministic validate_work_analysis

Planning ACTION
  frozen Output Route 1개
  → draft_action_objective_per_output_route LLM
  → compose_arguments_per_output_route LLM/tool-schema
  → 다음 Output Route
  → deterministic build_dependencies
  → deterministic assemble_plan
  → deterministic validate_plan

Review ACTION
  inspect_goal_and_evidence LLM
  → inspect_action_scope_and_route LLM
  → inspect_constraints_and_policy_summary LLM (필요 시)
  → deterministic aggregate_review_findings
  → deterministic validate_review
```

이 호출들은 같은 owner Subgraph 안에서 Local State를 통해 이어지며 Agent→Agent handoff가 아니다. 중간 Candidate는 Main State의 새 authority가 아니고 invocation 종료 시 공식 Result로만 병합한다. 강한 Runtime의 node fusion은 06/15가 요구하는 parity gate를 통과한 Profile에서만 허용한다. Product LLM 호출은 Run당 hard cap 24를 넘지 않는다.

### 3.2-A Review REVISE → Planning revision → affected-dimension RECHECK

`Review.REVISE`는 전체 Review를 처음부터 다시 실행하라는 의미가 아니다. 순서는 다음으로 고정한다.

```
Review
→ ReviewReviseV2.issues
   - affected_dimensions          # 필수 selector
   - affected_action_ids          # optional bounded context
   - affected_route_ids           # optional bounded context
→ Supervisor: Planning Back-edge
→ Planning revision Input Projection에 ReviewReviseV2.issues 전달
→ Planning이 새 planning_result revision 생성
→ Review 재진입 시 직전 REVISE issue의 affected_dimensions를 RECHECK Projection으로 전달
→ recheck_affected_dimensions
→ deterministic aggregate_review_findings
→ deterministic validate_review
→ PASS | REVISE | RETRIEVE_MORE | ROUTE_RECONSIDERATION | CONFIRM | BLOCK
```

- `affected_dimensions`가 비어 있지 않다면 `affected_action_ids=[]`, `affected_route_ids=[]`인 **dimension-only REVISE**도 유효하다. Action/Route ID를 임의 생성해 selector를 보충하지 않는다.
- Finding 문장이나 전체 Plan을 RECHECK selector로 사용하지 않는다.
- Planning Back-edge는 `ReviewReviseV2.issues`를 bounded revision context로 소비한다. 별도 장기 `WorkflowSignal` authority를 만들지 않는다.
- Review 재진입은 새 `planning_result` revision과 직전 REVISE의 affected-dimension context를 함께 사용한다. 이미 PASS한 dimension의 Product LLM inspector를 무조건 재호출하지 않는다.
- Review `REVISE`로 Run이 이미 `PLANNING`인 bounded revision에서는 `BeginPlanning`을 반복 적용하지 않는다.


### 3.3 External-control durable continuation common sequence

모든 사용자 개입 API는 아래 sequence를 소비한다. 개별 기능 Sequence가 이 공통 경로를 생략해 `APP → SUP` 직접 호출처럼 보이면 이 절이 우선한다.

```mermaid
sequenceDiagram
    autonumber
    participant FE as React
    participant API as FastAPI Route
    participant APP as Application controller
    participant DOM as Domain/lifecycle handler
    participant DB as SQLite UoW + workflow_handoffs
    participant WEP as WorkflowExecutionPort
    participant BG as BackgroundRunExecutor
    participant CP as Checkpoint adapter
    participant SUP as LangGraph

    FE->>API: user control + command_id + expected_version
    API->>APP: validated versioned request
    APP->>DOM: owning lifecycle/domain operation
    DOM->>DB: mutation + Receipt/Audit
    APP->>DB: stage WorkflowHandoffV1(PENDING, observed target/checkpoint, typed control?)
    DB-->>APP: one COMMIT
    APP->>APP: current Domain/child/target guard + effective binding + Run authority version
    APP->>DB: claim_execution_admission CAS
    Note over APP,DB: NORMAL PENDING→DISPATCHED before WEP; effective binding + expected Run version durable
    APP->>WEP: submit(WorkflowExecutionSubmissionV2(admission))
    WEP-->>APP: ACCEPTED / ALREADY_RUNNING / NOT_COMMITTED / BINDING_MISMATCH / SHUTTING_DOWN
    alt ACCEPTED
        Note over APP,DB: post-ACCEPTED handoff write = 0
        BG->>DB: reload exact persisted admission
        BG->>CP: commit execution_admission_id + runnable entry/control lineage
        BG->>DB: CAS CONSUMED/complete recovery admission + admission clear
    else non-ACCEPTED
        APP->>DB: release_execution_admission(reason)
    end
    Note over BG,DB: CONSUMED mark 전 owner Node/LLM/Connector I/O = 0
    BG->>SUP: exact registered target; descendant checkpoint는 active_handoff lineage 승계
```

Crash windows:

- Domain/Handoff same-UoW COMMIT 후 **admission claim 전** crash: `PENDING` startup redrive. Domain command 재실행 0.
- admission claim COMMIT 후 submit 전/후 crash: `DISPATCHED + persisted admission` redrive; exact same admission을 재사용한다.
- `ALREADY_RUNNING`: **submitted admission과 다른 admission이 same-Run worker slot을 점유한 경우에만** 반환한다. 동일 `admission_id` replay가 이미 accepted/active이면 WEP는 idempotent `ACCEPTED`를 반환한다. non-ACCEPTED release 시 Repository가 admission `expected_run_version`을 current Run.version과 재검사하여 equal epoch이면 NORMAL을 PENDING으로 되돌리고, newer Cancel/Reauth/Recovery/terminal 등으로 epoch가 바뀌었으면 stale NORMAL을 SUPERSEDED로 retire한다. 따라서 release가 이미 지나간 preemption window를 되돌려 old lower-sequence head를 부활시키지 않는다. Process-memory queue is not ordering authority.
- `SHUTTING_DOWN`: release 시 admission Run authority epoch가 current이면 NORMAL handoff는 PENDING으로 돌아가 next startup/live redrive 대상이 된다. newer control로 epoch가 stale이면 NORMAL은 SUPERSEDED되어 old head를 부활시키지 않는다.
- newer checkpoint generation caused by lower settled handoffs: immutable target + current Domain guard를 재검증한 ordered checkpoint rebind만 허용; arbitrary latest-target guessing은 금지.
- binding mismatch: release 시 Run authority epoch가 current일 때만 `BLOCKED_BINDING` durable commit → startup/live reconciler가 deterministic `system:handoff-binding-recovery:<handoff_id>` Recovery reconciliation → SUPERSEDED settlement. newer Reauth/Recovery/Cancel/terminal로 epoch가 이미 stale이면 old NORMAL handoff를 직접 SUPERSEDED하여 false CHECKPOINT_MISMATCH Recovery를 만들지 않는다.
- CONSUMED 이후 crash: latest descendant checkpoint에 `active_handoff_id` lineage가 남고 current Domain/child-fact fence가 허용하면 `CONSUMED_CONTINUATION_RECOVERY`, not SAFE_CHECKPOINT_RESUME. `REAUTH_REQUIRED|RECOVERY_REQUIRED|terminal` 또는 non-cancel-compatible CANCEL_REQUESTED이면 old continuation 0.

## 4. 앱 시작·Local Session·상태 복원

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자
    participant L as Launcher
    participant SVC as FastAPI Local Service Process
    participant API as FastAPI Route Adapter
    participant APP as Application
    participant REP as Domain Repository Ports
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant CP as CheckpointPort
    participant K as 운영체제 키 저장소
    participant MCP as Connector Ports · MCP Runtime
    participant LLM as LLM Ports · Router
    participant FE as React 프런트엔드

    U->>L: 앱 실행
    L->>SVC: 동적 포트로 프로세스 시작
    L->>API: GET /health/live
    API-->>L: LIVE
    SVC->>DB: Migration·quick_check·Open Run 조회
    SVC->>CP: Checkpointer availability·schema 확인
    SVC->>MCP: 자식 프로세스 시작·Tool Version·Schema 검증
    SVC->>LLM: 배포 프로필에 필요한 Adapter 로드 확인
    SVC->>APP: ReconcileInflightExecutionsHandler(startup-only batch Command)
    APP->>REP: list_reconciliation_candidates(limit)
    APP->>APP: POST_BEGIN_ORPHAN → UNKNOWN_RESULT → lookup/recovery
    APP->>APP: EXECUTED_AWAITING_VERIFICATION → BeginVerification/RECHECK + deterministic VERIFICATION handoff
    APP->>APP: FAILED_AWAITING_CONTINUATION → guarded PREFLIGHT/CANCEL_RESOLUTION handoff
    Note over SVC,APP: orphan batch는 MCP/LLM readiness 뒤, worker/handoff redrive 전에 bounded drain; live loop 호출 0
    SVC->>APP: RedriveWorkflowHandoffsHandler(initial handoff reconciliation)
    APP->>CP: Open Run latest checkpoint / active_handoff_id 검사
    APP->>APP: CONSUMED active-continuation + Domain-progress fence 우선
    APP->>APP: BLOCKED_BINDING head → deterministic CHECKPOINT_MISMATCH Recovery reconcile
    APP->>APP: PENDING/DISPATCHED dispatch-head → ScheduleRunExecutionHandler(NORMAL_HANDOFF)
    SVC->>APP: WorkflowHandoffReconciliationLoop start
    Note over SVC,APP: live loop는 RedriveWorkflowHandoffsHandler만 drive; direct WEP/LangGraph 0
    L->>API: GET /health/ready
    alt Core Readiness 성공
        API-->>L: READY
        L->>FE: same-origin URL 열기
    else 진단·복구만 가능
        API-->>L: SAFE_MODE 또는 NOT_READY
        L->>FE: same-origin 진단 UI 열기
    end
    FE->>API: POST /api/v1/session/bootstrap(bootstrap_secret, frontend_api_contract_version)
    API-->>FE: Local Session + api_contract_version + compatibility
    alt compatibility = INCOMPATIBLE
        FE->>FE: mutation/SSE 비활성화 + update-required 안내
    end
    FE->>API: GET /api/v1/runtime
    API->>APP: Runtime Status Query
    APP->>MCP: Google 계정·Scope·재인증 상태 조회
    MCP->>K: Refresh Token 존재·사용 가능 상태 확인
    MCP-->>APP: Google Runtime Metadata
    APP->>LLM: API Provider·Ollama 사용 가능 상태 조회
    LLM->>K: API Key 존재 여부 확인
    LLM-->>APP: LLM Runtime Metadata
    APP->>REP: Open Run·Recovery Domain 상태 조회
    REP-->>APP: bounded Run recovery state
    APP->>CP: 해당 Run checkpoint availability 조회
    CP-->>APP: bounded checkpoint availability
    APP-->>API: Runtime Status Projection
    API-->>FE: Runtime·Google·MCP·LLM·복구 가능 Run
    opt 중단된 Run 존재
        FE->>API: GET /api/v1/runs/{run_id}
        API->>APP: Run Snapshot Query
        APP->>REP: Domain Snapshot 조회
        REP-->>APP: Domain 상태
        APP->>CP: checkpoint availability 조회
        CP-->>APP: bounded resume availability
        APP-->>API: Run Snapshot
        API-->>FE: 복원 가능한 상태
    end
```

- `/health/ready`는 DB·Migration·정적 Asset·API Contract·Keyring Adapter·MCP Executable·Tool Schema 같은 Core Readiness를 판정한다.
- Google Credential, API LLM Key, Ollama와 Model 사용 가능 여부는 `/api/v1/runtime` 진단 결과이며 누락 자체가 Core Service 시작 실패를 의미하지 않는다.
- Bootstrap Secret은 한 번 교환한 뒤 폐기한다.
- Checkpoint와 Domain 상태가 충돌하면 자동 추정하지 않고 `RECOVERY_REQUIRED`로 표시한다.

### 4.1 Sequence persistence notation

현재 sequence에서 `DOM`은 **pure Domain guard/transition calculation**만 의미한다. Domain은 Repository/SQLite를 호출하지 않는다.

- `APP->>DOM` — Application handler가 Domain command/guard를 평가한다.
- `APP->>DB` — Domain 결과가 유효한 뒤 Application `UnitOfWork`가 **Repository Port를 통해** Receipt·Domain mutation·required Audit를 짧은 transaction으로 commit한다. Mermaid의 `DB` participant는 concrete DB direct import가 아니라 `UnitOfWork → Repository Port → SQLite Adapter` persistence boundary의 축약이다.
- `DOM->>DB` — **금지**. Domain→Persistence direct dependency를 뜻할 수 있으므로 current sequence에 사용하지 않는다.
- Connector/MCP/LLM external I/O 중에는 `UnitOfWork` transaction을 열어 두지 않는다. 외부 결과는 호출 종료 뒤 별도의 짧은 UoW로 저장한다.

## 5. Run 시작과 SSE 연결

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자
    participant FE as React 프런트엔드
    participant API as FastAPI
    participant APP as Application
    participant DOM as Domain
    participant REP as Domain Repository Ports
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant SUP as Supervisor

    U->>FE: 자연어 요청 제출
    FE->>API: POST /api/v1/runs<br>command_id·conversation_id<br>request_text·entry_mode·selected_resource_handles·requested_mode
    API->>API: Session·Schema·Version 검증
    API->>APP: start_run(command)
    APP->>DOM: StartRun(command_id·canonical request hash)
    APP->>APP: server-owned run_id·user_message_id·langgraph_thread_id·workflow_key preallocate
    APP->>DOM: StartRun guard/effect with server-owned IDs
    APP->>APP: current graph_profile/version + requested_mode로 WorkflowBindingV1 materialize
    APP->>DB: StartRun UoW · Receipt + Run/User Message + WorkflowBinding + START WorkflowHandoff(PENDING) commit
    DB-->>APP: COMMIT · applied=true·run_id·handoff_id·version
    APP->>SUP: post-commit schedule_run_execution(handoff_id) → WorkflowExecutionPort → BackgroundRunExecutor → Graph invoke
    API-->>FE: 202 Accepted·run_id·snapshot_version
    FE->>API: GET /api/v1/runs/{run_id}/events
    API-->>FE: SSE 연결
    SUP-->>API: phase_changed Projection
    API-->>FE: event_id·phase·user_message
```

- 동일 `command_id` 재전송은 기존 Run Result를 반환하거나 Version Conflict로 종료한다.
- 동일 `conversation_id`의 과거 Run이 Terminal이면 이 요청은 **새 Run·새 `langgraph_thread_id`**를 생성한다. 이전 Run Checkpoint를 Graph invoke 입력으로 재사용하지 않는다.
- 동일 Conversation에 비Terminal Run이 있으면 Open Run Guard가 두 번째 Run 생성을 차단한다. 기존 Run을 이어야 하는 경우 `/confirm`·`/resume` 등 해당 Run의 resume 계약을 사용한다.
- Graph 실행 시작과 HTTP 응답 순서는 구현상 비동기일 수 있으나 Run Row Commit 이후 `run.schedule_run_execution → WorkflowExecutionPort`를 통해서만 시작한다. FastAPI Route가 concrete background primitive나 LangGraph executor를 직접 선택하지 않는다.

## 6. AGENT_SEARCH 전체 조회·분석 시퀀스

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자
    participant CONFCTL as Application Confirmation Controller
    participant SUP as Main Supervisor
    participant APP as Application
    participant DOM as Domain
    participant REQ as Request Understanding Subgraph
    participant ROUTE as Tool Route Subgraph
    participant RET as Retrieval Subgraph
    participant ANA as Work Analysis Subgraph
    participant PLAN as Planning Subgraph
    participant REV as Review Subgraph
    participant LLM as Prompt Registry·LLM Router
    participant MCP as ConnectorReadPort
    participant G as Google APIs
    participant REP as Domain Repository Ports
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant CP as CheckpointPort

    SUP->>APP: start_analysis(command)
    APP->>DOM: StartAnalysis(expected_version)
    APP->>DB: UoW commit · Run CREATED → ANALYZING + Receipt/Audit
    DB-->>APP: COMMIT · applied=true
    APP-->>SUP: ANALYZING ready

    SUP->>REQ: Request Projection + invocation_id
    REQ->>LLM: goal/ambiguity Node PromptRef
    LLM-->>REQ: RequestIntent candidate
    REQ->>REQ: Schema·Contract Validate / bounded repair
    REQ-->>SUP: RequestIntentV2 + disposition
    SUP->>CP: REQUEST_UNDERSTANDING Checkpoint

    SUP->>ROUTE: RequestIntentV2
    ROUTE->>LLM: determine_resources PromptRef
    LLM-->>ROUTE: IN/OUT Resource·Effect candidate
    ROUTE->>ROUTE: deterministic `tool_routing.resolve_policy_preconditions`<br>TASK CREATE→Tasks duplicate READ<br>CALENDAR CREATE→Event/FreeBusy conflict READ
    alt mandatory READ가 사용자 지정 범위 밖
        ROUTE-->>SUP: NEEDS_CONFIRMATION<br>SCOPE_EXPANSION_REQUIRED
        SUP-->>U: 추가 Source·기간·Resource와 이유 확인
        U-->>CONFCTL: scope expansion 승인/거절
        CONFCTL->>DB: PolicyConfirmationReceiptV1 + POLICY_CONFIRMATION_RECORDED
        CONFCTL->>SUP: validated receipt + interrupt resume
        SUP->>ROUTE: Tool Route owner checkpoint resume
    end
    ROUTE->>ROUTE: confirmed scope 안에서 deterministic Registry candidate binding
    opt Registry candidate 여러 개
        ROUTE->>LLM: select_tool PromptRef<br>registered eligible candidates only; heuristic shortlist 금지
        LLM-->>ROUTE: selected candidate
    end
    ROUTE->>ROUTE: deterministic final route + validation
    ROUTE-->>SUP: ToolRoutePlanV2
    SUP->>CP: TOOL_ROUTING Checkpoint

    opt IN Route 존재
        SUP->>APP: begin_retrieval(command)
        APP->>DOM: BeginRetrieval(expected_version)
        APP->>DB: UoW commit · Run ANALYZING 또는 PLANNING → RETRIEVING
        DB-->>APP: COMMIT 또는 already RETRIEVING
        SUP->>RET: User Request + Intent + ToolRoutePlanV2.input_plan.input_routes + budget
        RET->>LLM: plan_query PromptRef
        LLM-->>RET: RetrievalQueryPlanV2
        RET->>RET: deterministic Query Builder
        loop 필요한 Input Route/페이지/상세만
            RET->>APP: retrieval.execute_read<br>validated query + allowed_read_tool_ids
            APP->>MCP: ConnectorReadPort call
            MCP->>G: Source-native API
            G-->>MCP: Metadata / Detail Result
            MCP-->>APP: Typed Read Result
            APP-->>RET: normalized read result
        end
        opt Calendar availability 계산 필요
            RET->>RET: deterministic FreeBusy interval normalize/subtract<br>AvailableIntervalV1[]
        end
        RET->>RET: normalize + segment + source security metadata
        RET->>RET: Run-scoped RAG retrieve/rerank
        RET->>LLM: select_evidence / assess_sufficiency
        LLM-->>RET: Evidence + Sufficiency candidate
        RET->>RET: Validate / finalize
        RET-->>SUP: RetrievalResultV1
        SUP->>CP: RETRIEVAL Checkpoint
    end

    alt effective analysis required = semantic REQUIRED or Policy Precondition
        SUP->>ANA: User Request + Intent + optional RetrievalResult/Evidence Projection
        ANA->>LLM: extract_work_facts PromptRef
        LLM-->>ANA: WorkFacts candidate
        opt entity relation analysis required
            ANA->>LLM: resolve_entity_relations PromptRef
            LLM-->>ANA: Entity relation candidates
        end
        opt temporal/dependency analysis required
            ANA->>LLM: resolve_temporal_dependencies PromptRef
            LLM-->>ANA: Temporal/dependency candidates
        end
        opt duplicate/conflict analysis required
            ANA->>LLM: detect_duplicate_conflict_candidates PromptRef
            LLM-->>ANA: Duplicate/conflict candidates
        end
        ANA->>ANA: deterministic validate_relations
        ANA->>LLM: assess_information_gaps PromptRef
        LLM-->>ANA: Information-gap candidate
        opt operational risk analysis required
            ANA->>LLM: assess_operational_risks PromptRef
            LLM-->>ANA: Operational-risk candidate
        end
        ANA->>ANA: deterministic assemble_work_analysis + validate_work_analysis
        alt exact duplicate default stop
            ANA-->>SUP: WorkAnalysisResultV2<br>action_necessity=NOT_REQUIRED
        else duplicate/conflict override requires confirmation
            ANA-->>SUP: NEEDS_CONFIRMATION<br>DUPLICATE_OVERRIDE_REQUIRED or CONFLICT_OVERRIDE_REQUIRED
            SUP-->>U: 2차 확인 interrupt
            U-->>CONFCTL: override 승인/거절
            CONFCTL->>DB: PolicyConfirmationReceiptV1 + POLICY_CONFIRMATION_RECORDED
            CONFCTL->>SUP: validated receipt + interrupt resume
            SUP->>ANA: same owner checkpoint resume
            alt receipt decision = APPROVED
                ANA->>ANA: confirmed override를 현재 relation/evidence Context에 결합
                ANA-->>SUP: WorkAnalysisResultV2<br>action_necessity=REQUIRED + override receipt ref
            else receipt decision = DECLINED
                ANA-->>SUP: WorkAnalysisResultV2<br>action_necessity=NOT_REQUIRED
            end
        else no blocking relation
            ANA->>ANA: typed local state + validate
            ANA-->>SUP: WorkAnalysisResultV2<br>including action_necessity
        end
    else semantic NONE and no Policy Precondition analysis
        SUP->>SUP: Work Analysis skip
    end

    SUP->>APP: begin_planning(command)
    APP->>DOM: BeginPlanning(expected_version)
    APP->>DB: UoW commit · Run ANALYZING 또는 RETRIEVING → PLANNING
    DB-->>APP: COMMIT 또는 already PLANNING
    SUP->>PLAN: User Request + Intent + ToolRoutePlanV2.output_plan + optional Analysis + Evidence refs
    alt output_mode = ANSWER
        PLAN->>LLM: compose_answer PromptRef
        LLM-->>PLAN: AnswerDraftV2
        PLAN-->>SUP: AnswerDraftV2
    else output_mode = ACTION and analysis.action_necessity = NOT_REQUIRED
        PLAN->>LLM: compose evidence-backed no-action answer
        LLM-->>PLAN: AnswerDraftV2
        PLAN-->>SUP: AnswerDraftV2<br>새 Action 0
    else output_mode = ACTION
        loop Output Route별
            PLAN->>LLM: user request + fixed OUT route의 selected_tool schema + optional analysis + evidence
            LLM-->>PLAN: Tool Arguments candidate
        end
        PLAN->>PLAN: deterministic build_dependencies + assemble_plan + validate_plan
        PLAN-->>SUP: ActionPlanDraftV2
        SUP->>REV: Intent + Plan + Evidence/Policy Projection
        REV->>LLM: inspect_goal_and_evidence / inspect_action_scope_and_route / inspect_constraints_and_policy_summary PromptRef(s)
        LLM-->>REV: dimension finding(s)
        REV->>REV: deterministic aggregate_review_findings + validate_review
        REV->>REV: deterministic map + validate
        REV-->>SUP: PlanReviewResultV2
    end
```

- Supervisor는 Agent Subgraph 단위로 Routing하고 Agent 내부 Node를 직접 호출하지 않는다.
- Tool Route는 한 번 Main State에 저장되며 Retrieval·Planning이 Tool 종류를 다시 선택하지 않는다. Output Route는 요청된 capability를 고정하지만 Retrieval/Analysis에서 목표가 이미 충족된 정확 중복·동일 상태를 확인하면 Planning은 Route를 바꾸지 않고 새 Action 0개의 Evidence 기반 Answer로 종료할 수 있다. `InputRoutePlanV1`과 `OutputPlanV1`은 독립 revision/based_on을 가져 OUT-only 변경이 기존 Retrieval을 불필요하게 재실행시키지 않는다.
- Retrieval은 고정 IN Route 안에서 Query→Read→Run-scoped RAG→Evidence→Sufficiency를 완료한다.
- Planning은 고정 OUT Route의 `selected_tool_id`와 해당 Tool Schema만 사용해 Arguments를 작성한다.
- Query candidate·Page Token·RAG score·LLM candidate는 Subgraph Local State/Run Cache에 두고 Parent에는 공식 Typed Result와 필요한 Typed Workflow Signal만 반환한다.

## 7. RESOURCE_SELECTED 요청 시퀀스

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자
    participant FE as React 프런트엔드
    participant API as FastAPI
    participant APP as Application
    participant DOM as Domain
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant SUP as Supervisor
    participant REQ as Request Understanding Subgraph
    participant ROUTE as Tool Route Subgraph
    participant RET as Retrieval Subgraph
    participant LLM as Prompt Registry·LLM Router
    participant MCP as ConnectorReadPort
    participant G as Google APIs

    U->>FE: Gmail·Task·Event 선택 후 요청
    FE->>API: POST /api/v1/runs<br>selected_resource_handles·command_id
    API->>APP: start_run(command)<br>selected_resource_handles signature/session/account 검증·resolve → StartRun UoW ResourceRef materialize
    APP->>DOM: StartRun(command_id·canonical request hash)
    APP->>DB: UoW commit · Receipt 검증 + Open Run Guard + Run CREATED·User Message INSERT<br>같은 Transaction
    DB-->>APP: COMMIT · applied=true·run_id·version
    APP->>SUP: durable START handoff → WorkflowExecutionPort<br>RunInputV1.selected_resource_refs
    SUP->>REQ: RESOURCE_SELECTED Input Projection
    REQ->>LLM: goal/ambiguity PromptRef
    LLM-->>REQ: RequestIntentV2
    REQ-->>SUP: RequestIntentV2

    SUP->>ROUTE: Intent + selected resource hints + Registry
    ROUTE-->>SUP: ToolRoutePlanV2<br>선택 Resource를 IN Route에 고정

    SUP->>RET: Intent + fixed input route + selected resource IDs
    loop Source별 선택 ID
        RET->>APP: retrieval.execute_read<br>validated ID GET
        APP->>MCP: ConnectorReadPort call
        MCP->>G: Resource GET
        G-->>MCP: 최신 Resource
        MCP-->>APP: Typed Detail Result
        APP-->>RET: normalized detail result
    end
    RET->>RET: normalize/segment + RAG + Evidence/Sufficiency
    RET-->>SUP: RetrievalResultV1

    opt 같은 IN Route 안에서 추가 상세/페이지 필요
        SUP->>RET: prior RetrievalResult refs + bounded additional request
        RET-->>SUP: revised RetrievalResultV1
    end

    opt 새로운 Resource/Connector Route 필요
        RET-->>SUP: ROUTE_RECONSIDERATION_REQUIRED<br>RouteReconsiderationRequiredV1
        SUP->>ROUTE: prior route + missing requirement
        ROUTE-->>SUP: new ToolRoutePlanV2 revision
    end
```

- 선택 Resource를 검색 Query로 다시 추측하지 않고 최신 상세 GET한다.
- 추가 조회가 같은 IN Route 안이면 Retrieval Subgraph 재진입, 새 Resource/Connector가 필요하면 Tool Route Back-edge다.
- 이전 Subgraph Local State를 장기 Memory처럼 재사용하지 않고 Parent의 공식 Result와 Run Cache Handle만 사용한다.

## 8. 추가 Retrieval과 사용자 확인 Interrupt

```mermaid
sequenceDiagram
    autonumber
    participant RET as Retrieval Subgraph
    participant ANA as Work Analysis Subgraph
    participant REV as Review Subgraph
    participant SUP as Supervisor
    participant ROUTE as Tool Route Subgraph
    participant APP as Application
    participant DOM as Domain
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant CP as CheckpointPort
    participant API as FastAPI
    participant FE as React 프런트엔드
    actor U as 사용자

    RET-->>SUP: disposition + optional WorkflowSignalV1
    alt 같은 IN Route에서 추가 Retrieval 가능
        SUP->>RET: bounded additional retrieval request + prior official refs
        RET-->>SUP: revised RetrievalResultV1
    else 새 Resource/Connector Route 필요
        SUP->>ROUTE: route reconsideration request
        ROUTE-->>SUP: ToolRoutePlanV2 new revision
        SUP->>SUP: route 의존 downstream state stale 처리
        SUP->>RET: new input route projection
    else 사용자만 해결 가능한 모호성
        SUP-->>APP: NEEDS_CONFIRMATION + semantic_owner_id + AgentNodeResumeTargetV2
        APP->>DOM: RequestConfirmation
        APP->>DB: UoW commit · WAITING_CONFIRMATION + Receipt/Audit
        DB-->>APP: COMMIT · applied=true
        APP->>SUP: interrupt 생성<br>owner + resume target + interrupt_id
        SUP->>CP: same-run checkpoint 저장
        SUP-->>API: confirmation_required Projection
        API-->>FE: 확인 질문 Card
        U->>FE: 후보 선택·추가 정보
        FE->>API: confirm command
        API->>APP: resume_confirmation(command)
        APP->>DOM: ResumeConfirmation
        APP->>DB: UoW commit · 발생 전 안전 Domain 상태 복원
        DB-->>APP: COMMIT · applied=true
        APP->>DB: Confirmation control + durable handoff commit
        APP->>SUP: WorkflowExecutionPort → same owner checkpoint resume
    else Budget 소진
        SUP->>SUP: PARTIAL 또는 BLOCKED Guard
        opt PARTIAL + usable Evidence
            SUP->>SUP: analysis_requirement에 따라 Work Analysis 또는 Planning으로 계속
        end
    end

    ANA-->>SUP: NEEDS_MORE_DATA 가능
    alt current InputRoutePlan has route
        SUP->>RET: RetrievalRequiredV1 projection
    else current InputRoutePlan has no route / new Route required
        ANA-->>SUP: ROUTE_RECONSIDERATION_REQUIRED + RouteReconsiderationRequiredV1
        SUP->>ROUTE: current RequestIntentV2 + route reconsideration signal
    end
    REV-->>SUP: RETRIEVE_MORE 가능
    alt current InputRoutePlan has route
        SUP->>RET: RetrievalRequiredV1 projection from EvidenceGapV1
    else current InputRoutePlan has no route / new Route required
        REV-->>SUP: ROUTE_RECONSIDERATION + RouteReconsiderationRequiredV1
        SUP->>ROUTE: current RequestIntentV2 + route reconsideration signal
    end
```

- 새 Route가 필요하지 않은 Query/Page/Detail 확장은 Retrieval 책임이다. Retrieval 자신의 `NEEDS_MORE_DATA`는 local loop이며 `RetrievalRequiredV1`을 만들지 않는다.
- Work Analysis `NEEDS_MORE_DATA`와 Review `RETRIEVE_MORE`만 현재 IN Route에서 해결 가능한 요구를 `RetrievalRequiredV1`으로 투영한다. 새 Route가 필요하면 Tool Route로 back-edge한다.
- Tool Route revision이 바뀌면 해당 Route에 의존한 Retrieval·Analysis·Planning·Review 결과를 stale 처리하고 다시 생성한다.
- 사용자 Context Adjustment는 `WAITING_APPROVAL`에서 아직 어떤 Action도 승인되지 않았고 in-flight 실행이 0일 때만 허용한다. `run.adjust_context`는 expected Run/Retrieval revision과 Preview membership을 검증하고 `BeginPlanning(USER_CONTEXT_ADJUSTMENT)`으로 current Plan을 `SUPERSEDED`한 뒤 same Run을 Retrieval로 재진입시킨다. `EXCLUDE_EVIDENCE`는 new selection에서 selected segment를 제외하고, `RETRIEVE_MORE`는 `RetrievalNeedV1(USER_CONTEXT_ADJUSTMENT)`로 추가 조회한다. 새 Retrieval revision에 의존하지 않는 기존 Analysis/Plan/Review는 stale이므로 재사용하지 않는다.
- Agent가 다른 Agent를 직접 호출하지 않는다.


### 8.1 Context Adjustment exact re-entry

```text
EXCLUDE_EVIDENCE
→ BeginPlanning(USER_CONTEXT_ADJUSTMENT) + Plan SUPERSEDED + WorkflowHandoff(PENDING) same-UoW commit
→ post-commit handoff MAIN_CONTROL:RETRIEVAL_ENTRY / ContextAdjustmentV1
→ fresh retrieval from frozen input routes
→ exclusion applied at select_evidence
→ new RetrievalHeadV1/revision

RETRIEVE_MORE
→ same lifecycle + WorkflowHandoff(PENDING) commit boundary
→ post-commit handoff MAIN_CONTROL:RETRIEVAL_ENTRY / ContextAdjustmentV1.retrieval_need
→ retrieval.plan_query consumes bounded USER_CONTEXT_ADJUSTMENT need
→ new RetrievalHeadV1/revision
```

둘 다 raw HTTP body나 Browser-mutated `excluded_segment_ids`를 checkpoint에 주입하지 않는다.

## 9. Answer-only Run 완료

```mermaid
sequenceDiagram
    autonumber
    participant PLAN as Planning Subgraph
    participant SUP as Supervisor
    participant APP as Application
    participant DOM as Domain
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant API as FastAPI
    participant FE as React 프런트엔드

    PLAN-->>SUP: ANSWER_ONLY·AnswerDraftV2
    SUP->>APP: build_terminal_message(AnswerDraftV2)
    APP-->>SUP: TerminalAssistantMessageInputV1 + COMPLETE_ANSWER_ONLY intent
    SUP->>APP: terminal_commit(COMPLETE_ANSWER_ONLY)
    APP->>DOM: CompleteAnswerOnlyRun + Open Action·Recovery Guard
    APP->>DB: UoW commit · Receipt·Run COMPLETED·final ASSISTANT Message·required Audit<br>같은 Transaction
    DB-->>APP: COMMIT · applied=true
    APP-->>SUP: applied=true
    SUP-->>API: completed Projection
    API-->>FE: 최종 답변·COMPLETED
```

Answer-only Run에는 Plan·Action·Approval·Attempt·Verification Row를 만들지 않는다.

## 10. Legacy/호환 READ-only Plan 실행

```mermaid
sequenceDiagram
    autonumber
    participant SUP as Supervisor
    participant APP as Application
    participant DOM as Domain
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant MCP as ConnectorReadPort
    participant G as Google APIs
    participant API as FastAPI
    participant FE as React 프런트엔드

    SUP->>APP: publish_read_only_plan<br>Legacy READ Action만 포함
    APP->>DOM: PublishReadOnlyPlan + Tool·Evidence·Dependency 검증
    APP->>DB: UoW commit · Receipt·Plan ACTIVE·READ Action PROPOSED 저장<br>Run PLANNING → EXECUTING · 같은 Transaction
    DB-->>APP: COMMIT · applied=true·ALLOW_READ

    loop 실행 가능한 READ Action
        APP->>DOM: claim_read_action(expected_version)
        APP->>DB: UoW commit · PROPOSED → EXECUTING
        DB-->>APP: COMMIT · applied=true
        APP->>MCP: 검증된 Read Tool
        MCP->>G: Google 조회
        G-->>MCP: Read Result
        MCP-->>APP: Typed Output
        alt Output Schema 정상
            APP->>DOM: complete_read_action
            APP->>DB: UoW commit · EXECUTING → EXECUTED
            APP->>APP: 결과를 응답·후속 판단에 반영
            APP->>DOM: finalize_read_action
            APP->>DB: UoW commit · EXECUTED → VERIFIED
        else 복구 불가능한 Read 실패
            APP->>DOM: fail_read_action
            APP->>DB: UoW commit · EXECUTING → FAILED
        end
    end

    APP->>DOM: CompleteReadOnlyRun(expected_version)
    APP->>DB: UoW commit · Plan ACTIVE → COMPLETED<br>Run EXECUTING → COMPLETED · final Message/Audit atomic
    API-->>FE: action_status·completed
```

- READ `VERIFIED`는 Output Schema Validation과 결과 반영 완료를 의미한다.
- Write Verification 지표에 포함하지 않는다.
- Legacy READ 중 Google/MCP가 `AUTH_EXPIRED`를 반환하면 `Run=EXECUTING + current READ Action=EXECUTING + ExecutionAttempt row 없음`을 검증한 뒤 `RequireReauth`가 `MAIN_CONTROL:READ_EXECUTION`을 등록한다. OAuth 완료 후 `ResumeAfterReauth(applied=true)`가 같은 Run/Action/route binding을 검증한 경우에만 **동일 non-mutating READ 호출을 재개**한다. 이 경로에서 Approval/ExecutionAttempt/ConnectorWritePort 생성·호출은 0이다.
- Legacy READ가 아닌 승인형 Write에서는 `READ_EXECUTION` target을 사용할 수 없다.

## 11. WRITE Plan 저장·승인·실행·검증

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자
    participant FE as React 프런트엔드
    participant API as FastAPI
    participant APP as Application
    participant DOM as Domain
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant SUP as Supervisor
    participant MCP as ConnectorWritePort · ConnectorReadPort
    participant G as Google APIs

    SUP->>APP: publish_plan(command)
    APP->>APP: Schema Validator · Tool/Argument/Output Schema validation
    APP->>APP: Policy Validator · allowlist/effect/policy preconditions validation
    APP->>APP: Semantic Validator · Evidence binding·DAG·중복·충돌 validation
    APP->>DOM: PublishPlan guard · expected_version·source status·review freshness
    APP->>DB: UoW commit · Receipt·Plan·Action·Dependency·Evidence 저장<br>Run PLANNING → WAITING_APPROVAL · 같은 Transaction
    DB-->>APP: COMMIT · applied=true·REQUIRE_APPROVAL
    API-->>FE: plan_updated·approval_required

    U->>FE: Action 승인
    FE->>API: POST /api/v1/actions/{action_id}/approve<br>command_id·expected_version
    API->>APP: approve_action
    APP->>APP: validate_action_arguments · current registered Tool Schema 검증
    APP->>APP: evaluate_action_policy · allow/deny/confirmation requirement + current PolicyConfirmationReceiptV1 freshness 검증
    APP->>DOM: ApproveAction guard · Action state/version · Review freshness · canonical snapshot binding 검증
    APP->>DB: UoW commit · BEGIN IMMEDIATE
    APP->>DB: UoW stage · Approval ACTIVE INSERT<br>Canonical Snapshot에 required receipt ref + decision_context_hash 포함<br>Action APPROVED
    APP->>DB: UoW stage · WorkflowHandoff(PENDING, target=MAIN_CONTROL:PREFLIGHT)
    APP->>DB: UoW commit · COMMIT
    DB-->>APP: COMMIT · applied=true + handoff_id
    APP->>SUP: post-commit schedule_run_execution(handoff_id) → WorkflowExecutionPort → MAIN_CONTROL:PREFLIGHT

    SUP->>APP: 실행 전 최신 Source 조회
    APP->>MCP: GET 대상·중복·충돌 자료
    MCP->>G: Google GET
    G-->>MCP: 최신 Resource
    MCP-->>APP: Current Snapshot
    APP->>APP: validate_action_arguments · final server dispatch args schema 검증
    APP->>APP: evaluate_action_policy · current policy 재평가
    APP->>APP: source/schema/policy/approval snapshot freshness + approved arguments hash 비교
    APP->>DOM: ClaimExecution guard · state/version/active Approval + current published Plan(WAITING_APPROVAL) + Run(WAITING_APPROVAL|VERIFYING) + cancel/UNKNOWN_RESULT preconditions

    alt 승인 유효·인자·Source binding 일치
        APP->>DOM: ClaimExecution(command)
        APP->>DB: UoW commit · BEGIN IMMEDIATE
        APP->>DB: UoW commit · APPROVED → EXECUTING<br>Approval CONSUMED<br>Attempt CLAIMED
        APP->>DB: UoW commit · COMMIT
        DB-->>APP: COMMIT · applied=true
        APP->>APP: build_claim_context · approved snapshot ↔ final dispatch args hash
        APP->>DOM: BeginExecutionAttempt(command)
        APP->>DB: UoW commit · Attempt CLAIMED → EXECUTING · Audit
        DB-->>APP: COMMIT · applied=true
        APP->>MCP: 승인된 Write Tool·고정 Arguments
        MCP->>G: CREATE 또는 UPDATE
        G-->>MCP: Resource ID·Metadata
        MCP-->>APP: Write Result
        APP->>DOM: store_success
        APP->>DB: UoW commit · Attempt SUCCEEDED·Action EXECUTED
        opt Run이 아직 VERIFYING이 아님
            APP->>DOM: begin_verification
            APP->>DB: UoW commit · Run WAITING_APPROVAL | CANCEL_REQUESTED → VERIFYING
        end
        APP->>MCP: 대응 GET Tool
        MCP->>G: 생성·수정 Resource 재조회
        G-->>MCP: Actual Resource
        MCP-->>APP: Typed Actual
        APP->>APP: expected·actual 정상화·비교
        APP->>DOM: store_verification
        APP->>DB: UoW commit · Verification INSERT<br>VERIFIED 또는 MISMATCH
        alt VERIFIED + 다음 실행 가능한 Action 존재
            APP->>DOM: Dependency 재계산
            DOM-->>APP: next executable action
        else VERIFIED + 모든 승인 대상 Action Terminal + 미해결 결과 없음
            APP->>APP: build_terminal_message(verified Plan/Action summary)
            APP->>DOM: CompleteWriteRun
            APP->>DB: UoW commit · Run VERIFYING → COMPLETED·Plan COMPLETED<br>final ASSISTANT Message·required Audit
        else MISMATCH
            APP->>DOM: RequireRecovery(VERIFICATION_MISMATCH)
            APP->>DB: UoW commit · Run VERIFYING → RECOVERY_REQUIRED + Receipt/Audit
        end
    else Approval TTL 만료 또는 Source/Policy/Tool-Schema/approval snapshot stale
        APP->>DOM: ExpireApproval
        APP->>DB: UoW commit · Action APPROVED → EXPIRED + Approval ACTIVE → EXPIRED
        APP->>DOM: RefreshExpiredAction
        APP->>DB: UoW stage · Action EXPIRED → MODIFIED + review gate REQUIRED
        APP->>DB: UoW stage · WorkflowHandoff(PENDING, target=MAIN_CONTROL:REVIEW_ENTRY)
        APP->>DB: COMMIT
        DB-->>APP: COMMIT · applied=true + handoff_id
        APP->>SUP: post-commit schedule_run_execution(handoff_id) → WorkflowExecutionPort → MAIN_CONTROL:REVIEW_ENTRY
        API-->>FE: 재검토 진행·fresh PASS 뒤 재승인 필요
    else current deterministic Policy = DENY
        APP->>APP: build_terminal_message(BLOCKED + policy reason codes)
        APP->>DOM: BlockRun
        APP->>DB: UoW commit · pending Action BLOCKED·Approval REVOKED·Plan CANCELLED·Run BLOCKED<br>final ASSISTANT Message·required Audit
        API-->>FE: blocked
    end
```

외부 Write와 GET 수행 중 DB Transaction을 유지하지 않는다.

### 11.1 Google Task 날짜·시간 의미

```
Gmail·사용자 요청에서 업무 마감만 확인
→ Request Understanding: business_deadline 후보
→ Task scheduled_date 없음
→ Plan: notes·Evidence·Approval Summary에 업무 마감 보존 제안
→ 사용자 Approval
→ tasks_create_task(due 없음)
→ GET Verification: 제목·notes·예정일 부재 비교

사용자가 수행 예정일도 명시
→ Request Understanding: scheduled_date 후보
→ 승인된 tasks_create_task(due = scheduled_date)
→ GET Verification: 예정일 비교

정확한 시간 구간 요청
→ Tasks 시간 설정 성공 선언 금지
→ 날짜 예정일 또는 별도 승인형 Calendar Event 대안 제시
```

Provider `needsAction`·`completed`는 Local API Projection에서 사용자 상태 `미완료`·`완료`로 정규화한다. 예정일 경과는 상태 전이나 자동 완료 시퀀스를 만들지 않는다.

## 12. 일부 승인과 Action DAG

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자
    participant FE as React 프런트엔드
    participant API as FastAPI Route Adapter
    participant APP as Application
    participant DOM as Domain
    participant DB as Application UoW · Repository Ports → SQLite Adapter

    U->>FE: 일부 Action 승인·일부 거절
    FE->>API: approve·reject Commands
    API->>APP: validated approve_action / reject_action
    APP->>DOM: Action별 조건부 전이
    APP->>DB: 각 applied Approve/Reject UoW에 승인·거절·Audit + WorkflowHandoff(PENDING, target=PREFLIGHT, server-owned run_sequence) 원자 stage/commit
    APP->>APP: 각 committed handoff_id를 post-commit schedule_run_execution; non-head sequence는 PENDING 유지
    APP->>APP: lower sequence settle 후 live reconciler/worker-boundary wake가 durable dispatch head를 다시 Application schedule boundary로 제출
    APP->>DOM: PREFLIGHT에서 현재 aggregate 전체를 다시 읽어 Dependency/terminal reconciliation 재계산
    DOM-->>APP: executable_actions·blocked_actions 또는 all-final terminal result

    loop 독립 또는 선행 VERIFIED Action
        APP->>DOM: 실행 가능 여부·Dependency 확인
        DOM-->>APP: ALLOW + next_allowed_commands
        APP->>APP: canonical ClaimExecution → build ClaimContext → BeginExecutionAttempt COMMIT → Connector Write → Verification orchestration 재사용
    end

    opt RejectAction이 적용된 Action의 미실행 dependent 존재
        Note over APP,DB: RejectAction의 동일 UoW가 transitive dependent를 DEPENDENCY_BLOCKED로 닫고 ACTIVE Approval을 revoke한다. 별도 block_by_dependency Command는 없다.
    end

    opt predecessor가 FAILED
        Note over APP,DOM: FAILED는 retry/cancel decision state다. dependent는 terminalize하지 않고 predecessor VERIFIED 전까지 Claim만 차단한다.
    end

    APP-->>FE: 부분 실행 결과·종속 영향
```

- `FAILED + NOT_SENT` Action이 생겨도 dependency가 없는 approved/executable Action이 남아 있으면 그 Action의 `PREFLIGHT`로 계속 진행한다. FAILED predecessor에 의존하는 Action은 Claim 0이다. 독립 Action까지 모두 처리한 뒤 unresolved `FAILED + NOT_SENT`가 남으면 그때 retry/cancel decision으로 suspend하며 `CompleteWriteRun`하지 않는다.
- 성공한 Action은 자동 롤백하지 않는다.
- 종속 Action은 선행 Action의 `VERIFIED` 또는 계약된 성공 조건 이후에만 실행한다.

## 13. 승인 수정·거절·만료

모든 Action mutation/Approval/Claim은 State Contract의 **Plan supersession child-authority fence**를 소비한다. owning Plan이 `SUPERSEDED`이면 old Action은 history projection일 뿐이며 approve/modify/reject/cancel/expire/refresh/retry/claim mutation은 effect 0이다. published Plan back-edge가 supersession을 commit할 때 old ACTIVE Approval revoke가 같은 UoW에 포함되므로 늦게 도착한 old HTTP command가 실행권을 되살릴 수 없다.

Action Reject는 `PROPOSED·MODIFIED·APPROVED → REJECTED`만 허용한다. APPROVED Reject는 기존 ACTIVE Approval을 삭제하지 않고 `REVOKED`로 보존한다. Reject와 `ACTION_REJECTED` Audit, 미실행 transitive dependent의 `DEPENDENCY_BLOCKED`, dependent ACTIVE Approval revoke는 하나의 UoW에서 commit한다. 모든 Action이 final fact로 닫히고 unresolved가 0이면 Application이 `CompleteWriteRun`을 적용해 Plan/Run을 `COMPLETED`로 확정하고, 독립적인 미완료 Action이 있으면 계속 진행한다. 외부 Write가 한 건도 시작되지 않은 all-rejected/all-cancelled Plan은 State Contract에 따라 `WAITING_APPROVAL → COMPLETED`로 닫을 수 있다. 외부 Google/MCP Write와 새 ExecutionAttempt는 생성하지 않는다.

### 13.1 사용자 수정

Action 수정이 실제 Canonical Arguments를 변경하면 기존 Approval을 revoke한 뒤 같은 Transaction에서 Plan Review를 `REQUIRED`로 무효화한다. Commit 이후 기존 Profile의 Plan Review를 다시 실행하고, 06의 deterministic `validate_review` PASS를 Application `plan.record_review_result`가 `RecordReviewResultCommandV1`으로 current Plan/Action revision에 조건부 기록한 뒤 Domain Validation이 성공한 경우에만 새 Approval을 허용한다. Review 중 후속 Modify가 발생하면 `expected_plan_version`/bound Action version mismatch로 writer가 conflict를 반환하며 이전 Review 결과는 durable PASS가 되지 않는다.

published Plan 재검토는 State Transition Contract의 post-review matrix를 그대로 사용한다. `REVISE | RETRIEVE_MORE | ROUTE_RECONSIDERATION`은 `WAITING_APPROVAL | VERIFYING`에서 guard가 허용될 때 `BeginPlanning` UoW에서 old Plan의 `ACTIVE` Approval을 먼저 `REVOKED`로 닫고 current Plan을 `SUPERSEDED` 처리한 뒤 Run을 `PLANNING`으로 되돌려 필요한 Planning/Retrieval/Tool Route 경로를 재사용한다. supersession commit 이후 old Plan child는 history-only이며 approve/modify/retry/claim으로 실행권을 복구할 수 없다. 이미 성공·검증된 외부 효과와 immutable final Action facts는 보존한다. `CONFIRM`은 guarded `RequestConfirmation`, `BLOCK`은 guarded `BlockRun`만 사용할 수 있다. unresolved in-flight/UNKNOWN_RESULT/MISMATCH가 있으면 이 back-edge/block 대신 해당 Recovery/reauth/cancel resolution을 먼저 완료한다. 후속 PASS는 기존 Plan의 gate를 다시 열지 않고 새 revision을 저장하며 새 Action에 대해 Approval을 다시 받아야 한다.

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자
    participant FE as React 프런트엔드
    participant API as FastAPI
    participant APP as Application
    participant DOM as Domain
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant SUP as Supervisor

    U->>FE: Action 내용 수정
    FE->>API: POST /api/v1/actions/{action_id}/modify
    API->>APP: modify_action
    APP->>APP: modify patch allowlist + validate_action_arguments
    APP->>APP: evaluate_action_policy · modified candidate의 deterministic policy requirement 계산
    APP->>DOM: ModifyAction guard · source state/version/current aggregate invariant
    APP->>DB: UoW stage · PROPOSED 또는 APPROVED → MODIFIED<br>Version 증가·기존 Approval REVOKED + Review REQUIRED
    APP->>DB: UoW stage · WorkflowHandoff(PENDING, target=MAIN_CONTROL:REVIEW_ENTRY)
    APP->>DB: COMMIT
    DB-->>APP: COMMIT · applied=true + handoff_id
    APP->>SUP: post-commit schedule_run_execution(handoff_id) → WorkflowExecutionPort → MAIN_CONTROL:REVIEW_ENTRY
    SUP-->>API: plan_updated
    API-->>FE: 수정 결과·새 승인 필요
```

### 13.2 승인 만료

```
Approval 유효 시간 경과 또는 Source·Policy·Tool Schema 변경
→ ExpireApproval COMMIT · Action/Approval EXPIRED
→ refresh_expired_action UoW · 최신 Source·Policy/Schema snapshot 재계산
→ Action MODIFIED + review REQUIRED + WorkflowHandoff(PENDING, REVIEW_ENTRY) same COMMIT
→ post-commit durable Review continuation
→ current revision fresh Review PASS
→ 새 Approval snapshot/idempotency authority
→ 사용자 재승인
```

기존 Approval을 다시 `ACTIVE`로 만들지 않는다.

## 14. Write 실패와 명시적 재시도

```mermaid
sequenceDiagram
    autonumber
    participant APP as Application
    participant DOM as Domain
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant API as FastAPI
    participant FE as React 프런트엔드
    actor U as 사용자
    participant SUP as Supervisor

    APP->>DOM: mark_failed<br>Google 미변경이 확실한 오류
    APP->>DB: UoW commit · Attempt FAILED·Action FAILED
    DOM-->>APP: retry_eligible·reason
    API-->>FE: 실패 결과·재시도 준비 가능

    U->>FE: 다시 시도 선택
    FE->>API: Retry 준비 Command
    API->>APP: prepare_write_retry
    APP->>DOM: 오류 유형·현재 상태·Dependency 검증
    APP->>DB: UoW stage · FAILED → MODIFIED<br>Version 증가 + Review REQUIRED
    APP->>DB: UoW stage · WorkflowHandoff(PENDING, target=MAIN_CONTROL:REVIEW_ENTRY)
    APP->>DB: COMMIT
    DOM-->>APP: 새 Approval 필요 + handoff_id
    APP->>SUP: post-commit schedule_run_execution(handoff_id) → WorkflowExecutionPort → MAIN_CONTROL:REVIEW_ENTRY
    SUP-->>API: approval_required
    API-->>FE: 변경 내용 확인·재승인
```

금지 전이:

```
FAILED → EXECUTING
UNKNOWN_RESULT → EXECUTING
```

재시도는 새 Approval, 새 Idempotency Key, 최신 Source Snapshot과 새 ExecutionAttempt ID를 사용하며 새 Approval의 `attempt_no`는 1로 시작한다.

## 15. Write 응답 유실·UNKNOWN_RESULT 복구

```mermaid
sequenceDiagram
    autonumber
    participant APP as Application
    participant MCP as ConnectorWritePort
    participant G as Google APIs
    participant DOM as Domain
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant API as FastAPI
    participant FE as React 프런트엔드

    APP->>MCP: 승인된 Write 호출
    MCP->>G: CREATE 또는 UPDATE
    G--xMCP: 응답 유실·Timeout·Transport 종료
    MCP-->>APP: UNKNOWN_RESULT
    APP->>DOM: mark_unknown_result
    APP->>DB: UoW commit · Attempt·Action UNKNOWN_RESULT
    API-->>FE: 실제 결과 확인 중

    Note over APP,DB: 새 Attempt·새 Write 금지

    alt CREATE
        APP->>MCP: RESOURCE_SEARCH · Recovery Fingerprint로 Resource Search
        MCP->>G: 후보 검색·상세 GET
    else UPDATE
        APP->>MCP: GET_TARGET · 대상 Resource GET
        MCP->>G: 현재 대상 조회
    else SEND
        APP->>MCP: MESSAGE_SEARCH · 기존 전송 결과 후보 검색
        MCP->>G: Sent 결과 후보 조회
    else DELETE
        APP->>MCP: GET_TARGET · 삭제 대상 상태 조회
        MCP->>G: 대상 존재/부재 조회
    end
    G-->>MCP: 기존 결과 후보 또는 미발견
    MCP-->>APP: Resolve Result

    alt 실행 결과 확인
        APP->>DOM: recover_existing_result
        APP->>DB: UoW commit · UNKNOWN_RESULT → EXECUTED
        alt Run = WAITING_APPROVAL | CANCEL_REQUESTED
            APP->>DOM: BeginVerification
            APP->>DB: UoW commit · Run → VERIFYING
        else Run = RECOVERY_REQUIRED
            APP->>DOM: ResolveRecovery(RECHECK) with changed external-state fingerprint
            APP->>DB: UoW commit · RECOVERY_REQUIRED → VERIFYING
        end
        APP->>APP: verification.verify_effect · expected·actual 비교
        APP->>DOM: store_verification
        APP->>DB: UoW commit · VERIFIED 또는 MISMATCH
        opt Verification = MISMATCH
            APP->>DOM: RequireRecovery(VERIFICATION_MISMATCH)
            APP->>DB: UoW commit · Run → RECOVERY_REQUIRED + Receipt/Audit
        end
    else 미실행이 확실
        APP->>DOM: ResolveAsFailed
        APP->>DB: UoW commit · UNKNOWN_RESULT → FAILED
        alt Run = RECOVERY_REQUIRED
            APP->>DOM: ResolveRecovery(RECHECK) with changed lookup fingerprint
            APP->>DB: UoW commit · RECOVERY_REQUIRED → saved pre_recovery_status
        else Run = WAITING_APPROVAL | CANCEL_REQUESTED | VERIFYING
            Note over APP,DOM: Run lifecycle command 0; Action FAILED fact만 반영
        end
        APP->>APP: FAILED fact 보존 · Verification 없음<br/>독립 approved/executable Action이 있으면 다음 PREFLIGHT, 없으면 retry/cancel decision suspend
    else 불명확 지속
        APP->>DOM: RequireRecovery(UNKNOWN_RESULT) unless already RECOVERY_REQUIRED
        APP->>DB: UoW commit · Run RECOVERY_REQUIRED + durable recovery context
        API-->>FE: 사용자 복구 선택 Card
    end
```

`NOT_FOUND` 한 번만으로 CREATE 미실행을 확정하지 않는다. 검색 범위·일관성 지연·권한 오류를 함께 판단한다.

## 16. OAuth 만료와 재인증 후 재개

```mermaid
sequenceDiagram
    autonumber
    participant MCP as OAuthCredentialPort · MCP Credential Provider
    participant G as Google OAuth·API
    participant APP as Application · connection use case
    participant DOM as Domain
    participant REP as Domain Repository Ports
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant CP as CheckpointPort
    participant API as FastAPI
    participant FE as React 프런트엔드
    actor U as 사용자
    participant SUP as Supervisor
    participant K as OS Keyring

    MCP->>G: Google API 호출
    G-->>MCP: AUTH_EXPIRED
    MCP-->>APP: AUTH_EXPIRED Metadata
    APP->>DOM: RequireReauth(expected_version)
    APP->>DB: UoW commit · Run → REAUTH_REQUIRED + Receipt/Audit
    APP->>CP: LangGraph Checkpoint 저장
    API-->>FE: reauth_required
    U->>FE: Google 재로그인
    FE->>API: POST /api/v1/connections/google/start
    API->>APP: connection.start_authorization(connector_id=google_workspace)
    APP->>APP: OperationalCommandReplayPort reserve_or_replay → stable operation_ref
    APP->>MCP: OAuthCredentialPort.start_authorization(connector_id=google_workspace, ..., operation_ref)
    MCP-->>APP: authorization_url·callback_id
    APP-->>API: AuthorizationStartV1
    API-->>FE: 시스템 Browser로 authorization_url 열기
    G->>MCP: 일시적 Loopback Callback code·state
    MCP->>MCP: state·PKCE 검증·Token 교환·Credential/connection metadata 갱신
    MCP->>K: Refresh Token 저장
    loop bounded status observation
        FE->>API: GET /api/v1/connections/google/status
        API->>APP: connection.get_connection_status(google_workspace)
        APP->>MCP: OAuthCredentialPort.get_connection_status(google_workspace)
        MCP-->>APP: ConnectionMetadataV1
        APP-->>API: bounded metadata
        API-->>FE: CONNECTING | CONNECTED | DISCONNECTED | REAUTH_REQUIRED | UNAVAILABLE
    end
    Note over FE,MCP: raw callback code/state/token은 MCP boundary 밖으로 나오지 않으며 별도 MCP→APP completion push는 없음
    FE->>API: POST /api/v1/runs/{run_id}/resume · REAUTH_COMPLETED
    API->>APP: run.resume_after_reauth(command_id, expected_version)
    APP->>DOM: ResumeAfterReauth(expected_version, registered_target_binding)

`RegisteredResumeTargetRefV2(kind=MAIN_CONTROL)`의 global closed stage는 `RETRIEVAL_ENTRY | PLANNING_ENTRY | REVIEW_ENTRY | PREFLIGHT | READ_EXECUTION | VERIFICATION | RECOVERY | CANCEL_RESOLUTION`다. 그중 Reauth/Recovery가 저장하는 target은 실제 suspend 직전 safe point에 해당하는 등록 target만 허용한다. `PREFLIGHT`는 `Run=WAITING_APPROVAL`이면서 current Write Attempt in-flight fact가 0인 **BeginExecutionAttempt 전 credential failure**에만 Reauth return target으로 허용한다. `WAITING_APPROVAL + Attempt EXECUTING/uncertain`은 preflight로 rewind하지 않고 delivery/existing-result reconciliation 뒤 `VERIFICATION | RECOVERY`로 간다. `READ_EXECUTION`은 `Run=EXECUTING + Legacy READ Action=EXECUTING + ExecutionAttempt 없음`의 AUTH_EXPIRED에만 허용한다. `RETRIEVAL_ENTRY | PLANNING_ENTRY | REVIEW_ENTRY | CANCEL_RESOLUTION`은 06의 external-control matrix가 요구하는 경우에만 발급한다. `ACTION_EXECUTION`은 resume target이 아니며 승인형 Write dispatch 시작 뒤 generic execution replay는 0이다.
    APP->>DB: UoW commit · REAUTH_REQUIRED → saved pre_reauth_status + Receipt/Audit
    DB-->>APP: applied=true
    APP->>SUP: durable handoff → 검증된 same thread / RegisteredResumeTargetRefV2 resume
    SUP->>SUP: 등록된 안전 target(Agent Node 또는 Main Control stage)에서 재개
```

- Authorization Code와 Token 원문은 MCP Credential Provider 경계를 벗어나지 않는다.
- Write 전달 여부가 불명확한 시점의 인증 오류는 `UNKNOWN_RESULT` 규칙을 우선한다.
- Checkpoint가 없으면 자동 재실행하지 않고 `RECOVERY_REQUIRED`로 전환한다.

## 17. 취소

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자
    participant FE as React 프런트엔드
    participant API as FastAPI
    participant APP as Application
    participant DOM as Domain
    participant DB as Application UoW · Repository Ports → SQLite Adapter
    participant MCP as ConnectorReadPort · Connector runtime
    participant G as Google APIs

    U->>FE: 실행 중단
    FE->>API: POST /api/v1/runs/{run_id}/cancel
    API->>APP: request_cancel
    APP->>DOM: request_cancel(expected_version)
    alt first checkpoint 존재
        APP->>DB: UoW stage · RequestCancel Receipt APPLIED + Run CANCEL_REQUESTED<br>earlier PENDING/DISPATCHED/BLOCKED_BINDING **without execution admission** SUPERSEDED + new WorkflowHandoff(PENDING, target=CANCEL_RESOLUTION, next run_sequence); admitted head is not retroactively revoked<br>같은 Transaction · durable cancel intent
        APP->>DB: COMMIT
        DB-->>APP: applied=true + handoff_id
        APP->>APP: post-commit schedule_run_execution(handoff_id, NORMAL_HANDOFF) → MAIN_CONTROL:CANCEL_RESOLUTION
    else Run=CREATED + first checkpoint 없음 + START=PENDING|BLOCKED_BINDING + execution admission 없음
        APP->>DB: UoW stage · RequestCancel Receipt APPLIED + Run CANCEL_REQUESTED + START SUPERSEDED; new RESUME handoff 0
        APP->>DB: COMMIT
        APP->>APP: run.continue_cancel_resolution 직접 조정; Agent/LLM/Connector/LangGraph 호출 0
    else Run=CREATED + first checkpoint 없음 + START=DISPATCHED + durable execution admission
        APP->>DB: UoW stage · RequestCancel Receipt APPLIED + Run CANCEL_REQUESTED; admitted START retroactive SUPERSEDED 0
        APP->>DB: COMMIT
        Note over APP,DB: cancel-induced Run.version advance makes old START admission authority-stale; release/settlement retires it via Architecture-18 authority-aware admission semantics
        APP->>APP: current cancel authority continues; initialization/settlement yields Agent/LLM/Connector external effect 0
    end
    Note over APP,DOM: ContinueCancelResolutionHandler가 아래 existing lifecycle command들을 current durable child fact에 따라 조정

    alt LLM·Retrieval 내부 단계 · 실행 중 Action 없음
        APP->>APP: 다음 안전 지점에서 Graph 중단
        APP->>APP: build_terminal_message(CANCELLED)
        APP->>DOM: FinalizeCancel
        APP->>DB: UoW commit · Run CANCELLED + final ASSISTANT Message + required Audit
    else Legacy READ Action = PROPOSED
        APP->>DOM: CancelPendingAction
        APP->>DB: UoW commit · READ Action CANCELLED + Receipt/Audit
        APP->>DOM: FinalizeCancel
        APP->>DB: terminal UoW · Run CANCELLED
    else Legacy READ Action = EXECUTING | EXECUTED
        Note over APP,MCP: RequestCancel 이후 새 ConnectorRead dispatch/retry 0
        alt Action = EXECUTING + read 미dispatch 또는 process restart로 result 미보존
            APP->>DOM: FailReadAction
            APP->>DB: UoW commit · READ EXECUTING → FAILED
        else Action = EXECUTING + 이미 in-flight READ 응답 도착
            alt typed Read success
                APP->>DOM: CompleteReadAction → FinalizeReadAction
                APP->>DB: UoW commit · EXECUTING → EXECUTED → VERIFIED
            else failure / AUTH_EXPIRED / transport interruption
                APP->>DOM: FailReadAction
                APP->>DB: UoW commit · EXECUTING → FAILED
                Note over APP,DOM: cancel intent가 active이면 Reauth/READ_EXECUTION resume/retry 0
            end
        else Action = EXECUTED
            APP->>DOM: FinalizeReadAction
            APP->>DB: UoW commit · EXECUTED → VERIFIED
        end
        APP->>APP: unresolved READ Action 0 확인
        APP->>DOM: FinalizeCancel
        APP->>DB: terminal UoW · Run CANCELLED + final ASSISTANT Message + required Audit
    else Write 호출 전
        loop pending PROPOSED·MODIFIED·APPROVED·EXPIRED Action
            APP->>DOM: CancelPendingAction(command)
            APP->>DB: short UoW commit · Action CANCELLED + 해당 ACTIVE Approval REVOKED + Receipt/Audit
        end
        APP->>APP: build_terminal_message(CANCELLED)
        APP->>DOM: FinalizeCancel(command)
        APP->>DB: terminal UoW commit · Run CANCEL_REQUESTED → CANCELLED + Plan CANCELLED + final ASSISTANT Message + required Audit
        API-->>FE: result_kind=CANCELLED
    else Write 전달 후 결과 미확정
        opt Attempt가 아직 EXECUTING
            APP->>APP: classify_dispatch_result
            APP->>DOM: StoreSuccess | MarkFailed | MarkUnknownResult
            APP->>DB: short UoW commit · dispatch fact durable 확정
        end
        alt Action = UNKNOWN_RESULT
            APP->>MCP: effect-specific 결과 GET·Search
            MCP->>G: 기존 결과 확인
            G-->>MCP: Actual / 미실행 확정 / 미확정
            alt MUTATION_FOUND
                APP->>DOM: RecoverExistingResult
                APP->>DB: UoW commit · UNKNOWN_RESULT → EXECUTED
                APP->>APP: Run 상태별 UNKNOWN_RESULT→Verification entry matrix 적용
                APP->>DOM: 필요한 BeginVerification / ResolveRecovery(RECHECK) / Run command 0
                APP->>MCP: verification reread
                APP->>DOM: StoreVerification
                APP->>DB: UoW commit · EXECUTED → VERIFIED|MISMATCH
                APP->>APP: mismatch면 별도 RequireRecovery, 아니면 cancel-resolution 계속
            else MUTATION_NOT_FOUND + 미실행 확정
                APP->>DOM: ResolveAsFailed
                APP->>DB: UoW commit · UNKNOWN_RESULT → FAILED
                opt Run = RECOVERY_REQUIRED
                    APP->>DOM: ResolveRecovery(RECHECK) with changed lookup fingerprint
                    APP->>DB: UoW commit · RECOVERY_REQUIRED → saved pre_recovery_status
                end
                Note over APP,DOM: FAILED에는 StoreVerification을 호출하지 않는다
                APP->>APP: cancel intent 우선 · unresolved external effect 0이면 FinalizeCancel 경로
            else 미확정 지속
                APP->>DOM: RequireRecovery(UNKNOWN_RESULT) unless already RECOVERY_REQUIRED
                APP->>DB: UoW commit · Run RECOVERY_REQUIRED<br>RequestCancel Receipt의 cancel intent 유지
            end
        else Action = EXECUTED
            APP->>APP: BeginVerification 필요 여부를 current Run status로 판정 후 verification 계속
        else Action = FAILED
            Note over APP,DOM: Verification 없음 · cancel resolution 계속
        end
        alt Run = RECOVERY_REQUIRED + unresolved external fact 존재
            APP->>APP: Recovery/재인증으로 결과 확정
            APP->>APP: terminal snapshot 전에는 ResolveRecovery(CANCEL) 금지
        else unresolved external fact = 0
            alt Run = RECOVERY_REQUIRED
                APP->>APP: build_terminal_message(CANCELLED/PARTIAL)
                APP->>DOM: ResolveRecovery(CANCEL)
                APP->>DB: UoW commit · cancel intent + terminal child facts 검증 후 Run CANCELLED + final ASSISTANT Message + required Audit
            else Run = VERIFYING | REAUTH_REQUIRED | CANCEL_REQUESTED
                APP->>APP: 필요한 reauth/verification lifecycle 해소 후 build_terminal_message(CANCELLED/PARTIAL)
                APP->>DOM: FinalizeCancel
                APP->>DB: UoW commit · Run CANCELLED + final ASSISTANT Message + required Audit
            end
        end
    end
```

취소는 성공한 Google 변경을 롤백하지 않는다.

## 18. SSE 단절·브라우저 새로고침

```mermaid
sequenceDiagram
    autonumber
    participant SUP as Supervisor
    participant API as FastAPI
    participant APP as Application
    participant REP as Domain Repository Ports
    participant FE as React 프런트엔드
    participant DB as Domain Store

    SUP-->>API: 상태 Projection 생성
    API--xFE: SSE 연결 단절
    Note over SUP,DB: Workflow와 Domain 상태는 계속 진행
    FE->>API: Last-Event-ID로 SSE 재연결
    alt Cursor 복원 가능
        API-->>FE: 누락 Projection 재전송
    else Cursor 만료·Service 재시작
        FE->>API: GET /api/v1/runs/{run_id}
        API->>APP: Run Snapshot Query
        APP->>REP: 최신 Run·Plan·Action Snapshot
        REP-->>APP: Domain 상태
        APP-->>API: Snapshot
        API-->>FE: Snapshot
        FE->>API: 최신 Cursor로 SSE 연결
    end
```

SSE 중복 Event는 `event_id`와 Aggregate Version으로 무시한다.

## 19. 앱 재시작과 Run 복구

이 절의 sequence는 §4 startup dependency gate와 startup-only `ReconcileInflightExecutionsHandler` drain이 완료된 **뒤의 workflow-handoff recovery phase**만 나타낸다. 현재 process의 live `EXECUTING` Attempt를 orphan으로 분류하지 않는다.

```mermaid
sequenceDiagram
    autonumber
    participant L as Launcher
    participant API as FastAPI
    participant APP as RedriveWorkflowHandoffsHandler
    participant REP as Domain/Handoff Repository Ports
    participant CP as CheckpointPort
    participant SCH as ScheduleRunExecutionHandler
    participant WEP as WorkflowExecutionPort
    participant DOM as Domain
    participant FE as React 프런트엔드

    L->>API: Local Service 재시작
    API->>APP: startup reconciliation pass
    APP->>REP: Open Run + Handoff + current Domain/child facts 조회
    APP->>CP: latest typed checkpoint 조회
    alt CONSUMED active lineage + current Domain fence PASS
        APP->>SCH: submission_kind=CONSUMED_CONTINUATION_RECOVERY
        SCH->>REP: claim/reuse recovery WorkflowExecutionAdmissionV1
        Note over SCH,REP: effective binding = latest descendant checkpoint · execution_kind=RESUME · expected Run version captured
        SCH->>WEP: submit(WorkflowExecutionSubmissionV2(admission))
        Note over APP,WEP: dispatch-head membership 0 · payload reinjection 0 · handoff status remains CONSUMED · original START/PREFLIGHT binding is not wire authority
    else Domain progress owner = REAUTH_REQUIRED|RECOVERY_REQUIRED|terminal
        APP->>APP: stale active lineage resume 금지
        APP-->>API: state-specific snapshot/coordinator result
    else Domain progress owner = CANCEL_REQUESTED
        APP->>APP: cancel-compatible continuation 또는 run.continue_cancel_resolution만 허용
        APP-->>API: cancelling snapshot
    else BLOCKED_BINDING dispatch head
        APP->>DOM: deterministic RequireRecovery(CHECKPOINT_MISMATCH)
        APP->>REP: matching RecoveryContext 확인 후 handoff SUPERSEDED
        APP-->>API: recovery_required
    else PENDING|DISPATCHED dispatch head
        APP->>SCH: submission_kind=NORMAL_HANDOFF
        SCH->>REP: claim or reuse persisted NORMAL execution admission
        SCH->>WEP: submit(WorkflowExecutionSubmissionV2(admission))
    else no handoff lane + State Contract SAFE gate PASS
        APP->>APP: run.resume_safe_checkpoint · source-state/binding/target guard
        APP->>SCH: existing durable handoff/schedule boundary
        SCH->>WEP: NORMAL_HANDOFF submit
    else WAITING_CONFIRMATION|WAITING_APPROVAL
        APP-->>API: snapshot/interrupt/approval restore only
    else EXECUTING|VERIFYING
        APP->>APP: generic SAFE resume 0 · live orphan execution reconciliation 0
        APP-->>API: current durable snapshot / already-staged state-specific continuation only
    else Checkpoint 유실 또는 충돌
        APP->>DOM: RequireRecovery(CHECKPOINT_MISMATCH)
        APP-->>API: recovery_required
    end
    API-->>FE: current durable snapshot / required user action
```

이미 `VERIFIED`인 Action과 `UNKNOWN_RESULT` 해결 전 Write는 재실행하지 않는다. Startup/live precedence는 **Domain progress pre-admission check → stale admitted-head retirement → CONSUMED active-continuation admission/reuse → BLOCKED_BINDING Recovery reconciliation → PENDING/DISPATCHED dispatch-head admission/redrive → generic SAFE checkpoint evaluation** 순서다. Persisted DISPATCHED admission의 `expected_run_version`이 current Run.version과 이미 다르면 WEP에 재제출하지 않고 `release_execution_admission(..., AUTHORITY_EPOCH_CHANGED)`로 NORMAL을 SUPERSEDED 처리한 뒤 current coordinator를 재판정한다. Admission claim 뒤 Domain authority가 바뀔 수 있으므로 owner I/O 전 settlement CAS도 동일 Run-version fence를 적용한다. mismatch=`AUTHORITY_STALE_RETIRED`이면 stale NORMAL row는 그 transaction에서 SUPERSEDED, recovery admission은 clear되고 old owner I/O=0이며 Application reconciliation이 state-specific coordinator를 선택한다. `CONSUMED_CONTINUATION_RECOVERY`는 latest checkpoint의 `active_handoff_id/run_sequence` lineage와 current Domain/child-fact/registered-target guard를 동시에 통과할 때만 허용되는 내부 lane이며 `SAFE_CHECKPOINT_RESUME`가 아니다. Initial applied checkpoint보다 generation이 진행된 descendant도 같은 lineage면 recover 가능하지만, `REAUTH_REQUIRED | RECOVERY_REQUIRED | terminal` 또는 cancel-incompatible `CANCEL_REQUESTED`에서는 state-specific coordinator가 우선한다. 따라서 generic SAFE source-state 금지를 우회하거나 완화하지 않는다.

### 19.1 Retrieval cache-loss restart sequence

```text
checkpoint/resume preparation
→ run.reconcile_retrieval_cache_restart
→ CheckpointPort latest GraphCheckpointEnvelopeV1 load
→ checkpoint.retrieval_cache_requirements 각각을 RunRetrievalCachePort.resolve_read_result(handle, run_id, route_id, query_identity_hash)로 검사
→ FOUND|EXHAUSTED이면 restart 0 / current target 계속 (`EXHAUSTED`는 NEXT_PAGE만 NO_MORE_PAGE)
→ MISSING|CROSS_RUN|BINDING_MISMATCH이면 stale local handles 사용 0
→ trigger = system:retrieval-cache-restart:<run_id>:<checkpoint_generation>
→ WorkflowHandoffRepository.get_by_trigger_command_id(trigger)
→ existing row면 reuse, 없으면 RETRIEVAL_CACHE_RESTART handoff short-UoW stage
→ commit 후 run.schedule_run_execution
→ MAIN_CONTROL:RETRIEVAL_ENTRY
→ frozen RequestIntent/InputRoute + preserved RunBudget/exclusion obligation로 fresh read
```

Normal external-control handoff가 먼저 admission되어 있었다면 그 one-shot control을 checkpoint에 적용·settle한 뒤, semantic owner I/O 전에 같은 prerequisite Handler를 호출한다. 따라서 old PENDING handoff를 건너뛰거나 control payload를 잃지 않고, cache restart row는 settled predecessor 다음 `run_sequence`로 stage된다. Background/LangGraph adapter는 Handler를 drive할 뿐 WorkflowHandoffRepository를 직접 mutate하지 않는다.

## 20. MCP 프로세스 장애

```mermaid
sequenceDiagram
    autonumber
    participant APP as Application
    participant MCP as MCPClientPort · Connector Runtime
    participant G as Google APIs
    participant DOM as Domain

    MCP--xAPP: 프로세스 종료 감지
    APP->>APP: 신규 Tool 호출 일시 차단
    APP->>MCP: 자식 프로세스 재시작 최대 1회
    MCP-->>APP: Tool 목록·Schema Version

    alt Read 호출 전 또는 미전달
        APP->>MCP: 정책에 따른 Read 재시도
    else Write 전달 가능성 없음
        APP->>APP: ClassifyDispatchResult → NOT_SENT
        APP->>DOM: MarkFailed(delivery_certainty=NOT_SENT)
    else Write 전달 가능성 있음
        APP->>APP: ClassifyDispatchResult → MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST
        APP->>DOM: MarkUnknownResult
        APP->>MCP: GET 또는 Resource Search만 수행
        MCP->>G: 기존 결과 확인
    end
```

Write는 Transport 오류만으로 즉시 재전송하지 않는다.

## 21. LLM Runtime 선택·Fallback

```mermaid
sequenceDiagram
    autonumber
    participant SUP as Supervisor
    participant LR as LLM Router
    participant O as Ollama
    participant P as API LLM Provider
    participant DB as Trace·Checkpoint

    SUP->>LR: Agent Structured Output 요청
    alt API_LLM 명시
        LR->>P: API 호출
        P-->>LR: Structured Output
    else LOCAL_GPU 명시
        LR->>O: Local 호출
        O-->>LR: 결과 또는 오류
        Note over LR: 자동 API 전환 금지
    else AUTO
        LR->>O: Local 호출
        alt 기술 오류·fallback 가능
            O-->>LR: 연결·OOM·Timeout·반복 Schema 실패
            LR->>P: API fallback 최대 1회
            P-->>LR: Structured Output
        else 정상
            O-->>LR: Structured Output
        end
    end
    LR->>DB: actual_runtime·model·fallback reason·usage
    LR-->>SUP: 검증된 Agent Result
```

## 22. 앱 정상 종료

```
Launcher 종료 요청
→ 신규 Run·승인 Command 차단
→ 실행 중 Write의 전달 여부 확인
→ 결과 저장 또는 UNKNOWN_RESULT
→ LangGraph Checkpoint Flush
→ SQLite Connection 종료
→ MCP 자식 프로세스 종료
→ FastAPI 종료
→ Launcher 종료
```

브라우저 탭을 닫는 것만으로 Local Service를 강제 종료하지 않는다.

## 23. Workflow Phase·Run Status·주요 Event 매핑

| Workflow Phase | Run Status | SSE Event |
| --- | --- | --- |
| `REQUEST_UNDERSTANDING` | `ANALYZING` | `phase_changed` |
| `TOOL_ROUTING` | `ANALYZING` | `tool_routing` |
| `RETRIEVAL` | `RETRIEVING` | `retrieval_progress` |
| `WAITING_CONFIRMATION` | `WAITING_CONFIRMATION` | `confirmation_required` |
| `WORK_ANALYSIS` | `ANALYZING` | `analysis_progress` |
| `PLANNING` | `PLANNING` | `plan_updated` |
| `REVIEW` | pre-publish=`PLANNING`; published re-review=`WAITING_APPROVAL | VERIFYING` — Review 자체는 Run status를 변경하지 않음 | `phase_changed`; disposition이 `BeginPlanning/RequestConfirmation/BlockRun`을 적용하면 해당 command/event가 별도 반영 |
| `WAITING_APPROVAL` | `WAITING_APPROVAL` | `approval_required` |
| `PREFLIGHT`, `ACTION_EXECUTION` | 승인형 Write는 `WAITING_APPROVAL` 유지 · Legacy/호환 경로만 `EXECUTING` 가능 | `action_status` |
| `VERIFICATION` | `VERIFYING` | `verification_result` |
| `RECOVERY` | `RECOVERY_REQUIRED` | `recovery_required` |
| `RESPONSE_SYNTHESIS` | terminal command 적용 전 현재 비Terminal/terminal candidate 상태 | 없음 — deterministic terminal message input 생성 |
| `TERMINAL_COMMIT` | terminal lifecycle handler 적용 후 `COMPLETED | BLOCKED | FAILED | CANCELLED` | terminal commit 이후 다음 단계에서 projection |
| `FINALIZE` | Terminal | `completed` 또는 `error` |

## 24. Transaction 경계 요약

| 구간 | DB Transaction | 외부 호출 |
| --- | --- | --- |
| Run 시작 | Run·User Message 원자 저장 | 없음 |
| Agent LLM 호출 | 없음 | API LLM 또는 Ollama |
| Google Read | 없음 | MCP·Google API |
| Plan 저장 | Plan·Action·Evidence Batch | 없음 |
| 승인 | Approval·Action·Audit | 없음 |
| 실행 Claim | Action·Approval·Attempt(`CLAIMED`) + Receipt/Audit | 외부 호출 없음; Claim Commit은 dispatch authority가 아님 |
| 실행 Attempt 시작 | Attempt `CLAIMED → EXECUTING` + Receipt/Audit | `BeginExecutionAttempt`가 current ClaimContext + cancel-intent guard를 adjudicate하고 COMMIT(`applied=true`); Transaction 종료 뒤에만 Write. 이후 Cancel은 in-flight result-resolution 규칙 |
| Write 결과 저장 | Attempt·Action·ResourceRef | Write 완료 이후 |
| 검증 저장 | Verification·Action only | GET 완료 이후. Run lifecycle은 `BeginVerification` / 별도 `RequireRecovery` / terminal command가 소유 |
| Answer-only 완료 | Run Terminal·final ASSISTANT Message·required Audit 같은 UoW; Trace/SSE는 post-commit projection | 없음 |

## 25. 오류 처리 우선순위

```
APPROVAL_INVALID·POLICY_BLOCKED·VERSION_CONFLICT
→ Write 호출 금지

AUTH_EXPIRED
→ REAUTH_REQUIRED·Checkpoint 재개

RATE_LIMITED·UPSTREAM_5XX
→ Read 제한 재시도 또는 부분 결과
→ Write는 전달 여부 확인 후 처리

TIMEOUT·MCP_UNAVAILABLE
→ Write 전달 가능성에 따라 FAILED 또는 UNKNOWN_RESULT

VERIFICATION_MISMATCH
→ 자동 수정 금지·사용자 Recovery
```


## 26. Command Receipt 시퀀스

```
Route가 Request 검증
→ Application이 Canonical Request Hash 생성
→ BEGIN IMMEDIATE
→ command_receipts 조회
→ 신규면 RECEIVED Insert
→ Domain 변경·Audit
→ Receipt APPLIED 또는 REJECTED
→ COMMIT
```

- 동일 `command_id`·동일 Hash면 저장된 응답을 반환한다.
- 동일 ID·다른 Hash면 `DUPLICATE_COMMAND`다.
- HTTP 응답 유실 후 재전송도 새 Run·Approval·Attempt를 만들지 않는다.


## 27. Claim Token 시퀀스

```
ClaimExecution Commit
→ Application Claim handler가 bounded-TTL `ClaimContextV2` / `claim_token` 생성
→ `BeginExecutionAttempt` Commit (`Attempt CLAIMED → EXECUTING` + required Audit)
→ MCP Write Tool 호출
→ MCP Signature·Binding·Nonce 검증
→ Nonce 소비
→ Connector Write
```

검증 실패 시 Google API를 호출하지 않고 `APPROVAL_INVALID` 또는 Claim Token 오류를 반환한다.


## 28. Transaction · Recovery · SEND/DELETE 시퀀스

```
Claim/dispatch saga:
1. `ClaimExecution` short UoW → COMMIT
2. `build_claim_context` (DB mutation 0)
3. `BeginExecutionAttempt` short UoW → COMMIT
4. **process-loss cut:** Begin commit 뒤 dispatch result persistence 전 process가 사라지면 restart는 provider call 여부를 추측하지 않는다. startup-only `execution_attempt.reconcile_inflight_executions` batch Command가 deterministic system identity로 `MarkUnknownResult(MAY_HAVE_BEEN_SENT)`를 apply/replay한다. 이후 durable `UNKNOWN_RESULT_UNRESOLVED` candidate가 existing-result lookup을, recovered `EXECUTED_AWAITING_VERIFICATION` candidate가 Verification handoff를 소유하므로 각 중간 commit 뒤 process loss에도 다음 startup이 이어간다. original Connector Write replay = 0.

5. Connector dispatch (DB Write Transaction 없음)
6. `StoreSuccess | MarkFailed | MarkUnknownResult` short UoW → COMMIT

Verification saga when Action is EXECUTED:
7. Run이 `WAITING_APPROVAL | CANCEL_REQUESTED`이면 `BeginVerification` short UoW; 이미 `VERIFYING`이면 Run command 0
7. verification Connector reread (DB Write Transaction 없음)
8. `StoreVerification` short UoW → Action/Verification only
9. MISMATCH이면 별도 `RequireRecovery(VERIFICATION_MISMATCH)` short UoW
```

Recovery는 `RequireRecovery`·`ResolveRecovery` Domain Command를 사용한다.

`UNKNOWN_RESULT` lookup에서 `RecoverExistingResult`가 Action을 `EXECUTED`로 복원했을 때 Run이 이미 `VERIFYING`이면 `BeginVerification`을 반복하지 않고 바로 verification reread로 진행한다. Run이 `RECOVERY_REQUIRED`이면 먼저 reason-specific `ResolveRecovery(RECHECK)`를 적용한다.

### Gmail SEND

Plan(SEND) → Domain Validation → WAITING_APPROVAL → ClaimExecution COMMIT → ClaimContext → BeginExecutionAttempt COMMIT → gmail_send → Sent Lookup → VERIFIED | MISMATCH | UNKNOWN_RESULT.

### Calendar DELETE

Plan(DELETE) → Domain Validation → WAITING_APPROVAL → ClaimExecution COMMIT → ClaimContext → BeginExecutionAttempt COMMIT → calendar_delete_event → target absence 확인 → VERIFIED | MISMATCH | UNKNOWN_RESULT.


## 29. Agent Subgraph 호출·복귀 시퀀스

```mermaid
sequenceDiagram
    participant SUP as Main Supervisor
    participant AG as Agent Subgraph
    participant LS as Typed Local State
    participant N1 as Node A
    participant N2 as Node B
    participant LLM as LLM Adapter
    participant APP as Deterministic Application Node

    SUP->>AG: Subgraph Input Projection + invocation_id
    AG->>LS: Typed Local State 초기화
    LS->>N1: Node A가 필요한 필드만 Projection
    opt Node A가 LLM 판단
        N1->>LLM: PromptRef + Typed Input
        LLM-->>N1: Candidate Output
    end
    N1->>LS: validated local result 저장
    LS->>N2: Node B가 필요한 필드만 Projection
    opt Node B가 deterministic work
        N2->>APP: typed local input
        APP-->>N2: deterministic result
    end
    N2->>LS: validated local result 저장
    AG->>AG: final contract validation
    AG-->>SUP: Versioned Typed Result + disposition
```

- Subgraph 내부 Node마다 필요한 State가 다르며 전체 Parent State를 일괄 전달하지 않는다.
- Local State는 invocation 범위에서만 유지하고 Parent에는 공식 Typed Result만 병합한다.
- Release Graph의 일반 Google READ는 Retrieval Subgraph의 결정적 Read Node가 소유한다. 아래 READ Action 흐름은 기존 Domain `READ` Effect와 회귀 테스트를 위한 Legacy/호환 경계이며 새 SIX Release Planning이 생성하는 정상 경로가 아니다.

Retrieval Subgraph의 결정적 Read Node는 `ToolRoutePlanV2.input_plan.input_routes[].allowed_read_tool_ids`만 사용할 수 있다.

- Planning Subgraph는 `ToolRoutePlanV2.output_plan.output_routes[].selected_tool_id`를 읽고 Tool을 재선택하지 않는다.
- Agent가 다른 Agent를 직접 호출하지 않는다. 다른 단계가 필요하면 Supervisor에 disposition을 반환한다.
- 실제 Connector Write는 공통 승인·Claim·실행·검증 경로에서만 수행한다.


### 29.1 LLM 호출 전 PromptRef 선택

모든 LLM 호출 전에 Supervisor가 선택한 Agent·Application Node가 다음 Key로 PromptRef를 확정한다.

```
agent_role + subgraph_name + node_name + node_state + purpose
```

Repair·Revision은 별도 PromptRef를 사용할 수 있으며 Prompt 선택 결과는 `prompt_id`·`prompt_version`·`content_hash`로 Trace한다.


## 30. Runtime E2E 취소·복구·전달 확실성

### 30.1 Cancel

```
사용자 Cancel
→ API가 command_id / expected_version 검증
→ RequestCancel
→ Run CANCEL_REQUESTED
→ 신규 Claim·Write 차단
→ 미실행 Action CANCELLED + ACTIVE Approval REVOKED
→ EXECUTING/EXECUTED는 결과·Verification 확정
→ UNKNOWN_RESULT가 있으면 RECOVERY_REQUIRED
→ 모든 in-flight 결과 확정
→ Plan/Run CANCELLED
→ 이미 성공한 Write가 있으면 result_kind PARTIAL
```

취소는 성공한 Google 변경을 rollback하지 않는다.

### 30.2 Insufficient Data

```
POLICY/safety-critical required issue → BLOCKED
USER required issue                  → NEEDS_CONFIRMATION
GOOGLE required issue + budget       → RETRIEVE_MORE
budget exhausted + usable Evidence → PARTIAL 유지 후 Work Analysis 또는 Planning
budget exhausted + usable Evidence 없음 → `CompleteAnswerOnlyRun` → FINALIZE
Write 필수 정보 부족                 → CONFIRMATION 또는 BLOCKED
```

모든 Graph Profile은 동일 Supervisor Guard를 사용한다.

### 30.3 Delivery Classification

```
Connector MCP Write
→ NOT_SENT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST
→ NOT_SENT만 FAILED 후보
→ 나머지는 UNKNOWN_RESULT + GET/Search Recovery
```

### 30.4 Verification MISMATCH

```
Verification MISMATCH
→ Action MISMATCH 보존
→ Run RECOVERY_REQUIRED
→ 자동 수정·자동 rollback 금지
→ ACCEPT_PARTIAL
   → 미실행 Action CANCELLED + ACTIVE Approval REVOKED
   → current Plan COMPLETED
   → Run COMPLETED + result_kind PARTIAL
또는
→ CREATE_CORRECTIVE_PLAN
   → 실제 Google 상태 재조회
   → Run PLANNING
   → 새 Plan Revision
   → 새 Approval·Claim·Attempt·Verification
```

기존 MISMATCH Action이나 Approval을 교정 Write에 재사용하지 않는다.


## 31. Claim V2·첨부파일 시퀀스

### Write

```
Approval ACTIVE
→ ClaimExecution DB Transaction
→ Action EXECUTING + Attempt CLAIMED + Approval CONSUMED
→ COMMIT
→ Application 최종 MCP Payload 구성
→ execution_arguments_hash + ClaimContextV2
→ BeginExecutionAttempt DB Transaction
→ Attempt CLAIMED → EXECUTING + Audit → COMMIT
→ MCP 실제 인자 재해시·Claim 검증
→ Connector Write
→ StoreSuccess/MarkFailed/MarkUnknownResult
→ 기존 Effect Verification
```

### 수신 첨부파일

```
사용자 Download 선택
→ FastAPI Local Session 검증
→ MCP gmail_get_attachment
→ Gmail users.messages.attachments.get
→ FastAPI Stream
→ 사용자 파일
```

### 발신 첨부파일

```
사용자 파일 선택
→ /api/v1/attachments/stage
→ Descriptor + SHA-256
→ Action/Approval
→ Claim V2
→ MCP 실제 bytes size/hash 재검증
→ MIME Draft/Send
→ Google 재조회 Verification
```

첨부파일 bytes는 어느 시퀀스에서도 LLM·Agent Context를 통과하지 않는다.

### Claim 이후 Begin 이전 cancel/crash sequence

```text
ClaimExecution COMMIT
→ Action EXECUTING + Attempt CLAIMED + Approval CONSUMED
→ [cancel / crash-restart / invalid ClaimContext / pre-Begin credential failure]
→ BeginExecutionAttempt = not applied
→ AbortClaimedExecution COMMIT
→ Attempt FAILED
→ Action CANCELLED (cancel intent) | FAILED (other pre-dispatch failure)
→ Provider Write = 0
→ FinalizeCancel 또는 existing retry/failwait path
```

Approval을 ACTIVE로 되돌리거나 새 Attempt를 자동 생성하지 않는다.


## 32. 정합성·테스트 완료 조건

- Tool Route Subgraph와 Retrieval Subgraph의 책임이 분리된다.
- Tool Route가 IN/OUT Tool을 한 번 확정하고 Retrieval·Planning이 재선택하지 않는다.
- Retrieval LLM이 MCP를 직접 호출하는 경로가 없고 결정적 Read Node만 허용 Tool 범위에서 호출한다.
- Retrieval은 Run-scoped RAG를 거쳐 Evidence를 반환한다.
- 일반 Retrieval이 Action Row를 생성하지 않는다.
- Answer-only Run이 Plan·Action 없이 완료된다.
- **Legacy/호환 READ-only Plan**은 승인 없이 실행된다. 새 Release Planning의 primary path가 아니다.
- Legacy READ Action에는 Approval·Attempt·Verification Row가 없다.
- Legacy READ Output Schema 실패는 `FAILED`로 저장된다.
- Write는 Approval + `ClaimExecution` Commit만으로 호출되지 않는다. `ClaimContextV2`가 current이고 cancel intent가 없는 상태에서 `BeginExecutionAttempt`가 `applied=true`로 Commit되어 Attempt=`EXECUTING`이 된 뒤에만 정확히 한 번 호출된다. 그 Commit 이후 새 Cancel이 APPLIED되면 해당 Attempt는 in-flight로 분류해 결과를 먼저 확정하고 추가 Claim/Write는 금지한다.
- 승인 이후 LLM이 Arguments를 다시 생성하지 않는다.
- `FAILED → MODIFIED → 새 승인`만 Write Retry로 허용된다.
- `UNKNOWN_RESULT`에서 새 Attempt·Write가 차단된다.
- 일부 승인·부분 실패 시 성공 Action을 보존한다.
- SSE 단절과 브라우저 새로고침이 Write 재실행을 만들지 않는다.
- OAuth 재인증은 같은 `langgraph_thread_id`의 안전한 Checkpoint에서 재개된다.
- 외부 호출 중 SQLite Transaction을 유지하지 않는다.
- MCP 장애에서 Write 전달 가능성을 확인하기 전 자동 재전송하지 않는다.
- `RESOURCE_SELECTED`는 React→FastAPI→Application→Supervisor 경계를 지킨다.
- 확인 응답 저장은 Application·Repository를 경유하며 FastAPI Route가 DB를 직접 수정하지 않는다.
- 07에 정의된 `ConnectorReadPort` read capability만 시퀀스에서 사용한다.
- Supervisor는 Node만 Routing하고 선택된 Agent·Application Node가 PromptRef를 확정하는지 검증한다.
- `/health/ready`와 `/api/v1/runtime`의 책임이 분리된다.
