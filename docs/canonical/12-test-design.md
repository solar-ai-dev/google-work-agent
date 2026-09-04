# 12. 테스트 설계서

> **Authority:** current owner contract와 State Transition Test Matrix의 product regression verification. Expected assertion은 검증 oracle이며 새 behavioral authority가 아니다.  
> **상태:** Draft v3.53 · **기준일:** 2026-09-03 · **OS:** Windows 11 x64 · **Browser:** Chrome·Edge

## 1. 목적과 계층

이 문서는 제품 계약과 안전 회귀를 검증한다. Model·Prompt·Retrieval·Graph 품질 비교는 `13. 평가·실험 설계서`가 소유한다.

```
Unit → Contract → Integration → Component → E2E → Failure Injection → Installer·Release
```

모든 상태 전이는 허용 Edge와 금지 Edge를 검증한다.

## 2. Test ID·Traceability

```
TST-<AREA>-<NNN>
AREA = DOM DB API SSE UI WF AGT RET LLM MCP CON GGL SEC INF OBS E2E PERF REL EVAL

`CON`은 Connector-independent Registry/MCP/Provider boundary 계약, `GGL`은 P0 Google Workspace Connector 고유 계약에 사용한다.
```

Case 필드:

```
test_id
source_contract
requirement_ids
case_id?
fixture_snapshot_id?
user_prompt_id?
main_experiment_id?      # A | B | C | D | E
experiment_id?           # compatibility-only reproduction alias
evaluation_item_id?
candidate_config_hash?
projection_version?
upstream_mode?          # ORACLE | LIVE
target_node_id?
grader_version?
prompt_bundle_version?
prompt_refs?
precondition
fixture
steps
expected_domain_state
expected_external_calls
expected_trace_audit
forbidden_side_effects
execution_lane
```

## 3. Lane

- FAST: 모든 PR
- WINDOWS_COMPONENT: Main Merge
- E2E_MOCK: Main·Release
- LIVE_GOOGLE: 명시적 Release 전
- LOCAL_GPU: Local Profile 후보
- CLEAN_VM: Release Candidate
- EXPERIMENT_RUNNER: 합성 Fixture·후보 Config·Grader 검증
- EXPERIMENT_MULTI_CONNECTOR: `13 Evaluation`의 Synthetic Multi-Connector Harness로 서로 다른 `connector_id`의 MCP Simulator 또는 등록 Connector 2개 이상을 검증한다. P0 제품 설치 범위를 자동 확장하지 않는다.

일반 CI에 Refresh Token·API Key·Signing Private Key를 넣지 않는다.

## 4. Test Double

```
FakeClock
DeterministicUUID
FakeKeyring
FakeGoogleProviderAdapter   # Google Workspace MCP Server 내부 Adapter 테스트 전용
FakeMCPTransport
SyntheticConnectorMCPServer # 13의 synthetic multi-connector harness용 결정적 Simulator. Provider direct port가 아니다.
FakeLLMProvider
FakeOllamaAdapter
FakeHardwareProbe
FakeBrowserLauncher
FaultInjectingSQLiteAdapter
FakeExperimentClock
DeterministicGrader
```

## 5. Fixture

P0 일반 Fixture는 합성 Gmail·Tasks·Calendar만 사용한다. Snapshot은 `fixture_snapshot_id`와 Relation Manifest를 가진다. 13의 synthetic multi-connector harness는 제품 지원 범위를 바꾸지 않는 별도 Fixture를 사용한다.

Checked-in provider/resource static fixture는 16/09의 exact grammar `tests/fixtures/data/<provider>/<resource>/<scenario>.json`과 UTF-8 strict JSON serialization을 사용한다. 12가 소유하는 것은 required fixture **semantic family/boundary**이며 concrete `<scenario>` filename의 closed set은 architecture authority가 아니다. 따라서 새 verification case가 같은 grammar 아래 scenario data file을 추가하는 것은 Canonical owner/path를 늘리는 일이 아니다. Evaluation dataset은 `tests/fixtures/data/**`에 두지 않는다.

필수 경계:

- Gmail 긴 Thread·외부 주소·Prompt Injection
- Task 중복·유사·예정일 없음·예정일 임박·업무 마감 분리
- Calendar Busy·Tentative·Free·OOO·Focus·DST
- Write 정상·정규화 차이·Mismatch
- 401·403·404·409·429·5xx·Timeout·응답 유실

User Prompt Catalog 필드:

```
user_prompt_id
intent_family
entry_mode
language
paraphrase_group_id
case_id
```

Canonical Case와 실험 Projection은 별도 파일로 관리하되 `case_id`·`fixture_snapshot_id`·`user_prompt_id`로 연결한다.

## 6. Domain

### Answer-only

Plan·Action 미생성, CommandReceipt·Run Terminal·final ASSISTANT Message·required Audit 원자 저장. Diagnostic Trace/SSE는 post-commit이며 실패가 Domain rollback을 만들지 않음을 검증한다.

### READ-only

Approval·ExecutionAttempt·Verification Row 미생성. Claim 경쟁 하나만 성공.

### WRITE

- Approval Snapshot·Hash·Source Snapshot
- ACTIVE Approval 하나
- Claim 전 MCP Write 금지
- 중복 Command·Click로 Attempt 추가 금지
- Write 후 GET Verification

### FAILED

`FAILED → MODIFIED → 새 Approval → 새 ExecutionAttempt`. 기존 Approval·Idempotency Key 재사용과 직접 `EXECUTING`을 금지한다. 새 Approval의 `attempt_no`는 1이다.

### UNKNOWN_RESULT

새 Attempt·Write 금지. Effect별 recovery/verification contract를 그대로 검증한다: CREATE는 `RESOURCE_SEARCH → GET_COMPARE`, UPDATE는 `GET_TARGET → GET_COMPARE`, SEND는 `MESSAGE_SEARCH → SENT_LOOKUP`, DELETE는 `GET_TARGET → GET_ABSENT`.
- recovered mutation에서 `RecoverExistingResult` 뒤 Verification 진입 전에 Run 상태에 맞는 `BeginVerification` 또는 `ResolveRecovery(RECHECK)`가 정확히 한 번 적용되는지 검증한다.
- Run이 이미 `VERIFYING`이면 recovered result에 Run lifecycle command가 0이어야 하고 바로 reread/StoreVerification으로 진행한다.
- unresolved lookup만 `RequireRecovery(UNKNOWN_RESULT)`를 만들고, deterministic 미실행 확정은 불필요한 `RECOVERY_REQUIRED`를 만들지 않는지 검증한다.
- `RecoveryContextV1` reason/scope/target/pre-status/fingerprint가 restart 후에도 복원되고 reason×resolution matrix, NO_PROGRESS, target-specific RECHECK를 동일하게 판정하는지 검증한다.

### Constraint

Open Run 1, Active Approval 1, Active Attempt 1, Version Conflict, DAG Cycle, Unique Position·Revision·ResourceRef. `0004` Plan Review Gate, `0005` NFR-019 cross-aggregate Trigger, `0006` Plan Aggregate cross-run/conversation/plan guards, `0007` Action/ResourceRef `connector_id` backfill·persistence identity, `0008` connector-aware ResourceRef uniqueness, **`0009` workflow_handoffs durable outbox/lookup indexes/constraints**를 각각 Migration·Contract Test로 검증한다. New implementation target의 Startup discovery는 package의 `0001~0009`을 version-sort하여 적용하고 checksum mismatch를 fail-close해야 한다.

## 7. Contract

- FastAPI Pydantic·Error Envelope
- `/health/live`, `/health/ready`, `/api/v1/runtime` 책임 분리
- SSE monotonic Event ID·Last-Event-ID·Snapshot Fallback
- `SseEventBufferPort` bounded replay: valid cursor replay, `CURSOR_EXPIRED` snapshot fallback, process restart buffer loss가 Domain failure/Write resend를 만들지 않음; current Infrastructure configuration의 capacity/terminal-retention/query-bound를 소비하고 boundary behavior를 검증
- `RunSseEventV1.event_type ↔ payload` closed mapping을 모든 14 event type에 대해 검증하고 unknown/mismatched payload, secret/raw Provider/Prompt payload가 publish되면 실패
- terminal handler replay가 final ASSISTANT Message duplicate row를 만들지 않으며 `(run_id, terminal_version, final ASSISTANT)` logical uniqueness가 유지됨
- FINALIZE는 Domain mutation/Message INSERT를 하지 않고 Trace emit + SSE projection만 수행
- `RESPONSE_SYNTHESIS → TERMINAL_COMMIT → FINALIZE` 순서를 강제하고 `TERMINAL_COMMIT` closed dispatch가 unknown kind를 fail closed하는지 검증한다. Response LLM이 terminal kind/status를 변경하거나 FINALIZE가 lifecycle handler를 대신 호출하면 실패
- Agent Structured Output Version·Enum·Repair 1회
- Core `SignedToolRegistry` ↔ MCP signed projection/descriptor · Schema · Effect · Scope · Retryability 정합성
- Observability Envelope·16 KiB·Sanitization
- Experiment Config·Candidate Config Hash·Projection Version·Grader Version

## 8. Multi-Agent·Prompt

### Conversation · Run Context Isolation 회귀

- 같은 Conversation에서 Run A가 Terminal이 된 뒤 업무적으로 관련 없는 USER 요청으로 Run B를 시작할 수 있어야 한다. 새 Conversation 강제는 실패다.
- Run B는 Run A와 다른 `run_id`와 다른 `langgraph_thread_id`를 가져야 하고, 같은 Conversation에 비Terminal Run이 이미 있으면 두 번째 Run 생성은 실패해야 한다.
- `POST /api/v1/runs`의 Browser Request가 `run_id`, `user_message_id`, `workflow_key`, `langgraph_thread_id`를 지정하거나 override할 수 있으면 실패다. Application은 네 server-owned ID를 Domain guard 전에 preallocate하고 `WorkflowBindingV1`을 materialize해야 한다. 04 §10.1의 같은 StartRun UoW가 Run·USER Message·선택 ResourceRef·initial WorkflowBinding·START handoff를 commit하며, 이후 일반 checkpoint write는 별도 transaction이어야 한다.
- Run B의 initial `RunInputV1`/Request Understanding/Prompt Projection에는 Run A의 Message history, RequestIntent, Tool Route, Retrieval/Evidence, Work Analysis, Plan/Review, `prompt_context`, Confirmation Receipt가 포함되지 않아야 한다.
- Run A의 Approval·Claim·Policy Confirmation Receipt를 Run B의 Write/Scope 확장 권한으로 재사용하면 실패다.
- 사용자가 Run B에서 과거 Resource를 명시적으로 다시 선택하면 해당 Resource Ref만 current-run Entry Context로 허용하고, Evidence·Approval은 Run B에서 다시 조회·검증해야 한다.
- `RESOURCE_SELECTED` StartRun은 Resource List가 발급한 opaque authenticated `selection_handle`만 받는다. signature/session/account/service-instance/expiry mismatch는 fail closed하고 cross-source probing은 0이어야 한다. 검증된 handle identity는 새 Run의 StartRun UoW에서 ResourceRef로 materialize된 뒤 `RunInputV1.selected_resource_refs`가 되어야 한다.
- Run B 입력이 `관련 메일 찾아줘`처럼 이전 Run 없이는 대상이 정해지지 않고 explicit Resource가 없다면, 과거 Conversation History를 암묵적으로 주입해 해석하지 않고 `NEEDS_CONFIRMATION` 또는 명시적 Resource 선택을 요구해야 한다.
- 동일 Run의 Confirmation/재인증/Recovery resume는 위 새 Run 생성과 구분한다. 이 경로는 기존 `run_id + langgraph_thread_id + checkpoint`를 보존해야 하며 새 Run을 만들면 실패다.
- 외부/API LLM Mock capture에는 current-run allowlisted Projection만 존재해야 하며 prior Conversation Message 원문 자동 전송은 0건이어야 한다.
- Profile별 Agent Subgraph 개수 계약: SINGLE=1, THREE=3, SIX=6
- Profile binding 검증: 세 `GraphProfileIdV1` builder가 모두 존재하고 StartRun의 `WorkflowBindingV1`에 selected profile + graph_version이 snapshot되어야 한다. restart/resume에서 binding과 다른 profile/version으로 fallback하거나 hot-swap하면 실패다.
- Profile semantic/safety parity 계약: `SINGLE_BASELINE`, `THREE_STAGE`, `SIX_ROLE_BASELINE`은 Subgraph 분해 수준만 달라야 한다. 같은 fixture/request에서 Domain transition, Policy/Confirmation, Approval, Claim, Execution, Verification, Recovery, external-effect boundary와 최종 typed semantics가 Profile 때문에 달라지면 실패다. Profile 전용 hidden business authority·별도 Tool selection·별도 Domain mutation 경로가 있으면 실패다.
- SIX Role 계약: Request Understanding / Tool Route / Retrieval / Work Analysis / Planning / Review
- Agent Subgraph는 invocation 범위 Typed Local State만 사용하고 장기 Memory를 생성하지 않음
- Agent 간 직접 호출·Peer-to-Peer 금지
- Agent invocation 수와 LLM Call 수를 별도 계수
- Local SLLM atomic decomposition 검증: Work Analysis의 `extract_work_facts / resolve_entity_relations / resolve_temporal_dependencies / detect_duplicate_conflict_candidates / assess_information_gaps / assess_operational_risks`, Planning의 `draft_action_objective_per_output_route / compose_arguments_per_output_route`, Review의 `inspect_goal_and_evidence / inspect_action_scope_and_route / inspect_constraints_and_policy_summary`가 서로 다른 PromptRef와 최소 Typed Projection을 사용해야 한다. 한 Prompt가 다른 atomic responsibility의 출력까지 동시에 생성하면 실패. `validate_relations / assemble_work_analysis / validate_work_analysis / build_dependencies / assemble_plan / validate_plan / aggregate_review_findings / validate_review`는 deterministic이므로 Product PromptRef가 있으면 실패
- Prompt Runtime exact-set closure: 15의 current 21 `prompt_slot_id` set = runtime Product-LLM caller set = `application/prompt_runtime/prompt_manifest.json` key set = concrete `sources/<prompt_id>.md` filename set = `prompt_runtime_input_contract_v1.json` key set이어야 한다. `prompt_id == prompt_slot_id`; broad predecessor `work_analysis.resolve_relations`, `review.inspect`, `review.recheck` source/manifest row는 0이어야 한다. `prompt_version/content_hash/activation_status`는 same-slot current manifest/release metadata이며 source set cardinality를 늘리지 않는다.
- Prompt input-contract realization: `load_prompt_input_contract()`가 schema version 1, duplicate/unknown slot, manifest/source/caller equality를 fail-closed하고, 06/15 allowlist 밖 Conversation history·previous-run artifact·raw Provider continuation·Gold/Grader field가 있으면 실패한다.
- Strong-runtime fusion parity 검증: fuse된 Profile은 atomic Profile과 동일 Typed candidate semantics, final disposition, failure localization을 재현해야 하며 parity 실패 시 fusion Profile을 Release 후보로 사용할 수 없음
- Review aggregator는 deterministic이어야 하며 각 inspector Finding을 stable issue code로 합치되 새 semantic issue를 생성하지 않아야 함
- REVISE 이후 Review는 `ReviewIssueV1.affected_dimensions`만 재호출하고 이미 PASS한 dimension의 LLM 호출을 반복하지 않는지 검증. 특히 `affected_dimensions`가 비어 있지 않고 `affected_action_ids=[]`, `affected_route_ids=[]`인 dimension-only issue도 Planning revision → Review RECHECK로 정상 전달되어야 한다. Finding text나 전체 Plan을 selector로 사용하거나 action/route ID를 임의 생성하면 실패다.
- `ReviewDimensionIdV1` closed set 밖의 unknown/free-text dimension이 inspector intermediate, `ReviewIssueV1`, RECHECK selector에 들어오면 deterministic validation이 fail closed해야 한다.
- Route/Runtime별 LLM Budget Profile과 Product LLM Call hard cap 24 검증. `NORMAL=14 / RETRIEVAL_HEAVY=20 / REVISION_HEAVY=18 / ABSOLUTE=24` ceiling을 정확히 계수하고, budget을 맞추기 위해 서로 다른 semantic responsibility를 임의 fuse하지 않는지 검증
- Revision 2, Repair 1, Additional Retrieval 2
- Main State Owner 단일성: RequestIntent / InputRoutePlan / OutputPlan / Retrieval / Analysis / Planning / Review 각각 단일 Owner. InputRoutePlan·OutputPlan의 Owner는 동일 Tool Route Subgraph지만 revision/stale 단위는 독립.
- Main State non-Agent control/reference field patch allowlist도 검증한다. Agent Subgraph 일반 patch가 `approved_plan_id`, `execution_summary`, `verification_summary`, `policy_confirmation_receipts`, `retry_budget`, `prompt_context`, `trace_context`를 변경하면 실패다. `approved_plan_id`와 execution/verification summary는 Domain-backed 결과의 결정적 projection/reference이며 Graph 값만으로 Domain 사실을 생성하면 실패, `policy_confirmation_receipts`는 Confirmation Controller만 append 가능, `workflow_signal`은 허용된 Subgraph Return이 만든 뒤 해당 Edge/Interrupt가 소비하면 clear돼야 한다. `retry_budget`/`prompt_context`/`trace_context`는 각각 결정적 runtime budget/Prompt/observability 경계에서만 갱신한다.
- Main State control/projection schema를 contract-test한다. `ExecutionSummaryV1`, `VerificationSummaryV1`, `RunBudgetV2`, `PromptContextV1`, `TraceContextV1`이 06의 declared fields를 정확히 가져야 하며 opaque `object`/임의 dict로 대체하면 실패한다. `RunBudgetV2.absolute_llm_call_limit=24`, active profile limits `14/20/18`, Planning Revision 2, Additional Retrieval 2를 검증하고 Profile 변경 시 counter reset을 금지한다. `PromptContextV1`에 Conversation History/previous-run artifact/raw user request가 들어가면 실패한다.
- current Node Registry closure를 검증한다. `analysis.finalize`는 `assemble_work_analysis → validate_work_analysis`, `planning.assemble`은 `assemble_plan → validate_plan`, `review.aggregate_findings`는 `aggregate_review_findings → validate_review`를 같은 deterministic runtime node 안에서 수행해야 한다. 위 validator operation을 undocumented 별도 LangGraph Node/Resume Target으로 만들거나 validation을 생략하면 실패한다.
- Tool Route 한 번 확정 후 Retrieval·Planning의 Tool 재선택 0
- Planning atomic responsibility contract: frozen `OutputToolRouteV1`마다 `draft_action_objective_per_output_route` LLM이 business mutation objective/target/scope candidate만 만들고, 이어지는 `compose_arguments_per_output_route` LLM은 해당 objective + frozen route + allowlisted Tool Schema만 사용해 Arguments 표현만 작성해야 한다. 두 호출 중 어느 쪽도 Tool identity/effect를 재선택할 수 없다. 다중 Action Dependency 생성·정규화·DAG cycle 검증은 deterministic `build_dependencies`가 수행하며 `planning.compose_dependencies` Product PromptRef 호출은 0건이다. 같은 안정적 외부 Resource identity의 후속 Action만 frozen route 순서상 직전 동일 Resource Action에 의존하고, CREATE/서로 다른 Resource를 임의 직렬화하지 않는지 검증한다.
- Tool Route의 결정적 `PolicyPreconditionResolver` 검증: `TASK + CREATE`는 기존 미완료 Task 중복 검사용 Tasks READ를, `CALENDAR + CREATE`는 Event/FreeBusy 충돌 검사용 Calendar READ를 필수 IN Route로 포함한다. 이 Route 보강은 OUT Tool을 변경하거나 두 번째 Tool 선택으로 계수하지 않는다.
- Policy Precondition READ가 사용자의 명시적 Source·기간·Resource 범위를 벗어나면 자동 확장 금지. `SCOPE_EXPANSION_REQUIRED` Confirmation 전에는 해당 Route를 실행할 수 없고, 거절 후 필수 검사를 생략한 Write Plan을 생성하면 실패다. Confirmation 후에는 Application/Confirmation Controller가 `PolicyConfirmationReceiptV1`과 `POLICY_CONFIRMATION_RECORDED` Audit을 만들고 Tool Route owner checkpoint에서 재개해 승인된 범위만 Input Route로 확정한다.
- Policy Confirmation Receipt는 Agent/LLM이 생성할 수 없고 `meta.based_on + decision_context_hash`가 현재 active revision과 일치해야 한다. upstream revision 변경 후 stale Receipt 재사용, DECLINED Receipt를 허용 근거로 사용, Audit ID/Checkpoint Receipt ID 불일치는 모두 실패다.
- Confirmation same-owner resume 검증: `RequestConfirmation → WAITING_CONFIRMATION → interrupt(semantic_owner_id + AgentNodeResumeTargetV2 + interrupt_id)` → validated `ConfirmationResponseV1` → deterministic `ConfirmationResponseProjectionV1` → `ResumeConfirmation → 발생 전 안전 Domain 상태 → 동일 owner checkpoint` 순서가 유지되어야 한다. 아래 6개 owner를 각각 독립 case로 검증하며 하나라도 다른 owner로 resume하면 실패다.
    - `REQUEST_UNDERSTANDING → REQUEST_UNDERSTANDING`
    - `TOOL_ROUTE → TOOL_ROUTE`
    - `RETRIEVAL → RETRIEVAL`
    - `WORK_ANALYSIS → WORK_ANALYSIS`
    - `PLANNING → PLANNING`
    - `REVIEW → REVIEW`
    
    각 case에서 `AgentNodeResumeTargetV2.semantic_owner_id`가 Confirmation owner와 일치하고, selected Graph Profile의 exact mapping으로 얻은 `compiled_subgraph_id`와 `node_id`가 NodeRegistry에 등록돼 있으며 `graph_version`이 현재 resume-contract version과 일치해야 한다. wrong owner, unregistered node, stale/wrong graph_version, user/LLM-supplied arbitrary node ID는 모두 fail-closed하고 다른 Agent 호출이나 guessed resume로 진행하지 않는다.

