# Google Work Agent Semantic Pilot 5

이 ZIP은 기존 `experiments/` 전체를 대체하는 완성본이 아니라, **실제 업무형 데이터셋을 어떤 수준으로 작성해야 하는지 보여주는 기준 예시 5개**입니다.

## 포함 Case

1. 긴 Gmail Thread의 최신 합의 요약 — Answer-only
2. Gmail·Tasks·Calendar 교차 확인으로 연결되지 않은 요청 찾기 — READ-only
3. 고객 요청 + 기존 Task + Calendar를 연결한 승인 대기 Write Plan
4. 동명이인과 검토 목적이 모호한 일정 요청 — Confirmation
5. 정상 업무 사실과 Source Prompt Injection이 혼재한 Write Plan

## 작성 순서

Business Scenario → 실제 Gmail·Task·Calendar → 자연어 요청 → Retrieval Gold → Tier A Gold 순서로 작성했습니다. Source 본문에는 `정답`, `hard negative`, `승인 정책` 같은 평가자 설명을 넣지 않았습니다.

## 주의

- 이 Pilot은 Holdout이 아닙니다.
- 현재 프로젝트의 기존 ID와 병합하기 전에 사람이 의미 검수해야 합니다.
- `planning.draft_plan`은 적용되는 2개 Case만 포함합니다.
- `review.inspect`는 PASS만이 아니라 PASS, REVISE, CONFIRM, BLOCK을 포함합니다.

## 검증

`python tools/validate_pilot.py`
