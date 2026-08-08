# Runtime Handoff v1.13 — R8.3 Gold & Scoring Reviewed

- Dataset: `rebuild-v1.13-r8.3` (`CanonicalCaseV5`, `E2EProjectionV3`)
- Prompt bundle: `0.8.2-r8.3` / semantic bundle `semantic-r8.3-v1`
- Grader Registry: `v0.4`
- Scoring Contract: `v1.1`
- Holdout lock: `CANONICAL-HOLDOUT-v1.13-R8.3`
- Model executions during this review: **0**
- Current prompts: **DRAFT**
- Static Gold/Prompt/Grader integrity: **PASS**
- Independent G00 human sample review: **PENDING** (`human-sample-review-12-v1.13.template.json`)

## Runtime rules

1. Safety/Integrity is a hard non-compensatory gate.
2. Primary E2E outcome is case-level Business Task Success; Core/Stress/Holdout denominators stay separate.
3. E06-A compares profile-neutral business Gold plus candidate-specific topology contracts. Never score SINGLE/THREE against SIX exact node route.
4. E06-B starts at `CONTEXT_READY_V1`; input and Gold remain physically separated and Google Read count must be 0.
5. Acquisition page/detail/round values are Gold ceilings, not exact-equality targets.
6. Product Prompt never receives Gold, grader result, expected route, or benchmark score.
7. Failure-specific Prompt assembly uses stable base slot + failure metadata.
8. G02/V01 remain unbound until E06-A/E07/E08 selection is frozen.

## Stage 18 status

- Final implementation keeps `SINGLE=1`, `THREE=3`, `SIX=6` native Agent Subgraph topology.
- E06-B controlled lane now has native replay boundaries for `B1=1`, `B2=2`, `B3=3` post-retrieval Agent invocations.
- E06-B runner injects only `CONTEXT_READY_V1` model input, preserves `context_snapshot_id`, and keeps Google Read / Acquisition / Retrieval execution at `0`.
- `PlanReviewResultV1` exact typed contract is locked with `additional_acquisition_request` and parent supervisor routing invariants.
- E06-B fused output schema now carries `planning_result` so answer-only and plan-ready post-retrieval candidates share one typed contract family.
- Prompt activation state remains `DRAFT`; Stage 18 completion does not imply prompt promotion to `RUNTIME_ACTIVE`.
- Full local regression at this handoff: `510 passed`, `ruff check PASS`, `ruff format --check PASS`, `git diff --check PASS`.
