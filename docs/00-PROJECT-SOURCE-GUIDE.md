# Google Work Agent — Project Source Guide

## 목적

이 묶음은 웹 GPT 프로젝트가 설계 검토, 구현 질의, 면접 준비, 실험 설계 검토를 수행할 때 사용하는 최신 프로젝트 소스다.

## 문서 권위·책임 소유 규칙

문서 번호가 뒤라고 자동으로 더 높은 권위를 갖지 않는다. 충돌은 **해당 Concern의 소유 문서**를 기준으로 판정한다.

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
Prompt·Failure 정규화   → 15 (01/04/05/06/07을 완화하지 않음)
```

통합 Snapshot은 탐색 편의를 위한 파일이며 개별 권위 문서를 대체하지 않는다.

## 최신 핵심 버전

- PRD v2.6
- Functional v2.5
- Policy v2.5
- UI·UX v2.3
- Architecture v2.9
- Domain·DB v1.11 / DB Schema v1.4
- Retrieval v2.4
- Workflow v5.9
- Interface v2.7
- Sequence v3.0
- Security v2.3
- Infrastructure v2.5
- Observability v2.8
- Test v3.0
- Evaluation v3.0
- Operations v2.4
- Agent Capability Contract v1.4
- Domain State Transition v1.4
- State Transition Test Matrix v1.4

## 평가·실험 핵심 결정

- 6개 역할은 초기 Baseline이며 최종 Release Graph가 아니다.
- Canonical Dataset은 Core 60 + Holdout 12 + Stress 20 = 92 Case다.
- 실험마다 별도 업무 Scenario를 대량 작성하지 않고 Canonical Case에서 Projection을 생성한다.
- P0 핵심 비교 실험은 E01~E08이다.
  - Model·Runtime
  - Prompt·Schema·Repair
  - Node 단독·Handoff
  - Source Acquisition·Read Tool Trajectory
  - Retrieval·Evidence·Context Budget
  - E06-A Agent Subgraph Native Architecture
  - E06-B Controlled Post-Retrieval Decomposition
  - Routing·Agent Skip
  - Review Agent
- Dataset·Grader, 위험 사용자 요청, Ambiguity·Clarification, Prompt Injection, Fault·Recovery·Write Integrity는 별도 Gate다.
- Prompt는 Tier A 5개를 우선 구현하되 평가 Projection은 8개 핵심 Node를 수용한다.

## 주의

- Holdout은 Prompt·Threshold 튜닝에 사용하지 않는다.
- `ORACLE` Node 결과는 상한 분석용이며 제품 후보가 아니다.
- Safety·Tool·Argument·End-state 판정은 가능한 경우 결정적 Grader를 사용한다.
- 과거 Snapshot은 구현 기준으로 사용하지 않는다. 변경 배경은 `99-change-history-archive.md`에서만 확인한다.

---

## 현재 DB·Effect 기준

현재 DB·Effect 계약은 승인형 `SEND | DELETE`, Task 완료·Calendar 참석자 UPDATE, Clarification UX, 과도 조회 BLOCK, Calendar overlap 관계 판정, External I/O↔SQLite Transaction 분리, Recovery Domain Command 경계를 포함한다.

`0001_initial.sql`은 Schema v1.2 baseline, `0002_action_effect_send_delete.sql` 적용 후 Repository baseline은 v1.3이다. Runtime E2E Canonical은 Action `CANCELLED` CHECK 확장을 포함하는 다음 Migration 적용 후 Domain DB Schema v1.4를 사용한다. 이 Source Pack에는 아직 구현되지 않은 Migration을 임의 생성하지 않으며 Repository 작업에서 추가한다.

Migration SQL의 Canonical executable source는 `src/google_work_agent/adapters/persistence/migrations/`이며, `docs/000*.sql`은 Source Pack용 byte-identical 문서 mirror다. Migration Runner와 checksum은 Runtime canonical source만 사용하고, 두 위치의 SQL은 `.gitattributes`의 LF 정책과 raw-byte equality 테스트로 drift를 차단한다.
## R8.3 Gold·Scoring 핵심 정의

- Canonical Gold는 `CanonicalCaseV5`, E2E는 `E2EProjectionV3`를 사용한다.
- Run 결과는 `run_outcome_expectation.evaluation_stop`으로 평가 경계를 명확히 한다.
- Acquisition 숫자 Budget은 exact match가 아니라 ceiling으로 채점한다.
- Grader Registry v0.4 + Scoring Contract v1.1을 활성 기준으로 사용한다.

- Canonical Gold는 `expected_interactions`와 Profile-neutral semantic milestone을 사용한다.
- `six_reference_route`는 SIX/E07 진단용이며 E06-A의 공통 성공 조건이 아니다.
- 1차 E2E 지표는 Business Task Success이고 Safety는 비보상 Hard Gate다.
- 비용·Latency는 품질 실패를 상쇄하지 않고 qualified 후보 간 Pareto 비교에만 사용한다.
- Product Prompt는 grader/gold/score 문구에 의존하지 않는다.

## Agent Subgraph 핵심 정의

- Agent는 Main Supervisor Graph가 호출하는 LangGraph Subgraph다.
- 각 Agent는 invocation 범위 Local State, Prompt 계약, bounded validation·repair/revision loop, Versioned Typed Result를 가진다.
- Agent별 장기 Memory는 없다.
- SINGLE/THREE/SIX는 1/3/6 Agent Subgraph 구조이며 LLM Call 수가 아니다.
- E06-A는 실제 1/3/6 native architecture를 비교한다.
- E06-B는 `CONTEXT_READY_V1` 이후의 post-retrieval reasoning을 B1(1)/B2(2)/B3(3) Agent Subgraph로 통제 비교한다.
## Runtime E2E Canonical 추가 기준

- Cancel은 `CANCEL_REQUESTED` 이후 새 Claim·Write를 금지하고 미실행 Action을 `CANCELLED`로 처리한다. in-flight Write는 결과를 먼저 확정하며 성공 Write를 rollback하지 않는다.
- `request_hash`와 Approval/Write authority metadata는 Browser 입력이 아니라 Application·Domain이 생성·검증한다.
- 정보 부족은 `POLICY/safety → BLOCKED`, `USER → NEEDS_CONFIRMATION`, `GOOGLE+budget → RETRIEVE_MORE`, Read-only budget 소진 시 근거 있는 경우에만 `PARTIAL` 순으로 결정한다.
- Verification MISMATCH는 Run `RECOVERY_REQUIRED`; P0 선택은 `ACCEPT_PARTIAL | CREATE_CORRECTIVE_PLAN`이다.
- Write Adapter는 `NOT_SENT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST`를 보존하며 `NOT_SENT`만 FAILED 후보로 인정한다.
