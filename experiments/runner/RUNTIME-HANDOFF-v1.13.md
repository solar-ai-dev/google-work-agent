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
- Handoff fidelity metrics now come from replay outputs rather than fixed placeholders, covering required-field preservation, evidence preservation, constraint loss, and contradiction introduction.
- `evaluation_environment_hash` is deterministically recomputed from candidate runtime/profile lock fields and checked against the declared candidate hash before replay execution.
- The August 8, 2026 audit of commit `7fd96e4` is locked in tests for `request-intent`, profile fused outputs, `action-plan-draft`, and `plan-review` schema requirements.
- Prompt activation state remains `DRAFT`; Stage 18 completion does not imply prompt promotion to `RUNTIME_ACTIVE`.
- Full local regression at this handoff: `510 passed`, `ruff check PASS`, `ruff format --check PASS`, `git diff --check PASS`.

## Final Certification Audit

### Handoff grader proof

- Grader entrypoint: `google_work_agent.application.workflows.controlled_post_retrieval._calculate_handoff_fidelity_metrics`
- Input: `ContextReadyReplayInputV1`, `ContextReadyGoldV1`, validated `WorkAnalysisResultV1`, validated `ProfilePlanningProjectionV1`
- Comparison baseline:
  - required evidence IDs from upstream `analysis_result.evidence_refs` + frozen `context_bundle.evidence_ids`
  - required resource refs from upstream `analysis_result.resource_refs`
  - deterministic constraints from Gold `expected_answer_type` and `forbidden_actions`
- Output metrics:
  - `required_field_preservation_rate`
  - `evidence_id_preservation_rate`
  - `constraint_loss_count`
  - `contradiction_introduced`

Negative mutation proof:

| Case | Actual pytest test | Expected signal |
|---|---|---|
| Required field loss | `test_controlled_replay_handoff_metrics_detect_required_field_loss` | `required_field_preservation_rate` drops from `1.0` to `0.5` |
| Evidence ID loss | `test_controlled_replay_handoff_metrics_detect_evidence_id_loss` | `evidence_id_preservation_rate = 0.0`, `constraint_loss_count > 0` |
| Constraint loss | `test_controlled_replay_handoff_metrics_detect_answer_type_constraint_loss` | `constraint_loss_count > 0` |
| Deterministic contradiction | `test_controlled_replay_handoff_metrics_detect_forbidden_action_contradiction` | `contradiction_introduced = true` |

### B1/B2/B3 semantic handoff count

| Profile | Agent invocation count | Agent-to-Agent semantic handoff count | Boundary graded |
|---|---|---:|---|
| `B1_INTEGRATED` | 1 | 0 | integrated post-retrieval output only |
| `B2_STAGED` | 2 | 1 | analysis/planning -> review |
| `B3_SPECIALIZED` | 3 | 2 | analysis -> planning, planning -> review |

Reference test: `test_controlled_replay_runner_executes_native_b1_b2_b3_topologies`

### Environment hash payload

Hash payload builder: `google_work_agent.application.workflows.controlled_post_retrieval._build_evaluation_environment_hash_payload`

| Field | Source | Value/type | Included in hash |
|---|---|---|---|
| `dataset_version` | candidate config | `str` | yes |
| `tool_schema_version` | candidate config | `str` | yes |
| `policy_version` | candidate config | `str` | yes |
| `prompt_semantic_bundle_version` | candidate config | `str` | yes |
| `graph_profile` | `graph_profile_spec.profile_id` | `str` | yes |
| `runtime.runtime_mode` | candidate config | `str` | yes |
| `runtime.provider` | candidate config | `str` | yes |
| `runtime.model` | candidate config | `str` | yes |
| `runtime.model_version` | candidate config | `str` | yes |
| `runtime.parameters` | candidate config | `object` | yes |
| `evaluation_environment.environment_lock_version` | candidate config | `str` | yes |
| `evaluation_environment.client_os` | candidate config | `str` | yes |
| `evaluation_environment.llm_concurrency` | candidate config | `int` | yes |
| `evaluation_environment.google_read_concurrency` | candidate config | `int` | yes |
| `evaluation_environment.write_concurrency` | candidate config | `int` | yes |
| `evaluation_environment.api_llm_timeout_seconds` | candidate config | `int` | yes |
| `evaluation_environment.google_timeout_seconds` | candidate config | `int` | yes |
| `evaluation_environment.runner_version` | candidate config | `str` | yes |
| `evaluation_environment.hardware_profile_id` | candidate config | `str` | yes |
| `fixture_snapshot_id` | replay model input | `str` | yes |
| `execution_contract` | evaluation item | `object` | yes |
| `context_ready_contract_version` | evaluation item | `str` | yes |

Stable hash algorithm:

- canonical serialization: `json.dumps(..., ensure_ascii=False, separators=(",", ":"), sort_keys=True)`
- key ordering: `sort_keys=True`
- encoding: UTF-8
- hash algorithm: SHA-256

Reference tests:

