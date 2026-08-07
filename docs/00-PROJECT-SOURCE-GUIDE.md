# Google Work Agent — Project Source Guide

## 목적

이 묶음은 웹 GPT 프로젝트가 설계 검토, 구현 질의, 면접 준비, 실험 설계 검토를 수행할 때 사용하는 최신 프로젝트 소스다.

## 권위 순서

`00 프로젝트 개요 → 01 PRD → 01-A 기능 → 01-B 정책 → 02~14 하위 설계 → 상태 전이 계약/테스트 매트릭스 → SQL`

충돌 시 상위 문서와 더 구체적인 Domain/DB Constraint를 우선한다. 통합 Snapshot은 탐색 편의를 위한 파일이며 개별 문서의 권위를 대체하지 않는다.

## 최신 핵심 버전

- PRD v2.3
- Architecture v2.5
- Workflow v5.4
- Observability v2.3
- Test v2.4
- Evaluation v2.5
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
- Dataset·Grader, Safety·Prompt Injection, Fault·Recovery·Write Integrity는 별도 Gate다.
- Prompt는 Tier A 5개를 우선 구현하되 평가 Projection은 8개 핵심 Node를 수용한다.

## 주의

- Holdout은 Prompt·Threshold 튜닝에 사용하지 않는다.
- `ORACLE` Node 결과는 상한 분석용이며 제품 후보가 아니다.
- Safety·Tool·Argument·End-state 판정은 가능한 경우 결정적 Grader를 사용한다.
- 폐기된 r3·r4 통합본을 최신 구현 기준으로 사용하지 않는다.

---

## R6 Source Pack 동기화

2026-08-07 기준 Source Pack은 `00-CODE-AGENT-START-HERE.md`와 `15-agent-capability-failure-prompt-contract.md`를 추가하고, `05·06·11·12·13`에 Agent Capability·Failure·Prompt 계약 부록을 반영한다.

오래된 `r5-sync-manifest.md`는 Pack에서 제외하며 `r6-source-pack-manifest.md`가 현재 문서 목록과 Hash를 소유한다.

