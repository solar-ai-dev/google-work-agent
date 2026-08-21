# Google Work Agent — Project Source Guide

## 목적

이 묶음은 설계 검토·구현 질의·실험/평가 검토에 사용하는 **Canonical 프로젝트 소스 26개**다.  
공식 원본은 **Notion Canonical**이며 이 Markdown 묶음은 **2026-08-22 Repository Architecture v1.2 + Local SLLM Responsibility Decomposition 정합화 이후 Export Snapshot**이다.

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
Repository 구조·코드 조직·Naming·의존 방향·Production Authority 유일성 → 16 Repository Architecture
```

같은 Concern에서는 해당 소유 계약과 실행 가능한 Domain/SQL Constraint가 우선한다.  
`00-A/00-B/00-C`와 변경 이력은 설명·요약·역사 자료이며 규범 권위가 아니다.

Semantic behavior는 기존 concern owner와 executable Domain/SQL Constraint가 계속 소유한다.  
**파일 위치, 모듈 책임, 네이밍 문법, import/export 의존 방향, semantic ownership, 동일 capability의 production authority 유일성, 구조 refactor 절차는 `16-repository-architecture-source.md`가 소유한다.**  
현재 코드의 위치·이름·wrapper chain이 16번 규칙과 충돌하면 현재 구현을 architecture authority로 간주하지 않고 **structural migration debt**로 판정한다.

## 현재 Canonical 기준 — 2026-08-22

Behavioral semantic baseline은 2026-08-19 승인 기준을 유지하되, 2026-08-22 사용자 승인 변경으로 Workflow/Sequence/Test/Evaluation/Prompt 계약과 Repository Architecture의 소유 내용이 실제로 변경되어 해당 문서만 version-up했다. 나머지 behavior 문서는 기존 version을 유지한다.

- Project Overview **v1.17**
- PRD **v2.11** / Functional **v2.18** / Policy **v2.12** / UI·UX **v2.14**
- Architecture **v3.7** / Domain·DB **v1.20** / DB Schema **v1.6**
- Retrieval **v2.13** / Workflow **v7.21** / Interface **v2.23** / Sequence **v3.18**
- Security **v2.11** / Infrastructure **v2.11** / Observability **v2.20**
- Test **v3.40** / Evaluation **v3.27** / Operations **v2.20**
- Agent Capability·Failure·Prompt **v1.27**
- Domain State Transition **v1.5** / State Transition Test Matrix **v1.5**
- Repository Architecture **v1.2 — CANONICAL_FOR_REFACTOR**
- Dataset candidate: `rebuild-v1.17-r8.6-phase7.5-contract-correction`
- Projection candidate: `projection-v1.1-r8.6-phase7.5`
- Previous runtime-aligned Prompt candidate: `0.9.1-r8.6-runtime-closure / semantic-r8.6-v3` — **27 Active + 3 Retired**, 재현 기준
- New topology candidate: `0.9.2-r8.6-sllm-decomposition / semantic-r8.6-v4`
  - 상태 `DESIGN_DEFINED_MANIFEST_NOT_BUILT`
  - Active Slot 수는 manifest/source/caller/input-contract 생성 후 확정
- 실제 Prompt 활성화는 Node DEV → Holdout → Safety Gate 이후에만 허용한다.

## 2026-08-19 Behavior Canonical 유지

### Conversation · Run 의미 경계

- `Conversation`은 여러 USER/ASSISTANT Message와 여러 Run을 시간순으로 보여 주는 **UI·영속 Timeline**이다.
- Conversation 자체는 Agent의 장기 Semantic Memory가 아니다.
- Terminal Run 뒤 같은 Conversation에서 후속 요청 또는 업무적으로 무관한 새 요청을 시작할 수 있다.
- 새 USER 요청은 **새 `run_id + langgraph_thread_id + RunInputV1`**로 시작한다.
- 과거 Run의 Message, Agent Artifact, Evidence, Plan/Review, Approval, Confirmation Receipt, Checkpoint를 새 Run에 암묵적으로 승계하지 않는다.
- 사용자가 과거 Resource를 이번 Run에 명시적으로 다시 선택하면 현재 Run에서 최소 자료를 다시 조회·검증한다.
- 동일 Run의 Confirmation·재인증·Recovery만 기존 Thread/Checkpoint를 resume한다.
- Conversation History 조회 결과를 StartRun/Prompt 입력으로 자동 주입하지 않는다.

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

## Repository Architecture v1.2 — 2026-08-22

### Frozen convention decisions

```text
D1 semantic-owner Domain organization
D2 operation-per-file Domain lifecycle/guards
D3 <Verb><Object>Handler Application use cases
D4 owner-local contracts; no global catch-all contracts package
D5 _compat forbidden on main
```

### Deterministic implementation lookup

```text
SPEC TERM
→ CANONICAL TERM
→ SEMANTIC OWNER
→ LAYER
→ OPERATION
→ PATH
→ FILE
→ SYMBOL
→ TEST PATH
```

- 현재 filename만 보고 기능 부재를 판정하지 않는다.
- 동일 Domain fact/state writer, repository mutation, external effect, transition/result, exported symbol, caller chain까지 semantic search한다.
- 동일 capability의 기존 production authority가 발견되면 새 병렬 구현을 만들지 않고 `SEMANTIC_AUTHORITY_COLLISION`으로 중단한다.
- Architecture v1.2의 repository naming/placement는 Workflow v7.21의 새 atomic responsibility topology를 distinct operation files로 매핑하되 runtime behavior authority는 06/15에 둔다.
- `_compat`은 refactor integration branch의 transient migration 도구일 뿐이며 `main`에서는 0개여야 한다.

## 2026-08-22 Local SLLM 책임 분해

- Agent 수는 6개를 유지한다.
- Work Analysis: facts / relation candidates / information gaps / operational risks를 atomic LLM responsibility로 분리한다.
- Planning ACTION: frozen Output Route별 action objective와 Tool Arguments serialization을 별도 LLM 호출로 분리한다.
- Review: goal/evidence, action scope/route, user constraints/supplied policy summary를 별도 검사하고 deterministic aggregator가 disposition을 만든다.
- 강한 Runtime의 node fusion은 atomic parity gate를 통과한 경우에만 허용한다.
- Product LLM Call hard cap은 Run당 24다.

## 프로젝트 소스 26개 구성

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
26. `16-repository-architecture-source.md`

**주의:** 16번 Source가 추가되었으므로 최종 Project Source 세트는 25가 아니라 **26개**다. `/docs/design/16-repository-architecture/` 아래 세부 문서는 16번 Source의 subordinate normative detail이며 Project Source 개수에 별도 산입하지 않는다.

상태 전이 파일명은 Repository 호환성 때문에 `v1.4` 문자열을 유지하지만 본문 Canonical은 **v1.5**다.  
적용 Migration `0001~0005`는 이력/checksum Artifact이므로 소급 수정하지 않는다.

## 16번 세부 문서 manifest

```text
/docs/design/16-repository-architecture/
├── 00-README.md
├── 01-spec-to-code-mapping.md
├── 02-directory-ownership.md
├── 03-naming-grammar.md
├── 04-artifact-taxonomy.md
├── 05-dependency-import-export-rules.md
├── 06-langgraph-state-ownership.md
├── 07-connector-api-persistence-grammar.md
├── 08-single-authority-compat.md
├── 09-test-fixture-migration-grammar.md
├── 10-error-event-configuration-naming.md
├── 11-refactor-playbook.md
├── 12-architecture-enforcement.md
└── 13-exception-registry.md
```

## Structural Refactor 시작 Gate

다음 문서 감사가 전부 PASS하기 전에는 structural refactor를 시작하지 않는다.

```text
DOCUMENT_AUTHORITY_PRIORITY_PASS
DOCUMENT_PURPOSE_SCOPE_PASS
DOCUMENT_VERSION_MANAGEMENT_PASS
DOCUMENT_FORMAT_CONSISTENCY_PASS
SEMANTIC_TERMINOLOGY_CONSISTENCY_PASS
CROSS_REFERENCE_VALIDITY_PASS
TRACEABILITY_COMPLETENESS_PASS
NO_DUPLICATE_AUTHORITY_PASS
```

전부 통과한 뒤에만:

```text
ARCHITECTURE_RULESET_FROZEN
READY_FOR_STRUCTURAL_REFACTOR
```

를 선언한다.
