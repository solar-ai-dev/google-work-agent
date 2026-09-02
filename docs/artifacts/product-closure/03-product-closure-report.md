# Remaining Runtime Authority and Duplication Closure Report

## Current truth anchors

```text
SOURCE_BRANCH = remediation/final-closure-integrity-fix
EXPECTED_SOURCE_HEAD = d2ee71fed4afc885bacc404c81c1c61dd56bc330
ACTUAL_SOURCE_HEAD = d2ee71fed4afc885bacc404c81c1c61dd56bc330
WORK_BRANCH = remediation/final-runtime-authority-closure
RUNTIME_COMMIT_SHA = 18a5b247692cc79697864562607c9358d57c3222
PRODUCT_SOURCE_SHA = efb10b374425c4ff1d0af3b7826dad5800e9192c
ARCHITECTURE_COMMIT_SHA = efb10b374425c4ff1d0af3b7826dad5800e9192c
MANUAL_REVIEW_SOURCE_SHA = efb10b374425c4ff1d0af3b7826dad5800e9192c
CURRENT_SHA_CI_EVIDENCE = NOT_AVAILABLE
ARTIFACT_1_SHA256 = cd17cf92bdaec4c82a85b786f3fb01e2f0346e6739dba0b8ae175d4fa28de318
ARTIFACT_2_SHA256 = 0fb2193f5d62c5647ae1f05c47fccc6aebcf3343867813c7f273625101e5ab89
```

The artifact-only commit is intentionally not self-referenced. All recorded execution evidence is LOCAL. The final artifact commit and the matching remote head are reported after push.

## Defect closure

| ID | Before | Root cause | Remediation | Exact proof | Status |
|---|---|---|---|---|---|
| B-001 | A LOCAL_CAPABLE install could not supply an approved selected model, immutable loopback endpoint policy, or final eligibility to production composition. | Release facts were projected through broad settings and the production hardware gate remained disconnected. | Added signed `LocalModelProductDecisionV1`, immutable `LlmRuntimeSelectionV1`, installed artifact validation, one eligibility evaluator, and production injection into both status and structured-inference routers. | `tests/integration/llm/test_production_local_runtime_composition.py::test_signed_local_decision__production_composition__invokes_only_local_provider` | PASS |
| B-002 | `AppSettings` re-owned user preferences, release profile, model identity, runtime mode, endpoint, and policy defaults. | An old compatibility aggregate survived after exact ports existed. | Deleted the aggregate; user persistence is `SettingsViewV1`, release choice is `LocalModelProductDecisionV1`, immutable runtime projection is `LlmRuntimeSelectionV1`, and approval timing is `ApprovalPolicyConfigV1`. | `tests/architecture/test_repository_architecture.py::test_removed_structure_residue__has_zero__production_authorities` | PASS |
| B-003 | Release generation and Product startup independently defined manifest fields and validation. | No packageable Product contract owned canonical parsing and serialization. | `approved_model_manifest.py` now owns the only schema/parser/hash/placeholder/order authority; generator and consumer import it. | `tests/release/test_generate_model_manifest.py::test_model_manifest_is__deterministic_and_uses__only_current_closed_schema`; `tests/architecture/test_repository_architecture.py::test_local_runtime_authorities__have_exactly_one__semantic_owner` | PASS |
| B-004 | Closure rows were accepted when paths and symbols merely existed. | The gate did not bind current caller, composition, effect, asserting test, frontend chain, or excessive proof reuse. | Added an artifact-bound review manifest plus AST/source gates for assertion behavior, owner/caller/composition/effect locators, frontend chain, deleted symbols, and manually adjudicated proof reuse. | `tests/architecture/test_product_closure_traceability.py::test_runtime_authority_review_manifest__binds_actual_callers__effects_and_asserting_tests` | PASS |
| H-001 | Some stage routers accepted globally known but profile-absent successors and failed later in edge-map lookup. | Routers validated the global target vocabulary instead of the compiled profile-local successor set. | All conditional stage routers now receive the immutable profile-local target set and reject unavailable targets before edge selection. | `tests/architecture/langgraph/test_main_stage_routing.py::test_every_main_stage__accepts_only__current_profile_successors`; `test_globally_known_but_profile_unavailable_target__fails_in_router__before_edge_map` | PASS |
| DUP-001 | Four app/composition tests lived under `frontend/src` while the canonical test root also existed. | Historical colocation survived after test-root ownership was standardized. | Moved all four tests to `frontend/tests/app`; assertions and the 107-case integration episode were preserved. | `npm exec -- vitest run`: 34 files / 156 tests; `test_removed_structure_residue__has_zero__production_authorities` | PASS |
| DUP-002 | Empty Google MCP and Main projection package markers remained in production source. | Old package locations survived after their authorities moved. | Deleted empty production packages and added a repository-wide empty-package gate. | `tests/architecture/test_repository_architecture.py::test_production_packages__contain_runtime_artifacts__beyond_package_markers` | PASS |
| DUP-003 | Static readiness test doubles were shipped in production source. | Test fixtures had become convenient imports for tests without a production caller. | Moved both static doubles to `tests/support/readiness.py`; production has zero references. | `tests/architecture/test_repository_architecture.py::test_removed_structure_residue__has_zero__production_authorities` | PASS |
| DUP-004 | Task and Calendar detail adapters repeat three small response checks. | The two consumers have owner-local provider response contracts, below the three-consumer extraction threshold. | Classified as `SAFE_LOCAL_REPETITION`; no generic helper or second authority was introduced. | Review manifest `defect_proof_map.DUP-004` and two-consumer census | PASS |

