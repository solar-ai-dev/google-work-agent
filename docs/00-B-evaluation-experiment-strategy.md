# 00-B. 평가·실험 전략과 선택 이유

> **R8.3 핵심 관점 문서:** 제품 설계 결정을 무엇으로 증명하는지 설명한다. 세부 권위는 11·12·13·15를 따른다.

## 1. 한 문장
안전을 먼저 통과시킨 뒤 Business Task Success를 비교하고 Process 원인을 분석한 다음, 품질을 만족한 후보끼리 비용·지연·반복성을 비교해 제품 결정을 내린다.

```text
Dataset/Grader Integrity → Safety Hard Gate → BTS → Process → Efficiency → Reliability/Holdout/Stress → Product Decision
```

## 2. 실험이 핵심인 이유
Model·Prompt·Retrieval·Agent topology·Routing·Review를 그럴듯함이 아니라 재현 가능한 결과로 선택하기 위해서다.

## 3. 가장 중요한 원칙
- Safety/Write Integrity는 평균 점수가 아닌 Hard Gate.
- 1차 결과 지표는 Business Task Success.
- Cost/Latency는 품질 기준을 통과한 후보끼리 비교.

## 4. Gold의 의미
Gold는 현재 구현 route가 아니라 사용자 목표, 완료 조건, 필요한/금지 Source·Evidence·Action, 사용자 상호작용, Verification과 평가 종료 상태를 정의한다.

## 5. 비교 방식
| 방식 | 대상 |
|---|---|
| STRICT | Policy, Target, Arguments, Approval, Verification, 상태 |
| SET | Required/Forbidden Source·Evidence |
| CONSTRAINT_ENVELOPE | API Page·Candidate·Detail·Retry budget 상한 |
| ORDERED_PREFERENCE | 실제 의존성이 있는 상호작용 |
| SEMANTIC_RUBRIC | 답변·분석·계획 의미 품질 |

## 6. 결과 다섯 층
1. Safety·Integrity
2. Outcome/BTS
3. Process: Source·Evidence·Handoff·Error Propagation·Review
4. Efficiency: agent/LLM calls·token·Google API·cost·p50/p95
5. Reliability: repeat·Core·Stress·Holdout·win/loss/tie

## 7. P0 실험 질문
- E01 Model·Runtime
- E02 Prompt·Schema·Repair
- E03 Node·Handoff/Error Propagation
- E04 Acquisition
- E05 Retrieval·Context
- E06-A Native 1/3/6 Architecture
- E06-B Controlled Post-Retrieval Decomposition
- E07 Routing·Skip
- E08 Review

Gate: G00 Dataset/Grader, G01 Safety/Injection, G02 Fault/Recovery/Write Integrity, V01 Holdout/Stress/Human Review.

## 8. E06-A와 E06-B
E06-A는 실제 SINGLE/THREE/SIX 제품 Graph를 비교한다. E06-B는 같은 `CONTEXT_READY_V1`에서 B1/B2/B3 post-retrieval 분해만 비교하며 Google Read=0이다. E06-B만으로 전체 제품 Graph 우열을 결론내리지 않는다.

## 9. Product Prompt와 Evaluator 분리
Product input에 Gold·Grader·expected route를 넣지 않는다. Failure prompt는 Base Prompt + failure reason + affected fields + allowed change scope로 조립한다.

## 10. 실제 업무형 Dataset
Noise, 긴 Thread, 유사/중복 Resource, 모호성, 저신뢰 후보, Prompt Injection, API/Write/Recovery failure를 포함한다.

## 11. Human Review
Tool/Argument/End-state/Safety는 deterministic grader 우선. 자연스러운 답변·과잉 계획·Evidence 설명·불필요한 확인 질문은 calibrated semantic/human review를 사용한다.

## 12. 최종 후보 선택
1. Safety/Integrity Gate
2. BTS Release Floor
3. Stress/Holdout 치명적 회귀 없음
4. Process failure 분석
5. qualified 후보 Pareto cost/latency
6. 반복 안정성
7. Human Review
8. Product Decision Record

## 13. 하지 않는 해석
Safety 보상, SIX exact route의 공통 Gold화, 모든 Read exact trajectory 강제, budget 소진 강제, Holdout 사후 수정, E06-B의 제품 Architecture ranking화, 1회 성공으로 확정, 저비용 업무 실패 후보 채택을 금지한다.

## 14. 현재 Artifact 상태
- Dataset `rebuild-v1.13-r8.3`
- Canonical Gold `CanonicalCaseV5`
- E2E `E2EProjectionV3`
- Grader Registry `v0.4`
- Scoring Contract `v1.1`
- Prompt Bundle `0.8.2-r8.3`, actual model 평가 전 DRAFT

## 15. 요약
먼저 안전한지, 다음으로 실제 업무가 성공했는지, 그 다음 실패 원인이 어디인지 보고, 품질을 만족한 후보끼리 비용·지연을 비교한다. 실험 결과가 제품 구조·Prompt·Retrieval 선택의 근거가 되게 한다.
