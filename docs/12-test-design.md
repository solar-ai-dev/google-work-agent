# 12. Google Work Agent · 테스트 설계서

> **문서 기준:** `01 PRD v2.8`, `01-A v2.9`, `01-B v2.8`, `02 UI·UX v2.8`, `03 Architecture v3.0`, `04 Database v1.12`, `05 Retrieval v2.6`, `06 Workflow v6.1`, `07 Interface v2.10`, `08 Sequence v3.2`, `09 Security v2.5`, `10 Infrastructure v2.7`, `11 Observability v2.9`, `15 Agent Capability·Failure·Prompt v1.5`, Domain 상태 전이 계약 v1.4와 테스트 매트릭스 v1.4을 기준으로 한다.
>
> **상태:** Draft v3.5 · **기준일:** 2026-08-10 · **OS:** Windows 11 x64 · **Browser:** Chrome·Edge

## 1. 목적과 계층

이 문서는 제품 계약과 안전 회귀를 검증한다. Model·Prompt·Retrieval·Graph 품질 비교는 `13. 평가·실험 설계서`가 소유한다.

```text
Unit → Contract → Integration → Component → E2E → Failure Injection → Installer·Release
```

모든 상태 전이는 허용 Edge와 금지 Edge를 검증한다.

## 2. Test ID·Traceability