- `test_controlled_replay_environment_hash_is_stable_under_key_reordering`
- `test_controlled_replay_environment_hash_changes_for_each_fixed_dimension`
- `test_controlled_replay_runner_rejects_mismatched_environment_hash`

### Independent-variable isolation

Shared fixed-environment payload builder: `google_work_agent.application.workflows.controlled_post_retrieval._build_fixed_environment_payload`

| Comparison | Actual pytest test | Result |
|---|---|---|
| `B1` vs `B2` vs `B3` excluding independent variable | `test_fixed_environment_payload_is_identical_for_b1_b2_b3_except_independent_variable` | identical |
| `SINGLE` vs `THREE` vs `SIX` excluding independent variable | `test_fixed_environment_payload_is_identical_for_e06a_profiles_except_independent_variable` | identical |

### Schema version audit (`7fd96e4`)

| Artifact | Shape change | Semantic change | Final verdict |
|---|---|---|---|
| `request-intent.schema.json` | flattened legacy intent fields -> structured intent contract | yes | semantic contract change under same schema version; repository now locks the current runtime contract in regression |
| `action-plan-draft.schema.json` | legacy result/answer form -> canonical `status/plan_id/summary/objective/actions/evidence_refs/resource_refs/confirmation` | yes | semantic contract change under same schema version; locked by regression |
| `profile-single-post-retrieval-output.schema.json` | `plan_draft` -> `planning_result` union | yes | semantic contract change; locked by regression |
| `profile-single-reason-plan-output.schema.json` | `plan_draft` -> `planning_result` union | yes | semantic contract change; locked by regression |
| `profile-three-stage2-output.schema.json` | `plan_draft` -> `planning_result` union | yes | semantic contract change; locked by regression |
| `plan-review-output.schema.json` | legacy findings/route fields -> canonical `status/summary/issues/confirmation/blockers/additional_acquisition_request` | yes | semantic contract change under same schema version; locked by regression |

Reference evidence:

- commit diff: `git diff 7fd96e4^ 7fd96e4 -- <schema paths>`
- lock test: `test_stage18_schema_audit_keeps_runtime_contract_fields_locked`

### Semantic bundle verdict

- `prompt_semantic_bundle_version = semantic-r8.3-v1`
- Verdict: `KEEP`
- Reason: the Stage 18 closure changed replay scoring integrity, environment locking, and schema/runtime contract locking. It did not change semantic responsibility coverage of the prompts themselves.

### Canonical test traceability

| Test ID | Actual pytest test name | Status |
|---|---|---|
| `TST-AGT-201` | `test_langgraph_runtime_reports_distinct_topologies_by_profile` | PASS |
| `TST-AGT-202` | `test_native_profile_runtimes_expose_three_and_single_subgraphs` | PASS |
| `TST-AGT-203` | `test_six_role_runtime_exposes_six_native_agent_subgraphs` | PASS |
| `TST-AGT-204` | `test_request_subgraph_clears_local_state_and_records_trace_counts` | PASS |
| `TST-AGT-205` | `test_acquisition_subgraph_keeps_single_invocation_id_and_parent_isolation` | PASS |
| `TST-AGT-206` | `test_plan_review_output_schema_requires_additional_acquisition_request` | PASS |
| `TST-AGT-207` | `test_native_profile_runtimes_expose_three_and_single_subgraphs` | PASS |
| `TST-AGT-208` | `test_native_profiles_generate_plan_and_share_domain_approval_boundary` | PASS |
| `TST-AGT-209` | `test_resume_rejects_mismatched_profile_for_thread` | PASS |
| `TST-EVAL-210` | `test_controlled_replay_runner_executes_native_b1_b2_b3_topologies` | PASS |
| `TST-EVAL-212` | `test_stage18_schema_audit_keeps_runtime_contract_fields_locked` | PASS |
| `TST-EVAL-213` | `test_fixed_environment_payload_is_identical_for_b1_b2_b3_except_independent_variable` | PASS |
| `TST-HANDOFF-214` | `test_controlled_replay_handoff_metrics_detect_required_field_loss`, `test_controlled_replay_handoff_metrics_detect_evidence_id_loss`, `test_controlled_replay_handoff_metrics_detect_answer_type_constraint_loss`, `test_controlled_replay_handoff_metrics_detect_forbidden_action_contradiction` | PASS |

### Safety / resume traceability

| Evidence goal | Actual pytest test name |
|---|---|
| FAILED direct retry prohibition | `tests.unit.domain.test_action_transitions.test_explicitly_forbidden_action_edges` |
| UNKNOWN_RESULT no blind resend | `tests.integration.persistence.test_write_actions.test_unknown_result_create_recovery_and_retry_flow` |
| READ persistence isolation | `tests.integration.langgraph.test_runtime.test_langgraph_runtime_executes_read_only_plan_to_terminal` |
| Claim-before-write | `tests.integration.persistence.test_write_actions.test_claim_is_blocked_by_missing_approval_and_source_hash_mismatch` |
| profile resume mismatch | `tests.integration.langgraph.test_runtime.test_resume_rejects_mismatched_profile_for_thread` |
