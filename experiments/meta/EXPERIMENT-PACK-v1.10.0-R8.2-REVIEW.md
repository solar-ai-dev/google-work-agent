# Google Work Agent Experiment Pack v1.10.0-r8.2 — Dataset & Prompt Review Report

- Product/design baseline: **R8.2 (2026-08-08)**
- Source pack reviewed: `google-work-agent-experiment-pack-v1.9.1-clean-root.zip`
- Reviewed artifact: **v1.10.0-r8.2**
- Prompt bundle: **0.8.0-r8.2**
- Prompt semantic bundle: **semantic-r8.3-v1**
- Actual model execution during this review: **NO**
- Final static audit: **PASS — 0 critical issues / 0 warnings**

## Review Pass 1 — Structural / Dataset Integrity

검사 범위:
- 전체 JSON·JSONL parse
- Core 60 / Stress 20 / Holdout 12 개수와 Core 6-category 균형
- Holdout scenario/fixture family 격리
- Canonical Case ↔ 8종 Projection의 `case_id`, `fixture_snapshot_id`, `user_prompt_id`, `entry_mode` 일치
- Retrieval·Planning Gold parity
- Allowed Action의 Effect/Approval/Evidence 정책

주요 발견·수정:
- 기존 R7 Pack의 Stress Projection에서 **180건의 참조/Gold 불일치**를 발견했다.
  - Stress 20 Case × 8 Projection의 `user_prompt_id`가 Core ID를 재사용한 문제 160건
  - Stress Retrieval Gold 불일치 10건
  - Stress Planning Gold 불일치 10건
- Holdout Planning Projection 일부에서 canonical `forbidden_actions` 누락을 동기화했다.
- Canonical Gold 자체를 대량 재작성하지 않고, 참조·Projection 정합성만 교정했다.

## Review Pass 2 — R8.2 Contract Alignment

R8.2 기준으로 다음을 마이그레이션했다.

- `SINGLE_BASELINE=1`, `THREE_STAGE=3`, `SIX_ROLE_BASELINE=6` **Agent Subgraph** 정의 반영
- Agent 수와 LLM Call 수 분리 계측
- E06을 `E06-A Native Architecture Ablation` / `E06-B Controlled Post-Retrieval Decomposition`으로 분리
- `CONTEXT_READY_V1` 30개 controlled item 생성
- Candidate Config v2 + `evaluation_environment_hash`
- Node Result v2 + Handoff preservation/contradiction/communication-token 계측
- E03-D Error Propagation Matrix 계약 보강
- E08 catch / false-block / over-correction / cost 지표 보강
- Prompt Manifest v0.8: Runtime Key에서 `failure_reason_code` 제거, Failure Block assembly metadata로 이동

## Review Pass 3 — Prompt Semantics / Business Realism / Leakage

### Prompt 구조

- 기존 SIX specialist Prompt를 R8.2 Agent Subgraph 역할에 맞게 보강했다.
- SINGLE/THREE 전용 fused Prompt를 새로 만들었다. 기존 6개 specialist Prompt를 wrapper에서 연속 호출하는 방식은 사용하지 않는다.
- SINGLE 정상 경로는 1 Agent invocation 안에서 다음 3 LLM call을 분리한다.
  1. Request + Source planning
  2. Evidence + Analysis + Planning
  3. Self-review
- THREE는 3 Agent invocation으로 같은 semantic responsibility를 소유한다.
- E06-B B1은 1 Agent / 2 calls, B2는 2 Agents / 2 calls, B3는 3 Agents / 3 calls로 정의해 B1↔B2에서 handoff 효과를 더 깨끗하게 볼 수 있게 했다.

### Gold leakage 방지

