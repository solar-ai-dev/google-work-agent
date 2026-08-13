# 00-B. 평가·실험 전략과 선택 이유

> 설명 문서다. 실험 권위 계약은 13, Prompt/Failure는 15, 제품 회귀는 12가 소유한다.

## 1. 제품 의사결정 구조

```text
A Model·Runtime
B Prompt·Node Quality
C Retrieval
D Agent Architecture
E Final Product Validation
```

기존 E01~E09/V01은 과거 Artifact 재현과 diagnostic traceability alias다.

## 2. 평가 우선순위

```text
Safety Hard Gate
→ Business Task Success
→ Process / Failure Taxonomy
→ Efficiency
→ Reliability / Holdout / Stress
```

Safety 실패를 비용·지연으로 상쇄하지 않는다. Core·Stress·Holdout·Product Episode denominator를 섞지 않는다.

## 3. Artifact 생성 순서

```text
Product Contract
→ Experiment Question
→ Dataset Coverage
→ Canonical Gold
→ Projection
→ Prompt
→ Runner / Grader
→ DEV Pilot
→ Holdout
```

Canonical Case가 Source of Truth이며 Projection은 View다. Product Prompt는 Gold/Grader/Expected Route/End-state/Decision Script를 보지 않는다.

## 4. PHASE 2~7 결정

- PHASE 2: Safety / Interaction / Trajectory / End-state / Semantic Completion grader 분리.
- PHASE 3: Base-92 고정, 희귀 P0 흐름은 Product Episode 10개로 분리.
- PHASE 4: `CanonicalCaseV7`, 명시적 `end_state_gold`.
- PHASE 5: Base-92 8종 736 Projection + E2EProjectionV5.
- PHASE 6: Prompt 0.9.0, 30 Slot 유지, runtime input allowlist / leakage 0 정적 Gate.
- PHASE 7: Runner slot-aware grading contract + 수동 40개 문체 smoke. 실제 Ollama/qwen benchmark는 아직 수행하지 않음.
- PHASE 7.5: Request Gold/Pre-policy Tool Route Gold/default container binding을 최소 교정하고 Dataset v1.17 + Projection v1.1을 정적 검증.

## 5. PHASE 7이 발견한 실제 blocker

1. **Tool Route stage mismatch**: pre-policy LLM candidate와 deterministic policy-precondition 이후 final Gold를 분리해야 한다.
2. **RequestIntent Gold review**: 단순 lookup/direct Action에 남아 있는 legacy `analysis_requirement=REQUIRED` 후보를 최신 Workflow 계약으로 검수한다.
3. **Planning default binding**: default tasklist/calendar ID를 LLM이 추측하지 않도록 deterministic binding 또는 명시적 runtime projection을 고정한다.

## 6. 다음 순서

```text
PHASE 7.5 contract correction 완료
→ Runner/Prompt Assembler 적용
→ CORE/DEV 실제 Local SLLM pilot
→ Prompt candidate 고정
→ Holdout
```