- **Main-control resume target regression:** global `MainResumeStageIdV1` exact set은 `RETRIEVAL_ENTRY | PLANNING_ENTRY | REVIEW_ENTRY | PREFLIGHT | READ_EXECUTION | VERIFICATION | RECOVERY | CANCEL_RESOLUTION`다. `RETRIEVAL_ENTRY`는 ContextAdjustment/cache-loss restart, `PLANNING_ENTRY`는 corrective-plan re-entry, `REVIEW_ENTRY`는 Modify/PrepareRetry/RefreshExpiredAction, `CANCEL_RESOLUTION`은 RequestCancel coordinator에만 사용한다. Reauth/Recovery는 suspend 직전 registered safe target만 복원한다. `PREFLIGHT`는 `Run=WAITING_APPROVAL + current Write Attempt in-flight fact=0 + BeginExecutionAttempt 전 credential failure`에만 Reauth return target으로 허용한다. `WAITING_APPROVAL + Attempt EXECUTING/uncertain`이면 PREFLIGHT target 발급은 실패이며 delivery/existing-result reconciliation 뒤 `VERIFICATION | RECOVERY`만 허용한다. `READ_EXECUTION`은 `Run=EXECUTING + Legacy READ Action=EXECUTING + ExecutionAttempt row=0`에서만 허용하고, 승인형 Write에서 사용하면 실패다. `ACTION_EXECUTION`, `FINALIZE`, free-string stage, stale graph/profile은 fail-closed한다.
- **Profile identity regression:** six `SemanticAgentOwnerIdV1`은 모든 profile에서 유지하지만 compiled subgraph 수/ID는 SINGLE=1, THREE=3, SIX=6 exact mapping을 따른다. semantic owner ID를 physical subgraph ID로 사용하거나 SINGLE/THREE에서 six physical subgraphs를 생성하면 실패다.
    