- E06-B `CONTEXT_READY_V1`은 item별로 `input.json` / `gold.json` / `evaluation-item.json`을 **물리 분리**했다.
- Runner는 `model_input_ref`만 모델에 전달하고 `grader_gold_ref`는 Grader 내부에서만 열도록 계약을 고정했다.
- E06-B에서는 Acquisition/Context Agent 실행 및 Google Read를 금지한다.

### Fused Prompt DEV Dataset

- SINGLE/THREE profile prompt를 E06-A 전에 검증하기 위한 **30개 DEV item**을 추가했다.
- 분포: request/source 12 + post-read reasoning/planning 12 + SINGLE self-review mutation 6.
- Self-review mutation은 구조적 schema 오류가 아니라 실제 검토 의미 오류를 겨냥하도록 Action `position` 등 구조 필드를 정상화했다.

### 입력 계약 보강

- `ProfileRequestSourceInputV1`을 추가해 fused Request/Source Agent가 `retrieval_budget`과 `policy_summary`를 명시적으로 입력받도록 했다.
- 모델이 `max_pages`, `detail_limit` 같은 운영 예산을 임의 추측하지 않도록 Prompt에도 hard ceiling을 명시했다.

### User Prompt 품질

- editable Core/Stress에서 내부 구현 용어가 드러나는 표현을 정리했다.
- Holdout 12는 Lock을 보존해 자연어 문구를 튜닝 목적으로 수정하지 않았다.
- Canonical prompt catalog를 Core+Stress 80 / locked Holdout 12로 물리 분리했다.
- Finalist robustness용 paraphrase 40개를 **ko-KR 20 + en-US 20**으로 구성했다.

## Review Pass 4 — Final Regression

최종 자동 회귀 결과:

- Checks executed: **8201**
- JSON parse: **5735**
- JSONL rows parse: **252**
- Canonical Cases: **92 (Core 60 / Stress 20 / Holdout 12)**
- Canonical projections: **736**
- JSON Schema validations: **1041**
- Prompt slots: **45**
- Failure-specific assembled variants: **46**
- Candidate configs: **23**
- CONTEXT_READY_V1 controlled items: **30**
- Profile fused Prompt DEV items: **30**
- R7 Prompt provenance hash changes: **0**
- Critical issues: **0**
- Warnings: **0**

결론: **Static Dataset/Prompt Contract Integrity PASS**.

## Deliberate limitations / 아직 PASS라고 말하면 안 되는 것

1. **모델 실행은 아직 하지 않았다.** 새 Prompt의 실제 정확도·비용·Latency는 미검증이다.
2. 새 R8.2 Prompt와 failure variant는 모두 `DRAFT`다. DEV → Node HOLDOUT → Safety Gate 전에는 `RUNTIME_ACTIVE`로 승격하지 않는다.
3. E06-B의 `CANONICAL_GOLD_CONTEXT`는 decomposition 원인 분석용 diagnostic input이다. 제품 E2E 성능으로 해석하지 않는다.
4. 영어 검증은 Finalist Core20의 en-US paraphrase 20개에 한정한다. 전체 92개 bilingual benchmark가 아니다.
5. Canonical Holdout 내용은 Lock을 유지했다. 변경된 Projection/contract에 대해서만 G00 human re-review가 필요하다.
6. 이 검수는 Experiment Pack과 Prompt Artifact 대상이다. Stage 18 실제 Runtime 코드가 이 계약대로 실행되는지는 별도 source-level 검증이 필요하다.

## 다음 Gate

권장 순서:

1. **G00 changed-sample human re-review** — 수정된 Stress Projection, E06-B gold isolation, Profile fused DEV item 표본 검수
2. **E02-E Profile Fused Prompt DEV** — SINGLE/THREE 신규 Prompt 실제 모델 실행
3. **G01-A Safety DEV** — 기존 Safety Gate 실행
4. 기존 E01~E08 계획에 따라 Candidate/Prompt freeze 후 E06-A/B 수행

새 Prompt의 정적 무결성 PASS를 모델 품질 PASS로 승격하지 않는다.
