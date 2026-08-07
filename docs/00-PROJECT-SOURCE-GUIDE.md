# Google Work Agent — Project Source Guide

## 목적

이 묶음은 웹 GPT 프로젝트가 설계 검토, 구현 질의, 면접 준비, 실험 설계 검토를 수행할 때 사용하는 최신 프로젝트 소스다.

## 권위 순서

`00 프로젝트 개요 → 01 PRD → 01-A 기능 → 01-B 정책 → 02~14 하위 설계 → 상태 전이 계약/테스트 매트릭스 → SQL`

충돌 시 상위 문서와 더 구체적인 Domain/DB Constraint를 우선한다. 통합 Snapshot은 탐색 편의를 위한 파일이며 개별 문서의 권위를 대체하지 않는다.

## 최신 핵심 버전

- PRD v2.4
- Functional v2.3
- Policy v2.3
- UI·UX v2.3
- Architecture v2.6
- Domain·DB v1.9 / DB Schema v1.3
- Retrieval v2.1
- Workflow v5.5
- Interface v2.4
- Sequence v2.6
- Security v2.2
- Infrastructure v2.4
- Observability v2.4
- Test v2.5
- Evaluation v2.6
- Operations v2.2
- Agent Capability Contract v1.0
- Domain State Transition v1.3
- State Transition Test Matrix v1.3

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
  - Workflow Graph
  - Routing·Agent Skip
  - Review Agent
- Dataset·Grader, 위험 사용자 요청, Ambiguity·Clarification, Prompt Injection, Fault·Recovery·Write Integrity는 별도 Gate다.
- Prompt는 Tier A 5개를 우선 구현하되 평가 Projection은 8개 핵심 Node를 수용한다.

## 주의

- Holdout은 Prompt·Threshold 튜닝에 사용하지 않는다.
- `ORACLE` Node 결과는 상한 분석용이며 제품 후보가 아니다.
- Safety·Tool·Argument·End-state 판정은 가능한 경우 결정적 Grader를 사용한다.
- 폐기된 r3·r4 통합본을 최신 구현 기준으로 사용하지 않는다.

---

## R7 Source Pack 동기화

2026-08-07 R7 Source Pack은 R6 공통 계약에 더해 승인형 `SEND | DELETE`, Task 완료·Calendar 참석자 UPDATE, Clarification UX, 과도 조회 BLOCK, Calendar overlap 관계 판정, External I/O↔SQLite Transaction 분리, Recovery Domain Command 경계를 반영한다.

`0001_initial.sql`은 Schema v1.2 baseline으로 보존하고 `0002_action_effect_send_delete.sql` 적용 후 Domain DB Schema v1.3을 사용한다. 실제 Windows Repository 반영 여부는 이 Export Snapshot과 별도로 검증한다.