- resumed Product Prompt에는 Controller가 정규화한 bounded `confirmation_response`만 optional Root Field로 허용한다. Raw resume payload, `interrupt_id`, checkpoint metadata, resume target을 Prompt에 직렬화하거나, 응답을 다른 Agent invocation에 자동 승계하면 실패다. 최초 invocation에서는 `confirmation_response`가 없어야 한다.
- Duplicate/Conflict Override Action은 `WorkAnalysisResultV2.policy_confirmation_receipt_refs`와 Approval Snapshot이 같은 APPROVED Receipt를 참조해야 하며 누락·stale이면 Domain Validation/Preflight에서 Claim 전에 차단한다.
- 위 Policy Precondition READ가 필요한 Action은 사용자 Arguments가 충분하더라도 해당 중복·충돌 검증을 생략한 채 Planning으로 직행하지 않는다.
- `InputRoutePlanV1`과 `OutputPlanV1` 독립 revision 검증: OUT-only 변경은 기존 Retrieval을 stale 처리하지 않고 Planning·Review만 재생성
- Artifact stale 판정은 하드코딩 단계 목록이 아니라 `meta.based_on`의 active revision 비교로 검증
- Retrieval LLM의 MCP 직접 호출 금지, deterministic Read Node만 `input_routes[].allowed_read_tool_ids` 범위에서 `ConnectorReadPort`를 호출하도록 허용
- Connector 접근 공통 경계 검증: React·FastAPI Route·Application·LangGraph·Agent·Domain에서 외부 Provider API/SDK 직접 호출·직접 Provider Client 구성 0건. **Application의 외부 I/O dependency는 `ConnectorReadPort | ConnectorWritePort | OAuthCredentialPort` 같은 abstract Connector Application Port로만 제한**하되, Application 내부 semantic binding은 structural `SignedToolRegistry`에서 `ValidatedConnectorToolBindingV1`으로 먼저 확정한다. `ConnectorRuntimeRegistry`, `MCPClientPort`, concrete Connector Adapter/Transport의 direct production caller는 Core-side Connector Adapter/transport implementation뿐이며 FastAPI Route·Application·LangGraph adapter/Agent·Domain direct call은 0건이어야 한다. 모든 Connector Browse/Count/Detail, Retrieval Read, Write, Verification, Recovery 조회는 `Application operation → SignedToolRegistry binding → Connector Application Port → Core-side Connector Adapter → ConnectorRuntimeRegistry/FakeMCPTransport(MCPClientPort) → MCP Tool` 경계를 통과한다. Connector Adapter의 `application/tool_registry/**` import는 0건이어야 한다. Provider Adapter 단위 테스트는 해당 Connector MCP Server 내부에서만 수행한다. P0 Google Workspace는 Gmail·Tasks·Calendar를 이 공통 계약으로 검증한다.
- **Tool catalog summary equality:** 07의 Gmail/Tasks/Calendar resource별 Tool 목록(§7~9)의 합집합은 07 current Signed Tool Registry exact set(§27) 및 16 provider-operation manifest와 exact set-equality여야 한다. `gmail_get_attachment`를 포함해 missing/extra Tool ID가 1개라도 있으면 실패다.
- 특정 Connector MCP unavailable/Tool Schema invalid 상황에서 제품 Core가 해당 Provider API 직접 호출로 fallback하지 않고 Connector 단위 NOT_READY/Recovery로 전환함을 검증
- Run 시작 뒤 Request Understanding 호출 전에 `StartAnalysis`가 정확히 한 번 적용되어 `CREATED → ANALYZING`이 되어야 한다. `StartAnalysis.applied=false`인데 Agent를 호출하면 실패다.
- Request Understanding의 정상 `COMPLETE` disposition은 반드시 Tool Route Subgraph로 정확히 한 번 연결되어야 한다. Release Graph의 Mermaid/Router 중 어느 한쪽에서 이 Edge가 누락되거나 Retrieval·Planning으로 직접 건너뛰면 실패다.
- Retrieval 공식 disposition 가시성 검증: `NEEDS_MORE_DATA`는 local budget이 남을 때만 bounded Retrieval local loop로 이어지고, budget 소진 시 `NEEDS_CONFIRMATION | PARTIAL | BLOCKED` 중 하나로 정규화되어야 한다. `NO_FETCH_NEEDED`는 `SUFFICIENT`와 동일한 analysis_requirement Guard를 거쳐 Work Analysis 또는 Planning으로 진행한다. Release Graph/Router에서 이 두 branch가 누락되면 실패다.
- Retrieval self-loop continuation ownership 검증: List/Search 결과의 raw `next_page_token`은 현재 Run의 Run Retrieval Cache read-result entry에만 존재하고 Local/Main State·Checkpoint·Domain DB·Prompt·Trace·Audit에는 원문이 없어야 한다. Local State에는 `read_result_handle`과 hash/summary만 남는다.
- `NEXT_PAGE` 검증: prior handle의 `run_id + route_id + query identity/hash`가 현재 frozen IN Route와 일치하고 continuation이 미소진일 때만 결정적 Read Node가 raw continuation을 resolve해 `ConnectorReadPort`의 `page_token` 입력으로 주입한다. unknown/cross-run/mismatched/exhausted handle은 Provider 호출 0건으로 fail-closed한다.
- Follow-up `plan_query` Projection 검증: Round 1/2는 `current_round_no + prior QueryAttemptV1 + unresolved SufficiencyIssueV2 + bounded read-result summary`를 볼 수 있지만 raw Page Token·Provider-native query·MCP argument를 보지 않는다. Round 0 입력과 follow-up 입력을 혼동하거나 Main State scratch로 승격하면 실패다.
- 동일 Query + 동일 continuation state 재실행은 새 Additional Retrieval round로 인정하지 않는다. `NEXT_PAGE`, 필요한 `DETAIL_FETCH`, 또는 미해결 issue에 근거한 변경 Query처럼 새 정보 획득 가능성이 있어야 한다.
- Retrieval self `NEEDS_MORE_DATA`가 Supervisor로 반환되거나 `RetrievalRequiredV1`/새 WorkflowSignal/Main State retry DTO를 생성하면 실패다. Work Analysis/Review의 외부 추가 Retrieval 요청과 self-loop를 분리해 검증한다.
- 새 Retrieval invocation 진입 시 Run이 `ANALYZING | PLANNING`이면 `BeginRetrieval → RETRIEVING`을 적용하고, 같은 Retrieval 내부 Additional Retrieval처럼 이미 `RETRIEVING`이면 반복 적용하지 않는다. Planning/Review Back-edge에서 `PLANNING → RETRIEVING`이 막히면 실패다.
- 새 Planning 진입 시 Run이 `ANALYZING | RETRIEVING`이면 `BeginPlanning → PLANNING`을 적용한다. no-fetch 경로의 `ANALYZING → PLANNING`과 Retrieval 완료 경로의 `RETRIEVING → PLANNING`을 모두 검증하고, Review Revision처럼 이미 `PLANNING`이면 반복 적용하지 않는다.
- **Preflight stale classification:** Approval TTL 또는 Source/Policy/Tool-Schema/approval snapshot binding stale은 `ExpireApproval → RefreshExpiredAction + same-UoW REVIEW_ENTRY handoff → fresh Review → new Approval`; current Policy `DENY`는 `BlockRun`; post-Claim `CLAIM_ARGUMENTS_MISMATCH`는 Provider Write 0 + `MarkFailed(NOT_SENT)`로 각각 단일 경로여야 한다.
- Preflight/Claim `applied=false`가 `ACTION_EXECUTION`으로 fall-through하거나 곧바로 `FINALIZE`되지 않는지 검증한다. `current_status + next_allowed_commands`를 재조회해 재승인·Recovery·Reauth·Cancel/in-flight resolution·이미 Terminal 중 하나로 결정적으로 조정해야 하며 같은 Claim의 무조건 자동 재시도는 금지한다.
- Policy Block은 Claim 전 `BlockRun`이 실제 `applied=true`로 Run을 `BLOCKED` 처리한 경우에만 `FINALIZE`한다. State/Version/Command conflict를 `BLOCKED` 또는 `FAILED`로 오분류하면 실패다.
- Recovery는 recheck 필요 시에만 Verification으로 복귀하고 `RECOVERY_REQUIRED` 유지 시 explicit resolve/re-auth까지 suspend하며, terminal failure/block/cancel에서 무한 Verification loop가 없음을 검증
- Recovery 종료 분기 단일성 검증: `ResolveRecovery(FAIL)`은 Run `FAILED → FINALIZE` 한 경로만 가져야 하고 `ACCEPT_PARTIAL`과 같은 Response 경로에 중복 매핑되면 실패다. `ResolveRecovery(ACCEPT_PARTIAL)`은 cancel intent가 없을 때만 `COMPLETED` 결과를 합성한 뒤 Response/FINALIZE로 진행한다.
- `Retrieval.PARTIAL + usable Evidence 없음`은 비Terminal Run에서 `FINALIZE`로 직접 진입하지 않는다. 처리 불가 안내를 저장하는 `CompleteAnswerOnlyRun → COMPLETED`가 먼저 적용된 뒤 FINALIZE해야 하며, Domain Command 없이 종료하면 실패다.
- `ACTION_EXECUTION` 결과 분기 완전성 검증: `EXECUTED`만 Verification으로 진입하고, `UNKNOWN_RESULT`는 Recovery다. `FAILED + NOT_SENT` 발생 시 dependency 없는 approved/executable Action이 남아 있으면 다음 `PREFLIGHT`로 계속 진행하고, FAILED predecessor dependent의 Claim은 0이어야 한다. 독립 Action이 없거나 모두 처리된 뒤 unresolved `FAILED + NOT_SENT`가 남을 때만 retry/cancel 대기 suspend로 이동하며 `CompleteWriteRun`은 금지한다. `prepare-retry` 후 `FAILED → MODIFIED → Review 재실행 → Domain Validation → 새 Approval` 순서를 통과해야 한다. 실행 중 Cancel은 Terminal로 직행하지 않고 durable cancel intent를 유지한 채 in-flight 결과를 먼저 확정한다. `EXECUTING → VERIFICATION` implicit fall-through, `FAILED → FINALIZE`, `EXECUTING → CANCELLED` 직접 종료는 실패다.
- dispatch persistence classifier 검증: `success=true → STORE_SUCCESS`, `NOT_SENT → MARK_FAILED`, `MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST → MARK_UNKNOWN_RESULT` 외 분기는 금지한다. HTTP status/exception name만으로 NOT_SENT를 추론하면 실패다. classifier는 Connector/DB 호출 0건이어야 한다.
- 승인형 Write 첫 Verification 전에 `BeginVerification`이 정확히 한 번 적용되어 정상 경로는 Run `WAITING_APPROVAL → VERIFYING`, 취소 중 이미 EXECUTED된 결과 확인 경로는 `CANCEL_REQUESTED → VERIFYING`이 되어야 한다. 후자의 경우 APPLIED `RequestCancel` Receipt에서 cancel intent가 계속 복원되어야 한다. 다중 Action DAG에서 Run이 이미 `VERIFYING`이면 다음 Action마다 `BeginVerification`을 반복 호출하지 않는다.
- 각 Action은 선행 Action이 `VERIFIED`된 뒤에만 Dependency상 다음 Action으로 진행한다. 모든 승인 대상 Action이 Terminal이고 미해결 `UNKNOWN_RESULT/MISMATCH`가 없을 때 cancel intent가 없으면 `CompleteWriteRun`으로 Run `VERIFYING → COMPLETED`와 Plan `COMPLETED`를 적용하고, cancel intent가 있으면 `FinalizeCancel → CANCELLED`를 우선한다. Action만 `VERIFIED`하고 Run을 열린 상태로 남기거나 Domain Command 없이 Run을 직접 `COMPLETED`로 저장하면 실패다.
- `ACTION_EXECUTION` 중 Cancel 요청은 즉시 `FINALIZE/CANCELLED`로 가지 않는다. `RequestCancel` 이후 신규 Claim·Write 0을 보장하고, 현재 in-flight Action 결과를 `EXECUTED | UNKNOWN_RESULT | FAILED`로 확정한 뒤 필요한 Verification/Recovery/Reauth를 마치고 `FinalizeCancel`해야 한다. `EXECUTING → CANCELLED` 직접 덮어쓰기는 실패다.
- OAuth reauth success 뒤 `ResumeAfterReauth` Receipt/Audit + Domain transition이 `applied=true`가 되기 전 LangGraph resume 0. `ResumeAfterReauth`는 saved Run status뿐 아니라 current child fact를 다시 검증한다: `PREFLIGHT`는 in-flight Write Attempt 0, `READ_EXECUTION`은 Legacy READ Action EXECUTING + ExecutionAttempt 0, `VERIFICATION/RECOVERY`는 해당 durable fact를 요구한다. stale/missing/child-fact-mismatched target은 `CHECKPOINT_MISMATCH` 또는 `RESUME_NOT_ALLOWED`로 fail closed한다.
- Startup `SAFE_CHECKPOINT_RESUME`는 State Contract source-state matrix를 exact 검증한다. `CREATED|ANALYZING|RETRIEVING|PLANNING` + binding exact match + cancel intent false + unresolved Write fact 0만 PASS다. `WAITING_CONFIRMATION|WAITING_APPROVAL|EXECUTING|VERIFYING|CANCEL_REQUESTED|REAUTH_REQUIRED|RECOVERY_REQUIRED|terminal`에서 generic Graph resume가 1회라도 발생하면 실패다.
- `WAITING_CONFIRMATION` restart는 interrupt snapshot restore 후 `ResumeConfirmation`, `WAITING_APPROVAL` restart는 Approval UI restore, `REAUTH_REQUIRED` restart는 `ResumeAfterReauth`, `RECOVERY_REQUIRED` restart는 `ResolveRecovery/Reauth`, `CANCEL_REQUESTED` restart는 cancel-resolution coordinator를 각각 사용해야 한다.
- `EXECUTING|VERIFYING` restart에서 checkpoint node를 그대로 replay하지 않고 persisted Action/Attempt/Verification fact를 먼저 reconcile해야 하며 이미 dispatch된 Write 재호출 0을 검증한다.
- `RequestCancel`의 APPLIED Command Receipt는 `FinalizeCancel`까지 durable cancel intent의 기준점이다. Run이 결과 확정 중 `VERIFYING | RECOVERY_REQUIRED | REAUTH_REQUIRED`로 이동하거나 앱이 재시작되어도 Receipt에서 cancel intent를 복원하고 새 Claim·Write 0을 유지해야 한다. 모든 in-flight 결과가 해결된 뒤 cancel intent가 활성인데 `CompleteWriteRun → COMPLETED`로 끝내면 실패이며 `FinalizeCancel → CANCELLED`가 우선한다.
- **Legacy READ cancel E2E:** cancel before `ClaimReadAction`, after Claim/before ConnectorRead, while ConnectorRead in-flight, after read result/before `CompleteReadAction`, after `CompleteReadAction`/before `FinalizeReadAction`, `AUTH_EXPIRED + cancel`, crash + restart를 모두 검증한다. RequestCancel 뒤 새 ConnectorRead/READ_EXECUTION reauth 0; existing READ는 `CancelPendingAction | FailReadAction | CompleteReadAction+FinalizeReadAction` 중 current fact에 맞는 기존 Command로 settle되고 `FinalizeCancel` 전 READ `EXECUTING|EXECUTED`가 0이어야 한다.
- pre-dispatch cancel은 각 pending Action에 개별 `CancelPendingAction` Receipt/UoW를 적용한 뒤 `FinalizeCancel`; 성공 Write가 0이면 terminal result `CANCELLED`, durably observed external mutation이 하나 이상이면 `PARTIAL`이어야 한다.
- `BlockRun`은 State Contract source set에서 Active/Unknown/미검증 Write Attempt와 unresolved MISMATCH가 없을 때만 허용한다. Plan이 있으면 미실행 `PROPOSED|MODIFIED|APPROVED|EXPIRED → BLOCKED` → ACTIVE Approval `REVOKED` → Plan `CANCELLED` → Run `BLOCKED` 순서를 같은 UoW에서 적용한다. `DEPENDENCY_BLOCKED` 신규 생성은 RejectAction contract에서만 검증한다. `VERIFYING` source의 post-publish BLOCK은 이미 dispatch된 Write가 모두 final일 때만 허용한다.
- **Review-driven published Plan revision:** State Contract의 post-review matrix를 exact 검증한다. `WAITING_APPROVAL | VERIFYING`에서 `REVISE|RETRIEVE_MORE|ROUTE_RECONSIDERATION → BeginPlanning + old ACTIVE Approval REVOKED + current Plan SUPERSEDED`가 같은 UoW여야 하고, `CONFIRM → RequestConfirmation`, guarded `BLOCK → BlockRun`을 따른다. supersession 뒤 old Plan Action의 approve/modify/retry/claim은 effect 0이며 stale `Action=APPROVED`만으로 새 Attempt/Write가 생기면 실패다. concurrent BeginPlanning/Claim은 supersession-first면 Claim 0, claim-first면 BeginPlanning의 in-flight guard가 supersession 0이어야 하며 둘 다 commit되면 실패다. 이미 발생한 external effect/terminal Action fact를 재실행·덮어쓰면 실패다.
- **All-terminal no-dispatch completion:** 모든 planned Action이 Reject/Cancel/Dependency Block 등 final fact로 닫혀 외부 Write가 0건이어도 unresolved 0 + cancel intent false이면 `CompleteWriteRun: WAITING_APPROVAL → COMPLETED` + Plan COMPLETED를 허용한다. Domain Command 없이 Plan/Run을 직접 완료하면 실패다.
- `CREATE_CORRECTIVE_PLAN` Recovery는 `cancel_intent_active=false`일 때만 Domain `RECOVERY_REQUIRED → PLANNING` 전이와 새 Plan Revision 생성으로 이어져야 한다. cancel intent가 활성인데 corrective plan이나 새 Claim/Write를 만들면 실패다. 기존 `MISMATCH` Action·Approval·Attempt를 재사용하거나 Recovery에서 Verification으로 무조건 복귀하면 실패다.
- `cancel_intent_active=true`인 `RECOVERY_REQUIRED`에서는 일반 `ACCEPT_PARTIAL → COMPLETED`로 취소 의도를 지우지 않는다. 결과 확인이 끝나면 `ResolveRecovery(CANCEL) → CANCELLED`, Verification으로 복귀했다면 검증 완료 후 `FinalizeCancel → CANCELLED`로 닫아야 한다.
- Retrieval에 Run-scoped RAG 단계 존재 및 후보 전체의 downstream 전달 금지
- Retrieval `PARTIAL`은 usable Evidence가 있으면 `coverage=PARTIAL`을 보존한 채 Work Analysis/Planning으로 전달하고, usable Evidence가 없으면 FINALIZE한다. Retrieval이 직접 Answer 내용을 작성하거나 RESPONSE_SYNTHESIS로 우회하는 경로 금지
- 복수 IN Route의 `RetrievalResultV1.source_statuses`는 Source별 `COMPLETE | PARTIAL | FAILED | NOT_ATTEMPTED`를 정확히 보존하며, 한 Source 실패를 전체 성공으로 표시하거나 전체 `coverage`만으로 미확인 Source를 확인했다고 추론하지 않음
- SourceSegment의 `SourceContentSecurityMetaV1`은 모든 Connector 본문을 `UNTRUSTED_SOURCE_CONTENT / DATA_ONLY`로 유지한다. P0 Google Workspace 본문도 동일하다. `instruction_like_content_detected=false`여도 신뢰 데이터로 승격하지 않으며 Source 지시가 RequestIntent·ToolRoute·WorkflowSignal로 변환되지 않음
- Calendar FreeBusy/Busy interval에서 가능한 시간 구간 계산은 deterministic `retrieval.resolve_availability`가 수행하고 LLM이 시간 구간 산술을 임의 생성하지 않음
- Node별 선언 Projection 밖 Main/Local State 전달 금지
- `run_input.user_request`는 Main State의 읽기 전용 원문이다. Request Understanding은 최초 입력으로 이를 소비하고, Work Analysis/Planning은 06/15가 명시한 최소 typed projection에서만 사용할 수 있다. **Retrieval Query/Evidence에는 raw `user_request` Projection이 0**이며 `RequestIntentV2 + frozen input_routes + retrieval_budget`를 소비한다. 어떤 Subgraph도 raw request를 별도 장기 Memory나 owner-local authority field로 복제하지 않는다.
- Confirmation은 `interrupt_id + semantic_owner_id + AgentNodeResumeTargetV2`으로 발생 Node checkpoint에 복귀하며 무조건 Request Understanding으로 재시작하지 않음. 공식 `NEEDS_CONFIRMATION` 뒤 `RequestConfirmation`이 먼저 `ANALYZING | RETRIEVING | PLANNING → WAITING_CONFIRMATION`을 적용해야 하고, 사용자 응답 검증 뒤 `ResumeConfirmation`이 발생 전 안전 Domain 상태를 복원한 후에만 Agent를 재호출한다. Resume target은 `ResumeTargetRegistry`가 `NodeRegistry` current entry로 발급·검증한 값만 허용하고 LLM 임의 Node ID는 차단
- `RequestConfirmation.applied=false`인데 interrupt를 생성하거나 `ResumeConfirmation.applied=false`인데 owner Agent를 재호출하면 실패다. Policy Confirmation Receipt는 실제 사용자 응답 검증과 동일 interrupt context에 묶여야 한다.
- 모든 공식 disposition은 정확히 하나의 Edge·Interrupt·Terminal 경로를 가지며 unknown disposition은 fail-closed. bounded repair 뒤에도 유효하지 않은 Enum·Version·Disposition은 다음 Agent/Tool 호출 0, `RequireRecovery(CONTRACT_VIOLATION) → RECOVERY_REQUIRED`여야 한다. 복구 불가가 확정되면 `ResolveRecovery(FAIL) → FAILED`; unknown 값을 임의 기존 Edge로 매핑하거나 FINALIZE로 직접 보내면 실패다.
- `FINALIZE`는 임의 상태 변경 Node가 아니다. `CompleteAnswerOnlyRun | BlockRun | CompleteWriteRun | FinalizeCancel | ResolveRecovery(...)` 중 해당 Domain 종료 Command가 먼저 적용되어 Run이 Terminal이어야 END로 갈 수 있다. `WAITING_APPROVAL | VERIFYING | REAUTH_REQUIRED | RECOVERY_REQUIRED | CANCEL_REQUESTED` 상태를 FINALIZE가 직접 덮어쓰면 실패다.
- `Request.INVALID`의 비정책 처리 불가 안내는 `CompleteAnswerOnlyRun → COMPLETED`, Policy 차단은 `BlockRun → BLOCKED`로 구분한다. Agent의 `INVALID/BLOCKED` 문자열만 보고 Run 상태를 직접 정하지 않는다.
- Reauth는 전역 Domain overlay로 검증한다. Retrieval·Preflight/Approval·Legacy READ·Verification·Recovery의 Connector 접근 중 Credential 실패 시 `REAUTH_REQUIRED`로 suspend한다. 재인증 뒤 `Run.status + child Action/ExecutionAttempt/delivery fact`가 허용하는 registered target으로만 돌아가며 dispatch된 Write 재전송은 0이어야 한다. Legacy READ 401은 `MAIN_CONTROL:READ_EXECUTION`으로 같은 non-mutating READ를 재개할 수 있지만 Write path는 이 target을 사용할 수 없다.
- Synthetic Branch Completeness Fixture는 Request/Tool Route/Retrieval/Work Analysis/Planning/Review의 모든 공식 disposition과 Domain/Application의 Preflight·Verification·Recovery 결과 분기를 최소 1회 이상 통과해야 한다. 각 Case는 END, 사용자 interrupt/suspend 또는 명시된 owner back-edge 중 하나로 닫혀야 하며 implicit fall-through·무한 self-loop·정의되지 않은 terminal을 허용하지 않는다.
- `workflow_phase`는 닫힌 Enum, `selected_resource_refs`는 `SelectedResourceRefV1`, Request constraint/ambiguity는 Typed Schema 사용
- `OutputPlanV1` discriminated-union shape: ANSWER에는 `output_routes` field가 absent, ACTION에는 minItems=1. ANSWER serializer가 `output_routes=[]`를 만들거나 두 representation을 모두 허용하면 실패다.
- `ConnectorReadPort.execute_read` actual Protocol과 16 mapping은 `ValidatedConnectorToolBindingV1` signature가 exact match해야 하며 tool_id-only signature 재도입, Adapter의 `application/tool_registry/**` import, 별도 tool→connector lookup authority는 실패다.
- Upstream State revision 시 based_on downstream Artifact stale 처리 검증
- `PlanReviewResultV2` discriminated union에서 `PASS + confirmation` 같은 불가능 조합 생성 차단
- Prompt Registry Key 검증
- Supervisor는 Node만 Routing하고 선택된 Agent·Application Node가 PromptRef를 확정
- LLM Router·Model의 Prompt 선택 금지
- Agent별 단일 Prompt 금지
- Repair·Revision 별도 Prompt ID
- Prompt Manifest Version·Hash·Schema 검증
- Local SLLM Node별 Complexity Metadata(`required/optional field count`, schema depth, union branches, max enum cardinality, tool candidate count, input projection token)를 기록하고 승인된 Complexity Profile 밖 Config는 재 Contract Gate 없이 Release 금지
- Complexity Sweep은 하나의 축만 변경해 Contract Validity와 Semantic Accuracy를 분리 측정하며, 임의의 전역 `Enum N개`, `Tool N개` 상한을 테스트 없이 하드코딩하지 않음
- Tool Calling 단독, Structured Output 단독, Tool Calling+별도 constrained JSON 조합은 서로 다른 Runtime Candidate로 Contract Test
- `ORACLE` Node Run과 `LIVE` Handoff Run 분리
- `RESOURCE_SELECTED`에서 불필요한 Workspace Search 금지
- exact selected Resource 1개 + exact detail READ Tool 1개인 초기 Retrieval은 `plan_query` LLM 0, deterministic `DETAIL_FETCH` validator 통과, Connector detail READ 1회를 검증한다. 복수 후보·일반 Agent Search·follow-up은 query-planning LLM을 유지한다.
- 제목 하나와 검증된 기본 Task List 하나로 고정된 `TASK + CREATE`는 중복 검사 Query Planning LLM 0, deterministic `SEARCH + CONTAINER_REF` validator 통과, 실제 Task READ와 중복 Work Analysis 유지를 검증한다. 복수 Task List·추가 검색 제약·follow-up에서는 Query Planning LLM을 유지한다.
- `output_mode=ANSWER`에서 Action Argument/Plan Node 미호출
- 단순 ACTION은 Arguments가 사용자 입력으로 충분하고 관계·충돌·중복 해석이 불필요하면 Work Analysis skip 가능; ACTION 자체만으로 Analysis 강제 금지. 단 `TASK + CREATE` 중복 검사와 `CALENDAR + CREATE` 충돌 검사는 `01-B`의 P0 필수 Policy Precondition이므로 이 skip 조건에 포함하지 않는다.
- Policy-only Task/Calendar CREATE는 entity/temporal LLM을 호출하지 않고 guarded duplicate/conflict 책임으로 직행한다. fact operand 2개 미만은 deterministic empty candidate + relation validation, 2개 이상은 duplicate/conflict LLM candidate + relation validation을 검증한다. 명시적 Analysis 요청의 전체 relation 경로를 이 최적화로 축소하면 실패다.
- 정확한 Task/Calendar CREATE는 검증된 Intent·Route·Policy-required Work Analysis가 모두 일치할 때만 objective/arguments 및 빈 Review Finding을 결정적으로 materialize할 수 있다. duplicate/conflict·risk·ambiguity·relation·추가 제약이 있는 fixture에서 LLM Review 또는 Confirmation을 잘못 생략하는 `FALSE_SKIP`은 실패다.
- Work Analysis의 `DUPLICATES`·`CONFLICTS_WITH` 확정과 `action_necessity=NOT_REQUIRED`는 LLM 출력만으로 허용하지 않는다. `relation_candidates`는 결정적 relation validator를 거쳐 `validated_relations`로 승격되어야 하며, 검증 전 후보가 `WorkAnalysisResultV2.relations`에 직접 포함되면 실패다. 정규화된 Source 데이터·Calendar availability·현재 Task 상태로 검증되지 않은 유사 후보 또는 불확실 관계는 `relation_validation_ambiguities`/위험·확인 경로로 남긴다.
- 정확 Task 중복의 기본 경로는 `action_necessity=NOT_REQUIRED → 새 Action 0`이다. 사용자가 중복 사실을 인지한 상태에서 추가 생성을 요구하면 `DUPLICATE_OVERRIDE_REQUIRED` 2차 Confirmation 전에는 Planning/Approval로 진행할 수 없다.
- 검증된 Calendar 충돌은 `CONFLICT_OVERRIDE_REQUIRED` 2차 Confirmation 전에는 충돌 Event Action Plan을 만들 수 없다. Confirmation 응답은 Work Analysis owner checkpoint로 resume하며 Request Understanding부터 재시작하지 않는다.
- Action Output Route가 존재해도 Retrieval/Analysis에서 목표가 이미 충족된 정확 중복·동일 상태를 확인하면 `action_necessity=NOT_REQUIRED`로 Planning이 새 Action 없이 Evidence 기반 Answer로 종료 가능. 이때 Tool Route를 재선택하거나 기존 Resource를 중복 생성하지 않음
- `NO_TOOL_NEEDED`라도 `analysis_requirement=REQUIRED`이면 Work Analysis를 건너뛰지 않으며, `NONE`일 때만 Planning(Answer)로 직행
- Review 없음·있음 Candidate가 Domain과 deterministic Policy 코드를 공유


## 9. UI

- Setup·Google Login·3열 Layout
- Gmail·Tasks·Calendar Pagination·Session Cache
- Resource Selection·Agent Search
- Confirmation·Approval·Modify·Partial Approval
- Verification Diff·UNKNOWN_RESULT·Recovery
- Refresh·SSE reconnect·duplicate click
- Chrome·Edge·Keyboard·Focus·Sanitization

## 10. Failure Injection

| 위치 | 오류 | 기대 |
| --- | --- | --- |
| LLM | Timeout·Invalid Output | Repair·Fallback 상한 |
| Google Read | 401·429·5xx | Reauth·제한 Retry |
| Connector Write | 전달 전 실패 | FAILED |
| Connector Write | 응답 유실 | UNKNOWN_RESULT |
| Verification | 404·Timeout | 즉시 실패 확정 금지 |
| SQLite | Busy·Disk Full | Write 전 차단 |
| Audit | 저장 실패 | 안전 Command 실패 |
| MCP | Exit | 1회 Restart 또는 UNKNOWN_RESULT |
| SSE | Loss | Domain 계속·UI 복원 |
| Launcher | Shutdown Timeout | Recovery Marker |
| Experiment Runner | Budget 초과 | 새 Item 시작 중단·Partial 표시 |
| Grader | Schema·Version 불일치 | 후보 판정 중단 |


### 10.1 External-control → background handoff mandatory gate

다음은 모두 P0 integration/failure-injection gate다.

