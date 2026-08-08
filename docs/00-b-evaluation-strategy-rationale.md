# 00-B. 평가·실험 전략과 선택 이유

> R8.3 설명 문서. 평가 권위는 `13-evaluation-experiment.md`다.

## 평가 결과를 읽는 순서

```text
Safety·Integrity Hard Gate
→ Business Task Success(BTS)
→ Process 원인 분석
→ Efficiency 비교
→ Repeatability·Holdout·Stress
```

안전 실패는 비용이나 다른 점수로 보상하지 않는다.

## Gold는 무엇인가

Gold는 내부 구현 순서를 외우는 답안지가 아니라 **사용자 업무 성공 조건**이다. 활성 계약은 `CanonicalCaseV5`와 `E2EProjectionV3`다.

- `expected_interactions`: 확인 → 승인 → Recovery처럼 여러 상호작용을 순서대로 표현
- `expected_semantic_milestones`: SINGLE/THREE/SIX에 공통인 업무 의미 단계
- `six_reference_route`: SIX/E07 진단 전용, E06-A 공통 점수에 사용하지 않음
- `run_outcome_expectation`: 이 평가 Item이 어디에서 멈춰야 하는지와 후속 경로

## 모든 Gold가 exact match인가

아니다.

- STRICT: Policy/Tool/Target/Arguments/Approval/Verification/상태
- SET: Required/Forbidden Source·Resource·Evidence
- CONSTRAINT_ENVELOPE: Page·Detail·Retry Budget 상한/하한
- ORDERED_PREFERENCE: 업무 의존성이 실제 의미인 순서
- SEMANTIC_RUBRIC: 답변·분석·계획의 의미 품질

예를 들어 `max_pages=2`는 2페이지를 반드시 읽으라는 뜻이 아니라 최대 2페이지까지 허용한다는 뜻이다.

## 점수

`BTS = hard_contract_pass AND semantic_task_pass`. Core·Stress·Holdout은 따로 보고 분모를 합치지 않는다. Cost·Token·p95는 품질 Gate를 통과한 후보끼리만 비교한다.

## E06

- E06-A: 실제 SINGLE/THREE/SIX 제품 후보 전체 비교
- E06-B: 동일 `CONTEXT_READY_V1` 입력에서 post-retrieval 1/2/3-Agent 분해만 통제 비교, Google Read=0

## Prompt와 Gold 분리

Product Prompt는 gold/grader/reference route/benchmark score를 입력받지 않는다. Failure-specific revision도 Gold 원문이 아니라 Runtime과 같은 `failure_record`를 사용한다.
