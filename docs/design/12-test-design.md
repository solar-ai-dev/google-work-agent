# 12. Google Work Agent · 테스트 설계서

> **문서 기준:** `01 PRD v2.10`, `01-A v2.17`, `01-B v2.11`, `02 UI·UX v2.13`, `03 Architecture v3.6`, `04 Database v1.19`, `05 Retrieval v2.13`, `06 Workflow v7.17`, `07 Interface v2.22`, `08 Sequence v3.15`, `09 Security v2.10`, `10 Infrastructure v2.10`, `11 Observability v2.20`, `15 Agent Capability·Failure·Prompt v1.23`, Domain 상태 전이 계약 v1.5와 테스트 매트릭스 v1.5을 기준으로 한다.
>
> **상태:** Draft v3.36 · **기준일:** 2026-08-18 · **OS:** Windows 11 x64 · **Browser:** Chrome·Edge

## 1. 목적과 계층

이 문서는 제품 계약과 안전 회귀를 검증한다. Model·Prompt·Retrieval·Graph 품질 비교는 `13. 평가·실험 설계서`가 소유한다.

```text
Unit → Contract → Integration → Component → E2E → Failure Injection → Installer·Release
```

모든 상태 전이는 허용 Edge와 금지 Edge를 검증한다.

## 2. Test ID·Traceability

```text
TST-<AREA>-<NNN>
AREA = DOM DB API SSE UI WF AGT RET LLM MCP CON GGL SEC INF OBS E2E PERF REL EVAL
```

Case 필드:

```text
test_id
source_contract
requirement_ids
case_id?
fixture_snapshot_id?
user_prompt_id?
experiment_id?
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

일반 CI에 Refresh Token·API Key·Signing Private Key를 넣지 않는다.

## 4. Test Double

```text
FakeClock
DeterministicUUID
FakeKeyring
FakeConnectorTransport      # Core Connector contract
FakeGoogleProviderAdapter   # P0 Google Workspace MCP Server 내부 Adapter 테스트 전용
FakeMCPTransport
FakeLLMProvider
FakeOllamaAdapter
FakeHardwareProbe
FakeBrowserLauncher
FaultInjectingSQLiteAdapter
FakeExperimentClock
DeterministicGrader
```

## 5. Fixture

합성 Gmail·Tasks·Calendar만 사용한다. Snapshot은 `fixture_snapshot_id`와 Relation Manifest를 가진다.

필수 경계:

- Gmail 긴 Thread·외부 주소·Prompt Injection
- Task 중복·유사·예정일 없음·예정일 임박·업무 마감 분리
- Calendar Busy·Tentative·Free·OOO·Focus·DST
- Write 정상·정규화 차이·Mismatch
- 401·403·404·409·429·5xx·Timeout·응답 유실

User Prompt Catalog 필드:

```text
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

Plan·Action 미생성, Message·Trace·Run Terminal 원자 저장.

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

새 Attempt·Write 금지. CREATE Search, UPDATE GET Target.

### Constraint

Open Run 1, Active Approval 1, Active Attempt 1, Version Conflict, DAG Cycle, Unique Position·Revision·ResourceRef.

## 7. Contract

- FastAPI Pydantic·Error Envelope
- `/health/live`, `/health/ready`, `/api/v1/runtime` 책임 분리
- SSE monotonic Event ID·Last-Event-ID·Snapshot Fallback
- Agent Structured Output Version·Enum·Repair 1회
- MCP Tool Registry·Schema·Effect·Scope·Retryability
- Observability Envelope·16 KiB·Sanitization
- Experiment Config·Candidate Config Hash·Projection Version·Grader Version

## 8. Multi-Agent·Prompt

- Profile별 Agent Subgraph 개수 계약: SINGLE=1, THREE=3, SIX=6
- Agent Subgraph는 invocation 범위 Local State만 사용하고 장기 Memory를 생성하지 않음
- Agent 간 직접 호출·Peer-to-Peer 금지
- Agent invocation 수와 LLM Call 수를 별도 계수
- Route별 LLM Budget Profile과 절대 상한 16 검증
- Revision 2, Repair 1, Additional Retrieval 2
- Main State Owner 단일성: RequestIntent/ToolRoute/Retrieval/Analysis/Planning/Review 각각 단일 Owner
- Tool Route 한 번 확정 후 Retrieval·Planning의 Tool 재선택 0

- 결정적 `PolicyPreconditionResolver`: `TASK + CREATE`는 기존 미완료 Task 중복검사용 Tasks READ, `CALENDAR + CREATE`는 Event/FreeBusy 충돌검사용 Calendar READ를 필수 IN Route로 포함한다.
- 위 필수 READ가 사용자의 명시적 Source·기간·Resource 범위를 벗어나면 자동 확장 금지. `SCOPE_EXPANSION_REQUIRED` APPROVED Receipt 전에는 Route 실행 불가, 거절 후 검사를 생략한 Write Plan은 실패다.
- `PolicyConfirmationReceiptV1`은 Agent/LLM이 생성할 수 없고 `meta.based_on + decision_context_hash`가 active revision과 일치해야 한다. stale/DECLINED Receipt, Audit/Checkpoint Receipt ID 불일치는 실패다.
- Work Analysis의 `relation_candidates`는 결정적 validator를 거쳐 `validated_relations`로 승격되어야 한다. 검증 전 `DUPLICATES`/`CONFLICTS_WITH`가 최종 Result에 직접 들어가면 실패다.
- 정확 Task 중복은 기본 `action_necessity=NOT_REQUIRED`이며 새 Action 0. 추가 생성은 `DUPLICATE_OVERRIDE_REQUIRED` 2차 Confirmation 후에만 가능하다.
- 검증된 Calendar 충돌 Action은 `CONFLICT_OVERRIDE_REQUIRED` 2차 Confirmation 후에만 가능하다.
- Override Action은 `WorkAnalysisResultV2.policy_confirmation_receipt_refs`와 Approval Snapshot이 같은 APPROVED Receipt를 참조해야 하며 누락/stale이면 Claim 전에 차단한다.