- Confirmation: HTTP projection → Domain `ResumeConfirmation` + `workflow_handoffs` same-UoW commit → exact originating owner target → one-shot `ConfirmationResponseProjectionV1`; raw request/interrupt/checkpoint metadata Prompt input 0.
- Context Adjustment: `EXCLUDE_EVIDENCE`와 `RETRIEVE_MORE` 각각 `MAIN_CONTROL:RETRIEVAL_ENTRY`; stale `RetrievalHeadV1` revision CAS reject; restart 뒤에도 same revision authority; new Retrieval revision/head 발급.
- Approve → `PREFLIGHT`; Modify/PrepareRetry/RefreshExpiredAction → `REVIEW_ENTRY`; Reject → `PREFLIGHT`에서 next independent action 또는 all-final terminal path; direct API/Application→LangGraph invocation 0.
- Reauth: OAuth success만으로 Run resume 0. `/resume(REAUTH_COMPLETED)` + `ResumeAfterReauth(applied=true)` 뒤 exact stored target handoff만 허용.
- Recovery: UNKNOWN_RESULT/VERIFICATION_MISMATCH/CHECKPOINT_MISMATCH/CONTRACT_VIOLATION RECHECK target matrix exact; `NO_PROGRESS` handoff 0; corrective plan → `PLANNING_ENTRY`; terminal resolution은 business resume 0.
- SAFE_CHECKPOINT_RESUME: source-state gate PASS 뒤 durable handoff를 사용하고 direct supervisor call 0.
- Cancel: RequestCancel commit → `CANCEL_RESOLUTION`; WAITING_CONFIRMATION/WAITING_APPROVAL/REAUTH_REQUIRED/RECOVERY_REQUIRED/Legacy READ/in-flight Write 각각 기존 lifecycle commands만으로 settle; cancel intent 이후 new Claim/Write 0.

Crash/replay matrix:

```text
Domain mutation + handoff before COMMIT crash       → both absent
COMMIT after handoff stage / before admission crash → PENDING redrive
ExpireApproval COMMIT → crash before RefreshExpiredAction → stale Approval remains EXPIRED; new Approval 0
RefreshExpiredAction + REVIEW_ENTRY handoff before COMMIT crash → both refresh mutation/handoff absent
RefreshExpiredAction + REVIEW_ENTRY same-UoW COMMIT → crash before scheduling → restart/redrive exactly one Review continuation
admission claim / before submit crash                 → same persisted admission redrive
submit ACCEPTED / before worker start crash           → same admission redrive; post-ACCEPTED DB write 0
ALREADY_RUNNING with newer control                 → newer handoff not lost
SHUTTING_DOWN after user command commit             → next-start redrive
control apply commit / before CONSUMED CAS crash    → same handoff not patched twice; CAS only redriven
CONSUMED / before first owner I/O crash              → CONSUMED_CONTINUATION_RECOVERY from active lineage; generic SAFE resume 0; control reinjection 0
CONSUMED / after 1+ descendant checkpoints crash      → latest checkpoint with same active_handoff_id resumes only if current Domain/child-fact fence still authorizes target
Domain advances to REAUTH/RECOVERY/CANCEL/terminal before admission claim → state-specific coordinator wins; old admission 0
Domain advances after admission claim / before settlement → admission checkpoint may exist, settlement Run-version CAS=`AUTHORITY_STALE_RETIRED`; stale NORMAL head retired / recovery admission cleared; old owner I/O 0
ALREADY_RUNNING old-worker slot-release race         → exact same admission replay returns idempotent ACCEPTED and active admission is never released; different-admission conflict release rechecks Run authority and stale lower head becomes SUPERSEDED, so later sequence progresses without restart
HTTP response loss + same command replay            → same handoff_id, no duplicate control
stale checkpoint generation                         → BLOCKED_BINDING + Recovery, no guessed target
```

`RunExecutionAcceptedV1` five reason codes each require assertion of HTTP result, durable handoff status, Domain mutation count, retry/redrive behavior and SSE/Trace projection. `NOT_COMMITTED` is forbidden on valid post-commit scheduler input and must not cause Domain command replay.

Workflow handoff persistence contract tests are mandatory:

- START/no-control row round-trip: `control_kind=NONE`, `control=None`, `control_payload_hash=None`, version 0.
- non-NONE PENDING/DISPATCHED row round-trip: payload present, canonical hash exact, persisted version exposed.
- CONSUMED historical-control round-trip: `control=None`, original `control_kind` retained, original hash retained, payload NULL, DB CHECK PASS.
- `get/get_by_trigger_command_id/list_redriveable` return the same persisted version; every `mark_*` CAS uses it and returns exactly version+1. stale concurrent expected_version never falls back to raw SQL/hard-coded 0.
- SAFE_CHECKPOINT_RESUME response-loss replay: same command/hash resolves the same handoff through OperationalCommandReplay + trigger lookup for PENDING, DISPATCHED, and CONSUMED; same command/different hash conflicts; duplicate control patch=0.
- system retrieval-cache-restart uses the same trigger lookup and never creates a second row for the same reserved system key.
- startup invokes `ReconcileInflightExecutionsHandler` only after DB/migration/checkpoint + MCP/LLM readiness and drains it before any workflow redrive. It then invokes `RedriveWorkflowHandoffsHandler` initial drain and starts `WorkflowHandoffReconciliationLoop` using the **same Redrive handler** for service-live reconciliation. Orphan execution Handler live invocation=0. Startup batches repeat until no immediately actionable row/no durable progress; rows beyond one `limit` cannot starve. Direct WEP/LangGraph call from either reconciler=0.
- `ScheduleRunExecutionHandler` admission test: `NORMAL_HANDOFF` requires the PENDING dispatch head (or exact persisted DISPATCHED admission on redrive), computes current effective binding/Run authority version, and calls `claim_execution_admission` **before** WEP. `CONSUMED_CONTINUATION_RECOVERY` accepts a CONSUMED row with current active checkpoint lineage even when `get_dispatch_head(run_id)` is `None`, persists a recovery admission whose effective binding is latest checkpoint + `execution_kind=RESUME`, and never mutates the original handoff execution fields.
- admission/submit matrix: NORMAL claim `PENDING→DISPATCHED + execution_admission`; recovery claim `CONSUMED→CONSUMED + execution_admission`. `ACCEPTED` causes zero subsequent handoff mutation. Exact same `admission_id` replay while active must return idempotent `ACCEPTED`, never `ALREADY_RUNNING`. For a different-admission `ALREADY_RUNNING|SHUTTING_DOWN|NOT_COMMITTED|BINDING_MISMATCH`, release rechecks admission expected Run version against current Run.version: equal epoch restores the ordinary PENDING/BLOCKED/CONSUMED state, stale epoch makes NORMAL `SUPERSEDED` or clears only recovery admission. Inject worker start immediately after ACCEPTED and assert there is no post-ACCEPTED handoff CAS at all.
- effective-binding tests: original START handoff → CONSUMED → 2+ descendant checkpoint → recovery admission MUST carry `RESUME + latest checkpoint_id/generation + latest registered target`; original START is never replayed. Approve/PREFLIGHT and Modify/REVIEW_ENTRY descendants likewise resume latest checkpoint without rewind.
- authority-linearization tests: current Domain/child mutation that changes continuation legality increments Run version. If Reauth/Recovery/Cancel/terminal commits before admission claim, claim fails/defer. If admission claim commits first but authority changes before `mark_consumed_and_clear_payload` / `complete_recovery_admission`, settlement returns `AUTHORITY_STALE_RETIRED`: NORMAL row is atomically SUPERSEDED+admission-cleared, recovery stays CONSUMED+admission-cleared, and old owner I/O=0. No stale admitted dispatch head remains to be repeatedly redriven. If settlement commits first, later control does not retroactively invalidate already-linearized pure workflow work, but cancel intent and current Domain guards yield new Claim/Write=0. Inject authority change before claim, between claim/checkpoint, between checkpoint/settlement, and immediately after settlement.
- same-Run `run_sequence` tests: Approve A+Approve B, Approve+Reject, Modify+Approve, Reject+Reject commit in durable order; only normal dispatch head runs; a post-commit schedule call for non-head returns ALREADY_RUNNING without WEP call and row remains PENDING; lower settled sequence permits ordered checkpoint rebind of the immutable target; normal concurrent controls do not cause false CHECKPOINT_MISMATCH Recovery.
- same-admission replay regression: H1 admission A1 is ACCEPTED and worker A1 is active; live reconciler resubmits exact A1; WEP returns idempotent ACCEPTED, `release_execution_admission` call count=0, **worker/queue entry count does not increase**, worker settlement remains valid.
- stale-release/preemption regression: claim H1/A1 → newer Cancel/terminal/Reauth/Recovery commits and increments Run.version → WEP for H1 returns non-ACCEPTED → authority-aware release must never restore H1 to PENDING/BLOCKED; NORMAL H1 becomes SUPERSEDED and later state-specific H2 becomes dispatchable without second user action.
- stale-settlement liveness regression: H1/A1 settlement observes Run.version mismatch → `AUTHORITY_STALE_RETIRED`; NORMAL H1 becomes SUPERSEDED in that settlement transaction (recovery keeps CONSUMED and clears admission), next reconciliation never reuses A1 and lower `run_sequence` no longer blocks H2. If restart/live redrive sees the stale persisted admission before worker settlement, it uses `release_execution_admission(..., AUTHORITY_EPOCH_CHANGED)` and WEP invocation=0.
- supersession tests: Approve→Cancel before execution, terminal Recovery resolution with old PENDING/DISPATCHED/BLOCKED_BINDING rows, and process crash after supersede. `supersede_unconsumed_for_run` can retire every current unconsumed row hidden behind a blocked head in the same UoW before replacement stage; cancel/terminal-preempted BLOCKED rows do not create CHECKPOINT_MISMATCH Recovery; old continuation never redrives; CONSUMED work is not rewritten; cancel intent yields new Claim/Write=0.
- pre-first-checkpoint cancel: CREATED + no checkpoint + START without execution admission (PENDING/BLOCKED_BINDING) commits cancel intent and START SUPERSEDED without RESUME; `run.continue_cancel_resolution` reaches CANCELLED with Agent/LLM/Connector/LangGraph=0. `DISPATCHED` without admission is invalid. If START admission already linearized (DISPATCHED + admission), RequestCancel does not retroactively supersede it; cancel-induced Run.version advance is settled through authority-aware admission retirement and current cancel authority, with Agent/LLM/Connector external effect=0. Both races are deterministic and restart-safe.
- `BLOCKED_BINDING` crash/live gap: crash after blocked CAS/before RequireRecovery, after RequireRecovery/before SUPERSEDED settlement, and **no process restart** runtime mismatch. Startup/live deterministic command `system:handoff-binding-recovery:<handoff_id>` enters matching Recovery exactly once unless a later cancel/terminal preemption already superseded the row.
- `CONSUMED_CONTINUATION_RECOVERY`: Approve/PREFLIGHT, Modify/REVIEW_ENTRY, Reauth saved target, Recovery RECHECK, Cancel/CANCEL_RESOLUTION, Confirmation owner entry. Test immediate crash and 1+/2+ descendant checkpoint crashes. Latest checkpoint must carry the same `active_handoff_id/run_sequence`; generic SAFE gate is not used; payload reinjection=0.
- Domain-progress fence tests split by linearization order. (A) Reauth/Recovery/Cancel/terminal commits before recovery/normal admission claim → claim fails and old continuation invocation=0. (B) admission claim commits first, then those Domain facts commit before settlement → admission checkpoint may be durable but settlement is `AUTHORITY_STALE_RETIRED`, stale NORMAL row is SUPERSEDED / recovery admission is cleared, old PREFLIGHT/Review/Verification owner I/O=0, and Application reconciliation chooses state-specific authority. (C) settlement commits first → later control is observed at the next Domain/workflow guard; new Claim/Write after cancel intent=0.

Operational artifact replay tests inject crash after side-effect success/before `store_result` for Backup, Restore, Diagnostic bundle, and Attachment staging. The reservation's stable `operation_ref` must reach the exact Port callable; `reconcile_*` recovers COMPLETED or proves SAFE_TO_RETRY without Application filesystem scanning, and UNCERTAIN forbids blind repetition.
- **Evidence exclusion identity/restart regression:** identical Provider source version/content normalized with the same chunk schema must regenerate the exact same deterministic `segment_id` across fresh Retrieval/cache restart; random UUID/retrieval-revision-scoped IDs fail. `EXCLUDE_EVIDENCE` must checkpoint `RetrievalState.exclusion_obligation_segment_ids` before one-shot handoff payload clear, survive crash/cache loss, and appear in finalized `RetrievalResultV1.excluded_segment_ids`. Provider content/version or chunk-schema change must issue a new segment ID and must not fuzzy-match/auto-exclude changed evidence.
- **Non-Domain reconcile surface completeness:** OAuth start/revoke, LLM credential store/delete, Settings update, Runtime Mode update, Backup/Restore, Diagnostics, Shutdown, Attachment staging must each call the exact 07 operation-specific reconcile callable on `RECOVER_RESERVED`; no handler may invent raw filesystem/keyring/process inspection. `SAFE_TO_RETRY` is required before retry.
- **RuntimeModePort authority:** `POST /runtime/mode` mutates only `RuntimeModePort` process-local state after Active Run guard and operational replay; Settings `preferred_llm_mode` and existing Run.requested_mode remain unchanged. Service restart + unresolved reservation is reconciled deterministically.
- **OAuth completion observation:** loopback callback code/state/token stay MCP-internal. UI completes onboarding/reauth by bounded `GET /connections/google/status` polling/refresh and observes `CONNECTING → CONNECTED|...`; no MCP→Application reverse completion event or FastAPI OAuth callback endpoint is required/allowed. Success navigation may return only to a validated exact `http://127.0.0.1:{app_port}/`; external host, user-info, missing port, non-root path, query, or fragment must fail closed, and the redirected app still reads connection truth through the status route.

### 10.2 Non-Domain operational crash replay gate

Backup/Restore/OAuth start/Credential/Settings/Runtime Mode/Diagnostics/Shutdown/Attachment staging each inject crash at: before side effect, during side effect, side effect success before completion journal, completion journal before HTTP response. Same command/hash must never blindly duplicate side effects; different hash conflicts. Restore uncertainty enters Safe Mode rather than blind restore; artifact-producing operations recover command-bound artifact/hash when present.

### 10.3 External LLM disclosure temporal gate

For `API_LLM` and `AUTO→API`: exact `ExternalLlmTransferScopeV1` hash must be stored in run-scoped CheckpointPort metadata and `EXTERNAL_LLM_SCOPE_PUBLISHED` appended before provider adapter invocation. Missing/stale scope or `external_llm_consent=false` means provider call count 0. Scope expansion after Retrieval/Route change requires a new published revision/hash. Browser ACK is not required and must not be treated as consent authority.

### 10.4 Retrieval cache-loss restart gate

Crash at page1→page2, detail fetch, normalize, evidence selection, sufficiency and Confirmation/Reauth suspend points. `GraphCheckpointEnvelopeV1.retrieval_cache_requirements` must contain only bounded handle/route/query identities and no raw token/content; Application checkpoint_blob deserialize count=0. Missing memory-only `read_result_handle` must cause `RETRIEVAL_CACHE_RESTART → RETRIEVAL_ENTRY`, raw provider token persistence 0, stale handle reuse 0, fresh provider reread/new Retrieval revision, and **no RunBudget counter reset**. Binding/contract mismatch still enters Recovery instead of restart. Canonical production path도 검증한다: `RunRetrievalCachePort → InMemoryRunRetrievalCache`, detector/producer=`run.reconcile_retrieval_cache_restart`, deterministic trigger duplicate handoff 0, LangGraph/Background adapter의 direct Repository mutation 0, terminal `discard_run` 후 handle resolve=missing.

## 11. Security

- Loopback only, Host·Origin·DNS Rebinding
- Bootstrap 1회·60초·재사용 차단
- Session restart invalidation
- Keyring Plain File Fallback 금지
- PATH Hijack·Shell Injection·Signature·Hash·Schema
- Prompt Injection·승인 이후 Argument 변경 차단
- Diagnostic Secret Leakage 0
- Holdout Gold·Prompt 튜닝 Trace 접근 분리

## 12. Installer·Upgrade

- User install, no admin, no Python·Node
- Production·distributed test Signature
- API_ONLY without Ollama
- LOCAL_CAPABLE clean VM automatic provisioning: compatible existing Ollama reuse 또는 signed Ollama 준비 → active single model download·digest verification → smoke test → READY; manual CLI·external install guidance 0
- Upgrade Backup·Migration·Safe Mode·Downgrade block
- Default uninstall preserves DB·Backup·Settings and deletes OAuth·LLM credentials

### 9-A. Local Runtime provisioning · tier routing

필수 regression:

- `API_ONLY`는 provisioning endpoint가 side effect 0의 unsupported result를 반환하고 Ollama/model artifact를 요구하지 않는다.
- `LOCAL_CAPABLE` clean Windows VM에서 사용자 CLI 없이 Ollama → active single model → Smoke Test → READY를 완료한다.
- compatible pre-existing Ollama는 보존·재사용하며 product uninstall/shutdown이 제거·강제 종료하지 않는다.
- incompatible pre-existing version, insufficient disk, network interruption, partial download, installer failure, signature/hash/digest mismatch를 fail-closed한다.
- same command/restart/crash에서 `OperationalCommandReplayPort`가 같은 operation을 reconcile하고 duplicate installer/model download를 만들지 않는다.
- Browser/Prompt/Connector Source supplied URL/path/model/tag/digest/shell fragment가 provisioning effect에 반영되지 않는다.
- Product LLM caller는 `StructuredInferenceRequestV2`의 exact `InferenceTierV1`을 보내고 Router만 `LocalModelProductDecisionV2.active_profile`을 resolve한다. Agent/Prompt/provider leaf에 concrete model branch/table이 있으면 실패다.
- unknown tier, missing/duplicate profile row, Product Decision↔Model Manifest hash mismatch, tier model digest mismatch, unapproved installed model, mixed V1/V2 artifact set은 inference 전 차단한다.
- repair/resume/revision이 model authority를 바꾸지 않고 actual inference class/profile/model이 Trace와 Result에 일치하며 같은 Run의 concrete model swap은 0이다.
- uninstall에서 pre-existing Ollama 보존, product model cleanup 명시 선택, user data/credential 기존 정책을 함께 검증한다.
- clean-VM/upgrade/uninstall Release Gate에서 Windows installer 본체에 Ollama executable/model weight가 포함되지 않았음을 검사한다.

