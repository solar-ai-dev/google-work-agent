# Google Work Agent · Code Agent Start Here

> **Source Pack:** R8.4 Claim V2·Attachment Canonical · 2026-08-09  
> **목적:** 구현·검수 Agent가 프로젝트 계약과 실제 소스의 차이를 빠르게 파악하고, 안전 경계를 훼손하지 않은 채 작업하도록 한다.

## 1. 최초 읽기 순서

작업 전 최소 다음 순서로 읽는다.

```text
00-google-work-agent-overview.md
→ 00-PROJECT-SOURCE-GUIDE.md
→ 01-requirements-prd.md
→ 01-b-policy-definition.md
→ 03-system-architecture.md
→ 04-domain-database-design.md
→ 0001_initial.sql
→ 0002_action_effect_send_delete.sql
→ state-transition-contract-v1.4.md
→ 06-agent-workflow.md
→ 07-tool-mcp-internal-interface.md
→ 12-test-design.md
→ 15-agent-capability-failure-prompt-contract.md
→ 01-IMPLEMENTATION-AND-EXPERIMENT-CHECKLIST.md
```

Retrieval·Prompt·평가 작업에서는 `05`, `11`, `13`, 상태 전이 테스트 매트릭스까지 반드시 읽는다.

## 2. 기준점 우선순위

문서 번호 순서가 아니라 책임 소유권을 따른다.

```text
01 PRD 제품 범위
01-B Policy 안전·승인
03 Architecture 경계
04 Domain·DB + State Contract 영속 사실·상태 전이
05 Retrieval / 06 Workflow / 07 Interface 전문 계약
15 Capability·Failure·Prompt 정규화
11 Observability / 12 Test / 13 Evaluation 소비·검증
```

하위 문서는 상위/전문 권위 문서의 안전 계약을 완화할 수 없다.

실제 구현 작업에서는 저장소의 소스·테스트·Migration이 현재 구현 상태의 기준점이다. 문서와 소스가 충돌하면 임의로 하나를 선택하지 말고 차이를 기록한다.

## 3. 작업 시작 전 조사

1. `git status`, 현재 Branch, 최근 Commit을 확인한다.
2. `pyproject.toml`, `README`, `src/`, `tests/`, `migrations/`, `config/`를 조사한다.
3. Domain, Application, Ports, Adapters의 실제 책임과 의존성을 파일별로 정리한다.
4. 문서에 있는 Command·Tool·상태가 실제 코드와 테스트에 존재하는지 확인한다.
5. 파일 수정 전 변경 범위, 불변조건, 검증 명령을 제시한다.

## 4. 절대 불변조건

- Supervisor는 결정적 Router다.
- LLM Agent는 Google API·MCP Write를 직접 호출하지 않는다.
- 실제 Query와 Tool Arguments는 결정적 코드가 검증·생성한다.
- 승인 후 Tool·Arguments·Target Resource를 LLM이 변경하지 않는다.
- Write 성공은 응답만으로 확정하지 않는다. CREATE·UPDATE는 GET 비교, DELETE는 대상 부재/삭제 상태, SEND는 Sent 결과 조회로 검증한다.
- `UNKNOWN_RESULT`에서 새 Write Attempt를 만들지 않는다.
- Verification `MISMATCH`에서 자동 수정·Rollback하지 않는다.
- Prompt·Completion·Credential·Google 원문 전체를 Trace에 저장하지 않는다.
- E06-A에서 SINGLE/THREE를 SIX exact node route와 비교해 오답 처리하지 않는다.
- Product Prompt에 evaluator/grader/gold 정답 정보를 넣지 않는다.

## 5. Agent·Prompt 작업 규칙

- Schema Repair, Semantic Revision, Workflow Redirection, 결정적 Recovery를 구분한다.
- 401·429·5xx·Timeout에 LLM Repair를 사용하지 않는다.
- 실패별 Prompt는 Base Prompt와 Failure Block을 조립한다.
- Node DEV·Node HOLDOUT·Safety Gate를 통과한 Prompt만 Runtime에 활성화한다.
- `AGENT_SEARCH`의 저신뢰 후보를 자동 확정하지 않는다.
- `RESOURCE_SELECTED`는 사용자 선택 ID를 재검색하지 않고 상세 GET한다.

## 6. 구현 완료 검증

최소 다음을 수행한다.

```text
pytest tests/unit -q
pytest tests/integration -q
pytest -q
ruff check src tests
ruff format --check src tests
```

저장소에 별도 명령이 정의돼 있으면 해당 명령을 우선한다. 안전·상태 전이·Tool Contract 실패가 하나라도 있으면 완료로 판정하지 않는다.

## 7. 이 Source Pack의 범위

- Web GPT Canonical Pack은 **25개 파일**이며, Repository 전체 문서 Pack은 여기에 설명 문서 `00-A/B/C` 3개를 더한 **28개 파일**이다.
- 현재 Pack에는 별도 `SOURCE-PACK-MANIFEST.json` 또는 `SHA256SUMS.txt`를 포함하지 않는다. 무결성 검사가 필요하면 Repository CI에서 생성한다.
- R8.3 Runtime E2E Pack은 2026-08-09 Agent Subgraph 계약에 더해 Cancel·API Trust Boundary·Insufficient Data Guard·MISMATCH Recovery·Write Delivery Classification을 반영한다.

## 8. Write·Recovery 구현 불변조건