- Retrieval LLM의 MCP 직접 호출 금지, deterministic Read Node만 `input_routes[].allowed_read_tool_ids` 범위에서 MCP Read Port를 호출하도록 허용
- Connector 접근 공통 경계 검증: React·FastAPI Route·Application·LangGraph·Agent·Domain에서 Provider API/SDK 직접 호출·직접 Provider Client 구성 0건. 모든 Sidebar Browse/Count/Detail, Retrieval Read, Write, Verification, Recovery 조회는 `FakeMCPTransport`/MCP Tool 경계를 통과한다. Provider Adapter 단위 테스트는 해당 MCP Server 내부에서만 수행한다. P0 `GGL` 영역은 Gmail·Tasks·Calendar·Google OAuth 세부 계약을 검증하고 `CON` 영역은 Connector Registry/MCP boundary를 검증한다.
- MCP unavailable/Tool Schema invalid 상황에서 제품 Core가 Google Provider API 직접 호출로 fallback하지 않고 NOT_READY/Recovery로 전환함을 검증
- Preflight/Claim `applied=false`가 ACTION_EXECUTION으로 fall-through하지 않고 Domain Result에 따라 재승인·Recovery·Terminal로만 라우팅되는지 검증
- Recovery는 recheck 필요 시에만 Verification으로 복귀하고 `RECOVERY_REQUIRED` 유지 시 explicit resolve/re-auth까지 suspend하며, terminal failure/block/cancel에서 무한 Verification loop가 없음을 검증
- Confirmation은 `interrupt_id + owner_subgraph + RegisteredResumeTargetRefV1`으로 발생 Subgraph checkpoint에 복귀하며 무조건 Request Understanding으로 재시작하지 않음. Resume target은 compiled Graph Registry 등록값만 허용하고 LLM 임의 Node ID는 차단
- `RetrievalNeedV1`은 non-empty `required_information`과 최소 1개 `reason_codes`만 허용하며 Connector·Tool·raw query·page token·MCP argument를 포함하지 않음. Work Analysis `NEEDS_MORE_DATA`와 Review `RETRIEVE_MORE`만 결정적 `RetrievalRequiredV1` projection을 만들고 Retrieval 자신의 `NEEDS_MORE_DATA`는 같은 frozen IN Route의 local bounded loop로 남음
- Retrieval self-loop continuation의 raw Provider token은 Run Retrieval Cache read-result entry에만 memory-only로 존재하고 Local/Main State·Checkpoint·Domain DB·Prompt·Trace·Audit에는 0건이어야 함
- `NEXT_PAGE` 검증: prior handle의 `run_id + route_id + query identity/hash`가 현재 frozen IN Route와 일치하고 continuation이 미소진일 때만 MCP Read가 발생함. unknown/cross-run/wrong-route/wrong-query/exhausted handle은 Provider 호출 0건으로 fail-closed
- Follow-up `retrieval.plan_query`는 `current_round_no + prior QueryAttempt + unresolved SufficiencyIssueV2 + bounded read-result summary`만 추가 소비하고 raw Page Token·Provider-native Query·MCP Arguments를 소비하지 않음
- 동일 Query + 동일 continuation state 반복은 새 Retrieval Round로 인정하지 않으며 `NEXT_PAGE | DETAIL_FETCH | unresolved issue에 근거한 changed SEARCH`만 새 정보 획득 후보로 인정함
- Release Retrieval planner output은 `RetrievalQueryPlanV2 / RouteQueryIntentV2`여야 하며 `RetrievalQueryPlanV1`을 새 Release authority로 사용하면 실패
- Initial SEARCH는 값이 포함된 `SemanticRetrievalConstraintV1`을 요구하고 name-only constraint 또는 Provider-native query 문자열은 실패
- CHANGED SEARCH upsert: prior `SourceFetchPlanV1.effective_constraints`와 `ConstraintDeltaV2.upsert_constraints`가 결정적으로 merge되어 새 `query_identity_hash`를 생성함
- CHANGED SEARCH remove: `remove_constraint_kinds`가 허용된 optional kind만 제거하며 frozen Route/Policy-required constraint 제거는 Provider 호출 0건으로 실패
- 같은 kind를 upsert/remove에 동시에 넣거나 unsupported/value-empty/contradictory temporal constraint는 Provider 호출 전에 fail-closed
- 의미상 동일한 changed SEARCH는 `QUERY_UNCHANGED_AFTER_FAILURE`로 차단되고 Retrieval Round를 증가시키지 않음
- 날짜 semantic value는 offset 없는 local ISO + IANA timezone이며 RFC3339/Gmail query syntax는 deterministic builder만 생성
- `ParticipantConstraintV1`은 role별 participant를 보존하여 sender+recipient 동시 제약을 손실 없이 표현
- `QueryAttempt.added_constraints/removed_constraints`는 관측 summary로만 사용하며 `SourceFetchPlanV1.effective_constraints` 재구성 권위로 사용하지 않음
- Retrieval Product Prompt에 raw `user_request`를 별도 권위 입력으로 재주입하지 않음. Initial planner Projection은 `request_intent + input_routes + retrieval_budget`
- Release Retrieval Local State는 `RetrievalStateV2`이며 `RetrievalStateV1` 이름에 V2 field contract를 덮어쓰지 않음
- 현재 IN Route로 추가 정보 요구를 충족할 수 없으면 `RetrievalRequiredV1`로 우회하지 않고 `RouteReconsiderationRequiredV1`을 사용함
- Resume target은 현재 compiled Main Graph Registry의 `(subgraph_id, node_id, graph_version)` 등록값만 허용. unknown target·wrong owner·wrong graph version은 fail-closed이며 LLM/User supplied resume authority를 허용하지 않음
- `ConfirmationRequiredV1.options=[]`는 자유 텍스트, non-empty options는 등록값 중 하나만 허용하는 닫힌 선택으로 검증. `UserInterruptV1`이 필요한 경우 Canonical confirmation state에서 UI/API one-way projection으로만 생성하고 Main State의 독립 workflow truth로 저장하지 않음
- 모든 공식 disposition은 정확히 하나의 Edge·Interrupt·Terminal 경로를 가지며 unknown disposition은 fail-closed
- Synthetic Branch Completeness Fixture는 Request/Tool Route/Retrieval/Work Analysis/Planning/Review의 모든 공식 disposition과 Domain/Application의 Preflight·Verification·Recovery 결과 분기를 최소 1회 이상 통과해야 한다. 각 Case는 END, 사용자 interrupt/suspend 또는 명시된 owner back-edge 중 하나로 닫혀야 하며 implicit fall-through·무한 self-loop·정의되지 않은 terminal을 허용하지 않는다.
- Retrieval에 Run-scoped RAG 단계 존재 및 후보 전체의 downstream 전달 금지
- Node별 Typed Input Projection: 필요하지 않은 Main/Local State 필드 전달 금지
- Prompt Registry Key 검증
- Supervisor는 Node만 Routing하고 선택된 Agent·Application Node가 PromptRef를 확정
- LLM Router·Model의 Prompt 선택 금지
- Agent별 단일 Prompt 금지
- Repair·Revision 별도 Prompt ID
- Prompt Manifest Version·Hash·Schema 검증
- `ORACLE` Node Run과 `LIVE` Handoff Run 분리
- `RESOURCE_SELECTED`에서 불필요한 Workspace Search 금지
- `output_mode=ANSWER`에서 Action Argument/Plan Node 미호출
- Review 없음·있음 Candidate가 Domain·Policy 코드를 공유


