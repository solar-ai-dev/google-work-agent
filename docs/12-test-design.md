# 12. Google Work Agent · 테스트 설계서

> **문서 기준:** `01 PRD v2.3`, `01-A v2.2`, `01-B v2.2`, `02 UI·UX v2.2`, `03 Architecture v2.5`, `04 Database v1.8`, `05 Retrieval v2.0`, `06 Workflow v5.4`, `07 Interface v2.3`, `08 Sequence v2.3`, `09 Security`, `10 Infrastructure v2.3`, `11 Observability v2.3`, Domain 상태 전이 계약 v1.3과 테스트 매트릭스 v1.3을 기준으로 한다.
>
> **상태:** Draft v2.4 · **OS:** Windows 11 x64 · **Browser:** Chrome·Edge

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
- Task 중복·유사·기한 없음·기한 임박
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

- 6개 Agent 중 필요한 단계만 호출
- Peer-to-Peer 금지
- LLM Call 최대 8
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
