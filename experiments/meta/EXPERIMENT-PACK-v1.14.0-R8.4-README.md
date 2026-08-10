# Experiment Pack v1.14.0 — R8.4

R8.4 ClaimContextV2·Gmail Attachment canonical 기준으로 재정합화한 실험팩이다.

- 사용자 요청은 Gmail/Tasks/Calendar 실제 업무 흐름만 사용한다.
- Consumer/off-topic user prompt는 허용하지 않는다.
- 대화 Context가 있는 ambiguity case는 직전 주제와 동일 업무 연속성을 유지한다.
- Gold/Policy/Effect/Verification/Recovery/Scoring 정합성을 자동 validator + semantic audit가 검사한다.
- Prompt Catalog는 Source-of-truth에서 생성하며 text/language/case/split parity를 검증한다.
- R8.4 Claim/Attachment는 G02 결정적 Hard Gate이며, negative fault와 positive path를 모두 가진다.
- Attachment bytes/content/local paths는 LLM Prompt/Context/Evidence/quality score에 들어가지 않는다.
- 비교 실험의 hypothesis/stop/adoption criteria는 결과 보기 전에 manifest에 고정한다.
- 구버전 R8.2/R8.3 active-control artifact는 현재 실행 권위에서 제거했다.

## 현재 Gate

- Automated static integrity: PASS, 14187 checks / issue 0 / warning 0.
- Automated semantic/Gold/scoring integrity: PASS, 7638 checks / issue 0 / warning 0.
- Independent human sample review: PENDING.
- Actual model execution: NOT RUN.
- Prompt runtime status: DRAFT.

자동 검수 PASS를 사람 검수 또는 모델 성능 PASS로 해석하지 않는다.
## 2차 독립 재검수 보강

- Quartz 첨부 SEND가 unrelated Grove campaign CSV를 사용하던 cross-project 오류를 Quartz 납품 확인 자료로 교체했다.
- Attachment download fault `FSI-034/035`를 실제 첨부 Metadata가 존재하는 `CASE-CORE-054`에 연결했다.
- E06-B Product Prompt에서 `grader/gold` 평가 전용 용어를 제거하고 Prompt hash를 재생성했다.
- 남아 있던 `prompts/agent/r8.2/` 구버전 트리를 물리적으로 제거했다.
- Dataset Build/Micro Dataset Manifest의 실제 파일 수 parity를 Gate에 추가하고, Quartz fixture 추가 후 stale count를 수정했다.

