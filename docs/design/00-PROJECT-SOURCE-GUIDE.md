# Google Work Agent — Project Source Guide

## 목적

이 묶음은 설계 검토·구현 질의·실험/평가 검토에 사용하는 **Canonical 프로젝트 소스 25개**다. 공식 원본은 Notion이며 이 Markdown은 **2026-08-18 Prompt Runtime Contract Closure 및 Notion Canonical 정합화 이후 Export Snapshot**이다.

## 문서 권위·책임 소유 규칙

```text
제품 목표·범위          → 01 PRD
사용자 기능 동작        → 01-A Functional
안전·금지·승인 정책     → 01-B Policy
시스템 경계             → 03 Architecture
영속 사실·상태 전이     → 04 Domain·DB + State Contract + SQL Constraint
Retrieval 계약          → 05
Agent·Workflow 계약     → 06
Tool·MCP·내부 Interface → 07
시퀀스                  → 08
보안                    → 09
환경·배포               → 10
관측성                  → 11
제품 회귀 검증          → 12
후보 비교·실험          → 13
운영                    → 14
Prompt·Failure 정규화   → 15
```

같은 Concern에서는 해당 소유 계약과 실행 가능한 Domain/SQL Constraint가 우선한다.

## 현재 Canonical 기준 — 2026-08-15 Retrieval Contract Alignment

- Project Overview v1.14
- PRD v2.10 / Functional v2.17 / Policy v2.11 / UI·UX v2.13
- Architecture v3.6 / Domain·DB v1.19 / DB Schema v1.6
- Retrieval **v2.13** / Workflow **v7.17** / Interface **v2.22** / Sequence **v3.15**
- Security v2.10 / Infrastructure **v2.10** / Observability **v2.20**
- Test **v3.36** / Evaluation **v3.23** / Operations **v2.19** / Agent Capability·Prompt **v1.23**
- Domain State Transition v1.5 / State Transition Test Matrix v1.5
- Dataset candidate: `rebuild-v1.17-r8.6-phase7.5-contract-correction`
- Projection candidate: `projection-v1.1-r8.6-phase7.5`
- Historical Prompt candidate: `0.9.0-r8.6-phase6 / semantic-r8.6-v2` — 30 Slot 정적 Rebase 이력 보존
- Current Runtime-aligned Prompt candidate: `0.9.1-r8.6-runtime-closure / semantic-r8.6-v3` — **27 Active Runtime Slot + 3 Retired Slot**, `DRAFT_RUNTIME_CONTRACT_ALIGNED_NOT_ACTIVE`
- 상태: `CONTRACT_CORRECTED_READY_FOR_REAL_MODEL_PILOT_NOT_ACTIVE`

PHASE 7에서 발견된 세 blocker는 PHASE 7.5에서 계약 수준으로 교정했다.

1. RequestIntent `analysis_requirement` legacy Gold 9건 교정, CORE-057은 human review 후 REQUIRED 유지.
2. Tool Route LLM용 `PrePolicyToolRouteGoldV1`을 final `ToolRoutePlanV2`와 분리.
3. `tasklist_id/calendar_id`는 LLM 추측이 아니라 deterministic default-container binding으로 고정.

실제 Ollama/qwen benchmark와 Holdout tuning은 아직 수행하지 않았다.

2026-08-14 Runtime alignment 과정에서 Workflow handoff의 미완성 계약을 닫았다.

- `RetrievalNeedV1 = required_information + reason_codes`로 최소 handoff schema를 확정했다.
- Work Analysis·Review의 추가 Retrieval 요청은 `RetrievalRequiredV1`로 정규화하고 Retrieval 내부 `NEEDS_MORE_DATA`는 같은 frozen IN Route의 bounded local loop로 유지한다.
- Confirmation resume authority는 active compiled Main Graph의 registered resume target이며 `graph_version`은 resume-contract version이다.
- `options=[]`는 자유 텍스트, non-empty options는 닫힌 선택 응답이다. `UserInterruptV1`은 Core workflow truth가 아니라 필요한 경우 UI/API one-way projection으로만 허용한다.

2026-08-14 Retrieval local-loop continuation alignment에서 구현 가능성을 막던 continuation owner 계약을 추가로 닫았다.

- Retrieval self-loop의 raw Provider continuation은 **Run Retrieval Cache의 read-result entry만 memory-only로 소유**하며 Local/Main State·Checkpoint·Domain DB·Prompt·Trace·Audit에 raw token을 복제하지 않는다.
- Retrieval Local State는 `read_result_handle`만 보존하고, 결정적 Read Node가 handle의 `run_id + route_id + query identity/hash`를 검증한 뒤 `NEXT_PAGE` continuation을 resolve한다.
- Follow-up `retrieval.plan_query`는 `current_round_no + prior QueryAttempt + unresolved SufficiencyIssueV2 + bounded read-result summary`를 추가로 보되 raw Page Token·Provider-native Query·MCP Arguments는 보지 않는다.
- 동일 Query + 동일 continuation state 재실행은 새 Retrieval Round로 인정하지 않으며 `NEXT_PAGE | DETAIL_FETCH | unresolved issue에 근거한 changed SEARCH`만 새 정보 획득 후보가 된다.

