# v1.2 E01→E02→E03 Execution Readiness Review

## 판정

**PASS_PREPARED_BLOCKED**

실험 계약, Item Selection, Candidate Template, Result Schema는 내부 검증을 통과했다. 실제 모델 호출은 E01용 API 모델 후보 2~3개가 바인딩되기 전 의도적으로 차단된다.

## 고정 Selection

- E01 Smoke 5 / Screening 20
- E02-A Initial Prompt DEV 99 / HOLDOUT 26
- E02-B Schema Repair DEV 108 / HOLDOUT 36
- E02-C Semantic Revision DEV 138 / HOLDOUT 46
- E02-D Retry·Stop DEV 264
- E03-A ORACLE 363
- E03-B LIVE 42
- E03-C MUTATED 42
- E03-D Attribution analysis only

## 현재 유일한 실행 블로커

`CAND-E01-API-A/B/C`에 실제 provider/model/version과 모든 후보에 공통인 runtime parameter를 바인딩해야 한다. Model과 reasoning budget을 같은 비교에서 동시에 바꾸면 안 된다.
