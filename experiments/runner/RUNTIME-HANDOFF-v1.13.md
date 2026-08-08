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
