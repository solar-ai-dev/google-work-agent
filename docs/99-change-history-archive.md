# 99. Google Work Agent · 변경 이력 · 아카이브

> **용도:** 과거 설계 변경의 맥락을 보존하는 비권위 문서다. 구현과 실험은 각 Canonical 문서의 현재 본문을 기준으로 한다.

## 현재 기준

- R8.3 · Gold · Scoring · Human Readability Consistency Patch · 2026-08-08
- Canonical Gold v4: ordered interactions + profile-neutral semantic milestones
- Grader Registry v0.4 · Scoring Contract v1.1
- Prompt Bundle 0.8.2-r8.3은 evaluator/gold 문구와 Product Prompt를 격리

## 주요 변화 요약

<details>
<summary>R8.2 — Agent Subgraph와 E06 정합성</summary>

- Agent를 invocation-local LangGraph Subgraph로 명시.
- SINGLE/THREE/SIX를 1/3/6 Agent Subgraph로 정의.
- E06-A Native Architecture와 E06-B Controlled Post-Retrieval 분리.
- Prompt Runtime Key와 failure block assembly 경계 정리.
</details>

<details>
<summary>R7 — 승인형 Effect·Recovery·Clarification</summary>

- SEND·Calendar DELETE·Task 완료·Attendee UPDATE 승인형 경로.
- External I/O와 SQLite Write Transaction 분리.
- UNKNOWN_RESULT No-Resend와 Recovery Domain Command.
- Clarification과 과도 조회 차단.
</details>

<details>
<summary>초기 R3~R6 — Local Runtime·Domain·Evaluation 기반</summary>

- React + FastAPI Local Service, MCP stdio, SQLite Domain Store/Checkpoint 분리.
- Command Receipt·Approval Hash·Claim·Verification 계약.
- Core/Holdout/Stress와 Node/Trajectory/E2E Projection 평가 구조.
</details>

## 규칙

- 과거 Version 번호나 날짜가 필요한 경우 이 문서에만 추가한다.
- Canonical 문서 본문에는 “이번에 무엇이 바뀌었는지”보다 **현재 무엇이 참인지**만 남긴다.
- 변경이 현재 계약을 수정하면 먼저 권위 문서 Version을 올리고, 여기에는 요약만 남긴다.
