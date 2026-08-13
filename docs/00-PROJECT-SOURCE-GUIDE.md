# Google Work Agent — Project Source Guide

## 목적

이 묶음은 WebGPT/프로젝트 소스가 설계 검토, 구현 질의, 면접 준비, 실험 설계 검토에 사용하는 **Canonical 프로젝트 소스 25개**다. 공식 원본은 Notion이며 Repository Markdown은 구현·리뷰용 Export Snapshot이다.

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

문서 번호가 뒤라고 더 높은 권위를 갖지 않는다. 같은 Concern에서는 해당 소유 계약과 실행 가능한 Domain/SQL Constraint를 우선한다.

## 현재 Canonical 기준 — 2026-08-13

- PRD v2.10 / Functional v2.15 / Policy v2.11 / UI·UX v2.11
- Architecture v3.5 / Domain·DB v1.19 / DB Schema v1.6
- Retrieval v2.11 / Workflow v7.12 / Interface v2.18 / Sequence v3.12
- Security v2.10 / Infrastructure v2.9 / Observability v2.12
- Test v3.19 / Evaluation v3.9 / Operations v2.7 / Agent Capability v1.11
- Domain State Transition v1.5 / State Transition Test Matrix v1.5
- DB Schema v1.6: `0001_initial.sql → 0002_action_effect_send_delete.sql → 0003_action_cancelled.sql → 0004_plan_review_gate.sql → 0005_cross_aggregate_invariants.sql`. 적용 Migration은 이력/checksum Artifact이므로 소급 수정하지 않는다.

## LangGraph 핵심 계약

- 결정적 Main Supervisor + 전문 Agent LangGraph Subgraph 구조다.
- Run 생성 직후 `StartAnalysis: CREATED → ANALYZING`을 적용한 뒤 Request Understanding을 호출한다.
- Schema는 출력 가능 범위를 통제하고, State는 확정 정보를 기억하며, Prompt는 각 Node의 작은 작업만 지시한다.
- Node는 Parent/Main State 전체가 아니라 필요한 필드 Projection만 받는다.
- Tool Route는 IN/OUT을 한 번 확정해 State에 저장하고 Retrieval·Planning은 재선택하지 않는다.
- 외부 업무 시스템 접근은 `Core → Connector Registry → MCP Client/Port → Connector MCP Server → Provider Adapter` 공통 경계다. React·FastAPI Route·Application·LangGraph·Agent·Domain의 Provider API/SDK 직접 호출과 direct fallback을 금지한다. P0 첫 Connector는 `google_workspace`이며 Gmail·Tasks·Calendar를 제공한다.
- `TASK + CREATE` 중복검사와 `CALENDAR + CREATE` 충돌검사는 결정적 Policy Precondition READ다.
- 사용자 지정 범위를 넓혀야 하면 `SCOPE_EXPANSION_REQUIRED` Confirmation을 먼저 받는다.
- Confirmation은 `RequestConfirmation → interrupt(owner_subgraph + RegisteredResumeTargetRefV1) → ResumeConfirmation → 동일 owner checkpoint` 순서로 재개한다.
- 중복/충돌 최종 확정은 deterministic validator가 수행하며 Override는 `PolicyConfirmationReceiptV1`로 증명한다.
- Write는 Approval → Claim → Connector MCP Write Tool → Connector 내부 Provider Adapter → Connector Verification Read 순서다.
- 승인형 Write의 Run은 Action 실행 중 기본적으로 `WAITING_APPROVAL`을 유지하고 첫 검증에서 `BeginVerification → VERIFYING`으로 전이한다. 다중 Action DAG는 predecessor `VERIFIED` 이후 다음 Action을 실행한다.
- `UNKNOWN_RESULT`는 blind resend하지 않고 Recovery로 보낸다. `FAILED + NOT_SENT`는 사용자의 명시적 retry/cancel 결정을 기다린다.
- `RequestCancel`의 APPLIED Command Receipt는 결과 확정 중에도 durable cancel intent의 기준점이며, cancel intent가 활성인 동안 새 Claim/Write를 금지한다.
- `FINALIZE`는 비Terminal Run을 임의 종료하지 않는다. 대응 Domain Command가 먼저 `COMPLETED | CANCELLED | FAILED | BLOCKED`를 만들어야 한다.

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

파일명에 과거 버전 문자열이 포함된 일부 문서는 저장소 경로 호환을 위해 이름을 유지한다. 특히 상태 전이 두 파일은 경로명에 `v1.4`가 남아 있어도 **본문 Canonical 계약은 v1.5**다. 공식 버전은 문서 본문과 Notion Manifest를 기준으로 한다.

## 전체 docs Pack

위 25개에 설명·온보딩 문서 5개를 더한 30개다. 추가 문서는 Concern Owner가 아니며 충돌 시 위 25개 Canonical 계약을 따른다.

26. `00-CODE-AGENT-START-HERE.md`
27. `00-google-work-agent-overview.md`
28. `00-A-product-design-decisions.md`
29. `00-B-evaluation-experiment-strategy.md`
30. `00-C-core-policy-safety-invariants.md`