## 13. Observability

- Correlation IDs
- Case·Fixture·User Prompt·Prompt·Model·Graph 연결
- `experiment_id`, `evaluation_item_id`, `candidate_config_hash`, `trial_index`
- `projection_version`, `upstream_mode`, `target_node_id`, `grader_version`
- Log Rotation·Terminal Run Trace=`configured retention_days`(default 30, P0 `1..30`)·Audit=90일 고정
- Audit append-only Repository
- Sanitization Canary Leak 0
- `ORACLE`·`LIVE`, Full·Partial 결과 혼합 금지

## 14. Evaluation Harness Regression

실험 Runner와 Dataset은 제품 품질 비교 전에 다음 회귀를 통과한다.

### Dataset·Projection

- Current Evaluation placement closure: checked-in Dataset/Gold는 `evaluation/datasets/{retrieval,agent,e2e}/**`, scoring contract는 `evaluation/scoring-contract-v1.1.json`, candidate metadata는 `evaluation/configs/**`, transient result는 gitignored `evaluation/results/**`에만 둔다. Top-level `experiments/`, live `evaluation/compat/`, internal Product target registry 생성/소비는 실패다.
- Current Micro Dataset은 13의 six dataset IDs를 retrieval/agent semantic category 아래 유지한다. Unknown extra dataset ID를 current release-evaluation input으로 자동 승격하면 실패다.
- Canonical Case → Node·Trajectory·E2E Projection 참조 무결성
- Required·Forbidden·Hard Negative 중복 0
- `scenario_family_id`·`fixture_relation_family` Split 누수 0
- Holdout Gold가 Prompt 튜닝 Artifact에 포함되지 않음
- Source 본문에 Evaluator Label·정답 유도 문구 없음

### Candidate Config

- 비교 후보 간 의도한 독립 변수 하나만 다름
- `candidate_config_hash` 재현 가능
- Dataset·Fixture·Tool·Policy Version 누락 시 실행 금지
- Budget·Stop Condition 없이 Runner 시작 금지

### Node·Handoff

- `ORACLE`은 Gold Upstream만 사용
- `LIVE`는 실제 Upstream Output만 사용
- 두 모드 결과를 같은 Metric 집계로 혼합하지 않음
- Target Node 외 LLM 호출이 있으면 Node 단독 Run 실패

### Trajectory·End-state Grader

- Required·Forbidden Tool과 Argument Constraint 검증
- 허용 경로가 여러 개인 READ는 Subset·Constraint 방식 사용
- 승인 → ClaimExecution COMMIT → ClaimContext → BeginExecutionAttempt COMMIT → Write → GET Verification의 Strict 순서를 검증
- Write 최종 상태를 Google Fixture End-state와 비교
- 텍스트 성공 선언만으로 Write 성공 처리 금지

### Scoring Contract

- `scoring-contract-v1.1.json` 존재·Version 고정
- Hard Gate 실패 Candidate가 aggregate PASS가 되지 않음
- Core·Stress·Holdout 분모를 분리
- Architecture Profile 비교에서 `six_reference_route`를 profile-neutral common BTS 조건으로 사용하지 않음
- 비용·Latency가 BTS 실패를 상쇄하지 않음

### Grader Calibration

- 결정적 판정 가능 항목에 LLM Judge 단독 사용 금지
- Human Sample과 LLM Judge 불일치 기록
- Dataset Issue와 Candidate Failure 분리
- Grader Version 변경 시 과거 결과와 직접 합산 금지

## 15. Coverage

```
Domain allowed·forbidden edges 100%
Policy·Forbidden Tool 100%
Approval·Execution·Verification branches 100%
Evaluation Reference Integrity 100%
Holdout Leakage 0
Deterministic Grader Contract 100%
Python line 80%, branch 75%
React statement 80%, branch 70%
Secret leakage 0
```

### 15.1 Synthetic Multi-Connector 제품형 E2E 계약

Final Product Validation과 Synthetic Multi-Connector 평가 설계는 `13 Evaluation`이 소유한다. 이 절은 해당 Harness가 현재 제품 안전·Connector boundary 계약을 위반하지 않는지만 검증한다.

- 서로 다른 `connector_id` 2개 이상이 Registry에 동시에 존재할 때 Connector/Tool 선택과 Route binding이 정확해야 한다.
- Synthetic Connector Lane은 MCP Transport/Server 경계 뒤에서만 동작하며 Core에 Provider Client 우회 Port를 추가하지 않는다.
- 같은 Resource/Effect를 제공하는 Tool이 여러 Connector에 있을 때 signed Registry eligibility → Tool Route → deterministic binding 순서를 검증한다.
- 한 Run에서 Connector A Read → Connector B Write, A+B Read → B Write 같은 cross-connector trajectory를 검증한다.
- 사용자 Confirmation과 Approval은 실제 Controller/Domain Command를 통과해야 하며 Simulator가 Approval Receipt·Claim Token을 직접 만들 수 없다.
- Approval 이전 Write 0, Decline/Cancel 이후 신규 Claim·Write 0, 승인 Arguments와 실제 dispatch Arguments 불일치 0을 검증한다.
- 실제 Write 성공은 Connector Verification Read와 최종 Fixture End-state로 확인한다. Assistant 최종 문장만으로 성공 처리하지 않는다.
- 특정 MCP 장애는 다른 Connector Provider로 direct fallback하는 이유가 아니다. 필요한 Route가 불가능하면 명시적 Partial/Confirmation/Recovery로 닫힌다.
- `UNKNOWN_RESULT` fault injection에서 blind resend 0, 기존 결과 Recovery 후 End-state가 Gold와 일치하는지 검증한다.
- Trajectory는 안전상 순서가 필수인 milestone과 순서가 자유로운 Read set을 분리해 채점할 수 있어야 한다.

두 번째 Connector를 실제 제품 지원 범위로 Release하려면 등록된 Connector 2개 이상의 product-style lane을 통과해야 한다. P0 Google-only Release의 Synthetic Harness 결과는 Connector-neutral Core 확장성 증거일 뿐 두 번째 Connector 제품 지원 완료를 뜻하지 않는다.

### 15.2 Evaluation Scoring·Grader Harness 계약

- Evaluation Result는 `main_experiment_id(A|B|C|D|E)`를 필수로 기록한다. `experiment_id`가 필요한 재현 Artifact는 compatibility-only trace alias로 격리하고 current scoring/decision key로 사용하지 않는다.
- Candidate별 분모를 사후 변경하지 않는다. `NOT_APPLICABLE`은 Gold가 실행 전에 명시한 경우만 제외하며, Dataset Defect 제외는 새 Dataset Version에 동일하게 반영한다.
- Safety/Integrity와 Business Outcome을 같은 Grader 결과로 합치지 않는다. Safety·Approval·Claim·UNKNOWN_RESULT·금지 Side Effect는 Hard Gate, 기대 업무 End-state는 Outcome으로 별도 채점한다.
- Tool Trajectory는 `STRICT | SET | SUBSET | CONSTRAINT_ENVELOPE` 비교 모드를 지원해야 하며, 순서가 안전·업무 의존성에 필요한 구간만 STRICT로 강제한다.
- Semantic Grader는 `SUPPORTING_ONLY`다. 결정적 Safety·Route/Tool·Interaction·End-state 실패를 뒤집을 수 없고 Candidate 선택에 쓰기 전 Human-reviewed calibration sample을 통과해야 한다.
- current `E2EProjectionV5`와 applicable `ProductEpisodeE2EProjectionV1`은 End-state Grader가 필요한 Case에 구조화 `end_state_gold`를 제공해야 한다. required Gold가 없으면 해당 End-state 판정을 fail closed하고, 숨은 Canonical 파일이나 Planning Arguments에서 정답을 추론하지 않는다.
- Finalist 반복성은 모든 Case·Candidate를 무차별 반복하지 않고 사전 등록한 reliability subset에서 기본 `consistent_success@3`를 사용한다.

### 15.3 Design Freeze deterministic boundary regression

- Approval 전 chain은 `Schema validation → Policy validation → Review freshness → Domain guard` 순서이며 각 경계의 failure가 다음 stage로 fall-through하지 않아야 한다. LLM output이 Policy/Domain guard를 우회하면 실패다.
- `ClaimExecution` commit → `build_claim_context` 뒤에도 Connector Write는 0이며, `BeginExecutionAttempt` commit으로 Attempt가 `EXECUTING`이 된 뒤에만 dispatch한다. MCP는 실제 args를 재해시해 claim mismatch를 외부 호출 전에 차단해야 한다.
- `RequestCancel` APPLIED 시 Run은 `CANCEL_REQUESTED`; cancel 중 Verification/Recovery/Reauth round-trip 후에도 durable cancel intent와 신규 Claim·Write 0이 유지되어야 한다.
- Action/Approval/Attempt coupled status mutation은 State Transition Test Matrix와 완전히 일치해야 하며 partial aggregate write는 UoW rollback이다.
- 필수 Audit event는 lifecycle mutation/Receipt와 같은 UoW에 exactly-once append되고 command replay에서 중복 생성되지 않아야 한다.
- repository build-order gate는 migration implementation/schema setup이 concrete SQLite repository integration보다 먼저 준비되는지 검사한다. downstream API/Graph가 undefined schema/Port를 placeholder로 만드는 것은 실패다.

## 16. Release Block

미승인 Write, 금지 Tool, Hash 변경, Verification 누락, 중복 Write, UNKNOWN_RESULT 재실행, FAILED 직접 실행, READ 승인 Row, Retrieval LLM 직접 MCP 호출, 허용 IN Route 밖 결정적 Read Tool 호출, Open Run 중복, Secret Leak, Public Bind, Signature·Migration·Backup 실패, Chrome·Edge 실패, API_ONLY Ollama 의존 중 하나라도 있으면 차단한다.

Experiment Runner는 Dataset·Projection 참조 오류, Holdout 누수, 의도 외 Config Diff, Grader Version 누락, Budget 미설정 중 하나라도 있으면 실험 결과 생성을 차단한다.

Current Prompt Runtime Gate:

- Product Prompt assembler는 Slot별 `prompt-runtime-input-contract-v1` allowlist 밖 Root Field를 직렬화하면 실패한다.
- `end_state_gold`, `decision_script`, `fault_script`, `six_reference_route`, Grader/score/holdout metadata 등 Evaluation 전용 Field가 Product Prompt payload에 나타나면 실패한다.
- **current 06/15 required PromptRef set = production runtime caller set = manifest set = source set = assembled set = input-contract set** 이어야 하며 missing/extra=0을 검증한다. Numeric slot count나 non-current candidate identity를 release gate로 사용하지 않는다.
- Repair/Revision Input은 `base_projection + candidate_output + normalized failure_record`만 허용하며 `affected_fields + allowed_change_scope` 밖 변경은 실패다.
- Provider 이름을 Product Prompt 책임 계약에 하드코딩하지 않는다. Connector/Tool 고유명은 Runtime 입력 Tool Schema/Registry Projection에서만 전달한다.
- Holdout Case는 Prompt authoring·DEV tuning에 사용하지 않는다.

## 17. 필수 회귀 ID

| Test ID | 계약 |
| --- | --- |
| `TST-DB-101` | Command Receipt와 Domain 변경 원자 Commit |
| `TST-API-101` | 같은 Command ID·같은 Hash 기존 결과 반환 |
| `TST-API-102` | 같은 Command ID·다른 Hash 409 차단 |
| `TST-SEC-101` | Bootstrap Endpoint는 기존 Session 없이 Secret으로만 성공 |
| `TST-SEC-102` | 일반 API는 Local Session 없이 차단 |
| `TST-SEC-103` | OAuth Token 원문 FastAPI·Log·DB 미노출 |
| `TST-MCP-101` | 유효 Claim Token + same-Attempt `BeginExecutionAttempt(applied=true)`일 때만 Write 허용 |
| `TST-MCP-102` | Claim Token 재사용·만료·Binding 불일치 차단 |
| `TST-WF-101` | Agent Node의 MCP 직접 호출 0회 |
| `TST-WF-102` | Node Registry 외 Edge 차단 |
| `TST-E2E-101` | Run 응답 유실·Service 재시작·재전송 시 Run 1개 |
| `TST-E2E-102` | 부분 Action 성공 후 취소: Run CANCELLED·result_kind PARTIAL |
| `TST-EVAL-101` | Case 1:N User Prompt와 Evaluation Item 연결 |
| `TST-EVAL-102` | Canonical Case와 모든 Projection Reference 무결성 |
| `TST-EVAL-103` | 후보 간 의도한 독립 변수 외 Config Diff 0 |
| `TST-EVAL-104` | `ORACLE`·`LIVE` Upstream 입력 모드 분리 |
| `TST-EVAL-105` | Required·Forbidden Read Tool Trajectory 판정 |
| `TST-EVAL-106` | Write 승인·ClaimExecution·BeginExecutionAttempt·GET·End-state Strict 판정 |
| `TST-EVAL-107` | Grader Version·Human Calibration·Dataset Issue 분리 |
| `TST-EVAL-108` | Scenario Family·Fixture Relation Family Holdout 누수 0 |

## 18. Agent Capability·Retry 회귀

이 절은 §8의 **current budget/profile 숫자를 재정의하지 않고**, 동일한 ceiling을 Failure/Retry 관점에서 검증한다. Budget value의 Test contract는 §8이 단일 current 위치이며, 15 Prompt·Failure와 06 Workflow의 current contract를 검증한다.

### 18.1 필수 회귀

- 동일 실패 Signature에 Semantic Revision을 두 번 호출하지 않는다.
- Schema Repair가 Goal·Evidence·Action 의미를 변경하면 실패다.
- 비재시도 오류에 LLM Prompt를 호출하지 않는다.
- `AUTH_REQUIRED`를 Retrieval Revision이나 Tool Route 재판단으로 해결하려 하지 않는다.
- 429·5xx·Timeout을 LLM 재시도로 처리하지 않는다.
- `UNKNOWN_RESULT`에서 Write Tool을 재호출하지 않는다.
- Verification `MISMATCH`에서 자동 수정·Rollback하지 않는다.
- `AGENT_SEARCH`의 저신뢰 후보를 자동 확정하지 않는다.
- 사용자 날짜·사람·이메일 제약이 Query에서 누락되면 실패다.
- 실패 후 Query·Page 상태가 모두 같은 `SEARCH`를 반복하면 실패다.
- 같은 Query와 새로운 Page Token의 `NEXT_PAGE`는 정상으로 인정한다.
- Node DEV와 Node HOLDOUT의 Failure·Scenario·Fixture Family가 겹치면 실패다.
- Prompt Manifest가 `RUNTIME_ACTIVE`가 아닌 Prompt를 제품 Runtime이 선택하면 실패다.

### 18.2 Node Dataset Gate

모든 적용 가능한 Failure Reason은 최소 `DEV 3 + HOLDOUT 1` Item을 가진다. `ORACLE`, `LIVE`, `MUTATED` 결과는 같은 집계로 합치지 않는다.

Gate는 고정 Sampling 조건에서 Item당 1회 평가한다. Temperature는 Gate Configuration에서 명시적으로 고정하고, Seed는 Provider가 지원함이 확인된 경우에만 고정한다. 이는 완전한 bit-identical Determinism을 보장하지 않는 best-effort 재현성이며, 반복 Trial 기반 Threshold PASS로 대체하지 않는다. 반복 Trial 평균·분산·Bootstrap Confidence Interval·Trial Consistency 평가는 `13` Evaluation 소관이다.

## 19. 정합성 회귀 Gate

- Google/MCP/LLM Stub 호출 순간 SQLite Write Transaction이 열려 있지 않아야 한다.
- 외부 호출 전후 두 Transaction 사이 Version 변경 시 결과 저장을 차단한다.
- Recovery는 `RequireRecovery`·`ResolveRecovery` 외 직접 상태 변경 0건이어야 한다.
- SEND: Approval Hash 일치 + Sent Lookup + UNKNOWN_RESULT 자동 재전송 0.
- DELETE: 정확한 Google Task와 Calendar Event만 승인형 `DELETE`로 허용하고 각각 `GET_ABSENT`를 확인한다. Gmail Message/Thread raw delete와 반복 Event 전체 일괄 delete는 금지한다.
- Task 완료·Calendar 참석자 변경: 정확한 Target과 승인된 UPDATE.
- Gmail 원문 삭제·반복 Event 전체 일괄 수정: Tool 제안/실행 0.
- Google Task DELETE: 정확한 Task Target → 승인 → ClaimExecution → Claim V2 → BeginExecutionAttempt COMMIT → `tasks_delete_task` → `GET_ABSENT` Verification. 승인/Claim/BeginExecutionAttempt/검증 우회 0.
- `ConfirmationRequiredV1(question, options)` 기반 clarification: 후보·차이·선택지를 bounded question/options로 제시하고 same-owner checkpoint resume를 검증한다.
- 문맥으로 해결된 요청과 `답장해줘` SEND 의도에 불필요 Clarification 0.
- 전체 Mailbox/무제한 Workspace 조회는 API 호출 전에 BLOCK.
- Calendar overlap 자체를 conflict로 오판하지 않는다.

## 20. Agent Subgraph 회귀 테스트

- `SIX_ROLE_BASELINE`의 Role은 Request Understanding / Tool Route / Retrieval / Work Analysis / Planning / Review다.
- Tool Route Subgraph가 `ToolRoutePlanV2`를 Parent에 반환한 뒤 Retrieval은 `input_plan`, Planning은 `output_plan`을 read-only로 소비한다.
- Retrieval Subgraph는 `input_routes` 안에서 Query→결정적 Read→Normalize/Segment→Run-scoped RAG→Evidence→Sufficiency를 완료한 뒤 공식 `RetrievalResultV1`과 필요한 Typed `WorkflowSignalV1`만 반환한다.
- Retrieval의 Query candidate·Page Token·RAG score·repair candidate를 Main State에 승격하지 않는다.
- Planning은 `output_routes[].selected_tool_id`와 해당 Tool Schema만 사용해 Arguments를 작성하고 Tool을 다시 선택하지 않는다.
- upstream State revision 시 의존 downstream State가 stale 처리되고 재생성되는지 검증한다.
- `SINGLE_BASELINE`은 Planning 결과에 대해 같은 Unified Agent 내부 self-review 책임을 수행한다.
- controlled post-retrieval decomposition diagnostic은 `13 Evaluation`이 등록한 bounded context snapshot 이후만 실행하며 추가 Google Read 호출 수가 0이어야 한다.
- diagnostic topology/candidate identity는 `13 Evaluation`이 소유하며 12가 별도 candidate enum을 정의하지 않는다.