## Runtime matrix

| Profile | Requested mode | Local state | Expected | Actual | Proof |
|---|---|---|---|---|---|
| API_ONLY | API_LLM | N/A | API primary, no local dependency | API primary; fallback disabled | `tests/unit/llm/test_router.py::test_api_only__forces_api__runtime` |
| API_ONLY | LOCAL_GPU | N/A | Fail before provider dispatch | `RUNTIME_MODE_BLOCKED`; local 0, API 0 | `tests/unit/adapters/llm/runtime/test_structured_inference_router.py::test_api_only_local_request__fails_before__either_provider_dispatch` |
| LOCAL_CAPABLE | LOCAL_GPU | Signed decision + approved manifest + eligible hardware + ready Ollama + installed matching model | Local primary | Local invoked exactly 1; API 0 | installed-like production-composition integration proof for B-001 |
| LOCAL_CAPABLE | LOCAL_GPU | unavailable or ineligible | Fail closed; API fallback 0 | `LOCAL_UNAVAILABLE` or exact eligibility reason; API 0 | `tests/unit/llm/test_runtime_service.py::test_local_gpu__mode_never_falls__back_to_api`; `test_local_gpu__blocked_when__hardware_not_validated` |
| LOCAL_CAPABLE | AUTO | local ready | Local primary | Local primary | `tests/unit/llm/test_router.py::test_auto_allows_one_api__fallback_when_local_is__unavailable_and_consent_exists` verifies primary and bounded fallback decision; installed-like B-001 proof verifies the live local leaf |
| LOCAL_CAPABLE | AUTO | technical local failure + consent + credential + exact published scope | One API fallback | Local 1 then API 1 | `tests/unit/llm/test_runtime_service.py::test_auto_falls__back_once_after__local_gpu_failure` |
| LOCAL_CAPABLE | AUTO | local failure but scope/consent policy forbids fallback | Fail closed | Local 1; API 0 | `tests/unit/adapters/llm/runtime/test_structured_inference_router.py::test_auto_fallback_does__not_call_api__without_published_scope` |
| LOCAL_CAPABLE | any local path | missing/invalid/stale/mismatched signed artifacts or unsupported hardware/Ollama/model | Fail before unsafe dispatch | Exact bounded safe code; provider dispatch 0 | `tests/integration/llm/test_production_local_runtime_composition.py` (14 cases) |

## Authority accounting

```text
COMPETING_LIVE_AUTHORITIES = 0
DUPLICATE_EXTERNAL_WRITE_CALLERS = 0
DUPLICATE_WORKFLOW_EXECUTORS = 0
DUPLICATE_PERSISTENCE_MUTATION_OWNERS = 0
MODEL_MANIFEST_PARSER_IMPLEMENTATIONS = 1
MODEL_MANIFEST_FIELD_SET_AUTHORITIES = 1
MODEL_MANIFEST_HASH_VALIDATORS = 1
MODEL_MANIFEST_PLACEHOLDER_VALIDATORS = 1
MODEL_MANIFEST_SCHEMA_AUTHORITIES = 1
GENERATOR_CONSUMER_SCHEMA_PARITY = 1
HARDWARE_ELIGIBILITY_AUTHORITIES = 1
SETTINGS_AUTHORITIES = 4
DUPLICATE_SETTINGS_AUTHORITIES = 0
BROAD_APP_SETTINGS_AGGREGATE = 0
RELEASE_FACTS_IN_USER_SETTINGS = 0
USER_PREFERENCES_IN_RELEASE_DECISION = 0
DEAD_APPLICATION_SETTINGS_FIELDS = 0
```

