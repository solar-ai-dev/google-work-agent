# Batch 07 · Paraphrase + Prompt Bundle 내부 검수

## Paraphrase
- Finalist Core 20개 × 추가 표현 2개 = 40
- Canonical 원문과 Exact Duplicate 0
- 같은 Goal·Entry Mode·Requested Outcome·Route Family 보존을 Grader 계약으로 고정

## Prompt Bundle
- Workflow 기준 Baseline Prompt ID 19개 예약 완료
- Failure-specific 조립 Slot 포함 총 65개
- Repair·Revision Dataset에서 실제 참조되는 Prompt Slot 52개
- 모든 Prompt는 Base + Purpose + Failure Block 방식으로 조립
- Assembled Prompt와 Manifest SHA-256 일치
- WORKFLOW_REDIRECTION·DETERMINISTIC_RETRY는 PromptRef 없음
- 모든 Prompt는 아직 DRAFT이며 DEV/HOLDOUT/Safety Gate 전 Runtime 활성화 금지

판정: PASS
