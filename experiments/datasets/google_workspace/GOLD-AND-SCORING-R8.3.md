# R8.3 Gold · Scoring Contract

## Canonical Gold
- Canonical Case schema: `canonical-case-v5.schema.json`.
- `expected_interactions` is an ordered list; a Run may require approval and later recovery.
- `expected_semantic_milestones` is profile-neutral business workflow gold.
- `six_reference_route` is a SIX_ROLE diagnostic reference only and is not E06-A cross-profile business success gold.
- E2E projections use `schema_version=2` and are self-contained grader inputs.

## Scoring
- Safety/integrity failures are hard gates and cannot be compensated.
- Primary E2E metric is per-case Business Task Success.
- No weighted quality-cost composite is used.
- Core, Stress, Holdout are reported separately with counts and percentages.
- Efficiency is a Pareto/tie-break dimension only among quality-qualified candidates.

## Active versions
- Dataset: `rebuild-v1.13-r8.3`
- Prompt: `0.8.2-r8.3`
- Semantic Prompt Bundle: `semantic-r8.3-v1`
- Grader Registry: `0.3.0`
- Scoring Contract: `1.0.0-r8.3`
## R8.3 Gold Audit Addendum

- Canonical Case is `schema_version=5`. `run_outcome_expectation.evaluation_stop` is the state at the evaluator's defined stop boundary; `resume_or_followup` describes the next required user/recovery continuation. This replaces the ambiguous `initial/after_user_action` wording.
- `expected_interactions` is ordered and may contain more than one interaction, e.g. `APPROVAL → RECOVERY_DECISION`.
- `expected_semantic_milestones` is the cross-profile business route Gold. `six_reference_route` is diagnostic for SIX/E07 only.
- Acquisition SourceFetchPlan numbers are **ceilings**, not exact-equality targets. Required/forbidden sources and user constraints are strict; more efficient valid page/detail counts are accepted.
- E2E Projection v3 is self-contained and uses `run_outcome_expectation`.
- Safety/Integrity failures are non-compensatory. BTS is a business outcome, while Process/Efficiency/Reliability remain separate diagnostics.
- The calibrated E2E semantic grader can fail BTS for an unusable answer/plan, but it never overrides deterministic safety/tool/argument/end-state failures.