The four settings-related authorities own non-overlapping facts: persisted user preferences (`SettingsViewV1`/`JsonSettingsAdapter`), signed release choice (`LocalModelProductDecisionV1`), immutable runtime projection (`LlmRuntimeSelectionV1`), and approval timing policy (`ApprovalPolicyConfigV1`).

## Duplication accounting

```text
SAFE_ROLE_SEPARATIONS = PRESERVED
REMOVED_STALE_CONTRACTS = 1
REMOVED_EMPTY_PACKAGES = 2
MOVED_TEST_DOUBLES = 2
FRONTEND_TEST_OWNERSHIP = SINGLE_CANONICAL_TEST_ROOT
SAFE_LOCAL_REPETITIONS = 1
UNJUSTIFIED_FRONTEND_TEST_ROOTS = 0
EMPTY_PRODUCTION_PACKAGES = 0
PRODUCTION_TEST_DOUBLES_WITHOUT_JUSTIFICATION = 0
```

Port/Adapter, scheduler/executor/reconciler/timer, semantic/runtime registries, persisted/process/snapshot state, stage-owned routers, and multi-level test coverage remain classified as safe role separation.

## Test inventory

```text
PYTHON_TESTS_BEFORE = 2041
PYTHON_TESTS_AFTER = 2066
FRONTEND_TESTS_BEFORE = 156
FRONTEND_TESTS_AFTER = 156
REMOVED_TESTS = 0
REMOVED_ASSERTIONS = 0
ADDED_TESTS = 25
MOVED_TESTS = 4
DUPLICATE_ASSERTION_EPISODES = 0
```

## Canonical and lineage accounting

```text
CANONICAL_REQUIREMENTS_TOTAL = 1010
UNIQUE_REQUIREMENT_IDS = 1010
DUPLICATE_REQUIREMENT_IDS = 0
PASS_REQUIREMENTS = 1010
OPEN_REQUIREMENTS = 0
NON_BLOCKING_DEBT_REQUIREMENTS = 0
TOTAL_LINEAGE_ROWS = 85
HANDOFF_ROWS = 53
HANDOFFS_CLOSED = 53
BROKEN_HANDOFFS = 0
AUTHORITY_ROWS = 13
AUTHORITY_ROWS_CLOSED = 13
SCENARIO_ROWS = 19
SCENARIOS_CLOSED = 19
OPEN_SCENARIOS = 0
HISTORICAL_FINDING_IDS_UNIQUE = 189
ORPHAN_HISTORICAL_FINDINGS = 0
UNPROVEN_HISTORICAL_CLOSURES = 0
UNACCOUNTED_OLD_FINDINGS = 0
```

## Regression execution ledger