2026-08-15 Retrieval semantic constraint alignment에서 changed SEARCH의 구현 blocker를 Canonical 계약으로 닫았다.

- Release Retrieval planner output은 `RetrievalQueryPlanV2 / RouteQueryIntentV2`다.
- `SEARCH`에서 LLM은 Provider-native query가 아니라 값이 포함된 `SemanticRetrievalConstraintV1`을 출력한다.
- Follow-up changed SEARCH는 `ConstraintDeltaV2(upsert_constraints, remove_constraint_kinds)`를 사용한다.
- `SourceFetchPlanBuilder`가 prior effective constraints와 delta를 결정적으로 merge하여 `SourceFetchPlanV1`과 query identity를 materialize한다.
- constraint 이름만 있는 delta, raw Gmail query, RFC3339 Provider 표현, raw continuation, MCP Arguments를 LLM 실행 권위로 사용하지 않는다.
- Retrieval Local State는 field/type 변경에 맞춰 `RetrievalStateV2`로 승격했다.
- `QueryAttempt.added_constraints/removed_constraints`는 관측·follow-up summary이며 다음 실행계획의 값 권위가 아니다.
- `NEXT_PAGE`의 raw continuation owner는 기존대로 Run Retrieval Cache read-result entry 하나이며, `DETAIL_FETCH`는 bounded candidate ref만 Planner가 제안한다.
- 위 변경의 제품 회귀 Gate는 `12 Test v3.36`, Prompt/Failure 정규화는 `15 v1.23`가 검증·소비한다.

2026-08-18 Gmail `↗` 정합화에서 원본 링크류 UI 계약을 실제 구현과 맞췄다.

- Gmail ResourceDetail의 `↗`은 `원본 스레드 직접 열기`가 아니라 `Gmail에서 찾기`다. RFC822 Message-ID가 있으면 `rfc822msgid:` 기반 Gmail 검색 URL, 없으면 All Mail 목록 fallback이며, Gmail REST `thread_id`/`message_id` 기반 direct-open hash URL은 사용하지 않는다.
- `02 UI·UX`·`01-A Functional`의 `원본 Google 서비스에서 열기`/`원본 링크가 보존된다` 표현을 Provider capability에 따라 직접 열기 또는 찾기일 수 있다는 의미로 정합화했다(`02 v2.13`, `01-A v2.17`).
- `07 Interface`는 `canonical_url`의 Gmail P0 의미와, 이를 위해 내부 MCP Gmail UI Detail 계약(`GmailThreadDetail`)에 `rfc822_message_id`가 추가로 전달됨을 반영했다(`07 v2.22`). API response schema(`GmailResourceDetailResponse`)는 변경하지 않았다.
- `01 PRD`는 검토 결과 direct-open permalink를 명시적으로 주장하는 충돌 문구가 없어 버전 변경 없이 유지한다.
- DB schema/migration, LangGraph, Prompt는 이 정합화의 대상이 아니다.

## 프로젝트 소스 25개 구성

1. `00-PROJECT-SOURCE-GUIDE.md`
2. `0001_initial.sql`
3. `0002_action_effect_send_delete.sql`
4. `0003_action_cancelled.sql`
5. `0004_plan_review_gate.sql`
6. `0005_cross_aggregate_invariants.sql`
7. `01-requirements-prd.md`
8. `01-a-functional-definition.md`
9. `01-b-policy-definition-v2.8.md`
10. `02-ui-ux-design.md`
11. `03-system-architecture.md`
12. `04-domain-database-design.md`
13. `05-context-retrieval.md`
14. `06-agent-workflow.md`
15. `07-tool-mcp-internal-interface.md`
16. `08-sequence-design.md`
17. `09-security-auth-v2.5.md`
18. `10-infrastructure-environment-v2.7.md`
19. `11-observability-logging-audit.md`
20. `12-test-design.md`
21. `13-evaluation-experiment.md`
22. `14-operations-troubleshooting.md`
23. `15-agent-capability-failure-prompt-contract.md`
24. `state-transition-contract-v1.4.md`
25. `state-transition-test-matrix-v1.4.md`

상태 전이 파일명은 호환성 때문에 `v1.4` 문자열을 유지하지만 본문 Canonical은 v1.5다. 적용 Migration `0001~0005`는 이력/checksum Artifact이므로 소급 수정하지 않는다.
