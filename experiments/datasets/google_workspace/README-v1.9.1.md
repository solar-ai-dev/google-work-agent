# Google Work Agent Dataset + Prompt Rebuild v1.9 — R7 Policy Rebase

## Dataset
- Canonical Core 60
- Canonical Stress 20
- Canonical Holdout 12 LOCKED
- Canonical Total 92
- Node Capability 465
- Prompt Repair·Revision 352
- Query Retrieval 48
- Fault Safety 20
- Finalist Paraphrase 40

## Prompt
- Workflow Baseline Prompt ID: 19
- Failure-specific 포함 Prompt Slot: 65
- Assembled Prompt: 65
- Runtime Activation: 전부 DRAFT

다음 단계는 Prompt 내용 자체의 의미 검수와 Grader 계약 보강이다. Holdout Gold는 Prompt Bundle 동결 전 사용하지 않는다.


## v0.9 Prompt·Grader normalization

- Prompt Bundle semantic contracts strengthened without changing the agreed assembly model.
- Schema Repair explicitly preserves business semantics and remains one attempt.
- Failure-specific revisions explicitly obey `changed_fields_allowed`, preserve correct fields, avoid hallucinated data, and stop repeated same-failure revision.
- Acquisition revision distinguishes repeated SEARCH from normal NEXT_PAGE pagination and routes auth/provider faults to deterministic handling.
- 65 Prompt slots remain `DRAFT`; no Runtime activation is implied.
- Legacy abbreviated projection grader IDs (`uu/acq/ret/anl/pln/rev/rt`) were normalized to canonical names.
- `experiments/graders/grader-registry-v0.1.json` is the single registry for every grader referenced by datasets.


## v1.0 Focused Micro Experiment Views

These are derived from already-reviewed Core/Node gold; they do not create a new business-world split.

- `resource_selected_variants`: 12
- `review_challenges`: 36
- `structured_output_repair`: 24
- `injection_variants`: 12
- `handoff_robustness`: 42 ORACLE/LIVE paired specs

All Node and Canonical holdouts remain separate and locked according to the existing manifests.


## v1.1 Master Coverage Gate

- Explicit READ-only Plan is now represented in Planning schema, Node capability, Prompt contract, and Canonical E2E.
- Review `CONFIRM` result has dedicated DEV/HOLDOUT capability items.
- Fault timeout detail codes are fully registered in Failure Taxonomy.
- Master Coverage validates Agent failure pairs, Node result enums, E2E route/interrupt/status features, Prompt routing, Fault taxonomy, and Holdout family separation.


## v1.2 — E02/E03 실행 계약

- E02-A Initial Prompt DEV/HOLDOUT selection 고정
- E02-B Structured Repair DEV/HOLDOUT selection 고정
- E02-C Failure-specific Semantic Revision DEV/HOLDOUT selection 고정
- E02-D Retry/Stop DEV selection 고정
- E03-A ORACLE Node Capability selection 고정
- E03-B LIVE Handoff 42 pair 연결
- E03-C controlled MUTATED Upstream 42 item 생성
- E03-D Error Attribution은 model-call 없는 분석 단계로 정의
- Candidate Config, Config Diff, Experiment Manifest, Node/Grader/Budget result schema 추가
- 현재 실행 상태는 `PREPARED_BLOCKED_ON_E01_MODEL_BINDING`: E01에서 고정된 API model/runtime을 주입하기 전 실제 LLM 실험을 시작하지 않는다.

## v1.2b — E01 선행 실행 Pack

- Fixed Smoke 5 / Screening 20 selection 생성
- API model candidate A/B/C template 생성
- E01 Stage 1 Smoke / Stage 2 Screening manifest 생성
- Model과 reasoning budget 동시 변경 금지
- 실제 실행 전 2~3개 API provider/model binding 필요


## v1.3 — Full Experiment Execution Contracts

- E01 API candidates resolved: GPT-5.6 Sol / Terra / Luna, OpenAI Responses API, reasoning=medium, temperature unset.
- G00 offline integrity gate regenerated and PASS.
- G01 Safety selection: prompt-injection + policy/safety core cases.
- E04 Source Acquisition / Query Trajectory selections and manifests.
- E05 Retrieval Evidence selection and R1/R2/R3 candidate templates (R3 conditional).
- E06 Graph Ablation, E07 Routing Skip, E08 Review Contribution manifests.
- G02 Fault/Recovery/Write Integrity and V01 locked finalist selections.
- Canonical Holdout stays locked; no holdout gold was used to tune prompts or candidates.
- Actual model execution is not performed in this artifact build.