### 8-A. Canonical Workflow·State Regression

- Run 시작 뒤 Request Understanding 전에 `StartAnalysis: CREATED → ANALYZING`이 정확히 한 번 적용되어야 한다.
- Request `COMPLETE`는 Tool Route로 정확히 한 번 연결된다. Retrieval/Planning으로 직접 건너뛰면 실패다.
- `BeginRetrieval`은 `ANALYZING | PLANNING → RETRIEVING`, `BeginPlanning`은 `ANALYZING | RETRIEVING → PLANNING`을 지원하며 이미 target 상태인 local loop에서는 반복하지 않는다.
- `NEEDS_MORE_DATA`는 local budget 내 bounded loop만 허용하고 budget 소진 시 `NEEDS_CONFIRMATION | PARTIAL | BLOCKED`로 정규화한다. `NO_FETCH_NEEDED`는 SUFFICIENT와 같은 analysis guard를 따른다.
- Confirmation은 `RequestConfirmation → WAITING_CONFIRMATION → ResumeConfirmation → 동일 owner checkpoint`를 사용한다. 모든 Confirmation을 Request Understanding으로 공통 재시작하면 실패다.
- Preflight/Claim `applied=false`가 `ACTION_EXECUTION` 또는 `FINALIZE`로 fall-through하면 실패다. `current_status + next_allowed_commands`로 재조정해야 한다.
- `ACTION_EXECUTION`: `EXECUTED`만 Verification, `UNKNOWN_RESULT`는 Recovery, `FAILED + NOT_SENT`는 retry/cancel 대기 suspend다.
- 승인형 Write 첫 Verification은 정상 경로 `WAITING_APPROVAL → VERIFYING`, 취소 후 이미 EXECUTED된 결과 확인은 `CANCEL_REQUESTED → VERIFYING`이다. 다중 Action에서 이미 VERIFYING이면 반복 호출하지 않는다.
- predecessor Action이 `VERIFIED`되기 전 종속 Action을 실행하면 실패다.
- 모든 승인 Action terminal + 미해결 결과 0 + cancel intent false에서만 `CompleteWriteRun → COMPLETED`; cancel intent true이면 `FinalizeCancel → CANCELLED`가 우선한다.
- `RequestCancel` APPLIED Receipt는 `VERIFYING | RECOVERY_REQUIRED | REAUTH_REQUIRED` 전환 및 재시작 이후에도 durable cancel intent를 복원해야 하며 새 Claim/Write는 0이다.
- `ResolveRecovery(FAIL)`은 `FAILED → FINALIZE` 한 경로만 가져야 한다. `ACCEPT_PARTIAL`과 중복 Edge에 매핑하면 실패다.
- `Retrieval.PARTIAL + usable Evidence 없음`은 `CompleteAnswerOnlyRun → COMPLETED` 이후 FINALIZE해야 하며 비Terminal Run의 직접 FINALIZE는 실패다.
- unknown Enum/Version/Disposition은 bounded repair 후 `RequireRecovery(CONTRACT_VIOLATION)`로 fail-closed한다.
- `BlockRun`은 Claim 전 + Active/Unknown/미검증 Write Attempt 없음일 때만 적용한다. Plan이 존재하면 Action terminalize → ACTIVE Approval revoke → Plan CANCELLED → Run BLOCKED 순서를 같은 UoW에서 지켜 `0005` cross-aggregate trigger를 만족해야 한다.

## 9. UI

- Setup·Google Login·3열 Layout
- Gmail·Tasks·Calendar Pagination·Session Cache
- Resource Selection·Agent Search
- Confirmation·Approval·Modify·Partial Approval
- Verification Diff·UNKNOWN_RESULT·Recovery
- Refresh·SSE reconnect·duplicate click
- Chrome·Edge·Keyboard·Focus·Sanitization

## 10. Failure Injection

