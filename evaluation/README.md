# Evaluation workspace

`evaluation/` is the single repository owner for datasets, Gold, experiment inputs, the
Product-independent grader, and a small public-API client. The Product is the system under
evaluation; this directory is never part of Product runtime or release packaging.

## Dependency boundary

Evaluation invokes an already configured Product only through its supported loopback HTTP API.
Code under this directory must not import `google_work_agent`, Product Domain/Application types,
LangGraph nodes, adapters, repositories, or test-only Product executors. Product code must not
import `evaluation`.

```text
dataset → evaluation.client.ProductApiClient → Product HTTP API
        → public run snapshot → evaluation.grader → JSON result
```

## Layout

```text
evaluation/
├── datasets/
│   ├── retrieval/   # retrieval/context cases and Gold
│   ├── agent/       # agent, safety, repair, robustness cases and prompt inputs
│   └── e2e/         # canonical cases, Product episodes, fixtures, Gold, attachments
├── configs/         # preserved candidate/config inputs; not runtime authority
├── client/          # HTTP request/response handling only
├── dataset.py       # strict JSONL loading and artifact hashing
├── grader.py        # semantic, Product-independent deterministic grading
└── runner.py        # one-case orchestration and JSON serialization
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

The JSON fixtures are synthetic. An evaluation environment that needs them must provision a
Product instance externally; Evaluation must not inject them by importing Product internals.

## Running one case

Start the supported Product locally, then run:

```powershell
.\.venv-cpu\Scripts\python.exe -m evaluation.runner `
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

## Results and reproducibility

`evaluation/results/` is local and gitignored by default. Commit only a deliberately selected
baseline, published comparison, or regression reference. Each runner result records dataset hash,
Product SHA, experiment and candidate IDs, timestamp, requested profile, grader hash, metrics, and
the normalized public observation. Do not commit secrets, live Google data, transient raw output,
or tuning caches.

The files under `configs/candidates/` preserve useful prior candidate definitions. They are inputs
and provenance, not active Product configuration or permission to invoke internal Product symbols.