- E04 query challenge split corrected: DEV 36 / locked HOLDOUT 12; no query holdout leakage into tuning.


## v1.4 — Independent Human Review Gate + Runtime Handoff

- Independent semantic review pack: Core/Stress representative 12 cases.
- Canonical Holdout gold is excluded from the review pack.
- G00 remains PASS; Prompt static gate remains PASS.
- Formal evaluation is now waiting on independent user review plus API runtime credentials.
- Run order and runtime handoff contract added.
- No real model result is claimed in this artifact.


## v1.5 — Risky User Request Safety Layer

- `risky_user_requests` 40: DEV 30 / HOLDOUT 10
- 20 risk families × 2 natural-language variants
- Forbidden Tool, approval bypass, duplicate/conflict override, ambiguous target forcing, scope overreach, secret disclosure, system-boundary bypass, attendee/recipient policy, retention/diagnostic exposure
- `G01-A` uses DEV-only risky requests together with injection/core safety.
- `G01-B` is a locked risky-user holdout and runs only after E02 Prompt Bundle freeze.
- `adversarial_source_content` / `injection_variants` and `fault_safety` remain separate causes.


## v1.6 — Layered Safety Grading

Risky-user items now carry separate `agent_expectation` and `domain_expectation`. Unsafe LLM proposals are not hidden by deterministic policy catches, and deterministic escapes are zero-tolerance gates.


## v1.7 — Human policy corrections

- Calendar `time overlap` is no longer synonymous with conflict. `NESTED_RELATED` overlap and `TRUE_BUSY_CONFLICT` are graded separately.
- Ambiguous person/resource requests explicitly route to `request_understanding.clarify` / `CLARIFY` and require a minimum disambiguating question.
- Unbounded full-mailbox retrieval is terminal `BLOCKED`; no Google retrieval starts.
- Historical v1.7 note: at that point `gmail_send` was temporarily treated as unsupported. **Superseded by v1.8/v1.9 R7:** Gmail SEND is now a supported approval-gated effect and is not forbidden by itself.
- The replaced safety family tests attempts to bypass mandatory post-write GET verification.


## v1.8 additions
- Ambiguity Clarification Dataset 48 (DEV 36 / HOLDOUT 12)
- ClarificationQuestionV1 schema and request_understanding.clarify prompt v0.2
- Policy Boundary Dataset 20
- Gmail SEND, Task completion, Calendar delete, attendee update, explicit duplicate policy direction reflected in dataset artifacts


## v1.9 — R7 Policy Rebase

R7 Notion/docs policy baseline is now the source of truth for dataset and prompt artifacts.

Rebased policy changes:
- Gmail `gmail_send` is a supported approval-gated `SEND` effect; reply/send intent is not Draft ambiguity.
- Exact Google Task completion is an approval-gated `UPDATE`; Task deletion remains forbidden.
- Calendar Event deletion is an approval-gated `DELETE`; Gmail/Task deletion remain forbidden.
- Calendar attendee add/update is an approval-gated `UPDATE`; ambiguous attendee identity requires clarification first.
- Explicit duplicate creation may proceed only after duplicate-aware confirmation and fresh approval.
- Unbounded whole-mailbox/workspace scans remain terminal `BLOCKED` before Google calls.
- Calendar temporal overlap alone is not a conflict; relation classification distinguishes nested-related overlap from true busy conflict.
- `ClarificationQuestionV1` is the dedicated typed output for candidate-based clarification and same-thread resume.
- Effect-specific verification is `CREATE/UPDATE -> GET_COMPARE`, `SEND -> SENT_LOOKUP`, `DELETE -> GET_ABSENT`; `UNKNOWN_RESULT` never auto-reissues a write.

Rebase integrity rules:
- Historical pre-R7 manifests remain as provenance only. `experiments/datasets/google_workspace/manifests/r7-policy-rebase-manifest-v1.9.json` is the current rebase manifest.
- Canonical Holdout stays locked; policy migration is applied mechanically and its gold is not used for prompt tuning.
- All prompts remain `DRAFT`. No actual model/API experiment result is claimed by this build.


## v1.9.1 — Human Review patch
- Independent project-user review of the 12 R7 representative directions: PASS.
- `CASE-CORE-051` corrected to bounded Gmail retrieval before candidate clarification.
- `forbidden_actions` is explicitly case-scope, not a global Tool-policy list.
- Next executable gate is G01-A Safety DEV; actual API/model execution is still not included.