| Test ID | 검증 | 기대 |
| --- | --- | --- |
| `TST-AGT-201` | SINGLE Profile topology | Agent Subgraph 1개 |
| `TST-AGT-202` | THREE Profile topology | 서로 다른 책임 계약의 Agent Subgraph 3개 |
| `TST-AGT-203` | SIX Profile topology | 전문 Agent Subgraph 6개 |
| `TST-AGT-204` | Agent Local State isolation | invocation 종료 후 다음 호출에 임시 candidate/repair state 자동 승계 0 |
| `TST-AGT-205` | Parent/Child state projection | 허용 필드만 입력·Typed Result만 반환 |
| `TST-AGT-206` | bounded repair loop | Schema Repair 최대 1, Semantic Revision 계약 상한 준수 |
| `TST-AGT-207` | direct agent call prohibition | Agent→Agent 직접 Edge 0 |
| `TST-AGT-208` | write boundary | Agent Subgraph의 Connector MCP Write 직접 호출 0 |
| `TST-AGT-209` | checkpoint authority | Local Checkpoint로 Approval/Execution 사실 확정 불가 |
| `TST-EVAL-210` | controlled decomposition replay boundary | 동일 registered evaluation snapshot을 comparison variants에 주입하고 추가 Google Read 0 |
| `TST-AGT-211` | Prompt Slot Key | `failure_reason_code`가 Runtime Slot Key에 포함되지 않고 Failure Block assembly metadata로만 사용 |
| `TST-EVAL-212` | Semantic parity | architecture comparison 후보의 `prompt_semantic_bundle_version`과 책임 coverage 일치 |
| `TST-EVAL-213` | Environment lock | 비교 후보의 `evaluation_environment_hash`가 의도한 독립변수 외 조건에서 동일 |
| `TST-HANDOFF-214` | Handoff fidelity | Required Field·Evidence ID·Constraint 보존 및 contradiction introduction 측정 |

### 20.1 LangGraph 구조 회귀 ID

| Test ID | 검증 | 기대 |
| --- | --- | --- |
| `TST-AGT-215` | Tool Route authority | `ToolRoutePlanV2` 생성 이후 downstream Tool 재선택·임의 변경 0 |
| `TST-AGT-216` | IN/OUT separation | Retrieval은 IN Route만, Planning은 OUT Route만 소비 |
| `TST-AGT-217` | Node projection minimization | Node 선언 입력 외 State 필드 전달 0 |
| `TST-AGT-218` | Local/Main boundary | Query candidate·Page Token·RAG score·LLM candidate의 Main State 승격 0 |
| `TST-AGT-219` | Upstream revision invalidation | Route/Retrieval/Analysis revision 시 downstream stale State 재사용 0 |
| `TST-RET-220` | Run-scoped RAG | Fetch 결과 전체를 Evidence 선정 없이 Analysis/Planning에 전달 0 |
| `TST-AGT-221` | RunInput authority | `entry_mode`·`user_request`·`selected_resource_refs` downstream 임의 변경 0 |
| `TST-AGT-222` | Artifact/Signal separation | 미완결 confirmation·route reconsideration candidate의 공식 Artifact 저장 0 |
| `TST-AGT-223` | Request revision invalidation | RequestIntent revision 변경 시 Route 이하 stale State 재사용 0 |
| `TST-AGT-224` | Tool Route internal responsibility | Resource·Effect 판단과 Registry binding 분리, unregistered Tool 생성 0 |
| `TST-AGT-225` | Analysis conditional routing | `analysis_requirement=NONE` Answer의 불필요 Analysis 0, 단순 ACTION의 허용된 Analysis skip 성공, `analysis_requirement=REQUIRED` 또는 Task CREATE/Calendar CREATE Policy precondition의 Analysis 우회 0 |
| `TST-AGT-226` | Review discriminated union | `PASS+confirmation`, `CONFIRM` without confirmation, `BLOCK` without blockers 표현 가능 상태 0 |

### 20.2 LangGraph State·Edge 회귀

다음 계약은 Release Graph 구현 시 반드시 회귀 검증한다.

- **공식 Edge 폐쇄성:** Request / Tool Route / Retrieval / Work Analysis / Planning / Review의 모든 공식 disposition은 정확히 하나의 Edge·Interrupt·Terminal 경로를 가진다. Tool Route에는 공식 disposition에 없는 self-edge를 만들지 않는다.
- **추가 Retrieval 진입:** `WorkAnalysis.NEEDS_MORE_DATA` 또는 `Review.RETRIEVE_MORE`는 현재 `InputRoutePlanV1`에 usable route가 있을 때만 `RetrievalRequiredV1`을 가지고 Retrieval로 이동한다. 현재 route로 해결할 수 없거나 새 Route가 필요하면 owner-local finalizer가 각각 `ROUTE_RECONSIDERATION_REQUIRED` / `ROUTE_RECONSIDERATION`과 `RouteReconsiderationRequiredV1`로 정규화해 Tool Route로 back-edge해야 한다. 빈 IN Route로 Retrieval을 시작하거나 `RetrievalRequiredV1`을 Tool Route signal처럼 사용하면 실패다.
- **Retrieval 반복 방지:** back-edge의 `RetrievalRequiredV1.needs`는 1개 이상이어야 하며, 추가 Retrieval은 이전 시도와 동일한 Query/범위를 이유 없이 반복하지 않는다.
- **READ 단일 책임:** Release Graph의 Google READ는 `InputRoutePlanV1 → Retrieval`만 수행한다. `OutputPlanV1` Action Route에 `READ`가 들어가면 Contract 실패다. Domain READ Action 호환 계약과 Release Planning 출력을 혼동하지 않는다.
- **Main State Owner 단일성:** RequestIntent / InputRoutePlan / OutputPlan / RetrievalResult / WorkAnalysisResult / PlanningResult / PlanReviewResult는 각각 선언된 Owner만 새 revision을 생성한다.
- **Patch merge:** Subgraph 반환은 owner field와 허용된 workflow signal만 갱신한다. Local State의 `None`·누락 필드 때문에 다른 Main State Artifact가 초기화·삭제되지 않는다.
- **Upstream read-only:** downstream Subgraph가 upstream Artifact를 다시 생성·덮어쓰지 않는다. 재판단은 해당 Owner로 Back-edge하고 새 revision을 만든다.
- **Tool 재선택 금지:** Planning LLM 출력에는 Tool 선택 필드를 두지 않고, Action의 Tool identity는 `OutputToolRouteV1.selected_tool_id`에서 결정적 Assembler가 복사한다.
- **Route 후보 보존:** signed registry의 Resource·Effect·Schema 적합성에 따른 eligibility filtering만 허용한다. 모델 부담을 이유로 heuristic shortlist가 eligible Tool을 임의 제거하면 실패다.
- **Graph/Domain 권위 분리:** `workflow_phase`는 checkpoint/routing 위치이고 Domain `Run.status`는 제품 상태 권위다. Reauth·Cancel·Recovery·Approval·Execution·Verification에서 두 값이 다를 수 있으며 복구 시 Domain 상태를 우선한다.
- **Freshness:** upstream revision 변경 후 `meta.based_on`이 현재 active revision과 맞지 않는 downstream Artifact를 non-null이라는 이유만으로 재사용하지 않는다.

## 21. Runtime E2E Canonical Contract 회귀

### 21.1 Cancel

- Version conflict 또는 같은 `command_id`의 다른 Hash에서는 Approval·Plan·Action 변경 0.
- 취소 수락 후 신규 Claim·Connector Write 0.
- 미실행 `PROPOSED | MODIFIED | APPROVED | EXPIRED` Action은 `CANCELLED`; ACTIVE Approval은 REVOKED; 새 Attempt·Verification 0.
- `EXECUTING` 취소는 결과 확정 전 상태를 덮어쓰지 않는다.
- `UNKNOWN_RESULT` 취소는 Run `RECOVERY_REQUIRED`; blind resend 0.
- 일부 Write 성공 후 취소는 Run `CANCELLED`, result_kind `PARTIAL`, rollback 0.

### 21.2 Runtime API Trust Boundary

- 같은 `command_id + canonical request hash` replay는 기존 결과 반환.
- 같은 `command_id + 다른 canonical hash`는 `409`, Domain mutation 0.
- Browser 제공 `request_hash`, `approval_id`, idempotency key, source snapshot, actor identity를 authority로 사용하지 않음.
- confirm/cancel/resume/prepare-retry/resolve-recovery의 Versioned Request Schema와 state precondition Contract Test.
- **Settings schema equality:** 10 §10.3 logical field set == 07 `SettingsPatchV1/SettingsViewV1` exact field set이어야 한다. timezone/working-day/weekend/calendar-buffer가 UI에는 있는데 wire에서 사라지거나 unknown key를 silently ignore하면 실패다. P0 `retention_days`는 `1, 30` accept / `<=0, >=31` reject이고, Conversation·Message·terminal Run subtree(**Trace 포함**)/owning Checkpoint에 적용되며 Audit 90일·Secret·Session Cache에는 적용되지 않아야 한다. `preferred_llm_mode`와 `/api/v1/runtime/mode`를 같은 persistence authority로 합치거나 undocumented `/runtime/mode` alias가 생기면 실패다. P0 Settings UI/API에 log-delete/full-app-reset Command가 생기면 실패다.
- arbitrary resume payload 차단.

### 21.3 Insufficient Data Guard

- required safety/POLICY issue → `BLOCKED`.
- required USER issue → `NEEDS_CONFIRMATION`.
- required GOOGLE issue + budget → `NEEDS_MORE_DATA`/`RETRIEVE_MORE`.
- budget exhausted + evidence-supported read-only → `PARTIAL`.
- Write 필수 Target/Argument/Evidence 부족은 PARTIAL로 우회하지 않음.
- SINGLE/THREE/SIX 동일 fixture에서 동일 semantic route 판정.

### 21.4 MISMATCH Recovery

- `StoreVerification(...MISMATCH)`는 Action/Verification만 먼저 commit하고, 별도 `RequireRecovery(VERIFICATION_MISMATCH)`가 Run을 `RECOVERY_REQUIRED`로 전이해야 한다. 두 operation을 한 숨은 mutation으로 합치면 실패하며 기존 Verification은 append-only다.
- `ACCEPT_PARTIAL`은 추가 Write 0, 미실행 Action `CANCELLED`, Run `COMPLETED` + result_kind `PARTIAL`.
- `CREATE_CORRECTIVE_PLAN`은 Run `PLANNING`, 새 Plan Revision, 기존 MISMATCH Action·Approval·Attempt 재사용 0.
- **Context Preview / Adjustment P0 boundary:** `GET /api/v1/runs/{run_id}`의 `ContextPreviewResponseV1` item/count/retrieval_revision은 current selected Evidence/ResourceRef와 exact하게 일치해야 한다. `retrieval_revision`은 `CheckpointPort.load_retrieval_head → RetrievalHeadV1`에서 읽고 opaque checkpoint deserialization/Plan revision 대체는 0이다. `adjustment_allowed=true`는 `WAITING_APPROVAL + current Action 전부 PROPOSED|MODIFIED + ACTIVE Approval 0 + in-flight/unknown/unverified execution 0`에서만 가능하다. `EXCLUDE_EVIDENCE`는 current Preview segment만 허용하고, `RETRIEVE_MORE`는 bounded `RetrievalNeedV1(reason_codes=[USER_CONTEXT_ADJUSTMENT])`로 projection된다. 수락 시 `BeginPlanning(USER_CONTEXT_ADJUSTMENT)` → current Plan `SUPERSEDED` → Retrieval new revision → stale-by-`meta.based_on` Analysis/Plan/Review 재계산을 검증한다. 승인/실행 이후 조정, Browser-local Evidence mutation, DB 직접 수정, stale expected_retrieval_revision 적용은 실패다.
- **RETRIEVE_MORE crash durability:** accepted Context Adjustment control patch는 payload clear 전에 `RetrievalState.pending_user_retrieval_need`를 checkpoint-commit한다. patch commit→handoff CONSUMED→`plan_query` 전 crash, cache-loss restart, Confirmation/Reauth suspend, Route reconsideration을 각각 주입해 동일 need가 보존되는지 검증한다. 새 `RetrievalResultV1` finalize checkpoint에서만 field가 clear되며 finalize 전 loss/후 duplicate replay는 각각 0이다.
- **Run Retrieval Cache resolve enum:** `FOUND|EXHAUSTED`는 valid resume dependency, `MISSING|CROSS_RUN|BINDING_MISMATCH`만 restart. `EXHAUSTED`에서 `NEXT_PAGE` Provider call=0, `RETRIEVAL_CACHE_RESTART`=0, bounded cached read result 사용은 허용한다.
- **Error action projection:** Browser는 `ErrorUiProjectionV1.actions`만 렌더링한다. `FAILED + NOT_SENT`가 아닌 상태에서 `PREPARE_RETRY`가 나오거나, `UNKNOWN_RESULT`에서 retry/write attempt가 생성되거나, State Contract가 금지한 status에서 `RESUME_SAFE_CHECKPOINT`가 나오면 실패다. `OPEN_SETTINGS/OPEN_DIAGNOSTICS`는 navigation-only여야 한다.
- Verification MISMATCH UI/API projection은 persisted `RecoveryContextV1` + State Contract matrix에서 생성한 `RecoveryUiProjectionV1.allowed_resolution_kinds`만 표시한다. `현재 결과 유지 → ACCEPT_PARTIAL`, `수정 제안 만들기 → CREATE_CORRECTIVE_PLAN`은 해당 kind가 allowed set에 있을 때만 `/resolve-recovery`로 전송하며, Browser-local reason mapping/no-op dismiss로 Recovery를 해소하면 실패다. `Google에서 열기`는 navigation only이며 Domain mutation 0이다.
- 교정 Write는 새 Approval → ClaimExecution → ClaimContext → BeginExecutionAttempt COMMIT → external Write → Verification 필요.

### 21.5 Post-Begin process-loss reconciliation

- Startup order exact: SQLite/migration/checkpoint → MCP Tool/Schema READY → configured LLM Adapter READY → `ReconcileInflightExecutionsHandler` bounded drain → initial `RedriveWorkflowHandoffsHandler` drain → live `WorkflowHandoffReconciliationLoop` start → READY. MCP/LLM readiness 전 Connector lookup/worker submit = 0.
- `ReconcileInflightExecutionsCommand(limit)`은 state-changing batch Command다. Handler가 `ExecutionAttemptRepository.list_reconciliation_candidates(limit)`를 직접 소유하고 `api/app.py`가 Repository를 enumerate하는 호출은 0. live WorkflowHandoff loop에서 이 Handler 호출도 0.
- `BeginExecutionAttempt` APPLIED commit 직후 Connector callable 진입 전 process crash → restart에서 original Write replay 0, `POST_BEGIN_ORPHAN` → deterministic `MarkUnknownResult(MAY_HAVE_BEEN_SENT)` exactly once.
- Connector callable 진입 중 process crash → 동일 reconciliation path; NOT_SENT 추정 0.
- `MarkUnknownResult` COMMIT 뒤 lookup 전 crash → 다음 startup에서 `UNKNOWN_RESULT_UNRESOLVED` candidate로 lookup을 재개하며 duplicate MarkUnknownResult 0.
- provider success/existing mutation 발견 후 `RecoverExistingResult` COMMIT 뒤 Verification 진입 전 crash → 다음 startup에서 `EXECUTED_AWAITING_VERIFICATION` candidate가 `BeginVerification | ResolveRecovery(RECHECK)`를 state guard에 맞게 apply/replay하고 deterministic `system:execution-attempt-reconcile:<attempt_id>:verification` handoff를 stage/reuse한다.
- lookup 결정적 미발견은 deterministic `ResolveAsFailed`. commit 뒤 crash 시 cancel intent 또는 다른 approved/executable Action의 자동 진행이 필요하면 `FAILED_AWAITING_CONTINUATION`이 `...:post-failed` handoff를 stage/reuse하고, stable retry/user-decision wait이면 background continuation 0. 불명확은 `RequireRecovery(UNKNOWN_RESULT)`; matching `RECOVERY_REQUIRED`가 durable해진 뒤 automatic lookup 반복 0.
- repeated startup에서 duplicate Domain mutation/Verification handoff 0, original Connector Write 0, bounded batch는 `has_more=false` 또는 no-progress까지 drain한다.

### 21.6 Delivery Certainty Failure Injection

- validation/preflight/dispatch 전 확정 실패 → `NOT_SENT`; FAILED 가능.
- dispatch 이후 Timeout → `MAY_HAVE_BEEN_SENT`; `UNKNOWN_RESULT`.
- 5xx에서 미전달 보장 없음 → `UNKNOWN_RESULT`.
- response loss → `SENT_RESPONSE_LOST`; `UNKNOWN_RESULT`.
- MCP process exit에서 dispatch 여부 불명 → `UNKNOWN_RESULT`.
- 모든 UNKNOWN_RESULT case에서 새 Attempt·blind resend 0.

## 22. Frontend Main UI 회귀 계약

Conversation UI 추가 회귀:

- `GET /api/v1/resources/tasks/{resource_id}`와 `/calendar/{resource_id}`는 current Row `selection_handle`을 검증하고 각각 `tasks_get_task`/`calendar_get_event`를 통해 Viewer required detail을 반환해야 한다. Task notes 및 Calendar attendees/description이 list-only projection 때문에 사라지면 실패다. React→MCP direct call은 0이며 detail Query가 Agent Evidence를 자동 생성하면 실패다.
- `GET /api/v1/conversations/{conversation_id}/history`는 Message 최신 최대 configured replay/query bound·Run 최대 configured replay/query bound를 bounded query로 반환하고 Message 초과 시 `truncated=true`여야 한다. unknown Conversation은 404다.
- History 응답은 저장된 Message와 Run을 Timeline 순서로 복원하되 API Query 자체가 Domain State·LangGraph Checkpoint를 변경하면 실패다.
- Frontend는 History fetch와 `POST /api/v1/runs`를 분리하며 StartRun Wire Payload가 `command_id, conversation_id, request_text, entry_mode, selected_resource_handles, requested_mode`만 포함하는지 검증한다. `run_id`, `user_message_id`, `workflow_key`, `langgraph_thread_id`, History Message 배열이나 previous-run Artifact를 함께 전송하면 실패다.
- 같은 Conversation의 과거 Message/날짜 그룹은 Timeline에 그대로 표시되지만 새 USER 요청 전송 Payload에 과거 Message 전체를 자동 포함하지 않는다.
- Terminal Run 뒤 새 요청을 보내도 `Conversation.title`은 최초 생성 제목을 유지하고 `Conversation.updated_at_ms`만 최신 활동 시각으로 갱신한다.
- 저장된 `created_at_ms` 기준 USER Message 시간과 Date Separator가 유지되며 오래된 Conversation에 새 Run이 추가되면 새 활동 날짜 그룹만 추가된다.
- Conversation 선택 시 Open Run이 있으면 그 Run의 checkpoint resume UI를 제공할 수 있지만, Open Run이 없으면 과거 Terminal Run checkpoint를 새 요청에 연결하지 않는다.
- Composer 1줄 시작·autosize·최대 높이 내부 scroll·동일 행 전송 Button·Center 하단 고정 계약과 Resource Detail compact/expand 계약을 유지한다.

이 절의 테스트는 `01-A 기능 정의서`와 `02 UI·UX 설계서`의 current Frontend 계약을 추적한다. Safety, Verification Diff, `UNKNOWN_RESULT`, Recovery, Chrome/Edge, Sanitization의 기존 회귀 계약도 같은 current owner 의미를 계속 검증한다.

| Test ID | 계층 | 검증 계약 |
| --- | --- | --- |
| `TST-UI-201` | Component | Header는 제품명·정중앙의 비대화형 Google 연결 chip·현재 계정·Settings를 표시하고 개발 Runtime/Node/Profile 문자열을 Main에 노출하지 않는다. |
| `TST-UI-202` | Component | Desktop 3 panel: Left Resource, Center Viewer+Chat, Right Conversation+Recent Execution의 정보 구조와 collapse 순서를 검증한다. |
| `TST-UI-203` | Component | Gmail/Tasks/Calendar 탭, 검색/필터, compact resource row, selected/hover/focus/disabled, 긴 문자열 ellipsis와 keyboard navigation을 검증한다. |
| `TST-UI-204` | Integration | configured `SIDEBAR_PAGE_SIZE`와 configured `RETRIEVAL_PAGE_SIZE`의 독립 계약을 검증한다. Gmail은 intermediate token-only traversal과 visible target metadata hydration, 이미 hydrate한 page 재방문 Provider 호출 0을 검증한다. Tasks는 Provider metadata batch를 configured `SIDEBAR_PAGE_SIZE`로 slice하고 continuation이 있으면 현재 materialized batch에서 계산되는 page 범위만 노출하며 알려진 마지막 page에서만 다음 batch를 append한다. Local API continuation을 UI page number나 Provider token으로 해석하지 않고 조건 변경·수동 Refresh에서 cache를 무효화한다. Calendar Month View는 visible grid terminal materialization을 사용하고 numeric pagination을 생성하지 않는다. |
| `TST-UI-205` | Integration | Gmail은 기본 `INBOX + PRIMARY` scope에서 `GET /api/v1/resources/gmail/count`의 exact count만 badge로 표시하고 추정값을 exact로 표시하지 않는다. Tasks는 incomplete browse의 terminal/continuation 상태에 따라 알려진 count를 표시하고 terminal materialization 뒤 exact total을 확정한다. Calendar tab에는 numeric badge가 없고 startup·Calendar refresh에서 별도 Calendar Count Read를 호출하지 않는다. Frontend count 생성을 위한 임의 전체 Page 순회·hard code가 없음을 검증한다. |
| `TST-UI-206` | Integration | Resource row click은 Focus Viewer만 갱신하고 checkbox는 다중 선택 Context 집합만 변경함을 검증한다. 선택 집합이 있으면 Composer Context Summary에 사용자 의미 label과 선택 수를 표시하고, 중복 없는 authenticated `selection_handle` 전체로 `RESOURCE_SELECTED`가 current identity resolve 후 최신 상세 조회를 시작함을 검증한다. 선택 집합이 없으면 `AGENT_SEARCH`를 검증한다. |
| `TST-UI-207` | Integration | 선택 없는 자연어 요청은 `AGENT_SEARCH`, Quick Action은 Agent 요청이며 Connector Write를 직접 호출하지 않음을 검증한다. |
| `TST-UI-208` | Component | Viewer와 Approval detail은 실제 REST/SSE Projection의 필드만 표시하며 fake count/detail/approval data가 없음을 검증한다. |
| `TST-UI-209` | Component | Inline Approval의 approve/modify/reject, detail expand, pending/submitting/completed 상태와 duplicate click 방지를 검증한다. |
| `TST-UI-210` | Integration | Conversation 새로 만들기·검색·선택 시 Center 복원과 Recent Execution의 Projection 조건부 표시/Empty State를 검증한다. |
| `TST-UI-211` | Component | Loading/Empty/Error, keyboard, focus, disabled, 반응형 Right→Left collapse, Chat Input과 Approval 접근성을 검증한다. |
| `TST-UI-212` | Integration | refresh, SSE disconnect/reconnect, cursor/snapshot 복구가 Domain 실패 또는 Write 재실행으로 오인되지 않음을 검증한다. |
| `TST-UI-213` | Regression | Browser P0에서 native Window Control을 기능으로 호출하지 않고 Settings/Diagnostics와 기존 사용자 설정을 보존함을 검증한다. |

### Calendar·Tasks·Viewer 회귀

- Calendar UI regression은 `TST-UI-204`의 selected-month Month View visible-grid contract와 Event 시간/All-day 표시를 검증한다. `time_min/time_max` 생략 시 90일 default는 Sidebar와 분리된 generic Upcoming Browse API case에서만 검증한다.
- Tasks Sidebar는 기본 Query가 미완료 Task 전체를 대상으로 하고 완료 Task는 기본 count/list에서 제외됨을 검증한다.
- 같은 날 시간 Event에는 연도·월·일·요일·시작/종료 시간이 있고 `시작`·`종료` label은 없으며, All-day Event에는 연도·월·일·요일과 `하루 종일`이 있다.
- Calendar 중앙 Viewer에는 실제 Projection의 `시작`, `종료` 필드가 남아 있음을 검증한다.
- Tasks Sidebar는 실제 Google Task Projection의 제목·예정일을 렌더링하고, Projection에 없는 priority·category·가짜 Task List를 표시하지 않음을 검증한다.
- Viewer Empty State는 Gmail·Tasks·Calendar 각각의 안내 문구를 검증하며, Source 전환 뒤 이전 Source 상세가 남지 않음을 검증한다.

### Google Tasks 날짜·상태 의미 회귀

1. Provider `needsAction`은 UI `미완료`, `completed`는 UI `완료`이며 raw enum 노출은 0이다.
2. `due=2026-08-11T00:00:00Z`는 `scheduled_date=2026-08-11` 및 사용자 UI `예정일`로 정규화한다. raw timestamp와 `마감일` 표현은 0이다.
3. 미완료 Task의 예정일이 지나도 Provider·Domain 완료 상태는 변하지 않으며 UI 보조 문구 `예정일 지남`만 허용한다.
4. 메일의 `8월 12일까지 제출` + Task 생성 요청은 `business_deadline=8/12`, `scheduled_date` 없음, Google `due` 자동 생성 0을 검증한다. 업무 마감 보존이 필요하면 승인된 notes·Evidence·Approval Projection을 검증한다.
5. `8월 11일에 처리`는 `scheduled_date=8/11`, Google `due=8/11`을 검증한다. `11일에 처리하고 12일까지 제출`은 두 값을 분리해 검증한다.
6. 시간대 지정 요청에서 Tasks API가 정확한 시간 구간을 설정했다고 성공 선언하는 경우는 0이다. Calendar Event 대안은 별도 승인형 Write인지 검증한다.
7. Task 완료 상태 변경은 정확한 대상·승인형 `UPDATE`이며 예정일 경과로 자동 완료되지 않음을 검증한다.

### UI Fixture 원칙

- Projection fixture는 제공 필드와 누락 필드를 모두 포함한다. 누락 필드에는 placeholder 사실, 가짜 실행 이력, count를 만들지 않는다.
- Page Token fixture는 최소 3페이지를 제공하며, 2/3페이지 재방문에서 API 호출이 없는 경우와 검색 조건 변경 후 1페이지 재조회 경우를 모두 검증한다.
- 접근성 검증은 Chrome·Edge에서 keyboard path와 focus visible을 포함한다. 단위/Component 검증만으로 REST Command, SSE, Approval 안전 회귀를 대체하지 않는다.

## 23. Claim V2·Attachment 필수 회귀

Claim V2:

- version 누락/불일치, issued_at 미래, TTL>60초, 만료 차단.
- Service/MCP Process Instance mismatch 차단.
- Action·Approval·Attempt·Tool·Approval Hash mismatch 차단.
- 실제 MCP Arguments 재해시 결과가 `execution_arguments_hash`와 다르면 Google 호출 0.
- 같은 Nonce/Claim 재사용 시 Google 호출 0.
- `ClaimExecution` DB Commit만으로 MCP Write 호출 0. `BeginExecutionAttempt` Receipt/Result가 `applied=true`이고 current Attempt=`EXECUTING`인 뒤에만 MCP Write를 허용한다.

Attachment:

- Message Attachment Metadata와 실제 Download bytes 일치.
- Download bytes가 LLM Prompt/Context/Evidence/SQLite/Trace로 유입되지 않음.
- Stage 결과 filename/MIME/size/SHA-256이 실제 파일과 일치.
- Staging 파일 변조·만료·삭제 후 기존 Approval 실행 0.
- Draft CREATE/UPDATE·SEND 시 실제 MIME attachment와 승인 Descriptor가 일치.
- Attachment 포함 SEND에서도 SENT_LOOKUP, UNKNOWN_RESULT no-resend 계약 유지.

## 24. Evaluation-derived stable regression gates

13 Evaluation의 candidate/history를 12가 재정의하지 않는다. Product regression에 남기는 것은 현재 owner contract에서 파생되는 안정적 assertion뿐이다.

- Tool selection input은 deterministic Registry eligibility를 통과한 fixed connector/resource/effect 후보만 포함한다. 식별자만 보고 숨은 Tool 의미를 추론해야 하면 Input Projection을 먼저 보강한다.
- Product Prompt Runner는 Prompt Manifest와 allowed-root-field contract를 적용하고 Evaluation Projection 전체를 Product Prompt에 직접 전달하지 않는다.
- LLM candidate stage와 deterministic post-transform/final artifact stage를 같은 Gold로 채점하지 않는다.
- Request Understanding `analysis_requirement`는 06 Workflow current contract를 검증한다. 과거 case ID/Gold correction narrative는 13 Evaluation/Audit에서 관리한다.
- Planning required container identity는 07 Interface current deterministic binding을 검증하며 LLM이 hidden `tasklist_id/calendar_id`를 발명하면 실패다.
- Manual pilot count, candidate Dataset ID, projection bundle ID, experiment chronology는 product regression authority가 아니다. 12는 current owner contract에서 파생된 stable assertion만 유지한다.

이 절은 Evaluation candidate의 승격/순위를 결정하지 않는다.

## 25. Retrieval typed changed-SEARCH Contract Regression

`05 Retrieval`의 current `RetrievalQueryPlanV2 → SourceFetchPlanV1` 계약을 다음 결정적 Contract/Integration Test로 검증한다.

- **Initial SEARCH typed value:** `InitialSearchSpecV1.constraints`에 지원되는 semantic constraint와 실제 값이 있으면 deterministic builder가 `SourceFetchPlanV1.effective_constraints`를 materialize한다.
- **CHANGED SEARCH upsert:** prior effective constraints에 `ConstraintDeltaV2.upsert_constraints`가 적용되어 새 effective constraints와 새 `query_identity_hash`가 생성된다.
- **CHANGED SEARCH remove:** optional constraint kind 제거가 deterministic merge에 반영된다.
- **name-only delta 차단:** constraint 이름/키만 있고 값이 없는 changed SEARCH는 Provider 호출 전에 contract invalid다.
- **unsupported constraint 차단:** frozen `InputToolRouteV1`/Source builder가 지원하지 않는 constraint kind 또는 값은 Provider 호출 0으로 fail-closed한다.
- **required constraint 제거 차단:** Policy Precondition 또는 frozen Route가 요구하는 constraint를 `remove_constraint_kinds`로 제거할 수 없다.
- **upsert/remove 충돌 차단:** 같은 kind를 같은 delta에서 추가/변경과 제거에 동시에 넣으면 Provider 호출 0이다.
- **unchanged SEARCH 차단:** merge/normalize 결과가 prior effective constraints와 동일하면 `QUERY_UNCHANGED_AFTER_FAILURE`, 새 Retrieval Round 증가 0, Provider 호출 0이다.
- **Provider authority leakage 차단:** Product Prompt/Planner output에 raw Provider query, RFC3339 provider representation, raw continuation, MCP Arguments가 들어가면 invalid contract다.
- **determinism:** 동일 `RequestIntentV2 + frozen route + prior effective constraints + ConstraintDeltaV2`는 동일 normalized effective constraints와 동일 `query_identity_hash`를 만든다.
- **operation authority:** `NEXT_PAGE`는 raw continuation을 Run Retrieval Cache handle에서만 resolve하고, `DETAIL_FETCH`는 bounded candidate ref만 Planner가 지정하며 actual target/tool binding은 deterministic code가 수행한다.
- **Prompt projection:** Retrieval 초기 Query Planner 입력에는 raw `user_request`가 없고 `request_intent + input_routes + retrieval_budget`만 존재한다. Follow-up은 bounded semantic summary만 추가한다.
- **Local State version:** Release Retrieval Local State는 `RetrievalState`이며 `query_plan: RetrievalQueryPlanV2 | None`을 사용한다. `RetrievalStateV1`에 V2 field contract를 덮어쓰는 호환 구현은 금지한다.
- **QueryAttempt 비권위:** `added_constraints/removed_constraints` 같은 QueryAttemptV1 summary만으로 다음 `SourceFetchPlanV1`을 재구성하지 않는다.

위 Test는 `12`가 새 제품 의미를 만들기 위한 것이 아니라 `05 Retrieval / 06 Workflow / 15 Prompt·Failure`의 current canonical 계약을 검증하기 위한 회귀 Gate다.

## 26. Responsibility-Split Regression Gate

`06 Workflow`와 `15 Prompt·Failure`의 current Local SLLM responsibility decomposition을 회귀 검증한다.

- 6개 `SemanticAgentOwnerIdV1` 책임은 항상 유지되어야 한다. physical compiled Agent Subgraph 수는 `SINGLE_BASELINE=1`, `THREE_STAGE=3`, `SIX_ROLE_BASELINE=6`의 exact profile binding을 따라야 한다.
- Work Analysis의 entity relation, temporal/dependency, duplicate/conflict candidate, information-gap, operational-risk LLM 책임은 각각 별도 PromptRef/Input Projection으로 검증한다.
- duplicate/conflict LLM output은 candidate이며 deterministic relation validator 전에는 `DUPLICATES | CONFLICTS_WITH` final authority가 될 수 없다.
- Planning ACTION은 `draft_action_objective_per_output_route`와 `compose_arguments_per_output_route`를 별도 LLM call로 수행하고, Tool identity/effect와 dependency authority는 바뀌지 않아야 한다.
- Review는 goal/evidence, action-scope/route, constraints/supplied-policy-summary를 독립 finding으로 만들고 deterministic aggregator가 최종 disposition을 산출해야 한다.
- Revision recheck는 affected dimensions만 재검사하고 `aggregate_review_findings → validate_review`를 다시 통과해야 한다.
- PromptRef/Runtime caller/Manifest/Source/Input Contract의 active set은 **current 06/15 contract와 exact set-equality**여야 한다. 특정 candidate ID·과거 slot count는 13 Evaluation/Audit에서 관리하며 12의 product contract authority가 아니다.
- Product LLM call absolute hard cap은 Run당 24이며, budget 초과는 추가 LLM 호출 대신 fail-closed/defined fallback으로 처리한다.
- Evaluation candidate의 DEV/Holdout/Safety 승격 조건·순위는 13 Evaluation이 소유한다. 12는 Runtime으로 승격된 current contract의 regression만 검증한다.
- **Review freshness persistence:** Action modify/retry/expired-refresh 뒤 durable Review gate가 `REQUIRED`로 reset되고, current plan/action revision에 bound된 Review PASS가 persistence boundary를 통해 기록되기 전 `ApproveAction`은 실패해야 한다. stale PASS 재사용과 concurrent Modify 중 PASS 기록은 version conflict로 차단한다.
- **Expired Approval lifecycle:** `ExpireApproval` 이후 direct `EXPIRED → APPROVED`는 실패하고, `refresh_expired_action → MODIFIED + review REQUIRED + same-UoW REVIEW_ENTRY handoff → fresh Review PASS → new Approval` 경로만 허용한다. refresh commit 뒤 scheduling crash/restart에서도 exactly-one durable Review continuation이어야 하며 stale Approval Row를 ACTIVE로 되살리면 실패다.
- **Reauth resume target:** `REAUTH_COMPLETED`는 saved same-Run `RegisteredResumeTargetRefV2`의 owner/node/graph_version이 active registry와 일치할 때만 resume한다. mismatch/stale checkpoint는 Recovery로 fail closed하며 dispatched Write 재호출은 0건이어야 한다.
- **Recovery RECHECK progress:** 동일 recovery/external-state fingerprint에 새 정보가 없는 `RECHECK`를 반복해 새 Verification round를 만들면 실패다.

## 27. Repository structural regression gate

### 27.1 Implementation completeness regression

- `plan.record_review_result`: current `expected_plan_version + based_on_action_versions`에서 PASS만 durable gate를 열고 concurrent Modify/retry/refresh 후 stale result write는 conflict여야 한다. 이 operation이 Approval/Action lifecycle mutation을 직접 수행하면 실패다.
- Runtime budget: 양의 `max_run_execution_ms/max_connector_calls/max_context_tokens/max_retry_attempts` fixture에서 limit 초과 전 다음 call을 차단하고 active Run의 counter/limit을 Settings 변경으로 reset하지 않는다.
- Component Circuit: technical failure threshold → OPEN/retry_at → retry_at 이전 outbound 0회 → 이후 serialized probe 1회 → 성공 close/reset 또는 failure reopen. Policy/Approval/schema rejection은 circuit failure가 아니다.
- Local API contract: Conversation list keyset cursor/search, Runtime Detail, Session Bootstrap, Resource List가 07 versioned wire schema와 일치한다.
- Port contract: 07 canonical callable method가 Port별로 존재하며 Application은 abstract Port만 import한다.
- P0 MCP Write Catalog: `gmail_send`, `tasks_delete_task`, `calendar_delete_event`가 Input/Output/Scope/Timeout/Retry row를 가진다.