| Command | SHA | Collected | Passed | Failed | Skipped | Duration | Evidence |
|---|---|---:|---:|---:|---:|---:|---|
| `.venv\\Scripts\\python.exe -m pytest --collect-only -q` | `efb10b37` + artifact gate | 2,066 | N/A | 0 | N/A | 2.62s | LOCAL |
| `.venv\\Scripts\\python.exe -m pytest -q` | `efb10b37` + artifact gate | 2,066 | 2,061 | 0 | 5 | 547.93s | LOCAL |
| `.venv\\Scripts\\python.exe -m pytest -q tests/unit` | `efb10b37` | 1,461 | 1,461 | 0 | 0 | 29.40s | LOCAL |
| `.venv\\Scripts\\python.exe -m pytest -q tests/integration` | `efb10b37` | 146 | 146 | 0 | 0 | 15.48s | LOCAL |
| `.venv\\Scripts\\python.exe -m pytest -q tests/component` | `efb10b37` | 3 | 3 | 0 | 0 | 3.26s | LOCAL |
| `.venv\\Scripts\\python.exe -m pytest -q tests/contract` | `efb10b37` | 17 | 17 | 0 | 0 | 1.11s | LOCAL |
| `.venv\\Scripts\\python.exe -m pytest -q tests/e2e` | `efb10b37` | 51 | 51 | 0 | 0 | 383.31s | LOCAL |
| `.venv\\Scripts\\python.exe -m pytest -q tests/release` | `efb10b37` | 16 | 16 | 0 | 0 | 0.94s | LOCAL |
| `.venv\\Scripts\\python.exe -m pytest -q tests/evaluation` | `efb10b37` | 11 | 11 | 0 | 0 | 6.37s | LOCAL |
| `$env:GWA_ARCHITECTURE_FINAL_CUTOVER='1'; .venv\\Scripts\\python.exe -m pytest -q tests/architecture` | `efb10b37` + artifact gate | 353 | 353 | 0 | 0 | 59.88s | LOCAL |
| `.venv\\Scripts\\python.exe -m pytest -q tests/integration/llm/test_production_local_runtime_composition.py` | `efb10b37` | 14 | 14 | 0 | 0 | 2.78s | LOCAL |
| `.venv\\Scripts\\python.exe -m ruff check .` | `efb10b37` + artifact gate | N/A | PASS | 0 | N/A | 0.49s | LOCAL |
| `.venv\\Scripts\\python.exe -m mypy .` | `efb10b37` + artifact gate | 1,405 files | PASS | 0 | N/A | 1.31s | LOCAL |
| `.venv\\Scripts\\python.exe -m compileall -q src launcher release evaluation tests` | `efb10b37` + artifact gate | N/A | PASS | 0 | N/A | 2.40s | LOCAL |
| `npm exec -- vitest run` | `efb10b37` | 34 files / 156 | 156 | 0 | 0 | 33.41s | LOCAL |
| `npm run typecheck` | `efb10b37` | N/A | PASS | 0 | N/A | 13.88s | LOCAL |
| `npm run lint` | `efb10b37` | N/A | PASS | 0 | N/A | 23.32s | LOCAL |
| `npm run build` | `efb10b37` | 103 modules | PASS | 0 | N/A | 15.79s wall / 1.19s Vite | LOCAL |
| `git diff --check` | `efb10b37` + final artifact | N/A | PASS | 0 | N/A | 0.22s | LOCAL |

CI evidence for the current source SHA is `NOT_AVAILABLE`; no LOCAL result is represented as CI.

## Zero gates and verdict

```text
LOCAL_CAPABLE_PRODUCTION_LOCAL_PATH_PROVEN = 1
LOCAL_GPU_UNREACHABLE_PATHS = 0
LOCAL_RUNTIME_SHADOW_DEFAULTS = 0
BROAD_APP_SETTINGS_AGGREGATE = 0
DUPLICATE_SETTINGS_AUTHORITIES = 0
MODEL_MANIFEST_PARSER_IMPLEMENTATIONS = 1
MODEL_MANIFEST_SCHEMA_AUTHORITIES = 1
HARDWARE_ELIGIBILITY_AUTHORITIES = 1
PROFILE_UNAVAILABLE_TARGETS_ACCEPTED = 0
DUPLICATE_EXTERNAL_WRITE_CALLERS = 0
DUPLICATE_WORKFLOW_EXECUTORS = 0
DUPLICATE_PERSISTENCE_MUTATION_OWNERS = 0
COMPETING_LIVE_AUTHORITIES = 0
UNJUSTIFIED_FRONTEND_TEST_ROOTS = 0
EMPTY_PRODUCTION_PACKAGES = 0
PRODUCTION_TEST_DOUBLES_WITHOUT_JUSTIFICATION = 0
OPEN_REQUIREMENTS = 0
BROKEN_HANDOFFS = 0
OPEN_SCENARIOS = 0
WEAK_TRACEABILITY_PROOFS = 0
STALE_CURRENT_TRUTH_REFERENCES = 0

FINAL_PRODUCT_CLOSURE = DEFERRED_UNTIL_PRODUCT_DECISION
LOCAL_RUNTIME_IMPLEMENTATION_CLOSURE = PASS
ACTUAL_LOCAL_MODEL_ACTIVATION = DEFERRED_UNTIL_PRODUCT_DECISION
REMAINING_FUNCTIONAL_BLOCKERS = 1 — final experiment-owned signed Product Decision
REMAINING_ARCHITECTURE_BLOCKERS = 0
REMAINING_COMPETING_AUTHORITIES = 0
REMAINING_REMOVABLE_DUPLICATION = 0
EXTERNAL_DISTRIBUTION_CLOSURE = DEFERRED — final model decision and external signing/distribution gates are not fabricated by this remediation
```

The implementation can activate LOCAL_GPU through the real production composition when supplied a valid signed decision and manifest. This repository does not contain an experiment-approved concrete final model decision, so actual activation and final Product closure remain explicitly deferred rather than being reported as PASS.
