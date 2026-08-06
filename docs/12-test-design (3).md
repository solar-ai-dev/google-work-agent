# 12. Google Work Agent · 테스트 설계서

> **상태:** Draft v2.3 · **OS:** Windows 11 x64 · **Browser:** Chrome·Edge

## 1. 계층

```text
Unit → Contract → Integration → Component → E2E → Failure Injection → Installer·Release
```

모든 상태 전이는 허용 Edge와 금지 Edge를 검증한다.

## 2. Test ID·Traceability

```text
TST-<AREA>-<NNN>
AREA = DOM DB API SSE UI WF AGT RET LLM MCP GGL SEC INF OBS E2E PERF REL
```

Case 필드:

```text
test_id
source_contract
requirement_ids
case_id?
fixture_snapshot_id?
user_prompt_id?
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
```

## 5. Fixture

합성 Gmail·Tasks·Calendar만 사용한다. Snapshot은 `fixture_snapshot_id`와 Relation Manifest를 가진다.

필수 경계:
- Gmail 긴 Thread·외부 주소·Prompt Injection
- Task 중복·유사·기한 없음·기한 임박
- Calendar Busy·Tentative·Free·OOO·Focus·DST
- Write 정상·정규화 차이·Mismatch
- 401·403·404·409·429·5xx·Timeout·응답 유실

User Prompt Catalog 필드: `user_prompt_id`, `intent_family`, `entry_mode`, `language`, `paraphrase_group_id`, `case_id`.

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
- `/health/live`, `/health/ready`, `/api/v1/runtime` 책임 분리와 Credential·API Key·Ollama 누락의 Core Readiness 비영향
- SSE monotonic Event ID·Last-Event-ID·Snapshot Fallback
- Agent Structured Output Version·Enum·Repair 1회
- MCP Tool Registry·Schema·Effect·Scope·Retryability
- Observability Envelope·16 KiB·Sanitization

## 8. Multi-Agent·Prompt

- 6개 Agent 필요한 단계만 호출
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

## 11. Security

- Loopback only, Host·Origin·DNS Rebinding
- Bootstrap 1회·60초·재사용 차단
- Session restart invalidation
- Keyring Plain File Fallback 금지
- PATH Hijack·Shell Injection·Signature·Hash·Schema
- Prompt Injection·승인 이후 Argument 변경 차단
- Diagnostic Secret Leakage 0

## 12. Installer·Upgrade

- User install, no admin, no Python·Node
- Production·distributed test Signature
- API_ONLY without Ollama
- LOCAL_CAPABLE missing Ollama·Model diagnosis and external install guidance; app-managed install/start/stop/update forbidden
- Upgrade Backup·Migration·Safe Mode·Downgrade block
- Default uninstall preserves DB·Backup·Settings and deletes OAuth·LLM credentials

## 13. Observability

- Correlation IDs
- case·fixture·user prompt·prompt·model·graph link
- Log Rotation·Trace 30일·Audit 90일
- Audit append-only Repository
- Sanitization Canary Leak 0

## 14. Coverage

```text
Domain allowed·forbidden edges 100%
Policy·Forbidden Tool 100%
Approval·Execution·Verification branches 100%
Python line 80%, branch 75%
React statement 80%, branch 70%
Secret leakage 0
```

## 15. Release Block

미승인 Write, 금지 Tool, Hash 변경, Verification 누락, 중복 Write, UNKNOWN_RESULT 재실행, FAILED 직접 실행, READ 승인 Row, Retriever MCP 호출, Open Run 중복, Secret Leak, Public Bind, Signature·Migration·Backup 실패, Chrome·Edge 실패, API_ONLY Ollama 의존 중 하나라도 있으면 차단한다.

## 16. r3 필수 회귀 ID

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

User Prompt Catalog 필드는 `user_prompt_id`, `case_id`, `intent_family`, `entry_mode`, `language`, `paraphrase_group_id`를 사용한다.
