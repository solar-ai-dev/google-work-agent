# Current Evaluation Dataset — R8.4

- Dataset: `rebuild-v1.14-r8.4`
- Prompt bundle: `0.8.3-r8.4`
- Semantic bundle: `semantic-r8.4-v1`
- Canonical Gold: `CanonicalCaseV5`
- E2E Gold: `E2EProjectionV3`
- Grader Registry: `v0.5`
- Scoring Contract: `v1.2`
- Holdout: `CANONICAL-HOLDOUT-v1.14-R8.4`

## Automated validation state

- R8.4 static integrity: **PASS**, 14187 checks / issue 0 / warning 0.
- R8.4 semantic/Gold/scoring audit: **PASS**, 7638 checks / issue 0 / warning 0.
- Business-only prompt and same-topic conversation continuity checks are included.
- Prompt catalog text/language/case/split parity is enforced against source artifacts.

## R8.4 additions

ClaimContextV2 and Gmail Attachment are deterministic safety/integrity concerns. G02 contains negative fault coverage and six positive integrity paths: valid claim, attachment download, staging, Draft CREATE, Draft UPDATE and attachment SEND. Attachment bytes/content/local paths are never model-quality inputs or Evidence.

## Not yet claimed

- Independent human sample review: **PENDING**.
- Actual model execution/performance: **NOT RUN**.
- Prompt activation: **DRAFT**.
