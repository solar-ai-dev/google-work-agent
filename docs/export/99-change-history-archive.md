# 99. 변경 이력 · 아카이브

> **비권위 참고 문서**입니다. 현재 구현·실험 기준은 01~15의 최신 계약을 따릅니다. 이 페이지의 과거 버전 설명으로 현재 Runtime을 구현하지 않습니다.

## 왜 분리했는가

설계 본문에 날짜별 패치와 과거 버전 설명이 계속 쌓이면 사람이 현재 결정을 찾기 어렵고, LLM/구현 Agent도 과거 문장을 현재 계약으로 오해할 수 있다. 그래서 **현재 설계 문서는 현재 사실만 유지**하고, 변경 배경은 이 페이지로 모은다.

## 아카이브 당시 기준

- R8.3: Gold·Scoring·Prompt Evaluator Isolation·Notion Human Readability 정리
- Agent: 결정적 Supervisor + 1/3/6 Agent Subgraph 비교
- Dataset: Canonical 92 Case, CanonicalCaseV5, E2EProjectionV3
- Scoring: Safety/Integrity Hard Gate + Business Task Success + Process/Efficiency/Reliability 분리
- Prompt: Runtime Slot Key와 Failure Block assembly metadata 분리

## 주요 변경 묶음

### R8.3 — Gold·Scoring·사람 중심 문서 구조
- 단일 `expected_interrupt` 대신 ordered `expected_interactions` 사용
- E06-A 공통 Gold에서 SIX exact route 제거, semantic milestone 사용
- `run_outcome_expectation`으로 평가 stop boundary 명확화
- Acquisition Budget은 exact match가 아닌 ceiling으로 채점
- Product Prompt에서 gold/grader/expected route metadata 격리
- 현재 문서의 날짜별 변경 이력은 본 페이지로 이동

### R8.2 — Agent Subgraph·Prompt Key·E06 정합성
- Agent를 invocation-local state를 가진 LangGraph Subgraph로 확정
- SINGLE=1 / THREE=3 / SIX=6 Agent Subgraph
- E06-A Native / E06-B Controlled Post-Retrieval 분리
- `failure_reason_code`를 Prompt Slot Key가 아닌 Failure Block assembly metadata로 정리

### R7 — 승인형 Write·복구·Clarification
- SEND/Calendar DELETE/Task 완료/Attendee UPDATE 승인형 Write
- UNKNOWN_RESULT blind resend 금지
- External I/O와 SQLite write transaction 분리
- RequireRecovery/ResolveRecovery Domain Command
- Clarification 후보·차이·선택지 계약

### 초기 설계 — Local App·Domain·MCP
- React + FastAPI localhost 제품 구조
- SQLite Domain Store와 LangGraph Checkpoint 분리
- Google Work MCP stdio
- 승인·Claim·Verification 경계와 Command Receipt 멱등성

## 사용 규칙

1. 현재 계약을 찾을 때는 00 개요 → Concern Owner 문서 → 세부 계약 순서로 읽는다.
2. 이 페이지는 설계 의도·변경 배경을 추적할 때만 사용한다.
3. 과거 수치·Enum·버전이 현재 문서와 다르면 현재 권위 문서가 우선한다.

## 2026-08-19 · Conversation/Run Context Isolation + Runtime Contract Sync

- Conversation History를 UI·영속 Timeline으로 고정하고 Agent 장기 Semantic Memory와 분리.
- 새 USER 요청은 새 Run/Thread/RunInput으로 격리; Terminal Run checkpoint 자동 상속 금지.
- 팀원 구현 `GET /api/v1/conversations/{conversation_id}/history`, stable title, updated_at, Timeline UI 계약 반영.
- Prompt Runtime 27 Active + 3 Retired, bounded confirmation projection, generic repair envelope 정합화.
- Planning Argument Writer를 OutputToolRouteV1 단위로 고정하고 Tool 재선택·LLM dependency authority를 금지.
- Canonical versions: PRD 2.11, Functional 2.18, Policy 2.12, UI 2.14, Architecture 3.7, Domain 1.20, Workflow 7.20, Interface 2.23, Sequence 3.17, Security 2.11, Infrastructure 2.11, Test 3.39, Evaluation 3.26, Operations 2.20, Prompt 1.26.
