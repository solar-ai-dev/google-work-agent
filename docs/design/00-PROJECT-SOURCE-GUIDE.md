# Google Work Agent — Project Source Guide

## 목적

이 묶음은 설계 검토·구현 질의·실험/평가 검토에 사용하는 **Canonical 프로젝트 소스 25개**다.  
공식 원본은 **Notion Canonical**이며 이 Markdown 묶음은 **2026-08-19 Conversation · Run Context Isolation + Team UI/History + Prompt Runtime Contract Closure 정합화 이후 Export Snapshot**이다.

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
`00-A/00-B/00-C`와 변경 이력은 설명·요약·역사 자료이며 규범 권위가 아니다.

## 현재 Canonical 기준 — 2026-08-19

- Project Overview **v1.16**
- PRD **v2.11** / Functional **v2.18** / Policy **v2.12** / UI·UX **v2.14**
- Architecture **v3.7** / Domain·DB **v1.20** / DB Schema **v1.6**
- Retrieval **v2.13** / Workflow **v7.20** / Interface **v2.23** / Sequence **v3.17**
- Security **v2.11** / Infrastructure **v2.11** / Observability **v2.20**
- Test **v3.39** / Evaluation **v3.26** / Operations **v2.20**
- Agent Capability·Failure·Prompt **v1.26**
- Domain State Transition **v1.5** / State Transition Test Matrix **v1.5**
- Dataset candidate: `rebuild-v1.17-r8.6-phase7.5-contract-correction`
- Projection candidate: `projection-v1.1-r8.6-phase7.5`
- Current Runtime-aligned Prompt candidate: `0.9.1-r8.6-runtime-closure / semantic-r8.6-v3`
  - **27 Active Runtime Slot + 3 Retired Slot**
  - 상태 `DRAFT_RUNTIME_CONTRACT_ALIGNED_NOT_ACTIVE`
- 실제 Prompt 활성화는 Node DEV → Holdout → Safety Gate 이후에만 허용한다.

## 2026-08-19 핵심 정합화

### Conversation · Run 의미 경계

- `Conversation`은 여러 USER/ASSISTANT Message와 여러 Run을 시간순으로 보여 주는 **UI·영속 Timeline**이다.
- Conversation 자체는 Agent의 장기 Semantic Memory가 아니다.
- Terminal Run 뒤 같은 Conversation에서 후속 요청 또는 업무적으로 무관한 새 요청을 시작할 수 있다.
- 새 USER 요청은 **새 `run_id + langgraph_thread_id + RunInputV1`**로 시작한다.
- 과거 Run의 Message, Agent Artifact, Evidence, Plan/Review, Approval, Confirmation Receipt, Checkpoint를 새 Run에 암묵적으로 승계하지 않는다.
- 사용자가 과거 Resource를 이번 Run에 명시적으로 다시 선택하면 현재 Run에서 최소 자료를 다시 조회·검증한다.
- 동일 Run의 Confirmation·재인증·Recovery만 기존 Thread/Checkpoint를 resume한다.
- Conversation History 조회 결과를 StartRun/Prompt 입력으로 자동 주입하지 않는다.

### 팀원 Conversation/UI 구현 반영

- `GET /api/v1/conversations/{conversation_id}/history`를 저장된 Message/Run Timeline용 bounded read-only projection으로 사용한다.
- 현재 구현 bound는 Message 200, Run 200이며 Message 초과는 `truncated=true`로 표시한다.
- Conversation title은 최초 USER 요청 기반의 안정적 제목이며 이후 Run 추가로 자동 재생성하지 않는다.
- `Conversation.updated_at_ms`는 마지막 활동 시각이며 Conversation 목록 정렬의 기준이다.
- USER Message Bubble, 저장 시각 기반 표시, 날짜별 Separator, 최신 Timeline scroll, compact/autosize Composer를 유지한다.
- Gmail 원본 참조는 direct Thread permalink 보장이 아니라 RFC822 Message-ID 기반 `Gmail에서 찾기`이며 없으면 All Mail fallback이다.

### Prompt Runtime Contract Closure

- Product Prompt는 Node별 allowlisted Typed Projection만 본다.
- Generic schema repair 입력은 `base_projection + candidate_output + failure_record` 표준 envelope 하나를 사용한다.
- Confirmation resume 시 originating owner Product Prompt에만 bounded `ConfirmationResponseV1`을 optional `confirmation_response`으로 추가한다.
- Raw resume payload, `interrupt_id`, checkpoint metadata, `RegisteredResumeTargetRefV1`은 Product Prompt 입력이 아니다.
- Planning Argument Writer는 **OutputToolRouteV1 한 개씩** 처리한다.
- Tool identity/effect는 Tool Route 권위이며 Planning LLM이 Tool을 재선택하지 않는다.
- Planning LLM은 business arguments + evidence만 작성하고 Action ID, dependency authority, approval, execution, expected verification authority는 결정적 코드가 소유한다.
- Dependency는 frozen route order를 기준으로 같은 stable external resource의 downstream Action에만 결정적으로 생성한다.
- `planning.compose_dependencies` Product Prompt는 두지 않는다.
- Review.REVISE는 affected route/action candidate만 수정하고 나머지는 보존한 뒤 결정적으로 plan을 재조립한다.

### Retrieval V2 유지

- Release Retrieval은 기존 `RetrievalQueryPlanV2 / RouteQueryIntentV2 / ConstraintDeltaV2 / SemanticRetrievalConstraintV1`을 유지한다.
- Provider-native query, RFC3339 변환, MCP Arguments, raw continuation은 LLM 권위가 아니다.
- raw continuation은 현재 Run의 Run Retrieval Cache read-result entry만 memory-only로 소유한다.
- Retrieval V2를 별도 재구현하지 않는다.

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

상태 전이 파일명은 Repository 호환성 때문에 `v1.4` 문자열을 유지하지만 본문 Canonical은 **v1.5**다.  
적용 Migration `0001~0005`는 이력/checksum Artifact이므로 소급 수정하지 않는다.
