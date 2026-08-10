# Active Prompt Bundle — R8.4

- Current: `prompt-manifest-v0.8.3.json` (`0.8.3-r8.4`)
- Semantic bundle: `semantic-r8.4-v1`
- All prompts remain `DRAFT` until Node DEV → Node HOLDOUT → G01 Safety Gate.
- Runtime selection key excludes `failure_reason_code`; failure-specific instructions are assembly metadata.
- Product Prompt must never receive evaluator/grader/gold/benchmark score.
- R8.4: user-facing text follows user input language unless explicitly overridden.
- R8.4: attachment bytes/content/local paths never enter LLM Prompt/Context/Evidence; only declared metadata/descriptors may be used.