<table fit-page-width="true" header-row="true">
	<tr>
		<td>위치</td>
		<td>오류</td>
		<td>기대</td>
	</tr>
	<tr>
		<td>LLM</td>
		<td>Timeout·Invalid Output</td>
		<td>Repair·Fallback 상한</td>
	</tr>
	<tr>
		<td>MCP Read Tool</td>
		<td>401·429·5xx</td>
		<td>Reauth·제한 Retry</td>
	</tr>
	<tr>
		<td>Google Write</td>
		<td>전달 전 실패</td>
		<td>FAILED</td>
	</tr>
	<tr>
		<td>Google Write</td>
		<td>응답 유실</td>
		<td>UNKNOWN_RESULT</td>
	</tr>
	<tr>
		<td>Verification</td>
		<td>404·Timeout</td>
		<td>즉시 실패 확정 금지</td>
	</tr>
	<tr>
		<td>SQLite</td>
		<td>Busy·Disk Full</td>
		<td>Write 전 차단</td>
	</tr>
	<tr>
		<td>Audit</td>
		<td>저장 실패</td>
		<td>안전 Command 실패</td>
	</tr>
	<tr>
		<td>MCP</td>
		<td>Exit</td>
		<td>1회 Restart 또는 UNKNOWN_RESULT</td>
	</tr>
	<tr>
		<td>SSE</td>
		<td>Loss</td>
		<td>Domain 계속·UI 복원</td>
	</tr>
	<tr>
		<td>Launcher</td>
		<td>Shutdown Timeout</td>
		<td>Recovery Marker</td>
	</tr>
	<tr>
		<td>Experiment Runner</td>
		<td>Budget 초과</td>
		<td>새 Item 시작 중단·Partial 표시</td>
	</tr>
	<tr>
		<td>Grader</td>
		<td>Schema·Version 불일치</td>
		<td>후보 판정 중단</td>
	</tr>
</table>

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
- LOCAL_CAPABLE missing Ollama·Model diagnosis and external install guidance
- Upgrade Backup·Migration·Safe Mode·Downgrade block
- Default uninstall preserves DB·Backup·Settings and deletes OAuth·LLM credentials

## 13. Observability

- Correlation IDs
- Case·Fixture·User Prompt·Prompt·Model·Graph 연결
- `experiment_id`, `evaluation_item_id`, `candidate_config_hash`, `trial_index`
- `projection_version`, `upstream_mode`, `target_node_id`, `grader_version`
- Log Rotation·Trace 30일·Audit 90일
- Audit append-only Repository
- Sanitization Canary Leak 0
- `ORACLE`·`LIVE`, Full·Partial 결과 혼합 금지

## 14. Evaluation Harness Regression

실험 Runner와 Dataset은 제품 품질 비교 전에 다음 회귀를 통과한다.

### Dataset·Projection

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
- 승인·Claim·Write·GET Verification은 Strict 순서 검증
- Write 최종 상태를 Google Fixture End-state와 비교
- 텍스트 성공 선언만으로 Write 성공 처리 금지

### Scoring Contract

- `scoring-contract-v1.1.json` 존재·Version 고정
- Hard Gate 실패 Candidate가 aggregate PASS가 되지 않음
- Core·Stress·Holdout 분모를 분리
- E06-A에서 `six_reference_route`를 common BTS 조건으로 사용하지 않음
- 비용·Latency가 BTS 실패를 상쇄하지 않음

### Grader Calibration

- 결정적 판정 가능 항목에 LLM Judge 단독 사용 금지
- Human Sample과 LLM Judge 불일치 기록
- Dataset Issue와 Candidate Failure 분리
- Grader Version 변경 시 과거 결과와 직접 합산 금지

## 15. Coverage