- Google/MCP/LLM 외부 호출을 SQLite Write Transaction 안에서 기다리지 않는다.
- 외부 호출 전 Snapshot Transaction과 호출 후 저장 Transaction을 분리하고, 두 번째 Transaction에서 `expected_version`, Action·Attempt 상태를 재검사한다.
- Run Recovery 진입·해제는 `RequireRecovery`·`ResolveRecovery` Domain Command를 거친다. Repository 직접 상태 setter는 금지한다.
- 승인형 Effect는 `READ | CREATE | UPDATE | SEND | DELETE`다.
- `gmail_send`, Task 완료 UPDATE, Google Task DELETE, Calendar Event DELETE, Calendar 참석자 UPDATE는 정확한 Target·Arguments와 사용자 승인을 요구한다.
- Gmail Message·Thread 원문 삭제와 반복 Event 전체 일괄 수정은 금지한다. Google Task 삭제는 정확한 Target·Arguments와 사용자 승인 후 허용되는 `DELETE`이며 Claim·GET_ABSENT Verification을 거친다.
- 모호성은 실제 발견된 단계에서 `NEEDS_CONFIRMATION`으로 보내고 `request_understanding.clarify`가 후보·차이·선택지를 생성한다.
## 9. Agent Subgraph 구현 기준

- Agent는 단순 LLM 함수나 wrapper node가 아니라 Parent Graph가 호출하는 LangGraph Subgraph다.
- 각 Agent는 invocation 범위 Local State만 갖고 장기 Memory를 만들지 않는다.
- `SINGLE_BASELINE=1`, `THREE_STAGE=3`, `SIX_ROLE_BASELINE=6` Agent Subgraph다.
- THREE 구현이 내부에서 기존 6개 전문 Agent 호출을 단순 묶는 wrapper라면 실험 후보로 인정하지 않는다.
- Agent 내부에는 Schema Validation과 계약상 허용된 bounded Repair/Revision loop를 둔다. 책임 수행에 필요한 결정적 Read Node도 포함할 수 있으나 LLM이 MCP를 직접 호출하지 않는다. 다른 Agent가 필요하면 disposition을 Parent에 반환한다.
- Acquisition은 `SourceFetchPlan`에서 Parent로 중간 종료하지 않고 같은 invocation 안에서 결정적 Read를 수행해 `AcquisitionResult`까지 반환한다.
- SINGLE은 Unified Agent 내부 self-review를 포함한다. E06-B는 `CONTEXT_READY_V1` 이후 B1/B2/B3만 비교한다.
- Domain·Approval·Claim·Execution·Verification·Recovery 코드는 Profile 간 공통이다.
- `agent_invocation_count`와 `llm_call_count`를 반드시 분리 계측한다.
- Prompt Runtime Slot Key는 `agent_role + subgraph_name + node_name + node_state + purpose + input_schema_version + output_schema_version`이다. `failure_reason_code`는 Base Prompt 선택 Key가 아니라 Failure-specific Instruction Block 조립 metadata다.
- E06-B는 `CONTEXT_READY_V1`의 동일 `context_snapshot_id`에서만 post-retrieval B1/B2/B3를 비교하며 Google Read는 0이어야 한다.


## Gold·Scoring 구현 주의

- `CanonicalCaseV5`와 `E2EProjectionV3`가 활성 Gold 계약이다.
- E06-A에서 `six_reference_route`로 SINGLE/THREE를 채점하지 않는다.
- Acquisition Gold의 Budget 수치는 ceiling이다. 더 적은 호출로 성공한 결과를 exact mismatch로 실패 처리하지 않는다.
- Product Prompt에 Gold·Grader·expected route를 주입하지 않는다.
- 활성 기준은 Grader Registry v0.4, Scoring Contract v1.1이다.
## 10. Runtime E2E 구현 기준

- Canonical DB target은 v1.4다. 기존 `0001`/`0002`는 이력으로 보존하고 Action `CANCELLED` CHECK 확장은 새 Migration으로 구현한다.
- Cancel Command의 Command Receipt/expected_version 판정 전에 Approval·Plan·Action을 변경하지 않는다.
- Browser 제공 `request_hash`, `approval_id`, idempotency key, source snapshot, actor identity를 authority로 사용하지 않는다.
- 모든 Profile은 05/06의 동일 insufficient-data Supervisor Guard를 사용한다.
- `MISMATCH` Action은 immutable이며 `ACCEPT_PARTIAL | CREATE_CORRECTIVE_PLAN` 외 임의 recovery choice를 만들지 않는다.
- Adapter는 `delivery_certainty`를 보존하며 dispatch 이후 Timeout을 무조건 미전달로 분류하지 않는다.
- Gmail SEND와 Calendar DELETE는 승인 → Claim Commit → Write → SENT_LOOKUP/GET_ABSENT Verification 전체 경로가 있어야 완료다.

## R8.4 구현 시작점

코드 수정 전 다음을 구현 기준으로 고정한다.

1. DB Schema v1.4는 `0003_action_cancelled.sql`까지 적용된 상태다. Claim V2/Attachment 때문에 추가 DB Migration을 만들지 않는다.
2. `ClaimContextV2`: approval hash와 execution hash 분리, HMAC-SHA-256, TTL, Service/MCP instance binding, 1회 Nonce, MCP 실제 arguments 재해시.
3. Gmail Attachment READ: metadata/detail → `get_gmail_attachment` → Download Stream. LLM 입력 금지.
4. Gmail Attachment WRITE: Local stage → Descriptor/SHA-256 → Approval → Claim V2 → MCP bytes 재검증 → MIME Draft/SEND.
5. 기존 WRITE 순서 `Approval → Claim Commit → external MCP/Google → Verification`을 유지한다.
