# Evaluation workspace

`evaluation/` is the single repository owner for datasets, Gold, experiment inputs, offline
Prompt candidates, the Product-independent grader, and public-boundary experiment operations.
The Product is the system under evaluation; this directory is never part of Product runtime or
release packaging.

## Dependency boundary

Evaluation invokes an already configured Product only through its supported loopback HTTP API.
Code under this directory must not import `google_work_agent`, Product Domain/Application types,
LangGraph nodes, adapters, repositories, or test-only Product executors. Product code must not
import `evaluation`.

```text
Dataset + Candidate Config + one selected Prompt candidate
        → ExperimentPlanV1 validation/materialization
        → evaluation.client.ProductApiClient → Product HTTP API
        → public run snapshot → evaluation.grader → trial/summary result
```

## Layout

```text
evaluation/
├── datasets/
│   ├── retrieval/   # retrieval/context cases and Gold
│   ├── agent/       # agent, safety, repair, robustness cases and prompt inputs
│   └── e2e/         # canonical cases, Product episodes, fixtures, Gold, attachments
├── configs/
│   ├── candidates/  # model/graph/runtime candidate inputs; not runtime authority
│   └── experiments/ # reproducible ExperimentPlanV1 templates
├── prompt_candidates/
│   └── <candidate-id>/ # versioned offline DRAFT Prompt sources and provenance
├── client/          # HTTP request/response handling only
├── dataset.py       # strict JSONL loading and artifact hashing
├── grader.py        # semantic, Product-independent deterministic grading
├── runner.py        # one-case public-HTTP orchestration and JSON serialization
├── prompt_candidate.py             # candidate validation/materialization
├── experiment_plan.py              # closed plan/provenance validation
├── run_experiment.py               # exact case × repetition batch operation
└── compare_experiment_results.py   # controlled result comparison
```

There were no useful notebooks or version-controlled benchmark results at migration time, so no
empty `notebooks/` or `results/` directories are kept. Add a notebook only for analysis,
comparison, visualization, or public-boundary orchestration.

## Dataset and Gold policy

- `datasets/e2e/canonical_cases_v7.jsonl` contains 92 immutable Canonical Cases.
- `datasets/e2e/product_episodes_v1.jsonl` contains 10 public-run Product Episode projections;
  the independent detailed Gold remains in `datasets/e2e/product_episode_gold/`.
- `datasets/agent/` contains 21 preserved agent inputs and 126 agent micro cases.
- `datasets/retrieval/` contains 8 retrieval variants plus controlled context assets.
- Candidate output must never be copied into Gold. A genuine labeling defect is fixed separately
  from candidate tuning and records the dataset identity change.
- During candidate comparison, dataset bytes, Gold, grader, fixture set, and Product boundary stay
  fixed. Only the candidate/config variable changes.
- DEV, HOLDOUT, Safety, and Product Episode identities remain Dataset-owner decisions. If a
  checked-in dataset does not encode a required split, validation reports `NEEDS_DATASET_DECISION`
  instead of inventing one.

The JSON fixtures are synthetic. An evaluation environment that needs them must provision a
Product instance externally; Evaluation must not inject them by importing Product internals.

## Prompt candidate lifecycle

Many useful Prompt candidates may coexist under `prompt_candidates/<candidate-id>/` on the same
branch. Branches are not candidate storage. Each experiment plan selects exactly one baseline or
DRAFT bundle, materializes it into a temporary `PromptRegistry` directory, and compares it while
all non-Prompt dimensions remain fixed. Switching plans changes the selected candidate; it does not
delete the other candidates.

A checked-in candidate is not validated evidence. Successful materialization is not a DEV pass,
a DEV pass is not a HOLDOUT or Safety pass, and an Evaluation comparison is not Product activation.
Only a separate immutable Product Decision may promote the eventual winner and remove superseded
candidates when the experiment program is complete.

Materialize a candidate without changing Product source:

```powershell
python evaluation/prompt_candidates/mcp-tool-use-2026-v1/materialize_prompt_candidate.py `
  --output <temporary-output-directory>
```

The materializer validates the exact 21-slot set, Product manifest/input contracts, source hashes,
candidate bundle hash, and DRAFT lifecycle. It refuses to overwrite Product Prompt source or the
candidate itself.

## Experiment plan and validation

`ExperimentPlanV1` locks the Product SHA, Dataset path/hash/case IDs, Candidate Config path/hash,
Prompt candidate identity/hash, repetition and failure policy, Grader path/hash, and comparison
group. Existing files under `configs/candidates/` remain the model/graph/runtime parameter owner;
the plan references them rather than duplicating those settings.

Validate both Prompt comparison templates without calling Product or an LLM:

```powershell
python -m evaluation.experiment_plan `
  --plan evaluation/configs/experiments/prompt-baseline-smoke.template.json `
  --validate-only

python -m evaluation.experiment_plan `
  --plan evaluation/configs/experiments/prompt-mcp-research-smoke.template.json `
  --validate-only
```

Validation reports every unresolved binding. In particular, a DRAFT candidate remains
`PENDING_DEV_LAUNCH_INTEGRATION` until the supported external development Product launcher can
select its materialized manifest, and unresolved model placeholders keep the plan non-runnable.

## Running experiments

Start the supported Product externally with the exact Product SHA and selected development
configuration. Evaluation does not construct Product internals or grant runtime authority to a
candidate. The one-case runner remains the smallest public-boundary operation:

```powershell
python -m evaluation.runner `
  --case-id CASE-CORE-003 `
  --product-sha <product-sha> `
  --experiment-name retrieval-baseline `
  --candidate-id baseline `
  --requested-mode AUTO `
  --output evaluation/results/retrieval-baseline/CASE-CORE-003.json
```

The runner requests the bootstrap secret interactively so it is not placed in source, arguments,
results, or shell history. It loads the dataset, calls the Product API, captures the public run
projection, grades it, and writes one JSON artifact.

After resolving every plan binding, run the exact case × repetition batch:

```powershell
python -m evaluation.run_experiment --plan <resolved-plan.json>
```

The batch delegates each trial to `evaluation.runner.run_case()`, follows the plan's `CONTINUE` or
`STOP` failure policy, and writes the validated plan, raw trials, normalized observations,
provenance, and an atomic summary. Results include Product, Dataset, Grader, Candidate Config,
Prompt bundle/materialized manifest, graph/runtime identities, pass rate, pass@k, and pass^k.

Compare two complete controlled result sets:

```powershell
python -m evaluation.compare_experiment_results `
  --baseline evaluation/results/<baseline-id> `
  --candidate evaluation/results/<candidate-id> `
  --output evaluation/results/<comparison-id>.json
```

Comparison refuses different Product, Dataset/Gold, Grader, model/profile/runtime configuration,
case set, or repetition count. It classifies case deltas and hard-gate regressions but never
declares a winner. Any new hard-gate failure is `NOT_PROMOTABLE`.

## Results and reproducibility

`evaluation/results/` is local and gitignored by default. Commit only a deliberately selected
baseline, published comparison, or regression reference. Do not commit secrets, live Google data,
transient raw output, or tuning caches.