```text
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

## 16. Release Block

미승인 Write, 금지 Tool, Hash 변경, Verification 누락, 중복 Write, UNKNOWN_RESULT 재실행, FAILED 직접 실행, READ 승인 Row, Retrieval LLM 직접 MCP 호출, Open Run 중복, Secret Leak, Public Bind, Signature·Migration·Backup 실패, Chrome·Edge 실패, API_ONLY Ollama 의존 중 하나라도 있으면 차단한다.

Experiment Runner는 Dataset·Projection 참조 오류, Holdout 누수, 의도 외 Config Diff, Grader Version 누락, Budget 미설정 중 하나라도 있으면 실험 결과 생성을 차단한다.

## 17. 필수 회귀 ID

<table fit-page-width="true" header-row="true">
	<tr>
		<td>Test ID</td>
		<td>계약</td>
	</tr>
	<tr>
		<td>`TST-DB-101`</td>
		<td>Command Receipt와 Domain 변경 원자 Commit</td>
	</tr>
	<tr>
		<td>`TST-API-101`</td>
		<td>같은 Command ID·같은 Hash 기존 결과 반환</td>
	</tr>
	<tr>
		<td>`TST-API-102`</td>
		<td>같은 Command ID·다른 Hash 409 차단</td>
	</tr>
	<tr>
		<td>`TST-SEC-101`</td>
		<td>Bootstrap Endpoint는 기존 Session 없이 Secret으로만 성공</td>
	</tr>
	<tr>
		<td>`TST-SEC-102`</td>
		<td>일반 API는 Local Session 없이 차단</td>
	</tr>
	<tr>
		<td>`TST-SEC-103`</td>
		<td>OAuth Token 원문 FastAPI·Log·DB 미노출</td>
	</tr>
	<tr>
		<td>`TST-MCP-101`</td>
		<td>유효 Claim Token만 Write 허용</td>
	</tr>
	<tr>
		<td>`TST-MCP-102`</td>
		<td>Claim Token 재사용·만료·Binding 불일치 차단</td>
	</tr>
	<tr>
		<td>`TST-WF-101`</td>
		<td>Agent Node의 MCP 직접 호출 0회</td>
	</tr>
	<tr>
		<td>`TST-WF-102`</td>
		<td>Node Registry 외 Edge 차단</td>
	</tr>
	<tr>
		<td>`TST-E2E-101`</td>
		<td>Run 응답 유실·Service 재시작·재전송 시 Run 1개</td>
	</tr>
	<tr>
		<td>`TST-E2E-102`</td>
		<td>부분 Action 성공 후 취소: Run CANCELLED·result_kind PARTIAL</td>
	</tr>
	<tr>
		<td>`TST-EVAL-101`</td>
		<td>Case 1:N User Prompt와 Evaluation Item 연결</td>
	</tr>
	<tr>
		<td>`TST-EVAL-102`</td>
		<td>Canonical Case와 모든 Projection Reference 무결성</td>
	</tr>
	<tr>
		<td>`TST-EVAL-103`</td>
		<td>후보 간 의도한 독립 변수 외 Config Diff 0</td>
	</tr>
	<tr>
		<td>`TST-EVAL-104`</td>
		<td>`ORACLE`·`LIVE` Upstream 입력 모드 분리</td>
	</tr>
	<tr>
		<td>`TST-EVAL-105`</td>
		<td>Required·Forbidden Read Tool Trajectory 판정</td>
	</tr>
	<tr>
		<td>`TST-EVAL-106`</td>
		<td>Write 승인·Claim·GET·End-state Strict 판정</td>
	</tr>
	<tr>
		<td>`TST-EVAL-107`</td>
		<td>Grader Version·Human Calibration·Dataset Issue 분리</td>
	</tr>
	<tr>
		<td>`TST-EVAL-108`</td>
		<td>Scenario Family·Fixture Relation Family Holdout 누수 0</td>
	</tr>
</table>

---

## 18. Agent Capability·Retry 회귀

이 절은 기존 8절의 단일 예산·Review 재시도 설명을 폐기하고 다음 Route Profile 계약으로 대체한다.

```text
NORMAL_MAX_LLM_CALLS=8
RETRIEVAL_HEAVY_MAX_LLM_CALLS=14
REVISION_HEAVY_MAX_LLM_CALLS=12
ABSOLUTE_MAX_LLM_CALLS=16
PLANNING_REVISION_PER_RUN=2
REVIEW_RECHECK_PER_PLANNING_REVISION=1
```

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
- 같은 Query와 새로운 continuation state의 `NEXT_PAGE`는 정상으로 인정한다. 동일 Query + 동일 continuation state 반복은 Round 증가 없이 실패 처리한다.
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
- DELETE: Calendar Event만 허용 + GET_ABSENT 확인.
- Task 완료·Calendar 참석자 변경: 정확한 Target과 승인된 UPDATE.
- Gmail 원문 삭제·반복 Event 전체 일괄 수정: Tool 제안/실행 0.
- Google Task DELETE: 정확한 Task Target → 승인 → Claim V2 → `tasks_delete_task` → `GET_ABSENT` Verification. 승인/Claim/검증 우회 0.
- `ClarificationQuestionV1`: 후보·차이·선택지·same-thread Resume.
- 문맥으로 해결된 요청과 `답장해줘` SEND 의도에 불필요 Clarification 0.
- 전체 Mailbox/무제한 Workspace 조회는 API 호출 전에 BLOCK.
- Calendar overlap 자체를 conflict로 오판하지 않는다.
## 20. Agent Subgraph 회귀 테스트

- `SIX_ROLE_BASELINE`의 Role은 Request Understanding / Tool Route / Retrieval / Work Analysis / Planning / Review다.
- Tool Route Subgraph가 `ToolRoutePlanV2`을 Parent에 반환한 뒤 Retrieval·Planning은 Tool Route를 read-only로 소비한다.
- Retrieval Subgraph는 `input_routes` 안에서 Query→결정적 Read→Normalize/Segment→Run-scoped RAG→Evidence→Sufficiency를 완료한 뒤 공식 `RetrievalResultV1`과 필요한 Typed `WorkflowSignalV1`만 반환한다.
- Retrieval의 Query candidate·Page Token·RAG score·repair candidate를 Main State에 승격하지 않는다.
- Planning은 `output_routes[].selected_tool_id`와 해당 Tool Schema만 사용해 Arguments를 작성하고 Tool을 다시 선택하지 않는다.
- upstream State revision 시 의존 downstream State가 stale 처리되고 재생성되는지 검증한다.
- `SINGLE_BASELINE`은 Planning 결과에 대해 같은 Unified Agent 내부 self-review 책임을 수행한다.
- E06-B는 `CONTEXT_READY_V1` 호환 Snapshot 이후만 실행하며 MCP Read Tool 호출 수가 0이어야 한다.
- E06-B 후보는 `B1_INTEGRATED=1`, `B2_STAGED=2`, `B3_SPECIALIZED=3` post-retrieval Agent Subgraph topology를 가져야 한다.

<table fit-page-width="true" header-row="true">
	<tr>
		<td>Test ID</td>
		<td>검증</td>
		<td>기대</td>
	</tr>
	<tr>
		<td>`TST-AGT-201`</td>
		<td>SINGLE Profile topology</td>
		<td>Agent Subgraph 1개</td>
	</tr>
	<tr>
		<td>`TST-AGT-202`</td>
		<td>THREE Profile topology</td>
		<td>서로 다른 책임 계약의 Agent Subgraph 3개</td>
	</tr>
	<tr>
		<td>`TST-AGT-203`</td>
		<td>SIX Profile topology</td>
		<td>전문 Agent Subgraph 6개</td>
	</tr>
	<tr>
		<td>`TST-AGT-204`</td>
		<td>Agent Local State isolation</td>
		<td>invocation 종료 후 다음 호출에 임시 candidate/repair state 자동 승계 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-205`</td>
		<td>Parent/Child state projection</td>
		<td>허용 필드만 입력·Typed Result만 반환</td>
	</tr>
	<tr>
		<td>`TST-AGT-206`</td>
		<td>bounded repair loop</td>
		<td>Schema Repair 최대 1, Semantic Revision 계약 상한 준수</td>
	</tr>
	<tr>
		<td>`TST-AGT-207`</td>
		<td>direct agent call prohibition</td>
		<td>Agent→Agent 직접 Edge 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-208`</td>
		<td>write boundary</td>
		<td>Agent Subgraph의 MCP/Google Write 직접 호출 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-209`</td>
		<td>checkpoint authority</td>
		<td>Local Checkpoint로 Approval/Execution 사실 확정 불가</td>
	</tr>
	<tr>
		<td>`TST-EVAL-210`</td>
		<td>E06-B replay</td>
		<td>동일 `CONTEXT_READY_V1` / `context_snapshot_id`를 B1/B2/B3에 주입하고 MCP Read Tool 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-211`</td>
		<td>Prompt Slot Key</td>
		<td>`failure_reason_code`가 Runtime Slot Key에 포함되지 않고 Failure Block assembly metadata로만 사용</td>
	</tr>
	<tr>
		<td>`TST-EVAL-212`</td>
		<td>Semantic parity</td>
		<td>E06 후보의 `prompt_semantic_bundle_version`과 책임 coverage 일치</td>
	</tr>
	<tr>
		<td>`TST-EVAL-213`</td>
		<td>Environment lock</td>
		<td>비교 후보의 `evaluation_environment_hash`가 의도한 독립변수 외 조건에서 동일</td>
	</tr>
	<tr>
		<td>`TST-HANDOFF-214`</td>
		<td>Handoff fidelity</td>
		<td>Required Field·Evidence ID·Constraint 보존 및 contradiction introduction 측정</td>
	</tr>
	<tr>
		<td>`TST-AGT-215`</td>
		<td>Tool Route authority</td>
		<td>`ToolRoutePlanV2` 생성 이후 downstream Tool 재선택·임의 변경 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-216`</td>
		<td>IN/OUT separation</td>
		<td>Retrieval은 IN Route만, Planning은 OUT Route만 소비</td>
	</tr>
	<tr>
		<td>`TST-AGT-217`</td>
		<td>Node projection minimization</td>
		<td>Node 선언 입력 외 State 필드 전달 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-218`</td>
		<td>Local/Main boundary</td>
		<td>Query candidate·Page Token·RAG score·LLM candidate의 Main State 승격 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-219`</td>
		<td>Upstream revision invalidation</td>
		<td>Route/Retrieval/Analysis revision 시 downstream stale State 재사용 0</td>
	</tr>
	<tr>
		<td>`TST-RET-220`</td>
		<td>Run-scoped RAG</td>
		<td>Fetch 결과 전체를 Evidence 선정 없이 Analysis/Planning에 전달 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-221`</td>
		<td>RunInput authority</td>
		<td>`entry_mode`·`user_request`·`selected_resource_refs`가 Main State 기준점으로 보존되고 downstream 임의 변경 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-222`</td>
		<td>Artifact/Signal separation</td>
		<td>confirmation·route reconsideration 미완결 candidate가 공식 Artifact field에 저장되는 경우 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-223`</td>
		<td>Request revision invalidation</td>
		<td>RequestIntent revision 변경 시 Route 이하 downstream stale State 재사용 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-224`</td>
		<td>Tool Route internal responsibility</td>
		<td>Resource·Effect 판단과 Registry binding이 분리되고 unregistered Tool 생성 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-225`</td>
		<td>Analysis conditional routing</td>
		<td>`analysis_requirement=NONE` Answer 요청의 불필요 Work Analysis 호출 0; 단순 ACTION 자체만으로 Analysis 강제 0; TASK/CALENDAR CREATE Policy Precondition은 우회 0</td>
	</tr>
	<tr>
		<td>`TST-AGT-226`</td>
		<td>Review discriminated union</td>
		<td>`PASS+confirmation`, `CONFIRM without confirmation`, `BLOCK without blockers` 표현 가능 상태 0</td>
	</tr>
</table>

## 21. Runtime E2E Canonical Contract 회귀

### 21.1 Cancel

- Version conflict 또는 같은 `command_id`의 다른 Hash에서는 Approval·Plan·Action 변경 0.
- 취소 수락 후 신규 Claim·Google Write 0.
- 미실행 `PROPOSED | MODIFIED | APPROVED | EXPIRED` Action은 `CANCELLED`; ACTIVE Approval은 REVOKED; 새 Attempt·Verification 0.
- `EXECUTING` 취소는 결과 확정 전 상태를 덮어쓰지 않는다.
- `UNKNOWN_RESULT` 취소는 Run `RECOVERY_REQUIRED`; blind resend 0.
- 일부 Write 성공 후 취소는 Run `CANCELLED`, result_kind `PARTIAL`, rollback 0.

### 21.2 Runtime API Trust Boundary

- 같은 `command_id + canonical request hash` replay는 기존 결과 반환.
- 같은 `command_id + 다른 canonical hash`는 `409`, Domain mutation 0.
- Browser 제공 `request_hash`, `approval_id`, idempotency key, source snapshot, actor identity를 authority로 사용하지 않음.
- confirm/cancel/resume/prepare-retry/resolve-recovery의 Versioned Request Schema와 state precondition Contract Test.
- arbitrary resume payload 차단.

### 21.3 Insufficient Data Guard

- required safety/POLICY issue → `BLOCKED`.
- required USER issue → `NEEDS_CONFIRMATION`.
- required GOOGLE issue + budget → `NEEDS_MORE_DATA`/`RETRIEVE_MORE`.
- budget exhausted + evidence-supported read-only → `PARTIAL`.
- Write 필수 Target/Argument/Evidence 부족은 PARTIAL로 우회하지 않음.
- SINGLE/THREE/SIX 동일 fixture에서 동일 semantic route 판정.

### 21.4 MISMATCH Recovery

- `MISMATCH` 기록 후 Run `RECOVERY_REQUIRED`, 기존 Verification append-only 유지.
- `ACCEPT_PARTIAL`은 추가 Write 0, 미실행 Action `CANCELLED`, Run `COMPLETED` + result_kind `PARTIAL`.
- `CREATE_CORRECTIVE_PLAN`은 Run `PLANNING`, 새 Plan Revision, 기존 MISMATCH Action·Approval·Attempt 재사용 0.
- 교정 Write는 새 Approval → Claim → Attempt → Verification 필요.

### 21.5 Delivery Certainty Failure Injection

- validation/preflight/dispatch 전 확정 실패 → `NOT_SENT`; FAILED 가능.
- dispatch 이후 Timeout → `MAY_HAVE_BEEN_SENT`; `UNKNOWN_RESULT`.
- 5xx에서 미전달 보장 없음 → `UNKNOWN_RESULT`.
- response loss → `SENT_RESPONSE_LOST`; `UNKNOWN_RESULT`.
- MCP process exit에서 dispatch 여부 불명 → `UNKNOWN_RESULT`.
- 모든 UNKNOWN_RESULT case에서 새 Attempt·blind resend 0.

## 22. Frontend Main UI 회귀 계약

이 절의 테스트는 `01-A v2.17`, `02 UI·UX v2.13`의 Frontend 구현 계약을 추적한다. 기존 Safety, Verification Diff, `UNKNOWN_RESULT`, Recovery, Chrome/Edge, Sanitization 회귀를 대체하거나 제거하지 않는다.

<table fit-page-width="true" header-row="true">
	<tr>
		<td>Test ID</td>
		<td>계층</td>
		<td>검증 계약</td>
	</tr>
	<tr>
		<td>`TST-UI-201`</td>
		<td>Component</td>
		<td>Header는 제품명·정중앙의 비대화형 Google 연결 chip·현재 계정·Settings를 표시하고 개발 Runtime/Node/Profile 문자열을 Main에 노출하지 않는다.</td>
	</tr>
	<tr>
		<td>`TST-UI-202`</td>
		<td>Component</td>
		<td>Desktop 3 panel: Left Resource, Center Viewer+Chat, Right Conversation+Recent Execution의 정보 구조와 collapse 순서를 검증한다.</td>
	</tr>
	<tr>
		<td>`TST-UI-203`</td>
		<td>Component</td>
		<td>Gmail/Tasks/Calendar 탭, 검색/필터, compact resource row, selected/hover/focus/disabled, 긴 문자열 ellipsis와 keyboard navigation을 검증한다.</td>
	</tr>
	<tr>
		<td>`TST-UI-204`</td>
		<td>Integration</td>
		<td>Gmail·Tasks UI visible page 20과 Agent Retrieval page size 20의 독립 계약을 검증한다. Gmail은 intermediate token-only traversal과 visible target metadata hydration, 이미 hydrate한 page 재방문 Provider 호출 0을 검증한다. Tasks는 Provider 최대 100개 batch를 UI 20개 page로 slice하고 100개+continuation이면 최초 1..5 page만 노출하며 알려진 마지막 page에서만 다음 batch를 append한다. Local API continuation을 UI page number나 Provider token으로 해석하지 않고 조건 변경·수동 Refresh에서 cache를 무효화한다. Calendar Month View는 visible grid terminal materialization을 사용하고 numeric pagination을 생성하지 않는다.</td>
	</tr>
	<tr>
		<td>`TST-UI-205`</td>
		<td>Integration</td>
		<td>Tasks badge는 미완료 기본 scope의 batch terminal/continuation 상태를 따르고 terminal 도달 시 exact total을 확정한다. Calendar tab에는 numeric badge가 없으며 startup·Calendar refresh에서 Calendar Count Read를 호출하지 않는다. Gmail은 실제 exact count가 확인된 경우만 exact badge로 표시하고 추정치를 exact로 표시하지 않는다. Frontend 전체 Page 순회·hard code count는 금지한다.</td>
	</tr>
	<tr>
		<td>`TST-UI-206`</td>
		<td>Integration</td>
		<td>Resource row click은 Focus Viewer만 갱신하고 checkbox는 다중 선택 Context 집합만 변경함을 검증한다. 선택 집합이 있으면 Composer Context Summary에 사용자 의미 label과 선택 수를 표시하고, 중복 없는 선택 ID 전체로 `RESOURCE_SELECTED`가 최신 상세 조회를 시작함을 검증한다. 선택 집합이 없으면 `AGENT_SEARCH`를 검증한다.</td>
	</tr>
	<tr>
		<td>`TST-UI-207`</td>
		<td>Integration</td>
		<td>선택 없는 자연어 요청은 `AGENT_SEARCH`, Quick Action은 Agent 요청이며 Google Write를 직접 호출하지 않음을 검증한다.</td>
	</tr>
	<tr>
		<td>`TST-UI-208`</td>
		<td>Component</td>
		<td>Viewer와 Approval detail은 실제 REST/SSE Projection의 필드만 표시하며 fake count/detail/approval data가 없음을 검증한다.</td>
	</tr>
	<tr>
		<td>`TST-UI-209`</td>
		<td>Component</td>
		<td>Inline Approval의 approve/modify/reject, detail expand, pending/submitting/completed 상태와 duplicate click 방지를 검증한다.</td>
	</tr>
	<tr>
		<td>`TST-UI-210`</td>
		<td>Integration</td>
		<td>Conversation 새로 만들기·검색·선택 시 Center 복원과 Recent Execution의 Projection 조건부 표시/Empty State를 검증한다.</td>
	</tr>
	<tr>
		<td>`TST-UI-211`</td>
		<td>Component</td>
		<td>Loading/Empty/Error, keyboard, focus, disabled, 반응형 Right→Left collapse, Chat Input과 Approval 접근성을 검증한다.</td>
	</tr>
	<tr>
		<td>`TST-UI-212`</td>
		<td>Integration</td>
		<td>refresh, SSE disconnect/reconnect, cursor/snapshot 복구가 Domain 실패 또는 Write 재실행으로 오인되지 않음을 검증한다.</td>
	</tr>
	<tr>
		<td>`TST-UI-213`</td>
		<td>Regression</td>
		<td>Browser P0에서 native Window Control을 기능으로 호출하지 않고 Settings/Diagnostics와 기존 사용자 설정을 보존함을 검증한다.</td>
	</tr>
</table>

### Calendar·Tasks·Viewer 회귀

- Calendar Sidebar는 기본 Query가 사용자 Timezone 기준 현재부터 향후 90일이며 실제 Event 제목과 같은 날/날짜가 다른 시간 범위, All-day 형식을 검증한다.
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
- Claim DB Commit 전에 MCP Write 호출 0.

Attachment:
- Message Attachment Metadata와 실제 Download bytes 일치.
- Download bytes가 LLM Prompt/Context/Evidence/SQLite/Trace로 유입되지 않음.
- Stage 결과 filename/MIME/size/SHA-256이 실제 파일과 일치.
- Staging 파일 변조·만료·삭제 후 기존 Approval 실행 0.
- Draft CREATE/UPDATE·SEND 시 실제 MIME attachment와 승인 Descriptor가 일치.
- Attachment 포함 SEND에서도 SENT_LOOKUP, UNKNOWN_RESULT no-resend 계약 유지.

## PHASE 4~7 Dataset·Projection·Prompt·Runner 계약

### CanonicalCaseV7 / E2EProjectionV5

- Base-92는 60 CORE / 20 STRESS / 12 HOLDOUT을 유지한다.
- `CanonicalCaseV7`은 모든 Case에 명시적 `end_state_gold`를 가진다.
- `E2EProjectionV5`는 Canonical V7에서만 생성하며 hidden Planning args로 end-state를 추론하지 않는다.
- Product Episode 10개는 E2E 전용 Projection으로 분리하고 Base-92 headline denominator에 섞지 않는다.

### Prompt Runtime Input Gate

- Product Prompt assembler는 `prompt-runtime-input-contract-v1` allowlist만 직렬화한다.
- `gold`, `grader`, `expected_route`, `end_state_gold`, Holdout label, User Simulator `decision_script`가 Product Prompt로 들어가면 실패다.
- Repair/Revision은 `base_projection + candidate_output + normalized failure_record`만 받고 `allowed_change_scope` 밖 필드를 변경하면 실패다.

### PHASE 7 slot-aware grading

Tool Route 평가를 두 단계로 분리한다.

```text
RouteResourceCandidateV1
→ PRE_POLICY_SEMANTIC_ROUTE_GOLD
→ deterministic Registry Binding
→ PolicyPreconditionResolver
→ ToolRoutePlanV2
→ final route/trajectory grader
```

LLM candidate를 final ToolRoutePlanV2의 policy-precondition READ와 직접 비교하면 grader defect다.

### RequestIntent Gold review gate

`analysis_requirement`는 ACTION 여부만으로 `REQUIRED`가 되지 않는다. 단순 조회·직접 Action은 제품 계약상 `NONE`일 수 있고 duplicate/conflict 검사는 downstream effective analysis다. `CASE-CORE-002/003/005/006/008/055/058/059/060`은 PHASE 7 Gold review candidate다. `CASE-CORE-057`은 business-deadline 의미 때문에 human review 전 자동 수정하지 않는다.

### Planning default binding gate

`tasklist_id`, `calendar_id` 같은 default container ID를 LLM이 숨은 값으로 추측하면 실패다. 실제 Local model Planning pilot 전 다음 중 하나를 고정한다.

1. deterministic Plan/Argument Assembler가 default ID를 바인딩한다.
2. 또는 allowlisted `runtime_context/default_resource_bindings`를 Planning input에 명시한다.

### Manual style smoke

PHASE 7의 20 CORE × 2 문체 = 40 요청은 실제 Ollama/qwen benchmark가 아니다. Holdout 0, benchmark eligible=false로 기록한다. 실제 모델 DEV/Holdout 결과와 합치지 않는다.

## PHASE 7.5 Contract Correction Regression

- `CASE-CORE-002/003/005/006/008/055/058/059/060`의 RequestIntent `analysis_requirement=NONE`을 검증한다.
- `CASE-CORE-057`은 business-deadline 의미 때문에 human review 결과 `REQUIRED` 유지다.
- `CORE-058`처럼 Request analysis는 NONE이어도 Calendar CREATE policy conflict precondition 때문에 `effective_analysis_required=true`가 될 수 있다.
- Tool Route Slot grader는 `PrePolicyToolRouteGoldV1`을 사용하고 final route/trajectory grader만 `ToolRoutePlanV2`를 사용한다.
- Base-92 92건 모두 pre-policy Gold가 존재해야 한다.
- Task UPDATE Planning Gold의 required `tasklist_id` 누락 0건을 검증한다.
- default `tasklist_id/calendar_id`는 deterministic resolver가 bind하며 Planning LLM hidden guess 0건을 검증한다.
- Dataset `rebuild-v1.17-r8.6-phase7.5-contract-correction`, Projection `projection-v1.1-r8.6-phase7.5`의 92 Canonical + 736 Projection source equality를 검증한다.

## 2026-08-15 Retrieval Contract Regression

위 Test는 12가 새 제품 의미를 만들기 위한 것이 아니라 `05 v2.13 / 06 v7.17 / 15 v1.23`의 Canonical 계약을 검증하기 위한 회귀 Gate다.

필수 결과:

| Case | 기대 |
|---|---|
| Initial SEARCH typed semantic value | PASS |
| CHANGED SEARCH upsert | PASS |
| CHANGED SEARCH remove | PASS |
| name-only delta | FAIL |
| unsupported constraint | FAIL |
| required constraint 제거 | FAIL |
| upsert/remove 동일 kind 충돌 | FAIL |
| unchanged SEARCH | FAIL |
| Provider-native query leakage | FAIL |
| raw continuation Prompt 유입 | FAIL |
| 동일 semantic input → 동일 query hash | PASS |
| NEXT_PAGE handle authority | PASS |
| DETAIL_FETCH bounded candidate authority | PASS |
| raw user_request planner authority 재주입 | FAIL |
| QueryAttempt summary를 실행 권위로 사용 | FAIL |
| RetrievalStateV1에 V2 계약 덮어쓰기 | FAIL |
## Prompt Runtime Contract Closure Gate (2026-08-18)

PHASE 6 historical `0.9.0-r8.6-phase6`의 30 Slot 정적 검증 결과는 재현 이력으로 보존한다. 현재 Runtime-aligned candidate는 `0.9.1-r8.6-runtime-closure / semantic-r8.6-v3`다.

현재 Gate:

```text
Canonical required Active PromptRef
= Production Runtime caller
= Manifest
= Source
= Assembled
= prompt-runtime-input-contract-v1
= 27

Retired = 3
- request_understanding.classify.revise
- retrieval.assess_sufficiency.revise
- work_analysis.analyze.reassess
```

검증 규칙:

- Retired PromptRef는 Active set/Manifest/Runtime caller에 다시 등장하면 실패다.
- `retrieval.select_evidence` Prompt input은 `request_intent + ranked_segments`만 허용하며 raw `user_request`를 root field로 받으면 실패다.
- Retrieval Repair/Revision은 각 Node의 실제 Output Type과 일치해야 한다: `RetrievalQueryPlanV2`, `EvidenceSelectionResultV2`, `SufficiencyResultV2`.
- Active PromptRef set equality, source/assembled 존재, content/assembled hash, Input Contract 연결을 정적으로 검증한다.
- 아직 Model DEV/Holdout/Safety Gate를 통과하지 않았으므로 `RUNTIME_ACTIVE`로 승격하지 않는다.

