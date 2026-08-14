# Google Work Agent — Project Source Guide

## 목적

이 묶음은 설계 검토·구현 질의·실험/평가 검토에 사용하는 **Canonical 프로젝트 소스 25개**다. 공식 원본은 Notion이며 이 Markdown은 **PHASE 7.5 완료 후 2026-08-14 기준 Export Snapshot**이다.

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

## 현재 Canonical 기준 — PHASE 7.5

- Project Overview v1.14
- PRD v2.10 / Functional v2.15 / Policy v2.11 / UI·UX v2.11
- Architecture v3.6 / Domain·DB v1.19 / DB Schema v1.6
- Retrieval v2.11 / Workflow **v7.14** / Interface **v2.19** / Sequence **v3.14**
- Security v2.10 / Infrastructure v2.9 / Observability v2.18
- Test **v3.31** / Evaluation **v3.20** / Operations **v2.17** / Agent Capability·Prompt **v1.20**
- Domain State Transition v1.5 / State Transition Test Matrix v1.5
- Dataset candidate: `rebuild-v1.17-r8.6-phase7.5-contract-correction`
- Projection candidate: `projection-v1.1-r8.6-phase7.5`
- Prompt candidate: `0.9.0-r8.6-phase6 / semantic-r8.6-v2` (내용 변경 없음)
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