```text
TST-<AREA>-<NNN>
AREA = DOM DB API SSE UI WF AGT RET LLM MCP GGL SEC INF OBS E2E PERF REL EVAL
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
FakeGoogleGateway
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
- Revision 2, Repair 1, Additional Acquisition 2
- Retriever MCP 직접 호출 금지
- Prompt Registry Key 검증
- Supervisor는 Node만 Routing하고 선택된 Agent·Application Node가 PromptRef를 확정
- LLM Router·Model의 Prompt 선택 금지
- Agent별 단일 Prompt 금지
- Repair·Revision 별도 Prompt ID
- Prompt Manifest Version·Hash·Schema 검증
- `ORACLE` Node Run과 `LIVE` Handoff Run 분리
- `RESOURCE_SELECTED`에서 불필요한 Workspace Search 금지
- `ANSWER_ONLY`에서 `planning.draft_plan` 미호출
- Review 없음·있음 Candidate가 Domain·Policy 코드를 공유

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
|---|---|---|
| LLM | Timeout·Invalid Output | Repair·Fallback 상한 |
| Google Read | 401·429·5xx | Reauth·제한 Retry |
| Google Write | 전달 전 실패 | FAILED |
| Google Write | 응답 유실 | UNKNOWN_RESULT |
| Verification | 404·Timeout | 즉시 실패 확정 금지 |
| SQLite | Busy·Disk Full | Write 전 차단 |
| Audit | 저장 실패 | 안전 Command 실패 |
| MCP | Exit | 1회 Restart 또는 UNKNOWN_RESULT |
| SSE | Loss | Domain 계속·UI 복원 |
| Launcher | Shutdown Timeout | Recovery Marker |
| Experiment Runner | Budget 초과 | 새 Item 시작 중단·Partial 표시 |
| Grader | Schema·Version 불일치 | 후보 판정 중단 |

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

미승인 Write, 금지 Tool, Hash 변경, Verification 누락, 중복 Write, UNKNOWN_RESULT 재실행, FAILED 직접 실행, READ 승인 Row, Retriever MCP 호출, Open Run 중복, Secret Leak, Public Bind, Signature·Migration·Backup 실패, Chrome·Edge 실패, API_ONLY Ollama 의존 중 하나라도 있으면 차단한다.

Experiment Runner는 Dataset·Projection 참조 오류, Holdout 누수, 의도 외 Config Diff, Grader Version 누락, Budget 미설정 중 하나라도 있으면 실험 결과 생성을 차단한다.

## 17. 필수 회귀 ID

| Test ID | 계약 |
|---|---|
| `TST-DB-101` | Command Receipt와 Domain 변경 원자 Commit |
| `TST-API-101` | 같은 Command ID·같은 Hash 기존 결과 반환 |
| `TST-API-102` | 같은 Command ID·다른 Hash 409 차단 |
| `TST-SEC-101` | Bootstrap Endpoint는 기존 Session 없이 Secret으로만 성공 |
| `TST-SEC-102` | 일반 API는 Local Session 없이 차단 |
| `TST-SEC-103` | OAuth Token 원문 FastAPI·Log·DB 미노출 |
| `TST-MCP-101` | 유효 Claim Token만 Write 허용 |
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
| `TST-EVAL-106` | Write 승인·Claim·GET·End-state Strict 판정 |
| `TST-EVAL-107` | Grader Version·Human Calibration·Dataset Issue 분리 |
| `TST-EVAL-108` | Scenario Family·Fixture Relation Family Holdout 누수 0 |

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
- `AUTH_REQUIRED`를 Acquisition Revision으로 해결하려 하지 않는다.
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
- DELETE: Calendar Event만 허용 + GET_ABSENT 확인.
- Task 완료·Calendar 참석자 변경: 정확한 Target과 승인된 UPDATE.
- Gmail 원문 삭제·반복 Event 전체 일괄 수정: Tool 제안/실행 0.
- Google Task DELETE: 정확한 Task Target → 승인 → Claim V2 → `tasks_delete_task` → `GET_ABSENT` Verification. 승인/Claim/검증 우회 0.
- `ClarificationQuestionV1`: 후보·차이·선택지·same-thread Resume.
- 문맥으로 해결된 요청과 `답장해줘` SEND 의도에 불필요 Clarification 0.
- 전체 Mailbox/무제한 Workspace 조회는 API 호출 전에 BLOCK.
- Calendar overlap 자체를 conflict로 오판하지 않는다.
## 20. Agent Subgraph 회귀 테스트

- Acquisition Agent는 LLM plan 후 같은 Subgraph invocation 안에서 결정적 Read Node를 실행하고 `AcquisitionResult` 반환 뒤 종료한다.
- SourceFetchPlan을 Parent에 반환해 invocation을 끝낸 뒤 같은 Local State로 재진입하는 경로는 금지한다.
- `SINGLE_BASELINE`은 Planning 결과에 대해 같은 Unified Agent 내부 self-review 책임을 수행한다.
- E06-B는 `CONTEXT_READY_V1` 이후만 실행하며 Google Read 호출 수가 0이어야 한다.
- E06-B 후보는 `B1_INTEGRATED=1`, `B2_STAGED=2`, `B3_SPECIALIZED=3` post-retrieval Agent Subgraph topology를 가져야 한다.

| Test ID | 검증 | 기대 |
|---|---|---|
| `TST-AGT-201` | SINGLE Profile topology | Agent Subgraph 1개 |
| `TST-AGT-202` | THREE Profile topology | 서로 다른 책임 계약의 Agent Subgraph 3개 |
| `TST-AGT-203` | SIX Profile topology | 전문 Agent Subgraph 6개 |
| `TST-AGT-204` | Agent Local State isolation | invocation 종료 후 다음 호출에 임시 candidate/repair state 자동 승계 0 |
| `TST-AGT-205` | Parent/Child state projection | 허용 필드만 입력·Typed Result만 반환 |
| `TST-AGT-206` | bounded repair loop | Schema Repair 최대 1, Semantic Revision 계약 상한 준수 |
| `TST-AGT-207` | direct agent call prohibition | Agent→Agent 직접 Edge 0 |
| `TST-AGT-208` | write boundary | Agent Subgraph의 MCP/Google Write 직접 호출 0 |
| `TST-AGT-209` | checkpoint authority | Local Checkpoint로 Approval/Execution 사실 확정 불가 |
| `TST-EVAL-210` | E06-B replay | 동일 `CONTEXT_READY_V1` / `context_snapshot_id`를 B1/B2/B3에 주입하고 Google Read 0 |
| `TST-AGT-211` | Prompt Slot Key | `failure_reason_code`가 Runtime Slot Key에 포함되지 않고 Failure Block assembly metadata로만 사용 |
| `TST-EVAL-212` | Semantic parity | E06 후보의 `prompt_semantic_bundle_version`과 책임 coverage 일치 |
| `TST-EVAL-213` | Environment lock | 비교 후보의 `evaluation_environment_hash`가 의도한 독립변수 외 조건에서 동일 |
| `TST-HANDOFF-214` | Handoff fidelity | Required Field·Evidence ID·Constraint 보존 및 contradiction introduction 측정 |

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

이 절의 테스트는 `01-A v2.9`, `02 UI·UX v2.8`의 Frontend 구현 계약을 추적한다. 기존 Safety, Verification Diff, `UNKNOWN_RESULT`, Recovery, Chrome/Edge, Sanitization 회귀를 대체하거나 제거하지 않는다.

| Test ID | 계층 | 검증 계약 |
|---|---|---|
| `TST-UI-201` | Component | Header는 제품명·정중앙의 비대화형 Google 연결 chip·현재 계정·Settings를 표시하고 개발 Runtime/Node/Profile 문자열을 Main에 노출하지 않는다. |
| `TST-UI-202` | Component | Desktop 3 panel: Left Resource, Center Viewer+Chat, Right Conversation+Recent Execution의 정보 구조와 collapse 순서를 검증한다. |
| `TST-UI-203` | Component | Gmail/Tasks/Calendar 탭, 검색/필터, compact resource row, selected/hover/focus/disabled, 긴 문자열 ellipsis와 keyboard navigation을 검증한다. |
| `TST-UI-204` | Integration | Sidebar UI page size 10, 숫자 페이지, Page Token 순차 조회, cache 재방문, 조건 변경/수동 새로고침 cache 무효화를 검증한다. Retrieval page size 20과 분리됨을 포함한다. |
| `TST-UI-205` | Integration | Tasks는 미완료 Task 전체 `total_count`, Calendar는 현재부터 향후 90일 범위의 exact `total_count`를 표시하고, Frontend 전체 Page 순회·hard code가 없음을 검증한다. Gmail 추정 count는 exact badge로 표시하지 않는다. |
| `TST-UI-206` | Integration | Resource row click은 Focus Viewer만 갱신하고 checkbox는 다중 선택 Context 집합만 변경함을 검증한다. 선택 집합이 있으면 Composer Context Summary에 사용자 의미 label과 선택 수를 표시하고, 중복 없는 선택 ID 전체로 `RESOURCE_SELECTED`가 최신 상세 조회를 시작함을 검증한다. 선택 집합이 없으면 `AGENT_SEARCH`를 검증한다. |
| `TST-UI-207` | Integration | 선택 없는 자연어 요청은 `AGENT_SEARCH`, Quick Action은 Agent 요청이며 Google Write를 직접 호출하지 않음을 검증한다. |
| `TST-UI-208` | Component | Viewer와 Approval detail은 실제 REST/SSE Projection의 필드만 표시하며 fake count/detail/approval data가 없음을 검증한다. |
| `TST-UI-209` | Component | Inline Approval의 approve/modify/reject, detail expand, pending/submitting/completed 상태와 duplicate click 방지를 검증한다. |
| `TST-UI-210` | Integration | Conversation 새로 만들기·검색·선택 시 Center 복원과 Recent Execution의 Projection 조건부 표시/Empty State를 검증한다. |
| `TST-UI-211` | Component | Loading/Empty/Error, keyboard, focus, disabled, 반응형 Right→Left collapse, Chat Input과 Approval 접근성을 검증한다. |
| `TST-UI-212` | Integration | refresh, SSE disconnect/reconnect, cursor/snapshot 복구가 Domain 실패 또는 Write 재실행으로 오인되지 않음을 검증한다. |
| `TST-UI-213` | Regression | Browser P0에서 native Window Control을 기능으로 호출하지 않고 Settings/Diagnostics와 기존 사용자 설정을 보존함을 검증한다. |

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
