# Runtime Handoff v1.11 — R8.2 Business-ready

- Dataset: `rebuild-v1.13-r8.3`
- Prompt bundle: `0.8.2-r8.3` / semantic bundle `semantic-r8.3-v1`
- Model executions in this review: **0**
- New/changed prompts: **DRAFT**
- E06: run E06-A and E06-B only; legacy E06 is superseded.
- E06-B: inject model input from `CONTEXT_READY_V1`; never expose grader gold and perform Google Read 0.
- Prompt failure handling: use stable base slot + `failure_reason_code` assembly metadata.
- G02/V01: bind `candidate-integrated-finalist.template.json` only after E06-A/E07/E08 decision freeze.
- G00 Human Review must cover changed Korean requests and enriched email fixtures before model experiment execution.
