# Runtime Handoff v1.14 — R8.4 Claim V2 + Attachment Rebase

- Dataset: `rebuild-v1.14-r8.4` (`CanonicalCaseV5`, `E2EProjectionV3`)
- Prompt bundle: `0.8.3-r8.4` / `semantic-r8.4-v1`
- Policy: `01-B-v2.7`
- Tool/Interface contract: `v2.8`
- Grader Registry: `v0.5`
- Scoring Contract: `v1.2`
- Holdout lock: `CANONICAL-HOLDOUT-v1.14-R8.4`
- Model executions during this rebase: **0**
- Prompt activation: **DRAFT**
- Independent human review: **PENDING**

## R8.4 additions

1. ClaimContextV2 deterministic hard gates: version/TTL/expiry, Service+MCP instance, Action/Approval/Attempt/Tool/approval hash, execution arguments rehash, one-time nonce, commit-before-write.
2. Gmail Attachment deterministic hard gates: download metadata-byte consistency, byte isolation, staging descriptor integrity, tamper/expiry/missing handling, Draft/SEND MIME descriptor match, SEND no blind resend.
3. Prompt semantic boundary: attachment bytes/content/local path never enter LLM Prompt/Context/Evidence.
4. Prompt Catalog is generated from source artifacts; G00 requires text/language/case/split parity.
5. Experiment manifests contain pre-registered hypothesis, stop conditions, and adoption criteria.
6. Candidate comparisons use deterministic counterbalanced ordering with recorded seed where applicable.

## Before any model run

Run `python experiments/runner/r84_pack_validator.py` and require zero issues, then complete the independent G00 human sample review.
