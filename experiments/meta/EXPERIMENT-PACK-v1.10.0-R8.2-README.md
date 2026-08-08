# Google Work Agent Experiment Pack v1.10.0 — R8.2

This pack rebases the v1.9.1 experiment assets to the R8.2 hierarchical Agent Subgraph contract.

## Active baseline
- Product: R8.2 (2026-08-08)
- Dataset: `rebuild-v1.10-r8.2`
- Prompt bundle: `0.8.0-r8.2`
- Prompt semantic bundle: `semantic-r8.3-v1`
- Tool / Interface: `v2.6`
- Policy: `01-B-v2.4`
- Model execution performed during this review: **No**

## Important R8.2 changes
1. Stress Projection identity/gold joins repaired against their own Stress Case.
2. Canonical prompt catalogs now cover all 92 cases while keeping Holdout catalog locked.
3. Finalist paraphrase robustness is bilingual: 20 ko-KR + 20 en-US.
4. Prompt Manifest v0.8 implements the exact 7-field Runtime Slot Key; failure_reason_code is assembly metadata only.
5. SINGLE/THREE use dedicated fused profile prompts; SIX specialist prompts remain separate.
6. E06 split into E06-A Native Architecture and E06-B CONTEXT_READY_V1 controlled post-retrieval decomposition.
7. E03-D, E08, Node Result v2 and Candidate Config v2 include R8.2 propagation/handoff/environment metrics.

## Activation
All new R8.2 prompt artifacts are DRAFT. Static integrity PASS does not mean model-quality validation or Runtime activation.
