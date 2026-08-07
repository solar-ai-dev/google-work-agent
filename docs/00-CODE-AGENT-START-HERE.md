# Google Work Agent · Code Agent Start Here

> **Source Pack:** R7 · 2026-08-07  
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
→ state-transition-contract-v1.3.md
→ 06-agent-workflow.md
→ 07-tool-mcp-internal-interface.md
→ 12-test-design.md
→ 15-agent-capability-failure-prompt-contract.md
→ 01-IMPLEMENTATION-AND-EXPERIMENT-CHECKLIST.md
```

Retrieval·Prompt·평가 작업에서는 `05`, `11`, `13`, 상태 전이 테스트 매트릭스까지 반드시 읽는다.

## 2. 기준점 우선순위

```text
PRD·정책
→ Domain 상태 전이·DB Constraint
→ Tool Registry·Interface
→ Retrieval·Workflow 제품 계약
→ Agent Capability·Failure·Prompt 공통 계약
→ Observability·Test·Evaluation
→ 개별 Prompt·Dataset Artifact
```

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

- `docs/` 아래 Source Document는 26개다. `0001` Schema v1.2 baseline과 `0002` SEND·DELETE Effect Migration을 포함한다.
- `SOURCE-PACK-MANIFEST.json`은 파일 Hash와 역할을 기록한다.
- `SHA256SUMS.txt`는 배포·전달 무결성 검사용이다.
- R7 Pack은 2026-08-07 Notion의 승인형 SEND·DELETE, Clarification, Transaction·Recovery 정합성 계약을 반영한다.

## 8. R7 추가 구현 불변조건

- Google/MCP/LLM 외부 호출을 SQLite Write Transaction 안에서 기다리지 않는다.
- 외부 호출 전 Snapshot Transaction과 호출 후 저장 Transaction을 분리하고, 두 번째 Transaction에서 `expected_version`, Action·Attempt 상태를 재검사한다.
- Run Recovery 진입·해제는 `RequireRecovery`·`ResolveRecovery` Domain Command를 거친다. Repository 직접 상태 setter는 금지한다.
- 승인형 Effect는 `READ | CREATE | UPDATE | SEND | DELETE`다.
- `gmail_send`, Task 완료 UPDATE, Calendar Event DELETE, Calendar 참석자 UPDATE는 정확한 Target·Arguments와 사용자 승인을 요구한다.
- Gmail Message·Thread 원문 삭제, Task 삭제, 반복 Event 전체 일괄 수정은 금지한다.
- 모호성은 실제 발견된 단계에서 `NEEDS_CONFIRMATION`으로 보내고 `request_understanding.clarify`가 후보·차이·선택지를 생성한다.