Structural refactor completion is tested independently from whether canonical files merely exist.

A migrated capability passes only when all are true:

```
canonical authority live
intended production callers cut over
old production callers = 0
old production imports = 0
old concrete exports = 0
duplicate live authority = 0
forbidden compatibility = 0
canonical test owner active
behavior regression preserved
```

### 27.2 Application required-operation manifest

The architecture test suite must load the canonical required-operation mapping owned by Repository Architecture and compare it as a closed set against the repository. For each required Application row, assert:

- exactly one canonical production module/symbol exists;
- the expected canonical unit-test owner path exists;
- no second live authority satisfies the same semantic capability;
- production caller inventory is closed across FastAPI, LangGraph, composition/dependency wiring, and other production orchestrators;
- old caller/import/export paths are zero.

Artifact taxonomy regression: state-changing `execution_attempt.reconcile_inflight_executions` and `run.reconcile_retrieval_cache_restart` inputs must be `*CommandV1`, never `*QueryV1`. Query-named state-changing reconciliation artifacts are a closed-world failure.

At minimum, manifest coverage includes the canonical Application owners `conversation`, `message`, `run`, `plan`, `action`, `approval`, `claim`, `execution_attempt`, `verification`, `recovery`, `resource_ref`, and the six Agent owners `request_understanding`, `tool_routing`, `retrieval`, `work_analysis`, `planning`, `review`. Exact required operations come from the current semantic/state-transition authority and Repository Architecture mapping, never from implementation discovery. The exact-set regression must in particular include `execution_attempt.abort_claimed_execution`, `execution_attempt.reconcile_inflight_executions`, `run.project_external_llm_transfer_scope`, and `run.reconcile_retrieval_cache_restart`; treating any of these mapped production authorities as an unexpected extra is a test failure.

### 27.2-A Frontend exact responsibility manifest regression

Architecture test는 16 `Frontend exact responsibility manifest`를 closed set으로 읽고 다음을 검증한다.

- 각 manifest row의 exact production file + primary symbol + canonical test owner가 정확히 하나 존재한다.
- UI-001은 `diagnostics/startup_check.tsx`, UI-002는 `settings/first_run_onboarding.tsx`, FN-001 top-level orchestration은 `app/startup_flow.tsx`에만 존재하며 별도 `onboarding/` owner 0.
- FN-009 session/bootstrap과 compatibility gate, FN-014/015/016 resource browser, FN-018 SSE/progress, FN-021A/FN-042A attachment, FN-078 history, FN-082 diagnostics가 manifest 밖 competing feature module을 갖지 않는다.
- `frontend/src/ui/**`는 presentation-only이며 API call/cache/domain authority 0; `shared/common/utils/service/manager` feature owner package 0.

### 27.2-B Launcher / Installer / Release exact manifest regression

Architecture/Release test는 16 `Launcher · Installer · Release exact manifest`를 closed set으로 읽고 다음을 검증한다.

- Launcher responsibility마다 exact file/symbol/test owner가 하나만 존재하고 `launcher/entrypoint.py` 외 second launcher orchestration root 0.
- single-instance, installation verification, verified Signed Build Config projection, data-dir/ACL, dynamic port, bootstrap secret, service-instance ID, service spawn/readiness/browser/shutdown responsibility가 manifest 밖 generic manager/service/runtime module로 이동하지 않는다.
- installer source root는 `installer/windows/**`, release tooling root는 `release/**`뿐이며 alternate `packaging/`, `build/`, `scripts/release/` production authority 0.
- `API_ONLY`/`LOCAL_CAPABLE` profile, One-folder assembly, Windows installer build, Release Manifest, Code Signing/Timestamp가 각 canonical operation으로 존재한다.
- product runtime import graph에서 `installer/**` 또는 `release/**` import 0.
- Signed Build Config installed authority는 `release-manifest.json + .sig` 하나뿐이다. manifest는 closed `ReleaseManifestV1`이며 `oauth_env/oauth_client_id`를 포함하고 `release/generate_release_manifest.py`가 materialize, `launcher/verify_installation.py`가 signature/hash verify, `launcher/release_build_config.py`가 verified manifest에서만 `SignedBuildConfigV1`을 project해야 한다. competing `build-config.json`, unsigned production env/settings authority는 0이다. P0 manifest/Installer/Keyring/environment/CLI에 `client_secret` 또는 `OAUTH_CLIENT_SECRET` field/path가 있으면 실패다.
- Production signed-locked field를 Launcher arg/User Settings/ambient env로 override 0. tampered/missing signature, wrong `oauth_env/oauth_client_id`, manifest-field mismatch는 MCP child spawn 전 fail-closed다. MCP child의 `GOOGLE_OAUTH_ENV/GOOGLE_OAUTH_CLIENT_ID`는 verified projection과 exact match해야 한다. Signed P0에는 `client_secret` 전달 경로가 없음을 유지한다. 별도로 `EXPLICIT_DEVELOPMENT`는 `.env.local` optional compatibility credential이 authorization-code/refresh grant에만 포함되고 `repr`·오류·connection projection·child environment에는 노출되지 않음을 검증한다.
- `LOCAL_CAPABLE`은 `src/google_work_agent/ports/llm/approved_model_manifest.py`의 단일 parser를 사용해 `release/generate_model_manifest.py`가 생성하고 Release Manifest hash chain에 포함한 `ModelManifestV2 → model-manifest-v2.json(approved Ollama installer identity/hash + approved model ID/digest/parameter class/download size)`과, 그 canonical hash에서 active single-model binding 및 hardware requirement를 선택한 `LocalModelProductDecisionV2 → local-model-product-decision-v2.json`을 요구한다. Product composition은 signed fixture로 모든 inference class가 같은 approved Local model로 resolve되고 unapproved/digest-mismatch가 fail-closed됨을 증명한다. 같은 Ollama/model/profile authority가 `SignedBuildConfigV1`, User Settings, Prompt, Agent code에 중복되면 실패다. `API_ONLY`는 두 local artifact와 provisioning side effect를 모두 금지한다.
- Release CLI가 검증한 Prompt bundle과 `service_distribution` package 기본 Prompt가 달라도 signed output/runtime은 `manifests/prompt/`의 검증된 전자만 사용한다. Prompt manifest·input contract·source·activation evidence 각각의 tamper는 Release 또는 installed runtime에서 fail closed하고, signed composition의 package 기본 Prompt fallback은 0이어야 한다. `EXPLICIT_DEVELOPMENT`의 package DRAFT + `DEVELOPMENT_SMOKE` 경로는 그대로 유지한다.

### 27.3 Final structural negative tests

Release/Main structural validation must assert:

- Application root broad semantic authority zero;
- legacy `application/workflows/**` production authority zero;
- migrated `read_*` / `write_*` concrete compatibility facade zero;
- `_compat` zero on `main`;
- forbidden filename/version-suffix zero except registered exceptions;
- concrete `__init__.py` barrel exports zero; only deliberate stable contract/Port exports allowed;
- Agent atomic responsibility operation-per-file exact coverage;
- legacy test imports/ownership zero for migrated capabilities;
- Application dependency violations zero: FastAPI responsibility, LangGraph routing responsibility, concrete Connector/MCP Adapter, Provider SDK/API client, concrete SQLite adapter/direct SQLite access.
- top-level closed ownership summary includes the already-normative `evaluation/` root; product runtime → `evaluation/**`와 Evaluation → Product internal Python import graph가 모두 zero다.

Old path strings used solely by negative architecture tests are allowed as enforcement literals and are not live-import violations.

### 27.4 Migration history regression

Applied implementation migrations remain immutable and checksum-valid. Structural refactor tests must not require renaming or rewriting historical migrations. Any new persistent invariant is introduced through a new ordered migration and corresponding contract test.

### 27.5 Release verdict

Structural closure is declared only when:

```
STRUCTURAL_CONTRACT_PASS
AND CALLER_CLOSURE_PASS
AND TEST_OWNERSHIP_PASS
AND BEHAVIOR_REGRESSION_PASS
```

A canonical directory that is empty, scaffold-only, or not yet wired is an implementation failure/gap, not a documentation ambiguity when these criteria are unambiguous.


### 27.6 Audit lifecycle parity regression

- `Domain State Transition Contract`의 current lifecycle **command-family key set**과 11의 required Audit mapping key set은 exact equality여야 하며 missing/extra=0이어야 한다. Parameterized command의 disposition coverage도 owning State Contract current set과 별도로 exact 비교하며 숫자 count를 regression authority로 복제하지 않는다.
- state-changing command가 `applied=false` 또는 same-command replay인 경우 새 required Audit append는 0이다.
- required Audit append 실패는 같은 UoW의 Receipt/Domain mutation/final ASSISTANT Message(terminal command인 경우)와 함께 rollback한다.
- `RecordReviewResult`와 `POLICY_CONFIRMATION_RECORDED`는 각각 Application persistence/Policy Confirmation concern이며 lifecycle Command count에 포함하지 않는다.

## 28. Production-authority closed-set regression

이 절은 behavioral contract를 새로 만들지 않고 16 Repository Architecture의 production placement/single-authority closure를 검증한다.

### 28.1 Domain Repository manifest

- 04 §16 persistence capability 각각이 16/07의 exact Repository/SQLite Adapter/Test row 하나에만 매핑된다.
- `ConversationRepository`, `MessageRepository`, `RunRepository`, `PlanRepository`, `ActionRepository`, `ApprovalRepository`, `ExecutionAttemptRepository`, `VerificationRepository`, `RecoveryRepository`, `ResourceRefRepository`, `EvidenceRepository`, `CommandReceiptRepository`, `RetentionRepository` 이외 generic `DomainRepository|CRUDRepository|RepositoryManager` production authority 0.
- `ClaimExecution`은 별도 ClaimRepository를 만들지 않고 Action+Approval+ExecutionAttempt+Receipt+Audit repositories를 하나의 UoW에서 사용한다.
- hidden mutable dependency-result repository/status column authority 0.

### 28.2 Registry single authority

- `ConnectorRuntimeRegistry`: exactly one production class/path; connector_id별 active process binding only.
- `SignedToolRegistry`: exactly one Core Tool semantic registry; MCP descriptor/projected registry가 competing authority가 아님.
- `NodeRegistry` + `ResumeTargetRegistry`: active graph_version/node target validation의 유일한 lookup authority.
- `PromptRegistry`: active PromptRef/manifest/source lookup의 유일한 runtime registry; LLM adapter prompt selection 0.
- Graph Profile lookup은 `adapters/langgraph/profiles/profile_registry.py → get_graph_profile_builder()`만 소유하며 별도 registry class authority를 만들지 않는다.
- generic `RegistryManager`, catch-all service locator, subgraph-local duplicate resume registry 0.

### 28.3 LangGraph exact adapter manifest

- 06 current Agent Runtime Node set = 35.
- 16/06 exact node adapter rows = 35/35.
- 각 row는 exact node file/symbol + projection file/symbol + Application operation(s) + router file/symbol + architecture test를 가진다.
- `validate_work_analysis`, `validate_plan`, `validate_review`, `resolve_policy_preconditions`, `resolve_availability`, `resolve_default_container`가 extra Runtime Node/ResumeTarget로 승격되지 않는다.
- undefined/extra current production Agent node = 0.

### 28.4 Confirmation wire/controller

- `RunSnapshotResponseV1.pending_interrupt` wire type은 `PendingInterruptResponseV1` 하나다.
- internal `ConfirmationRequiredV1 → PendingInterruptResponseV1` projection에서 resume_target/checkpoint metadata가 Browser로 노출되지 않는다.
- current legacy interrupt DTO alias definition/reference = 0.
- `/confirm → run.confirm_run → ResumeConfirmation(applied=true) + same-UoW WorkflowHandoff(PENDING) → post-commit schedule_run_execution(handoff_id)` 경로 하나만 허용.
- PolicyConfirmationReceiptV1 생성 production authority는 ConfirmRun/Application control boundary 하나다.

### 28.5 LLM Runtime Router

- Application/Agent가 import하는 inference boundary는 `StructuredInferencePort` 하나.
- production concrete binding = `StructuredInferenceRuntimeRouter` exactly one.
- leaf API/Ollama inference adapter를 Application/Agent/FastAPI가 직접 import/select하는 경로 0.
- external API provider leaf file/symbol mirror exact: `<provider>/structured_inference.py → <Provider>StructuredInferenceAdapter`, `<provider>/credential.py → <Provider>LlmCredentialAdapter`, `<provider>/runtime_status.py → <Provider>LlmRuntimeStatusAdapter`.
- Ollama leaf exact: `ollama/structured_inference.py → OllamaStructuredInferenceAdapter`, `ollama/runtime_status.py → OllamaLlmRuntimeStatusAdapter`; `ollama/credential.py` production artifact 0.
- concrete leaf tests mirror `tests/unit/adapters/llm/<provider>/test_{structured_inference,credential,runtime_status}.py` and `tests/unit/adapters/llm/ollama/test_{structured_inference,runtime_status}.py`.
- `LlmCredentialPort`/`LlmRuntimeStatusPort`도 production Router binding exactly one; provider-specific credential/status leaf를 Application/API가 직접 선택하는 경로 0.
- concrete external API provider/model name은 10/13의 current Release selection 없이 Repository/Core default로 발명·고정되지 않는다.
- AUTO fallback/actual_runtime/provider/model/fallback_reason은 Router contract로만 기록.

### 28.6 Background Run execution

- `StartRun` UoW commit 이전 `WorkflowExecutionPort.submit` = 0.
- committed Run은 `run.schedule_run_execution → WorkflowExecutionPort → BackgroundRunExecutorAdapter` 한 경로로만 LangGraph 실행.
- Confirmation/Reauth/Recovery resume도 owning lifecycle command `applied=true` 이후 같은 execution boundary 사용.
- FastAPI `BackgroundTasks`, `asyncio.create_task`, concrete worker queue/LangGraph executor 직접 선택 0.
- 동일 run_id concurrent worker execution은 하나만 허용.

### 28.7 Composition root

- production Service entry/composition = `api/app.py → create_app() → api/composition.py → build_production_runtime()` exactly one.
- `application/composition.py`, `launcher/composition.py`, FastAPI route/startup-helper ad-hoc concrete binding, adapter-local second root 0.
- composition root는 wiring만 수행하고 Tool/Prompt/Policy/Domain semantic 결정 0.

### 28.8 Connector-neutral circuit

- Core circuit key는 `ComponentCircuitKeyV1`.
- `CONNECTOR` branch는 connector_id 필수, `LLM_RUNTIME` branch는 `API_LLM|LOCAL_GPU` 필수.
- Core closed enum에 `GOOGLE_API`, `MICROSOFT_API` 등 provider-specific circuit identity 0.
- second Connector 추가 시 circuit semantic enum 수정 없이 connector_id row만 추가.

### 28.9 Review six-disposition persistence regression

- `ROUTE_RECONSIDERATION → plan.record_review_result → restart → guarded BeginPlanning`을 검증한다.
- `CONFIRM → plan.record_review_result → restart → guarded RequestConfirmation`을 검증한다.
- six-disposition set과 `RecordReviewResultCommandV1.disposition`의 set equality를 architecture contract test로 고정한다.
- stale `expected_plan_version` 또는 `based_on_action_versions`는 conflict이고 durable writer/guard를 우회하지 않는다.

### 28.10 Frontend/API compatibility regression

- matching supported contract version → bootstrap `COMPATIBLE`, mutation/SSE admission allowed.
- unsupported version → `INCOMPATIBLE`, mutation/SSE 0.
- Browser가 ConversationHistory를 먼저 호출해야 version을 알 수 있는 경로는 금지한다.

### 28.11 AbortClaimedExecution regression

- Claim → cancel → before Begin: Write 0, Attempt FAILED, Action CANCELLED, FinalizeCancel reachable.
- Claim → crash → restart → before Begin: Write 0, `AbortClaimedExecution` → Action/Attempt FAILED, retry/cancel path reachable.
- Claim → invalid ClaimContext / pre-Begin credential failure: same non-cancel settlement.
- BeginExecutionAttempt vs Abort race: exactly one APPLIED by CAS; if Begin wins, Abort 0 and in-flight result-resolution path; if Abort wins, Write 0.

## 29. Implementation determinism regression

Architecture regression must assert:

- Review 6-disposition set == durable Review writer set.
- `requested_mode` survives StartRun→restart→same-Run resume exactly.
- external LLM provider call requires persisted consent=true; revoke blocks subsequent external calls.
- bootstrap incompatible API contract blocks mutation/SSE.
- Task List/Calendar container discovery and Backup list routes exist in 07↔16 exact route set.
- LLM credential status and Google `display_email` are re-readable non-secret projections.
- Runtime diagnostics projection renders every FN-082 required category without secret/raw path.
- non-Domain operational command replay uses `OperationalCommandReplayPort`, never Domain `command_receipts`.
- pre-Begin CLAIMED Attempt is settleable only by `BeginExecutionAttempt` or `AbortClaimedExecution`, never stranded.

### 29.1 Operational/UI transport regression

- task-list/calendar container list routes return bounded container projections and call registered READ tools through `ConnectorReadPort`.
- `GET /api/v1/backups` survives Safe Mode and yields opaque selectable refs.
- `GET /api/v1/credentials/llm/{provider}` rehydrates `configured/storage_mode/validation_status` without secret material.
- connection status exposes verified `display_email` while `account_id` remains opaque.
- FN-082 required diagnostics categories are renderable from protected `/api/v1/runtime` only.
- 07 Local API route set equals 16 mapping set after these read surfaces are included.

### 29.2 Lifecycle/audit closed-set regression

`AbortClaimedExecution` must be present in State Contract, 16 handler mapping, 11 Audit mapping (`EXECUTION_CLAIM_ABORTED`), State Matrix, and unit/E2E tests. Missing or extra lifecycle family across these surfaces fails architecture regression.
